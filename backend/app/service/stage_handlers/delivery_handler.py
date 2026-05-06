"""
代码交付阶段处理器

处理 DELIVERY 阶段：
- 创建独立临时工作区（隔离 Git 操作环境）
- Git 分支管理和代码提交
- PR 生成和创建
- 【新增】交付失败后打回 CODING/TESTING 阶段
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import settings
from app.core.sse_log_buffer import push_log
from app.core.timezone import now
from app.models.pipeline import StageName, PipelineStatus, StageStatus, PipelineStage
from app.service.git_provider import GitProviderService, GitProviderError
from app.service.platform_provider import GitHubProviderService
from app.service.pr_generator import PRGeneratorService
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService
from app.service.sandbox_manager import sandbox_manager


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
        rename_mappings = []
        delivery_workspace = None  # 独立交付工作区

        try:
            # 【绑定挂载架构】直接从 sandbox_manager 获取工作区路径
            # 避免依赖 SandboxOrchestrator 实例，防止进程重启后实例丢失
            sandbox_info = sandbox_manager.get_info(pipeline_id)
            if not sandbox_info:
                raise ValueError(f"Sandbox 未启动，无法执行 DELIVERY 阶段 (pipeline_id={pipeline_id})")

            sandbox_path = sandbox_info.project_path
            if not sandbox_path:
                raise ValueError("Sandbox 工作区路径为空，无法执行 DELIVERY 阶段")

            sandbox_dir = Path(sandbox_path)
            await push_log(
                pipeline_id,
                "info",
                f"Sandbox 工作区: {sandbox_dir.name}",
                stage="DELIVERY"
            )

            # 【关键改进】创建独立的交付工作区，隔离 Git 操作环境
            # 避免 Sandbox 工作区中的未跟踪文件、日志等影响 Git 操作
            delivery_workspace = Path(tempfile.mkdtemp(prefix=f"omniflow-delivery-{pipeline_id}-"))
            await push_log(
                pipeline_id,
                "info",
                f"创建独立交付工作区: {delivery_workspace.name}",
                stage="DELIVERY"
            )

            # 获取修改的文件列表
            modified_files = coding_output_data.get("modified_files", [])
            if not modified_files and generated_files:
                # 如果没有记录修改的文件列表，从 generated_files 推断
                modified_files = [f["file_path"] for f in generated_files]

            copied_count = len(modified_files)

            # 【关键改进】只复制修改过的文件到交付工作区，保持工作区干净
            for file_path in modified_files:
                src_file = sandbox_dir / file_path
                if src_file.exists():
                    dst_file = delivery_workspace / file_path
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)

            await push_log(
                pipeline_id,
                "info",
                f"已复制 {copied_count} 个修改的文件到交付工作区",
                stage="DELIVERY"
            )

            # Git 操作在独立的交付工作区执行
            git_service = GitProviderService(str(delivery_workspace))
            timestamp = now().strftime("%Y%m%d_%H%M%S")
            git_branch = f"devflow/pipeline-{pipeline_id}-{timestamp}"

            # 【关键改进】交付工作区是全新的，需要初始化 Git
            await push_log(
                pipeline_id,
                "info",
                "初始化 Git 仓库...",
                stage="DELIVERY"
            )
            remote_url = f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}.git"
            git_service.init_repo(remote_url=remote_url)

            # 【关键改进】从远程 main 分支创建本地分支，保持历史一致性
            await push_log(
                pipeline_id,
                "info",
                f"从远程 main 分支创建本地分支 {git_branch}...",
                stage="DELIVERY"
            )
            try:
                # 【修复】先创建 orphan 分支，然后 reset 到 origin/main，避免工作区文件冲突
                # 这样可以保留已复制的文件，同时设置正确的 Git 历史
                git_service._run_git_command(["checkout", "--orphan", git_branch], check=True)
                git_service._run_git_command(["reset", "--mixed", "origin/main"], check=False)
            except GitProviderError as e:
                # 如果分支已存在（极少见），则切换到该分支
                if "already exists" in str(e).lower():
                    await push_log(
                        pipeline_id,
                        "warning",
                        f"分支 {git_branch} 已存在，切换到该分支...",
                        stage="DELIVERY"
                    )
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
            output_data = {
                "git_branch": git_branch,
                "commit_hash": commit_hash,
                "pr_url": pr_url,
                "pr_created": pr_created,
                "execution_summary": {"success": copied_count, "total": len(modified_files)}
            }

            return StageResult.success_result(
                message="Delivery completed",
                output_data=output_data,
                status=PipelineStatus.SUCCESS,
                git_branch=git_branch,
                commit_hash=commit_hash,
                pr_url=pr_url
            )

        except Exception as e:
            await push_log(pipeline_id, "error", f"代码交付失败: {str(e)}", stage="DELIVERY")
            raise

        finally:
            # 【关键改进】清理独立交付工作区
            if delivery_workspace and delivery_workspace.exists():
                try:
                    shutil.rmtree(delivery_workspace, ignore_errors=True)
                    await push_log(
                        pipeline_id,
                        "info",
                        f"清理交付工作区: {delivery_workspace.name}",
                        stage="DELIVERY"
                    )
                except Exception as cleanup_error:
                    await push_log(
                        pipeline_id,
                        "warning",
                        f"清理交付工作区失败: {cleanup_error}",
                        stage="DELIVERY"
                    )

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
        """
        错误处理：交付失败后打回 CODING/TESTING 阶段

        不再直接标记 Pipeline 失败，而是：
        1. 记录 DELIVERY 阶段失败
        2. 重置 CODING 和 UNIT_TESTING 阶段状态
        3. 设置 Pipeline 为 PAUSED 状态，等待重新确认交付
        """
        from sqlmodel import select

        await push_log(
            context.pipeline_id,
            "error",
            f"代码交付阶段异常: {str(error)}",
            stage="DELIVERY"
        )
        await push_log(
            context.pipeline_id,
            "info",
            "交付失败，打回 CODING/TESTING 阶段等待重新确认...",
            stage="DELIVERY"
        )

        # 创建失败的 DELIVERY 阶段记录
        delivery_stage = PipelineStage(
            pipeline_id=context.pipeline_id,
            name=StageName.DELIVERY,
            status=StageStatus.FAILED,
            output_data={
                "error": str(error),
                "error_type": type(error).__name__,
                "rollback_to": "CODING/TESTING"
            }
        )
        context.session.add(delivery_stage)

        # 【关键】重置 CODING 和 UNIT_TESTING 阶段状态
        # 查询现有的 CODING 和 UNIT_TESTING 阶段
        stmt = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name.in_([StageName.CODING, StageName.UNIT_TESTING])
        )
        result = await context.session.execute(stmt)
        stages_to_reset = result.scalars().all()

        for stage in stages_to_reset:
            # 将阶段状态重置为 SUCCESS（保留输出数据，但允许重新触发交付）
            # 或者重置为 PENDING 如果需要重新执行
            stage.status = StageStatus.SUCCESS
            # 添加标记表示需要重新确认交付
            if stage.output_data is None:
                stage.output_data = {}
            stage.output_data["delivery_failed"] = True
            stage.output_data["delivery_error"] = str(error)
            context.session.add(stage)

        # 更新 Pipeline 状态为 PAUSED，等待重新确认
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if pipeline:
            # 设置当前阶段为 CODE_REVIEW（让用户在审批界面重新确认）
            pipeline.current_stage = StageName.CODE_REVIEW
            await WorkflowService.set_pipeline_paused(pipeline, context.session)

        await context.session.commit()

        await push_log(
            context.pipeline_id,
            "info",
            "Pipeline 已暂停，请在 CODE_REVIEW 阶段重新确认交付",
            stage="DELIVERY"
        )

        # 注意：不清理 SSE 日志缓冲区，因为 Pipeline 并未结束
        # 不停止 Sandbox，因为可能需要重新交付

        return StageResult(
            success=False,
            status=PipelineStatus.PAUSED,
            message=f"Delivery failed, rolled back to CODE_REVIEW for re-confirmation: {str(error)}",
            output_data={
                "error": str(error),
                "error_type": type(error).__name__,
                "rollback_to": "CODE_REVIEW",
                "requires_re_confirmation": True
            }
        )
