"""
时区工具模块
统一使用 UTC+8 时区
"""

from datetime import datetime
from zoneinfo import ZoneInfo

# 定义 UTC+8 时区
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def now() -> datetime:
    """获取当前 UTC+8 时间"""
    return datetime.now(TZ_SHANGHAI)


def now_iso() -> str:
    """获取当前 UTC+8 时间的 ISO 格式字符串"""
    return now().isoformat()


def now_str(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """获取当前 UTC+8 时间的格式化字符串"""
    return now().strftime(fmt)


def to_shanghai(dt: datetime) -> datetime:
    """将时间转换为 UTC+8 时区"""
    if dt.tzinfo is None:
        # 如果无时区信息，假设为 UTC
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ_SHANGHAI)
