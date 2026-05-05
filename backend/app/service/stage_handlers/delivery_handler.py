"""
代码交付阶段处理器

处理 DELIVERY 阶段：
- 创建临时工作区
- Git 分支管理和代码提交
- PR 生成和创建
"""

import asyncio
from pathlib import Path
from typing import Any, Dict

from app.core.sse_log_buffer import push_log
from app.core.timezone import now
from app.models.pipeline import StageName, PipelineStatus, StageStatus, PipelineStage
from app.service.git_provider import GitProviderService, GitProviderError
from app.service.platform_provider import GitHubProviderService
from app.service.pr_generator import PRGeneratorService
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService
from app.service.sandbox_manager import sandbox_manager
from app.service.sandbox_orchestrator import get_sandbox_orchestrator


class DeliveryHandler(StageHandler):
    """代码交付阶段处理器"""

    @property
    def stage_name(self) -> StageName:
        return StageName.DELIVERY

    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取 CODING 阶段输出和 Pipeline 信息"""
        from sqlmodel import select

        # 获取 Pipeline
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if not pipeline:
            raise ValueError(f"Pipeline {context.pipeline_id} not found")

        context.input_data["requirement_summary"] = (
            pipeline.description[:80] if pipeline.description else f"Pipeline #{context.pipeline_id}"
        )

        # 获取 CODING 阶段输出
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.CODING
        )
        result = await context.session.execute(statement)
        coding_stage = result.scalar_one_or_none()

        if not coding_stage or not coding_stage.output_data:
            raise ValueError("No coding output found for DELIVERY stage")

        context.input_data["coding_output"] = coding_stage.output_data

        return context

    async def execute(self, context: StageContext) -> StageResult:
        """执行代码交付"""
        pipeline_id = context.pipeline_id
        requirement_summary = context.input_data.get("requirement_summary", "")
        coding_output_data = context.input_data.get("coding_output", {})
        multi_agent_output = coding_output_data.get("multi_agent_output", {})
        generated_files = multi_agent_output.get("files", [])

        git_branch = None
        commit_hash = None
        pr_url = None
        pr_created = False
        copied_count = 0

        try:
            # 【绑定挂载架构】直接使用 Sandbox 的宿主机工作区目录
            orchestrator = get_sandbox_orchestrator(pipeline_id)
            workspace_path = orchestrator.get_workspace_path()

            if not workspace_path:
                raise ValueError("Sandbox 工作区未初始化，无法执行 DELIVERY 阶段")

            workspace_dir = Path(workspace_path)
            await push_log(
                pipeline_id,
                "info",
                f"使用 Sandbox 工作区: {workspace_dir.name}",
                stage="DELIVERY"
            )

            # 【绑定挂载架构】文件已在宿主机工作区，无需复制
            # Agent 在 Sandbox 中的修改直接反映到宿主机 temp_dir
            modified_files = coding_output_data.get("modified_files", [])
            if not modified_files and generated_files:
                # 如果没有记录修改的文件列表，从 generated_files 推断
                modified_files = [f["file_path"] for f in generated_files]

            copied_count = len(modified_files)
            await push_log(
                pipeline_id,
                "info",
                f"工作区已有 {copied_count} 个修改的文件（绑定挂载）",
                stage="DELIVERY"
            )

            # Git 操作
            git_service = GitProviderService(str(workspace_dir))
            timestamp = now().strftime("%Y%m%d_%H%M%S")
            git_branch = f"devflow/pipeline-{pipeline_id}-{timestamp}"

            try:
                git_service.create_branch(git_branch)
            except GitProviderError as e:
                if "分支已存在" in str(e):
                    git_service.checkout_branch(git_branch)
                else:
                    raise

            # Git 提交
            git_service.add_files()
            if git_service.has_changes():
                commit_message = f"feat(pipeline-{pipeline_id}): {multi_agent_output.get('summary', '代码生成')[:100]}"
                git_service.commit_changes(commit_message)
                commit_hash = git_service.get_last_commit_hash()

            # 推送分支
            await push_log(
                pipeline_id,
                "info",
                f"推送代码到远程分支 {git_branch}...",
                stage="DELIVERY"
            )
            git_service.push_branch(git_branch)

            # 生成 PR 描述
            pr_description = await PRGeneratorService.generate_pr_description(
                pipeline_id=pipeline_id,
                multi_agent_output=multi_agent_output,
                execution_summary={"success": copied_count, "total": len(modified_files)},
                git_service=git_service
            )

            # 创建 PR
            pr_title = f"OmniFlowAI: {requirement_summary}"
            async with GitHubProviderService() as github_service:
                pr_result = await github_service.create_pull_request(
                    head_branch=git_branch,
                    title=pr_title,
                    body=pr_description,
                    base_branch="main"
                )

            if pr_result.success:
                pr_url = pr_result.pr_url
                pr_created = True
                await push_log(pipeline_id, "info", f"PR 创建成功: {pr_url}", stage="DELIVERY")
            else:
                pr_created = False
                await push_log(pipeline_id, "warning", f"PR 创建失败: {pr_result.error}", stage="DELIVERY")

            # 返回成功结果
            return StageResult.success_result(
                message="Delivery completed",
                output_data={
                    "git_branch": git_branch,
                    "commit_hash": commit_hash,
                    "pr_url": pr_url,
                    "pr_created": pr_created,
                    "execution_summary": {"success": copied_count, "total": len(modified_files)}
                },
                status=PipelineStatus.SUCCESS,
                git_branch=git_branch,
                commit_hash=commit_hash,
                pr_url=pr_url
            )

        except Exception as e:
            await push_log(pipeline_id, "error", f"代码交付失败: {str(e)}", stage="DELIVERY")
            raise

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：创建 DELIVERY 阶段记录，更新 Pipeline 状态"""
        # 创建 DELIVERY 阶段
        delivery_stage = PipelineStage(
            pipeline_id=context.pipeline_id,
            name=StageName.DELIVERY,
            status=StageStatus.SUCCESS if result.success else StageStatus.FAILED,
            output_data=result.output_data
        )
        context.session.add(delivery_stage)
        await context.session.flush()

        # 更新 Pipeline 状态
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if pipeline:
            pipeline.current_stage = StageName.DELIVERY
            if result.success:
                await WorkflowService.set_pipeline_success(pipeline, context.session)
            else:
                await WorkflowService.set_pipeline_failed(pipeline, context.session)

        # 【修复】先发送完成日志，再清理 SSE 缓冲区，避免竞态条件导致最后一条日志丢失
        await push_log(context.pipeline_id, "info", "✅ Pipeline 执行成功完成！", stage="DELIVERY")

        # 【关键修复】Pipeline 完成时停止 Sandbox
        try:
            await sandbox_manager.stop(context.pipeline_id)
            await push_log(context.pipeline_id, "info", "Sandbox 已停止", stage="DELIVERY")
        except Exception as e:
            await push_log(context.pipeline_id, "warning", f"停止 Sandbox 时出错: {str(e)}", stage="DELIVERY")

        await context.session.commit()

        # 【修复】确保所有日志发送完成后再清理 SSE 日志缓冲区
        await asyncio.sleep(0.5)
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
            f"代码交付阶段异常: {str(error)}",
            stage="DELIVERY"
        )

        # 创建失败的 DELIVERY 阶段
        delivery_stage = PipelineStage(
            pipeline_id=context.pipeline_id,
            name=StageName.DELIVERY,
            status=StageStatus.FAILED,
            output_data={"error": str(error), "error_type": type(error).__name__}
        )
        context.session.add(delivery_stage)

        # 更新 Pipeline 为失败状态
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if pipeline:
            await WorkflowService.set_pipeline_failed(pipeline, context.session)

        await context.session.commit()

        # 清理 SSE 日志缓冲区
        from app.core.sse_log_buffer import remove_buffer
        remove_buffer(context.pipeline_id)

        # 【关键修复】Pipeline 失败时停止 Sandbox
        try:
            await sandbox_manager.stop(context.pipeline_id)
        except Exception:
            pass  # 忽略错误

        return StageResult.failure_result(
            message=f"Delivery failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )
