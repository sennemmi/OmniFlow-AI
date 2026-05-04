#!/usr/bin/env python3
"""
端到端集成测试（契约增强版 V2）- 简化版

移除了不成熟的 Architect/Editor 分离模式，只保留稳定的传统模式。

保留功能：
- code_apply 工具: 精确 search/replace 执行器，失败时返回结构化错误
- Linting-修复自动化: 代码生成后自动运行 ruff 检查并修复
- 交互式编辑器工具集: read_file, grep, code_apply, func_replace 等
- 微提交 (Micro-commits): 每次成功工具调用后自动 git commit

使用方式:
  # 运行测试（传统模式）
  python scripts/test_e2e_with_contract_v2.py
  
  # 禁用 Linting 检查
  set LINTING_ENABLED=false
  python scripts/test_e2e_with_contract_v2.py

警告: 此脚本会调用真实 LLM 并启动 Docker，请确保配置正确。
"""

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ========================== 测试配置 ==========================
PIPELINE_ID = 99999
FEATURE_REQUEST = "实现一个简单的时间戳服务,返回当前的时间戳"

# 默认重试次数
DEFAULT_MAX_RETRIES = 3

# ========================== 代码生成模式配置 ==========================
# 【已简化】只保留传统模式，移除了 Architect/Editor 分离模式
# 传统模式：CoderAgent 直接生成完整代码 JSON
CODE_GEN_MODE = "legacy"

# ========================== 调试配置 ==========================
# 设置为 True 以启用 Agent 输入输出调试
# 调试输出将保存到 agent_debug_output/<session_id>/ 目录
AGENT_DEBUG_ENABLED = True

# 调试输出目录（相对于项目根目录）
AGENT_DEBUG_OUTPUT_DIR = "./agent_debug_output"

# ========================== Linting 配置 ==========================
# 启用生成后自动 Lint 检查
LINTING_ENABLED = os.environ.get("LINTING_ENABLED", "true").lower() == "true"
LINTING_MAX_RETRIES = int(os.environ.get("LINTING_MAX_RETRIES", "3"))


# ========================== 辅助函数 ==========================
def clean_path(p: str) -> str:
    """路径归一化：统一使用正斜杠，移除 backend/ 前缀"""
    if not p:
        return p
    return p.replace("\\", "/").replace("backend/", "").lstrip("/")


@pytest.fixture(autouse=True)
async def cleanup_old_sandboxes():
    """测试前清理可能残留的 Docker 容器"""
    print("🧹 清理旧的 Sandbox 容器...")
    try:
        # 强制停止可能残留的测试容器
        subprocess.run(
            "docker rm -f $(docker ps -aq --filter name=omniflow-sandbox)",
            shell=True,
            capture_output=True,
            timeout=30
        )
    except Exception as e:
        print(f"   ⚠️ 清理容器时出错（非关键）: {e}")
    yield


async def wait_for_stage_completion(
    client,
    pipeline_id: int,
    target_stage: str,
    timeout: int = 300
) -> Dict:
    """
    指数退避轮询等待阶段完成

    Args:
        client: HTTP 客户端
        pipeline_id: Pipeline ID
        target_stage: 目标阶段名称
        timeout: 超时时间（秒）

    Returns:
        Dict: 阶段状态数据

    Raises:
        TimeoutError: 超时未到达目标阶段
        Exception: Pipeline 失败
    """
    start_time = time.time()
    interval = 5  # 初始轮询间隔 5 秒
    max_interval = 30  # 最大轮询间隔 30 秒

    while time.time() - start_time < timeout:
        # 这里简化处理，实际应该调用 API 获取状态
        # 在实际 E2E 测试中，可以通过 e2e_service 获取状态
        elapsed = int(time.time() - start_time)
        print(f"   ⏳ 等待 {target_stage} 阶段完成... ({elapsed}s)")

        # 指数退避增加间隔
        await asyncio.sleep(interval)
        interval = min(interval * 1.5, max_interval)

    raise TimeoutError(f"Stage {target_stage} did not complete in {timeout}s")


from app.agents.architect import architect_agent
from app.agents.coder import coder_agent, CoderAgent
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
from app.utils.agent_debug_utils import AgentDebugger
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
    extract_critical_files,
    extract_pytest_failures,
    print_fix_result,
)
from app.utils.file_utils import extract_file_paths


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
    linting_passed: bool = True  # Linting 检查是否通过


class ContractE2ETester:
    def __init__(self, debug_enabled: bool = AGENT_DEBUG_ENABLED):
        self.backend_dir = Path(__file__).parent.parent
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.e2e_service = E2ETestService()
        
        # 初始化调试器
        self.debugger = AgentDebugger(
            enabled=debug_enabled,
            output_dir=AGENT_DEBUG_OUTPUT_DIR
        )
        if debug_enabled:
            print(f"🔍 Agent 调试已启用，输出目录: {self.debugger.output_dir / self.debugger.session_id}")
        
        # Linting 配置
        self.linting_enabled = LINTING_ENABLED
        if self.linting_enabled:
            print(f"🔍 Linting 检查已启用 (最大重试: {LINTING_MAX_RETRIES})")

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

            retry_input = {
                "design_output": retry_design_output,
                "pipeline_id": PIPELINE_ID,
                "injected_files": injected_files
            }
            retry_result = await coder_agent.generate_code(**retry_input)

            # 保存调试信息
            self.debugger.save_agent_io(
                agent_name="CoderAgent",
                stage="key_mismatch_retry",
                input_data=retry_input,
                output_data=retry_result,
                metadata={"attempt": retry_attempt + 1, "max_retries": max_retries, "key_mismatches": key_mismatches},
                success=retry_result.get("success", False),
                error=retry_result.get("error"),
                tool_calls=retry_result.get("tool_results", []),
                system_prompt=coder_agent.system_prompt
            )

            if retry_result.get("success"):
                print(f"   ✅ 第 {retry_attempt + 1} 次重试成功")
                return retry_result
            else:
                print(f"   ❌ 第 {retry_attempt + 1} 次重试失败: {retry_result.get('error')}")

        return None

    async def _handle_missing_symbols_retry(
        self,
        error_message: str,
        design_output: Dict,
        injected_files: Dict[str, str]
    ) -> Optional[Dict]:
        """处理符号缺失的重试逻辑"""
        import re
        from app.utils.agent_instruction_utils import build_contract_fix_instruction
        
        max_retries = 3
        
        # 从错误消息中提取缺失的符号信息
        # 错误格式: "生成的代码缺少契约要求的符号: ['symbol_name in module_path', ...]"
        missing_symbols = re.findall(r"'([^']+)'", error_message)
        
        # 构建 interface_specs 中缺失符号的详细信息
        interface_specs = design_output.get("interface_specs", [])
        missing_specs = []
        for spec in interface_specs:
            symbol_name = spec.get("symbol_name", "")
            module = spec.get("module", "")
            key = f"{symbol_name} in {module}"
            if any(key in m for m in missing_symbols):
                missing_specs.append(spec)
        
        fix_instruction = build_contract_fix_instruction(missing_specs)
        
        for retry_attempt in range(max_retries):
            print(f"\n   🔧 符号缺失，第 {retry_attempt + 1}/{max_retries} 次重试...")
            print(f"   缺失符号: {[s.get('symbol_name') for s in missing_specs]}")
            
            instruction, force_full_file = build_retry_fix_instruction(
                retry_attempt, max_retries, fix_instruction
            )
            
            retry_design_output = {
                **design_output,
                "fix_mode": True,
                "force_full_file": True,  # 符号缺失时强制完整文件
                "fix_instruction": instruction,
                "affected_files": list(set(
                    [s.get("module", "") for s in missing_specs if s.get("module")]
                    + list(injected_files.keys())
                ))
            }
            
            print(f"   📝 调用 CoderAgent 重试 (force_full_file=True)...")
            
            retry_input = {
                "design_output": retry_design_output,
                "pipeline_id": PIPELINE_ID,
                "injected_files": injected_files
            }
            retry_result = await coder_agent.generate_code(**retry_input)
            
            # 保存调试信息
            self.debugger.save_agent_io(
                agent_name="CoderAgent",
                stage="missing_symbols_retry",
                input_data=retry_input,
                output_data=retry_result,
                metadata={"attempt": retry_attempt + 1, "max_retries": max_retries, "missing_specs": [{"symbol_name": s.get("symbol_name"), "module": s.get("module")} for s in missing_specs]},
                success=retry_result.get("success", False),
                error=retry_result.get("error"),
                tool_calls=retry_result.get("tool_results", []),
                system_prompt=coder_agent.system_prompt
            )
            
            if retry_result.get("success"):
                print(f"   ✅ 第 {retry_attempt + 1} 次重试成功")
                return retry_result
            else:
                print(f"   ❌ 第 {retry_attempt + 1} 次重试失败: {retry_result.get('error')}")
        
        return None

    async def _run_linting_check(
        self,
        code_files: List[Dict],
        file_service: SandboxFileService
    ) -> tuple[bool, List[Dict]]:
        """
        运行 Linting 检查并尝试自动修复
        
        Args:
            code_files: 代码文件列表
            file_service: 文件服务
            
        Returns:
            (是否通过, 修复后的文件列表)
        """
        if not self.linting_enabled:
            return True, code_files
            
        print(f"\n   🔍 运行 Linting 检查...")
        
        # 尝试运行 ruff 检查
        linting_errors = []
        checked_files = set()  # 用于去重，避免重复检查同一文件
        
        for file_obj in code_files:
            file_path = file_obj.get("file_path", "")
            if not file_path.endswith(".py"):
                continue
                
            # 转换为沙箱中的路径（相对于 /workspace/backend）
            # 沙箱中的工作目录是 /workspace，所以路径应该是 backend/xxx
            if file_path.startswith("backend/"):
                sandbox_path = file_path
                normalized_path = file_path
            else:
                sandbox_path = f"backend/{file_path}"
                normalized_path = sandbox_path
            
            # 去重检查：如果已经检查过这个文件，跳过
            if normalized_path in checked_files:
                continue
            checked_files.add(normalized_path)
            
            # 检查文件是否存在于沙箱
            clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
            read_res = await file_service.read_file(clean_path)
            
            if not read_res.exists:
                continue
                
            # 尝试运行 ruff check
            try:
                from app.service.sandbox_manager import sandbox_manager
                
                result = await sandbox_manager.exec(
                    PIPELINE_ID,
                    f"cd /workspace && ruff check {sandbox_path} --output-format=json 2>&1 || true",
                    timeout=30
                )
                
                if result.stdout:
                    import json
                    try:
                        errors = json.loads(result.stdout)
                        if errors:
                            # 过滤掉 "文件不存在" 错误 (E902) 和语法错误无法自动修复的
                            real_errors = [e for e in errors if e.get("code") not in ("E902",)]
                            # 过滤掉 invalid-syntax 错误（这些通常是文件本身的问题，无法通过 ruff fix 修复）
                            real_errors = [e for e in real_errors if "invalid-syntax" not in str(e.get("code", "")).lower()]
                            if real_errors:
                                linting_errors.append({
                                    "file": file_path,
                                    "sandbox_path": sandbox_path,
                                    "errors": real_errors
                                })
                    except json.JSONDecodeError:
                        pass
                        
            except Exception as e:
                logger.warning(f"Linting 检查失败 {file_path}: {e}")
        
        if not linting_errors:
            print(f"   ✅ Linting 检查通过")
            return True, code_files
            
        print(f"   ⚠️ 发现 {len(linting_errors)} 个文件有 Linting 错误")
        
        # 尝试自动修复
        for attempt in range(LINTING_MAX_RETRIES):
            print(f"   🔄 Linting 自动修复尝试 {attempt + 1}/{LINTING_MAX_RETRIES}...")
            
            # 尝试运行 ruff fix
            try:
                from app.service.sandbox_manager import sandbox_manager
                
                # 使用 set 去重，避免重复修复同一文件
                fixed_paths = set()
                for error_info in linting_errors:
                    sandbox_path = error_info.get("sandbox_path", error_info["file"])
                    
                    # 去重：如果已经修复过这个文件，跳过
                    if sandbox_path in fixed_paths:
                        continue
                    fixed_paths.add(sandbox_path)
                    
                    # 运行 ruff fix
                    fix_result = await sandbox_manager.exec(
                        PIPELINE_ID,
                        f"cd /workspace && ruff check {sandbox_path} --fix 2>&1 || true",
                        timeout=30
                    )
                    
                    output = fix_result.stdout[:200] if fix_result.stdout else "无输出"
                    # 过滤掉文件不存在的错误信息和语法错误
                    if "E902" not in output and "invalid-syntax" not in output.lower():
                        print(f"      📝 修复 {sandbox_path}: {output}")
                    
                # 重新检查
                remaining_errors = []
                checked_remaining = set()  # 去重集合
                for error_info in linting_errors:
                    sandbox_path = error_info.get("sandbox_path", error_info["file"])
                    
                    # 去重
                    if sandbox_path in checked_remaining:
                        continue
                    checked_remaining.add(sandbox_path)
                    
                    result = await sandbox_manager.exec(
                        PIPELINE_ID,
                        f"cd /workspace && ruff check {sandbox_path} --output-format=json 2>&1 || true",
                        timeout=30
                    )
                    
                    if result.stdout:
                        try:
                            errors = json.loads(result.stdout)
                            if errors:
                                # 过滤掉 "文件不存在" 错误和语法错误
                                real_errors = [e for e in errors if e.get("code") not in ("E902",)]
                                real_errors = [e for e in real_errors if "invalid-syntax" not in str(e.get("code", "")).lower()]
                                if real_errors:
                                    remaining_errors.append({
                                        "file": error_info["file"],
                                        "sandbox_path": sandbox_path,
                                        "errors": real_errors
                                    })
                        except json.JSONDecodeError:
                            pass
                
                if not remaining_errors:
                    print(f"   ✅ Linting 修复完成")
                    return True, code_files
                    
                linting_errors = remaining_errors
                
            except Exception as e:
                print(f"   ⚠️ Linting 自动修复失败: {e}")
                break
        
        if linting_errors:
            print(f"   ⚠️ Linting 检查后仍有 {len(linting_errors)} 个文件有问题")
            for err in linting_errors:
                print(f"      - {err['file']}: {len(err['errors'])} 个错误")
        
        # 返回 True 允许继续，但记录警告
        return True, code_files

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

            retry_input = {
                "design_output": {
                    "fix_mode": True,
                    "fix_instruction": build_search_block_retry_instruction(
                        file_path, current_content, replace_block
                    ),
                    "affected_files": [file_path]
                },
                "pipeline_id": PIPELINE_ID,
                "injected_files": {file_path: current_content}
            }
            retry_result = await coder_agent.generate_code(**retry_input)

            # 保存调试信息
            self.debugger.save_agent_io(
                agent_name="CoderAgent",
                stage="search_block_retry",
                input_data=retry_input,
                output_data=retry_result,
                metadata={"attempt": retry_attempt + 1, "max_retries": max_retries, "file_path": file_path},
                success=retry_result.get("success", False),
                error=retry_result.get("error"),
                tool_calls=retry_result.get("tool_results", []),
                system_prompt=coder_agent.system_prompt
            )

            if retry_result.get("success"):
                retry_output = retry_result.get("output", {})
                # 【修复】retry_output 是字典，不是 Pydantic 模型
                # CoderAgent 返回的 output 是字典格式 {"files": [...]}
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
            return E2EContractResult(False, False, False, False, error_message="API Key 缺失",
                                     linting_passed=True)
        if not self.check_docker():
            return E2EContractResult(False, False, False, False, error_message="Docker 不可用",
                                     linting_passed=True)

        # Step 0: 启动 Sandbox
        print("🐳 启动 Docker Sandbox...")
        sandbox_orch = get_sandbox_orchestrator(PIPELINE_ID)
        project_root = str(self.backend_dir.parent)
        sandbox_init = await sandbox_orch.initialize(project_root)
        if not sandbox_init["success"]:
            return E2EContractResult(False, False, False, False, error_message="Sandbox 启动失败",
                                     linting_passed=True)
        file_service = sandbox_orch.get_file_service()
        print("✅ Sandbox 就绪")

        try:
            # ========== Step 1: 需求分析 ==========
            print("\n📋 Step 1: ArchitectAgent 分析需求...")
            arch_input = {
                "requirement": FEATURE_REQUEST,
                "file_tree": self.build_file_tree(),
                "pipeline_id": PIPELINE_ID,
                "project_path": str(self.backend_dir)
            }
            arch_result = await architect_agent.analyze(**arch_input)
            
            # 保存 ArchitectAgent 输入输出
            self.debugger.save_agent_io(
                agent_name="ArchitectAgent",
                stage="analyze",
                input_data=arch_input,
                output_data=arch_result,
                metadata={"input_tokens": arch_result.get("input_tokens", 0), 
                          "output_tokens": arch_result.get("output_tokens", 0)},
                success=arch_result.get("success", False),
                error=arch_result.get("error"),
                tool_calls=arch_result.get("tool_results", []),
                system_prompt=architect_agent.system_prompt
            )
            
            if not arch_result["success"]:
                raise RuntimeError(f"ArchitectAgent 失败: {arch_result.get('error')}")
            arch_output = arch_result["output"]
            print(f"   验收标准: {arch_output.get('acceptance_criteria', [])}")
            # 【诊断】打印 required_symbols
            required_symbols = arch_output.get('required_symbols', [])
            print(f"   必需符号: {[s.get('name') for s in required_symbols]}")
            add_agent_tokens(arch_result, self)

            # ========== Step 2: 方案设计 ==========
            print("\n🎨 Step 2: DesignerAgent 技术设计...")
            design_input = {
                "architect_output": arch_output,
                "file_tree": self.build_file_tree(),
                "related_code_context": "",
                "full_files_context": arch_result.get("injected_files", {}),
                "pipeline_id": PIPELINE_ID
            }
            design_result = await designer_agent.design(**design_input)
            
            # 保存 DesignerAgent 输入输出
            self.debugger.save_agent_io(
                agent_name="DesignerAgent",
                stage="design",
                input_data=design_input,
                output_data=design_result,
                metadata={"input_tokens": design_result.get("input_tokens", 0),
                          "output_tokens": design_result.get("output_tokens", 0)},
                success=design_result.get("success", False),
                error=design_result.get("error"),
                tool_calls=design_result.get("tool_results", []),
                system_prompt=designer_agent.system_prompt
            )
            
            if not design_result["success"]:
                raise RuntimeError(f"DesignerAgent 失败: {design_result.get('error')}")
            design_output = design_result["output"]
            interface_specs = design_output.get("interface_specs", [])
            print(f"   接口契约 ({len(interface_specs)} 项)")
            # 【诊断】打印 interface_specs 中的符号
            print(f"   契约符号: {[s.get('symbol_name') for s in interface_specs]}")
            add_agent_tokens(design_result, self)

            # ========== Step 3: 代码生成 ==========
            print("\n📝 Step 3: CoderAgent 生成代码...")
            injected_files = arch_result.get("injected_files", {})
            
            coder_input = {
                "design_output": design_output,
                "pipeline_id": PIPELINE_ID,
                "injected_files": injected_files
            }
            coder_result = await coder_agent.generate_code(**coder_input)

            # 保存 CoderAgent 输入输出
            self.debugger.save_agent_io(
                agent_name="CoderAgent",
                stage="generate_code",
                input_data=coder_input,
                output_data=coder_result,
                metadata={"input_tokens": coder_result.get("input_tokens", 0),
                          "output_tokens": coder_result.get("output_tokens", 0)},
                success=coder_result.get("success", False),
                error=coder_result.get("error"),
                tool_calls=coder_result.get("tool_results", []),
                system_prompt=coder_agent.system_prompt
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
            elif not coder_result.get("success") and "缺少契约要求的符号" in coder_result.get('error', ''):
                # 【新增】处理符号缺失的重试
                print(f"   ⚠️ 符号缺失，启动重试...")
                retry_result = await self._handle_missing_symbols_retry(
                    coder_result.get('error', ''), design_output, injected_files
                )
                if retry_result:
                    coder_result = retry_result
                    # 保存重试结果
                    self.debugger.save_agent_io(
                        agent_name="CoderAgent",
                        stage="generate_code_retry",
                        input_data=coder_input,
                        output_data=retry_result,
                        metadata={"input_tokens": retry_result.get("input_tokens", 0),
                                  "output_tokens": retry_result.get("output_tokens", 0)},
                        success=retry_result.get("success", False),
                        error=retry_result.get("error"),
                        tool_calls=retry_result.get("tool_results", []),
                        system_prompt=coder_agent.system_prompt
                    )
                else:
                    raise RuntimeError("CoderAgent 符号缺失重试后仍然失败")
            elif not coder_result.get("success"):
                raise RuntimeError(f"CoderAgent 失败: {coder_result.get('error')}")

            code_files = await self._apply_coder_result(coder_result, file_service)
            print(f"   CoderAgent 生成 {len(code_files)} 个文件")
            add_agent_tokens(coder_result, self)

            # ========== Step 3.5: Linting 检查和自动修复 ==========
            linting_passed, code_files = await self._run_linting_check(code_files, file_service)
            self.linting_passed = linting_passed

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

            test_input = {
                "design_output": design_output,
                "code_output": code_output_dict,
                "pipeline_id": PIPELINE_ID
            }
            test_result = await tester_agent.generate_tests(**test_input)

            # 保存 TesterAgent 输入输出
            self.debugger.save_agent_io(
                agent_name="TesterAgent",
                stage="generate_tests",
                input_data=test_input,
                output_data=test_result,
                metadata={"input_tokens": test_result.get("input_tokens", 0),
                          "output_tokens": test_result.get("output_tokens", 0)},
                success=test_result.get("success", False),
                error=test_result.get("error"),
                tool_calls=test_result.get("tool_results", []),
                system_prompt=tester_agent.system_prompt
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
            syntax_errors = await self.e2e_service.validate_code_syntax(code_files, file_service, PIPELINE_ID)

            if syntax_errors:
                print(f"   ❌ 发现 {len(syntax_errors)} 个语法错误，启动修复...")

                # 从沙箱读取错误文件的内容
                error_files_with_content = []
                for err in syntax_errors:
                    fp = err.file
                    read_res = await file_service.read_file(fp)
                    if read_res.exists:
                        error_files_with_content.append((fp, read_res.content))
                    else:
                        error_files_with_content.append((fp, ""))

                fixed_files = await run_syntax_fix_loop(
                    syntax_errors=[err.to_dict() for err in syntax_errors],
                    files_to_check=error_files_with_content,
                    file_service=file_service,
                    design_output=build_design_output_with_pipeline(design_output, PIPELINE_ID),
                    max_retries=DEFAULT_MAX_RETRIES,
                    debugger=self.debugger,
                    coder_system_prompt=coder_agent.system_prompt,
                    pipeline_id=PIPELINE_ID,
                )

                # 【修复】重新验证语法错误是否已修复，而不是仅检查 fixed_files
                remaining_syntax_errors = await self.e2e_service.validate_code_syntax(code_files, file_service, PIPELINE_ID)
                if remaining_syntax_errors:
                    print(f"   ❌ 修复后仍有 {len(remaining_syntax_errors)} 个语法错误")
                    for err in remaining_syntax_errors:
                        print(f"      - {err.file}: {err.error}")
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
                    max_retries=DEFAULT_MAX_RETRIES,
                    debugger=self.debugger,
                    coder_system_prompt=coder_agent.system_prompt
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
                    code_output={"files": code_files},
                    debugger=self.debugger,
                    tester_system_prompt=tester_agent.system_prompt
                )
                if not fixed:
                    raise RuntimeError(f"导入错误无法修复: {import_errors}")

            test_syntax_errors = await self.e2e_service.validate_code_syntax(
                [{"file_path": tf.get("file_path", ""), "change_type": "add", "content": tf.get("content", "")}
                 for tf in test_files],
                file_service,
                PIPELINE_ID
            )
            if test_syntax_errors:
                print(f"   ❌ 发现 {len(test_syntax_errors)} 个测试语法错误")
                fixed_test_files = await run_test_syntax_fix_loop(
                    test_files=test_files,
                    syntax_errors=[err.to_dict() for err in test_syntax_errors],
                    file_service=file_service,
                    design_output=build_design_output_with_pipeline(design_output, PIPELINE_ID),
                    code_output={"files": code_files},
                    debugger=self.debugger,
                    tester_system_prompt=tester_agent.system_prompt
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
                        duration_seconds=time.time() - start,
                        linting_passed=getattr(self, 'linting_passed', True)
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

            # 保存调试摘要
            summary_path = self.debugger.save_summary()
            if summary_path:
                print(f"🔍 Agent 调试摘要已保存: {summary_path}")

            return E2EContractResult(
                success=success,
                code_generated=len(code_files) > 0,
                tests_generated=True,
                tests_passed=success,
                layered_result=layered_result,
                duration_seconds=duration,
                linting_passed=getattr(self, 'linting_passed', True)
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

        # 【Traceback 路径提取策略】简化版本
        # 不再主动包含 import 关联文件，而是让 RepairerAgent 使用工具自行探索
        # 第1步：从 Traceback 提取关键文件路径
        essential_paths = extract_critical_files(logs, generated_file_paths)
        print(f"   🎯 精选策略：从 {len(generated_file_paths)} 个文件中提取 {len(essential_paths)} 个核心文件（Traceback 关联）")
        print(f"   💡 提示：RepairerAgent 可使用 read_file/glob/grep 等工具探索 import 依赖")

        fix_order = build_fix_order(
            failed_tests=failed_tests,
            logs=logs,
            generated_file_paths=essential_paths,  # 使用精简后的路径列表
            errors_list=errors_list
        )

        # 【方案二】利用 ProjectCard 注入核心契约文件的函数签名（已取消）
        # 注：地基代码通过 context_builder.get_evergreen_context() 统一注入，不再在此重复注入
        # try:
        #     from app.agents.project_card_builder import ProjectCardBuilder
        #
        #     builder = ProjectCardBuilder(Path(str(self.backend_dir)))
        #     signatures = builder._build_function_signature_library(max_files=20)
        #
        #     # 提取核心契约文件的签名
        #     core_contracts = ["app/core/response.py", "app/core/database.py"]
        #     contract_signatures = []
        #     for core_file in core_contracts:
        #         if core_file in signatures:
        #             func_sigs = signatures[core_file]
        #             sig_text = f"\n【{core_file} 函数签名】\n"
        #             for func in func_sigs[:5]:  # 每个文件最多5个函数
        #                 sig_text += f"  - {func.get('signature', 'unknown')}\n"
        #             contract_signatures.append(sig_text)
        #
        #     if contract_signatures:
        #         fix_order["fix_hint"] += "\n【参考：核心契约库函数签名】" + "".join(contract_signatures)
        #         print(f"   📋 已注入核心契约文件函数签名到 fix_hint")
        # except Exception as e:
        #     print(f"   ⚠️ 注入函数签名失败（非关键）: {e}")

        # 第3步：收集关键文件的完整内容（已取消强制注入，由 RepairerAgent 自行获取）
        # 注：不再预先注入文件内容，RepairerAgent 会使用 read_file/glob/grep 等工具自行获取所需文件
        target_files = {}
        # for path in essential_paths:
        #     if path in file_contents:
        #         target_files[path] = file_contents[path]
        #     else:
        #         read_res = await file_service.read_file(path)
        #         if read_res.exists:
        #             target_files[path] = read_res.content

        # 【已取消】不再主动探索测试文件的 import 依赖，由 RepairerAgent 自行发现
        # from app.utils.repair_utils import parse_all_app_imports, module_to_file_path
        # discovered_modules = set()
        # for file_info in all_generated_files:
        #     file_path = file_info.get("file_path", "")
        #     file_content = file_info.get("content", "")
        #     if "test" in file_path.lower():
        #         imported_modules = parse_all_app_imports(file_content)
        #         for module in imported_modules:
        #             if module not in discovered_modules:
        #                 discovered_modules.add(module)
        #                 dep_file_path = module_to_file_path(module)
        #                 if dep_file_path not in target_files:
        #                     read_res = await file_service.read_file(dep_file_path)
        #                     if read_res.exists and read_res.content:
        #                         target_files[dep_file_path] = read_res.content
        #                         print(f"   📦 从测试导入发现依赖: {dep_file_path}")

        print(f"   📦 RepairerAgent 将自行获取所需文件内容（不强制注入）")

        repairer = RepairerAgentWithTools()
        repair_input = {
            "pipeline_id": PIPELINE_ID,
            "stage_name": "REPAIR",
            "fix_order": fix_order,
            "target_files": target_files,
            "file_service": file_service,
            "max_rounds": 3,
            "debugger": self.debugger
        }
        repair_result = await repairer.execute_with_tools(**repair_input)

        # 保存最终汇总调试信息（每轮的详细信息已在 execute_with_tools 内部保存）
        self.debugger.save_agent_io(
            agent_name="RepairerAgent",
            stage="repair_final_summary",
            input_data=repair_input,
            output_data=repair_result,
            metadata={"failed_tests": failed_tests, "missing_symbols": missing_symbols or []},
            success=repair_result.get("success", False),
            error=repair_result.get("error"),
            tool_calls=repair_result.get("tool_results", []),
            system_prompt=repairer.system_prompt if hasattr(repairer, 'system_prompt') else None
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

        fix_input = {
            "design_output": {
                **design_output,
                "fix_mode": True,
                "fix_instruction": build_type_error_fix_instruction(type_errors),
                "affected_files": [tf.get("file_path", "") for tf in test_files]
            },
            "code_output": {"files": code_files},
            "pipeline_id": PIPELINE_ID
        }
        fix_result = await tester_agent.generate_tests(**fix_input)

        # 保存调试信息
        self.debugger.save_agent_io(
            agent_name="TesterAgent",
            stage="type_error_fix",
            input_data=fix_input,
            output_data=fix_result,
            metadata={"type_errors": [str(e) for e in type_errors]},
            success=fix_result.get("success", False),
            error=fix_result.get("error"),
            tool_calls=fix_result.get("tool_results", []),
            system_prompt=tester_agent.system_prompt
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
    
    # 打印详细结果摘要
    print("\n" + "=" * 70)
    print("📊 测试执行摘要")
    print("=" * 70)
    print(f"成功: {'✅ 是' if result.success else '❌ 否'}")
    print(f"代码生成: {'✅' if result.code_generated else '❌'}")
    print(f"测试生成: {'✅' if result.tests_generated else '❌'}")
    print(f"测试通过: {'✅' if result.tests_passed else '❌'}")
    print(f"Linting 检查: {'✅ 通过' if result.linting_passed else '⚠️ 有警告'}")
    print(f"总耗时: {result.duration_seconds:.1f}s")
    if result.error_message:
        print(f"错误: {result.error_message}")
    print("=" * 70)
    
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
