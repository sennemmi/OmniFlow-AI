from typing import Optional
from pydantic import BaseModel, Field


class SystemStatsSchema(BaseModel):
    """系统统计数据结构"""
    cpu_usage: float = Field(description="CPU 使用率")
    memory_usage: float = Field(description="内存使用率")
    # Pipeline 统计字段
    total_pipelines: int = Field(default=0, description="流水线总数")
    running_pipelines: int = Field(default=0, description="运行中流水线数量")
    completed_pipelines: int = Field(default=0, description="已完成流水线数量")
    failed_pipelines: int = Field(default=0, description="失败流水线数量")
    avg_duration: Optional[float] = Field(default=None, description="平均耗时（秒）")