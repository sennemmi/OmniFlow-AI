"""
健康检查 API
路由层 - 只负责路由定义和参数解析
"""

from fastapi import APIRouter, Request

from app.core.response import ResponseModel, success_response

router = APIRouter()


@router.get("/health", response_model=ResponseModel)
async def health_check(request: Request):
    """
    健康检查端点
    
    Returns:
        ResponseModel: 统一响应格式 {success, data, error, request_id}
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    data = {
        "status": "healthy",
        "service": "omniflowai-backend",
        "version": "0.1.0"
    }
    
    return success_response(data=data, request_id=request_id)


@router.get("/health/detailed", response_model=ResponseModel)
async def health_check_detailed(request: Request):
    """
    详细健康检查端点
    
    Returns:
        ResponseModel: 包含更多系统信息的统一响应
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    data = {
        "status": "healthy",
        "service": "omniflowai-backend",
        "version": "0.1.0",
        "components": {
            "api": "ok",
            "database": "not_configured",
            "llm": "not_configured"
        }
    }
    
    return success_response(data=data, request_id=request_id)
