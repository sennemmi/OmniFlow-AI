"""
工作流状态管理服务
负责 Pipeline 的状态流转（Status Check, Approve, Reject 状态切换逻辑）
"""

from typing import Optional, Dict, Any, Tuple
from datetime import datetime

from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.timezone import now
from app.core.logging import info, error
from app.models.pipeline import (
    Pipeline, PipelineStatus,
    PipelineStage, StageName, StageStatus
)


class WorkflowService:
    """
    工作流状态管理服务
    
    职责：
    1. Pipeline 状态检查和验证
    2. 状态流转（Approve/Reject）
    3. 阶段管理和转换
    """
    
    # 阶段流转顺序
    STAGE_FLOW = [
        StageName.REQUIREMENT,
        StageName.DESIGN,
        StageName.CODING,
        StageName.CODE_REVIEW,
        StageName.DELIVERY,
    ]
    
    @classmethod
    async def get_pipeline_with_stages(
        cls,
        pipeline_id: int,
        session: AsyncSession
    ) -> Optional[Pipeline]:
        """
        获取 Pipeline 及其所有阶段
        
        Args:
            pipeline_id: Pipeline ID
            session: 数据库会话
            
        Returns:
            Pipeline: Pipeline 对象（包含 stages），不存在返回 None
        """
        statement = select(Pipeline).where(Pipeline.id == pipeline_id).options(
            selectinload(Pipeline.stages)
        )
        result = await session.execute(statement)
        return result.scalar_one_or_none()
    
    @classmethod
    async def validate_can_approve(
        cls,
        pipeline: Pipeline
    ) -> Tuple[bool, Optional[str]]:
        """
        验证是否可以批准
        
        Args:
            pipeline: Pipeline 对象
            
        Returns:
            Tuple[bool, Optional[str]]: (是否可批准, 错误信息)
        """
        if not pipeline:
            return False, "Pipeline not found"
        
        if pipeline.status != PipelineStatus.PAUSED:
            return False, f"Pipeline is not in PAUSED state, cannot approve"
        
        return True, None
    
    @classmethod
    async def validate_can_reject(
        cls,
        pipeline: Pipeline
    ) -> Tuple[bool, Optional[str]]:
        """
        验证是否可以驳回
        
        Args:
            pipeline: Pipeline 对象
            
        Returns:
            Tuple[bool, Optional[str]]: (是否可驳回, 错误信息)
        """
        if not pipeline:
            return False, "Pipeline not found"
        
        if pipeline.status != PipelineStatus.PAUSED:
            return False, f"Pipeline is not in PAUSED state, cannot reject"
        
        return True, None
    
    @classmethod
    async def get_next_stage(cls, current_stage: StageName) -> Optional[StageName]:
        """
        获取下一阶段
        
        Args:
            current_stage: 当前阶段
            
        Returns:
            Optional[StageName]: 下一阶段，如果是最后阶段返回 None
        """
        try:
            current_index = cls.STAGE_FLOW.index(current_stage)
            if current_index < len(cls.STAGE_FLOW) - 1:
                return cls.STAGE_FLOW[current_index + 1]
            return None
        except ValueError:
            return None
    
    @classmethod
    async def transition_to_next_stage(
        cls,
        pipeline: Pipeline,
        session: AsyncSession
    ) -> Tuple[bool, Optional[StageName], Optional[str]]:
        """
        流转到下一阶段
        
        Args:
            pipeline: Pipeline 对象
            session: 数据库会话
            
        Returns:
            Tuple[bool, Optional[StageName], Optional[str]]: 
                (是否成功, 新阶段, 错误信息)
        """
        next_stage = await cls.get_next_stage(pipeline.current_stage)
        
        if next_stage is None:
            # 已经是最后阶段，标记为成功
            pipeline.status = PipelineStatus.SUCCESS
            pipeline.current_stage = StageName.DELIVERY
            await session.commit()
            
            info(
                "Pipeline 完成所有阶段",
                pipeline_id=pipeline.id,
                status="SUCCESS"
            )
            return True, None, None
        
        # 更新 Pipeline 状态
        pipeline.status = PipelineStatus.RUNNING
        pipeline.current_stage = next_stage
        await session.commit()
        
        info(
            "Pipeline 进入下一阶段",
            pipeline_id=pipeline.id,
            previous_stage=pipeline.current_stage.value if pipeline.current_stage else None,
            next_stage=next_stage.value
        )
        
        return True, next_stage, None
    
    @classmethod
    async def create_stage(
        cls,
        pipeline_id: int,
        stage_name: StageName,
        input_data: Optional[Dict[str, Any]],
        session: AsyncSession
    ) -> PipelineStage:
        """
        创建新阶段
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            input_data: 输入数据
            session: 数据库会话
            
        Returns:
            PipelineStage: 创建的阶段
        """
        stage = PipelineStage(
            pipeline_id=pipeline_id,
            name=stage_name,
            status=StageStatus.RUNNING,
            input_data=input_data
        )
        session.add(stage)
        await session.commit()
        
        info(
            "创建 Pipeline 阶段",
            pipeline_id=pipeline_id,
            stage=stage_name.value
        )
        
        return stage
    
    @classmethod
    async def complete_stage(
        cls,
        stage: PipelineStage,
        output_data: Dict[str, Any],
        success: bool,
        session: AsyncSession
    ) -> None:
        """
        完成阶段
        
        Args:
            stage: 阶段对象
            output_data: 输出数据
            success: 是否成功
            session: 数据库会话
        """
        stage.status = StageStatus.SUCCESS if success else StageStatus.FAILED
        stage.output_data = output_data
        stage.completed_at = now()
        session.add(stage)
        await session.commit()
        
        info(
            "Pipeline 阶段完成",
            pipeline_id=stage.pipeline_id,
            stage=stage.name.value,
            status=stage.status.value
        )
    
    @classmethod
    async def mark_stage_for_rerun(
        cls,
        pipeline_id: int,
        stage_name: StageName,
        rejection_feedback: Dict[str, Any],
        session: AsyncSession
    ) -> Optional[PipelineStage]:
        """
        标记阶段为重新运行（驳回后）
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            rejection_feedback: 驳回反馈
            session: 数据库会话
            
        Returns:
            Optional[PipelineStage]: 阶段对象
        """
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == stage_name
        )
        result = await session.execute(statement)
        stage = result.scalar_one_or_none()
        
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
            
            info(
                "Pipeline 阶段标记为重新运行",
                pipeline_id=pipeline_id,
                stage=stage_name.value
            )
        
        return stage
    
    @classmethod
    async def set_pipeline_running(
        cls,
        pipeline: Pipeline,
        session: AsyncSession
    ) -> None:
        """
        设置 Pipeline 为运行状态
        
        Args:
            pipeline: Pipeline 对象
            session: 数据库会话
        """
        pipeline.status = PipelineStatus.RUNNING
        await session.commit()
        
        info(
            "Pipeline 状态更新为 RUNNING",
            pipeline_id=pipeline.id,
            current_stage=pipeline.current_stage.value if pipeline.current_stage else None
        )
    
    @classmethod
    async def set_pipeline_paused(
        cls,
        pipeline: Pipeline,
        session: AsyncSession
    ) -> None:
        """
        设置 Pipeline 为暂停状态（等待审批）
        
        Args:
            pipeline: Pipeline 对象
            session: 数据库会话
        """
        pipeline.status = PipelineStatus.PAUSED
        await session.commit()
        
        info(
            "Pipeline 状态更新为 PAUSED",
            pipeline_id=pipeline.id,
            current_stage=pipeline.current_stage.value if pipeline.current_stage else None
        )
    
    @classmethod
    async def set_pipeline_failed(
        cls,
        pipeline: Pipeline,
        session: AsyncSession
    ) -> None:
        """
        设置 Pipeline 为失败状态
        
        Args:
            pipeline: Pipeline 对象
            session: 数据库会话
        """
        pipeline.status = PipelineStatus.FAILED
        await session.commit()
        
        info(
            "Pipeline 状态更新为 FAILED",
            pipeline_id=pipeline.id,
            current_stage=pipeline.current_stage.value if pipeline.current_stage else None
        )
