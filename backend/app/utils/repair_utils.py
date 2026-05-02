"""
Repairer 工具函数

提供构建修复工单、收集目标文件等功能
"""

import re
from typing import Any, Dict, List, Optional

from app.service.sandbox_file_service import SandboxFileService
from app.utils.file_operation_utils import clean_backend_prefix


def extract_pytest_failures(logs: str, max_chars: int = 5000) -> str:
    """
    从 pytest 日志中提取 FAILURES 部分

    Args:
        logs: pytest 日志
        max_chars: 最大字符数（当无法提取 FAILURES 时）

    Returns:
        提取的错误内容
    """
    # 尝试提取 FAILURES 部分
    failures_match = re.search(
        r'=+\s*FAILURES\s*=+(.*?)(?:=+\s*short test summary info\s*=+|=+\s*\d+ failed|$)',
        logs,
        re.DOTALL
    )

    if failures_match:
        # 提取 FAILURES 部分 + 后面的 short test summary
        failures_section = failures_match.group(1)
        summary_match = re.search(
            r'=+\s*short test summary info\s*=+(.*?)(?:=+\s*\d+ failed|$)',
            logs,
            re.DOTALL
        )
        if summary_match:
            return failures_section + "\n" + summary_match.group(0)
        else:
            return failures_section
    else:
        # 回退到取日志后 max_chars 字符
        return logs[-max_chars:] if len(logs) > max_chars else logs


def build_fix_order(
    failed_tests: List[str],
    logs: str,
    generated_file_paths: List[str],
    missing_symbols: Optional[List[str]] = None,
    errors_list: Optional[List[Dict]] = None,
    target_file_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    构建修复工单

    Args:
        failed_tests: 失败的测试列表
        logs: 错误日志
        generated_file_paths: 生成的文件路径列表
        missing_symbols: 缺失的符号列表
        errors_list: 错误列表（如果提供，将优先使用）
        target_file_path: 目标文件路径（用于缺失符号错误，默认从 generated_file_paths 推断）

    Returns:
        修复工单字典
    """
    if errors_list is None:
        errors_list = []

    # 如果没有提供 errors_list 但有 missing_symbols，构建错误列表
    if not errors_list and missing_symbols:
        # 推断目标文件路径
        inferred_target = target_file_path
        if not inferred_target and generated_file_paths:
            # 优先找 api 目录下的文件
            api_files = [p for p in generated_file_paths if '/api/' in p or '\\api\\' in p]
            if api_files:
                inferred_target = api_files[0]
            else:
                # 找 service 目录下的文件
                service_files = [p for p in generated_file_paths if '/service/' in p or '\\service\\' in p]
                if service_files:
                    inferred_target = service_files[0]
                else:
                    inferred_target = generated_file_paths[0]

        if not inferred_target:
            raise ValueError(
                "无法推断目标文件路径：generated_file_paths 为空，"
                "且未提供 target_file_path 参数"
            )

        errors_list.append({
            "file_path": inferred_target,
            "line": 1,
            "severity": "critical",
            "summary": f"缺少必需的实现: {', '.join(missing_symbols)}",
            "detail": f"测试需要这些符号，但代码中未定义: {missing_symbols}",
            "fix_hint": f"请在 {inferred_target} 中实现以下函数: {', '.join(missing_symbols)}"
        })

    # 提取 pytest 错误内容
    error_content = extract_pytest_failures(logs)

    return {
        "type": "fix_order",
        "category": "code_bug",
        "source": "VerifyAgent",
        "errors": errors_list,
        "failed_tests": failed_tests,
        "error_logs": error_content,
        "error_snippet": error_content[:3000],
        "generated_files": generated_file_paths,
        "fix_hint": "重点：确保实现所有接口契约中声明的函数。可以修改测试文件或被测代码，根据错误类型判断。"
    }


def collect_target_files(
    all_generated_files: List[Dict],
    file_service: SandboxFileService,
    errors_list: Optional[List[Dict]] = None
) -> Dict[str, str]:
    """
    收集目标文件的完整内容

    Args:
        all_generated_files: 所有生成的文件列表
        file_service: 文件服务
        errors_list: 错误列表（用于收集涉及的文件）

    Returns:
        文件路径到内容的字典
    """
    target_files = {}

    # 从 all_generated_files 中提取文件内容
    for file_info in all_generated_files:
        file_path = file_info.get("file_path", "")
        content = file_info.get("content", "")
        if file_path and content:
            clean_path = clean_backend_prefix(file_path)
            target_files[clean_path] = content

    # 从沙箱读取最新内容（覆盖旧内容）
    files_to_read = set()
    for file_info in all_generated_files:
        fp = file_info.get("file_path", "")
        if fp:
            clean_fp = clean_backend_prefix(fp)
            files_to_read.add(clean_fp)

    # 添加错误列表中涉及的文件
    if errors_list:
        for err in errors_list:
            fp = err.get("file_path", "")
            if fp:
                clean_fp = clean_backend_prefix(fp)
                files_to_read.add(clean_fp)

    return target_files


async def collect_target_files_async(
    all_generated_files: List[Dict],
    file_service: SandboxFileService,
    errors_list: Optional[List[Dict]] = None
) -> Dict[str, str]:
    """
    异步收集目标文件的完整内容

    Args:
        all_generated_files: 所有生成的文件列表
        file_service: 文件服务
        errors_list: 错误列表（用于收集涉及的文件）

    Returns:
        文件路径到内容的字典
    """
    target_files = {}

    # 从 all_generated_files 中提取文件内容
    for file_info in all_generated_files:
        file_path = file_info.get("file_path", "")
        content = file_info.get("content", "")
        if file_path and content:
            clean_path = clean_backend_prefix(file_path)
            target_files[clean_path] = content

    # 从沙箱读取最新内容（覆盖旧内容）
    files_to_read = set()
    for file_info in all_generated_files:
        fp = file_info.get("file_path", "")
        if fp:
            clean_fp = clean_backend_prefix(fp)
            files_to_read.add(clean_fp)

    # 添加错误列表中涉及的文件
    if errors_list:
        for err in errors_list:
            fp = err.get("file_path", "")
            if fp:
                clean_fp = clean_backend_prefix(fp)
                files_to_read.add(clean_fp)

    # 从沙箱读取最新内容
    for clean_path in files_to_read:
        read_res = await file_service.read_file(clean_path)
        if read_res.exists and read_res.content:
            target_files[clean_path] = read_res.content

    return target_files


def extract_file_paths(all_generated_files: List[Dict]) -> List[str]:
    """
    从生成的文件列表中提取路径

    Args:
        all_generated_files: 所有生成的文件列表

    Returns:
        文件路径列表
    """
    file_paths = []
    for file_info in all_generated_files:
        fp = file_info.get("file_path", "")
        if fp:
            clean_fp = clean_backend_prefix(fp)
            file_paths.append(clean_fp)
    return file_paths


def print_fix_result(repair_result: Dict, output: Dict) -> None:
    """
    打印修复结果

    Args:
        repair_result: 修复结果
        output: 输出字典
    """
    if repair_result.get("success"):
        rounds = output.get("rounds", 1)
        print(f"   ✅ RepairerAgentWithTools 修复成功（共 {rounds} 轮）")
        if "files" in output:
            for fc in output["files"]:
                fp = fc.get("file_path", "")
                print(f"      📝 修复了: {fp}")
    else:
        rounds = output.get("rounds", 0)
        print(f"   ❌ RepairerAgentWithTools 修复失败（进行了 {rounds} 轮修复）: {repair_result.get('error')}")
