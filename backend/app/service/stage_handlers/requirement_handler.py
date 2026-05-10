"""
需求分析阶段处理器（使用 AgentCoordinatorService）

使用统一的 AgentCoordinatorService 构建 Agent 上下文
与 E2E 测试脚本保持一致
"""

from typing import Any, Dict, Optional

from app.core.logging import info, error
from app.core.sse_log_buffer import push_log
from app.core.config import settings
from app.agents.architect import architect_agent
from app.models.pipeline import StageName, PipelineStatus, StageStatus
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService
from app.service.agent_coordinator_service import agent_coordinator_service


class RequirementHandler(StageHandler):
    """需求分析阶段处理器（使用统一服务）"""

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
        from app.models.pipeline import StageStatus

        stage = await PipelineStageRepository.get_by_pipeline_and_name(
            context.pipeline_id, self.stage_name, context.session
        )

        if stage:
            context.stage_id = stage.id
            # 【修复】将 stage 状态更新为 RUNNING，前端才能显示"执行中"
            stage.status = StageStatus.RUNNING
            await context.session.commit()

        return context

    async def execute(self, context: StageContext) -> StageResult:
        """执行需求分析（使用 AgentCoordinatorService）"""
        import time
        phase_timings = {}
        t0 = time.perf_counter()

        pipeline_id = context.pipeline_id
        requirement = context.get("requirement", "")
        element_context = context.get("element_context")

        await push_log(pipeline_id, "info", "开始需求分析...", stage="REQUIREMENT")

        try:
            # 【统一】使用 AgentCoordinatorService 构建上下文
            project_path = settings.TARGET_PROJECT_PATH

            # 构建 ArchitectAgent 上下文
            t1 = time.perf_counter()
            architect_context = await agent_coordinator_service.build_architect_context(
                requirement=requirement,
                element_context=element_context,
                pipeline_id=pipeline_id
            )
            phase_timings["build_context"] = int((time.perf_counter() - t1) * 1000)

            await push_log(
                pipeline_id,
                "info",
                f"调用 ArchitectAgent (requirement: {len(requirement)} chars)",
                stage="REQUIREMENT"
            )

            # 【关键修复】为 ArchitectAgent 注入 SandboxFileService，确保在沙箱模式下执行
            from app.service.sandbox_file_service import SandboxFileService
            file_service = SandboxFileService(pipeline_id)
            architect_agent.set_file_service(file_service)

            # 调用 ArchitectAgent
            t2 = time.perf_counter()
            arch_result = await architect_agent.analyze(
                requirement=architect_context["requirement"],
                element_context=architect_context["element_context"],
                pipeline_id=pipeline_id,
                project_path=project_path
            )
            phase_timings["architect_analyze"] = int((time.perf_counter() - t2) * 1000)

            # 保存 Agent 调试信息
            self._save_agent_log(
                agent_name="ArchitectAgent",
                stage="analyze",
                input_data=architect_context,
                output_data=arch_result,
                system_prompt=architect_agent.system_prompt
            )

            if not arch_result.get("success"):
                error_msg = arch_result.get("error", "Unknown error")
                await push_log(pipeline_id, "error", f"需求分析失败: {error_msg}", stage="REQUIREMENT")
                return StageResult.failure_result(
                    message=f"Requirement analysis failed: {error_msg}",
                    output_data={"error": error_msg}
                )

            arch_output = arch_result.get("output", {})
            acceptance_criteria = arch_output.get("acceptance_criteria", [])

            await push_log(
                pipeline_id,
                "info",
                f"需求分析完成，验收标准: {acceptance_criteria}",
                stage="REQUIREMENT"
            )
            phase_timings["total"] = int((time.perf_counter() - t0) * 1000)
            await push_log(
                pipeline_id,
                "info",
                f"需求分析完成，等待审批",
                stage="REQUIREMENT"
            )

            # 记录分阶段耗时日志
            info(
                "REQUIREMENT 阶段耗时分析",
                pipeline_id=pipeline_id,
                build_context_ms=phase_timings.get("build_context", 0),
                architect_analyze_ms=phase_timings.get("architect_analyze", 0),
                total_ms=phase_timings.get("total", 0),
            )

            # 返回成功，状态为 PAUSED（等待审批）
            return StageResult.success_result(
                message="Requirement analysis completed",
                output_data=arch_output,
                status=PipelineStatus.PAUSED,
                metrics=self._build_metrics(arch_result, architect_context, arch_output)
            )

        except Exception as e:
            error_msg = str(e)
            error("Architect analysis failed", pipeline_id=pipeline_id, error=error_msg, exc_info=True)
            await push_log(pipeline_id, "error", f"需求分析失败: {error_msg[:500]}", stage="REQUIREMENT")
            raise

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：保存 Stage 输出并更新 Pipeline 状态"""
        await self._save_stage_result(context, result)
        await self._update_pipeline_after_stage(context, result)

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

    async def on_approved(
        self,
        context: StageContext,
        notes: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> StageResult:
        """
        REQUIREMENT 阶段被批准后：触发 DESIGN 阶段
        """
        from app.service.stage_handlers import DesignHandler

        await push_log(
            context.pipeline_id,
            "info",
            "需求分析已批准，开始技术设计...",
            stage="REQUIREMENT"
        )

        # 创建 DESIGN 阶段的 Handler 并执行
        design_handler = DesignHandler()
        design_context = StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={}
        )

        result = await design_handler.run(design_context)

        return StageResult(
            success=result.success,
            status=result.status,
            message=result.message,
            output_data={
                "previous_stage": StageName.REQUIREMENT.value,
                "next_stage": StageName.DESIGN.value,
                "design_result": result.output_data
            },
            git_branch=result.git_branch,
            commit_hash=result.commit_hash,
            pr_url=result.pr_url
        )

    async def on_rejected(
        self,
        context: StageContext,
        reason: str,
        suggested_changes: Optional[str] = None
    ) -> StageResult:
        """
        REQUIREMENT 阶段被驳回后：重新执行 REQUIREMENT 阶段
        """
        await push_log(
            context.pipeline_id,
            "info",
            f"需求分析被驳回，原因: {reason}，重新分析...",
            stage="REQUIREMENT"
        )

        # 获取 pipeline 描述
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )

        if not pipeline:
            return StageResult.failure_result("Pipeline not found")

        # 重新执行当前阶段
        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}

        result = await self.run(StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={"requirement": pipeline.description},
            rejection_feedback=rejection_feedback
        ))

        return StageResult(
            success=result.success,
            status=result.status,
            message=result.message,
            output_data={
                "previous_stage": StageName.REQUIREMENT.value,
                "current_stage": StageName.REQUIREMENT.value,
                "feedback": rejection_feedback
            }
        )
