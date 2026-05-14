"""
代码交付阶段处理器

处理 DELIVERY 阶段：
- 创建独立临时工作区（隔离 Git 操作环境）
- Git 分支管理和代码提交
- PR 生成和创建
- 【新增】交付失败后打回 CODING/TESTING 阶段
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

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
        coding_stage = result.scalars().first()

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
                # 【修复】添加校验：确保 file_path 是字符串且不为空
                for f in generated_files:
                    if isinstance(f, dict):
                        fp = f.get("file_path")
                        if isinstance(fp, str) and fp.strip():
                            modified_files.append(fp)

            # Git 操作在独立的交付工作区执行
            git_service = GitProviderService(str(delivery_workspace))
            timestamp = now().strftime("%Y%m%d_%H%M%S")
            git_branch = f"omniflow/pipeline-{pipeline_id}-{timestamp}"

            # 【重构】简化 Git 流程：init → fetch → checkout → 复制 → add → commit
            await push_log(
                pipeline_id,
                "info",
                "初始化 Git 仓库...",
                stage="DELIVERY"
            )
            remote_url = f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}.git"
            await push_log(
                pipeline_id,
                "info",
                f"远程仓库: {remote_url}",
                stage="DELIVERY"
            )
            # 【修复】skip_fetch=True 避免全量 fetch，后续用浅克隆只 fetch main 分支
            git_service.init_repo(remote_url=remote_url, skip_fetch=True)

            # 【修复】使用浅克隆只 fetch main 分支，避免全量 fetch 超时
            await push_log(
                pipeline_id,
                "info",
                "获取远程 main 分支（浅克隆）...",
                stage="DELIVERY"
            )
            try:
                git_service._run_git_command(
                    ["fetch", "origin", "main", "--depth=1"],
                    check=True,
                    timeout=60
                )
                await push_log(
                    pipeline_id,
                    "info",
                    "远程分支获取完成",
                    stage="DELIVERY"
                )
            except GitProviderError as fetch_error:
                await push_log(
                    pipeline_id,
                    "error",
                    f"获取远程分支失败: {str(fetch_error)}",
                    stage="DELIVERY"
                )
                raise ValueError(f"无法获取远程 main 分支，请检查仓库权限和网络连接: {fetch_error}")

            # 【重构】从 origin/main 创建普通分支（替代 orphan + reset 方案）
            # 这样分支有完整历史，PR diff 只包含实际修改的文件
            await push_log(
                pipeline_id,
                "info",
                f"从 origin/main 创建分支 {git_branch}...",
                stage="DELIVERY"
            )
            try:
                git_service._run_git_command(
                    ["checkout", "-b", git_branch, "origin/main"],
                    check=True
                )
                await push_log(
                    pipeline_id,
                    "info",
                    "分支创建完成",
                    stage="DELIVERY"
                )
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

            # 【重构】文件复制时机：在分支创建之后
            # 此时工作区已是 origin/main 的内容，复制进去的文件天然就是"相对于 main 的变更"
            copied_count = 0
            for file_path in modified_files:
                try:
                    content = None
                    src_file = sandbox_dir / file_path
                    if src_file.exists() and src_file.is_file():
                        # 绑定挂载模式：直接从宿主机文件系统读取
                        content = src_file.read_text(encoding="utf-8")
                    else:
                        # 非绑定挂载模式（docker cp / exec）：文件仅在容器内存在
                        # 从容器内读取文件内容后直接写入交付工作区
                        # 路径归一化：确保 backend/ 前缀，与 SandboxFileService._sanitize_path 保持一致
                        clean = file_path.replace("\\", "/").lstrip("/")
                        if clean.startswith("workspace/backend/"):
                            clean = clean[len("workspace/backend/"):]
                        elif clean.startswith("workspace/"):
                            clean = clean[len("workspace/"):]
                        if not clean.startswith("backend/"):
                            clean = f"backend/{clean}"
                        try:
                            container_content = await sandbox_manager.read_file(
                                pipeline_id, clean
                            )
                            content = container_content
                            await push_log(
                                pipeline_id,
                                "debug",
                                f"从容器内读取文件: {clean} ({len(content)} 字符)",
                                stage="DELIVERY"
                            )
                        except FileNotFoundError:
                            await push_log(
                                pipeline_id,
                                "warning",
                                f"文件不存在或不是普通文件，跳过: {file_path}",
                                stage="DELIVERY"
                            )
                            continue

                    if content is not None:
                        dst_file = delivery_workspace / file_path
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        dst_file.write_text(content, encoding="utf-8")
                        copied_count += 1
                except Exception as copy_error:
                    await push_log(
                        pipeline_id,
                        "warning",
                        f"复制文件失败 {file_path}: {str(copy_error)}",
                        stage="DELIVERY"
                    )

            await push_log(
                pipeline_id,
                "info",
                f"已复制 {copied_count} 个修改的文件到交付工作区",
                stage="DELIVERY"
            )

            # 【修复】如果没有文件被成功复制，提前报错
            if copied_count == 0:
                raise ValueError(
                    f"没有文件被成功复制，无法创建 PR（共 {len(modified_files)} 个目标文件）"
                )

            # 【修复】复制完文件后需要 add_files() 将变更加入暂存区
            await push_log(
                pipeline_id,
                "info",
                "添加文件到暂存区...",
                stage="DELIVERY"
            )
            git_service.add_files()

            # Git 提交
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
            try:
                git_service.push_branch(git_branch)
                await push_log(
                    pipeline_id,
                    "info",
                    "代码推送完成",
                    stage="DELIVERY"
                )
            except Exception as push_error:
                await push_log(
                    pipeline_id,
                    "error",
                    f"推送失败: {str(push_error)}",
                    stage="DELIVERY"
                )
                raise

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
        from sqlmodel import select

        # 先删除已存在的 DELIVERY 阶段（重试场景），避免 UNIQUE 约束冲突
        stmt = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.DELIVERY
        )
        existing = (await context.session.execute(stmt)).scalars().first()
        if existing:
            await context.session.delete(existing)
            await context.session.flush()

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
                # 兜底：确保所有阶段状态正确，防止阶段残留 RUNNING 导致前端进度条卡住
                for stage in pipeline.stages:
                    if stage.status == StageStatus.RUNNING:
                        stage.status = StageStatus.SUCCESS
                await WorkflowService.set_pipeline_success(pipeline, context.session)
            else:
                await WorkflowService.set_pipeline_failed(pipeline, context.session)

        # 【修复】先发送完成日志，再清理 SSE 缓冲区，避免竞态条件导致最后一条日志丢失
        await push_log(context.pipeline_id, "info", "✅ Pipeline 执行成功完成！", stage="DELIVERY")

        # 【关键修复】Pipeline 完成时停止 Sandbox
        sandbox_stop_error = None
        try:
            await sandbox_manager.stop(context.pipeline_id)
            await push_log(context.pipeline_id, "info", "Sandbox 已停止", stage="DELIVERY")
        except Exception as e:
            sandbox_stop_error = e
            await push_log(context.pipeline_id, "warning", f"停止 Sandbox 时出错: {str(e)}", stage="DELIVERY")

        await context.session.commit()

        # 【修复】如果 Sandbox 停止失败，抛出异常确保调用方能感知资源泄漏
        if sandbox_stop_error:
            raise RuntimeError(f"Pipeline 成功但 Sandbox 停止失败: {sandbox_stop_error}") from sandbox_stop_error

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
        错误处理：交付失败后暂停在 CODE_REVIEW 阶段等待重新确认

        不再直接标记 Pipeline 失败，而是：
        1. 记录 DELIVERY 阶段失败
        2. 标记 CODING 和 UNIT_TESTING 阶段需要重新确认交付（delivery_failed 标记）
        3. 设置 Pipeline 为 PAUSED 状态，current_stage 回退到 CODE_REVIEW
        4. 保留 Sandbox 运行，以便重新交付
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
            "交付失败，回退到 CODE_REVIEW 阶段等待重新确认...",
            stage="DELIVERY"
        )

        # 先删除已存在的 DELIVERY 阶段（重试场景），避免 UNIQUE 约束冲突
        existing_stmt = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.DELIVERY
        )
        existing = (await context.session.execute(existing_stmt)).scalars().first()
        if existing:
            await context.session.delete(existing)
            await context.session.flush()

        # 创建失败的 DELIVERY 阶段记录
        delivery_stage = PipelineStage(
            pipeline_id=context.pipeline_id,
            name=StageName.DELIVERY,
            status=StageStatus.FAILED,
            output_data={
                "error": str(error),
                "error_type": type(error).__name__,
                "rollback_to": "CODE_REVIEW"
            }
        )
        context.session.add(delivery_stage)

        # 【关键】标记 CODING 和 UNIT_TESTING 阶段需要重新确认交付
        # 阶段状态保持 SUCCESS（代码和测试本身是正确的，只是交付失败）
        # 通过 delivery_failed 标记让前端知道需要重新触发交付流程
        stmt = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name.in_([StageName.CODING, StageName.UNIT_TESTING])
        )
        result = await context.session.execute(stmt)
        stages_to_mark = result.scalars().all()

        for stage in stages_to_mark:
            # 【修复】SQLModel/SQLAlchemy 对 JSON 字段的原地修改不会被自动检测为 dirty
            # 需要用赋值替换整个对象才能触发变更追踪
            new_output = dict(stage.output_data) if stage.output_data else {}
            new_output["delivery_failed"] = True
            new_output["delivery_error"] = str(error)
            stage.output_data = new_output
            context.session.add(stage)

        # 更新 Pipeline 状态为 PAUSED，等待重新确认
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if pipeline:
            # 【修复】current_stage 回退到 CODE_REVIEW，与注释和 rollback_to 一致
            # CODE_REVIEW 是交付前的审批阶段，用户在此重新确认后再次触发 DELIVERY
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
