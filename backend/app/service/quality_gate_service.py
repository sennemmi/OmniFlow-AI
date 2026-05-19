"""
质量门禁服务 (QualityGateService)

统一 E2E 测试和 Pipeline 中的质量检查流程。
包括：语法检查、契约检查、测试导入验证、Linting 检查等。
"""

import logging
import py_compile
import re
import tempfile
import os
from typing import Dict, List, Optional, Any, Callable

from app.service.code_validation_service import CodeValidationService
from app.service.sandbox_file_service import SandboxFileService
from app.service.sandbox_manager import sandbox_manager
from app.core.contract_checker import check_contract_before_test, verify_contract
from app.core.sse_log_buffer import push_log
from app.utils.linting_utils import run_linting_check
from app.utils.test_execution import run_pytest_in_sandbox

logger = logging.getLogger(__name__)


class QualityGateService:
    """
    统一的质量门禁服务

    职责：
    1. 语法检查（CodeValidationService + py_compile）
    2. 契约检查（check_contract_before_test）
    3. 测试导入验证
    4. Linting 检查（run_linting_check）
    5. 分层测试运行

    使用场景：
    - E2E 测试脚本
    - TestingHandler (Pipeline)
    - 任何需要质量检查的地方
    """

    def __init__(self):
        pass

    async def run_quality_checks(
        self,
        code_files: List[Dict[str, Any]],
        pipeline_id: int,
        design_output: Optional[Dict[str, Any]] = None,
        test_files: Optional[List[Dict[str, Any]]] = None,
        file_service: Optional[SandboxFileService] = None,
        log_callback: Optional[Callable[[str, str], Any]] = None,
        enable_syntax_check: bool = True,
        enable_contract_check: bool = True,
        enable_import_check: bool = True,
        enable_linting: bool = True,
        enable_test_run: bool = False,
    ) -> Dict[str, Any]:
        """
        运行完整的质量门禁检查

        Args:
            code_files: 代码文件列表
            pipeline_id: Pipeline ID
            design_output: 设计输出（用于契约检查）
            test_files: 测试文件列表（用于测试运行）
            file_service: 沙箱文件服务
            log_callback: 日志回调函数 (level, message) -> None
            enable_*: 各检查项开关

        Returns:
            Dict: {
                "success": bool,
                "checks": Dict[str, Dict],  # 各检查项结果
                "errors": List[Dict],       # 所有错误汇总
                "summary": str,
            }
        """
        def log(level: str, message: str):
            if log_callback:
                log_callback(level, message)
            else:
                getattr(logger, level.lower(), logger.info)(message)
            push_log(pipeline_id, level.lower(), message, stage="QUALITY_GATE")

        log("info", "🔍 启动质量门禁检查...")

        all_errors = []
        checks = {}

        # 1. 语法检查
        if enable_syntax_check:
            log("info", "📋 执行语法检查...")
            syntax_result = await self._check_syntax(code_files, pipeline_id)
            checks["syntax"] = syntax_result
            if not syntax_result["passed"]:
                all_errors.extend(syntax_result.get("errors", []))
                log("error", f"❌ 语法检查失败: {len(syntax_result.get('errors', []))} 个错误")
            else:
                log("success", "✅ 语法检查通过")

        # 2. 契约检查
        if enable_contract_check and design_output:
            log("info", "📋 执行契约检查...")
            contract_result = await self._check_contract(code_files, design_output, pipeline_id)
            checks["contract"] = contract_result
            if not contract_result["passed"]:
                all_errors.extend(contract_result.get("errors", []))
                log("error", f"❌ 契约检查失败: {len(contract_result.get('errors', []))} 个问题")
            else:
                log("success", "✅ 契约检查通过")

        # 3. 导入检查
        if enable_import_check and file_service:
            log("info", "📋 执行导入检查...")
            import_result = await self._check_imports(code_files, pipeline_id, file_service)
            checks["import"] = import_result
            if not import_result["passed"]:
                all_errors.extend(import_result.get("errors", []))
                log("error", f"❌ 导入检查失败: {len(import_result.get('errors', []))} 个问题")
            else:
                log("success", "✅ 导入检查通过")

        # 4. Linting 检查
        if enable_linting and file_service:
            log("info", "📋 执行 Linting 检查...")
            lint_result = await self._check_linting(code_files, pipeline_id, file_service)
            checks["linting"] = lint_result
            if not lint_result["passed"]:
                all_errors.extend(lint_result.get("errors", []))
                log("warning", f"⚠️ Linting 检查发现 {len(lint_result.get('errors', []))} 个问题")
            else:
                log("success", "✅ Linting 检查通过")

        # 5. 测试运行（可选）
        if enable_test_run and test_files:
            log("info", "📋 执行测试运行...")
            test_result = await self._run_tests(test_files, pipeline_id)
            checks["test"] = test_result
            if not test_result["passed"]:
                all_errors.extend(test_result.get("errors", []))
                log("error", f"❌ 测试运行失败: {len(test_result.get('errors', []))} 个失败")
            else:
                log("success", "✅ 测试运行通过")

        # 汇总结果
        all_passed = all(check.get("passed", True) for check in checks.values())

        summary = self._build_summary(checks, all_errors)

        if all_passed:
            log("success", f"🎉 所有质量检查通过！({len(checks)} 项)")
        else:
            log("error", f"🚨 质量检查未通过: {len(all_errors)} 个问题")

        return {
            "success": all_passed,
            "checks": checks,
            "errors": all_errors,
            "summary": summary,
            "total_checks": len(checks),
            "passed_checks": sum(1 for c in checks.values() if c.get("passed", True)),
        }

    async def _check_syntax(
        self,
        code_files: List[Dict[str, Any]],
        pipeline_id: int,
        file_service: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        语法检查

        优先在沙箱内检查（避免宿主机编码问题）
        """
        errors = []

        # 提取文件路径列表
        file_paths = [
            f.get("file_path", "") for f in code_files
            if f.get("file_path") and f.get("content") and f.get("file_path", "").endswith(".py")
        ]

        if not file_paths:
            return {
                "passed": True,
                "errors": [],
                "error_count": 0,
            }

        # 优先使用沙箱内语法检查
        if file_service:
            try:
                from app.service.code_validation_service import code_validation_service
                sandbox_errors = await code_validation_service.check_syntax_in_sandbox(
                    file_paths=file_paths,
                    pipeline_id=pipeline_id
                )
                errors = [
                    {
                        "type": "syntax_error",
                        "file": err.file,
                        "line": err.line,
                        "message": err.error,
                    }
                    for err in sandbox_errors
                ]
            except Exception as e:
                logger.warning(f"沙箱内语法检查失败，回退到宿主机检查: {e}")
                errors = await self._check_syntax_host(code_files)
        else:
            errors = await self._check_syntax_host(code_files)

        return {
            "passed": len(errors) == 0,
            "errors": errors,
            "error_count": len(errors),
        }

    async def _check_syntax_host(
        self,
        code_files: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """在宿主机上进行语法检查（使用 UTF-8 编码）"""
        errors = []

        for file_info in code_files:
            file_path = file_info.get("file_path", "")
            content = file_info.get("content", "")

            if not file_path or not content or not file_path.endswith(".py"):
                continue

            # 使用临时文件进行语法检查（强制 UTF-8 编码）
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                py_compile.compile(tmp_path, doraise=True)
            except py_compile.PyCompileError as e:
                error_msg = str(e)
                line_no = 0
                if "line" in error_msg.lower():
                    line_match = re.search(r"line\s+(\d+)", error_msg, re.IGNORECASE)
                    if line_match:
                        line_no = int(line_match.group(1))

                errors.append({
                    "type": "syntax_error",
                    "file": file_path,
                    "line": line_no,
                    "message": error_msg,
                })
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return errors

    async def _check_contract(
        self,
        code_files: List[Dict[str, Any]],
        design_output: Dict[str, Any],
        pipeline_id: int,
    ) -> Dict[str, Any]:
        """契约检查"""
        code_files_dict = {}
        for f in code_files:
            fp = f.get("file_path", "")
            if f.get("content"):
                code_files_dict[fp] = f["content"]
            elif f.get("replace_block"):
                code_files_dict[fp] = f["replace_block"]

        contract_check = check_contract_before_test(
            design_output=design_output,
            code_files=code_files_dict
        )

        if contract_check.get("success", True):
            return {
                "passed": True,
                "errors": [],
                "violations": [],
            }

        violations = contract_check.get("violations", [])
        errors = [
            {
                "type": "contract_violation",
                "file": "",
                "line": 0,
                "message": v,
            }
            for v in violations
        ]

        return {
            "passed": False,
            "errors": errors,
            "violations": violations,
            "error_count": len(errors),
        }

    async def _check_imports(
        self,
        code_files: List[Dict[str, Any]],
        pipeline_id: int,
        file_service: SandboxFileService,
    ) -> Dict[str, Any]:
        """导入检查 - 在沙箱中验证代码能否正确导入"""
        errors = []

        # 构建需要检查的 Python 文件列表
        py_files = [
            f.get("file_path", "").replace("backend/", "")
            for f in code_files if f.get("file_path", "").endswith(".py")
        ]

        if not py_files:
            return {"passed": True, "errors": []}

        # 在沙箱中尝试导入每个模块
        for file_path in py_files[:5]:  # 限制检查数量，避免超时
            module_path = file_path.replace("/", ".").replace("\\", ".").replace(".py", "")

            try:
                result = await sandbox_manager.exec(
                    pipeline_id,
                    f"cd /workspace/backend && python -c 'import {module_path}' 2>&1",
                    timeout=10
                )

                if result.exit_code != 0:
                    errors.append({
                        "type": "import_error",
                        "file": file_path,
                        "line": 0,
                        "message": result.stderr or "Import failed",
                    })
            except Exception as e:
                logger.warning(f"Import check failed for {file_path}: {e}")

        return {
            "passed": len(errors) == 0,
            "errors": errors,
            "error_count": len(errors),
        }

    async def _check_linting(
        self,
        code_files: List[Dict[str, Any]],
        pipeline_id: int,
        file_service: SandboxFileService,
    ) -> Dict[str, Any]:
        """Linting 检查"""
        def log_callback(level: str, message: str):
            push_log(pipeline_id, level.lower(), message, stage="QUALITY_GATE")

        passed, errors = await run_linting_check(
            code_files=code_files,
            pipeline_id=pipeline_id,
            max_retries=0,  # 不重试，只检查
            log_callback=log_callback,
            enabled=True,
        )

        # 转换错误格式
        formatted_errors = [
            {
                "type": "lint_error",
                "file": err.get("filename", "").replace("/workspace/backend/", ""),
                "line": err.get("location", {}).get("row", 0),
                "message": f"[{err.get('code', '?')}] {err.get('message', '')}",
            }
            for err in errors
        ]

        return {
            "passed": passed,
            "errors": formatted_errors,
            "error_count": len(formatted_errors),
        }

    async def _run_tests(
        self,
        test_files: List[Dict[str, Any]],
        pipeline_id: int,
    ) -> Dict[str, Any]:
        """运行测试"""
        # 从 test_files 构建测试路径
        test_paths = []
        for tf in test_files:
            fp = tf.get("file_path", "")
            if fp:
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

        result = await run_pytest_in_sandbox(
            pipeline_id=pipeline_id,
            test_path=test_path_str,
            timeout=120,
        )

        if result.get("success"):
            return {
                "passed": True,
                "errors": [],
            }

        # 解析失败信息
        failed_tests = result.get("failed_tests", [])
        errors = [
            {
                "type": "test_failure",
                "file": test,
                "line": 0,
                "message": f"Test failed: {test}",
            }
            for test in failed_tests[:10]  # 限制错误数量
        ]

        return {
            "passed": False,
            "errors": errors,
            "logs": result.get("logs", ""),
            "error_count": len(errors),
        }

    def _build_summary(self, checks: Dict[str, Dict], all_errors: List[Dict]) -> str:
        """构建检查摘要"""
        lines = ["Quality Gate Check Summary:"]

        for check_name, check_result in checks.items():
            status = "✅ PASS" if check_result.get("passed", True) else "❌ FAIL"
            error_count = check_result.get("error_count", 0)
            lines.append(f"  {status} {check_name}: {error_count} issues")

        if all_errors:
            lines.append(f"\nTotal errors: {len(all_errors)}")
            for err in all_errors[:5]:
                lines.append(f"  - [{err.get('type', 'unknown')}] {err.get('file', '')}:{err.get('line', 0)}: {err.get('message', '')[:50]}")

        return "\n".join(lines)


# 全局单例实例
quality_gate_service = QualityGateService()
