"""
PipelineStage Repository

封装 PipelineStage 的所有数据库查询操作
"""

from typing import Optional, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pipeline import PipelineStage, StageName


class PipelineStageRepository:
    """
    PipelineStage 数据访问层

    提供所有 PipelineStage 相关的数据库查询操作
    """

    @staticmethod
    async def get_by_id(
        stage_id: int,
        session: AsyncSession
    ) -> Optional[PipelineStage]:
        """
        根据 ID 获取 Stage

        Args:
            stage_id: Stage ID
            session: 数据库会话

        Returns:
            Optional[PipelineStage]: Stage 对象或 None
        """
        return await session.get(PipelineStage, stage_id)

    @staticmethod
    async def get_by_pipeline_and_name(
        pipeline_id: int,
        stage_name: StageName,
        session: AsyncSession
    ) -> Optional[PipelineStage]:
        """
        根据 Pipeline ID 和 Stage 名称获取 Stage

        Args:
            pipeline_id: Pipeline ID
            stage_name: Stage 名称
            session: 数据库会话

        Returns:
            Optional[PipelineStage]: Stage 对象或 None
        """
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == stage_name
        )
        result = await session.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_latest_by_pipeline_and_name(
        pipeline_id: int,
        stage_name: StageName,
        session: AsyncSession
    ) -> Optional[PipelineStage]:
        """
        获取指定 Pipeline 和 Stage 名称的最新 Stage（按创建时间倒序）

        Args:
            pipeline_id: Pipeline ID
            stage_name: Stage 名称
            session: 数据库会话

        Returns:
            Optional[PipelineStage]: 最新的 Stage 对象或 None
        """
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == stage_name
        ).order_by(PipelineStage.created_at.desc())
        result = await session.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_by_pipeline(
        pipeline_id: int,
        session: AsyncSession
    ) -> List[PipelineStage]:
        """
        获取指定 Pipeline 的所有 Stages

        Args:
            pipeline_id: Pipeline ID
            session: 数据库会话

        Returns:
            List[PipelineStage]: Stage 列表
        """
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id
        ).order_by(PipelineStage.created_at)
        result = await session.execute(statement)
        return list(result.scalars().all())

    @staticmethod
    async def get_current_stage(
        pipeline_id: int,
        current_stage_name: StageName,
        session: AsyncSession
    ) -> Optional[PipelineStage]:
        """
        获取 Pipeline 当前 Stage

        Args:
            pipeline_id: Pipeline ID
            current_stage_name: 当前 Stage 名称
            session: 数据库会话

        Returns:
            Optional[PipelineStage]: 当前 Stage 对象或 None
        """
        return await PipelineStageRepository.get_by_pipeline_and_name(
            pipeline_id, current_stage_name, session
        )

    @staticmethod
    async def update_output_data(
        stage_id: int,
        output_data: dict,
        session: AsyncSession
    ) -> bool:
        """
        更新 Stage 的 output_data

        Args:
            stage_id: Stage ID
            output_data: 输出数据
            session: 数据库会话

        Returns:
            bool: 是否更新成功
        """
        stage = await session.get(PipelineStage, stage_id)
        if not stage:
            return False

        stage.output_data = output_data

        # 标记字典已修改，确保 SQLAlchemy 能检测到变化
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(stage, "output_data")

        return True

    @staticmethod
    async def append_to_output_data(
        stage_id: int,
        key: str,
        value: any,
        session: AsyncSession
    ) -> bool:
        """
        向 Stage 的 output_data 追加数据（不覆盖原有数据）

        Args:
            stage_id: Stage ID
            key: 数据键
            value: 数据值
            session: 数据库会话

        Returns:
            bool: 是否更新成功
        """
        stage = await session.get(PipelineStage, stage_id)
        if not stage:
            return False

        # 复制原有数据，避免直接修改
        current_data = dict(stage.output_data) if stage.output_data else {}
        current_data[key] = value
        stage.output_data = current_data

        # 标记字典已修改
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(stage, "output_data")

        return True

    @staticmethod
    async def get_output_data_value(
        pipeline_id: int,
        stage_name: StageName,
        key: str,
        session: AsyncSession,
        default: any = None
    ) -> any:
        """
        获取 Stage output_data 中的特定值

        Args:
            pipeline_id: Pipeline ID
            stage_name: Stage 名称
            key: 数据键
            session: 数据库会话
            default: 默认值

        Returns:
            any: 数据值或默认值
        """
        stage = await PipelineStageRepository.get_by_pipeline_and_name(
            pipeline_id, stage_name, session
        )

        if not stage or not stage.output_data:
            return default

        return stage.output_data.get(key, default)

    @staticmethod
    async def create(
        pipeline_id: int,
        stage_name: StageName,
        status: str,
        session: AsyncSession,
        input_data: Optional[dict] = None,
        output_data: Optional[dict] = None
    ) -> PipelineStage:
        """
        创建新的 Stage

        Args:
            pipeline_id: Pipeline ID
            stage_name: Stage 名称
            status: 状态
            input_data: 输入数据
            output_data: 输出数据
            session: 数据库会话

        Returns:
            PipelineStage: 创建的 Stage 对象
        """
        stage = PipelineStage(
            pipeline_id=pipeline_id,
            name=stage_name,
            status=status,
            input_data=input_data,
            output_data=output_data
        )
        session.add(stage)
        await session.flush()
        return stage
