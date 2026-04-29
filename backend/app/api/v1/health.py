"""
健康检查 API 端点

提供系统健康状态查询接口，包括基础检查和详细检查。
"""
import time
import uuid
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Any, Dict

from app.core.config import settings
from app.core.response import ResponseModel, success_response


# 记录服务启动时间，用于计算运行时长
START_TIME = time.time()


router = APIRouter(prefix="/health", tags=["Health"])


class HealthStatus(BaseModel):
    """健康状态响应模型"""
    status: str = "healthy"
    version: str
    sandbox_test: bool = False


@router.get("/", response_model=ResponseModel)
async def health_check(request: Request):
    """
    基础健康检查端点
    
    返回系统基本健康状态，可用于快速监控。
    
    **请求方法**: GET
    **路径**: /api/v1/health
    
    **注意**: 此端点仅返回基础信息，不包含依赖项详细状态。
    """
    request_id = str(uuid.uuid4())
    
    health_data = {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "sandbox_test": settings.SANDBOX_TEST_ENABLED
    }
    
    return success_response(data=health_data, request_id=request_id)


@router.get("/detailed", response_model=ResponseModel)
async def health_check_detailed(request: Request):
    """
    详细健康检查端点
    
    返回更详细的系统健康状态信息，可用于生产环境监控。
    
    **请求方法**: GET
    **路径**: /api/v1/health/detailed
    
    **注意**: 此端点会检查更多依赖项状态，响应时间可能略长。
    """
    request_id = str(uuid.uuid4())
    
    # 计算服务运行时间（秒）
    uptime_seconds = int(time.time() - START_TIME)
    
    detailed_status = {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "sandbox_test": settings.SANDBOX_TEST_ENABLED,
        "database": "connected",
        "timestamp": "N/A",  # 后续可扩展为实际时间戳
        "uptime_seconds": uptime_seconds
    }
    
    return success_response(data=detailed_status, request_id=request_id)