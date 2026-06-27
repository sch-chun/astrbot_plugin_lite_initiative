#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - LLM 工具模块

⚠️ 重要：@llm_tool 装饰的函数不能是类方法！
AstrBot 的 tool executor 以 handler(event, **kwargs) 的方式调用工具，
如果函数是类方法（有 self 参数），event 会被错误地当作 self 传入。
所以所有工具函数都必须是独立函数，通过闭包持有 plugin 引用。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import List, Optional

from astrbot.api import llm_tool
from astrbot.api.event import AstrMessageEvent

# 模块级插件引用（在 LLMFunctions.__init__ 中设置）
_plugin = None


def _config():
    return _plugin._config


def _triggers():
    return _plugin._triggers


def _storage():
    return _plugin._storage


def _lock():
    return _plugin._lock


def _list_for_session(session: str = "") -> List[dict]:
    tlist = []
    for t in _triggers().values():
        if not session or t.session == session:
            tlist.append(t.to_dict())
    tlist.sort(key=lambda x: x.get("fire_at_unix", 0))
    return tlist


def _check_sleep(fire_at_unix: float) -> bool:
    from .time_utils import _get_now_tz, _is_in_sleep_hours
    tz = _config().get_tz()
    now = _get_now_tz(tz)
    fire_dt = datetime.fromtimestamp(fire_at_unix, tz=now.tzinfo if tz else None)
    return _is_in_sleep_hours(fire_dt, _config().get_sleep_hours())


def _format_trigger_list(session: str) -> str:
    """格式化指定会话的触发器列表"""
    from .time_utils import _get_now_tz, _format_time_delta
    tlist = _list_for_session(session)
    if not tlist:
        return "当前没有待执行的触发器。"
    now_ts = time.time()
    tz = _config().get_tz()
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
        use_agent = t.get("use_agent", True)
        extra_preview = (t.get("extra_prompt") or "无")[:30]
        lines.append(
            f"{i}. [{t['trigger_id']}] 会话={sid} | "
            f"触发时间={fire_str} ({status}) | "
            f"agent={use_agent} | 提示词={extra_preview}"
        )
    return "\n".join(lines)


# ═══════════════════════ 独立的 @llm_tool 函数 ═══════════════════════

@llm_tool(name="list_triggers")
async def list_triggers(event: AstrMessageEvent, session: str = "") -> str:
    """列出当前所有的主动闲聊触发器（临时性任务，用户发新消息后可能被清空）。

    注意：要查看持久性定时任务（如闹钟、提醒），请使用 future_task 的相关查询功能。

    Args:
        session(string): 会话ID，不填则默认为当前会话
    """
    if not session:
        session = event.unified_msg_origin
    return _format_trigger_list(session)


@llm_tool(name="create_trigger")
async def create_trigger(
    event: AstrMessageEvent,
    fire_at_str: str,
    session: str = "",
    extra_prompt: str = "",
    use_agent: bool = True,
) -> str:
    """创建一个临时的主动对话触发器。

    ⚠️ 重要约束：此触发器用于 AI 在用户沉默时主动发起闲聊，属于"临时性"任务。
    一旦用户发送任何新消息，本会话下的此类触发器有可能被自动清空。
    如需创建持久性定时提醒、闹钟、周期性报告，请务必使用系统内置工具 future_task。

    适用场景：AI 判断用户情绪低落想主动关心、每日分析后决定分享有趣话题。
    不适用场景：用户明确说"明天8点叫我起床"、"每小时提醒我喝水"。

    Args:
        fire_at_str(string): 触发时间，支持格式：'HH:MM:SS'(今天，若已过则次日)、'After HH:MM:SS'(相对时间)、'YYYY-MM-DD HH:MM:SS'(绝对时间)
        session(string): 会话ID，不填则默认为当前会话
        extra_prompt(string): 触发器触发时 AI 用来生成主动消息的话术指令，请详细描述要说什么、语气风格、是否需要用到 Agent 能力等
        use_agent(boolean): 是否使用 Agent 能力执行触发器，默认开启
    """
    from .time_utils import _get_now_tz, _parse_trigger_time, calc_sleep_end_unix
    from .data_types import Trigger

    if not session:
        session = event.unified_msg_origin

    # 获取当前时间和时区
    tz = _config().get_tz()
    now = _get_now_tz(tz)
    
    # 解析时间字符串
    fire_at_unix = _parse_trigger_time(fire_at_str, now, tz)
    if fire_at_unix is None:
        return f"❌ 创建失败：无法解析时间字符串 '{fire_at_str}'。请使用 'HH:MM:SS'、'YYYY-MM-DD HH:MM:SS'、'After HH:MM:SS' 或 'After X hours Y minutes Z seconds' 格式。"

    # 检查是否在睡眠时段
    if _check_sleep(fire_at_unix):
        sleep_end = calc_sleep_end_unix(_config().get_sleep_hours(), tz)
        if sleep_end and sleep_end < fire_at_unix:
            pass  # 已过睡眠结束时间，可以
        else:
            return f"❌ 创建失败：触发时间落在睡眠时段内（{_config().get_sleep_hours()}），请选择其他时间。"

    async with _lock():

        # 上限检查
        max_n = _config().get_max_triggers()

        # 获取当前会话触发器列表
        session_triggers = _list_for_session(session)
        if len(session_triggers) >= max_n:
            list_output = _format_trigger_list(session)
            
            # 格式化
            return (
                f"❌ 创建失败：当前会话已达到触发器上限（{max_n} 个）。\n\n"
                f"{list_output}\n\n"
                f"💡 请先使用 `delete_trigger` 删除不需要的旧触发器，然后重试创建。"
            )
        t = Trigger(
            fire_at_unix=fire_at_unix,
            session=session,
            extra_prompt=extra_prompt,
            use_agent=use_agent,
        )
        _triggers()[t.trigger_id] = t
        _plugin._enforce_max_triggers()
        _storage().save_triggers(_triggers())

    fire_dt = datetime.fromtimestamp(fire_at_unix)
    fire_str = fire_dt.strftime("%Y-%m-%d %H:%M:%S")
    return f"✅ 触发器已创建：ID={t.trigger_id}，触发时间={fire_str}，会话={session}"


@llm_tool(name="delete_trigger")
async def delete_trigger(event: AstrMessageEvent, trigger_id: str) -> str:
    """删除一个指定的主动闲聊触发器。

    注意：此操作仅影响临时性的主动闲聊触发器，不影响 future_task 创建的持久任务。

    Args:
        trigger_id(string): 要删除的触发器 ID，可通过 list_triggers 获取
    """
    async with _lock():
        if trigger_id in _triggers():
            del _triggers()[trigger_id]
            _storage().save_triggers(_triggers())
            return f"✅ 触发器 {trigger_id} 已成功删除。"
    return f"❌ 未找到触发器 {trigger_id}，请使用 list_triggers 确认 ID。"


@llm_tool(name="update_trigger")
async def update_trigger(
    event: AstrMessageEvent,
    trigger_id: str,
    fire_at_unix: Optional[float] = None,
    extra_prompt: Optional[str] = None,
    use_agent: Optional[bool] = None,
) -> str:
    """更新一个已有的主动闲聊触发器的属性。

    仅适用于临时性的主动闲聊触发器。如需修改持久任务，请使用 future_task 工具。

    Args:
        trigger_id(string): 要更新的触发器 ID
        fire_at_unix(number): 新的触发时间戳（Unix 秒），不填则保持不变
        extra_prompt(string): 新的触发话术指令，不填则保持不变
        use_agent(boolean): 是否使用 Agent 能力执行，不填则保持不变
    """
    async with _lock():
        t = _triggers().get(trigger_id)
        if not t:
            return f"❌ 更新失败：未找到触发器 {trigger_id}"
        if fire_at_unix is not None:
            if _check_sleep(fire_at_unix):
                return "❌ 更新失败：新触发时间在睡眠时段内。"
            t.fire_at_unix = fire_at_unix
        if extra_prompt is not None:
            t.extra_prompt = extra_prompt
        if use_agent is not None:
            t.use_agent = use_agent
        _storage().save_triggers(_triggers())

    fire_str = datetime.fromtimestamp(t.fire_at_unix).strftime("%Y-%m-%d %H:%M:%S")
    return f"✅ 触发器 {trigger_id} 已更新：触发时间={fire_str}，agent={t.use_agent}，提示词长度={len(t.extra_prompt)}"


# ═══════════════════════ 注册辅助 ═══════════════════════

class LLMFunctions:
    """
    LLM 函数工具集 - 用于注册独立函数到 AstrBot 工具管理器。

    ⚠️ 工具函数已改为模块级独立函数，不再绑在类方法上。
    这是为了兼容 AstrBot tool executor 的调用方式：handler(event, **kwargs)
    """

    def __init__(self, plugin):
        global _plugin
        _plugin = plugin

        # 注册所有工具函数
        self._register_tool("list_triggers")
        self._register_tool("create_trigger")
        self._register_tool("delete_trigger")
        self._register_tool("update_trigger")

    def _register_tool(self, func_name: str):
        """将模块级工具函数注册到 AstrBot"""
        import astrbot.api as api_module
        func = globals()[func_name]
        api_module.register_llm_tool(func)