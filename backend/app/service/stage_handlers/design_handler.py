"""
技术设计阶段处理器

处理 DESIGN 阶段：
- 调用 DesignerAgent 进行技术设计
- 支持两层代码上下文注入
- 支持带反馈的重新设计
"""

from typing import Optional

from app.core.logging import info, error
from app.core.sse_log_buffer import push_log
from app.core.contract_alignment import (
    verify_contract_alignment,
    build_alignment_feedback,
    verify_criteria_alignment,
    build_criteria_alignment_feedback,
    ContractMisalignmentError,
    CriteriaAlignmentError
)
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
        from app.repositories import PipelineStageRepository
        
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
        """执行技术设计（带契约对齐校验和重试）"""
        pipeline_id = context.pipeline_id
        rejection_feedback = context.rejection_feedback
        
        await push_log(pipeline_id, "info", "开始技术设计...", stage="DESIGN")
        
        # 获取 REQUIREMENT 阶段的输出（包含 required_symbols）
        from app.repositories import PipelineStageRepository
        requirement_stage = await PipelineStageRepository.get_by_pipeline_and_name(
            pipeline_id, StageName.REQUIREMENT, context.session
        )
        required_symbols = []
        if requirement_stage and requirement_stage.output_data:
            required_symbols = requirement_stage.output_data.get("required_symbols", [])
        
        # 最大重试次数
        max_retries = 3
        retry_count = 0
        alignment_feedback = None
        
        while retry_count < max_retries:
            try:
                # 构建反馈信息（如果有）
                feedback_to_use = rejection_feedback
                if alignment_feedback:
                    if feedback_to_use:
                        feedback_to_use["suggested_changes"] = alignment_feedback
                    else:
                        feedback_to_use = {"reason": "契约对齐失败", "suggested_changes": alignment_feedback}
                
                if feedback_to_use:
                    # 带反馈的重新设计
                    result = await AgentCoordinatorService.run_designer_with_feedback(
                        pipeline_id=pipeline_id,
                        reason=feedback_to_use.get("reason", ""),
                        suggested_changes=feedback_to_use.get("suggested_changes"),
                        session=context.session
                    )
                else:
                    # 首次设计 - 传入 stage_id 避免重复创建
                    result = await AgentCoordinatorService.run_designer_analysis(
                        pipeline_id=pipeline_id,
                        session=context.session,
                        design_stage_id=context.stage_id
                    )
                
                if not result["success"]:
                    error_msg = result.get("error", "Unknown error")
                    await push_log(pipeline_id, "error", f"技术设计失败: {error_msg}", stage="DESIGN")
                    return StageResult.failure_result(
                        message=f"Technical design failed: {error_msg}",
                        output_data={"error": error_msg}
                    )
                
                # 【契约对齐校验】检查 Designer 输出是否包含所有必需符号
                design_output = result.get("output", {})
                interface_specs = design_output.get("interface_specs", [])
                criteria_mappings = design_output.get("criteria_mappings", [])
                
                # 1. 检查 required_symbols 对齐
                is_symbol_aligned, missing_symbols, extra_symbols = verify_contract_alignment(
                    required_symbols, interface_specs
                )
                
                # 2. 检查验收标准对齐（新增）
                acceptance_criteria = context.previous_output.get("acceptance_criteria", [])
                is_criteria_aligned, missing_criteria, invalid_mappings = verify_criteria_alignment(
                    acceptance_criteria, criteria_mappings, interface_specs
                )
                
                # 合并对齐结果
                is_aligned = is_symbol_aligned and is_criteria_aligned
                
                if is_aligned:
                    await push_log(pipeline_id, "info", f"✅ 契约对齐校验通过（共 {len(interface_specs)} 个符号，{len(criteria_mappings)} 个映射）", stage="DESIGN")
                    await push_log(pipeline_id, "info", "技术设计完成，等待审批", stage="DESIGN")
                    return StageResult.success_result(
                        message="Technical design completed",
                        output_data=design_output,
                        status=PipelineStatus.PAUSED
                    )
                else:
                    # 契约未对齐，构建反馈信息
                    retry_count += 1
                    feedback_parts = []
                    
                    if not is_symbol_aligned:
                        symbol_feedback = build_alignment_feedback(missing_symbols, required_symbols)
                        feedback_parts.append(f"【符号对齐问题】\n{symbol_feedback}")
                        await push_log(
                            pipeline_id, 
                            "warning", 
                            f"⚠️ 符号对齐校验失败，缺失符号: {missing_symbols}", 
                            stage="DESIGN"
                        )
                    
                    if not is_criteria_aligned:
                        criteria_feedback = build_criteria_alignment_feedback(
                            missing_criteria, invalid_mappings, acceptance_criteria
                        )
                        feedback_parts.append(f"【验收标准对齐问题】\n{criteria_feedback}")
                        await push_log(
                            pipeline_id, 
                            "warning", 
                            f"⚠️ 验收标准对齐校验失败，缺失标准: {missing_criteria}", 
                            stage="DESIGN"
                        )
                    
                    alignment_feedback = "\n\n".join(feedback_parts)
                    
                    await push_log(
                        pipeline_id, 
                        "warning", 
                        f"⚠️ 契约对齐校验失败（第 {retry_count}/{max_retries} 次尝试）", 
                        stage="DESIGN"
                    )
                    
                    if retry_count >= max_retries:
                        # 重试次数用尽，返回失败
                        error_msg = "契约对齐失败"
                        if missing_symbols:
                            error_msg += f"，缺失符号: {missing_symbols}"
                        if missing_criteria:
                            error_msg += f"，缺失验收标准映射: {missing_criteria}"
                        await push_log(pipeline_id, "error", f"❌ {error_msg}", stage="DESIGN")
                        raise ContractMisalignmentError(
                            error_msg, 
                            missing_symbols=missing_symbols,
                            missing_criteria=missing_criteria
                        )
                    
                    # 继续重试
                    continue
                    
            except ContractMisalignmentError:
                raise
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

    async def on_approved(
        self,
        context: StageContext,
        notes: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> StageResult:
        """
        DESIGN 阶段被批准后：触发后台 CODING 任务
        
        注意：此阶段需要后台异步执行，避免 HTTP 超时
        """
        from app.models.pipeline import PipelineStatus
        
        await push_log(
            context.pipeline_id,
            "info",
            "技术设计已批准，代码生成任务将在后台启动...",
            stage="DESIGN"
        )
        
        # 返回 async=True 信息，由 PipelineService 处理后台任务
        return StageResult.success_result(
            message="代码生成任务已在后台启动，请通过日志监控进度",
            output_data={
                "previous_stage": StageName.DESIGN.value,
                "next_stage": StageName.CODING.value,
                "async": True,
                "requires_background_task": True
            },
            status=PipelineStatus.RUNNING
        )
    
    async def on_rejected(
        self,
        context: StageContext,
        reason: str,
        suggested_changes: Optional[str] = None
    ) -> StageResult:
        """
        DESIGN 阶段被驳回后：重新执行 DESIGN 阶段
        """
        await push_log(
            context.pipeline_id,
            "info",
            f"技术设计被驳回，原因: {reason}，重新设计...",
            stage="DESIGN"
        )
        
        # 重新执行当前阶段
        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}
        
        result = await self.run(StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={},
            rejection_feedback=rejection_feedback
        ))
        
        return StageResult(
            success=result.success,
            status=result.status,
            message=result.message,
            output_data={
                "previous_stage": StageName.DESIGN.value,
                "current_stage": StageName.DESIGN.value,
                "feedback": rejection_feedback
            }
        )
