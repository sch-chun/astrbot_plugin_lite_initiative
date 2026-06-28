"""
LiteInitiative - 时间工具模块
"""
from __future__ import annotations

import re
from datetime import datetime, time as dt_time
from typing import Optional


def _get_now_tz(tz_name: str | None) -> datetime:
    """获取带时区的当前时间"""
    if tz_name:
        try:
            import zoneinfo
            return datetime.now(zoneinfo.ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def _parse_time_str(s: str) -> Optional[tuple[int, int]]:
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
    """
    解析触发时间字符串，返回 UNIX 时间戳（秒）。

    支持的格式：
    - 绝对日期时间：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD HH:MM
    - 绝对时间：HH:MM:SS（当天或次日）
    - 相对时间：After HH:MM:SS（表示 HH 小时 MM 分钟 SS 秒后）
    - 相对时间：After X hours Y minutes Z seconds（数字和单位，可省略部分）
    """
    raw = raw.strip()
    if not raw:
        return None

    # 1. 解析绝对日期时间
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            if tz:
                import zoneinfo
                dt = dt.replace(tzinfo=zoneinfo.ZoneInfo(tz))
            return dt.timestamp()
        except ValueError:
            continue

    # 2. 解析绝对时间 HH:MM:SS（当天，若已过则次日）
    m = re.match(r"^(\d{1,2}):([0-5]\d):([0-5]\d)$", raw)
    if m:
        h, minute, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        target = now.replace(hour=h, minute=minute, second=s, microsecond=0)
        if target <= now:
            target = target.replace(day=target.day + 1)
        return target.timestamp()

    # 3. 解析相对时间（After ...）
    raw_lower = raw.lower()
    if raw_lower.startswith("after "):
        # 3.1 After HH:MM:SS
        m = re.match(r"^after\s+(\d{1,2}):([0-5]\d):([0-5]\d)$", raw_lower)
        if m:
            h, minute, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
            delta = h * 3600 + minute * 60 + s
            return now.timestamp() + delta

        # 3.2 After X hours Y minutes Z seconds（顺序任意，单位可单复数）
        hours = minutes = seconds = 0
        m_h = re.search(r'(\d+)\s*hours?', raw_lower)
        if m_h:
            hours = int(m_h.group(1))
        m_m = re.search(r'(\d+)\s*minutes?', raw_lower)
        if m_m:
            minutes = int(m_m.group(1))
        m_s = re.search(r'(\d+)\s*seconds?', raw_lower)
        if m_s:
            seconds = int(m_s.group(1))
        if hours or minutes or seconds:
            delta = hours * 3600 + minutes * 60 + seconds
            return now.timestamp() + delta

    # 无法解析
    return None


def calc_sleep_end_unix(sleep_hours: str, tz_name: str | None) -> Optional[float]:
    """计算睡眠时段结束时间的 UNIX 时间戳"""
    now = _get_now_tz(tz_name)
    if not sleep_hours or "-" not in sleep_hours:
        return None
    parts = sleep_hours.split("-", 1)
    t_end = _parse_time_str(parts[1])
    if not t_end:
        return None
    end = now.replace(hour=t_end[0], minute=t_end[1], second=0, microsecond=0)
    if end <= now:
        end = end.replace(day=end.day + 1)
    return end.timestamp()
