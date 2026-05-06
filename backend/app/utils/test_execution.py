"""
测试执行工具函数

提供统一的测试执行功能，供 E2E 测试脚本和 Pipeline 处理器共同使用
"""

import logging
import re
from typing import Any, Dict, List, Optional, Callable

from app.service.sandbox_manager import sandbox_manager

logger = logging.getLogger(__name__)


async def run_pytest_in_sandbox(
    pipeline_id: int,
    test_path: str,
    timeout: int = 120,
    extra_args: str = "-v --tb=short --color=no",
    log_callback: Optional[Callable[[str, str], Any]] = None
) -> Dict[str, Any]:
    """
    在沙箱中运行 pytest

    Args:
        pipeline_id: Pipeline ID
        test_path: 测试路径（可以是文件或目录）
        timeout: 超时时间（秒）
        extra_args: pytest 额外参数
        log_callback: 日志回调函数 (level, message) -> None

    Returns:
        Dict with success, logs, failed_tests, exit_code
    """
    def log(level: str, message: str):
        if log_callback:
            log_callback(level, message)
        else:
            getattr(logger, level.lower(), logger.info)(message)

    log("info", f"🧪 运行 pytest: {test_path}")

    try:
        exec_result = await sandbox_manager.exec(
            pipeline_id,
            f"cd /workspace && PYTHONPATH=/workspace/backend python -m pytest {test_path} {extra_args} 2>&1",
            timeout=timeout
        )

        logs = exec_result.stdout + "\n" + exec_result.stderr
        success = exec_result.exit_code == 0

        # 提取失败的测试 (FAILED)
        failed_tests = re.findall(r'FAILED\s+(\S+)', logs)
        # 提取错误的测试 (ERROR - 如导入错误、收集错误等)
        error_tests = re.findall(r'ERROR\s+(\S+)', logs)
        # 提取错误数量
        errors_match = re.search(r'(\d+)\s+error', logs, re.IGNORECASE)
        errors_count = int(errors_match.group(1)) if errors_match else len(error_tests)
        # 提取通过数量
        passed_match = re.search(r'(\d+)\s+passed', logs, re.IGNORECASE)
        passed_count = int(passed_match.group(1)) if passed_match else 0
        # 提取收集到的测试数量
        collected_match = re.search(r'collected\s+(\d+)\s+item', logs)
        collected_count = int(collected_match.group(1)) if collected_match else 0

        if success:
            log("info", f"✅ 测试通过 ({passed_count} passed)")
        else:
            # 详细显示失败原因
            if failed_tests and errors_count > 0:
                log("warning", f"❌ 测试失败: {len(failed_tests)} 个失败, {errors_count} 个错误")
            elif failed_tests:
                log("warning", f"❌ 测试失败: {len(failed_tests)} 个失败")
            elif errors_count > 0:
                log("warning", f"❌ 测试错误: {errors_count} 个错误 (可能是导入/收集失败)")
            elif collected_count == 0:
                log("warning", f"❌ 未收集到任何测试 (路径可能错误)")
            else:
                log("warning", f"❌ 测试失败: 退出码 {exec_result.exit_code}")

            # 【新增】打印详细的测试日志，便于调试
            log("warning", "=" * 60)
            log("warning", "【测试失败详情 - 开始】")
            log("warning", "=" * 60)
            # 限制日志长度，避免输出过多
            max_log_length = 3000
            if len(logs) > max_log_length:
                log("warning", logs[:max_log_length] + "\n... (日志已截断)")
            else:
                log("warning", logs)
            log("warning", "=" * 60)
            log("warning", "【测试失败详情 - 结束】")
            log("warning", "=" * 60)

        return {
            "success": success,
            "logs": logs,
            "failed_tests": failed_tests,
            "error_tests": error_tests,
            "exit_code": exec_result.exit_code,
            "passed_count": passed_count,
            "errors_count": errors_count,
            "collected_count": collected_count,
            "error": None if success else f"{len(failed_tests)} failed, {errors_count} errors, {passed_count} passed"
        }

    except Exception as e:
        log("error", f"❌ 测试执行异常: {str(e)}")
        return {
            "success": False,
            "logs": str(e),
            "failed_tests": [],
            "exit_code": -1,
            "error": str(e)
        }


async def run_preliminary_test(
    pipeline_id: int,
    test_files: List[Dict],
    file_service,
    timeout: int = 120,
    log_callback: Optional[Callable[[str, str], Any]] = None
) -> Dict[str, Any]:
    """
    运行预测试：快速验证新生成的测试文件

    Args:
        pipeline_id: Pipeline ID
        test_files: 测试文件列表
        file_service: 文件服务
        timeout: 超时时间
        log_callback: 日志回调函数

    Returns:
        Dict with success, logs, failed_tests, error
    """
    def log(level: str, message: str):
        if log_callback:
            log_callback(level, message)
        else:
            getattr(logger, level.lower(), logger.info)(message)

    log("info", "🧪 运行预测试（快速验证新测试文件）...")

    if not test_files:
        return {"success": True, "logs": "", "failed_tests": [], "error": None}

    # 构建测试路径
    test_paths = []
    for tf in test_files:
        fp = tf.get("file_path", "")
        if fp:
            if "tests/ai_generated" in fp:
                clean_path = fp
            else:
                filename = fp.split("/")[-1]
                clean_path = f"backend/tests/ai_generated/{filename}"
            test_paths.append(clean_path)

    if not test_paths:
        return {"success": True, "logs": "", "failed_tests": [], "error": None}

    test_path_str = " ".join(test_paths)

    return await run_pytest_in_sandbox(
        pipeline_id=pipeline_id,
        test_path=test_path_str,
        timeout=timeout,
        log_callback=log_callback
    )


def analyze_test_failure(logs: Optional[str]) -> Dict[str, Any]:
    """
    分析测试失败原因，判断是测试文件问题还是代码问题

    Args:
        logs: 测试日志

    Returns:
        Dict with is_test_file_error, error_type, error_detail, suggestion
    """
    if not logs:
        return {
            "is_test_file_error": False,
            "error_type": "unknown",
            "error_detail": "无日志输出",
            "suggestion": "查看详细日志"
        }

    # 测试文件语法错误
    if "SyntaxError" in logs:
        file_match = re.search(r'File "([^"]*test_[^"]+)"', logs)
        if file_match:
            return {
                "is_test_file_error": True,
                "error_type": "test_syntax_error",
                "error_detail": f"测试文件语法错误: {file_match.group(1)}",
                "suggestion": "重新生成测试文件"
            }

    # 测试文件导入错误
    if "ImportError" in logs or "ModuleNotFoundError" in logs:
        file_match = re.search(r'File "([^"]*test_[^"]+)"', logs)
        if file_match:
            return {
                "is_test_file_error": True,
                "error_type": "test_import_error",
                "error_detail": f"测试文件导入错误: {file_match.group(1)}",
                "suggestion": "修正测试文件的 import 语句"
            }

    # 测试收集错误
    if "collection error" in logs.lower() or "ImportError while loading" in logs:
        return {
            "is_test_file_error": True,
            "error_type": "test_collection_error",
            "error_detail": "测试收集失败",
            "suggestion": "检查测试文件结构"
        }

    # 普通测试失败（可能是代码问题或测试逻辑问题）
    if "FAILED" in logs or "AssertionError" in logs:
        return {
            "is_test_file_error": False,
            "error_type": "test_assertion_failure",
            "error_detail": "测试断言失败",
            "suggestion": "检查代码实现或测试逻辑"
        }

    return {
        "is_test_file_error": False,
        "error_type": "unknown",
        "error_detail": "未知错误",
        "suggestion": "查看详细日志"
    }
