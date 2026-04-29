"""
需求分析阶段处理器

处理 REQUIREMENT 阶段：
- 调用 ArchitectAgent 分析需求
- 支持带反馈的重新分析
"""

from typing import Any, Dict, Optional

from app.core.logging import info, error
from app.core.sse_log_buffer import push_log
from app.models.pipeline import StageName, PipelineStatus
from app.service.agent_coordinator import AgentCoordinatorService
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService


class RequirementHandler(StageHandler):
    """需求分析阶段处理器"""
    
    @property
    def stage_name(self) -> StageName:
        return StageName.REQUIREMENT
    
    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取需求描述和元素上下文"""
        # 从 input_data 获取必要信息
        requirement = context.get("requirement", "")
        element_context = context.get("element_context")
        
        if not requirement:
            raise ValueError("Requirement is required for REQUIREMENT stage")
        
        # 阶段记录在 Pipeline 创建时已经创建，这里获取 stage_id
        from app.repositories import PipelineStageRepository
        stage = await PipelineStageRepository.get_by_pipeline_and_name(
            context.pipeline_id, self.stage_name, context.session
        )
        
        if stage:
            context.stage_id = stage.id
        
        return context
    
    async def execute(self, context: StageContext) -> StageResult:
        """执行需求分析"""
        pipeline_id = context.pipeline_id
        requirement = context.get("requirement", "")
        element_context = context.get("element_context")
        rejection_feedback = context.rejection_feedback
        
        await push_log(pipeline_id, "info", "开始需求分析...", stage="REQUIREMENT")
        
        try:
            if rejection_feedback:
                # 带反馈的重新分析
                result = await AgentCoordinatorService.run_architect_with_feedback(
                    pipeline_id=pipeline_id,
                    requirement=requirement,
                    reason=rejection_feedback.get("reason", ""),
                    suggested_changes=rejection_feedback.get("suggested_changes"),
                    session=context.session
                )
            else:
                # 首次分析
                result = await AgentCoordinatorService.run_architect_analysis(
                    pipeline_id=pipeline_id,
                    requirement=requirement,
                    element_context=element_context,
                    session=context.session
                )
            
            if result["success"]:
                await push_log(pipeline_id, "info", "需求分析完成，等待审批", stage="REQUIREMENT")
                return StageResult.success_result(
                    message="Requirement analysis completed",
                    output_data=result.get("output", {}),
                    status=PipelineStatus.PAUSED
                )
            else:
                error_msg = result.get("error", "Unknown error")
                await push_log(pipeline_id, "error", f"需求分析失败: {error_msg}", stage="REQUIREMENT")
                return StageResult.failure_result(
                    message=f"Requirement analysis failed: {error_msg}",
                    output_data={"error": error_msg}
                )
                
        except Exception as e:
            error_msg = str(e)
            error("Architect analysis failed", pipeline_id=pipeline_id, error=error_msg, exc_info=True)
            await push_log(pipeline_id, "error", f"需求分析失败: {error_msg[:500]}", stage="REQUIREMENT")
            raise
    
    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：更新 Pipeline 状态"""
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        
        if pipeline:
            if result.success:
                await WorkflowService.set_pipeline_paused(pipeline, context.session)
            else:
                await WorkflowService.set_pipeline_failed(pipeline, context.session)
                from app.core.sse_log_buffer import remove_buffer
                remove_buffer(context.pipeline_id)
    
    async def handle_error(
        self,
        context: StageContext,
        error: Exception
    ) -> StageResult:
        """错误处理"""
        await push_log(
            context.pipeline_id,
            "error",
            f"需求分析阶段异常: {str(error)}",
            stage="REQUIREMENT"
        )
        return StageResult.failure_result(
            message=f"Requirement analysis failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )
