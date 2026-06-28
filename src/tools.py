"""
LiteInitiative - LLM 工具模块（类方式）
"""
from __future__ import annotations

import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Optional

from astrbot.api import FunctionTool
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext


_plugin: Optional[Any] = None


def _get_plugin():
    if _plugin is None:
        raise RuntimeError("Plugin not initialized")
    return _plugin


from .time_utils import _get_now_tz, _parse_trigger_time, _is_in_sleep_hours, _format_time_delta
from .data_types import Trigger


def _list_for_session(session: str = "") -> list[dict]:
    tlist = []
    for t in _get_plugin()._triggers.values():
        if not session or t.session == session:
            tlist.append(t.to_dict())
    tlist.sort(key=lambda x: x.get("fire_at_unix", 0))
    return tlist


def _format_trigger_list(session: str) -> str:
    tlist = _list_for_session(session)
    if not tlist:
        return "当前没有待执行的触发器。"
    now_ts = time.time()
    tz = _get_plugin()._config.get_tz()
    lines = [f"当前共有 {len(tlist)} 个触发器："]
    for i, t in enumerate(tlist, 1):
        fire_dt = datetime.fromtimestamp(t["fire_at_unix"])
        try:
            import zoneinfo
            if tz:
                fire_str = fire_dt.astimezone(zoneinfo.ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S")
            else:
                fire_str = fire_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            fire_str = fire_dt.strftime("%Y-%m-%d %H:%M:%S")
        remaining = t["fire_at_unix"] - now_ts
        status = "⚠️ 已过期" if remaining <= 0 else f"⏳ {_format_time_delta(remaining)}后触发"
        sid = t.get("session") or "当前"
        direct_send = t.get("direct_send", True)
        extra_preview = (t.get("extra_prompt") or "无")[:30]
        lines.append(
            f"{i}. [{t['trigger_id']}] 会话={sid} | "
            f"触发时间={fire_str} ({status}) | "
            f"direct_send={direct_send} | 提示词={extra_preview}"
        )
    return "\n".join(lines)


# ==================== 工具类定义 ====================

@dataclass
class ListTriggersTool(FunctionTool):
    """列出当前触发器"""
    plugin: Any = None
    name: str = "list_triggers"
    description: str = "列出当前所有的主动闲聊触发器（临时性任务，用户发新消息后可能被清空）。注意：要查看持久性定时任务（如闹钟、提醒），请使用 future_task 的相关查询功能。"
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "session": {"type": "string", "description": "会话ID，不填则默认为当前会话"}
        }
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs: Any) -> str:
        session = kwargs.get("session", "")
        event = context.context.event
        if not session:
            session = event.unified_msg_origin
        return _format_trigger_list(session)


@dataclass
class CreateTriggerTool(FunctionTool):
    """创建触发器"""
    plugin: Any = None
    name: str = "create_trigger"
    description: str = "创建一个临时的主动对话触发器。⚠️ 重要约束：此触发器用于 AI 在用户沉默时主动发起闲聊，属于'临时性'任务。一旦用户发送任何新消息，本会话下的此类触发器有可能被自动清空。如需创建持久性定时提醒、闹钟、周期性报告，请务必使用系统内置工具 future_task。适用场景：AI 判断用户情绪低落想主动关心、每日分析后决定分享有趣话题。不适用场景：用户明确说'明天8点叫我起床'、'每小时提醒我喝水'"
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "fire_at_str": {"type": "string", "description": "触发时间，支持格式：'HH:MM:SS'(今天，若已过则次日)、'After HH:MM:SS'(相对时间)、'YYYY-MM-DD HH:MM:SS'(绝对时间)"},
            "session": {"type": "string", "description": "会话ID，不填则默认为当前会话"},
            "extra_prompt": {"type": "string", "description": "触发器触发时 AI 用来生成主动消息的话术指令，请详细描述要说什么、语气风格、是否需要用到 Agent 能力等"},
            "direct_send": {"type": "boolean", "description": "为 True 时将直接发送 extra_prompt 原文给用户，相当于定时留言，对于简单主动发送单次消息可以减少一次 AI 调用，节约开销。**请务必注意**：此项为 False 时，extra_prompt 是给 AI 看的；为 True 时，是直接给*用户*看的，注意区分话术和语气"}
        },
        "required": ["fire_at_str"]
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs: Any) -> str:
        fire_at_str = kwargs.get("fire_at_str")
        if fire_at_str is None:
            return "❌ 缺少必填参数 fire_at_str"
        session = kwargs.get("session", "")
        extra_prompt = kwargs.get("extra_prompt", "")
        direct_send = kwargs.get("direct_send", False)

        # 获取插件实例和配置
        plugin = self.plugin
        config = plugin._config
        triggers = plugin._triggers
        storage = plugin._storage
        lock = plugin._lock

        # 从 context 获取事件对象以提取会话 ID（如未提供 session）
        event = context.context.event
        if not session:
            session = event.unified_msg_origin

        tz = config.get_tz()
        now = _get_now_tz(tz)

        fire_at_unix = _parse_trigger_time(fire_at_str, now, tz)
        if fire_at_unix is None:
            return f"❌ 创建失败：无法解析时间字符串 '{fire_at_str}'。"

        # 检查睡眠时段
        fire_dt = datetime.fromtimestamp(fire_at_unix)
        if _is_in_sleep_hours(fire_dt, config.get_sleep_hours()):
            return f"❌ 创建失败：触发时间在睡眠时段内（{config.get_sleep_hours()}）。"

        # 检查最小延迟
        min_delay = config.get_min_trigger_delay()
        if min_delay > 0:
            delay = fire_at_unix - time.time()
            if delay < min_delay:
                return (
                    f"❌ 创建失败：触发器必须至少延迟 {min_delay} 秒，"
                    f"当前延迟仅 {delay:.0f} 秒。请使用 `send_message_to_user` 工具直接发送。"
                )

        async with lock:
            max_n = config.get_max_triggers()
            session_triggers = _list_for_session(session)
            if len(session_triggers) >= max_n:
                return f"❌ 创建失败：当前会话已达上限（{max_n} 个）。\n\n{_format_trigger_list(session)}\n\n💡 请先删除旧触发器再重试。"

            t = Trigger(
                fire_at_unix=fire_at_unix,
                session=session,
                extra_prompt=extra_prompt,
                direct_send=direct_send,
            )
            triggers[t.trigger_id] = t
            plugin._enforce_max_triggers()
            storage.save_triggers(triggers)

        fire_dt = datetime.fromtimestamp(fire_at_unix)
        return f"✅ 触发器已创建：ID={t.trigger_id}，时间={fire_dt.strftime('%Y-%m-%d %H:%M:%S')}，会话={session}"

@dataclass
class DeleteTriggerTool(FunctionTool):
    """删除触发器"""
    plugin: Any = None
    name: str = "delete_trigger"
    description: str = "删除一个指定的主动闲聊触发器。注意：此操作仅影响临时性的主动闲聊触发器，不影响 future_task 创建的持久任务。"
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "trigger_id": {"type": "string", "description": "要删除的触发器 ID，可通过 list_triggers 获取"}
        },
        "required": ["trigger_id"]
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs: Any) -> str:
        trigger_id = kwargs.get("trigger_id")
        if not trigger_id:
            return "❌ 缺少必填参数 trigger_id"
        plugin = self.plugin
        async with plugin._lock:
            if trigger_id in plugin._triggers:
                del plugin._triggers[trigger_id]
                plugin._storage.save_triggers(plugin._triggers)
                return f"✅ 触发器 {trigger_id} 已删除。"
        return f"❌ 未找到触发器 {trigger_id}。"

@dataclass
class UpdateTriggerTool(FunctionTool):
    """更新触发器"""
    plugin: Any = None
    name: str = "update_trigger"
    description: str = "更新一个已有的主动闲聊触发器的属性。仅适用于临时性的主动闲聊触发器。如需修改持久任务，请使用 future_task 工具。"
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "trigger_id": {"type": "string", "description": "要更新的触发器 ID"},
            "fire_at_unix": {"type": "number", "description": "新的触发时间戳（Unix 秒），不填则保持不变"},
            "extra_prompt": {"type": "string", "description": "新的触发话术指令，不填则保持不变"},
            "direct_send": {"type": "boolean", "description": "为 True 时直接发送原文，为 False 时走 Agent 能力生成，不填则保持不变"}
        },
        "required": ["trigger_id"]
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs: Any) -> str:
        trigger_id = kwargs.get("trigger_id")
        if not trigger_id:
            return "❌ 缺少必填参数 trigger_id"
        fire_at_unix = kwargs.get("fire_at_unix")
        extra_prompt = kwargs.get("extra_prompt")
        direct_send = kwargs.get("direct_send")

        plugin = self.plugin
        async with plugin._lock:
            t = plugin._triggers.get(trigger_id)
            if not t:
                return f"❌ 未找到触发器 {trigger_id}"
            if fire_at_unix is not None:
                fire_dt = datetime.fromtimestamp(fire_at_unix)
                if _is_in_sleep_hours(fire_dt, plugin._config.get_sleep_hours()):
                    return "❌ 新触发时间在睡眠时段内。"
                t.fire_at_unix = fire_at_unix
            if extra_prompt is not None:
                t.extra_prompt = extra_prompt
            if direct_send is not None:
                t.direct_send = direct_send
            plugin._storage.save_triggers(plugin._triggers)
        fire_str = datetime.fromtimestamp(t.fire_at_unix).strftime("%Y-%m-%d %H:%M:%S")
        return f"✅ 触发器 {trigger_id} 已更新：时间={fire_str}，direct_send={t.direct_send}"
