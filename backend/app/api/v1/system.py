"""
系统监控 API
路由层 - 只负责路由定义和参数解析
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.service.system_stats import SystemStatsService
from app.core.response import ResponseModel

router = APIRouter()


class SystemStatsData(BaseModel):
    """系统统计数据"""
    cpu_usage: float = Field(
        ...,
        description="CPU 使用率 (百分比，0-100)",
        ge=0,
        le=100,
        example=45.5
    )
    memory_usage: float = Field(
        ...,
        description="内存使用率 (百分比，0-100)",
        ge=0,
        le=100,
        example=62.3
    )


@router.get(
    "/system/stats",
    response_model=ResponseModel,
    summary="获取系统统计信息",
    description="""
    获取服务器实时的 CPU 使用率和内存占用情况。

    返回数据说明：
    - **cpu_usage**: CPU 使用率百分比（0-100）
    - **memory_usage**: 内存使用率百分比（0-100）

    适用于：
    - 系统监控面板
    - 资源使用趋势分析
    - 告警阈值判断
    """,
    response_description="系统 CPU 和内存使用率"
)
async def get_system_stats(request: Request):
    """
    获取服务器实时 CPU 使用率和内存占用情况
    """
    request_id = getattr(request.state, "request_id", None)
    try:
        stats = SystemStatsService.collect_stats()
        return ResponseModel(
            success=True,
            data=SystemStatsData(
                cpu_usage=stats.cpu_usage,
                memory_usage=stats.memory_usage
            ).model_dump(),
            error=None,
            request_id=request_id
        )
    except Exception as e:
        return ResponseModel(
            success=False,
            data=None,
            error=str(e),
            request_id=request_id
        )
