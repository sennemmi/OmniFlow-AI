from typing import Dict, Any
import asyncio
import time
import shutil
from enum import Enum


class ComponentStatus(str, Enum):
    """组件状态枚举 - 统一状态词汇，只保留三个核心状态"""
    HEALTHY = "healthy"      # 健康
    DEGRADED = "degraded"    # 降级（有警告但可用）
    UNHEALTHY = "unhealthy"  # 不健康（不可用）


class SystemMonitor:
    """系统监控类，提供磁盘、内存和数据库健康检查的静态方法"""

    @staticmethod
    def get_disk_usage() -> Dict[str, float]:
        """获取磁盘使用信息"""
        total, used, free = shutil.disk_usage("/")
        total_gb = total / (1024 ** 3)
        used_gb = used / (1024 ** 3)
        free_gb = free / (1024 ** 3)
        usage_percent = (used / total) * 100

        return {
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "usage_percent": usage_percent
        }

    @staticmethod
    def get_memory_usage() -> Dict[str, float]:
        """获取内存使用信息"""
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()

            mem_info = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    value = int(parts[1])
                    mem_info[key] = value

            total_mb = mem_info.get('MemTotal', 0) / 1024
            available_mb = mem_info.get('MemAvailable', mem_info.get('MemFree', 0)) / 1024
            used_mb = total_mb - available_mb
            usage_percent = (used_mb / total_mb) * 100 if total_mb > 0 else 0

            return {
                "total_mb": total_mb,
                "used_mb": used_mb,
                "available_mb": available_mb,
                "usage_percent": usage_percent
            }
        except Exception:
            return {
                "total_mb": 0,
                "used_mb": 0,
                "available_mb": 0,
                "usage_percent": 0
            }

    @staticmethod
    async def check_database() -> Dict[str, Any]:
        """
        检查数据库状态
        返回统一格式的健康状态字典
        """
        from app.core.database import get_session
        from sqlalchemy import text

        start_time = time.time()
        try:
            async for session in get_session():
                await session.execute(text("SELECT 1"))
                await session.close()
                break

            response_time = int((time.time() - start_time) * 1000)
            # 响应时间决定健康分数：小于1秒满分，1-5秒降级，超过5秒不健康
            if response_time < 1000:
                health_score = 100
                health_status = ComponentStatus.HEALTHY
            elif response_time < 5000:
                health_score = 50
                health_status = ComponentStatus.DEGRADED
            else:
                health_score = 0
                health_status = ComponentStatus.UNHEALTHY

            return {
                "health_status": health_status,
                "health_score": health_score,
                "response_time_ms": response_time,
                "message": "Database connection successful"
            }
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            return {
                "health_status": ComponentStatus.UNHEALTHY,
                "health_score": 0,
                "response_time_ms": response_time,
                "message": f"Database connection failed: {str(e)}"
            }

    @staticmethod
    async def check_disk() -> Dict[str, Any]:
        """
        检查磁盘状态
        返回统一格式的健康状态字典
        """
        disk_info = SystemMonitor.get_disk_usage()
        usage_percent = disk_info["usage_percent"]
        available_gb = disk_info["free_gb"]

        # 统一使用 health_status 进行状态判定
        if usage_percent >= 90:
            health_status = ComponentStatus.UNHEALTHY
            health_score = 0
        elif usage_percent >= 70:
            health_status = ComponentStatus.DEGRADED
            health_score = 50
        else:
            health_status = ComponentStatus.HEALTHY
            health_score = 100

        return {
            "health_status": health_status,
            "health_score": health_score,
            "usage_percent": round(usage_percent, 2),
            "available_gb": round(available_gb, 2)
        }

    @staticmethod
    async def check_memory() -> Dict[str, Any]:
        """
        检查内存状态
        返回统一格式的健康状态字典
        """
        mem_info = SystemMonitor.get_memory_usage()
        usage_percent = mem_info["usage_percent"]
        available_mb = mem_info["available_mb"]

        # 统一使用 health_status 进行状态判定
        if usage_percent >= 90:
            health_status = ComponentStatus.UNHEALTHY
            health_score = 0
        elif usage_percent >= 70:
            health_status = ComponentStatus.DEGRADED
            health_score = 50
        else:
            health_status = ComponentStatus.HEALTHY
            health_score = 100

        return {
            "health_status": health_status,
            "health_score": health_score,
            "usage_percent": round(usage_percent, 2),
            "available_mb": round(available_mb, 2)
        }

    @staticmethod
    async def get_all_components_status() -> Dict[str, Any]:
        """
        并行获取所有组件的健康状态
        """
        db_status, disk_status, memory_status = await asyncio.gather(
            SystemMonitor.check_database(),
            SystemMonitor.check_disk(),
            SystemMonitor.check_memory()
        )

        return {
            "database": db_status,
            "disk": disk_status,
            "memory": memory_status
        }


# 保持向后兼容的模块级函数 - 全部委托给 SystemMonitor 类

async def check_database() -> Dict[str, Any]:
    """检测数据库连接状态（兼容函数）"""
    return await SystemMonitor.check_database()


async def check_disk() -> Dict[str, Any]:
    """检测磁盘使用状态（兼容函数）"""
    return await SystemMonitor.check_disk()


async def check_memory() -> Dict[str, Any]:
    """检测内存使用状态（兼容函数）"""
    return await SystemMonitor.check_memory()


async def get_all_components_status() -> Dict[str, Any]:
    """并行聚合所有组件的状态信息（兼容函数）"""
    return await SystemMonitor.get_all_components_status()
