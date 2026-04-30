"""
技术设计阶段处理器

处理 DESIGN 阶段：
- 调用 DesignerAgent 进行技术设计
- 支持两层代码上下文注入
- 支持带反馈的重新设计
"""

from app.core.logging import info, error
from app.core.sse_log_buffer import push_log
from app.models.pipeline import StageName, PipelineStatus
from app.service.agent_coordinator import AgentCoordinatorService
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService


class DesignHandler(StageHandler):
    """技术设计阶段处理器"""
    
    @property
    def stage_name(self) -> StageName:
        return StageName.DESIGN
    
    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取 REQUIREMENT 阶段输出"""
        from app.service.repositories import PipelineStageRepository
        
        # 获取 REQUIREMENT 阶段输出作为输入
        requirement_stage = await PipelineStageRepository.get_by_pipeline_and_name(
            context.pipeline_id, StageName.REQUIREMENT, context.session
        )
        
        if not requirement_stage or not requirement_stage.output_data:
            raise ValueError("No requirement output found for DESIGN stage")
        
        context.previous_output = requirement_stage.output_data
        
        # 创建 DESIGN 阶段记录
        design_stage = await WorkflowService.create_stage(
            pipeline_id=context.pipeline_id,
            stage_name=self.stage_name,
            input_data=context.previous_output,
            session=context.session
        )
        context.stage_id = design_stage.id
        
        return context
    
    async def execute(self, context: StageContext) -> StageResult:
        """执行技术设计"""
        pipeline_id = context.pipeline_id
        rejection_feedback = context.rejection_feedback
        
        await push_log(pipeline_id, "info", "开始技术设计...", stage="DESIGN")
        
        try:
            if rejection_feedback:
                # 带反馈的重新设计
                result = await AgentCoordinatorService.run_designer_with_feedback(
                    pipeline_id=pipeline_id,
                    reason=rejection_feedback.get("reason", ""),
                    suggested_changes=rejection_feedback.get("suggested_changes"),
                    session=context.session
                )
            else:
                # 首次设计 - 传入 stage_id 避免重复创建
                result = await AgentCoordinatorService.run_designer_analysis(
                    pipeline_id=pipeline_id,
                    session=context.session,
                    design_stage_id=context.stage_id
                )
            
            if result["success"]:
                await push_log(pipeline_id, "info", "技术设计完成，等待审批", stage="DESIGN")
                return StageResult.success_result(
                    message="Technical design completed",
                    output_data=result.get("output", {}),
                    status=PipelineStatus.PAUSED
                )
            else:
                error_msg = result.get("error", "Unknown error")
                await push_log(pipeline_id, "error", f"技术设计失败: {error_msg}", stage="DESIGN")
                return StageResult.failure_result(
                    message=f"Technical design failed: {error_msg}",
                    output_data={"error": error_msg}
                )
                
        except Exception as e:
            error_msg = str(e)
            error("Designer analysis failed", pipeline_id=pipeline_id, error=error_msg, exc_info=True)
            await push_log(pipeline_id, "error", f"技术设计失败: {error_msg[:500]}", stage="DESIGN")
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
    
    async def handle_error(
        self,
        context: StageContext,
        error: Exception
    ) -> StageResult:
        """错误处理"""
        await push_log(
            context.pipeline_id,
            "error",
            f"技术设计阶段异常: {str(error)}",
            stage="DESIGN"
        )
        return StageResult.failure_result(
            message=f"Technical design failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )
