"""
分层测试运行器
防止新代码与旧测试的"套娃"判断问题：分层隔离，各自报告。

【快速失败设计原则 - Fail Fast】
Layer 顺序按照"发现问题速度"和"修复成本"排列：
1. Layer 1 (语法检查) - 毫秒级，不启动子进程
2. Layer 2 (防御性/回归测试) - 秒级，验证核心保护机制
3. Layer 3 (新测试) - 秒级，验证新生成功能
4. Layer 4 (健康检查) - 验证服务启动

这样设计的原因：
- 如果破坏了防御性测试（如文件回滚、路径安全），应该立即失败，不需要跑新测试
- 防御性测试失败 = 代码破坏了系统核心保护机制，必须人工介入
- 新测试失败 = 功能实现有问题，可以进入 Auto-Fix 循环

【Docker 环境支持】
- 支持通过 file_service 在 Docker 容器中检查文件是否存在
- 如果 file_service 为 None，则回退到本地文件系统检查
"""

import asyncio
import os
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.service.test_runner import TestRunnerService
from app.service.sandbox_file_service import SandboxFileService


class LayerStatus:
    """分层测试状态常量"""
    SYNTAX = "syntax"
    DEFENSE = "defense"
    REGRESSION = "regression"
    NEW_TESTS = "new_tests"
    HEALTH = "health"
    SMOKE_TEST = "smoke_test"  # 【新增】冒烟测试层


@dataclass
class LayerResult:
    layer: str              # syntax | defense | regression | new_tests | health | smoke_test
    passed: bool
    summary: str
    logs: str = ""
    failed_tests: List[str] = field(default_factory=list)
    error_type: Optional[str] = None   # syntax_error | defense_failure | test_failure | smoke_test_failure | ...


@dataclass
class LayeredTestResult:
    all_passed:    bool
    layers:        List[LayerResult]
    # 关键分类：是代码的问题，还是旧测试不兼容？
    failure_cause: Optional[str] = None  # "code_bug" | "defense_broken" | "regression_broken" | None
    failed_tests: List[str] = field(default_factory=list)
    # 详细的错误信息，用于传递给 AI 进行修复
    error_details: Dict[str, Any] = field(default_factory=dict)


class LayeredTestRunner:
    """
    四层测试策略（按快速失败原则排序）：
      Layer 1 - 语法检查：对所有新生成文件做 ast.parse，毫秒级
      Layer 2 - 防御性测试：跑 backend/tests/unit/defense/
                （这是"免疫系统"——失败说明破坏了核心保护机制，必须人工介入）
      Layer 3 - 新测试：只跑 backend/tests/ai_generated/
                （失败可进入 Auto-Fix 循环）
      Layer 4 - 健康检查：curl sandbox /health（可选，有 sandbox_port 才跑）

    【防御性测试说明】
    backend/tests/unit/defense/ 目录包含 4 层防线的核心测试：
    - Layer 1 防线: 代码修改与沙箱测试（防止 AI 破坏物理文件）
    - Layer 2 防线: 测试运行器与决策测试（防止"旧测试"被 AI 篡改）
    - Layer 3 防线: 多 Agent 协作与状态机测试（防止系统死循环）
    - Layer 4 防线: 工作流与状态持久化测试（确保界面显示正确）

    这些测试是系统的"免疫系统"，任何代码变更都必须通过。
    如果防御性测试失败，说明代码破坏了核心保护机制，必须人工介入。
    """

    NEW_TESTS_DIR        = "backend/tests/ai_generated"
    DEFENSE_TEST_DIR     = "backend/tests/unit/defense"
    REGRESSION_DIRS      = [
        "backend/tests/unit",
        "backend/tests/integration"
    ]

    @classmethod
    async def run(
        cls,
        workspace_path: str,
        new_files: List[Dict[str, Any]],   # CoderAgent + TestAgent 产出的文件列表
        sandbox_port: Optional[int] = None,
        timeout: int = 120,
        file_service: Optional[SandboxFileService] = None,  # Docker 环境文件服务
    ) -> LayeredTestResult:

        layers: List[LayerResult] = []
        executed_test_layers = 0  # 【修复】记录实际执行的测试层数

        # ── Layer 1: 语法检查（毫秒级，最快失败）────────────────────────
        syntax_result = cls._check_syntax(new_files)
        layers.append(syntax_result)
        if not syntax_result.passed:
            return LayeredTestResult(
                all_passed=False,
                layers=layers,
                failure_cause="code_bug",
                error_details={
                    "layer": "syntax",
                    "message": "代码存在语法错误",
                    "logs": syntax_result.logs,
                    "suggestion": "检查 Python 语法，确保所有括号、引号正确闭合"
                }
            )

        ws = Path(workspace_path)

        # ── Layer 2: 防御性测试（核心保护机制，优先于新测试）──────────────
        # 防御性测试失败 = 破坏了系统免疫系统，必须人工介入
        # 【支持 Docker】通过 file_service 或本地文件系统检查
        # 注意：传入相对路径，因为 file_service 会自动添加 /workspace 前缀
        defense_exists = await cls._check_path_exists(
            file_service, cls.DEFENSE_TEST_DIR, str(ws / cls.DEFENSE_TEST_DIR)
        )
        if defense_exists:
            executed_test_layers += 1  # 【修复】记录执行了测试层
            # 【Docker 支持】如果在 Docker 环境，使用 file_service 执行测试
            if file_service is not None:
                r = await cls._run_tests_in_docker(
                    file_service, cls.DEFENSE_TEST_DIR, timeout
                )
            else:
                r = await TestRunnerService.run_tests(
                    str(ws), timeout=timeout, test_path=cls.DEFENSE_TEST_DIR
                )
            defense_result = LayerResult(
                layer="defense",
                passed=r["success"],
                summary=r["summary"],
                logs=r.get("logs", ""),
                failed_tests=r.get("failed_tests", []),
                error_type="defense_failure" if not r["success"] else None,
            )
            layers.append(defense_result)

            if not defense_result.passed:
                # 防御性测试失败 = 破坏了核心保护机制
                failed_tests = r.get("failed_tests", [])
                return LayeredTestResult(
                    all_passed=False,
                    layers=layers,
                    failure_cause="defense_broken",
                    failed_tests=failed_tests,
                    error_details={
                        "layer": "defense",
                        "message": f"防御性测试失败: {len(failed_tests)} 个测试未通过",
                        "logs": r.get("logs", "")[:2000],  # 限制长度避免 Token 过多
                        "failed_tests": failed_tests,
                        "suggestion": "代码变更破坏了系统的核心保护机制（如文件回滚、路径安全、状态机等）。"
                                     "这是严重问题，必须人工检查代码，不能自动修复。"
                    }
                )
        else:
            # 【修复】目录检查失败（可能是超时），添加警告层
            layers.append(LayerResult(
                layer="defense",
                passed=False,  # 视为失败
                summary="防御性测试目录检查失败（可能是超时）",
                logs="无法访问 backend/tests/unit/defense 目录，命令执行超时",
                error_type="check_timeout",
            ))

        # ── Layer 3: 回归测试（受保护层）──────────────────────────────
        regression_failed: List[str] = []
        regression_checked = False  # 【修复】标记是否成功检查了回归测试
        for reg_dir in cls.REGRESSION_DIRS:
            # 跳过防御性测试目录（已在 Layer 2 执行）
            if reg_dir == cls.DEFENSE_TEST_DIR or reg_dir.endswith("defense"):
                continue

            # 【支持 Docker】通过 file_service 或本地文件系统检查
            # 注意：传入相对路径，因为 file_service 会自动添加 /workspace 前缀
            reg_exists = await cls._check_path_exists(
                file_service, reg_dir, str(ws / reg_dir)
            )
            if not reg_exists:
                continue
            
            regression_checked = True  # 【修复】标记已检查
            executed_test_layers += 1  # 【修复】记录执行了测试层
            
            # 【Docker 支持】如果在 Docker 环境，使用 file_service 执行测试
            if file_service is not None:
                r = await cls._run_tests_in_docker(file_service, reg_dir, timeout)
            else:
                r = await TestRunnerService.run_tests(
                    str(ws), timeout=timeout, test_path=reg_dir
                )
            # 【修复】如果测试执行失败是因为"没有测试可运行"（exit_code=5），视为通过
            exit_code = r.get("exit_code")
            logs_lower = r.get("logs", "").lower()
            is_no_tests = (not r["success"] and 
                          ("no tests ran" in logs_lower or 
                           exit_code == 5 or 
                           exit_code == "5"))
            
            if is_no_tests:
                layer_result = LayerResult(
                    layer="regression",
                    passed=True,  # 没有测试可运行视为通过
                    summary=f"{r['summary']} (无测试可运行，视为通过)",
                    logs=r.get("logs", ""),
                    failed_tests=[],
                    error_type=None,
                )
            else:
                layer_result = LayerResult(
                    layer="regression",
                    passed=r["success"],
                    summary=r["summary"],
                    logs=r.get("logs", ""),
                    failed_tests=r.get("failed_tests", []),
                    error_type=r.get("error_type"),
                )
                if not r["success"]:
                    regression_failed.extend(r.get("failed_tests", []))
            
            layers.append(layer_result)
        
        # 【修复】如果没有成功检查任何回归测试目录，添加失败层
        if not regression_checked:
            layers.append(LayerResult(
                layer="regression",
                passed=False,
                summary="回归测试目录检查失败（可能是超时）",
                logs="无法访问回归测试目录，命令执行超时",
                error_type="check_timeout",
            ))

        if regression_failed:
            # 触发"旧测试不兼容"分支，不进 Auto-Fix Loop
            return LayeredTestResult(
                all_passed=False,
                layers=layers,
                failure_cause="regression_broken",
                failed_tests=regression_failed,
                error_details={
                    "layer": "regression",
                    "message": f"回归测试失败: {len(regression_failed)} 个测试未通过",
                    "failed_tests": regression_failed,
                    "suggestion": "新代码导致原有测试失败。请选择：更新测试以适配新代码，或回滚代码变更。"
                }
            )

        # ── Layer 4: 新生成测试（可进入 Auto-Fix 循环）───────────────────
        # 【支持 Docker】通过 file_service 或本地文件系统检查
        # 注意：传入相对路径，因为 file_service 会自动添加 /workspace 前缀
        new_tests_exists = await cls._check_path_exists(
            file_service, cls.NEW_TESTS_DIR, str(ws / cls.NEW_TESTS_DIR)
        )
        if new_tests_exists:
            executed_test_layers += 1  # 【修复】记录执行了测试层
            # 【Docker 支持】如果在 Docker 环境，使用 file_service 执行测试
            if file_service is not None:
                r = await cls._run_tests_in_docker(
                    file_service, cls.NEW_TESTS_DIR, timeout
                )
            else:
                r = await TestRunnerService.run_tests(
                    str(ws), timeout=timeout, test_path=cls.NEW_TESTS_DIR
                )
            new_test_result = LayerResult(
                layer="new_tests",
                passed=r["success"],
                summary=r["summary"],
                logs=r.get("logs", ""),
                failed_tests=r.get("failed_tests", []),
                error_type=r.get("error_type"),
            )
            layers.append(new_test_result)

            if not new_test_result.passed:
                # 新测试失败 = 功能实现有问题，可以 Auto-Fix
                return LayeredTestResult(
                    all_passed=False,
                    layers=layers,
                    failure_cause="code_bug",
                    failed_tests=r.get("failed_tests", []),
                    error_details={
                        "layer": "new_tests",
                        "message": f"新测试失败: {len(r.get('failed_tests', []))} 个测试未通过",
                        "logs": r.get("logs", "")[:2000],
                        "failed_tests": r.get("failed_tests", []),
                        "suggestion": "功能实现不符合测试预期。AI 将自动分析错误并修复代码。"
                    }
                )
        else:
            # 【修复】目录检查失败（可能是超时），添加失败层
            layers.append(LayerResult(
                layer="new_tests",
                passed=False,
                summary="新生成测试目录检查失败（可能是超时）",
                logs="无法访问 backend/tests/ai_generated 目录，命令执行超时",
                error_type="check_timeout",
            ))

        # ── Layer 5: 健康检查 ──────────────────────────────────────────
        if sandbox_port:
            health_ok = await cls._check_health(sandbox_port)
            layers.append(LayerResult(
                layer="health",
                passed=health_ok,
                summary="服务健康检查" + ("通过" if health_ok else "失败"),
            ))
            # 健康检查失败也视为 code_bug（启动问题）
            if not health_ok:
                return LayeredTestResult(
                    all_passed=False,
                    layers=layers,
                    failure_cause="code_bug",
                    error_details={
                        "layer": "health",
                        "message": "服务健康检查失败",
                        "suggestion": "代码可能导致服务无法启动，请检查依赖和配置"
                    }
                )

        # 【修复】最终判断：只有实际执行了至少一个测试层且全部通过，才算成功
        # 如果所有测试层都因为超时等原因被跳过，应该视为失败
        all_layers_passed = all(layer.passed for layer in layers)
        
        # 检查是否有检查超时的错误
        has_timeout_errors = any(
            layer.error_type == "check_timeout" for layer in layers
        )
        
        if has_timeout_errors:
            # 如果有超时错误，返回失败并附带详细信息
            return LayeredTestResult(
                all_passed=False,
                layers=layers,
                failure_cause="infrastructure_error",
                error_details={
                    "layer": "multiple",
                    "message": "测试基础设施问题：目录检查命令超时",
                    "logs": "Docker/Sandbox 环境响应缓慢，导致目录检查命令超时。请检查容器状态。",
                    "suggestion": "请检查 Docker 容器是否正常运行，或增加命令超时时间。"
                }
            )
        
        return LayeredTestResult(all_passed=all_layers_passed, layers=layers)

    # ── 私有方法 ──────────────────────────────────────────────────────

    @classmethod
    def _check_syntax(cls, files: List[Dict[str, Any]]) -> LayerResult:
        """对所有 .py 文件做 ast.parse，不起子进程，毫秒级完成。"""
        errors = []
        for f in files:
            path    = f.get("file_path", "")
            content = f.get("content", "")
            if not path.endswith(".py") or not content:
                continue
            try:
                ast.parse(content)
            except SyntaxError as e:
                errors.append(f"{path}: SyntaxError at line {e.lineno}: {e.msg}")

        if errors:
            return LayerResult(
                layer="syntax", passed=False,
                summary=f"{len(errors)} 个文件存在语法错误",
                logs="\n".join(errors),
                error_type="syntax_error",
            )
        return LayerResult(layer="syntax", passed=True, summary="语法检查通过")

    @classmethod
    async def _check_health(cls, port: int, timeout: int = 5) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-sf", f"http://localhost:{port}/health",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode == 0
        except Exception:
            return False

    @classmethod
    async def _run_tests_in_docker(
        cls,
        file_service: SandboxFileService,
        test_path: str,
        timeout: int = 120,
        ignore_patterns: Optional[List[str]] = None,
        specific_tests: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        在 Docker 容器中执行 pytest 测试

        Args:
            file_service: SandboxFileService 实例
            test_path: 测试路径（如 "backend/tests/unit/defense"）
            timeout: 超时时间（秒）
            ignore_patterns: 要忽略的路径模式列表（如 ["defense"]）
            specific_tests: 指定要运行的具体测试文件列表（如 ["test_timestamp.py"]）
                           如果提供，则只运行这些文件，避免无关文件干扰

        Returns:
            Dict: 测试结果
        """
        from app.service.sandbox_manager import sandbox_manager
        import re

        pipeline_id = file_service.pipeline_id

        # 构建 pytest 命令
        # -v: 详细模式
        # --tb=short: 短堆栈
        # --color=no: 禁用颜色
        # 注意：不再使用 -x 和 --maxfail=1，让 pytest 跑完全部测试
        # 这样可以一次性收集所有失败，避免"修一个冒一个"的乒乓效应
        # 注意：test_path 已经是如 "backend/tests/unit/defense" 的格式

        # 添加 --ignore 参数
        ignore_args = ""
        if ignore_patterns:
            for pattern in ignore_patterns:
                # 构建相对路径的 ignore 参数
                ignore_path = f"{test_path}/{pattern}"
                ignore_args += f"--ignore={ignore_path} "

        # 【方案二】如果指定了具体测试文件，只运行这些文件，避免无关文件干扰
        if specific_tests:
            # 构建具体的测试文件路径
            test_targets = " ".join([f"{test_path}/{t}" for t in specific_tests])
        else:
            test_targets = test_path

        cmd = (
            f"cd /workspace && "
            f"PYTHONPATH=/workspace/backend python -m pytest {test_targets} "
            f"{ignore_args}"
            f"-v --tb=short --color=no "
            f"2>&1"
        )

        try:
            exec_result = await sandbox_manager.exec(
                pipeline_id,
                cmd,
                timeout=timeout
            )

            stdout = exec_result.stdout or ""
            stderr = exec_result.stderr or ""
            logs = stdout + "\n" + stderr

            # 解析测试结果
            success = exec_result.exit_code == 0

            # 提取失败测试
            failed_tests = []
            if not success:
                # 匹配 pytest 的失败测试输出
                pattern = r"FAILED\s+(\S+)"
                failed_tests = re.findall(pattern, logs)

            # 提取摘要
            summary_match = re.search(r"(\d+) passed|(\d+) failed|(\d+) error", logs)
            if summary_match:
                summary = summary_match.group(0)
            else:
                summary = "测试执行完成" if success else "测试执行失败"

            # 检测错误类型（仅在测试失败时）
            error_type = None
            if not success:
                if "SyntaxError" in logs or "IndentationError" in logs:
                    error_type = "syntax_error"
                elif "ImportError" in logs or "ModuleNotFoundError" in logs:
                    error_type = "import_error"
                elif "collection" in logs.lower() and "error" in logs.lower():
                    error_type = "collection_error"
                else:
                    error_type = "test_failure"

            # 【DEBUG】打印详细的测试日志
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[LayeredTestRunner] 测试执行结果: success={success}, exit_code={exec_result.exit_code}")
            logger.info(f"[LayeredTestRunner] 测试路径: {test_path}")
            logger.info(f"[LayeredTestRunner] 摘要: {summary}")
            logger.info(f"[LayeredTestRunner] 错误类型: {error_type}")
            logger.info(f"[LayeredTestRunner] 失败测试: {failed_tests}")
            logger.info(f"[LayeredTestRunner] 完整日志前2000字符:\n{logs[:2000]}")
            if len(logs) > 2000:
                logger.info(f"[LayeredTestRunner] 完整日志后1000字符:\n{logs[-1000:]}")

            return {
                "success": success,
                "exit_code": exec_result.exit_code,
                "logs": logs,
                "summary": summary,
                "error": stderr if stderr else None,
                "error_type": error_type,
                "failed_tests": failed_tests
            }

        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "logs": str(e),
                "summary": "测试执行异常",
                "error": str(e),
                "error_type": "execution_error",
                "failed_tests": []
            }

    @classmethod
    async def _check_path_exists(
        cls,
        file_service: Optional[SandboxFileService],
        relative_path: str,
        absolute_path: str
    ) -> bool:
        """
        检查路径是否存在（支持 Docker 和本地环境）

        Args:
            file_service: Docker 文件服务，如果为 None 则使用本地文件系统
            relative_path: 相对路径（用于 Docker 环境，如 "backend/tests/unit/defense"）
            absolute_path: 绝对路径（用于本地环境，如 "/workspace/backend/tests/unit/defense"）

        Returns:
            bool: 路径是否存在
        """
        if file_service is not None:
            # Docker 环境：使用 file_service 检查
            # SandboxFileService 会自动处理 backend/ 前缀，直接传入即可
            try:
                result = await file_service.list_directory(relative_path)
                return result.get("success", False)
            except Exception:
                return False
        else:
            # 本地环境：使用 Path.exists()
            return Path(absolute_path).exists()
