from pydantic import BaseModel
from typing import List, Optional


class HealthComponentStatus(BaseModel):
    """Pydantic 数据模型，定义单个组件状态的字段结构"""
    name: str
    status: str  # up/warning/down
    response_time_ms: Optional[int] = None
    disk_usage_percent: Optional[float] = None
    free_space_gb: Optional[float] = None
    memory_usage_percent: Optional[float] = None
    available_mb: Optional[float] = None
    error_message: Optional[str] = None


class OverallHealthStatus(BaseModel):
    """Pydantic 数据模型，定义整体健康状态的字段结构，包含汇总信息和组件列表"""
    overall_health_score: int
    component_count: int
    healthy_component_count: int
    degraded_component_count: int
    down_component_count: int
    components: List[HealthComponentStatus]
    error: Optional[str] = None