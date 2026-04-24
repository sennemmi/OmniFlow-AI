from pydantic import BaseModel


class SystemStatsSchema(BaseModel):
    """系统统计数据结构"""
    cpu_usage: float
    memory_usage: float