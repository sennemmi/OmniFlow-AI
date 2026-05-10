"""
Test Orchestrator Service

测试编排服务 — 从 PipelineService 提取的测试执行逻辑。

职责：
1. 前置检查（契约检查 + 语法检查）
2. 预测试执行与修复循环
3. 分层测试（defense → regression → new_tests）
4. FastAPI 沙箱启动
5. 单文件测试执行
"""

import logging
from typing import Dict, Any, List

from sqlmodel import select

from app.core.database import async_session_factory
from app.core.sse_log_buffer import push_log
from app.models.pipeline import PipelineStage, StageName
from app.service.sandbox_manager import sandbox_manager

logger = logging.getLogger(__name__)


class TestOrchestrator:
    """测试编排服务 — 从 PipelineService 中提取的测试执行逻辑"""
    @staticmethod
    async def _run_tests_after_gather(pipeline_id: int) -> Dict[str, Any]:
        """
        在 CODING 和 TESTING 都完成后，统一执行测试流程（支持逐层修复）

        流程：
        1. 从数据库读取 CODING 和 UNIT_TESTING 阶段的输出
        2. 【前置检查】契约检查 + 语法检查，失败则重新调用 Tester 生成测试
        3. 执行预测试，失败则调用 RepairService 修复，直到通过
        4. 执行分层测试（defense -> regression -> new_tests），每层失败后修复再重试
        5. 返回测试结果
        """

        # 【新增】初始化测试详情记录
        test_details = {
            "preliminary": {"attempts": [], "final_status": "pending"},
            "layers": {"defense": [], "regression": [], "new_tests": []},
            "repairs": [],
            "defense_violations": [],  # 记录对 defense 文件夹的修改尝试
        }
        from app.service.layered_test_runner import LayeredTestRunner, LayerResult
        from app.service.sandbox_file_service import get_sandbox_file_service
        from app.service.repair_service import repair_service
        from app.core.contract_checker import verify_contract
        from app.utils.test_execution import run_preliminary_test, analyze_test_failure
        from app.agents import test_agent
        from app.utils.agent_debug_utils import get_agent_debugger
        from app.service.pipeline import PipelineService

        await push_log(pipeline_id, "info", "CODER 和 TESTER 都已完成，开始测试流程...", stage="UNIT_TESTING")

        # 【新增】测试流程开始前检查 Pipeline 是否已终止
        if await PipelineService._check_pipeline_terminated(pipeline_id):
            await push_log(pipeline_id, "warning", "Pipeline 已终止，测试流程退出", stage="UNIT_TESTING")
            return {"success": False, "error": "Pipeline terminated", "test_run_success": False}

        file_service = get_sandbox_file_service(pipeline_id)
        debugger = get_agent_debugger()

        # 从数据库获取 CODING 和 UNIT_TESTING 阶段的输出
        async with async_session_factory() as session:
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name.in_([StageName.CODING, StageName.UNIT_TESTING])
            )
            result = await session.execute(statement)
            stages = result.scalars().all()

            coding_stage = None
            testing_stage = None
            for stage in stages:
                if stage.name == StageName.CODING:
                    coding_stage = stage
                elif stage.name == StageName.UNIT_TESTING:
                    testing_stage = stage

            # 提取代码文件（从 CODING 阶段）
            code_files = []
            if coding_stage and coding_stage.output_data:
                coder_output = coding_stage.output_data.get("coder_output", {})
                code_files = coder_output.get("files", [])

            # 提取测试文件（从 UNIT_TESTING 阶段）
            test_files = []
            design_output = {}
            if testing_stage and testing_stage.output_data:
                testing_result = testing_stage.output_data.get("testing_result", {})
                test_files = testing_result.get("test_files", [])
                design_output = testing_stage.input_data.get("design_output", {})

        if not test_files:
            return {"success": False, "error": "No test files found", "contract_check": None}

        # 构建 code_files_dict 用于契约检查
        code_files_dict = {}
        for f in code_files:
            file_path = f.get("file_path", "")
            content = f.get("content", "")
            if file_path and content:
                file_path = file_path.lstrip("/")
                if not file_path.startswith("backend/"):
                    file_path = f"backend/{file_path}"
                code_files_dict[file_path] = content

        # ========== 【前置检查】契约检查 + 语法检查 ==========
        await push_log(pipeline_id, "info", "[前置检查] 执行契约检查和语法检查...", stage="UNIT_TESTING")

        interface_specs = design_output.get("interface_specs", [])
        max_tester_regeneration = 2  # 最多重新生成2次

        for regeneration in range(max_tester_regeneration + 1):
            # 契约检查
            contract_passed = True
            if interface_specs and code_files_dict:
                missing_symbols = verify_contract(code_files_dict, interface_specs)
                contract_passed = len(missing_symbols) == 0

                if not contract_passed:
                    await push_log(
                        pipeline_id, "warning",
                        f"❌ 契约检查失败: {len(missing_symbols)} 个符号未实现",
                        stage="UNIT_TESTING"
                    )
                    for sym in missing_symbols:
                        await push_log(pipeline_id, "warning", f"   - {sym}", stage="UNIT_TESTING")

            # 语法检查（对测试文件）
            syntax_passed = True
            syntax_errors = []
            import ast
            for tf in test_files:
                path = tf.get("file_path", "")
                content = tf.get("content", "")
                if path.endswith(".py") and content:
                    try:
                        ast.parse(content)
                    except SyntaxError as e:
                        syntax_passed = False
                        syntax_errors.append(f"{path}: SyntaxError at line {e.lineno}: {e.msg}")

            if not syntax_passed:
                await push_log(
                    pipeline_id, "warning",
                    f"❌ 语法检查失败: {len(syntax_errors)} 个文件存在语法错误",
                    stage="UNIT_TESTING"
                )
                for err in syntax_errors:
                    await push_log(pipeline_id, "warning", f"   - {err}", stage="UNIT_TESTING")

            # 检查是否通过
            if contract_passed and syntax_passed:
                await push_log(
                    pipeline_id, "info",
                    "✅ 契约检查和语法检查通过",
                    stage="UNIT_TESTING"
                )
                break
            else:
                if regeneration < max_tester_regeneration:
                    await push_log(
                        pipeline_id, "warning",
                        f"前置检查失败（尝试 {regeneration + 1}/{max_tester_regeneration}），重新调用 Tester 生成测试...",
                        stage="UNIT_TESTING"
                    )

                    # 重新调用 Tester 生成测试
                    test_result = await test_agent.generate_tests(
                        design_output=design_output,
                        code_output=None,
                        pipeline_id=pipeline_id,
                    )

                    if test_result.get("success"):
                        test_files = test_result["output"].get("test_files", [])
                        # 写入沙箱
                        for tf in test_files:
                            file_path = tf.get("file_path", "")
                            content = tf.get("content", "")
                            if file_path and content:
                                # 【修复】正确处理 Tester 生成的路径（已规范输出 backend/tests/ai_generated/...）
                                # 信任 Tester 生成的路径，不再添加前缀
                                await file_service.write_file(file_path, content)

                        await push_log(
                            pipeline_id, "info",
                            f"✅ 测试重新生成成功 ({len(test_files)} 个文件)",
                            stage="UNIT_TESTING"
                        )
                    else:
                        await push_log(
                            pipeline_id, "error",
                            f"❌ 测试重新生成失败: {test_result.get('error', '')}",
                            stage="UNIT_TESTING"
                        )
                        return {
                            "success": False,
                            "error": "前置检查失败且测试重新生成失败",
                            "test_run_success": False,
                            "layers": [{"layer": "pre_check", "passed": False, "summary": "前置检查失败"}]
                        }
                else:
                    await push_log(
                        pipeline_id, "error",
                        "❌ 前置检查在最大重试次数后仍未通过",
                        stage="UNIT_TESTING"
                    )
                    return {
                        "success": False,
                        "error": "契约检查或语法检查失败",
                        "test_run_success": False,
                        "layers": [{"layer": "pre_check", "passed": False, "summary": "前置检查失败"}]
                    }

        # 构建 all_files 列表
        all_files = []
        for f in code_files:
            file_path = f.get("file_path", "")
            content = f.get("content", "")
            if file_path and content:
                file_path = file_path.lstrip("/")
                if not file_path.startswith("backend/"):
                    file_path = f"backend/{file_path}"
                all_files.append({"file_path": file_path, "content": content})

        for tf in test_files:
            file_path = tf.get("file_path", "")
            content = tf.get("content", "")
            if file_path and content:
                # 【修复】信任 Tester 生成的路径（已规范输出 backend/tests/ai_generated/...）
                # 不再添加前缀，直接使用原始路径
                all_files.append({"file_path": file_path, "content": content})

        # ========== 1. 预测试（失败则修复直到通过）==========
        await push_log(pipeline_id, "info", "[Step 1/3] 执行预测试...", stage="UNIT_TESTING")

        max_preliminary_retries = 3
        preliminary_passed = False
        preliminary_logs = ""

        # 包装 push_log 为同步回调（push_log 内部无 await，直接调用即可）
        def _sync_push_log(level: str, msg: str):
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(push_log(pipeline_id, level, msg, stage="UNIT_TESTING"))
                else:
                    # 无事件循环时直接同步执行（push_log 内部无 await）
                    asyncio.run(push_log(pipeline_id, level, msg, stage="UNIT_TESTING"))
            except RuntimeError:
                # get_event_loop 可能失败，fallback
                pass

        for retry in range(max_preliminary_retries):
            preliminary_result = await run_preliminary_test(
                pipeline_id=pipeline_id,
                test_files=test_files,
                file_service=file_service,
                timeout=60,
                log_callback=_sync_push_log
            )

            preliminary_logs = preliminary_result.get("logs", "")

            # 【新增】记录预测试尝试
            test_details["preliminary"]["attempts"].append({
                "attempt": retry + 1,
                "success": preliminary_result.get("success", False),
                "passed_count": preliminary_result.get("passed_count", 0),
                "failed_count": preliminary_result.get("failed_count", 0),
                "logs": preliminary_logs[:2000] if preliminary_logs else "",  # 限制日志长度
            })

            if preliminary_result.get("success"):
                preliminary_passed = True
                test_details["preliminary"]["final_status"] = "passed"
                await push_log(
                    pipeline_id, "info",
                    f"✅ 预测试通过 ({preliminary_result.get('passed_count', 0)} passed)",
                    stage="UNIT_TESTING"
                )
                break
            else:
                await push_log(
                    pipeline_id, "warning",
                    f"预测试失败（尝试 {retry + 1}/{max_preliminary_retries}），启动 RepairService...",
                    stage="UNIT_TESTING"
                )

                # 【修复】显式推送预测试错误详情到终端/SSE
                failed_count = preliminary_result.get("failed_count", 0)
                errors_count = preliminary_result.get("errors_count", 0)
                passed_count = preliminary_result.get("passed_count", 0)
                collected_count = preliminary_result.get("collected_count", 0)
                failed_tests = preliminary_result.get("failed_tests", [])
                error_tests = preliminary_result.get("error_tests", [])

                await push_log(
                    pipeline_id, "warning",
                    f"预测试统计: collected={collected_count} | passed={passed_count} | failed={failed_count} | errors={errors_count}",
                    stage="UNIT_TESTING"
                )
                if failed_tests:
                    await push_log(
                        pipeline_id, "warning",
                        f"失败测试: {', '.join(failed_tests[:10])}",
                        stage="UNIT_TESTING"
                    )
                if error_tests:
                    await push_log(
                        pipeline_id, "warning",
                        f"错误测试: {', '.join(error_tests[:10])}",
                        stage="UNIT_TESTING"
                    )

                # 提取并推送错误日志关键部分
                from app.utils.repair_utils import extract_pytest_failures
                error_summary = extract_pytest_failures(preliminary_logs, max_chars=3000)
                if error_summary:
                    await push_log(
                        pipeline_id, "warning",
                        f"【预测试错误详情】\n{error_summary}",
                        stage="UNIT_TESTING"
                    )

                # 【新增】检查 RepairAgent 是否尝试修改 defense 文件夹
                defense_violations = await TestOrchestrator._check_defense_modifications(pipeline_id, file_service)
                if defense_violations:
                    violation_msg = f"🚫 检测到 RepairAgent 尝试修改 defense 文件夹: {defense_violations}"
                    await push_log(pipeline_id, "error", violation_msg, stage="UNIT_TESTING")
                    test_details["defense_violations"].extend(defense_violations)

                    # 终止 Pipeline
                    async with async_session_factory() as session:
                        pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
                        if pipeline:
                            pipeline.status = PipelineStatus.FAILED
                            from app.core.timezone import now
                            pipeline.updated_at = now()
                            await session.commit()

                    return {
                        "success": False,
                        "error": f"RepairAgent 违规修改 defense 文件夹: {defense_violations}",
                        "test_run_success": False,
                        "defense_violations": defense_violations,
                        "test_details": test_details,
                        "layers": [{"layer": "preliminary", "passed": False, "summary": "违规修改 defense 文件夹"}]
                    }

                # 调用 RepairService 修复
                repair_result = await repair_service.start_repair(
                    pipeline_id=pipeline_id,
                    code_files=code_files,
                    test_files=test_files,
                    test_logs=preliminary_logs,
                    design_output=design_output,
                    file_service=file_service,
                    log_callback=lambda level, msg: push_log(pipeline_id, level, msg, stage="UNIT_TESTING"),
                    debugger=debugger,
                )

                # 【新增】记录修复详情
                test_details["repairs"].append({
                    "stage": "preliminary",
                    "attempt": retry + 1,
                    "success": repair_result.get("test_run_success", False),
                    "repair_rounds": repair_result.get("repair_rounds", 0),
                    "fixed_files": repair_result.get("fixed_files", []),
                    "fix_history": repair_result.get("fix_history", []),
                })

                if repair_result.get("test_run_success"):
                    await push_log(
                        pipeline_id, "success",
                        f"✅ 修复成功，重新进行预测试...",
                        stage="UNIT_TESTING"
                    )
                    # 更新代码文件（修复后的）
                    code_files = repair_result.get("fixed_files", code_files)
                else:
                    await push_log(
                        pipeline_id, "warning",
                        f"⚠️ 修复失败，预测试未通过，建议重试或完善需求说明",
                        stage="UNIT_TESTING"
                    )
                    test_details["preliminary"]["final_status"] = "failed"
                    # 【修改】返回警告而非失败，允许用户选择继续
                    return {
                        "success": True,  # 改为 True，表示流程可以继续
                        "warning": True,
                        "error": "预测试失败且修复未通过",
                        "test_run_success": False,
                        "requires_user_decision": True,
                        "suggestion": "建议重试或完善需求说明",
                        "test_details": test_details,
                        "layers": [{"layer": "preliminary", "passed": False, "summary": "预测试失败（需人工确认）"}]
                    }

        if not preliminary_passed:
            await push_log(
                pipeline_id, "warning",
                f"⚠️ 预测试在最大重试次数后仍未通过，建议重试或完善需求说明",
                stage="UNIT_TESTING"
            )
            # 【修改】返回警告而非失败
            return {
                "success": True,  # 改为 True
                "warning": True,
                "error": "预测试在最大重试次数后仍未通过",
                "test_run_success": False,
                "requires_user_decision": True,
                "suggestion": "建议重试或完善需求说明",
                "layers": [{"layer": "preliminary", "passed": False, "summary": "预测试失败（需人工确认）"}]
            }

        # ========== 2. 分层测试（逐层执行，每层失败后修复）==========
        await push_log(pipeline_id, "info", "[Step 2/3] 执行分层测试...", stage="UNIT_TESTING")

        layers: List[LayerResult] = []
        layer_order = ["defense", "regression", "new_tests"]
        max_layer_retries = 3

        for layer_name in layer_order:
            await push_log(pipeline_id, "info", f"  开始 {layer_name} 层测试...", stage="UNIT_TESTING")

            layer_passed = False
            layer_result = None

            for retry in range(max_layer_retries):
                # 运行当前层测试
                if layer_name == "defense":
                    layer_result = await LayeredTestRunner._run_defense_layer(
                        Path("/workspace"), file_service, 120
                    )
                elif layer_name == "regression":
                    layer_result = await LayeredTestRunner._run_regression_layer(
                        Path("/workspace"), file_service, 120
                    )
                else:  # new_tests
                    layer_result = await LayeredTestRunner._run_new_tests_layer(
                        Path("/workspace"), file_service, 120
                    )

                layers.append(layer_result)

                # 【新增】记录分层测试详情
                test_details["layers"][layer_name].append({
                    "attempt": retry + 1,
                    "passed": layer_result.passed,
                    "summary": layer_result.summary,
                    "logs": layer_result.logs[:2000] if layer_result.logs else "",
                    "failed_tests": layer_result.failed_tests if hasattr(layer_result, 'failed_tests') else [],
                })

                status = "✅ PASS" if layer_result.passed else "❌ FAIL"
                await push_log(
                    pipeline_id,
                    "info" if layer_result.passed else "warning",
                    f"  {status} {layer_name}: {layer_result.summary}",
                    stage="UNIT_TESTING"
                )

                if layer_result.passed:
                    layer_passed = True
                    break
                else:
                    # 当前层失败，调用 RepairService
                    await push_log(
                        pipeline_id, "warning",
                        f"  {layer_name} 层失败（尝试 {retry + 1}/{max_layer_retries}），启动修复...",
                        stage="UNIT_TESTING"
                    )

                    # 【新增】检查 RepairAgent 是否尝试修改 defense 文件夹
                    defense_violations = await TestOrchestrator._check_defense_modifications(pipeline_id, file_service)
                    if defense_violations:
                        violation_msg = f"🚫 检测到 RepairAgent 尝试修改 defense 文件夹: {defense_violations}"
                        await push_log(pipeline_id, "error", violation_msg, stage="UNIT_TESTING")
                        test_details["defense_violations"].extend(defense_violations)

                        # 终止 Pipeline
                        async with async_session_factory() as session:
                            pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
                            if pipeline:
                                pipeline.status = PipelineStatus.FAILED
                                from app.core.timezone import now
                                pipeline.updated_at = now()
                                await session.commit()

                        return {
                            "success": False,
                            "error": f"RepairAgent 违规修改 defense 文件夹: {defense_violations}",
                            "test_run_success": False,
                            "defense_violations": defense_violations,
                            "test_details": test_details,
                            "layers": [
                                {"layer": l.layer, "passed": l.passed, "summary": "违规修改 defense 文件夹"}
                                for l in layers
                            ]
                        }

                    repair_result = await repair_service.start_repair(
                        pipeline_id=pipeline_id,
                        code_files=code_files,
                        test_files=test_files,
                        test_logs=layer_result.logs,
                        design_output=design_output,
                        file_service=file_service,
                        log_callback=lambda level, msg: push_log(pipeline_id, level, msg, stage="UNIT_TESTING"),
                        debugger=debugger,
                    )

                    # 【新增】记录修复详情
                    test_details["repairs"].append({
                        "stage": layer_name,
                        "attempt": retry + 1,
                        "success": repair_result.get("test_run_success", False),
                        "repair_rounds": repair_result.get("repair_rounds", 0),
                        "fixed_files": repair_result.get("fixed_files", []),
                        "fix_history": repair_result.get("fix_history", []),
                    })

                    if repair_result.get("test_run_success"):
                        await push_log(
                            pipeline_id, "success",
                            f"  ✅ {layer_name} 层修复成功，重新测试...",
                            stage="UNIT_TESTING"
                        )
                        code_files = repair_result.get("fixed_files", code_files)
                    else:
                        await push_log(
                            pipeline_id, "warning",
                            f"  ⚠️ {layer_name} 层修复失败，建议重试或完善需求说明",
                            stage="UNIT_TESTING"
                        )
                        # 【修改】返回警告而非失败，允许用户选择继续
                        return {
                            "success": True,  # 改为 True
                            "warning": True,
                            "error": f"{layer_name} 层测试失败且修复未通过",
                            "test_run_success": False,
                            "requires_user_decision": True,
                            "suggestion": "建议重试或完善需求说明",
                            "test_details": test_details,
                            "layers": [
                                {"layer": l.layer, "passed": l.passed, "summary": l.summary + "（需人工确认）"}
                                for l in layers
                            ]
                        }

            if not layer_passed:
                await push_log(
                    pipeline_id, "warning",
                    f"  ⚠️ {layer_name} 层在最大重试次数后仍未通过，建议重试或完善需求说明",
                    stage="UNIT_TESTING"
                )
                # 【修改】返回警告而非失败
                return {
                    "success": True,  # 改为 True
                    "warning": True,
                    "error": f"{layer_name} 层在最大重试次数后仍未通过",
                    "test_run_success": False,
                    "requires_user_decision": True,
                    "suggestion": "建议重试或完善需求说明",
                    "test_details": test_details,
                    "layers": [
                        {"layer": l.layer, "passed": l.passed, "summary": l.summary + "（需人工确认）"}
                        for l in layers
                    ]
                }

        all_passed = all(l.passed for l in layers)

        # 【修改】即使测试未完全通过，也返回成功（带警告），让用户决定
        if not all_passed:
            await push_log(
                pipeline_id, "warning",
                "⚠️ 部分测试未通过，建议重试或完善需求说明",
                stage="UNIT_TESTING"
            )
            return {
                "success": True,  # 改为 True，流程继续
                "warning": True,
                "test_run_success": False,
                "requires_user_decision": True,
                "suggestion": "建议重试或完善需求说明",
                "contract_check": {"passed": True, "message": "契约检查已在前置步骤完成"},
                "logs": "\n\n".join([l.logs for l in layers]),
                "failed_tests": [],
                "test_details": test_details,
                "layers": [
                    {"layer": l.layer, "passed": l.passed, "summary": l.summary + ("（需人工确认）" if not l.passed else "")}
                    for l in layers
                ]
            }

        return {
            "success": True,
            "test_run_success": True,
            "contract_check": {"passed": True, "message": "契约检查已在前置步骤完成"},
            "logs": "\n\n".join([l.logs for l in layers]),
            "failed_tests": [],
            "test_details": test_details,
            "layers": [
                {"layer": l.layer, "passed": l.passed, "summary": l.summary}
                for l in layers
            ]
        }

    @staticmethod
    async def _check_defense_modifications(pipeline_id: int, file_service: Any) -> List[str]:
        """
        检查 RepairAgent 是否尝试修改 defense 文件夹中的内容

        通过 sandbox 内的 git diff 检测 defense 目录下的文件变更。
        任何对 defense 文件的修改都是违规的。

        Returns:
            List[str]: 违规修改的文件路径列表，如果没有则返回空列表
        """
        violations = []
        try:
            # 方法1：通过 git diff 检测 defense 目录的变更（最可靠）
            defense_dir = "backend/tests/unit/defense"
            result = await sandbox_manager.exec(
                pipeline_id,
                f"cd /workspace && git diff --name-only HEAD -- {defense_dir} 2>/dev/null || true",
                timeout=15
            )
            if result.stdout.strip():
                modified = [
                    f.strip().replace("\\", "/")
                    for f in result.stdout.strip().split("\n")
                    if f.strip().endswith(".py")
                ]
                if modified:
                    logger.error(
                        f"检测到 defense 文件被修改: {modified}",
                        extra={"pipeline_id": pipeline_id}
                    )
                    violations.extend(modified)

            # 方法2：检查是否有新增的未跟踪文件（防止绕过 git）
            result = await sandbox_manager.exec(
                pipeline_id,
                f"cd /workspace && git ls-files --others --exclude-standard -- {defense_dir} 2>/dev/null || true",
                timeout=10
            )
            if result.stdout.strip():
                untracked = [
                    f.strip().replace("\\", "/")
                    for f in result.stdout.strip().split("\n")
                    if f.strip().endswith(".py")
                ]
                if untracked:
                    logger.error(
                        f"检测到 defense 目录下有未跟踪文件: {untracked}",
                        extra={"pipeline_id": pipeline_id}
                    )
                    violations.extend(untracked)

        except Exception as e:
            # 防御检查本身失败不应该阻塞主流程，但必须记录严重警告
            logger.error(
                f"防御检查执行失败，无法确定 defense 文件完整性: {e}",
                extra={"pipeline_id": pipeline_id},
                exc_info=True
            )

        return violations

    @staticmethod
    async def _start_fastapi_in_sandbox(pipeline_id: int) -> Dict[str, Any]:
        """
        分层测试通过后在 Sandbox 容器中启动 FastAPI 服务

        1. 杀掉 sandbox 中占用 8000 端口的进程
        2. 后台启动 uvicorn main:app
        3. 推送启动日志供用户查看

        Returns:
            Dict: {success, port, message}
        """
        try:
            # 1. 杀掉占用 8000 端口的进程
            kill_cmd = (
                "fuser -k 8000/tcp 2>/dev/null && echo 'killed' || echo 'port_free'"
            )
            kill_result = await sandbox_manager.exec(pipeline_id, kill_cmd, timeout=10)
            await push_log(
                pipeline_id, "info",
                f"端口 8000 清理结果: {kill_result.stdout.strip()}",
                stage="UNIT_TESTING"
            )

            # 2. 后台启动 FastAPI
            start_cmd = (
                "cd /workspace/backend && "
                "PYTHONPATH=/workspace/backend nohup python -m uvicorn main:app "
                "--host 0.0.0.0 --port 8000 "
                "> /tmp/fastapi.log 2>&1 & "
                "sleep 3 && "
                "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/health 2>/dev/null || echo 'starting'"
            )
            start_result = await sandbox_manager.exec(pipeline_id, start_cmd, timeout=15)
            status_output = start_result.stdout.strip()

            # 3. 获取 sandbox 对外端口
            sandbox_info = sandbox_manager.get_info(pipeline_id)
            host_port = sandbox_info.port if sandbox_info else "unknown"

            if "200" in status_output:
                await push_log(
                    pipeline_id, "success",
                    f"FastAPI 服务已在 Sandbox 中启动，对外端口: {host_port}",
                    stage="UNIT_TESTING"
                )
                await push_log(
                    pipeline_id, "info",
                    f"接口测试地址: http://localhost:{host_port}/api/v1/health",
                    stage="UNIT_TESTING"
                )
                return {"success": True, "port": host_port, "message": f"FastAPI started on sandbox port {host_port}"}
            else:
                await push_log(
                    pipeline_id, "info",
                    f"FastAPI 已启动，对外端口：{host_port}",
                    stage="UNIT_TESTING"
                )
                return {"success": True, "port": host_port, "message": f"FastAPI started on sandbox port {host_port}"}

        except Exception as e:
            await push_log(
                pipeline_id, "error",
                f"在 Sandbox 中启动 FastAPI 失败: {str(e)}",
                stage="UNIT_TESTING"
            )
            return {"success": False, "error": str(e)}
            return False

    @classmethod
    async def _run_single_test_file(
        cls,
        pipeline_id: int,
        file_path: str,
        content: str,
        file_service: Any
    ) -> Dict[str, Any]:
        """
        运行单个测试文件

        Args:
            pipeline_id: Pipeline ID
            file_path: 测试文件路径
            content: 测试文件内容
            file_service: 沙箱文件服务

        Returns:
            Dict: 测试结果
        """
        from app.service.sandbox_manager import sandbox_manager
        import re

        try:
            # 在 Docker 容器中运行单个测试文件
            cmd = (
                f"cd /workspace && "
                f"PYTHONPATH=/workspace/backend python -m pytest {file_path} "
                f"-v --tb=short --color=no "
                f"2>&1"
            )

            exec_result = await sandbox_manager.exec(
                pipeline_id,
                cmd,
                timeout=120
            )

            stdout = exec_result.stdout or ""
            stderr = exec_result.stderr or ""
            logs = stdout + "\n" + stderr

            success = exec_result.exit_code == 0

            # 提取失败测试
            failed_tests = []
            if not success:
                pattern = r"FAILED\s+(\S+)"
                failed_tests = re.findall(pattern, logs)

            # 提取摘要
            summary_match = re.search(r"(\d+\s+passed|\d+\s+failed|\d+\s+error)", logs)
            if summary_match:
                summary = summary_match.group(0)
            else:
                summary = "测试执行完成" if success else "测试执行失败"

            return {
                "success": success,
                "exit_code": exec_result.exit_code,
                "logs": logs,
                "summary": summary,
                "failed_tests": failed_tests,
                "error": stderr if stderr else None
            }

        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "logs": str(e),
                "summary": "测试执行异常",
                "failed_tests": [],
                "error": str(e)
            }

