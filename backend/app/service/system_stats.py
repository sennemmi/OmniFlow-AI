import psutil
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.stats_response import SystemStatsSchema
from app.models.pipeline import Pipeline, PipelineStatus, PipelineStage, StageStatus


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