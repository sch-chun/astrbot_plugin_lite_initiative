# tests/test_time_utils.py
import time
from datetime import datetime, timedelta
import pytest
from astrbot_plugin_lite_initiative.time_utils import (
    _get_now_tz,
    _parse_time_str,
    _is_in_sleep_hours,
    _format_time_delta,
    _parse_trigger_time,
    calc_sleep_end_unix,
)

def test_parse_time_str():
    assert _parse_time_str("23:59") == (23, 59)
    assert _parse_time_str("00:00") == (0, 0)
    assert _parse_time_str("24:00") is None
    assert _parse_time_str("12:60") is None
    assert _parse_time_str("abc") is None

def test_get_now_tz():
    # 无时区返回本地时间
    now = _get_now_tz(None)
    assert isinstance(now, datetime)
    # 有效时区
    now_sh = _get_now_tz("Asia/Shanghai")
    assert now_sh.tzinfo is not None
    offset = now_sh.tzinfo.utcoffset(now_sh)
    assert offset is not None
    assert offset.total_seconds() == 28800  # UTC+8

def test_is_in_sleep_hours():
    # 测试不跨天
    now = datetime(2026, 1, 1, 2, 0, 0)
    assert _is_in_sleep_hours(now, "23:00-07:00") is True
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert _is_in_sleep_hours(now, "23:00-07:00") is False
    # 跨天
    now = datetime(2026, 1, 1, 23, 30, 0)
    assert _is_in_sleep_hours(now, "22:00-06:00") is True
    now = datetime(2026, 1, 1, 5, 30, 0)
    assert _is_in_sleep_hours(now, "22:00-06:00") is True
    now = datetime(2026, 1, 1, 10, 0, 0)
    assert _is_in_sleep_hours(now, "22:00-06:00") is False

def test_format_time_delta():
    assert _format_time_delta(0) == "不到1分钟"
    assert _format_time_delta(30) == "不到1分钟"
    assert _format_time_delta(60) == "1分钟"
    assert _format_time_delta(90) == "1分钟"  # 只显示分钟
    assert _format_time_delta(120) == "2分钟"
    assert _format_time_delta(3660) == "1小时1分钟"
    assert _format_time_delta(3600) == "1小时"
    assert _format_time_delta(86400) == "1天"
    assert _format_time_delta(90000) == "1天1小时"  # 25小时

def test_parse_trigger_time_absolute():
    now = datetime(2026, 1, 1, 12, 0, 0)
    # HH:MM:SS 当天
    ts = _parse_trigger_time("13:30:45", now, None)
    assert ts is not None
    dt = datetime.fromtimestamp(ts)
    assert dt.hour == 13 and dt.minute == 30 and dt.second == 45
    # 若已过则次日
    ts = _parse_trigger_time("11:00:00", now, None)
    assert ts is not None
    dt = datetime.fromtimestamp(ts)
    assert dt.day == now.day + 1
    # 绝对日期
    ts = _parse_trigger_time("2026-12-31 23:59:59", now, None)
    assert ts is not None
    dt = datetime.fromtimestamp(ts)
    assert dt.year == 2026 and dt.month == 12 and dt.day == 31

def test_parse_trigger_time_relative():
    now = datetime(2026, 1, 1, 12, 0, 0)
    # After HH:MM:SS
    ts = _parse_trigger_time("After 01:30:00", now, None)
    assert ts is not None
    assert ts == now.timestamp() + 5400
    # After X hours Y minutes
    ts = _parse_trigger_time("After 2 hours 15 minutes", now, None)
    assert ts is not None
    assert ts == now.timestamp() + 8100
    # 混合单复数
    ts = _parse_trigger_time("After 1 hour 0 minutes 30 seconds", now, None)
    assert ts is not None
    assert ts == now.timestamp() + 3630

def test_calc_sleep_end_unix():
    tz = "Asia/Shanghai"
    now = _get_now_tz(tz)
    end_ts = calc_sleep_end_unix("23:00-07:00", tz)
    assert end_ts is not None
    end_dt = datetime.fromtimestamp(end_ts, tz=now.tzinfo)
    # 应该是在7:00，如果当前时间大于7:00则次日
    if now.hour >= 7:
        assert end_dt.day == now.day + 1
    else:
        assert end_dt.day == now.day
    assert end_dt.hour == 7 and end_dt.minute == 0
    