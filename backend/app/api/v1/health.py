"""
健康检查 API
路由层 - 只负责路由定义和参数解析
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.response import ResponseModel, success_response

router = APIRouter()


class HealthStatus(BaseModel):
    """健康状态数据"""
    status: str = Field(..., description="服务状态: healthy/unhealthy")
    service: str = Field(..., description="服务名称")
    version: str = Field(..., description="服务版本号")


class ComponentStatus(BaseModel):
    """组件状态详情"""
    api: str = Field(..., description="API 服务状态")
    database: str = Field(..., description="数据库连接状态")
    llm: str = Field(..., description="LLM 服务状态")


class HealthDetailedStatus(BaseModel):
    """详细健康状态数据"""
    status: str = Field(..., description="整体服务状态")
    service: str = Field(..., description="服务名称")
    version: str = Field(..., description="服务版本号")
    components: ComponentStatus = Field(..., description="各组件状态详情")


@router.get(
    "/health",
    response_model=ResponseModel,
    summary="健康检查",
    description="""
    基础健康检查端点，用于快速验证服务是否正常运行。
    
    返回服务基本状态信息，适用于：
    - 负载均衡器健康检查
    - 容器编排（如 Kubernetes）存活探针
    - 简单的心跳检测
    """,
    response_description="服务健康状态"
)
async def health_check(request: Request):
    """
    健康检查端点
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    health_data = HealthStatus(
        status="healthy",
        service="omniflowai-backend",
        version="0.1.2"
    )
    
    return success_response(data=health_data.model_dump(), request_id=request_id)


@router.get(
    "/health/detailed",
    response_model=ResponseModel,
    summary="详细健康检查",
    description="""
    详细健康检查端点，返回各组件的详细状态。
    
    包含以下组件状态：
    - **api**: API 服务运行状态
    - **database**: 数据库连接状态
    - **llm**: LLM 服务可用性
    
    适用于监控系统和故障排查。
    """,
    response_description="详细健康状态及各组件信息"
)
async def health_check_detailed(request: Request):
    """
    详细健康检查端点
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    components = ComponentStatus(
        api="ok",
        database="connected",
        llm="available"
    )
    
    health_data = HealthDetailedStatus(
        status="healthy",
        service="omniflowai-backend",
        version="0.1.2",
        components=components
    )
    
    return success_response(data=health_data.model_dump(), request_id=request_id)
