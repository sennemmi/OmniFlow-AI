#!/usr/bin/env python3
"""
端到端集成测试（契约增强版 V2）- 高度重构版本

基于 test_e2e_with_contract_refactored.py 进一步重构：
1. 复用 utils 工具模块：file_operation_utils, agent_instruction_utils, repair_loop_utils
2. 复用后端服务：E2ETestService
3. 测试脚本只保留最核心的流程编排逻辑

警告: 此脚本会调用真实 LLM 并启动 Docker，请确保配置正确。
"""

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.architect import architect_agent
from app.agents.coder import coder_agent, CoderAgent, CoderOutput
from app.agents.designer import designer_agent
from app.agents.repairer_with_tools import RepairerAgentWithTools
from app.agents.tester import tester_agent
from app.service.e2e_test_service import E2ETestService
from app.service.layered_test_runner import LayeredTestResult
from app.service.sandbox_file_service import SandboxFileService
from app.service.sandbox_orchestrator import (
    cleanup_sandbox_orchestrator,
    get_sandbox_orchestrator,
)
from app.utils.agent_instruction_utils import (
    build_key_mismatch_fix_instruction,
    build_key_mismatch_repair_instruction,
    build_retry_fix_instruction,
    build_type_error_fix_instruction,
)
from app.utils.agent_output_utils import (
    extract_code_files,
    extract_key_mismatches,
    extract_test_files,
    get_agent_output_dict,
    merge_files_content,
    print_code_files_summary,
)
from app.utils.env_utils import check_api_key, check_docker
from app.utils.file_operation_utils import (
    merge_and_write_files,
    normalize_file_path,
)
from app.utils.fix_loop_utils import (
    FixLoopState,
    build_enhanced_design_output,
    determine_fix_type,
    execute_fix_by_type,
)
from app.utils.repair_loop_utils import (
    run_contract_fix_loop,
    run_syntax_fix_loop,
    run_test_import_fix_loop,
    run_test_syntax_fix_loop,
)
from app.utils.repair_utils import (
    build_fix_order,
    collect_target_files_async,
    extract_file_paths,
    extract_pytest_failures,
    print_fix_result,
)

# ========================== 测试配置 ==========================
PIPELINE_ID = 99999
FEATURE_REQUEST = "在健康检查接口中增加系统组件状态监控（数据库、磁盘、内存），并给出整体健康度。"

# 默认重试次数
DEFAULT_MAX_RETRIES = 3


def add_agent_tokens(agent_result: Dict, tester: "ContractE2ETester") -> None:
    """添加 Agent 调用的 Token 统计"""
    tester.total_input_tokens += agent_result.get("input_tokens", 0)
    tester.total_output_tokens += agent_result.get("output_tokens", 0)


def build_design_output_with_pipeline(design_output: Dict, pipeline_id: int) -> Dict:
    """构建包含 pipeline_id 的设计输出"""
    return {**design_output, "pipeline_id": pipeline_id}


@dataclass
class E2EContractResult:
    success: bool
    code_generated: bool
    tests_generated: bool
    tests_passed: bool
    layered_result: Optional[LayeredTestResult] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0.0


class ContractE2ETester:
    def __init__(self):
        self.backend_dir = Path(__file__).parent.parent
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.e2e_service = E2ETestService()

    def check_api_key(self) -> bool:
        return check_api_key(self.backend_dir)

    def check_docker(self) -> bool:
        return check_docker()

    def build_file_tree(self) -> Dict[str, Any]:
        return {}

    async def _handle_key_mismatch_retry(
        self,
        key_mismatches: List[Dict],
        design_output: Dict,
        injected_files: Dict[str, str]
    ) -> Optional[Dict]:
        """处理返回键名不匹配的重试逻辑"""
        max_retries = 3
        key_mismatch_instruction = build_key_mismatch_fix_instruction(
            key_mismatches, injected_files
        )

        for retry_attempt in range(max_retries):
            print(f"\n   🔧 返回键名不匹配，第 {retry_attempt + 1}/{max_retries} 次重试...")

            instruction, force_full_file = build_retry_fix_instruction(
                retry_attempt, max_retries, key_mismatch_instruction
            )

            retry_design_output = {
                **design_output,
                "fix_mode": True,
                "force_full_file": force_full_file,
                "fix_instruction": instruction,
                "affected_files": list(injected_files.keys())
            }

            print(f"   📝 调用 CoderAgent 重试 (force_full_file={force_full_file})...")

            retry_result = await coder_agent.generate_code(
                design_output=retry_design_output,
                pipeline_id=PIPELINE_ID,
                injected_files=injected_files
            )

            if retry_result.get("success"):
                print(f"   ✅ 第 {retry_attempt + 1} 次重试成功")
                return retry_result
            else:
                print(f"   ❌ 第 {retry_attempt + 1} 次重试失败: {retry_result.get('error')}")

        return None

    async def _apply_coder_result(
        self,
        coder_result: Dict,
        file_service: SandboxFileService
    ) -> List[Dict]:
        """应用 CoderAgent 的结果"""
        code_files = extract_code_files(coder_result.get("output", {}))

        if not code_files:
            print("   ⚠️ CoderAgent 未生成任何文件")
            return []

        print_code_files_summary(code_files)

        # 创建重试回调函数
        async def retry_callback(fp, sb, rb, cc):
            return await self._handle_search_block_retry(fp, sb, rb, cc)

        # 使用工具函数合并写入，传入重试回调
        written_count = await merge_and_write_files(code_files, file_service, retry_callback)
        print(f"   ✅ 写入完成: {written_count} 个文件")

        return code_files

    async def _handle_search_block_retry(
        self,
        file_path: str,
        search_block: str,
        replace_block: str,
        current_content: str
    ) -> tuple[bool, str]:
        """
        处理 search_block 不匹配的重试
        返回 (success, new_content)
        """
        from app.utils.agent_instruction_utils import build_search_block_retry_instruction

        max_retries = 3
        for retry_attempt in range(max_retries):
            print(f"      🔄 重新请求 CoderAgent 修复 {file_path} (第 {retry_attempt + 1}/{max_retries} 次)...")

            retry_result = await coder_agent.generate_code(
                design_output={
                    "fix_mode": True,
                    "fix_instruction": build_search_block_retry_instruction(
                        file_path, current_content, replace_block
                    ),
                    "affected_files": [file_path]
                },
                pipeline_id=PIPELINE_ID,
                injected_files={file_path: current_content}
            )

            if retry_result.get("success"):
                retry_output = retry_result.get("output", {})
                if isinstance(retry_output, CoderOutput):
                    retry_files = [f.model_dump() for f in retry_output.files]
                else:
                    retry_files = retry_output.get("files", [])

                for rfc in retry_files:
                    rfp = normalize_file_path(rfc.get("file_path", ""))
                    if rfp == file_path:
                        r_search = rfc.get("search_block", "")
                        r_replace = rfc.get("replace_block", "")
                        r_content = rfc.get("content", "")

                        if r_search and r_search in current_content:
                            new_content = current_content.replace(r_search, r_replace, 1)
                            print(f"      ✅ modify(重试成功): {file_path}")
                            return True, new_content
                        elif r_content:
                            print(f"      ✅ modify(重试-完整覆盖): {file_path}")
                            return True, r_content
                        else:
                            print(f"      ⚠️ modify(重试 {retry_attempt + 1} 无法应用): {file_path}")
            else:
                print(f"      ⚠️ modify(重试 {retry_attempt + 1} 失败): {file_path} - {retry_result.get('error', '未知错误')}")

        print(f"      ❌ modify(所有重试均失败): {file_path} - 跳过此修改")
        return False, current_content

    async def run(self) -> E2EContractResult:
        start = time.time()
        print("=" * 70)
        print("🧪 契约增强端到端测试 V2（高度重构版）")
        print("=" * 70)
        print("需求: 系统状态监控 API")
        print()

        if not self.check_api_key():
            return E2EContractResult(False, False, False, False, error_message="API Key 缺失")
        if not self.check_docker():
            return E2EContractResult(False, False, False, False, error_message="Docker 不可用")

        # Step 0: 启动 Sandbox
        print("🐳 启动 Docker Sandbox...")
        sandbox_orch = get_sandbox_orchestrator(PIPELINE_ID)
        project_root = str(self.backend_dir.parent)
        sandbox_init = await sandbox_orch.initialize(project_root)
        if not sandbox_init["success"]:
            return E2EContractResult(False, False, False, False, error_message="Sandbox 启动失败")
        file_service = sandbox_orch.get_file_service()
        print("✅ Sandbox 就绪")

        try:
            # ========== Step 1: 需求分析 ==========
            print("\n📋 Step 1: ArchitectAgent 分析需求...")
            arch_result = await architect_agent.analyze(
                requirement=FEATURE_REQUEST,
                file_tree=self.build_file_tree(),
                pipeline_id=PIPELINE_ID,
                project_path=str(self.backend_dir)
            )
            if not arch_result["success"]:
                raise RuntimeError(f"ArchitectAgent 失败: {arch_result.get('error')}")
            arch_output = arch_result["output"]
            print(f"   验收标准: {arch_output.get('acceptance_criteria', [])}")
            add_agent_tokens(arch_result, self)

            # ========== Step 2: 方案设计 ==========
            print("\n🎨 Step 2: DesignerAgent 技术设计...")
            design_result = await designer_agent.design(
                architect_output=arch_output,
                file_tree=self.build_file_tree(),
                related_code_context="",
                full_files_context=arch_result.get("injected_files", {}),
                pipeline_id=PIPELINE_ID
            )
            if not design_result["success"]:
                raise RuntimeError(f"DesignerAgent 失败: {design_result.get('error')}")
            design_output = design_result["output"]
            interface_specs = design_output.get("interface_specs", [])
            print(f"   接口契约 ({len(interface_specs)} 项)")
            add_agent_tokens(design_result, self)

            # ========== Step 3: 代码生成 ==========
            print("\n📝 Step 3: CoderAgent 生成代码...")
            injected_files = arch_result.get("injected_files", {})

            coder_result = await coder_agent.generate_code(
                design_output=design_output,
                pipeline_id=PIPELINE_ID,
                injected_files=injected_files
            )

            # 处理键名不匹配重试
            if not coder_result.get("success") and "返回键名与契约不一致" in coder_result.get('error', ''):
                key_mismatches = extract_key_mismatches(coder_result.get('output', {}))

                retry_result = await self._handle_key_mismatch_retry(
                    key_mismatches, design_output, injected_files
                )
                if retry_result:
                    coder_result = retry_result
                else:
                    raise RuntimeError("CoderAgent 重试后仍然失败")
            elif not coder_result.get("success"):
                raise RuntimeError(f"CoderAgent 失败: {coder_result.get('error')}")

            code_files = await self._apply_coder_result(coder_result, file_service)
            print(f"   CoderAgent 生成 {len(code_files)} 个文件")
            add_agent_tokens(coder_result, self)

            # ========== Step 4: 测试生成 ==========
            print("\n🧪 Step 4: TesterAgent 生成测试...")
            code_output_dict = get_agent_output_dict(coder_result.get("output", {}))

            # 提取 mock 目标
            if interface_specs and code_files:
                print(f"   🔍 提取 mock 依赖...")
                for spec in interface_specs:
                    symbol_name = spec.get("symbol_name", "")
                    module_path = spec.get("module", "")
                    if module_path:
                        real_mocks = self.e2e_service.extract_mock_targets(
                            symbol_name, module_path, code_files
                        )
                        if real_mocks:
                            spec["mock_dependencies"] = [m.to_dict() for m in real_mocks]

            test_result = await tester_agent.generate_tests(
                design_output=design_output,
                code_output=code_output_dict,
                pipeline_id=PIPELINE_ID
            )

            if not test_result.get("success"):
                raise RuntimeError(f"TesterAgent 失败: {test_result.get('error')}")

            test_files = extract_test_files(test_result.get("output", {}))
            print(f"   TesterAgent 生成 {len(test_files)} 个测试文件")

            # 写入生成的测试文件到沙箱
            for test_file in test_files:
                file_path = test_file.get("file_path", "")
                content = test_file.get("content", "")
                if file_path and content:
                    await file_service.write_file(file_path, content)
                    print(f"   已生成测试文件: {file_path} ({len(content)} 字符)")

            add_agent_tokens(test_result, self)

            # ========== Step 5: 语法验证 ==========
            print(f"\n   🔍 验证代码语法...")
            syntax_errors = await self.e2e_service.validate_code_syntax(code_files, file_service)

            if syntax_errors:
                print(f"   ❌ 发现 {len(syntax_errors)} 个语法错误，启动修复...")
                fixed_files = await run_syntax_fix_loop(
                    syntax_errors=[err.to_dict() for err in syntax_errors],
                    files_to_check=[(err.file, "") for err in syntax_errors],
                    file_service=file_service,
                    design_output=build_design_output_with_pipeline(design_output, PIPELINE_ID),
                    max_retries=DEFAULT_MAX_RETRIES
                )
                if not fixed_files:
                    raise RuntimeError("语法错误自动修复失败")

            # ========== Step 6: 契约检查 ==========
            print("\n🔍 Step 6: 前置契约检查...")
            missing_syms = await self.e2e_service.verify_contract(
                file_service, code_files, interface_specs
            )
            if missing_syms:
                print(f"   ❌ 契约检查失败，缺失 {len(missing_syms)} 项")
                fixed, still_missing, fix_files = await run_contract_fix_loop(
                    missing_syms=missing_syms,
                    interface_specs=interface_specs,
                    design_output=build_design_output_with_pipeline(design_output, PIPELINE_ID),
                    file_service=file_service,
                    max_retries=DEFAULT_MAX_RETRIES
                )
                if not fixed:
                    raise RuntimeError(f"契约自动修复失败: {still_missing}")
                code_files.extend(fix_files)
            print(f"   ✅ 契约检查通过")

            # ========== Step 7: 测试导入和语法验证 ==========
            print("\n   🔍 验证测试文件...")
            import_errors = await self.e2e_service.validate_test_imports(test_files, file_service)
            if import_errors:
                print(f"   ❌ 发现 {len(import_errors)} 个导入错误")
                fixed = await run_test_import_fix_loop(
                    test_files=test_files,
                    import_errors=import_errors,
                    file_service=file_service,
                    design_output=build_design_output_with_pipeline(design_output, PIPELINE_ID),
                    code_output={"files": code_files}
                )
                if not fixed:
                    raise RuntimeError(f"导入错误无法修复: {import_errors}")

            test_syntax_errors = await self.e2e_service.validate_code_syntax(
                [{"file_path": tf.get("file_path", ""), "change_type": "add", "content": tf.get("content", "")}
                 for tf in test_files],
                file_service
            )
            if test_syntax_errors:
                print(f"   ❌ 发现 {len(test_syntax_errors)} 个测试语法错误")
                fixed_test_files = await run_test_syntax_fix_loop(
                    test_files=test_files,
                    syntax_errors=[err.to_dict() for err in test_syntax_errors],
                    file_service=file_service,
                    design_output=build_design_output_with_pipeline(design_output, PIPELINE_ID),
                    code_output={"files": code_files}
                )
                if not fixed_test_files:
                    raise RuntimeError("测试语法错误无法修复")
                test_files = fixed_test_files

            # ========== Step 8: 运行测试 ==========
            print("\n🐳 Step 8: 运行测试...")

            # 预测试
            print("\n   [Step 8.1] 预测试...")
            preliminary_result = await self.e2e_service.run_preliminary_test(
                pipeline_id=PIPELINE_ID,
                test_files=test_files,
                file_service=file_service
            )

            if not preliminary_result.get("success"):
                print("   ❌ 预测试失败，启动 Repair 修复...")

                # 获取完整的日志信息
                logs = preliminary_result.get("logs", "")

                # 从日志中提取失败测试列表
                import re
                failed_tests = re.findall(r'FAILED\s+(\S+)', logs)

                print(f"\n   [预测试失败详情]")

                # 使用统一的提取方法显示错误
                error_content = extract_pytest_failures(logs, max_chars=5000)
                print(f"\n   [预测试错误日志]:")
                print(f"   {error_content}")
                if len(logs) > 5000:
                    print(f"   ... (日志共 {len(logs)} 字符，显示关键部分)")

                all_files = merge_files_content(code_files, test_files)
                fix_success, _ = await self._fix_with_repairer(
                    logs=logs,
                    failed_tests=failed_tests,
                    file_service=file_service,
                    all_generated_files=all_files
                )
                if not fix_success:
                    return E2EContractResult(
                        success=False,
                        code_generated=True,
                        tests_generated=True,
                        tests_passed=False,
                        duration_seconds=time.time() - start
                    )

            # 分层测试
            print("\n   [Step 8.2] 分层测试...")
            all_generated_files = merge_files_content(code_files, test_files)

            layered_result = await self.e2e_service.run_layered_tests(
                pipeline_id=PIPELINE_ID,
                generated_files=all_generated_files,
                file_service=file_service
            )

            print(f"\n   分层测试结果: {'✅ 通过' if layered_result.all_passed else '❌ 失败'}")

            # Auto-Fix 循环
            if not layered_result.all_passed:
                layered_result = await self._run_auto_fix_loop(
                    layered_result, all_generated_files, file_service, design_output, code_files, test_files
                )

            duration = time.time() - start
            success = layered_result.all_passed if layered_result else False
            print(f"\n⏱️  总耗时 {duration:.1f}s")
            print("=" * 70)
            print(f"结果: {'✅ 成功' if success else '❌ 失败'}")
            print("=" * 70)

            return E2EContractResult(
                success=success,
                code_generated=len(code_files) > 0,
                tests_generated=True,
                tests_passed=success,
                layered_result=layered_result,
                duration_seconds=duration
            )

        finally:
            print("🧹 清理 Sandbox...")
            await cleanup_sandbox_orchestrator(PIPELINE_ID)

    async def _fix_with_repairer(
        self,
        logs: str,
        failed_tests: List[str],
        file_service: SandboxFileService,
        all_generated_files: List[Dict],
        missing_symbols: List[str] = None
    ) -> tuple[bool, Dict]:
        """使用 RepairerAgentWithTools 修复"""
        print(f"   🔧 RepairerAgentWithTools: 修复代码逻辑错误（支持多轮对话）")

        if missing_symbols is None:
            missing_symbols = []

        # 构建错误列表
        errors_list = []
        if missing_symbols:
            # 从生成的文件中推断目标文件路径
            target_file = ""
            for f in all_generated_files:
                fp = f.get("file_path", "")
                if "/api/" in fp or "\\api\\" in fp:
                    target_file = fp
                    break
            if not target_file:
                for f in all_generated_files:
                    fp = f.get("file_path", "")
                    if "/service/" in fp or "\\service\\" in fp:
                        target_file = fp
                        break
            if not target_file and all_generated_files:
                target_file = all_generated_files[0].get("file_path", "")

            if not target_file:
                raise ValueError(
                    "无法推断目标文件路径：all_generated_files 为空或没有有效的文件路径"
                )

            errors_list.append({
                "file_path": target_file,
                "line": 1,
                "severity": "critical",
                "summary": f"缺少必需的实现: {', '.join(missing_symbols)}",
                "detail": f"测试需要这些符号，但代码中未定义: {missing_symbols}",
                "fix_hint": f"请在 {target_file} 中实现以下函数: {', '.join(missing_symbols)}"
            })

        # 构建修复工单
        generated_file_paths = extract_file_paths(all_generated_files)
        fix_order = build_fix_order(
            failed_tests=failed_tests,
            logs=logs,
            generated_file_paths=generated_file_paths,
            errors_list=errors_list
        )

        # 收集所有相关文件的完整内容
        target_files = await collect_target_files_async(
            all_generated_files=all_generated_files,
            file_service=file_service,
            errors_list=errors_list
        )

        if not target_files:
            print(f"   ❌ 没有收集到任何文件内容，无法调用 RepairerAgent")
            return False, {"success": False, "error": "没有文件内容"}

        print(f"   📦 共传入 {len(target_files)} 个文件的完整内容给 RepairerAgentWithTools")

        repairer = RepairerAgentWithTools()
        repair_result = await repairer.execute_with_tools(
            pipeline_id=PIPELINE_ID,
            stage_name="REPAIR",
            fix_order=fix_order,
            target_files=target_files,
            file_service=file_service,
            max_rounds=3
        )

        print_fix_result(repair_result, repair_result.get("output", {}))

        return repair_result.get("success", False), repair_result

    async def _run_auto_fix_loop(
        self,
        layered_result: LayeredTestResult,
        all_generated_files: List[Dict],
        file_service: SandboxFileService,
        design_output: Dict,
        code_files: List[Dict],
        test_files: List[Dict]
    ) -> LayeredTestResult:
        """
        运行自动修复循环（使用 FixLoopState 状态管理）
        """
        print("\n🔧 启动 Auto-Fix（智能错误路由）...")

        # 初始化修复循环状态
        state = FixLoopState(
            code_files=code_files,
            test_files=test_files,
            max_retries=3
        )

        while state.attempt < state.max_retries and not layered_result.all_passed:
            state.attempt += 1
            print(f"\n   🔄 第 {state.attempt}/{state.max_retries} 次修复")

            # 提取错误信息
            logs = ""
            failed_tests = []
            for layer in layered_result.layers:
                if not layer.passed and layer.logs:
                    logs = layer.logs
                    failed_tests = layer.failed_tests or []
                    break

            # 分析错误类型
            error_analysis = self.e2e_service.analyze_errors(logs, failed_tests)
            fix_type = determine_fix_type(error_analysis)

            print(f"   🎯 检测到错误类型: {fix_type}")

            # 构建增强的设计输出（包含修复历史）
            enhanced_design_output = build_enhanced_design_output(
                design_output=design_output,
                fix_history=state.fix_history,
                current_error=logs[:500] if logs else ""
            )
            enhanced_design_output["pipeline_id"] = PIPELINE_ID

            fix_success = False
            fix_message = ""

            # 根据错误类型执行修复
            if fix_type in ["syntax", "import"]:
                # 使用统一的修复执行函数
                result = await execute_fix_by_type(
                    fix_type=fix_type,
                    state=state,
                    file_service=file_service,
                    design_output=enhanced_design_output,
                    e2e_service=self.e2e_service,
                    logs=logs,
                    failed_tests=failed_tests
                )
                fix_success = result.success
                fix_message = result.message

                # 更新文件列表（如果修复返回了新的文件）
                if result.new_code_files:
                    state.update_code_files(result.new_code_files)
                if result.new_test_files:
                    state.update_test_files(result.new_test_files)

            elif fix_type == "type":
                # 类型错误特殊处理
                type_errors = error_analysis.get("type_errors", [])
                fix_success = await self._fix_test_type_errors(
                    type_errors=type_errors,
                    test_files=state.test_files,
                    file_service=file_service,
                    design_output=enhanced_design_output,
                    code_files=state.code_files
                )
                fix_message = "类型错误修复"

            else:
                # Repair 修复
                print(f"   🎯 路由到 RepairerAgent")
                missing = self.e2e_service.extract_missing_symbols(logs)
                fix_success, _ = await self._fix_with_repairer(
                    logs=logs,
                    failed_tests=failed_tests,
                    file_service=file_service,
                    all_generated_files=state.all_generated_files,
                    missing_symbols=missing
                )
                fix_message = "RepairerAgent 修复"

            # 记录修复历史
            state.record_fix(
                fix_type=fix_type,
                success=fix_success,
                details={"message": fix_message, "failed_tests_count": len(failed_tests)}
            )

            if not fix_success:
                print(f"   ❌ 本轮修复失败: {fix_message}")
                break

            print(f"   ✅ 本轮修复成功: {fix_message}")

            # 重新运行分层测试（使用最新的文件列表）
            print(f"\n   🔄 重新运行分层测试...")
            layered_result = await self.e2e_service.run_layered_tests(
                pipeline_id=PIPELINE_ID,
                generated_files=state.all_generated_files,
                file_service=file_service
            )

            print(f"   📊 修复后测试结果: {'✅ 通过' if layered_result.all_passed else '❌ 仍有失败'}")

        # 打印修复历史摘要
        if state.fix_history:
            print(f"\n   📋 修复历史摘要:")
            for record in state.fix_history:
                status = "✅" if record["success"] else "❌"
                print(f"      {status} 第 {record['attempt']} 轮 ({record['type']}): {record['details'].get('message', '')}")

        if state.attempt >= state.max_retries and not layered_result.all_passed:
            print(f"\n   🚨 已达到最大重试次数 ({state.max_retries})")

        return layered_result

    async def _fix_test_type_errors(
        self,
        type_errors: List,
        test_files: List[Dict],
        file_service: SandboxFileService,
        design_output: Dict,
        code_files: List[Dict]
    ) -> bool:
        """修复测试文件中的类型错误"""
        print(f"   🔧 TesterAgent: 修复测试类型错误")

        fix_result = await tester_agent.generate_tests(
            design_output={
                **design_output,
                "fix_mode": True,
                "fix_instruction": build_type_error_fix_instruction(type_errors),
                "affected_files": [tf.get("file_path", "") for tf in test_files]
            },
            code_output={"files": code_files},
            pipeline_id=PIPELINE_ID
        )

        if fix_result.get("success"):
            retry_files = fix_result.get("output", {}).get("test_files", [])
            for tf in retry_files:
                fp = tf.get("file_path", "")
                content = tf.get("content", "")
                if content:
                    await file_service.write_file(fp, content)
            return True
        return False


async def main():
    tester = ContractE2ETester()
    result = await tester.run()
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
