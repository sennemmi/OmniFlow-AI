"""
工作流状态管理服务
负责 Pipeline 的状态流转（Status Check, Approve, Reject 状态切换逻辑）

【优化】使用 Repository 模式统一数据访问，消除重复代码
"""

from typing import Optional, Dict, Any, Tuple

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import info, error
from app.models.pipeline import (
    Pipeline, PipelineStatus,
    PipelineStage, StageName, StageStatus
)
from app.service.repositories import (
    PipelineRepository,
    PipelineStageRepository,
    StageTransitionService
)


class WorkflowService:
    """
    工作流状态管理服务
    
    职责：
    1. Pipeline 状态检查和验证
    2. 状态流转（Approve/Reject）
    3. 阶段管理和转换
    
    【优化】所有数据访问委托给 Repository，本层只保留业务逻辑
    """
    
    # 阶段流转顺序（委托给 StageTransitionService）
    STAGE_FLOW = StageTransitionService.STAGE_FLOW
    
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
        return await PipelineRepository.get_by_id(pipeline_id, session, load_stages=True)
    
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
        return StageTransitionService.get_next_stage(current_stage)
    
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
        success, next_stage, error = await StageTransitionService.transition(
            pipeline, session
        )
        
        if success and next_stage:
            info(
                "Pipeline 进入下一阶段",
                pipeline_id=pipeline.id,
                previous_stage=pipeline.current_stage.value if pipeline.current_stage else None,
                next_stage=next_stage.value
            )
        elif success and not next_stage:
            info(
                "Pipeline 完成所有阶段",
                pipeline_id=pipeline.id,
                status="SUCCESS"
            )
        
        return success, next_stage, error
    
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
        stage = await PipelineStageRepository.create(
            pipeline_id, stage_name, input_data, session
        )
        
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
        session: AsyncSession,
        metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        完成阶段

        Args:
            stage: 阶段对象
            output_data: 输出数据
            success: 是否成功
            session: 数据库会话
            metrics: 可观测性指标（可选）
                - input_tokens: 输入 Token 数
                - output_tokens: 输出 Token 数
                - duration_ms: 执行耗时（毫秒）
                - retry_count: 重试次数
                - reasoning: AI 推理过程
        """
        await PipelineStageRepository.complete(
            stage, output_data, success, session, metrics
        )
        
        info(
            "Pipeline 阶段完成",
            pipeline_id=stage.pipeline_id,
            stage=stage.name.value,
            status=stage.status.value,
            input_tokens=stage.input_tokens,
            output_tokens=stage.output_tokens,
            duration_ms=stage.duration_ms,
            retry_count=stage.retry_count
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
        stage = await PipelineStageRepository.mark_for_rerun(
            pipeline_id, stage_name, rejection_feedback, session
        )
        
        if stage:
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
        await PipelineRepository.set_running(pipeline, session)
        
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
        await PipelineRepository.set_paused(pipeline, session)
        
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
        await PipelineRepository.set_failed(pipeline, session)
        
        info(
            "Pipeline 状态更新为 FAILED",
            pipeline_id=pipeline.id,
            current_stage=pipeline.current_stage.value if pipeline.current_stage else None
        )
