"""
Pipeline Repository

封装 Pipeline 的所有数据库查询操作
"""

from typing import Optional

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pipeline import Pipeline, PipelineStatus
from app.core.timezone import now


class PipelineRepository:
    """Pipeline 数据访问"""

    @staticmethod
    async def get_by_id(
        pipeline_id: int,
        session: AsyncSession,
        load_stages: bool = True
    ) -> Optional[Pipeline]:
        """
        根据 ID 获取 Pipeline

        Args:
            pipeline_id: Pipeline ID
            session: 数据库会话
            load_stages: 是否加载 stages 关联

        Returns:
            Optional[Pipeline]: Pipeline 对象
        """
        statement = select(Pipeline).where(Pipeline.id == pipeline_id)
        if load_stages:
            statement = statement.options(selectinload(Pipeline.stages))
        result = await session.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        pipeline: Pipeline,
        status: PipelineStatus,
        session: AsyncSession
    ) -> None:
        """
        更新 Pipeline 状态

        Args:
            pipeline: Pipeline 对象
            status: 新状态
            session: 数据库会话
        """
        pipeline.status = status
        await session.commit()

    @staticmethod
    async def set_running(
        pipeline: Pipeline,
        session: AsyncSession
    ) -> None:
        """设置 Pipeline 为运行状态"""
        await PipelineRepository.update_status(pipeline, PipelineStatus.RUNNING, session)

    @staticmethod
    async def set_paused(
        pipeline: Pipeline,
        session: AsyncSession
    ) -> None:
        """设置 Pipeline 为暂停状态"""
        await PipelineRepository.update_status(pipeline, PipelineStatus.PAUSED, session)

    @staticmethod
    async def set_failed(
        pipeline: Pipeline,
        session: AsyncSession
    ) -> None:
        """设置 Pipeline 为失败状态"""
        await PipelineRepository.update_status(pipeline, PipelineStatus.FAILED, session)

    @staticmethod
    async def set_success(
        pipeline: Pipeline,
        session: AsyncSession
    ) -> None:
        """设置 Pipeline 为成功状态"""
        await PipelineRepository.update_status(pipeline, PipelineStatus.SUCCESS, session)
