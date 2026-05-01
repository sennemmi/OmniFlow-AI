import asyncio
import uuid
from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.core.response import success_response, error_response
from app.service.health_service import HealthService, get_system_health, get_health_status, calculate_overall_health
from app.utils.system_monitor import SystemMonitor, check_database, check_disk, check_memory, get_all_components_status

router = APIRouter()


@router.get("/health")
async def health_check(request: Request) -> Dict[str, Any]:
    """
    健康检查端点，返回系统健康状态，包含 components 和 overall_health 字段
    """
    request_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    try:
        # 调用 HealthService 获取组件健康度
        health_result = await HealthService.get_component_health()
        
        components = health_result.get("components", {})
        overall_health = health_result.get("overall_health", "unhealthy")
        
        # 组装响应数据
        status = overall_health
        return {
            "status": status,
            "overall_health": overall_health,
            "components": components,
            "timestamp": timestamp,
            "request_id": request_id,
            "success": overall_health == "healthy",
            "error": None
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "overall_health": "unhealthy",
            "components": {},
            "timestamp": timestamp,
            "request_id": request_id,
            "success": False,
            "error": str(e)
        }


@router.get("/detailed")
async def detailed_health_check(request: Request) -> Dict[str, Any]:
    """
    详细健康检查端点，返回更详细的系统健康信息包括 overall_health_score 和 component_count
    """
    request_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    try:
        # 调用聚合服务获取系统健康状态
        health_result = await get_system_health()
        
        # 将组件列表转换为以组件名为键的字典格式
        components_list = health_result.get("components", [])
        components_dict = {}
        for comp in components_list:
            name = comp.get("name", "unknown")
            components_dict[name] = comp
        
        # 获取整体健康度评分
        overall_score = health_result.get("health_score", 0)
        
        # 组装响应数据 - 包含所有要求的字段
        return {
            "status": health_result.get("overall_health", "unknown"),
            "success": overall_score > 0,
            "overall_health_score": overall_score,
            "component_count": health_result.get("component_count", 0),
            "components": components_dict,
            "error": None,
            "request_id": request_id,
            "timestamp": timestamp
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "success": False,
            "overall_health_score": 0,
            "component_count": 0,
            "components": {},
            "error": "Health check failed: " + str(e),
            "request_id": request_id,
            "timestamp": timestamp
        }


async def get_health_status() -> dict:
    """
    API 层健康检查入口，返回整体健康状态包含 status、components、timestamp 字段
    """
    timestamp = datetime.utcnow().isoformat()
    health_result = await get_system_health()
    
    components_list = health_result.get("components", [])
    components_dict = {}
    for comp in components_list:
        name = comp.get("name", "unknown")
        components_dict[name] = comp
    
    return {
        "status": health_result.get("overall_health", "unknown"),
        "components": components_dict,
        "timestamp": timestamp
    }


def calculate_health_score():
    """
    计算系统健康分数
    返回: int 健康分数 (0-100)
    """
    # 简单实现，返回100表示健康
    return 100


def calculate_health_score():
    """
    计算系统健康分数
    返回: int 健康分数 (0-100)
    """
    # 简单实现，返回100表示健康
    return 100