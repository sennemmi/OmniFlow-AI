"""
Stage Transition Service

阶段流转服务
"""

from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pipeline import Pipeline, PipelineStatus, StageName, StageStatus
from app.core.timezone import now
from app.repositories.pipeline_repository import PipelineRepository
from app.repositories.pipeline_stage_repository import PipelineStageRepository


class StageTransitionService:
    """阶段流转服务"""

    # 阶段流转顺序
    STAGE_FLOW = [
        StageName.REQUIREMENT,
        StageName.DESIGN,
        StageName.CODING,
        StageName.UNIT_TESTING,   # 插入到 CODING 之后
        StageName.CODE_REVIEW,
        StageName.DELIVERY,
    ]

    @classmethod
    def get_next_stage(cls, current_stage: StageName) -> Optional[StageName]:
        """
        获取下一阶段

        Args:
            current_stage: 当前阶段

        Returns:
            Optional[StageName]: 下一阶段
        """
        try:
            current_index = cls.STAGE_FLOW.index(current_stage)
            if current_index < len(cls.STAGE_FLOW) - 1:
                return cls.STAGE_FLOW[current_index + 1]
            return None
        except ValueError:
            return None

    @classmethod
    async def transition(
        cls,
        pipeline: Pipeline,
        session: AsyncSession
    ) -> tuple[bool, Optional[StageName], Optional[str]]:
        """
        流转到下一阶段

        Args:
            pipeline: Pipeline 对象
            session: 数据库会话

        Returns:
            tuple[bool, Optional[StageName], Optional[str]]: (是否成功, 新阶段, 错误信息)
        """
        next_stage = cls.get_next_stage(pipeline.current_stage)

        if next_stage is None:
            # 已经是最后阶段，标记为成功
            await PipelineRepository.set_success(pipeline, session)
            return True, None, None

        # 找到当前阶段并标记为成功
        current_stage = await PipelineStageRepository.get_by_pipeline_and_name(
            pipeline.id, pipeline.current_stage, session
        )
        if current_stage and current_stage.status == StageStatus.RUNNING:
            current_stage.status = StageStatus.SUCCESS
            current_stage.completed_at = now()
            session.add(current_stage)

        # 更新 pipeline
        pipeline.status = PipelineStatus.RUNNING
        pipeline.current_stage = next_stage
        await session.commit()

        return True, next_stage, None
