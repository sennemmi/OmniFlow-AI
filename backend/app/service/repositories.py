"""
数据访问层 - Repository 模式
统一封装数据库访问逻辑，消除重复查询代码
"""

from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.models.pipeline import (
    Pipeline, PipelineStatus,
    PipelineStage, StageName, StageStatus
)
from app.core.timezone import now
from app.core.logging import logger


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


class PipelineStageRepository:
    """PipelineStage 数据访问"""
    
    @staticmethod
    async def get_by_pipeline_and_name(
        pipeline_id: int,
        stage_name: StageName,
        session: AsyncSession
    ) -> Optional[PipelineStage]:
        """
        根据 Pipeline ID 和阶段名称获取 Stage
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            session: 数据库会话
            
        Returns:
            Optional[PipelineStage]: Stage 对象
        """
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == stage_name
        )
        result = await session.execute(statement)
        return result.scalar_one_or_none()
    
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
            Optional[PipelineStage]: Stage 对象
        """
        statement = select(PipelineStage).where(PipelineStage.id == stage_id)
        result = await session.execute(statement)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create(
        pipeline_id: int,
        stage_name: StageName,
        input_data: Optional[Dict[str, Any]],
        session: AsyncSession
    ) -> PipelineStage:
        """
        创建新 Stage
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            input_data: 输入数据
            session: 数据库会话
            
        Returns:
            PipelineStage: 创建的 Stage
        """
        stage = PipelineStage(
            pipeline_id=pipeline_id,
            name=stage_name,
            status=StageStatus.RUNNING,
            input_data=input_data
        )
        session.add(stage)
        await session.commit()

        # ★ DEBUG: 刷新并验证保存的数据
        await session.refresh(stage)
        logger.info(f"[DEBUG] After commit - stage {stage.name} metrics: input_tokens={stage.input_tokens}, output_tokens={stage.output_tokens}, duration_ms={stage.duration_ms}")
        return stage
    
    @staticmethod
    async def complete(
        stage: PipelineStage,
        output_data: Dict[str, Any],
        success: bool,
        session: AsyncSession,
        metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        完成 Stage

        Args:
            stage: Stage 对象
            output_data: 输出数据
            success: 是否成功
            session: 数据库会话
            metrics: 可观测性指标（可选）
        """
        # ★ DEBUG: 打印接收到的 metrics
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[DEBUG] PipelineStageRepository.complete called with metrics: {metrics}")

        stage.status = StageStatus.SUCCESS if success else StageStatus.FAILED
        stage.output_data = output_data
        stage.completed_at = now()

        # 保存可观测性指标
        if metrics:
            stage.input_tokens = metrics.get('input_tokens', 0)
            stage.output_tokens = metrics.get('output_tokens', 0)
            stage.duration_ms = metrics.get('duration_ms', 0)
            stage.retry_count = metrics.get('retry_count', 0)
            stage.reasoning = metrics.get('reasoning')
            logger.info(f"[DEBUG] Saved metrics to stage: input_tokens={stage.input_tokens}, output_tokens={stage.output_tokens}, duration_ms={stage.duration_ms}")
        else:
            logger.warning(f"[DEBUG] No metrics provided for stage {stage.name}, all metrics will be 0")

        session.add(stage)
        await session.commit()
    
    @staticmethod
    async def mark_for_rerun(
        pipeline_id: int,
        stage_name: StageName,
        rejection_feedback: Dict[str, Any],
        session: AsyncSession
    ) -> Optional[PipelineStage]:
        """
        标记 Stage 为重新运行（驳回后）
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            rejection_feedback: 驳回反馈
            session: 数据库会话
            
        Returns:
            Optional[PipelineStage]: Stage 对象
        """
        stage = await PipelineStageRepository.get_by_pipeline_and_name(
            pipeline_id, stage_name, session
        )
        
        if stage:
            # 记录驳回信息
            if stage.output_data is None:
                stage.output_data = {}
            stage.output_data["rejection_feedback"] = {
                **rejection_feedback,
                "rejected_at": now().isoformat()
            }
            stage.status = StageStatus.RUNNING
            session.add(stage)
            await session.commit()
        
        return stage
    
    @staticmethod
    def extract_metrics(agent_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 Agent 执行结果中提取可观测性指标
        
        Args:
            agent_result: Agent 执行结果
            
        Returns:
            Dict[str, Any]: 指标字典
        """
        return {
            'input_tokens': agent_result.get('input_tokens', 0),
            'output_tokens': agent_result.get('output_tokens', 0),
            'duration_ms': agent_result.get('duration_ms', 0),
            'retry_count': agent_result.get('retry_count', 0),
            'reasoning': agent_result.get('reasoning')
        }


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
