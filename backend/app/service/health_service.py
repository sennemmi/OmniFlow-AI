from typing import Dict, Any, Tuple
from app.utils.system_monitor import (
    SystemMonitor,
    get_all_components_status,
    ComponentStatus
)


class HealthService:
    """健康检查服务类，协调各组件检查逻辑并计算整体健康度"""

    @staticmethod
    def calculate_health_score(components: Dict[str, Any]) -> Tuple[int, str]:
        """
        根据组件健康度计算整体健康度分数和状态

        算法规则（一票否决制）：
        1. 如果有任何组件 UNHEALTHY -> 整体 UNHEALTHY
        2. 如果所有组件 HEALTHY -> 整体 HEALTHY
        3. 如果有组件 DEGRADED 但没有 UNHEALTHY -> 整体 DEGRADED
        """
        if not components:
            return 0, ComponentStatus.UNHEALTHY

        total_score = 0
        component_count = 0
        all_healthy = True
        any_unhealthy = False

        for name, comp_data in components.items():
            health_score = comp_data.get("health_score", 0)
            health_status = comp_data.get("status", comp_data.get("health_status", ComponentStatus.UNHEALTHY))

            total_score += health_score
            component_count += 1

            if health_status == ComponentStatus.UNHEALTHY:
                any_unhealthy = True
                all_healthy = False
            elif health_status == ComponentStatus.DEGRADED:
                all_healthy = False

        if component_count == 0:
            return 0, ComponentStatus.UNHEALTHY

        avg_score = total_score // component_count

        # 一票否决制
        if any_unhealthy:
            return avg_score, ComponentStatus.UNHEALTHY
        elif all_healthy:
            return 100, ComponentStatus.HEALTHY
        else:
            return avg_score, ComponentStatus.DEGRADED

    @staticmethod
    async def get_component_health() -> Dict[str, Any]:
        """
        获取组件健康度，返回包含components和overall_health的字典
        """
        # 并行获取各组件状态
        components = await SystemMonitor.get_all_components_status()

        # 计算整体健康度
        overall_health_score, overall_health_str = HealthService.calculate_health_score(components)

        return {
            "components": components,
            "overall_health": overall_health_str
        }


async def check_database_status() -> Dict[str, Any]:
    """返回数据库连接状态，包含 status 和 response_time_ms 字段"""
    result = await SystemMonitor.check_database()
    return {
        "status": result.get("health_status", ComponentStatus.UNHEALTHY),
        "response_time_ms": result.get("response_time_ms", 0)
    }


async def check_disk_status() -> Dict[str, Any]:
    """返回磁盘使用状态，包含 status 和 usage_percent 字段"""
    result = await SystemMonitor.check_disk()
    return {
        "status": result.get("health_status", ComponentStatus.UNHEALTHY),
        "usage_percent": result.get("usage_percent", 0)
    }


async def check_memory_status() -> Dict[str, Any]:
    """返回内存使用状态，包含 status 和 usage_percent 字段"""
    result = await SystemMonitor.check_memory()
    return {
        "status": result.get("health_status", ComponentStatus.UNHEALTHY),
        "usage_percent": result.get("usage_percent", 0)
    }


async def calculate_overall_health(components: Dict[str, Any]) -> str:
    """
    计算整体健康状态，返回 healthy/degraded/unhealthy
    """
    _, health_level = HealthService.calculate_health_score(components)
    return health_level


async def compute_overall_health() -> Dict[str, Any]:
    """
    计算整体健康度，返回包含 overall 和 components 的字典
    """
    db_status = await check_database_status()
    disk_status = await check_disk_status()
    memory_status = await check_memory_status()

    components = {
        "database": db_status,
        "disk": disk_status,
        "memory": memory_status
    }

    # 计算整体健康度
    _, overall_health = HealthService.calculate_health_score(components)

    return {
        "overall": overall_health,
        "components": components
    }


async def get_system_health() -> Dict[str, Any]:
    """
    执行所有健康检查，返回包含 overall_health、health_score、components、component_count 的字典
    """
    components = await get_all_components_status()
    health_score, health_level = HealthService.calculate_health_score(components)

    return {
        "overall_health": health_level,
        "health_score": health_score,
        "components": components,
        "component_count": len(components)
    }


async def get_health_status() -> Dict[str, Any]:
    """
    服务层健康检查函数，返回整体健康状态包含 status、components、timestamp 字段
    """
    from datetime import datetime
    timestamp = datetime.utcnow().isoformat()
    health_result = await get_system_health()

    return {
        "status": health_result.get("overall_health", "unknown"),
        "components": health_result.get("components", {}),
        "timestamp": timestamp
    }
