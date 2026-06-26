#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - 配置读取模块
"""

from __future__ import annotations

from typing import Any, Optional
from time_utils import _parse_time_str


class ConfigReader:
    """插件配置读取器"""
    
    def __init__(self, cfg: Any):
        self.cfg = cfg
    
    def _get(self, *keys, default=None):
        """递归读取配置项"""
        node = self.cfg
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                node = getattr(node, key, None)
            if node is None:
                return default
        return node if node is not None else default
    
    def get_tz(self) -> Optional[str]:
        return self._get("timezone") or None
    
    def get_sleep_hours(self) -> str:
        return self._get("sleep_hours") or ""
    
    def get_max_triggers(self) -> int:
        return int(self._get("max_triggers") or 20)
    
    def get_decision_timeout(self) -> int:
        return int(self._get("timeout_decision", "decision_timeout_seconds") or 300)
    
    def get_decision_prompt(self) -> str:
        return self._get("timeout_decision", "decision_prompt") or "你是一个主动闲聊决策助手。"
    
    def get_decision_max_history(self) -> int:
        return int(self._get("timeout_decision", "decision_max_history_messages") or 20)
    
    def get_daily_analysis_times(self):
        raw = self._get("daily_analysis", "daily_analysis_times") or "09:00,14:00,21:00"
        result = []
        for part in raw.split(","):
            part = part.strip()
            t = _parse_time_str(part)
            if t:
                result.append(t)
        return result
    
    def get_daily_analysis_prompt(self) -> str:
        return self._get("daily_analysis", "daily_analysis_prompt") or "你是一个对话分析助手。"
    
    def get_daily_analysis_max_history(self) -> int:
        return int(self._get("daily_analysis", "daily_analysis_max_history_messages") or 50)
    
    def get_inactive_threshold_hours(self) -> int:
        return int(self._get("daily_analysis", "inactive_threshold_hours") or 24)
    
    def get_inject_date_tip(self) -> bool:
        return bool(self._get("inject_date_tip", True))
    
    def get_trigger_persist(self) -> bool:
        return bool(self._get("trigger_persist", True))
