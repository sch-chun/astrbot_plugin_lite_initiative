#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - LLM 工具模块
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import llm_tool
from astrbot.api.event import AstrMessageEvent


class LLMFunctions:
    """LLM 函数工具集，供 AI 调用"""
    
    def __init__(self, plugin):
        self._plugin = plugin
    
    def _get_tz(self):
        return self._plugin._get_tz()
    
    def _list_triggers_for_session(self, session: str = "") -> List[dict]:
        return self._plugin._list_triggers_for_session(session)
    
    def _format_time_delta(self, seconds: float) -> str:
        from utils import _format_time_delta
        return _format_time_delta(seconds)
    
    @llm_tool(name="list_triggers")
    async def list_triggers(self, event: AstrMessageEvent, session: str = "") -> str:
        """列出当前所有待执行的触发器"""
        tlist = self._list_triggers_for_session(session)
        if not tlist:
            return "当前没有待执行的触发器。"

        now_ts = time.time()
        lines = [f"当前共有 {len(tlist)} 个触发器："]
        for i, t in enumerate(tlist, 1):
            fire_dt = datetime.fromtimestamp(t["fire_at_unix"])
            tz = self._get_tz()
            try:
                import zoneinfo
                if tz:
                    fire_str = fire_dt.astimezone(zoneinfo.ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    fire_str = fire_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                fire_str = fire_dt.strftime("%Y-%m-%d %H:%M:%S")
            remaining = t["fire_at_unix"] - now_ts
            status = "⚠️ 已过期" if remaining <= 0 else f"⏳ {self._format_time_delta(remaining)}后触发"
            sid = t.get("session") or "当前"
            src_name = t.get("source", "unknown")
            use_agent = t.get("use_agent", True)
            extra_prompt_preview = (t.get("extra_prompt") or "无")[:30]
            lines.append(
                f"{i}. [{t['trigger_id']}] 会话={sid} | "
                f"触发时间={fire_str} ({status}) | 来源={src_name} | "
                f"agent={use_agent} | 提示词={extra_prompt_preview}"
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
        source: str = "manual",
    ) -> str:
        """创建一个新的触发器"""
        if not session:
            session = event.unified_msg_origin

        if self._plugin._check_sleep_hours(fire_at_unix):
            now_ts = time.time()
            remaining = fire_at_unix - now_ts
            if remaining > 0:
                sleep_end = self._plugin._calc_sleep_end_unix()
                if sleep_end and sleep_end < fire_at_unix:
                    pass
                else:
                    return "❌ 创建失败：触发时间落在睡眠时段内，触发器会被直接丢弃。请在睡眠时段外创建。"
            else:
                return "❌ 创建失败：触发时间已过期。"

        t = self._plugin._create_trigger_internal(
            fire_at_unix=fire_at_unix,
            session=session,
            extra_prompt=extra_prompt,
            use_agent=use_agent,
            source=source,
        )
        if not t:
            return "❌ 创建触发器失败，请检查参数或触发时间。"
        fire_str = datetime.fromtimestamp(fire_at_unix).strftime("%Y-%m-%d %H:%M:%S")
        return f"✅ 触发器已创建：ID={t.trigger_id}，触发时间={fire_str}，会话={session}"

    @llm_tool(name="delete_trigger")
    async def delete_trigger(self, event: AstrMessageEvent, trigger_id: str) -> str:
        """删除一个已有的触发器"""
        if self._plugin._delete_trigger_internal(trigger_id):
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
        t = self._plugin._update_trigger_internal(
            trigger_id=trigger_id,
            fire_at_unix=fire_at_unix,
            extra_prompt=extra_prompt,
            use_agent=use_agent,
        )
        if not t:
            return f"❌ 更新失败：未找到触发器 {trigger_id} 或新触发时间在睡眠时段内。"
        fire_str = datetime.fromtimestamp(t.fire_at_unix).strftime("%Y-%m-%d %H:%M:%S")
        return f"✅ 触发器 {trigger_id} 已更新：触发时间={fire_str}，agent={t.use_agent}，提示词长度={len(t.extra_prompt)}"
