"""
代码生成阶段处理器

处理 CODING 阶段：
- 使用临时工作区执行代码生成
- 调用多 Agent 协调器
- 支持自动修复循环
"""

from pathlib import Path
from typing import Any, Dict

from app.core.config import settings
from app.core.sse_log_buffer import push_log
from app.models.pipeline import StageName, PipelineStatus, StageStatus
from app.service.agent_coordinator import AgentCoordinatorService
from app.service.sandbox_manager import sandbox_manager
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService


class CodingHandler(StageHandler):
    """代码生成阶段处理器"""
    
    @property
    def stage_name(self) -> StageName:
        return StageName.CODING
    
    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取 DESIGN 阶段输出，创建 CODING 阶段记录"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        # 获取 DESIGN 阶段输出
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.DESIGN
        )
        result = await context.session.execute(statement)
        design_stage = result.scalar_one_or_none()

        if not design_stage or not design_stage.output_data:
            raise ValueError("No design output found for CODING stage")

        context.previous_output = design_stage.output_data

        # 【改造】不再预加载目标文件内容
        # CoderAgent 现在使用工具按需读取文件（glob/grep/read_file）
        # 只传递 affected_files 列表供参考，不加载内容
        affected_files = design_stage.output_data.get("affected_files", [])
        context.input_data["affected_files"] = affected_files

        # 创建 CODING 阶段
        coding_stage = await WorkflowService.create_stage(
            pipeline_id=context.pipeline_id,
            stage_name=self.stage_name,
            input_data=design_stage.output_data,
            session=context.session
        )
        context.stage_id = coding_stage.id

        # 提交事务释放连接
        await context.session.commit()

        return context
    
    async def execute(self, context: StageContext) -> StageResult:
        """执行代码生成"""
        pipeline_id = context.pipeline_id
        design_output = context.previous_output
        affected_files = context.input_data.get("affected_files", [])

        await push_log(pipeline_id, "info", "开始代码生成...", stage="CODING")

        from app.agents.multi_agent_coordinator import multi_agent_coordinator

        multi_agent_result = None
        sandbox_info = None
        sandbox_started = False

        try:
            # 启动沙箱
            project_path = str(Path(settings.TARGET_PROJECT_PATH).resolve())
            sandbox_info = await sandbox_manager.start(pipeline_id, project_path)
            sandbox_started = True
            await push_log(
                pipeline_id,
                "info",
                f"沙箱已启动，预览端口: {sandbox_info.port}",
                stage="CODING"
            )

            # 【改造】调用带自动修复的协调器
            # 不再传入预加载的 target_files，CoderAgent 使用工具按需读取
            multi_agent_result = await multi_agent_coordinator.execute_with_auto_fix(
                design_output=design_output,
                affected_files=affected_files,
                pipeline_id=pipeline_id,
                workspace_path="/workspace",  # 容器内路径，固定
                sandbox_port=sandbox_info.port,  # 透传给 coordinator，存入 output_data
                error_context=context.error_context  # 传入错误上下文（如允许修改测试的授权）
            )

            # 如果成功，记录测试日志
            if multi_agent_result["success"] and "test_logs" in multi_agent_result:
                await push_log(pipeline_id, "info", "测试日志已保存", stage="CODING")

        except Exception as e:
            await push_log(pipeline_id, "error", f"代码生成执行失败: {str(e)}", stage="CODING")
            multi_agent_result = {
                "success": False,
                "error": str(e),
                "output": None
            }
        finally:
            # 确保沙箱被停止，避免资源泄漏
            if sandbox_started:
                try:
                    await sandbox_manager.stop(pipeline_id)
                    await push_log(pipeline_id, "info", "沙箱已停止", stage="CODING")
                except Exception as stop_error:
                    await push_log(pipeline_id, "warning", f"停止沙箱时出错: {str(stop_error)}", stage="CODING")
        
        # 构建结果
        if not multi_agent_result or not multi_agent_result["success"]:
            error_msg = multi_agent_result.get("error", "Unknown error") if multi_agent_result else "Unknown error"

            # 检查是否是挂起等待用户决策的状态
            if multi_agent_result and multi_agent_result.get("pending_user_decision"):
                return StageResult(
                    success=False,
                    status=PipelineStatus.PAUSED,   # PAUSED 不是 FAILED
                    message="等待用户决策：旧测试不兼容",
                    output_data={
                        "pending_user_decision": True,
                        "decision_options": multi_agent_result.get("decision_options", []),
                        "user_message": multi_agent_result.get("user_message", ""),
                        "regression_failed_tests": multi_agent_result.get("regression_failed_tests", []),
                        "last_code_output": multi_agent_result.get("last_code_output"),
                        "target_files": target_files,
                    },
                    metrics=self._extract_metrics(multi_agent_result),
                )

            output_data = {
                "error": error_msg,
                "last_error_logs": multi_agent_result.get("last_error_logs") if multi_agent_result else None
            }

            # 注意：失败时不保存 multi_agent_output，避免脏数据残留
            # 只保存 affected_files 列表用于调试
            if affected_files:
                output_data["affected_files"] = affected_files

            return StageResult.failure_result(
                message=f"Code generation failed: {error_msg}",
                output_data=output_data,
                metrics=self._extract_metrics(multi_agent_result)
            )
        
        # 成功处理
        combined_output = multi_agent_result["output"]
        file_count = len(combined_output.get('files', []))
        attempt_count = multi_agent_result.get("attempt", 0)
        
        if attempt_count > 0:
            await push_log(
                pipeline_id,
                "info",
                f"代码生成完成（经过 {attempt_count + 1} 次尝试），共 {file_count} 个文件",
                stage="CODING"
            )
        else:
            await push_log(
                pipeline_id,
                "info",
                f"代码生成完成，共 {file_count} 个文件",
                stage="CODING"
            )
        
        return StageResult.success_result(
            message="Code generated successfully",
            output_data={
                "multi_agent_output": combined_output,
                "tests_included": combined_output.get("tests_included", False),
                "target_files": target_files,
                "auto_fix_attempts": attempt_count,
                "test_logs": multi_agent_result.get("test_logs"),
                "sandbox_port": sandbox_info.port if sandbox_info else None
            },
            status=PipelineStatus.RUNNING,  # 继续执行到 UNIT_TESTING
            metrics=self._extract_metrics(multi_agent_result)
        )
    
    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：保存结果，创建 UNIT_TESTING 阶段"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage
        
        # 重新获取 stage（因为 execute 中提交了事务）
        statement = select(PipelineStage).where(PipelineStage.id == context.stage_id)
        query_result = await context.session.execute(statement)
        coding_stage = query_result.scalar_one_or_none()
        
        if coding_stage:
            await WorkflowService.complete_stage(
                stage=coding_stage,
                output_data=result.output_data,
                success=result.success,
                session=context.session,
                metrics=result.metrics
            )
        
        if result.success:
            # 创建 UNIT_TESTING 阶段
            coding_output = result.output_data.get("multi_agent_output", {})
            affected_files = context.input_data.get("affected_files", [])
            design_output = context.previous_output

            await WorkflowService.create_stage(
                pipeline_id=context.pipeline_id,
                stage_name=StageName.UNIT_TESTING,
                input_data={
                    "coding_output": coding_output,
                    "affected_files": affected_files,
                    "design_output": design_output
                },
                session=context.session
            )
            
            # 更新 Pipeline 当前阶段
            pipeline = await WorkflowService.get_pipeline_with_stages(
                context.pipeline_id, context.session
            )
            if pipeline:
                pipeline.current_stage = StageName.UNIT_TESTING
                await WorkflowService.set_pipeline_running(pipeline, context.session)
            
            await push_log(
                context.pipeline_id,
                "info",
                "代码生成完成，进入单元测试阶段",
                stage="UNIT_TESTING"
            )
        else:
            # 失败处理
            pipeline = await WorkflowService.get_pipeline_with_stages(
                context.pipeline_id, context.session
            )
            if pipeline:
                await WorkflowService.set_pipeline_failed(pipeline, context.session)

            from app.core.sse_log_buffer import remove_buffer
            remove_buffer(context.pipeline_id)

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
            f"代码生成阶段异常: {str(error)}",
            stage="CODING"
        )
        # 注意：沙箱在 execute 方法的 finally 块中已停止
        return StageResult.failure_result(
            message=f"Code generation failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )
    
    def _extract_metrics(self, multi_agent_result: Dict[str, Any] | None) -> Dict[str, Any]:
        """提取可观测性指标"""
        if not multi_agent_result:
            return {}
        return {
            'input_tokens': multi_agent_result.get('input_tokens', 0),
            'output_tokens': multi_agent_result.get('output_tokens', 0),
            'duration_ms': multi_agent_result.get('duration_ms', 0),
            'retry_count': multi_agent_result.get('attempt', 0),
            'reasoning': multi_agent_result.get('reasoning')
        }
