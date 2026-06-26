#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - LLM 工具模块
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import List, Optional

from astrbot.api import llm_tool
from astrbot.api.event import AstrMessageEvent
from .time_utils import _get_now_tz, _format_time_delta, calc_sleep_end_unix, _is_in_sleep_hours, _parse_trigger_time


class LLMFunctions:
    """LLM 函数工具集"""

    def __init__(self, plugin):
        self._plugin = plugin

    @property
    def _triggers(self):
        return self._plugin._triggers

    @property
    def _config(self):
        return self._plugin._config

    @property
    def _storage(self):
        return self._plugin._storage

    @property
    def _lock(self):
        return self._plugin._lock

    def _list_for_session(self, session: str = "") -> List[dict]:
        tlist = []
        for t in self._triggers.values():
            if not session or t.session == session:
                tlist.append(t.to_dict())
        tlist.sort(key=lambda x: x.get("fire_at_unix", 0))
        return tlist

    def _check_sleep(self, fire_at_unix: float) -> bool:
        tz = self._config.get_tz()
        now = _get_now_tz(tz)
        fire_dt = datetime.fromtimestamp(fire_at_unix, tz=now.tzinfo if tz else None)
        return _is_in_sleep_hours(fire_dt, self._config.get_sleep_hours())

    @llm_tool(name="list_triggers")
    async def list_triggers(self, event: AstrMessageEvent, session: str = "") -> str:
        """【主动闲聊插件专用】列出当前所有的【主动闲聊触发器】（非持久任务）。

        注意：这里列出的触发器都是临时性的，用户发新消息后可能被清空。
        要查看持久性的定时任务（如闹钟、提醒），请使用 `future_task` 的相关查询功能。
        """
        if not session:
            session = event.unified_msg_origin
        return self._format_trigger_list(session)

    @llm_tool(name="create_trigger")
    async def create_trigger(
        self,
        event: AstrMessageEvent,
        fire_at_str: str,          # 自然语言时间字符串
        session: str = "",
        extra_prompt: str = "",
        use_agent: bool = True,
    ) -> str:
        """【主动闲聊插件专用】创建一个临时的主动对话触发器。

        ⚠️ 重要约束：
        - 此触发器用于 AI 在用户沉默时主动发起闲聊，属于“临时性”任务。
        - **一旦用户发送任何新消息，本会话下的此类触发器有可能被自动清空。**
        - 如果你需要创建“持久性”的定时提醒、闹钟、周期性报告（即使用户发消息也不会消失），
        请务必使用系统内置工具 `future_task`，而不是本工具。

        适用场景：
        - AI 判断用户情绪低落，想在 2 小时后主动关心一下。
        - 每日分析后决定在下午主动分享一个有趣的话题。

        不适用场景：
        - 用户明确说“明天 8 点叫我起床”、“每小时提醒我喝水” → 请用 `future_task`。

        时间格式支持：
        - "21:30:00" -> 今天 21:30，若已过则次日
        - "After 1 hour 30 minutes" -> 1.5 小时后
        - "2025-12-31 23:59:59" -> 指定日期时间

        Args:
        fire_at_str (str): **必填**。触发时间，支持自然语言格式：
            - "21:30:00" -> 今天21:30（若已过则次日）
            - "After 1 hour 30 minutes" -> 1小时30分钟后
            - "2025-12-31 23:59:59" -> 指定日期时间

        session (str): **选填**。会话ID，不填则默认为当前会话。一般无需修改。

        extra_prompt (str): **关键参数，最好填入详细内容**
            这是触发器触发时，AI 用来生成主动消息的 “话术指令”。
            请确保该字段能有效传达你的想法与交代的任务。
            表述清楚需要干什么，可以怎么干 (比如调用需要的 Agent 能力)。
        """
        if not session:
            session = event.unified_msg_origin

        # 获取当前时间和时区
        tz = self._config.get_tz()
        now = _get_now_tz(tz)
        
        # 解析时间字符串
        fire_at_unix = _parse_trigger_time(fire_at_str, now, tz)
        if fire_at_unix is None:
            return f"❌ 创建失败：无法解析时间字符串 '{fire_at_str}'。请使用 'HH:MM:SS'、'YYYY-MM-DD HH:MM:SS'、'After HH:MM:SS' 或 'After X hours Y minutes Z seconds' 格式。"

        # 检查是否在睡眠时段
        if self._check_sleep(fire_at_unix):
            sleep_end = calc_sleep_end_unix(self._config.get_sleep_hours(), tz)
            if sleep_end and sleep_end < fire_at_unix:
                pass  # 已过睡眠结束时间，可以
            else:
                return f"❌ 创建失败：触发时间落在睡眠时段内（{self._config.get_sleep_hours()}），请选择其他时间。"

        async with self._lock:

            # 上限检查
            max_n = self._config.get_max_triggers()

            # 获取当前会话触发器列表
            session_triggers = self._list_for_session(session)
            if len(session_triggers) >= max_n:
                list_output = self._format_trigger_list(session)
                
                # 格式化
                return (
                    f"❌ 创建失败：当前会话已达到触发器上限（{max_n} 个）。\n\n"
                    f"{list_output}\n\n"
                    f"💡 请先使用 `delete_trigger` 删除不需要的旧触发器，然后重试创建。"
                )
            from .data_types import Trigger  # 确保相对导入
            t = Trigger(
                fire_at_unix=fire_at_unix,
                session=session,
                extra_prompt=extra_prompt,
                use_agent=use_agent,
            )
            self._triggers[t.trigger_id] = t
            self._plugin._enforce_max_triggers()
            self._storage.save_triggers(self._triggers)

        fire_dt = datetime.fromtimestamp(fire_at_unix)
        fire_str = fire_dt.strftime("%Y-%m-%d %H:%M:%S")
        return f"✅ 触发器已创建：ID={t.trigger_id}，触发时间={fire_str}，会话={session}"

    @llm_tool(name="delete_trigger")
    async def delete_trigger(self, event: AstrMessageEvent, trigger_id: str) -> str:
        """【主动闲聊插件专用】删除一个【主动闲聊触发器】。

        注意：此操作仅影响临时性的主动闲聊触发器，不影响 `future_task` 创建的持久任务。
        """
        async with self._lock:
            if trigger_id in self._triggers:
                del self._triggers[trigger_id]
                self._storage.save_triggers(self._triggers)
                return f"✅ 触发器 {trigger_id} 已成功删除。"
        return f"❌ 未找到触发器 {trigger_id}，请使用 list_triggers 确认 ID。"

    @llm_tool(name="update_trigger")
    async def update_trigger(
        self,
        event: AstrMessageEvent,
        trigger_id: str,
        fire_at_unix: Optional[float] = None,
        extra_prompt: Optional[str] = None,
        use_agent: Optional[bool] = None,
    ) -> str:
        """【主动闲聊插件专用】修改一个已有的【主动闲聊触发器】。

        仅适用于临时性的主动闲聊触发器。如需修改持久任务，请使用 `future_task` 工具。
        """
        async with self._lock:
            t = self._triggers.get(trigger_id)
            if not t:
                return f"❌ 更新失败：未找到触发器 {trigger_id}"
            if fire_at_unix is not None:
                if self._check_sleep(fire_at_unix):
                    return "❌ 更新失败：新触发时间在睡眠时段内。"
                t.fire_at_unix = fire_at_unix
            if extra_prompt is not None:
                t.extra_prompt = extra_prompt
            if use_agent is not None:
                t.use_agent = use_agent
            self._storage.save_triggers(self._triggers)

        fire_str = datetime.fromtimestamp(t.fire_at_unix).strftime("%Y-%m-%d %H:%M:%S")
        return f"✅ 触发器 {trigger_id} 已更新：触发时间={fire_str}，agent={t.use_agent}，提示词长度={len(t.extra_prompt)}"

    def _format_trigger_list(self, session: str) -> str:
        """格式化指定会话的触发器列表（同步方法）"""
        tlist = self._list_for_session(session)
        if not tlist:
            return "当前没有待执行的触发器。"
        now_ts = time.time()
        tz = self._config.get_tz()
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
    