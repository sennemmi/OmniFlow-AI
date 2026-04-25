"""
系统监控 API
路由层 - 只负责路由定义和参数解析
"""

from typing import Optional
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import func, select

from app.service.system_stats import SystemStatsService
from app.core.response import ResponseModel
from app.core.database import get_session
from app.models.pipeline import Pipeline, PipelineStage, PipelineStatus

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
    avg_duration: Optional[float] = Field(
        default=0.0,
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


class AnalyticsData(BaseModel):
    """系统分析数据"""
    success_rate: float = Field(
        default=0.0,
        description="成功率 (百分比，0-100)",
        ge=0,
        le=100,
        example=85.5
    )
    total_pipelines: int = Field(
        default=0,
        description="总流水线数",
        example=100
    )
    total_tokens_consumed: int = Field(
        default=0,
        description="总 Token 消耗数",
        example=1250403
    )
    avg_fix_count: float = Field(
        default=0.0,
        description="平均自动修复次数",
        example=0.42
    )
    avg_duration_ms: int = Field(
        default=0,
        description="平均耗时（毫秒）",
        example=15000
    )
    total_cost_usd: float = Field(
        default=0.0,
        description="总成本预估（美元）",
        example=12.5
    )


@router.get(
    "/system/analytics",
    response_model=ResponseModel,
    summary="获取系统分析统计",
    description="""
    获取全局成功率、Token 消耗、平均修复次数等分析数据。

    适用于：
    - 可观测性面板
    - 成本分析
    - 成功率趋势
    """,
    response_description="系统分析统计数据"
)
async def get_analytics(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    获取系统全局分析统计
    """
    request_id = getattr(request.state, "request_id", None)
    try:
        # 统计 Pipeline 状态分布
        total_result = await session.execute(select(func.count(Pipeline.id)))
        total = total_result.scalar() or 0

        success_result = await session.execute(
            select(func.count(Pipeline.id)).where(Pipeline.status == PipelineStatus.SUCCESS)
        )
        success = success_result.scalar() or 0

        failed_result = await session.execute(
            select(func.count(Pipeline.id)).where(Pipeline.status == PipelineStatus.FAILED)
        )
        failed = failed_result.scalar() or 0

        # 计算成功率
        completed = success + failed
        success_rate = (success / completed * 100) if completed > 0 else 0.0

        # 统计 Token 消耗
        tokens_result = await session.execute(
            select(
                func.sum(PipelineStage.input_tokens),
                func.sum(PipelineStage.output_tokens)
            )
        )
        input_tokens, output_tokens = tokens_result.first() or (0, 0)
        total_tokens = (input_tokens or 0) + (output_tokens or 0)

        # 计算成本（基于 GPT-4 价格）
        # 输入: $0.03/1K tokens, 输出: $0.06/1K tokens
        input_cost = (input_tokens or 0) / 1000 * 0.03
        output_cost = (output_tokens or 0) / 1000 * 0.06
        total_cost = input_cost + output_cost

        # 统计平均修复次数
        fix_result = await session.execute(
            select(func.avg(PipelineStage.retry_count))
        )
        avg_fix = fix_result.scalar() or 0.0

        # 统计平均耗时
        duration_result = await session.execute(
            select(func.avg(PipelineStage.duration_ms))
        )
        avg_duration = int(duration_result.scalar() or 0)

        return ResponseModel(
            success=True,
            data=AnalyticsData(
                success_rate=round(success_rate, 2),
                total_pipelines=total,
                total_tokens_consumed=total_tokens,
                avg_fix_count=round(avg_fix, 2),
                avg_duration_ms=avg_duration,
                total_cost_usd=round(total_cost, 4)
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
