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
from time_utils import _get_now_tz, _format_time_delta, calc_sleep_end_unix, _is_in_sleep_hours


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
        """列出当前所有待执行的触发器"""
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

    @llm_tool(name="create_trigger")
    async def create_trigger(
        self,
        event: AstrMessageEvent,
        fire_at_unix: float,
        session: str = "",
        extra_prompt: str = "",
        use_agent: bool = True,
    ) -> str:
        """创建一个新的触发器"""
        if not session:
            session = event.unified_msg_origin

        if self._check_sleep(fire_at_unix):
            now_ts = time.time()
            remaining = fire_at_unix - now_ts
            if remaining > 0:
                sleep_end = calc_sleep_end_unix(self._config.get_sleep_hours(), self._config.get_tz())
                if sleep_end and sleep_end < fire_at_unix:
                    pass
                else:
                    return "❌ 创建失败：触发时间落在睡眠时段内，触发器会被直接丢弃。请在睡眠时段外创建。"
            else:
                return "❌ 创建失败：触发时间已过期。"

        async with self._lock:
            from types import Trigger
            t = Trigger(
                fire_at_unix=fire_at_unix,
                session=session,
                extra_prompt=extra_prompt,
                use_agent=use_agent,
            )
            self._triggers[t.trigger_id] = t
            self._plugin._enforce_max_triggers()
            self._storage.save_triggers(self._triggers)

        fire_str = datetime.fromtimestamp(fire_at_unix).strftime("%Y-%m-%d %H:%M:%S")
        return f"✅ 触发器已创建：ID={t.trigger_id}，触发时间={fire_str}，会话={session}"

    @llm_tool(name="delete_trigger")
    async def delete_trigger(self, event: AstrMessageEvent, trigger_id: str) -> str:
        """删除一个已有的触发器"""
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
        """修改一个已有的触发器"""
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
