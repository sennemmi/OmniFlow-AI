"""
修复服务 (RepairService)

统一 E2E 测试和 Pipeline 中的代码修复循环。
使用 FixLoopState 和智能错误路由。
"""

import logging
import re
from typing import Dict, List, Optional, Any, Callable

from app.agents.repairer_with_tools import RepairerAgentWithTools
from app.service.sandbox_file_service import SandboxFileService
from app.service.error_analysis_service import ErrorAnalysisService
from app.core.sse_log_buffer import push_log
from app.utils.fix_loop_utils import (
    FixLoopState,
    FixResult,
    execute_fix_by_type,
    determine_fix_type,
    build_enhanced_design_output,
)
from app.utils.repair_utils import extract_critical_files, build_fix_order
from app.utils.file_utils import read_files_with_size_limit, extract_file_paths

logger = logging.getLogger(__name__)


class RepairService:
    """
    统一的代码修复服务

    职责：
    1. 智能错误类型检测（syntax/import/type/other）
    2. 使用 FixLoopState 管理修复状态
    3. 调用 RepairerAgentWithTools 进行修复
    4. 统一构建修复工单（fix_order）

    使用场景：
    - E2E 测试脚本
    - TestingHandler (Pipeline)
    - AutoFixLoop 中的修复阶段
    """

    MAX_REPAIR_ROUNDS = 3

    def __init__(self):
        self.error_analysis_service = ErrorAnalysisService()

    def _analyze_errors(self, logs: str, failed_tests: Optional[List[str]] = None) -> Dict[str, List[Any]]:
        """分析错误日志，分类返回错误信息"""
        if failed_tests is None:
            failed_tests = []
        return {
            "syntax_errors": self.error_analysis_service.extract_syntax_errors(logs),
            "import_errors": self.error_analysis_service.extract_import_errors(logs),
            "logic_errors": self.error_analysis_service.extract_logic_errors(logs, failed_tests),
            "type_errors": self.error_analysis_service.extract_type_errors_in_test(logs)
        }

    def _extract_missing_symbols(self, logs: str) -> List[str]:
        """从日志中提取缺失符号"""
        return self.error_analysis_service.extract_missing_symbols(logs)

    async def start_repair(
        self,
        pipeline_id: int,
        code_files: List[Dict[str, Any]],
        test_files: List[Dict[str, Any]],
        test_logs: str,
        design_output: Dict[str, Any],
        file_service: SandboxFileService,
        log_callback: Optional[Callable[[str, str], Any]] = None,
        debugger: Optional[Any] = None,
        executor: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        启动智能修复循环

        Args:
            pipeline_id: Pipeline ID
            code_files: 代码文件列表
            test_files: 测试文件列表
            test_logs: 测试日志
            design_output: 设计输出
            file_service: 沙箱文件服务
            log_callback: 日志回调函数
            debugger: AgentDebugger 实例
            executor: CodeExecutorService 实例（用于读取修复后的文件）

        Returns:
            Dict: {
                "success": bool,
                "repair_rounds": int,
                "test_run_success": bool,
                "fixed_files": List[str],
                "fix_history": List[Dict],
                "error": Optional[str],
            }
        """
        def log(level: str, message: str):
            if log_callback:
                log_callback(level, message)
            else:
                getattr(logger, level.lower(), logger.info)(message)
            push_log(pipeline_id, level.lower(), message, stage="REPAIR")

        log("info", "🔧 启动智能修复循环...")

        # 初始化 FixLoopState
        state = FixLoopState(
            code_files=code_files,
            test_files=test_files,
            max_retries=self.MAX_REPAIR_ROUNDS
        )

        # 提取失败的测试
        failed_tests = re.findall(r'FAILED\s+(\S+)', test_logs)
        log("info", f"📋 发现 {len(failed_tests)} 个失败测试")

        while state.attempt < state.max_retries:
            state.attempt += 1
            log("info", f"🔄 第 {state.attempt}/{state.max_retries} 次修复尝试")

            # 分析错误类型
            error_analysis = self._analyze_errors(test_logs, failed_tests)
            fix_type = determine_fix_type(error_analysis)
            log("info", f"🎯 检测到错误类型: {fix_type}")

            # 构建增强的设计输出
            enhanced_design = build_enhanced_design_output(
                design_output=design_output,
                fix_history=state.fix_history,
                current_error=test_logs[:500] if test_logs else ""
            )
            enhanced_design["pipeline_id"] = pipeline_id

            fix_success = False
            fix_message = ""

            # 根据错误类型选择修复策略
            if fix_type in ["syntax", "import"]:
                # 使用 execute_fix_by_type 修复语法/导入错误
                log("info", f"🔧 使用自动修复策略: {fix_type}")
                result = await execute_fix_by_type(
                    fix_type=fix_type,
                    state=state,
                    file_service=file_service,
                    design_output=enhanced_design,
                    error_analysis_service=self.error_analysis_service,
                    logs=test_logs,
                    failed_tests=failed_tests
                )
                fix_success = result.success
                fix_message = result.message

                if result.new_code_files:
                    state.update_code_files(result.new_code_files)
                if result.new_test_files:
                    state.update_test_files(result.new_test_files)

            elif fix_type == "type":
                # 类型错误修复
                type_errors = error_analysis.get("type_errors", [])
                log("info", f"🔧 修复类型错误: {len(type_errors)} 个")
                fix_success = await self._fix_type_errors(
                    pipeline_id=pipeline_id,
                    type_errors=type_errors,
                    test_files=state.test_files,
                    design_output=enhanced_design,
                    file_service=file_service,
                )
                fix_message = "类型错误修复"

            else:
                # 其他错误，使用 RepairerAgentWithTools
                log("info", "🎯 路由到 RepairerAgent")

                missing = self._extract_missing_symbols(test_logs)
                repair_result = await self._run_repair_with_fix_order(
                    pipeline_id=pipeline_id,
                    test_files=state.test_files,
                    code_files=state.code_files,
                    test_logs=test_logs,
                    design_output=design_output,
                    file_service=file_service,
                    missing_symbols=missing,
                    debugger=debugger,
                )

                fix_success = repair_result.get("success", False)
                fix_message = "RepairerAgent 修复"

                # 如果修复成功，更新代码文件
                if fix_success and executor:
                    updated_code_files = await self._read_updated_files(
                        state.code_files, executor
                    )
                    state.update_code_files(updated_code_files)

            # 记录修复历史
            state.record_fix(
                fix_type=fix_type,
                success=fix_success,
                details={"message": fix_message, "failed_tests_count": len(failed_tests)}
            )

            if not fix_success:
                log("warning", f"❌ 本轮修复失败: {fix_message}")
                break

            log("success", f"✅ 本轮修复成功: {fix_message}")

            # 重新运行测试验证修复
            log("info", "🔄 重新运行测试验证修复...")
            from app.utils.test_execution import run_pytest_in_sandbox

            # 从 test_files 构建测试路径（与 RepairerAgent 保持一致）
            test_paths = []
            for tf in state.test_files:
                fp = tf.get("file_path", "")
                if fp:
                    # 确保路径格式正确
                    if "tests/ai_generated" in fp:
                        test_paths.append(fp)
                    elif "tests/" in fp:
                        test_paths.append(fp)
                    else:
                        test_paths.append(f"backend/tests/ai_generated/{fp.split('/')[-1]}")

            # 如果没有测试文件，使用默认路径
            if test_paths:
                test_path_str = " ".join(test_paths)
            else:
                test_path_str = "backend/tests/ai_generated"

            log("info", f"🧪 运行测试: {test_path_str}")

            test_result = await run_pytest_in_sandbox(
                pipeline_id=pipeline_id,
                test_path=test_path_str,
                timeout=120,
            )

            if test_result.get("success"):
                log("success", "📊 修复后测试通过！")
                return {
                    "success": True,
                    "repair_rounds": state.attempt,
                    "test_run_success": True,
                    "fixed_files": [],
                    "fix_history": state.fix_history,
                }
            else:
                log("warning", "📊 修复后测试仍有失败，继续下一轮...")

            # 更新测试日志和失败测试列表
            test_logs = test_result.get("logs", "")
            failed_tests = re.findall(r'FAILED\s+(\S+)', test_logs)

        # 达到最大重试次数
        log("error", f"🚨 已达到最大重试次数 ({state.max_retries})")

        return {
            "success": False,
            "repair_rounds": state.attempt,
            "test_run_success": False,
            "error": f"Auto-fix failed after {state.attempt} rounds",
            "fix_history": state.fix_history,
        }

    async def _run_repair_with_fix_order(
        self,
        pipeline_id: int,
        test_files: List[Dict[str, Any]],
        code_files: List[Dict[str, Any]],
        test_logs: str,
        design_output: Dict[str, Any],
        file_service: SandboxFileService,
        missing_symbols: List[str],
        debugger: Optional[Any],
    ) -> Dict[str, Any]:
        """
        使用 RepairerAgentWithTools 进行修复
        """
        all_generated_files = code_files + test_files
        generated_file_paths = extract_file_paths(all_generated_files)

        # 收集文件内容
        file_contents = {}
        for file_info in all_generated_files:
            file_path = file_info.get("file_path", "")
            content = file_info.get("content", "")
            if file_path and content:
                file_contents[file_path] = content

        # 提取关键文件
        essential_paths = extract_critical_files(
            logs=test_logs,
            all_generated_paths=generated_file_paths
        )

        # 构建修复工单
        failed_tests = re.findall(r'FAILED\s+(\S+)', test_logs)
        fix_order = build_fix_order(
            failed_tests=failed_tests,
            logs=test_logs,
            generated_file_paths=essential_paths,
            missing_symbols=missing_symbols
        )

        # 构建目标文件字典
        target_files = {}
        for path in essential_paths:
            if path in file_contents:
                target_files[path] = file_contents[path]

        # 调用 RepairerAgentWithTools
        repairer = RepairerAgentWithTools()
        repair_result = await repairer.execute_with_tools(
            pipeline_id=pipeline_id,
            stage_name="REPAIR",
            fix_order=fix_order,
            target_files=target_files,
            file_service=file_service,
            max_rounds=3,
            debugger=debugger
        )

        return repair_result

    async def _fix_type_errors(
        self,
        pipeline_id: int,
        type_errors: List[Dict],
        test_files: List[Dict[str, Any]],
        design_output: Dict[str, Any],
        file_service: SandboxFileService,
    ) -> bool:
        """
        修复测试文件中的类型错误
        """
        from app.agents.tester import tester_agent
        from app.utils.agent_instruction_utils import build_type_error_fix_instruction

        push_log(
            pipeline_id,
            "info",
            "🔧 TesterAgent: 修复测试类型错误",
            stage="REPAIR"
        )

        fix_input = {
            "design_output": {
                **design_output,
                "fix_mode": True,
                "fix_instruction": build_type_error_fix_instruction(type_errors),
                "affected_files": [tf.get("file_path", "") for tf in test_files]
            },
            "code_output": {"files": []},
            "target_files": {tf.get("file_path", ""): tf for tf in test_files},
            "pipeline_id": pipeline_id
        }

        fix_result = await tester_agent.generate_tests(**fix_input)

        if fix_result.get("success"):
            fixed_test_files = fix_result.get("output", {}).get("files", [])
            for test_file in fixed_test_files:
                file_path = test_file.get("file_path", "")
                content = test_file.get("content", "")
                if file_path and content:
                    await file_service.write_file(file_path, content)
            return True
        return False

    async def _read_updated_files(
        self,
        code_files: List[Dict[str, Any]],
        executor: Any,
    ) -> List[Dict[str, Any]]:
        """
        读取修复后的文件内容
        """
        updated_files = []
        for f in code_files:
            fp = f.get("file_path", "")
            try:
                content = executor.read_file(fp.replace("backend/", "").replace("backend\\", ""))
                if content:
                    updated_files.append({**f, "content": content})
                else:
                    updated_files.append(f)
            except Exception:
                updated_files.append(f)
        return updated_files


# 全局单例实例
repair_service = RepairService()
