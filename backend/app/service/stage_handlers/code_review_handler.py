"""
代码审查阶段处理器

处理 CODE_REVIEW 阶段：
- 调用 CodeReviewerAgent 生成 AI 审查报告
- 保持 PAUSED 状态等待人工审批
- 批准后触发 DELIVERY 阶段
- 驳回后回退到 CODING 阶段
"""

from typing import Optional

from app.core.sse_log_buffer import push_log
from app.core.logging import error
from app.models.pipeline import StageName, PipelineStatus
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService
from app.agents import code_reviewer_agent


class CodeReviewHandler(StageHandler):
    """代码审查阶段处理器"""

    @property
    def stage_name(self) -> StageName:
        return StageName.CODE_REVIEW

    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取 CODING 和 UNIT_TESTING 阶段输出"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        # 获取 CODING 阶段输出
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.CODING
        )
        result = await context.session.execute(statement)
        coding_stage = result.scalar_one_or_none()

        coding_output = {}
        if coding_stage and coding_stage.output_data:
            coding_output = coding_stage.output_data
            context.input_data["coding_output"] = coding_output
            # 【修复】将 coder_output 提升到顶层，便于前端访问
            context.input_data["coder_output"] = coding_output.get("coder_output", {})
            context.input_data["files"] = coding_output.get("files", [])
            context.input_data["modified_files"] = coding_output.get("modified_files", [])

        # 获取 UNIT_TESTING 阶段输出
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.UNIT_TESTING
        )
        result = await context.session.execute(statement)
        testing_stage = result.scalar_one_or_none()

        testing_result = {}
        test_files = []
        if testing_stage and testing_stage.output_data:
            testing_output = testing_stage.output_data
            testing_result = testing_output.get("testing_result", {})
            test_files = testing_output.get("test_files", [])
            context.input_data["testing_result"] = testing_result
            context.input_data["test_files"] = test_files
            context.input_data["target_files"] = testing_output.get("target_files", {})

        # 获取或创建 CODE_REVIEW 阶段
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.CODE_REVIEW
        )
        result = await context.session.execute(statement)
        review_stage = result.scalar_one_or_none()

        if not review_stage:
            review_stage = await WorkflowService.create_stage(
                pipeline_id=context.pipeline_id,
                stage_name=self.stage_name,
                input_data=context.input_data,
                session=context.session
            )

        context.stage_id = review_stage.id
        await context.session.commit()

        return context

    async def execute(self, context: StageContext) -> StageResult:
        """执行代码审查阶段（调用 AI Agent 生成审查报告）"""
        await push_log(
            context.pipeline_id,
            "info",
            "开始 AI 代码审查分析...",
            stage="CODE_REVIEW"
        )

        # 【集成】调用 CodeReviewerAgent 生成审查报告
        review_report = await self._generate_review_report(context)

        await push_log(
            context.pipeline_id,
            "info",
            f"AI 代码审查完成，发现 {len(review_report.get('issues', []))} 个问题",
            stage="CODE_REVIEW"
        )

        # 【修复】将 CODING、TESTING 和审查报告数据写入 output_data
        output_data = {
            "testing_result": context.input_data.get("testing_result", {}),
            "coding_output": context.input_data.get("coding_output", {}),
            "target_files": context.input_data.get("target_files", {}),
            "coder_output": context.input_data.get("coder_output", {}),
            "files": context.input_data.get("files", []),
            "modified_files": context.input_data.get("modified_files", []),
            "test_files": context.input_data.get("test_files", []),
            # 【新增】AI 生成的审查报告
            "review_report": review_report,
        }

        # 保持 PAUSED 状态，等待人工审批
        return StageResult.success_result(
            message="Code review stage ready for approval",
            output_data=output_data,
            status=PipelineStatus.PAUSED
        )

    async def _generate_review_report(self, context: StageContext) -> dict:
        """
        调用 CodeReviewerAgent 生成审查报告

        Args:
            context: 阶段上下文，包含 CODING 和 TESTING 的输出数据

        Returns:
            dict: 审查报告数据
        """
        try:
            # 准备输入数据
            file_changes = context.input_data.get("files", [])
            test_results = context.input_data.get("testing_result", {})
            coding_output = context.input_data.get("coding_output", {})

            # 获取设计方案（从 DESIGN 阶段的输出）
            design_doc = await self._get_design_doc(context)

            # 获取接口契约
            interface_specs = coding_output.get("interface_specs", [])

            # 构建 Agent 初始状态
            initial_state = {
                "file_changes": file_changes,
                "test_results": test_results,
                "design_doc": design_doc,
                "interface_specs": interface_specs,
            }

            # 执行 Agent
            result = await code_reviewer_agent.execute(
                pipeline_id=context.pipeline_id,
                stage_name="CODE_REVIEW",
                initial_state=initial_state
            )

            if result.get("success") and result.get("output"):
                review_output = result["output"]
                report = review_output.get("review_report", {})
                await push_log(
                    context.pipeline_id,
                    "thought",
                    f"审查报告生成成功: {report.get('overall_assessment', '')[:100]}...",
                    stage="CODE_REVIEW"
                )
                return report
            else:
                error_msg = result.get("error", "未知错误")
                await push_log(
                    context.pipeline_id,
                    "warning",
                    f"审查报告生成失败: {error_msg}",
                    stage="CODE_REVIEW"
                )
                return self._create_fallback_report(error_msg)

        except Exception as e:
            error(f"[Pipeline {context.pipeline_id}] 生成审查报告异常: {e}")
            await push_log(
                context.pipeline_id,
                "error",
                f"生成审查报告异常: {str(e)}",
                stage="CODE_REVIEW"
            )
            return self._create_fallback_report(str(e))

    def _create_fallback_report(self, error_msg: str) -> dict:
        """创建降级审查报告（当 Agent 执行失败时）"""
        return {
            "issues": [],
            "overall_assessment": f"AI 审查报告生成失败: {error_msg}。请人工仔细审查代码。",
            "summary": "审查报告生成异常",
            "improvement_suggestions": ["请人工仔细审查代码", "检查代码是否符合设计规范"],
            "risk_level": "medium",
            "approval_recommendation": "approve_with_caution"
        }

    async def _get_design_doc(self, context: StageContext) -> str:
        """获取设计方案文档"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        try:
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == context.pipeline_id,
                PipelineStage.name == StageName.DESIGN
            )
            result = await context.session.execute(statement)
            design_stage = result.scalar_one_or_none()

            if design_stage and design_stage.output_data:
                output = design_stage.output_data
                # 尝试提取技术设计
                if isinstance(output, dict):
                    return output.get("technical_design", "")
        except Exception as e:
            error(f"[Pipeline {context.pipeline_id}] 获取设计方案失败: {e}")

        return ""

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：更新阶段状态"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        statement = select(PipelineStage).where(PipelineStage.id == context.stage_id)
        query_result = await context.session.execute(statement)
        review_stage = query_result.scalar_one_or_none()

        if review_stage:
            await WorkflowService.complete_stage(
                stage=review_stage,
                output_data=result.output_data,
                success=result.success,
                session=context.session
            )

        await context.session.commit()

    async def handle_error(
        self,
        context: StageContext,
        error: Exception
    ) -> StageResult:
        """错误处理"""
        await push_log(
            context.pipeline_id,
            "error",
            f"代码审查阶段异常: {str(error)}",
            stage="CODE_REVIEW"
        )
        return StageResult.failure_result(
            message=f"Code review failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )

    async def on_approved(
        self,
        context: StageContext,
        notes: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> StageResult:
        """
        CODE_REVIEW 阶段被批准后：触发 DELIVERY 阶段
        """
        from app.service.stage_handlers import DeliveryHandler

        await push_log(
            context.pipeline_id,
            "info",
            "代码审查已批准，开始代码交付...",
            stage="CODE_REVIEW"
        )

        # 执行 DELIVERY 阶段
        delivery_handler = DeliveryHandler()
        delivery_context = StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={}
        )

        delivery_result = await delivery_handler.run(delivery_context)

        return StageResult(
            success=delivery_result.success,
            status=delivery_result.status,
            message=delivery_result.message,
            output_data={
                "previous_stage": StageName.CODE_REVIEW.value,
                "next_stage": StageName.DELIVERY.value,
                "delivery_result": delivery_result.output_data
            },
            git_branch=delivery_result.git_branch,
            commit_hash=delivery_result.commit_hash,
            pr_url=delivery_result.pr_url
        )

    async def on_rejected(
        self,
        context: StageContext,
        reason: str,
        suggested_changes: Optional[str] = None
    ) -> StageResult:
        """
        CODE_REVIEW 阶段被驳回后：回退到 CODING 重新生成
        """
        from app.service.stage_handlers import CodingHandler, TestingHandler

        await push_log(
            context.pipeline_id,
            "info",
            f"代码审查被驳回，原因: {reason}，回退到代码生成阶段...",
            stage="CODE_REVIEW"
        )

        # 标记 CODING 阶段需要重新执行
        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}

        await WorkflowService.mark_stage_for_rerun(
            pipeline_id=context.pipeline_id,
            stage_name=StageName.CODING,
            rejection_feedback=rejection_feedback,
            session=context.session
        )

        # 重新触发 CODING 阶段
        coding_handler = CodingHandler()
        coding_context = StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={},
            rejection_feedback=rejection_feedback
        )

        coding_result = await coding_handler.run(coding_context)

        if coding_result.success:
            # CODING 成功后，执行 TESTING
            testing_handler = TestingHandler()
            testing_result = await testing_handler.run(StageContext(
                pipeline_id=context.pipeline_id,
                session=context.session,
                input_data={}
            ))

            return StageResult(
                success=testing_result.success,
                status=testing_result.status,
                message="Coding and unit testing re-executed after rejection",
                output_data={
                    "previous_stage": StageName.CODE_REVIEW.value,
                    "current_stage": StageName.UNIT_TESTING.value,
                    "test_generated": testing_result.output_data.get("testing_result", {}).get("test_generated", False),
                    "test_run_success": testing_result.output_data.get("testing_result", {}).get("test_run_success", False)
                }
            )
        else:
            return StageResult.failure_result(
                message="Code generation failed after rejection",
                output_data={
                    "previous_stage": StageName.CODE_REVIEW.value,
                    "current_stage": StageName.CODING.value,
                    "error": coding_result.message
                }
            )
