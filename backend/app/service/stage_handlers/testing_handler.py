"""
Unit Testing Stage Handler (using RepairService)

Handles UNIT_TESTING stage:
- Generate test code via TestAgent
- Execute test validation
- Support RepairerAgent auto-fix on test failures
- Uses RepairService for unified repair loop
"""

from typing import Any, Dict, List, Optional

from app.core.sse_log_buffer import push_log
from app.models.pipeline import StageName, PipelineStatus
from app.service.layered_test_runner import LayeredTestRunner
from app.service.sandbox_file_service import SandboxFileService
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService
from app.service.workspace import async_workspace_context
from app.service.repair_service import repair_service
from app.service.sandbox_manager import sandbox_manager
from app.utils.test_execution import run_preliminary_test, analyze_test_failure

import logging
logger = logging.getLogger(__name__)


class TestingHandler(StageHandler):
    """Unit Testing Stage Handler (using RepairService)"""

    MAX_TEST_RETRIES = 2

    @property
    def stage_name(self) -> StageName:
        return StageName.UNIT_TESTING

    async def _run_layered_tests(
        self,
        workspace_dir: str,
        test_files: List[Dict],
        code_files: List[Dict],
        pipeline_id: int,
        file_service=None
    ) -> Dict[str, Any]:
        """Run layered tests using LayeredTestRunner"""
        await push_log(
            pipeline_id,
            "info",
            "Running layered tests...",
            stage="UNIT_TESTING"
        )

        all_files = code_files + test_files

        layered_result = await LayeredTestRunner.run(
            workspace_path=workspace_dir,
            new_files=all_files,
            sandbox_port=None,
            timeout=120,
            file_service=file_service
        )

        result = {
            "success": layered_result.all_passed,
            "logs": "\n\n".join([layer.logs for layer in layered_result.layers]),
            "summary": f"Layered tests: {len([l for l in layered_result.layers if l.passed])}/{len(layered_result.layers)} passed",
            "failed_tests": layered_result.failed_tests,
            "layered_result": {
                "all_passed": layered_result.all_passed,
                "failure_cause": layered_result.failure_cause,
                "layers": [
                    {
                        "layer": layer.layer,
                        "passed": layer.passed,
                        "summary": layer.summary,
                        "failed_tests": layer.failed_tests,
                        "error_type": layer.error_type
                    }
                    for layer in layered_result.layers
                ]
            }
        }

        for layer in layered_result.layers:
            status = "PASS" if layer.passed else "FAIL"
            await push_log(
                pipeline_id,
                "info" if layer.passed else "warning",
                f"{status} {layer.layer}: {layer.summary}",
                stage="UNIT_TESTING"
            )

        return result

    async def _generate_tests_with_retry(
        self,
        test_agent,
        design_output: Dict,
        code_output: Dict,
        target_files: Dict,
        pipeline_id: int,
        file_service
    ) -> Dict[str, Any]:
        """Generate tests with retry"""
        retry_count = 0
        last_error_context = None

        while retry_count <= self.MAX_TEST_RETRIES:
            generate_params = {
                "design_output": design_output,
                "code_output": code_output,
                "target_files": target_files,
                "pipeline_id": pipeline_id
            }

            if last_error_context:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"Retry {retry_count}: Fixing test files...",
                    stage="UNIT_TESTING"
                )
                enhanced_design = dict(design_output)
                enhanced_design["test_fix_context"] = last_error_context
                generate_params["design_output"] = enhanced_design

            test_result = await test_agent.generate_tests(**generate_params)

            # Save agent debug info
            self._save_agent_log(
                agent_name="TesterAgent",
                stage=f"generate_tests{'_retry_' + str(retry_count) if retry_count > 0 else ''}",
                input_data=generate_params,
                output_data=test_result,
                retry_count=retry_count
            )

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
                    f"Test generation failed, retrying ({retry_count}/{self.MAX_TEST_RETRIES})...",
                    stage="UNIT_TESTING"
                )
                continue

            test_output = test_result["output"]
            test_files = test_output.get("test_files", [])

            if not test_files:
                return {
                    "success": True,
                    "test_generated": False,
                    "error": "No test files generated",
                    "retry_count": retry_count
                }

            # Write test files using SandboxFileService
            for test_file in test_files:
                file_path = test_file.get("file_path", "")
                content = test_file.get("content", "")
                if file_path and content:
                    if not file_path.startswith("tests/") and not file_path.startswith("backend/tests/"):
                        file_path = f"tests/{file_path}"
                    # 使用 SandboxFileService 直接写入文件
                    await file_service.write_file(file_path, content)
                    await push_log(pipeline_id, "info", f"  📝 测试文件已生成: {file_path}", stage="UNIT_TESTING")

            # Run preliminary test
            preliminary_result = await run_preliminary_test(
                pipeline_id=pipeline_id,
                test_files=test_files,
                file_service=file_service,
                log_callback=lambda level, msg: push_log(pipeline_id, level.lower(), msg, stage="UNIT_TESTING")
            )

            # If preliminary test fails due to test file issues, retry
            if not preliminary_result.get("success"):
                logs = preliminary_result.get("logs", "")
                failure_analysis = analyze_test_failure(logs)

                if failure_analysis.get("is_test_file_error") and retry_count < self.MAX_TEST_RETRIES:
                    retry_count += 1
                    last_error_context = self._build_error_context(
                        retry_count, failure_analysis, logs, "Preliminary test failed"
                    )
                    await push_log(
                        pipeline_id,
                        "warning",
                        f"Preliminary test found test file errors, retrying ({retry_count}/{self.MAX_TEST_RETRIES})...",
                        stage="UNIT_TESTING"
                    )
                    continue

            # Run full test validation using LayeredTestRunner
            await push_log(pipeline_id, "info", "Running full test validation...", stage="UNIT_TESTING")
            from app.service.layered_test_runner import LayeredTestRunner
            layered_result = await LayeredTestRunner.run(
                workspace_path="/workspace",
                new_files=test_files,
                sandbox_port=None,
                timeout=120,
                file_service=file_service
            )
            # 转换 LayeredTestResult 为字典格式
            test_run_result = {
                "success": layered_result.all_passed,
                "logs": "\n\n".join([layer.logs for layer in layered_result.layers]),
                "summary": f"Layered tests: {len([l for l in layered_result.layers if l.passed])}/{len(layered_result.layers)} passed",
                "failed_tests": layered_result.failed_tests,
                "error": layered_result.failure_cause,
                "error_type": "test_failure" if not layered_result.all_passed else None
            }

            if test_run_result["success"]:
                await push_log(pipeline_id, "success", "All tests passed!", stage="UNIT_TESTING")
                return {
                    "success": True,
                    "test_generated": True,
                    "test_files": test_files,
                    "test_run_success": True,
                    "test_logs": test_run_result.get("logs", ""),
                    "retry_count": retry_count
                }

            # Test failed, analyze reason
            logs = test_run_result.get("logs") or ""
            failure_analysis = analyze_test_failure(logs)

            if failure_analysis["is_test_file_error"] and retry_count < self.MAX_TEST_RETRIES:
                retry_count += 1
                last_error_context = self._build_error_context(
                    retry_count, failure_analysis, logs, "Test file error"
                )
                await push_log(
                    pipeline_id,
                    "warning",
                    f"Detected test file error: {failure_analysis['error_detail']}, retrying...",
                    stage="UNIT_TESTING"
                )
            else:
                error_summary = test_run_result.get("summary", "Unknown error")
                await push_log(
                    pipeline_id,
                    "warning",
                    f"Tests failed: {error_summary}",
                    stage="UNIT_TESTING"
                )
                return {
                    "success": True,
                    "test_generated": True,
                    "test_files": test_files,
                    "test_run_success": False,
                    "test_error": error_summary,
                    "test_logs": test_run_result.get("logs", ""),
                    "retry_count": retry_count,
                    "failure_analysis": failure_analysis
                }

        return {
            "success": True,
            "test_generated": True,
            "test_files": test_files if 'test_files' in locals() else [],
            "test_run_success": False,
            "test_error": "Max retries reached, test files still have issues",
            "retry_count": retry_count
        }

    def _build_error_context(
        self,
        retry_count: int,
        failure_analysis: Dict,
        logs: str,
        error_title: str
    ) -> str:
        """Build error context for retry"""
        return f"""
[{error_title} - Retry {retry_count}]
Error Type: {failure_analysis['error_type']}
Error Detail: {failure_analysis['error_detail']}
Suggestion: {failure_analysis['suggestion']}

[Logs]
{logs[:2000]}

Please fix the errors in the test files and regenerate.
"""

    async def prepare(self, context: StageContext) -> StageContext:
        """Prepare stage: get CODING stage output"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.CODING
        )
        result = await context.session.execute(statement)
        coding_stage = result.scalar_one_or_none()

        if not coding_stage or not coding_stage.output_data:
            raise ValueError("No coding output found for UNIT_TESTING stage")

        coding_output = coding_stage.output_data.get("coder_output", {})
        target_files = coding_stage.output_data.get("target_files", {})

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
        await context.session.commit()

        return context

    async def execute(self, context: StageContext) -> StageResult:
        """Execute unit test generation and validation"""
        pipeline_id = context.pipeline_id
        coding_output = context.input_data.get("coding_output", {})
        design_output = context.input_data.get("design_output", {})
        target_files = context.input_data.get("target_files", {})

        await push_log(pipeline_id, "info", "Starting unit testing stage...", stage="UNIT_TESTING")

        from app.agents import test_agent
        from app.service.import_sanitizer import ImportSanitizer
        from app.service.sandbox_file_service import get_sandbox_file_service

        testing_result = None
        repair_history = []

        try:
            # 【关键修复】使用沙箱文件服务，而不是创建新的 workspace
            # Coding 阶段已经把代码写入沙箱了，测试阶段直接读取即可
            file_service = get_sandbox_file_service(pipeline_id)
            await push_log(
                pipeline_id,
                "info",
                f"Using existing sandbox for testing (pipeline_{pipeline_id})",
                stage="UNIT_TESTING"
            )

            all_files = coding_output.get("files", [])

            # 清理导入路径
            all_files, fix_report = ImportSanitizer.sanitize_files(all_files)

            for f in all_files:
                p = f.get("file_path", "")
                p = p.lstrip("/")
                if p and not p.startswith("backend/"):
                    f["file_path"] = f"backend/{p}"

            # Contract check
            interface_specs = design_output.get("interface_specs", [])
            if interface_specs:
                await push_log(
                    pipeline_id,
                    "info",
                    f"Starting contract check ({len(interface_specs)} symbols)...",
                    stage="UNIT_TESTING"
                )

                code_files_dict = {f["file_path"]: f["content"] for f in all_files if f.get("content")}

                from app.core.contract_checker import verify_contract
                missing_symbols = verify_contract(code_files_dict, interface_specs)

                if missing_symbols:
                    await push_log(
                        pipeline_id,
                        "error",
                        f"Contract check failed: {len(missing_symbols)} missing symbols",
                        stage="UNIT_TESTING"
                    )
                    for sym in missing_symbols:
                        await push_log(pipeline_id, "error", f"   - {sym}", stage="UNIT_TESTING")

                    return StageResult.failure_result(
                        message=f"Contract violation: {missing_symbols}",
                        output_data={
                            "contract_violation": True,
                            "missing_symbols": missing_symbols,
                            "interface_specs": interface_specs
                        }
                    )
                else:
                    await push_log(
                        pipeline_id,
                        "info",
                        f"Contract check passed ({len(interface_specs)} symbols implemented)",
                        stage="UNIT_TESTING"
                    )

            # Generate tests
            await push_log(pipeline_id, "info", "TestAgent generating test code...", stage="UNIT_TESTING")

            testing_result = await self._generate_tests_with_retry(
                test_agent=test_agent,
                design_output=design_output,
                code_output=coding_output,
                target_files=target_files,
                pipeline_id=pipeline_id,
                file_service=file_service
            )

            retry_count = testing_result.get("retry_count", 0)
            if retry_count > 0:
                await push_log(
                    pipeline_id,
                    "info",
                    f"Test generation retried {retry_count} times",
                    stage="UNIT_TESTING"
                )

            # Auto-fix using RepairService
            if testing_result.get("test_generated") and not testing_result.get("test_run_success"):
                failure_analysis = testing_result.get("failure_analysis", {})

                if not failure_analysis.get("is_test_file_error", True):
                    test_logs = testing_result.get("test_logs") or ""
                    test_files = testing_result.get("test_files", [])

                    # 【统一】使用 RepairService 进行修复
                    repair_result = await repair_service.start_repair(
                        pipeline_id=pipeline_id,
                        code_files=all_files,
                        test_files=test_files,
                        test_logs=test_logs,
                        design_output=design_output,
                        file_service=file_service,
                        debugger=self.debugger,
                    )

                    repair_history.append({
                        "rounds": repair_result.get("repair_rounds", 0),
                        "success": repair_result.get("test_run_success", False),
                        "fixed_files_count": len(repair_result.get("fixed_files", [])),
                        "fix_history": repair_result.get("fix_history", [])
                    })

                    if repair_result.get("test_run_success"):
                        testing_result["test_run_success"] = True
                        testing_result["repair_success"] = True
                        await push_log(
                            pipeline_id,
                            "success",
                            "Code repair successful, tests passed!",
                            stage="UNIT_TESTING"
                        )
                    else:
                        testing_result["repair_success"] = False
                        await push_log(
                            pipeline_id,
                            "warning",
                            "Auto-fix could not resolve all issues, entering manual review",
                            stage="UNIT_TESTING"
                        )

        except Exception as e:
            await push_log(pipeline_id, "error", f"Unit testing execution failed: {str(e)}", stage="UNIT_TESTING")
            # 【关键修复】异常时返回失败结果，而不是继续返回 success
            return StageResult.failure_result(
                message=f"Unit testing failed: {str(e)}",
                output_data={
                    "testing_result": {
                        "success": False,
                        "test_generated": False,
                        "test_error": str(e),
                        "error_type": type(e).__name__
                    },
                    "test_files": [],
                    "coding_output": coding_output,
                    "target_files": target_files,
                    "repair_history": repair_history
                }
            )

        metrics = {
            "retry_count": testing_result.get("retry_count", 0),
            "repair_rounds": sum(r.get("rounds", 0) for r in repair_history),
            "repair_success": any(r.get("success", False) for r in repair_history)
        }

        test_files = testing_result.get("test_files", []) if testing_result else []

        return StageResult.success_result(
            message="Unit testing completed",
            output_data={
                "testing_result": testing_result,
                "test_files": test_files,
                "coding_output": coding_output,
                "target_files": target_files,
                "repair_history": repair_history
            },
            status=PipelineStatus.PAUSED,
            metrics=metrics
        )

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """Complete stage: save results, create CODE_REVIEW stage"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

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

        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if pipeline:
            pipeline.current_stage = StageName.CODE_REVIEW
            await WorkflowService.set_pipeline_paused(pipeline, context.session)

        repair_history = result.output_data.get("repair_history", [])
        if repair_history:
            total_rounds = sum(r.get("rounds", 0) for r in repair_history)
            repair_success = any(r.get("success", False) for r in repair_history)
            status_icon = "PASS" if repair_success else "WARN"
            await push_log(
                context.pipeline_id,
                "info",
                f"{status_icon} Unit testing completed (RepairerAgent fixed {total_rounds} rounds), entering code review",
                stage="CODE_REVIEW"
            )
        else:
            await push_log(
                context.pipeline_id,
                "info",
                "Unit testing completed, entering code review",
                stage="CODE_REVIEW"
            )

        await context.session.commit()

    async def handle_error(
        self,
        context: StageContext,
        error: Exception
    ) -> StageResult:
        """Error handling"""
        await push_log(
            context.pipeline_id,
            "error",
            f"Unit testing stage error: {str(error)}",
            stage="UNIT_TESTING"
        )
        return StageResult.failure_result(
            message=f"Unit testing failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )

    async def on_approved(
        self,
        context: StageContext,
        notes: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> StageResult:
        """UNIT_TESTING stage approved: enter CODE_REVIEW stage"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        await push_log(
            context.pipeline_id,
            "info",
            "Unit testing approved, entering code review...",
            stage="UNIT_TESTING"
        )

        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.UNIT_TESTING
        )
        result = await context.session.execute(statement)
        testing_stage = result.scalar_one_or_none()

        testing_result = {}
        if testing_stage and testing_stage.output_data:
            testing_result = testing_stage.output_data.get("testing_result", {})

        coding_output = testing_stage.output_data.get("coding_output", {}) if testing_stage else {}
        target_files = testing_stage.output_data.get("target_files", {}) if testing_stage else {}

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

        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if pipeline:
            pipeline.current_stage = StageName.CODE_REVIEW
            await WorkflowService.set_pipeline_paused(pipeline, context.session)

        await context.session.commit()

        return StageResult.success_result(
            message="Unit testing approved, proceeding to code review",
            output_data={
                "previous_stage": StageName.UNIT_TESTING.value,
                "next_stage": StageName.CODE_REVIEW.value,
                "test_generated": testing_result.get("test_generated", False),
                "test_run_success": testing_result.get("test_run_success", False)
            },
            status=PipelineStatus.PAUSED
        )

    async def on_rejected(
        self,
        context: StageContext,
        reason: str,
        suggested_changes: Optional[str] = None
    ) -> StageResult:
        """UNIT_TESTING stage rejected: rollback to CODING to regenerate code and tests"""
        from app.service.stage_handlers import CodingHandler

        await push_log(
            context.pipeline_id,
            "info",
            f"Unit testing rejected, reason: {reason}, rolling back to code generation...",
            stage="UNIT_TESTING"
        )

        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}

        await WorkflowService.mark_stage_for_rerun(
            pipeline_id=context.pipeline_id,
            stage_name=StageName.CODING,
            rejection_feedback=rejection_feedback,
            session=context.session
        )

        coding_handler = CodingHandler()
        coding_context = StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={},
            rejection_feedback=rejection_feedback
        )

        coding_result = await coding_handler.run(coding_context)

        if coding_result.success:
            testing_result = await self.run(StageContext(
                pipeline_id=context.pipeline_id,
                session=context.session,
                input_data={}
            ))

            return StageResult(
                success=testing_result.success,
                status=testing_result.status,
                message="Coding and unit testing re-executed",
                output_data={
                    "previous_stage": StageName.UNIT_TESTING.value,
                    "current_stage": StageName.UNIT_TESTING.value,
                    "test_generated": testing_result.output_data.get("testing_result", {}).get("test_generated", False),
                    "test_run_success": testing_result.output_data.get("testing_result", {}).get("test_run_success", False)
                }
            )
        else:
            return StageResult.failure_result(
                message="Code generation failed after rejection",
                output_data={
                    "previous_stage": StageName.UNIT_TESTING.value,
                    "current_stage": StageName.CODING.value,
                    "error": coding_result.message
                }
            )
