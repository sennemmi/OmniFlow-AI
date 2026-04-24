"""
统一 API 响应格式
所有 API 统一返回 {success, data, error, request_id}
"""

from typing import Any, Optional

from pydantic import BaseModel


class ResponseModel(BaseModel):
    """
    统一响应模型
    
    Attributes:
        success: 请求是否成功
        data: 响应数据
        error: 错误信息（如果有）
        request_id: 请求唯一标识
    """
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    request_id: str


def success_response(data: Any = None, request_id: str = "") -> ResponseModel:
    """
    创建成功响应
    
    Args:
        data: 响应数据
        request_id: 请求唯一标识
    
    Returns:
        ResponseModel: 成功响应对象
    """
    return ResponseModel(
        success=True,
        data=data,
        error=None,
        request_id=request_id
    )


def error_response(error: str, request_id: str = "") -> ResponseModel:
    """
    创建错误响应
    
    Args:
        error: 错误信息
        request_id: 请求唯一标识
    
    Returns:
        ResponseModel: 错误响应对象
    """
    return ResponseModel(
        success=False,
        data=None,
        error=error,
        request_id=request_id
    )
