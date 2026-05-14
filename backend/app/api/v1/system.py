"""
系统监控 API
路由层 - 只负责路由定义和参数解析
"""

import time
import uuid
from datetime import datetime, UTC
from typing import Optional
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import func, select

from app.service.system_stats import SystemStatsService
from app.service.health_service import HealthService
from app.core.response import ResponseModel, success_response, error_response
from app.core.database import get_session, get_db_status
from app.core.logging import get_request_id_from_request
from app.models.pipeline import Pipeline, PipelineStage, PipelineStatus
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


# ============================================
# 基础健康检查端点（兼容旧版 /health）
# ============================================

@router.get("/health", summary="基础健康检查 (兼容端点)")
async def basic_health_check(request: Request):
    """供内部服务和探针使用的轻量级健康检查"""
    request_id = get_request_id_from_request(request)
    try:
        health_data = await HealthService.get_component_health()
        overall_health = health_data.get("overall_health", "unhealthy")
        return success_response(
            data={
                "status": overall_health,
                "overall_health": overall_health,
                "components": health_data.get("components", {}),
                "timestamp": datetime.now(UTC).isoformat(),
            },
            request_id=request_id
        )
    except Exception as e:
        return error_response(error=str(e), request_id=request_id)


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
    request_id = get_request_id_from_request(request)
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
        from app.core.logging import error
        error("获取系统统计失败", exc_info=True)
        return ResponseModel(
            success=False,
            data=None,
            error=str(e),
            request_id=request_id
        )


@router.get(
    "/system/health",
    response_model=ResponseModel,
    summary="获取系统健康状态",
    description="""
    获取系统整体健康状态和各组件健康状态。

    返回数据说明：
    - **status**: 整体健康状态 (healthy/degraded/unhealthy)
    - **components**: 各组件健康状态详情
    - **overall_health**: 整体健康状态

    适用于：
    - 系统健康监控
    - 告警阈值判断
    - 运维巡检
    """,
    response_description="系统健康状态和组件详情"
)
async def get_system_health(request: Request) -> ResponseModel:
    """
    获取系统健康状态，返回包含status、components、overall_health字段的响应
    """
    request_id = get_request_id_from_request(request)
    try:
        health_data = await HealthService.get_component_health()
        components = health_data.get("components", {})
        overall_health = health_data.get("overall_health", "unhealthy")
        
        # 根据 overall_health 确定 status
        status = overall_health
        
        return success_response(
            data={
                "status": status,
                "components": components,
                "overall_health": overall_health
            },
            request_id=request_id
        )
    except Exception as e:
        logger.error("健康检查失败", error=str(e))
        return error_response(
            error=f"Health check failed: {str(e)}",
            request_id=request_id
        )


@router.get(
    "/system/metrics",
    response_model=ResponseModel,
    summary="获取系统资源使用指标",
    description="""
    获取系统资源使用指标，包含CPU、内存、磁盘使用率和运行时间。

    返回数据说明：
    - **cpu_usage**: CPU使用率百分比
    - **memory_usage**: 内存使用率百分比
    - **disk_usage**: 磁盘使用率百分比
    - **uptime_seconds**: 服务运行时间(秒)

    适用于：
    - 系统资源监控
    - 性能分析
    - 容量规划
    """,
    response_description="系统资源使用指标"
)
async def get_system_metrics(request: Request) -> ResponseModel:
    """
    获取系统资源使用指标，返回包含cpu_usage、memory_usage、disk_usage、uptime_seconds字段的响应
    """
    request_id = get_request_id_from_request(request)
    try:
        resource_stats = await SystemStatsService.get_resource_stats()
        
        # 映射字段名到契约要求的字段
        cpu_usage = resource_stats.get("cpu_percent", 0.0)
        memory_usage = resource_stats.get("memory_percent", 0.0)
        disk_usage = resource_stats.get("disk_percent", 0.0)
        uptime_seconds = resource_stats.get("uptime_seconds", 0)
        
        return success_response(
            data={
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage,
                "uptime_seconds": uptime_seconds
            },
            request_id=request_id
        )
    except Exception as e:
        logger.error("系统指标收集失败", error=str(e))
        return error_response(
            error=f"Metrics collection failed: {str(e)}",
            request_id=request_id
        )


class DatabaseStatusResponse(BaseModel):
    """数据库状态响应模型"""
    connected: bool = Field(
        ...,
        description="数据库是否连接成功",
        example=True
    )
    database_url: str = Field(
        ...,
        description="数据库连接URL（已脱敏）",
        example="sqlite+aiosqlite:///./omniflow.db"
    )
    pool_size: int = Field(
        ...,
        description="连接池大小",
        example=5
    )
    active_connections: int = Field(
        ...,
        description="当前活跃连接数",
        example=1
    )


@router.get(
    "/system/db-status",
    response_model=ResponseModel,
    summary="检查数据库连接状态",
    description="""
    检查数据库连接状态和连接池统计信息。

    返回数据说明：
    - **connected**: 数据库是否连接成功
    - **database_url**: 数据库连接URL（已脱敏处理）
    - **pool_size**: 连接池大小
    - **active_connections**: 当前活跃连接数

    适用于：
    - 数据库健康检查
    - 连接池监控
    """,
    response_description="数据库连接状态信息"
)
async def get_db_status_endpoint(request: Request):
    """
    检查数据库连接状态和统计信息
    """
    request_id = get_request_id_from_request(request)
    try:
        db_status = await get_db_status()
        return ResponseModel(
            success=True,
            data=DatabaseStatusResponse(**db_status).model_dump(),
            error=None,
            request_id=request_id
        )
    except Exception as e:
        from app.core.logging import error
        error("获取数据库状态失败", exc_info=True)
        return ResponseModel(
            success=False,
            data=None,
            error=str(e),
            request_id=request_id
        )


# ============================================
# 新增综合健康检查端点
# ============================================

class ServiceCheck(BaseModel):
    """服务状态检查"""
    status: str = Field(..., description="状态 (healthy/degraded/unhealthy)")
    version: str = Field(..., description="服务版本")
    uptime_seconds: int = Field(..., description="运行时间（秒）")


class DatabaseCheck(BaseModel):
    """数据库状态检查"""
    status: str = Field(..., description="状态 (healthy/degraded/unhealthy)")
    connected: bool = Field(..., description="是否已连接")


class ResourcesCheck(BaseModel):
    """资源状态检查"""
    status: str = Field(..., description="状态 (healthy/degraded/unhealthy)")
    cpu_percent: float = Field(..., description="CPU使用率")
    memory_percent: float = Field(..., description="内存使用率")
    disk_percent: float = Field(..., description="磁盘使用率")


class DetailedHealthResponse(BaseModel):
    """综合健康检查响应模型"""
    overall_status: str = Field(
        ...,
        description="整体状态 (healthy/degraded/unhealthy)",
        example="healthy"
    )
    checks: dict = Field(
        ...,
        description="各项检查结果",
        example={
            "service": {"status": "healthy", "version": "0.1.0", "uptime_seconds": 3600},
            "database": {"status": "healthy", "connected": True},
            "resources": {"status": "healthy", "cpu_percent": 45.5, "memory_percent": 62.3, "disk_percent": 75.0}
        }
    )
    timestamp: str = Field(
        ...,
        description="检查时间戳",
        example="2024-01-15T10:30:00"
    )


# 记录服务启动时间
SERVICE_START_TIME = time.time()


@router.get(
    "/system/health-detailed",
    response_model=ResponseModel,
    summary="综合健康检查",
    description="""
    综合健康检查，包含服务状态、数据库状态和资源使用情况。

    返回数据说明：
    - **overall_status**: 整体健康状态 (healthy/degraded/unhealthy)
    - **checks**: 各项检查结果
        - **service**: 服务状态（版本、运行时间）
        - **database**: 数据库状态（连接状态）
        - **resources**: 资源状态（CPU、内存、磁盘使用率）
    - **timestamp**: 检查时间戳

    状态判定规则：
    - **healthy**: 所有检查项正常
    - **degraded**: 部分检查项警告（如资源使用率高但未超限）
    - **unhealthy**: 存在严重问题（如数据库连接失败）

    适用于：
    - 生产环境健康监控
    - 负载均衡器健康检查
    - 告警系统
    """,
    response_description="综合健康检查报告"
)
async def get_detailed_health(request: Request):
    """
    综合健康检查，聚合服务状态、数据库状态和资源使用信息
    """
    request_id = get_request_id_from_request(request)
    try:
        # 1. 服务状态
        uptime_seconds = int(time.time() - SERVICE_START_TIME)
        service_check = ServiceCheck(
            status="healthy",
            version=settings.APP_VERSION,
            uptime_seconds=uptime_seconds
        )

        # 2. 数据库状态
        try:
            db_status = await get_db_status()
            db_connected = db_status.get("connected", False)
            db_check = DatabaseCheck(
                status="healthy" if db_connected else "unhealthy",
                connected=db_connected
            )
        except Exception:
            db_check = DatabaseCheck(
                status="unhealthy",
                connected=False
            )

        # 3. 资源状态
        try:
            resource_stats = await SystemStatsService.get_resource_stats()
            cpu_percent = resource_stats["cpu_percent"]
            memory_percent = resource_stats["memory_percent"]
            disk_percent = resource_stats["disk_percent"]

            # 判定资源状态
            if cpu_percent > 90 or memory_percent > 90 or disk_percent > 95:
                resources_status = "unhealthy"
            elif cpu_percent > 70 or memory_percent > 70 or disk_percent > 85:
                resources_status = "degraded"
            else:
                resources_status = "healthy"

            resources_check = ResourcesCheck(
                status=resources_status,
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                disk_percent=disk_percent
            )
        except Exception:
            resources_check = ResourcesCheck(
                status="unhealthy",
                cpu_percent=0.0,
                memory_percent=0.0,
                disk_percent=0.0
            )

        # 计算整体状态
        checks = {
            "service": service_check.model_dump(),
            "database": db_check.model_dump(),
            "resources": resources_check.model_dump()
        }

        if db_check.status == "unhealthy" or resources_check.status == "unhealthy":
            overall_status = "unhealthy"
        elif resources_check.status == "degraded":
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        health_data = DetailedHealthResponse(
            overall_status=overall_status,
            checks=checks,
            timestamp=datetime.now().isoformat()
        )

        return ResponseModel(
            success=True,
            data=health_data.model_dump(),
            error=None,
            request_id=request_id
        )
    except Exception as e:
        from app.core.logging import error
        error("综合健康检查失败", exc_info=True)
        return ResponseModel(
            success=False,
            data=None,
            error=str(e),
            request_id=request_id
        )


@router.get(
    "/system/config",
    response_model=ResponseModel,
    summary="获取系统配置",
    description="获取前端所需的系统配置信息，如目标项目路径等",
)
async def get_system_config(
    request: Request,
):
    """
    获取系统配置信息
    """
    request_id = get_request_id_from_request(request)
    try:
        from app.core.config import settings

        return ResponseModel(
            success=True,
            data={
                "target_project_path": settings.TARGET_PROJECT_PATH,
                "api_base_url": "http://localhost:8000",
                "version": "1.0.0",
            },
            error=None,
            request_id=request_id
        )
    except Exception as e:
        from app.core.logging import error
        error("获取系统配置失败", exc_info=True)
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
    request_id = get_request_id_from_request(request)
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
        from app.core.logging import error
        error("获取系统分析数据失败", exc_info=True)
        return ResponseModel(
            success=False,
            data=None,
            error=str(e),
            request_id=request_id
        )
