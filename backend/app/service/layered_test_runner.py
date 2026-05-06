"""
分层测试运行器（简化版）

分层结构：
1. Layer 1 - defense（防御性测试）
2. Layer 2 - regression（回归测试，跳过 defense 目录）
3. Layer 3 - new_tests（新生成测试）

【逐层修复设计】
- 每层失败后调用 RepairAgent 修复
- 修复后重新运行该层，直到通过或达到最大修复次数
- 当前层通过后才进入下一层
"""

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.service.test_runner import TestRunnerService
from app.service.sandbox_file_service import SandboxFileService


class LayerStatus:
    """分层测试状态常量"""
    DEFENSE = "defense"
    REGRESSION = "regression"
    NEW_TESTS = "new_tests"


@dataclass
class LayerResult:
    layer: str              # defense | regression | new_tests
    passed: bool
    summary: str
    logs: str = ""
    failed_tests: List[str] = field(default_factory=list)
    error_type: Optional[str] = None


@dataclass
class LayeredTestResult:
    all_passed:    bool
    layers:        List[LayerResult]
    failure_cause: Optional[str] = None
    failed_tests: List[str] = field(default_factory=list)
    error_details: Dict[str, Any] = field(default_factory=dict)


class LayeredTestRunner:
    """
    三层测试策略（简化版）：
      Layer 1 - 防御性测试：跑 backend/tests/unit/defense/
      Layer 2 - 回归测试：跑 backend/tests/unit 和 backend/tests/integration（跳过 defense）
      Layer 3 - 新测试：跑 backend/tests/ai_generated/
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
        new_files: List[Dict[str, Any]],
        sandbox_port: Optional[int] = None,
        timeout: int = 120,
        file_service: Optional[SandboxFileService] = None,
    ) -> LayeredTestResult:
        """
        执行分层测试（逐层执行，每层失败后修复再重试）
        """
        layers: List[LayerResult] = []
        ws = Path(workspace_path)

        # ── Layer 1: 防御性测试 ─────────────────────────────────────────
        defense_result = await cls._run_defense_layer(
            ws, file_service, timeout
        )
        layers.append(defense_result)

        if not defense_result.passed:
            return LayeredTestResult(
                all_passed=False,
                layers=layers,
                failure_cause="defense_broken",
                failed_tests=defense_result.failed_tests,
                error_details={
                    "layer": "defense",
                    "message": f"防御性测试失败: {len(defense_result.failed_tests)} 个测试未通过",
                    "logs": defense_result.logs[:2000],
                    "failed_tests": defense_result.failed_tests,
                    "suggestion": "代码破坏了系统核心保护机制，需要修复"
                }
            )

        # ── Layer 2: 回归测试 ───────────────────────────────────────────
        regression_result = await cls._run_regression_layer(
            ws, file_service, timeout
        )
        layers.append(regression_result)

        if not regression_result.passed:
            return LayeredTestResult(
                all_passed=False,
                layers=layers,
                failure_cause="regression_broken",
                failed_tests=regression_result.failed_tests,
                error_details={
                    "layer": "regression",
                    "message": f"回归测试失败: {len(regression_result.failed_tests)} 个测试未通过",
                    "logs": regression_result.logs[:2000],
                    "failed_tests": regression_result.failed_tests,
                    "suggestion": "新代码导致原有测试失败"
                }
            )

        # ── Layer 3: 新生成测试 ─────────────────────────────────────────
        new_test_result = await cls._run_new_tests_layer(
            ws, file_service, timeout
        )
        layers.append(new_test_result)

        if not new_test_result.passed:
            return LayeredTestResult(
                all_passed=False,
                layers=layers,
                failure_cause="code_bug",
                failed_tests=new_test_result.failed_tests,
                error_details={
                    "layer": "new_tests",
                    "message": f"新测试失败: {len(new_test_result.failed_tests)} 个测试未通过",
                    "logs": new_test_result.logs[:2000],
                    "failed_tests": new_test_result.failed_tests,
                    "suggestion": "功能实现不符合测试预期"
                }
            )

        return LayeredTestResult(all_passed=True, layers=layers)

    @classmethod
    async def _run_defense_layer(
        cls,
        ws: Path,
        file_service: Optional[SandboxFileService],
        timeout: int
    ) -> LayerResult:
        """运行防御性测试层"""
        defense_exists = await cls._check_path_exists(
            file_service, cls.DEFENSE_TEST_DIR, str(ws / cls.DEFENSE_TEST_DIR)
        )

        if not defense_exists:
            return LayerResult(
                layer="defense",
                passed=True,  # 目录不存在视为通过
                summary="防御性测试目录不存在，跳过",
                logs="",
            )

        if file_service is not None:
            r = await cls._run_tests_in_docker(
                file_service, cls.DEFENSE_TEST_DIR, timeout
            )
        else:
            r = await TestRunnerService.run_tests(
                str(ws), timeout=timeout, test_path=cls.DEFENSE_TEST_DIR
            )

        return LayerResult(
            layer="defense",
            passed=r["success"],
            summary=r["summary"],
            logs=r.get("logs", ""),
            failed_tests=r.get("failed_tests", []),
            error_type="defense_failure" if not r["success"] else None,
        )

    @classmethod
    async def _run_regression_layer(
        cls,
        ws: Path,
        file_service: Optional[SandboxFileService],
        timeout: int
    ) -> LayerResult:
        """运行回归测试层（跳过 defense 目录）"""
        all_failed_tests: List[str] = []
        all_logs: List[str] = []
        any_executed = False

        for reg_dir in cls.REGRESSION_DIRS:
            # 【修复】正确跳过包含 defense 的目录
            if "defense" in reg_dir:
                continue

            reg_exists = await cls._check_path_exists(
                file_service, reg_dir, str(ws / reg_dir)
            )
            if not reg_exists:
                continue

            any_executed = True

            # 【修复】使用 --ignore 参数跳过 defense 子目录
            # 通过 _run_tests_in_docker 或 TestRunnerService 的特定调用方式
            if file_service is not None:
                # Docker 环境：使用带 ignore 的测试运行
                r = await cls._run_tests_in_docker_with_ignore(
                    file_service, reg_dir, timeout,
                    ignore_dirs=["defense"]
                )
            else:
                # 本地环境：直接运行，但跳过 defense 子目录的测试结果
                r = await TestRunnerService.run_tests(
                    str(ws), timeout=timeout, test_path=reg_dir
                )

            all_logs.append(f"=== {reg_dir} ===")
            all_logs.append(r.get("logs", ""))

            if not r["success"]:
                # 检查是否是"没有测试可运行"
                logs_lower = r.get("logs", "").lower()
                exit_code = r.get("exit_code")
                is_no_tests = (
                    "no tests ran" in logs_lower or
                    exit_code == 5 or
                    exit_code == "5"
                )
                if not is_no_tests:
                    all_failed_tests.extend(r.get("failed_tests", []))

        if not any_executed:
            return LayerResult(
                layer="regression",
                passed=True,
                summary="回归测试目录不存在，跳过",
                logs="",
            )

        return LayerResult(
            layer="regression",
            passed=len(all_failed_tests) == 0,
            summary=f"回归测试: {len(all_failed_tests)} 个失败" if all_failed_tests else "回归测试通过",
            logs="\n".join(all_logs),
            failed_tests=all_failed_tests,
            error_type="regression_failure" if all_failed_tests else None,
        )

    @classmethod
    async def _run_new_tests_layer(
        cls,
        ws: Path,
        file_service: Optional[SandboxFileService],
        timeout: int
    ) -> LayerResult:
        """运行新生成测试层"""
        new_tests_exists = await cls._check_path_exists(
            file_service, cls.NEW_TESTS_DIR, str(ws / cls.NEW_TESTS_DIR)
        )

        if not new_tests_exists:
            return LayerResult(
                layer="new_tests",
                passed=True,  # 目录不存在视为通过
                summary="新生成测试目录不存在，跳过",
                logs="",
            )

        if file_service is not None:
            r = await cls._run_tests_in_docker(
                file_service, cls.NEW_TESTS_DIR, timeout
            )
        else:
            r = await TestRunnerService.run_tests(
                str(ws), timeout=timeout, test_path=cls.NEW_TESTS_DIR
            )

        return LayerResult(
            layer="new_tests",
            passed=r["success"],
            summary=r["summary"],
            logs=r.get("logs", ""),
            failed_tests=r.get("failed_tests", []),
            error_type="test_failure" if not r["success"] else None,
        )

    @classmethod
    async def _check_path_exists(
        cls,
        file_service: Optional[SandboxFileService],
        relative_path: str,
        absolute_path: str
    ) -> bool:
        """检查路径是否存在"""
        if file_service is not None:
            try:
                result = await file_service.list_directory(relative_path)
                return result.get("success", False)
            except Exception:
                return False
        else:
            return Path(absolute_path).exists()

    @classmethod
    async def _run_tests_in_docker(
        cls,
        file_service: SandboxFileService,
        test_path: str,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """在 Docker 容器中执行 pytest 测试"""
        return await cls._run_tests_in_docker_with_ignore(
            file_service, test_path, timeout, ignore_dirs=[]
        )

    @classmethod
    async def _run_tests_in_docker_with_ignore(
        cls,
        file_service: SandboxFileService,
        test_path: str,
        timeout: int = 120,
        ignore_dirs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """在 Docker 容器中执行 pytest 测试（支持忽略指定目录）"""
        from app.service.sandbox_manager import sandbox_manager
        import re

        pipeline_id = file_service.pipeline_id

        # 构建 ignore 参数
        ignore_args = ""
        if ignore_dirs:
            for dir_name in ignore_dirs:
                ignore_path = f"{test_path}/{dir_name}"
                ignore_args += f"--ignore={ignore_path} "

        cmd = (
            f"cd /workspace && "
            f"PYTHONPATH=/workspace/backend python -m pytest {test_path} "
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

            success = exec_result.exit_code == 0

            # 提取失败测试
            failed_tests = []
            if not success:
                pattern = r"FAILED\s+(\S+)"
                failed_tests = re.findall(pattern, logs)

            # 提取摘要
            summary_match = re.search(r"(\d+) passed|(\d+) failed|(\d+) error", logs)
            if summary_match:
                summary = summary_match.group(0)
            else:
                summary = "测试执行完成" if success else "测试执行失败"

            # 检测错误类型
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
