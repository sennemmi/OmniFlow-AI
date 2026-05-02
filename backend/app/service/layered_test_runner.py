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
"""

import asyncio
import os
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.service.test_runner import TestRunnerService


@dataclass
class LayerResult:
    layer: str              # syntax | defense | regression | new_tests | health
    passed: bool
    summary: str
    logs: str = ""
    failed_tests: List[str] = field(default_factory=list)
    error_type: Optional[str] = None   # syntax_error | defense_failure | test_failure | ...


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
    ) -> LayeredTestResult:

        layers: List[LayerResult] = []

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
        defense_path = ws / cls.DEFENSE_TEST_DIR
        if defense_path.exists() and any(defense_path.rglob("test_*.py")):
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

        # ── Layer 3: 回归测试（受保护层）──────────────────────────────
        regression_failed: List[str] = []
        for reg_dir in cls.REGRESSION_DIRS:
            # 跳过防御性测试目录（已在 Layer 2 执行）
            if reg_dir == cls.DEFENSE_TEST_DIR or reg_dir.endswith("defense"):
                continue

            reg_path = ws / reg_dir
            if not reg_path.exists() or not any(reg_path.rglob("test_*.py")):
                continue
            r = await TestRunnerService.run_tests(
                str(ws), timeout=timeout, test_path=reg_dir
            )
            layer_result = LayerResult(
                layer="regression",
                passed=r["success"],
                summary=r["summary"],
                logs=r.get("logs", ""),
                failed_tests=r.get("failed_tests", []),
                error_type=r.get("error_type"),
            )
            layers.append(layer_result)
            if not r["success"]:
                regression_failed.extend(r.get("failed_tests", []))

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
        new_tests_path = ws / cls.NEW_TESTS_DIR
        if new_tests_path.exists() and any(new_tests_path.rglob("test_*.py")):
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

        return LayeredTestResult(all_passed=True, layers=layers)

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
