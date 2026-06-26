#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - 工具函数模块
"""

from __future__ import annotations

import re
from datetime import datetime, time as dt_time
from typing import Optional, Tuple


def _get_now_tz(tz_name: str | None) -> datetime:
    """获取带时区的当前时间"""
    try:
        if tz_name:
            import zoneinfo
            try:
                return datetime.now(zoneinfo.ZoneInfo(tz_name))
            except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                pass
    except ImportError:
        try:
            from backports import zoneinfo
            return datetime.now(zoneinfo.ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def _parse_time_str(s: str) -> Optional[Tuple[int, int]]:
    """解析 HH:MM 格式的时间字符串"""
    s = s.strip()
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _is_in_sleep_hours(now: datetime, sleep_range: str) -> bool:
    """判断当前时间是否在睡眠时段内"""
    if not sleep_range or "-" not in sleep_range:
        return False
    parts = sleep_range.split("-", 1)
    t1 = _parse_time_str(parts[0])
    t2 = _parse_time_str(parts[1])
    if not t1 or not t2:
        return False
    start = dt_time(t1[0], t1[1])
    end = dt_time(t2[0], t2[1])
    current = now.time()
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _format_time_delta(seconds: float) -> str:
    """格式化时间差为中文描述"""
    if seconds < 0:
        return "0分钟"
    minutes = int(seconds / 60)
    hours = int(minutes / 60)
    days = int(hours / 24)
    if days > 0:
        rem_h = hours % 24
        if rem_h > 0:
            return f"{days}天{rem_h}小时"
        return f"{days}天"
    if hours > 0:
        rem_m = minutes % 60
        if rem_m > 0:
            return f"{hours}小时{rem_m}分钟"
        return f"{hours}小时"
    if minutes > 0:
        return f"{minutes}分钟"
    return "不到1分钟"


def _parse_trigger_time(raw: str, now: datetime, tz: Optional[str]) -> Optional[float]:
    """解析触发时间字符串，返回 UNIX 时间戳"""
    raw = raw.strip()
    if not raw:
        return None
    
    m_rel = re.match(r"^(\d{1,2}:\d{2}:\d{2})\s*后$", raw)
    if m_rel:
        secs_parts = m_rel.group(1).split(":")
        if len(secs_parts) == 3:
            secs = int(secs_parts[0]) * 3600 + int(secs_parts[1]) * 60 + int(secs_parts[2])
            return now.timestamp() + secs
    
    abs_time = None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
        try:
            abs_time = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    
    if abs_time:
        return abs_time.timestamp()
    
    t = _parse_time_str(raw)
    if t:
        target = now.replace(hour=t[0], minute=t[1], second=0, microsecond=0)
        if target <= now:
            target = target.replace(day=target.day + 1)
        return target.timestamp()
    
    return None
