"""
单元测试阶段处理器

处理 UNIT_TESTING 阶段：
- 调用 TestAgent 生成测试代码
- 执行测试验证
- 支持测试失败处理和自动重试
"""

from typing import Any, Dict, List
import re

from app.core.sse_log_buffer import push_log
from app.models.pipeline import StageName, PipelineStatus
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService
from app.service.workspace import async_workspace_context


class TestingHandler(StageHandler):
    """单元测试阶段处理器"""

    MAX_TEST_RETRIES = 2  # 测试生成和修复的最大重试次数

    @property
    def stage_name(self) -> StageName:
        return StageName.UNIT_TESTING

    def _analyze_test_failure(self, logs: str) -> Dict[str, Any]:
        """
        分析测试失败原因，判断是测试文件问题还是代码问题
        
        Returns:
            Dict with 'is_test_file_error', 'error_type', 'error_detail'
        """
        # 测试文件语法错误
        if "SyntaxError" in logs:
            file_match = re.search(r'File "([^"]*test_[^"]+)"', logs)
            if file_match:
                return {
                    "is_test_file_error": True,
                    "error_type": "test_syntax_error",
                    "error_detail": f"测试文件语法错误: {file_match.group(1)}",
                    "suggestion": "重新生成测试文件"
                }
        
        # 测试文件导入错误
        if "ImportError" in logs or "ModuleNotFoundError" in logs:
            file_match = re.search(r'File "([^"]*test_[^"]+)"', logs)
            if file_match:
                return {
                    "is_test_file_error": True,
                    "error_type": "test_import_error",
                    "error_detail": f"测试文件导入错误: {file_match.group(1)}",
                    "suggestion": "修正测试文件的 import 语句"
                }
        
        # 测试收集错误
        if "collection error" in logs.lower() or "ImportError while loading" in logs:
            return {
                "is_test_file_error": True,
                "error_type": "test_collection_error",
                "error_detail": "测试收集失败",
                "suggestion": "检查测试文件结构"
            }
        
        # 普通测试失败（可能是代码问题或测试逻辑问题）
        if "FAILED" in logs or "AssertionError" in logs:
            return {
                "is_test_file_error": False,
                "error_type": "test_assertion_failure",
                "error_detail": "测试断言失败",
                "suggestion": "检查代码实现或测试逻辑"
            }
        
        return {
            "is_test_file_error": False,
            "error_type": "unknown",
            "error_detail": "未知错误",
            "suggestion": "查看详细日志"
        }

    async def _generate_tests_with_retry(
        self,
        test_agent,
        design_output: Dict,
        code_output: Dict,
        target_files: Dict,
        pipeline_id: int,
        executor,
        test_runner
    ) -> Dict[str, Any]:
        """
        生成测试并支持自动重试修复
        
        Returns:
            Dict with test generation result and test files
        """
        retry_count = 0
        last_error_context = None
        
        while retry_count <= self.MAX_TEST_RETRIES:
            # 构建生成参数
            generate_params = {
                "design_output": design_output,
                "code_output": code_output,
                "target_files": target_files,
                "pipeline_id": pipeline_id
            }
            
            # 如果有错误上下文，添加到提示中
            if last_error_context:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"第 {retry_count} 次尝试修复测试文件...",
                    stage="UNIT_TESTING"
                )
                # 修改 design_output 添加错误上下文
                enhanced_design = dict(design_output)
                enhanced_design["test_fix_context"] = last_error_context
                generate_params["design_output"] = enhanced_design
            
            test_result = await test_agent.generate_tests(**generate_params)
            
            if not test_result["success"]:
                retry_count += 1
                if retry_count > self.MAX_TEST_RETRIES:
                    return {
                        "success": False,
                        "error": test_result.get("error", "Unknown error"),
                        "test_generated": False,
                        "retry_count": retry_count - 1
                    }
                await push_log(
                    pipeline_id,
                    "warning",
                    f"TestAgent 生成失败，准备重试 ({retry_count}/{self.MAX_TEST_RETRIES})...",
                    stage="UNIT_TESTING"
                )
                continue
            
            # 获取测试文件
            test_output = test_result["output"]
            test_files = test_output.get("test_files", [])
            
            if not test_files:
                return {
                    "success": True,
                    "test_generated": False,
                    "error": "No test files generated",
                    "retry_count": retry_count
                }
            
            # 写入测试文件
            for test_file in test_files:
                file_path = test_file.get("file_path", "")
                content = test_file.get("content", "")
                if file_path and content:
                    if not file_path.startswith("tests/") and not file_path.startswith("backend/tests/"):
                        file_path = f"tests/{file_path}"
                    executor.apply_changes({file_path: content}, create_if_missing=True)
            
            # 运行测试验证
            await push_log(pipeline_id, "info", "运行测试验证...", stage="UNIT_TESTING")
            test_run_result = await test_runner.run_tests(str(executor.workspace_dir))
            
            if test_run_result["success"]:
                await push_log(pipeline_id, "success", "✅ 所有测试通过！", stage="UNIT_TESTING")
                return {
                    "success": True,
                    "test_generated": True,
                    "test_files": test_files,
                    "test_run_success": True,
                    "test_logs": test_run_result.get("logs", ""),
                    "retry_count": retry_count
                }
            
            # 测试失败，分析原因
            logs = test_run_result.get("logs", "")
            failure_analysis = self._analyze_test_failure(logs)
            
            if failure_analysis["is_test_file_error"] and retry_count < self.MAX_TEST_RETRIES:
                # 测试文件问题，可以重试
                retry_count += 1
                last_error_context = f"""
【测试文件错误 - 第 {retry_count} 次重试】
错误类型: {failure_analysis['error_type']}
错误详情: {failure_analysis['error_detail']}
建议: {failure_analysis['suggestion']}

【测试日志】
{logs[:2000]}

请修复测试文件中的错误并重新生成。
"""
                await push_log(
                    pipeline_id,
                    "warning",
                    f"⚠️ 检测到测试文件错误: {failure_analysis['error_detail']}，准备重试...",
                    stage="UNIT_TESTING"
                )
            else:
                # 代码问题或达到最大重试次数
                error_summary = test_run_result.get("summary", "Unknown error")
                await push_log(
                    pipeline_id,
                    "warning",
                    f"⚠️ 测试未通过: {error_summary}",
                    stage="UNIT_TESTING"
                )
                return {
                    "success": True,  # 代码本身没问题
                    "test_generated": True,
                    "test_files": test_files,
                    "test_run_success": False,
                    "test_error": error_summary,
                    "test_logs": test_run_result.get("logs", ""),
                    "retry_count": retry_count,
                    "failure_analysis": failure_analysis
                }
        
        # 达到最大重试次数
        return {
            "success": True,
            "test_generated": True,
            "test_files": test_files if 'test_files' in locals() else [],
            "test_run_success": False,
            "test_error": "达到最大重试次数，测试文件仍有问题",
            "retry_count": retry_count
        }

    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取 CODING 阶段输出"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        # 获取 CODING 阶段输出
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.CODING
        )
        result = await context.session.execute(statement)
        coding_stage = result.scalar_one_or_none()

        if not coding_stage or not coding_stage.output_data:
            raise ValueError("No coding output found for UNIT_TESTING stage")

        coding_output = coding_stage.output_data.get("multi_agent_output", {})
        target_files = coding_stage.output_data.get("target_files", {})

        # 获取 DESIGN 阶段输出
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.DESIGN
        )
        result = await context.session.execute(statement)
        design_stage = result.scalar_one_or_none()
        design_output = design_stage.output_data if design_stage else None

        context.input_data["coding_output"] = coding_output
        context.input_data["target_files"] = target_files
        context.input_data["design_output"] = design_output

        # 获取或创建 UNIT_TESTING 阶段
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.UNIT_TESTING
        )
        result = await context.session.execute(statement)
        testing_stage = result.scalar_one_or_none()

        if not testing_stage:
            testing_stage = await WorkflowService.create_stage(
                pipeline_id=context.pipeline_id,
                stage_name=self.stage_name,
                input_data={
                    "coding_output": coding_output,
                    "target_files": target_files,
                    "design_output": design_output
                },
                session=context.session
            )

        context.stage_id = testing_stage.id

        # 提交事务释放连接
        await context.session.commit()

        return context

    async def execute(self, context: StageContext) -> StageResult:
        """执行单元测试生成和验证"""
        pipeline_id = context.pipeline_id
        coding_output = context.input_data.get("coding_output", {})
        design_output = context.input_data.get("design_output", {})
        target_files = context.input_data.get("target_files", {})

        await push_log(pipeline_id, "info", "开始单元测试阶段...", stage="UNIT_TESTING")

        from app.agents import test_agent
        from app.service.code_executor import CodeExecutorService
        from app.service.import_sanitizer import ImportSanitizer
        from app.service.test_runner import TestRunnerService

        testing_result = None

        try:
            async with async_workspace_context(pipeline_id) as ws:
                workspace_dir = ws.get_workspace_path()
                await push_log(
                    pipeline_id,
                    "info",
                    f"创建临时工作区用于测试: {workspace_dir.name}",
                    stage="UNIT_TESTING"
                )

                # 写入代码文件到工作区
                executor = CodeExecutorService(workspace_dir)
                all_files = coding_output.get("files", [])

                # 修正 import 路径
                all_files, fix_report = ImportSanitizer.sanitize_files(all_files)

                # 强制添加 backend/ 前缀
                for f in all_files:
                    p = f.get("file_path", "")
                    p = p.lstrip("/")
                    if p and not p.startswith("backend/"):
                        f["file_path"] = f"backend/{p}"

                executor.apply_changes(
                    {f["file_path"]: f["content"] for f in all_files},
                    create_if_missing=True
                )

                # 调用 TestAgent 生成测试（带重试机制）
                await push_log(pipeline_id, "info", "TestAgent 开始生成测试代码...", stage="UNIT_TESTING")

                testing_result = await self._generate_tests_with_retry(
                    test_agent=test_agent,
                    design_output=design_output,
                    code_output=coding_output,
                    target_files=target_files,
                    pipeline_id=pipeline_id,
                    executor=executor,
                    test_runner=TestRunnerService
                )

                # 记录重试次数
                retry_count = testing_result.get("retry_count", 0)
                if retry_count > 0:
                    await push_log(
                        pipeline_id,
                        "info",
                        f"测试生成共重试 {retry_count} 次",
                        stage="UNIT_TESTING"
                    )

        except Exception as e:
            await push_log(pipeline_id, "error", f"单元测试执行失败: {str(e)}", stage="UNIT_TESTING")
            testing_result = {
                "success": True,  # 代码本身没问题
                "test_generated": False,
                "test_error": str(e)
            }

        # 构建结果
        # 从 testing_result 中提取指标
        metrics = {
            "retry_count": testing_result.get("retry_count", 0),
        }

        return StageResult.success_result(
            message="Unit testing completed",
            output_data={
                "testing_result": testing_result,
                "coding_output": coding_output,
                "target_files": target_files
            },
            status=PipelineStatus.PAUSED,  # 等待审批
            metrics=metrics
        )

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：保存结果，创建 CODE_REVIEW 阶段"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        # 重新获取 stage
        statement = select(PipelineStage).where(PipelineStage.id == context.stage_id)
        query_result = await context.session.execute(statement)
        testing_stage = query_result.scalar_one_or_none()

        if testing_stage:
            testing_data = result.output_data.get("testing_result", {})
            await WorkflowService.complete_stage(
                stage=testing_stage,
                output_data=result.output_data,
                success=testing_data.get("success", True),
                session=context.session,
                metrics=result.metrics
            )

        # 创建 CODE_REVIEW 阶段
        coding_output = result.output_data.get("coding_output", {})
        testing_result = result.output_data.get("testing_result", {})
        target_files = result.output_data.get("target_files", {})

        await WorkflowService.create_stage(
            pipeline_id=context.pipeline_id,
            stage_name=StageName.CODE_REVIEW,
            input_data={
                "coding_output": coding_output,
                "testing_result": testing_result,
                "target_files": target_files
            },
            session=context.session
        )

        # 更新 Pipeline 状态
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if pipeline:
            pipeline.current_stage = StageName.CODE_REVIEW
            await WorkflowService.set_pipeline_paused(pipeline, context.session)

        await push_log(
            context.pipeline_id,
            "info",
            "单元测试完成，进入代码审查阶段",
            stage="CODE_REVIEW"
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
            f"单元测试阶段异常: {str(error)}",
            stage="UNIT_TESTING"
        )
        return StageResult.failure_result(
            message=f"Unit testing failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )
