"""时间与闰年工具：getCurrentTime / isLeapYear。

时间使用 `datetime.now()` 与 `zoneinfo`，跨平台且非硬编码；
闰年规则：能被 4 整除，且整百年必须能被 400 整除。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
    "GET_CURRENT_TIME_TOOL",
    "IS_LEAP_YEAR_TOOL",
    "get_current_time",
    "is_leap",
    "is_leap_year",
]

GET_CURRENT_TIME_TOOL = {
    "type": "function",
    "function": {
        "name": "getCurrentTime",
        "description": (
            "获取当前日期时间与 Unix 时间戳。timezone 传 local 使用本机时区，"
            "也可传 IANA 时区名（如 Asia/Shanghai、UTC）。format 控制可读格式，"
            "返回内容始终包含 ISO 8601 时间与时间戳。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "时区：local（默认）或 IANA 名称，例如 Asia/Shanghai。",
                },
                "format": {
                    "type": "string",
                    "enum": ["iso", "text", "timestamp"],
                    "description": "iso（默认）返回 ISO 8601；text 返回本地化文本；timestamp 额外强调秒级时间戳。",
                },
            },
            "additionalProperties": False,
        },
    },
}

IS_LEAP_YEAR_TOOL = {
    "type": "function",
    "function": {
        "name": "isLeapYear",
        "description": "判断指定年份是否为闰年（整百年需能被 400 整除）。",
        "parameters": {
            "type": "object",
            "properties": {
                "year": {
                    "type": "integer",
                    "description": "要判断的年份，例如 2000。",
                }
            },
            "required": ["year"],
            "additionalProperties": False,
        },
    },
}

_FORMATS = {"iso", "text", "timestamp"}


def is_leap(year: int) -> bool:
    """纯函数版本，供工具与示例脚本复用。"""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def is_leap_year(year) -> str:
    if isinstance(year, bool) or not isinstance(year, int):
        try:
            if isinstance(year, str) and year.strip():
                year = int(year.strip())
            else:
                raise ValueError
        except (TypeError, ValueError):
            return "isLeapYear 执行失败：year 必须是整数。"
    return f"{year} 年是闰年。" if is_leap(year) else f"{year} 年不是闰年。"


def get_current_time(timezone: str = "local", format: str = "iso") -> str:
    if format not in _FORMATS:
        return f"getCurrentTime 执行失败：format 必须是 {'/'.join(sorted(_FORMATS))}。"

    zone_name = (timezone or "local").strip()
    if zone_name.lower() in {"local", ""}:
        now = datetime.now().astimezone()
    else:
        try:
            now = datetime.now(ZoneInfo(zone_name))
        except (ZoneInfoNotFoundError, ValueError, OSError):
            return (
                f"getCurrentTime 执行失败：未知时区 {zone_name!r}。"
                "请使用 local 或 IANA 时区名（如 Asia/Shanghai、UTC）。"
            )

    stamp = int(now.timestamp())
    iso = now.isoformat(timespec="seconds")
    if format == "timestamp":
        return f"时间戳：{stamp}\nISO 时间：{iso}\n时区：{now.tzname() or zone_name}"
    if format == "text":
        text = now.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"当前时间：{text}\nISO 时间：{iso}\n"
            f"时区：{now.tzname() or zone_name}\n时间戳：{stamp}"
        )
    return f"当前时间：{iso}\n时间戳：{stamp}"
