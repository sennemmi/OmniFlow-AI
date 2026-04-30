import time
import psutil
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.stats_response import SystemStatsSchema
from app.models.pipeline import Pipeline, PipelineStatus, PipelineStage, StageStatus


# 记录服务启动时间
SERVICE_START_TIME = time.time()


class SystemStatsService:
    @staticmethod
    async def collect_stats(session: AsyncSession) -> SystemStatsSchema:
        """
        收集系统统计信息
        
        包括：
        1. CPU 和内存使用率
        2. Pipeline 统计（总数、各状态数量、平均耗时）
        
        Args:
            session: 数据库会话
            
        Returns:
            SystemStatsSchema: 系统统计数据
        """
        # 1. 系统资源统计
        cpu_usage = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        
        # 2. Pipeline 统计
        # 总数
        total_result = await session.execute(select(func.count(Pipeline.id)))
        total_pipelines = total_result.scalar() or 0
        
        # 运行中
        running_result = await session.execute(
            select(func.count(Pipeline.id)).where(Pipeline.status == PipelineStatus.RUNNING)
        )
        running_pipelines = running_result.scalar() or 0
        
        # 已完成 (SUCCESS)
        completed_result = await session.execute(
            select(func.count(Pipeline.id)).where(Pipeline.status == PipelineStatus.SUCCESS)
        )
        completed_pipelines = completed_result.scalar() or 0
        
        # 失败
        failed_result = await session.execute(
            select(func.count(Pipeline.id)).where(Pipeline.status == PipelineStatus.FAILED)
        )
        failed_pipelines = failed_result.scalar() or 0
        
        # 平均耗时（计算所有已完成流水线的平均耗时）
        avg_duration = await SystemStatsService._calculate_avg_duration(session)
        
        return SystemStatsSchema(
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            total_pipelines=total_pipelines,
            running_pipelines=running_pipelines,
            completed_pipelines=completed_pipelines,
            failed_pipelines=failed_pipelines,
            avg_duration=avg_duration
        )

    @staticmethod
    async def get_resource_stats() -> Dict[str, Any]:
        """
        获取系统资源使用统计
        
        包括 CPU、内存、磁盘使用率和运行时间
        
        Returns:
            Dict[str, Any]: 包含以下字段的字典：
                - cpu_percent: CPU 使用率（百分比）
                - memory_percent: 内存使用率（百分比）
                - memory_used_mb: 已使用内存（MB）
                - memory_total_mb: 总内存（MB）
                - disk_percent: 磁盘使用率（百分比）
                - disk_used_gb: 已使用磁盘空间（GB）
                - disk_total_gb: 总磁盘空间（GB）
                - uptime_seconds: 服务运行时间（秒）
        """
        # CPU 使用率
        cpu_percent = psutil.cpu_percent(interval=0.5)
        
        # 内存信息
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_used_mb = int(memory.used / (1024 * 1024))
        memory_total_mb = int(memory.total / (1024 * 1024))
        
        # 磁盘信息
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_used_gb = round(disk.used / (1024 * 1024 * 1024), 2)
        disk_total_gb = round(disk.total / (1024 * 1024 * 1024), 2)
        
        # 运行时间
        uptime_seconds = int(time.time() - SERVICE_START_TIME)
        
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "memory_used_mb": memory_used_mb,
            "memory_total_mb": memory_total_mb,
            "disk_percent": disk_percent,
            "disk_used_gb": disk_used_gb,
            "disk_total_gb": disk_total_gb,
            "uptime_seconds": uptime_seconds
        }

    @staticmethod
    def get_cpu_stats() -> Dict[str, Any]:
        """
        获取 CPU 统计信息
        
        Returns:
            Dict[str, Any]: 包含以下字段的字典：
                - percent: CPU 使用率（百分比）
                - count: CPU 核心数
                - freq_mhz: CPU 频率（MHz）
        """
        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_count = psutil.cpu_count()
        
        try:
            cpu_freq = psutil.cpu_freq()
            freq_mhz = cpu_freq.current if cpu_freq else 0
        except Exception:
            freq_mhz = 0
        
        return {
            "percent": cpu_percent,
            "count": cpu_count,
            "freq_mhz": freq_mhz
        }

    @staticmethod
    def get_memory_stats() -> Dict[str, Any]:
        """
        获取内存统计信息
        
        Returns:
            Dict[str, Any]: 包含以下字段的字典：
                - percent: 内存使用率（百分比）
                - used_mb: 已使用内存（MB）
                - total_mb: 总内存（MB）
                - available_mb: 可用内存（MB）
        """
        memory = psutil.virtual_memory()
        
        return {
            "percent": memory.percent,
            "used_mb": int(memory.used / (1024 * 1024)),
            "total_mb": int(memory.total / (1024 * 1024)),
            "available_mb": int(memory.available / (1024 * 1024))
        }

    @staticmethod
    def get_disk_stats() -> Dict[str, Any]:
        """
        获取磁盘统计信息
        
        Returns:
            Dict[str, Any]: 包含以下字段的字典：
                - percent: 磁盘使用率（百分比）
                - used_gb: 已使用空间（GB）
                - total_gb: 总空间（GB）
                - free_gb: 可用空间（GB）
        """
        disk = psutil.disk_usage('/')
        
        return {
            "percent": disk.percent,
            "used_gb": round(disk.used / (1024 * 1024 * 1024), 2),
            "total_gb": round(disk.total / (1024 * 1024 * 1024), 2),
            "free_gb": round(disk.free / (1024 * 1024 * 1024), 2)
        }
    
    @staticmethod
    async def _calculate_avg_duration(session: AsyncSession) -> Optional[float]:
        """
        计算已完成流水线的平均耗时
        
        通过计算每个 pipeline 的 stages 的总耗时平均值
        
        Args:
            session: 数据库会话
            
        Returns:
            Optional[float]: 平均耗时（秒），如果没有已完成流水线则返回 None
        """
        # 获取所有已完成的 stage
        from sqlalchemy import func
        
        # 查询所有有 completed_at 的 stages
        statement = select(
            PipelineStage.pipeline_id,
            func.min(PipelineStage.created_at).label("start_time"),
            func.max(PipelineStage.completed_at).label("end_time")
        ).where(
            PipelineStage.completed_at.is_not(None)
        ).group_by(PipelineStage.pipeline_id)
        
        result = await session.execute(statement)
        rows = result.all()
        
        if not rows:
            return None
        
        total_duration = 0.0
        count = 0
        
        for row in rows:
            start_time = row.start_time
            end_time = row.end_time
            if start_time and end_time:
                duration = (end_time - start_time).total_seconds()
                if duration > 0:
                    total_duration += duration
                    count += 1
        
        return total_duration / count if count > 0 else None