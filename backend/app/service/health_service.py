from typing import Dict, Any, Tuple

from app.utils.system_monitor import SystemMonitor, ComponentStatus


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

        if any_unhealthy:
            return avg_score, ComponentStatus.UNHEALTHY
        elif all_healthy:
            return 100, ComponentStatus.HEALTHY
        else:
            return avg_score, ComponentStatus.DEGRADED

    @staticmethod
    async def get_component_health() -> Dict[str, Any]:
        """获取组件健康度，返回包含components和overall_health的字典"""
        components = await SystemMonitor.get_all_components_status()
        overall_health_score, overall_health_str = HealthService.calculate_health_score(components)

        return {
            "components": components,
            "overall_health": overall_health_str
        }
