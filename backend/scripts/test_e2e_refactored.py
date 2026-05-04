"""
契约增强端到端测试（使用统一服务重构版）

使用 CodeGenerationService、RepairService 等统一服务
与 Pipeline 保持一致，消除重复实现
"""

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.architect import architect_agent
from app.agents.designer import designer_agent
from app.agents.tester import tester_agent
from app.service.agent_coordinator_service import agent_coordinator_service
from app.service.code_generation_service import code_generation_service
from app.service.e2e_test_service import e2e_test_service
from app.service.repair_service import repair_service
from app.service.sandbox_orchestrator import get_sandbox_orchestrator, cleanup_sandbox_orchestrator
from app.utils.agent_debug_utils import get_agent_debugger
from app.utils.agent_output_utils import get_agent_output_dict
from app.utils.agent_instruction_utils import build_designer_alignment_fix_instruction, build_retry_fix_instruction


PIPELINE_ID = 99999  # E2E 测试专用 Pipeline ID

FEATURE_REQUEST = """
实现一个简单的时间戳服务,返回当前的时间戳
"""


@dataclass
class E2EResult:
    """E2E 测试结果"""
    success: bool
    code_generated: bool
    tests_generated: bool
    tests_passed: bool
    duration_seconds: float
    error_message: Optional[str] = None


class E2ETestRunner:
    """E2E 测试运行器（使用统一服务）"""

    def __init__(self):
        self.backend_dir = Path(__file__).parent.parent
        self.debugger = get_agent_debugger()
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def check_api_key(self) -> bool:
        """检查 API Key"""
        from app.core.config import settings
        api_key = settings.OPENAI_API_KEY or settings.ANTHROPIC_API_KEY
        if not api_key:
            print("❌ 错误: 未设置 OPENAI_API_KEY 或 ANTHROPIC_API_KEY")
            return False
        return True

    def check_docker(self) -> bool:
        """检查 Docker 是否可用"""
        import subprocess
        try:
            result = subprocess.run(
                ["docker", "ps"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            print("❌ 错误: Docker 不可用")
            return False

    def _add_tokens(self, result: Dict):
        """累加 Token 数"""
        self.total_input_tokens += result.get("input_tokens", 0) or 0
        self.total_output_tokens += result.get("output_tokens", 0) or 0

    async def run(self) -> E2EResult:
        """运行 E2E 测试"""
        start = time.time()
        print("=" * 70)
        print("🧪 E2E 测试（使用统一服务重构版）")
        print("=" * 70)
        print(f"需求: {FEATURE_REQUEST[:100]}...")
        print()

        if not self.check_api_key():
            return E2EResult(False, False, False, False, 0, "API Key 缺失")
        if not self.check_docker():
            return E2EResult(False, False, False, False, 0, "Docker 不可用")

        # 启动 Sandbox
        print("🐳 启动 Docker Sandbox...")
        sandbox_orch = get_sandbox_orchestrator(PIPELINE_ID)
        project_root = str(self.backend_dir.parent)
        sandbox_init = await sandbox_orch.initialize(project_root)
        if not sandbox_init["success"]:
            return E2EResult(False, False, False, False, 0, "Sandbox 启动失败")
        file_service = sandbox_orch.get_file_service()
        print("✅ Sandbox 就绪")

        try:
            # ========== Step 1: 需求分析 ==========
            print("\n📋 Step 1: ArchitectAgent 分析需求...")
            arch_context = await agent_coordinator_service.build_architect_context(
                requirement=FEATURE_REQUEST,
                file_tree={},
                element_context=None,
                pipeline_id=PIPELINE_ID
            )
            arch_result = await architect_agent.analyze(
                requirement=arch_context["requirement"],
                file_tree=arch_context["file_tree"],
                element_context=arch_context["element_context"],
                pipeline_id=PIPELINE_ID,
                project_path=str(self.backend_dir)
            )
            self._save_agent_debug("ArchitectAgent", "analyze", arch_context, arch_result)

            if not arch_result.get("success"):
                raise RuntimeError(f"ArchitectAgent 失败: {arch_result.get('error')}")
            arch_output = arch_result["output"]
            print(f"   ✅ 验收标准: {arch_output.get('acceptance_criteria', [])}")
            self._add_tokens(arch_result)

            # ========== Step 2: 方案设计 ==========
            print("\n🎨 Step 2: DesignerAgent 技术设计...")

            # 【修复点 1】直接从 arch_result 提取，不要依赖 agent_coordinator_service
            injected_files = arch_result.get("injected_files", {})

            design_context = await agent_coordinator_service.build_designer_context(
                requirement=FEATURE_REQUEST,
                arch_output=arch_output,
                file_tree={},
                pipeline_id=PIPELINE_ID
            )
            design_result = await designer_agent.design(
                architect_output=design_context["arch_output"],
                file_tree=design_context["file_tree"],
                related_code_context="",
                full_files_context=injected_files,  # <--- 修正这里：传入真实的 injected_files
                pipeline_id=PIPELINE_ID
            )
            self._save_agent_debug("DesignerAgent", "design", design_context, design_result)

            # 【新增】DesignerAgent 契约对齐失败重试逻辑
            max_design_retries = 3
            design_retry_count = 0
            while not design_result.get("success") and "契约对齐校验失败" in design_result.get("error", "") and design_retry_count < max_design_retries:
                design_retry_count += 1
                print(f"   🔄 DesignerAgent 契约对齐失败，第 {design_retry_count}/{max_design_retries} 次重试...")

                # 从错误信息中提取缺失的验收标准
                error_msg = design_result.get("error", "")
                import re
                missing_match = re.search(r"缺失 (\d+) 条验收标准映射: (.+)$", error_msg)
                if missing_match:
                    missing_criteria_str = missing_match.group(2)
                    # 解析列表形式的字符串
                    try:
                        missing_criteria = eval(missing_criteria_str)
                        if not isinstance(missing_criteria, list):
                            missing_criteria = [missing_criteria_str]
                    except:
                        missing_criteria = [missing_criteria_str]
                else:
                    missing_criteria = []

                if not missing_criteria:
                    print(f"   ⚠️ 无法解析缺失的验收标准，跳过重试")
                    break

                # 构建修复指令
                fix_instruction = build_designer_alignment_fix_instruction(missing_criteria)
                retry_instruction, _ = build_retry_fix_instruction(
                    design_retry_count - 1, max_design_retries, fix_instruction
                )

                # 构建重试输入
                retry_design_output = {
                    **arch_output,
                    "fix_mode": True,
                    "fix_instruction": retry_instruction,
                    "missing_criteria": missing_criteria,
                }

                retry_input = {
                    "architect_output": retry_design_output,
                    "file_tree": design_context["file_tree"],
                    "related_code_context": "",
                    "full_files_context": injected_files,
                    "pipeline_id": PIPELINE_ID
                }

                design_result = await designer_agent.design(**retry_input)
                self._save_agent_debug(f"DesignerAgent", f"design_retry_{design_retry_count}", retry_input, design_result)
                self._add_tokens(design_result)

                if design_result.get("success"):
                    print(f"   ✅ DesignerAgent 重试成功")
                    break

            if not design_result.get("success"):
                raise RuntimeError(f"DesignerAgent 失败: {design_result.get('error')}")
            design_output = design_result["output"]
            interface_specs = design_output.get("interface_specs", [])
            print(f"   ✅ 接口契约 ({len(interface_specs)} 项)")
            self._add_tokens(design_result)

            # ========== Step 3: 代码生成（使用统一服务）==========
            print("\n📝 Step 3: 使用 CodeGenerationService 生成代码...")
            # 【修复点 2】使用刚才提取的 injected_files，而不是从 arch_output 获取
            # injected_files = arch_output.get("injected_files", {})  <-- 删掉这一行

            code_result = await code_generation_service.generate_and_fix(
                design_output=design_output,
                injected_files=injected_files,
                pipeline_id=PIPELINE_ID,
                workspace_path=str(self.backend_dir),
                file_service=file_service,
                debugger=self.debugger,
                enable_linting=True,
                enable_contract_check=True,
            )

            if not code_result.get("success"):
                raise RuntimeError(f"代码生成失败: {code_result.get('error')}")

            code_files = code_result.get("files", [])
            fix_history = code_result.get("fix_history", [])
            print(f"   ✅ 生成 {len(code_files)} 个文件")
            if fix_history:
                print(f"   🔄 经历 {len(fix_history)} 轮自动修复")
            self.total_input_tokens += code_result.get("input_tokens", 0)
            self.total_output_tokens += code_result.get("output_tokens", 0)

            # 注意：CodeGenerationService 已经在内部完成写入、Linting、语法检查、契约检查

            # ========== Step 4: 测试生成（带重试逻辑，与 Pipeline 保持一致）==========
            print("\n🧪 Step 4: TesterAgent 生成测试...")

            # 【修复点 3】保留 CoderAgent 的原始 summary 等字段，而不是只留 files
            code_output_dict = get_agent_output_dict(code_result.get("output", {}))

            # 【修复点 4】补回提取 mock 目标的逻辑
            if interface_specs and code_files:
                print(f"   🔍 提取 mock 依赖...")
                for spec in interface_specs:
                    symbol_name = spec.get("symbol_name", "")
                    module_path = spec.get("module", "")
                    if module_path:
                        # 【修正】使用全局单例 e2e_test_service 而不是 self.e2e_service
                        real_mocks = e2e_test_service.extract_mock_targets(
                            symbol_name, module_path, code_files
                        )
                        if real_mocks:
                            spec["mock_dependencies"] = [m.to_dict() for m in real_mocks]

            # 【新增】测试生成重试逻辑（与 TestingHandler 保持一致）
            MAX_TEST_GENERATION_RETRIES = 2
            test_gen_retry_count = 0
            last_test_error_context = None
            test_result = None

            while test_gen_retry_count <= MAX_TEST_GENERATION_RETRIES:
                # 构建测试生成参数
                test_context = await agent_coordinator_service.build_tester_context(
                    design_output=design_output,
                    code_output=code_output_dict,
                    target_files={},
                    pipeline_id=PIPELINE_ID
                )

                # 如果有错误上下文，添加到 design_output 中
                if last_test_error_context:
                    print(f"   🔄 第 {test_gen_retry_count}/{MAX_TEST_GENERATION_RETRIES} 次重试生成测试...")
                    enhanced_design = dict(test_context["design_output"])
                    enhanced_design["test_fix_context"] = last_test_error_context
                    test_context["design_output"] = enhanced_design

                test_result = await tester_agent.generate_tests(
                    design_output=test_context["design_output"],
                    code_output=test_context["code_output"],
                    target_files=test_context["target_files"],
                    pipeline_id=PIPELINE_ID
                )
                self._save_agent_debug(
                    "TesterAgent",
                    f"generate_tests{'_retry_' + str(test_gen_retry_count) if test_gen_retry_count > 0 else ''}",
                    test_context,
                    test_result
                )
                self._add_tokens(test_result)

                if test_result.get("success"):
                    break

                # 生成失败，准备重试
                test_gen_retry_count += 1
                if test_gen_retry_count > MAX_TEST_GENERATION_RETRIES:
                    raise RuntimeError(f"TesterAgent 失败: {test_result.get('error')}")

                # 构建错误上下文用于下次重试
                last_test_error_context = f"上次生成失败: {test_result.get('error', 'Unknown error')}"
                print(f"   ⚠️ 测试生成失败，准备重试 ({test_gen_retry_count}/{MAX_TEST_GENERATION_RETRIES})...")

            if not test_result or not test_result.get("success"):
                raise RuntimeError(f"TesterAgent 失败: 达到最大重试次数")

            test_output = test_result.get("output", {})
            test_files = test_output.get("test_files", [])
            print(f"   ✅ 生成 {len(test_files)} 个测试文件" + (f" (重试 {test_gen_retry_count} 次)" if test_gen_retry_count > 0 else ""))

            # 写入测试文件到沙箱
            for test_file in test_files:
                file_path = test_file.get("file_path", "")
                content = test_file.get("content", "")
                if file_path and content:
                    await file_service.write_file(file_path, content)

            # ========== Step 5: 运行测试与修复（与 TestingHandler 保持一致）==========
            print("\n🐳 Step 5: 运行测试...")

            # 【新增】Step 5.1: 预测试（与 Pipeline 保持一致）
            print("\n   [Step 5.1] 预测试...")
            from app.utils.test_execution import run_preliminary_test, analyze_test_failure
            preliminary_result = await run_preliminary_test(
                pipeline_id=PIPELINE_ID,
                test_files=test_files,
                file_service=file_service
            )

            if not preliminary_result.get("success"):
                print("   ❌ 预测试失败，分析失败原因...")
                logs = preliminary_result.get("logs", "")
                failure_analysis = analyze_test_failure(logs)

                if failure_analysis.get("is_test_file_error"):
                    print(f"   ⚠️ 检测到测试文件错误: {failure_analysis.get('error_detail', 'Unknown')}")
                    # 预测试失败，但继续执行分层测试，让 RepairService 处理
                else:
                    print(f"   ⚠️ 预测试失败，可能是被测代码问题")

            # Step 5.2: 分层测试
            print("\n   [Step 5.2] 分层测试...")
            all_files = code_files + test_files

            layered_result = await e2e_test_service.run_layered_tests(
                pipeline_id=PIPELINE_ID,
                generated_files=all_files,
                file_service=file_service
            )

            print(f"\n   分层测试结果: {'✅ 通过' if layered_result.all_passed else '❌ 失败'}")

            # 如果分层测试失败，只调用一次 repair_service.start_repair（与 TestingHandler 一致）
            if not layered_result.all_passed:
                print("\n   🔧 启动 RepairService 修复...")

                # 收集测试日志
                test_logs = "\n".join([layer.logs for layer in layered_result.layers])

                repair_result = await repair_service.start_repair(
                    pipeline_id=PIPELINE_ID,
                    code_files=code_files,
                    test_files=test_files,
                    test_logs=test_logs,
                    design_output=design_output,
                    file_service=file_service,
                    debugger=self.debugger,
                )

                if repair_result.get("test_run_success"):
                    print("   ✅ 修复成功，测试通过")
                    layered_result.all_passed = True
                else:
                    print("   ❌ 修复失败")

            # ========== 完成 ==========
            duration = time.time() - start
            success = layered_result.all_passed

            print(f"\n⏱️  总耗时 {duration:.1f}s")
            print(f"📊 Token 使用: {self.total_input_tokens} in / {self.total_output_tokens} out")
            print("=" * 70)
            print(f"结果: {'✅ 成功' if success else '❌ 失败'}")
            print("=" * 70)

            # 保存调试摘要
            summary = self.debugger.log_summary()
            print(f"\n📊 Agent 调用统计:")
            print(f"   总调用次数: {summary.get('total_calls', 0)}")
            print(f"   成功次数: {summary.get('successful_calls', 0)}")
            print(f"   失败次数: {summary.get('failed_calls', 0)}")
            print(f"   成功率: {summary.get('success_rate', 0) * 100:.1f}%")

            return E2EResult(
                success=success,
                code_generated=len(code_files) > 0,
                tests_generated=len(test_files) > 0,
                tests_passed=success,
                duration_seconds=duration
            )

        finally:
            print("\n🧹 清理 Sandbox...")
            await cleanup_sandbox_orchestrator(PIPELINE_ID)

    def _save_agent_debug(
        self,
        agent_name: str,
        stage: str,
        input_data: Dict,
        output_data: Dict
    ):
        """保存 Agent 调试信息"""
        import importlib

        # 动态获取 system_prompt
        system_prompt = None
        try:
            if agent_name == "ArchitectAgent":
                from app.agents.architect import architect_agent
                system_prompt = architect_agent.system_prompt
            elif agent_name == "DesignerAgent":
                from app.agents.designer import designer_agent
                system_prompt = designer_agent.system_prompt
            elif agent_name == "TesterAgent":
                from app.agents.tester import tester_agent
                system_prompt = tester_agent.system_prompt
        except Exception:
            pass

        self.debugger.save_agent_io(
            agent_name=agent_name,
            stage=stage,
            input_data=input_data,
            output_data=output_data,
            metadata={
                "input_tokens": output_data.get("input_tokens", 0),
                "output_tokens": output_data.get("output_tokens", 0),
            },
            success=output_data.get("success", False),
            error=output_data.get("error"),
            tool_calls=output_data.get("tool_results", []),
            system_prompt=system_prompt
        )


async def main():
    """主函数"""
    runner = E2ETestRunner()
    result = await runner.run()

    print("\n" + "=" * 70)
    print("E2E 测试完成")
    print("=" * 70)
    print(f"成功: {result.success}")
    print(f"代码生成: {result.code_generated}")
    print(f"测试生成: {result.tests_generated}")
    print(f"测试通过: {result.tests_passed}")
    print(f"耗时: {result.duration_seconds:.1f}s")
    if result.error_message:
        print(f"错误: {result.error_message}")

    return 0 if result.success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
