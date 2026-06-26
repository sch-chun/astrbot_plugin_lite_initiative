# tests/test_config.py
import pytest
from astrbot_plugin_lite_initiative.config import ConfigReader

def test_config_reader_defaults():
    cfg = ConfigReader({})
    assert cfg.get_tz() is None
    assert cfg.get_sleep_hours() == "23:00-08:00"
    assert cfg.get_max_triggers() == 20
    assert cfg.get_decision_timeout() == 300
    assert cfg.get_decision_prompt() == "你是一个主动闲聊决策助手。"
    assert cfg.get_decision_max_history() == 20
    assert cfg.get_daily_analysis_times() == [(9, 0), (14, 0), (21, 0)]  # 默认
    assert cfg.get_daily_analysis_prompt() == "你是一个对话分析助手。"
    assert cfg.get_daily_analysis_max_history() == 50
    assert cfg.get_inactive_threshold_hours() == 24
    assert cfg.get_inject_date_tip() is True
    assert cfg.get_trigger_persist() is True
    assert cfg.get_whitelist() == []

def test_config_reader_custom_values(sample_config_dict):
    cfg = ConfigReader(sample_config_dict)
    assert cfg.get_tz() == "Asia/Shanghai"
    assert cfg.get_sleep_hours() == "23:00-07:00"
    assert cfg.get_max_triggers() == 5
    assert cfg.get_decision_timeout() == 300
    assert cfg.get_decision_prompt() == "决策提示词"
    assert cfg.get_decision_max_history() == 20
    assert cfg.get_daily_analysis_times() == [(7, 0), (16, 0)]
    assert cfg.get_daily_analysis_prompt() == "分析提示词"
    assert cfg.get_daily_analysis_max_history() == 50
    assert cfg.get_inactive_threshold_hours() == 24
    assert cfg.get_inject_date_tip() is True
    assert cfg.get_trigger_persist() is True
    assert cfg.get_whitelist() == []

def test_whitelist_handling():
    cfg = ConfigReader({"whitelist": ["123", "456"]})
    assert cfg.get_whitelist() == ["123", "456"]
    cfg = ConfigReader({"whitelist": None})
    assert cfg.get_whitelist() == []
    