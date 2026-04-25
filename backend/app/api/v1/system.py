"""
系统监控 API
路由层 - 只负责路由定义和参数解析
"""

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.service.system_stats import SystemStatsService
from app.core.response import ResponseModel
from app.core.database import get_session

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
    # Pipeline 统计字段
    total_pipelines: int = Field(
        default=0,
        description="流水线总数",
        example=100
    )
    running_pipelines: int = Field(
        default=0,
        description="运行中流水线数量",
        example=5
    )
    completed_pipelines: int = Field(
        default=0,
        description="已完成流水线数量",
        example=85
    )
    failed_pipelines: int = Field(
        default=0,
        description="失败流水线数量",
        example=10
    )
    avg_duration: float = Field(
        default=None,
        description="平均耗时（秒）",
        example=120.5
    )


@router.get(
    "/system/stats",
    response_model=ResponseModel,
    summary="获取系统统计信息",
    description="""
    获取服务器实时的 CPU 使用率、内存占用情况和 Pipeline 统计数据。

    返回数据说明：
    - **cpu_usage**: CPU 使用率百分比（0-100）
    - **memory_usage**: 内存使用率百分比（0-100）
    - **total_pipelines**: 流水线总数
    - **running_pipelines**: 运行中流水线数量
    - **completed_pipelines**: 已完成流水线数量
    - **failed_pipelines**: 失败流水线数量
    - **avg_duration**: 平均耗时（秒）

    适用于：
    - 系统监控面板
    - 资源使用趋势分析
    - 告警阈值判断
    """,
    response_description="系统 CPU、内存使用率和 Pipeline 统计"
)
async def get_system_stats(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    获取服务器实时 CPU 使用率、内存占用情况和 Pipeline 统计数据
    """
    request_id = getattr(request.state, "request_id", None)
    try:
        stats = await SystemStatsService.collect_stats(session)
        return ResponseModel(
            success=True,
            data=SystemStatsData(
                cpu_usage=stats.cpu_usage,
                memory_usage=stats.memory_usage,
                total_pipelines=stats.total_pipelines,
                running_pipelines=stats.running_pipelines,
                completed_pipelines=stats.completed_pipelines,
                failed_pipelines=stats.failed_pipelines,
                avg_duration=stats.avg_duration
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
