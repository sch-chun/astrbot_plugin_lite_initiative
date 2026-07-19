"""
LiteInitiative - 配置读取模块
"""
from __future__ import annotations

from typing import Any, Optional
from .time_utils import _parse_time_str

from astrbot.api import logger


class ConfigReader:
    """插件配置读取器"""
    
    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
    
    def get_tz(self) -> Optional[str]:
        return self.cfg.get("timezone")
    
    def get_sleep_hours(self) -> str:
        return self.cfg.get("sleep_hours", "23:00-08:00")
    
    def get_max_triggers(self) -> int:
        return int(self.cfg.get("max_triggers", 20))
    
    def get_decision_timeout(self) -> int:
        return int(self.cfg.get("decision_timeout_seconds", 300))
    
    def get_decision_prompt(self) -> str:
        return self.cfg.get("decision_prompt", "你是一个主动闲聊决策助手。")
    
    def get_daily_analysis_times(self) -> list:
        raw = self.cfg.get("daily_analysis_times", "07:00,16:00")
        result = []
        for part in raw.split(","):
            part = part.strip()
            t = _parse_time_str(part)
            if t:
                result.append(t)
        return result
    
    def get_daily_analysis_prompt(self) -> str:
        return self.cfg.get("daily_analysis_prompt", "你是一个对话分析助手。")
    
    def get_inactive_threshold_hours(self) -> int:
        return int(self.cfg.get("inactive_threshold_hours", 24))
    
    def get_inject_date_tip(self) -> bool:
        return bool(self.cfg.get("inject_date_tip", True))
    
    def get_trigger_persist(self) -> bool:
        return bool(self.cfg.get("trigger_persist", True))
    
    def get_whitelist(self) -> list:
        """获取白名单 ID 列表，返回 list"""
        return self.cfg.get("whitelist", []) or []
    
    def get_decision_provider(self) -> Optional[str]:
        """获取决策阶段使用的模型提供商 ID，若未配置则返回 None"""
        return self.cfg.get("decision_provider") or None

    def get_min_trigger_delay(self) -> int:
        return int(self.cfg.get("min_trigger_delay", 0))
    
    def get_suggest_direct_send(self) -> bool:
        return bool(self.cfg.get("suggest_direct_send", True))
    
    def get_suggest_direct_send_prompt(self) -> str:
        return self.cfg.get("suggest_direct_send_prompt", "")
    
    def get_decision_trigger_probability(self) -> float:
        """获取超时决策触发概率（%），若未配置则返回 100"""
        val = self.cfg.get("decision_trigger_probability", 100)
        try:
            return float(val)
        except (ValueError, TypeError):
            logger.warning(f"Invalid decision_trigger_probability value: {val}. Using default 100.0")
            return 100.0
