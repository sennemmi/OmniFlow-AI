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


class SystemStatsResponse(BaseModel):
    """系统资源统计响应模型"""
    cpu_percent: float = Field(..., description="CPU 使用率 (百分比，0-100)", ge=0, le=100)
    memory_percent: float = Field(..., description="内存使用率 (百分比，0-100)", ge=0, le=100)
    memory_used_mb: int = Field(..., description="已使用内存 (MB)")
    memory_total_mb: int = Field(..., description="总内存 (MB)")
    disk_percent: float = Field(..., description="磁盘使用率 (百分比，0-100)", ge=0, le=100)
    disk_used_gb: float = Field(..., description="已使用磁盘空间 (GB)")
    disk_total_gb: float = Field(..., description="总磁盘空间 (GB)")
    uptime_seconds: int = Field(..., description="服务运行时间 (秒)")


class HealthCheckResponse(BaseModel):
    """健康检查响应模型"""
    status: str = Field(..., description="健康状态 (healthy/degraded/unhealthy)")
    version: str = Field(..., description="服务版本")
    sandbox_test: bool = Field(default=False, description="沙箱测试功能是否启用")
    timestamp: str = Field(..., description="检查时间戳")


class DatabaseStatusResponse(BaseModel):
    """数据库状态响应模型"""
    connected: bool = Field(..., description="数据库是否连接成功")
    database_url: str = Field(..., description="数据库连接URL（已脱敏）")
    pool_size: int = Field(..., description="连接池大小")
    active_connections: int = Field(..., description="当前活跃连接数")


class DetailedHealthCheck(BaseModel):
    """单项健康检查结果"""
    status: str = Field(..., description="状态 (healthy/degraded/unhealthy)")


class ServiceCheck(DetailedHealthCheck):
    """服务状态检查"""
    version: str = Field(..., description="服务版本")
    uptime_seconds: int = Field(..., description="运行时间（秒）")


class DatabaseCheck(DetailedHealthCheck):
    """数据库状态检查"""
    connected: bool = Field(..., description="是否已连接")


class ResourcesCheck(DetailedHealthCheck):
    """资源状态检查"""
    cpu_percent: float = Field(..., description="CPU使用率")
    memory_percent: float = Field(..., description="内存使用率")
    disk_percent: float = Field(..., description="磁盘使用率")


class DetailedHealthResponse(BaseModel):
    """综合健康检查响应模型"""
    overall_status: str = Field(..., description="整体状态 (healthy/degraded/unhealthy)")
    checks: dict = Field(..., description="各项检查结果")
    timestamp: str = Field(..., description="检查时间戳")