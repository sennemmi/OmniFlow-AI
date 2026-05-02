"""
Repairer 工具函数

提供构建修复工单、收集目标文件等功能
"""

import ast
import re
from typing import Any, Dict, List, Optional, Set

from app.service.sandbox_file_service import SandboxFileService
from app.utils.file_operation_utils import clean_backend_prefix


# 核心契约文件映射表（用于 import 关联提取）
CORE_CONTRACT_MODULES = {
    "app.core.response": "app/core/response.py",
    "app.core.database": "app/core/database.py",
    "app.core.config": "app/core/config.py",
    "app.core.security": "app/core/security.py",
}


def extract_pytest_failures(logs: Optional[str], max_chars: int = 5000) -> str:
    """
    从 pytest 日志中提取 FAILURES 部分

    Args:
        logs: pytest 日志
        max_chars: 最大字符数（当无法提取 FAILURES 时）

    Returns:
        提取的错误内容
    """
    # 确保 logs 是字符串
    if not logs:
        return ""

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
    logs: Optional[str],
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


def extract_critical_files(logs: str, all_generated_paths: List[str]) -> List[str]:
    """
    【全量收集 + 智能过滤】从报错日志中提取关键文件

    策略：
    1. 全量收集：扫描日志中所有可能的 Python 文件路径
    2. 智能过滤：只保留包含 'app/' 或 'tests/' 的业务相关文件
    3. 强制注入：地基文件（response.py, database.py）
    """
    critical_files = set()

    # 1. 【地基】强制注入核心契约文件
    CORE_CONTRACTS = [
        "app/core/response.py",
        "app/core/database.py",
    ]
    critical_files.update(CORE_CONTRACTS)

    # 2. 【全量收集】扫描所有可能的 Python 文件路径
    # 匹配：/workspace/backend/app/service/health_service.py
    # 匹配：backend/app/service/health_service.py
    # 匹配：app/service/health_service.py
    all_paths = re.findall(r'(/[\w/.-]+\.py)', logs)

    # 3. 【智能过滤】只保留业务相关文件
    for p in all_paths:
        # 清理路径，适配项目结构
        clean_p = p.split('backend/')[-1] if 'backend/' in p else p
        clean_p = clean_p.lstrip('/')

        # 只保留包含 'app/' 或 'tests/' 的文件
        if 'app/' in clean_p or 'tests/' in clean_p:
            critical_files.add(clean_p)

    # 4. 额外提取：FAILED 行中的测试文件（备用方案）
    failed_matches = re.findall(r"FAILED ([\w/.-]+)::", logs)
    for f in failed_matches:
        clean_f = f.replace("backend/", "").lstrip("/")
        if 'tests/' in clean_f:
            critical_files.add(clean_f)

    # 5. 确保 all_generated_paths 中的文件也被包含
    for gen_path in all_generated_paths:
        clean_path = gen_path.replace("backend/", "").lstrip("/")
        if clean_path not in critical_files:
            critical_files.add(clean_path)

    return list(critical_files)[:8]  # 放宽到最多8个文件


def parse_local_imports(file_content: str, file_path: str) -> Set[str]:
    """
    解析 Python 文件内容，提取本地项目 import 的核心契约文件

    Args:
        file_content: 文件内容
        file_path: 文件路径（用于相对路径计算）

    Returns:
        被 import 的核心契约文件路径集合
    """
    imported_core_files: Set[str] = set()

    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        return imported_core_files

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module
            if not module:
                continue

            # 检查是否 import 了核心契约模块（支持前缀匹配）
            for core_module, core_path in CORE_CONTRACT_MODULES.items():
                if module == core_module or module.startswith(core_module + "."):
                    imported_core_files.add(core_path)

    return imported_core_files


def parse_all_app_imports(file_content: str) -> Set[str]:
    """
    【主动探索】解析文件中所有 from app.xxx import 的模块路径

    用于 RepairerAgent 上下文收集，确保测试文件引用的所有 app/* 模块都被包含。

    Args:
        file_content: Python 文件内容

    Returns:
        被 import 的 app.* 模块路径集合（如 {"app.service.health_service", "app.utils.system_monitor"}）
    """
    imported_modules: Set[str] = set()

    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        return imported_modules

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module
            if not module:
                continue

            # 只收集 app.* 模块
            if module.startswith("app."):
                imported_modules.add(module)

    return imported_modules


def module_to_file_path(module_path: str) -> str:
    """
    将 Python 模块路径转换为文件路径

    Args:
        module_path: 模块路径（如 "app.service.health_service"）

    Returns:
        文件路径（如 "app/service/health_service.py"）
    """
    return module_path.replace(".", "/") + ".py"


async def extract_critical_files_with_imports_recursive(
    logs: str,
    all_generated_paths: List[str],
    file_contents: Dict[str, str],
    file_service,
    max_depth: int = 2
) -> List[str]:
    """
    【P2】增强版：递归解析 Import 关联路径（深度2）

    1. 确定性提取：从 Traceback 提取所有提到的 app/*.py 和 tests/*.py
    2. 关联性提取（递归深度2）：
       - 第1层：解析关键文件的 import
       - 第2层：解析被 import 文件的 import

    Args:
        logs: 错误日志
        all_generated_paths: 所有生成的文件路径
        file_contents: 文件内容映射
        file_service: 文件服务（用于读取依赖文件）
        max_depth: 最大递归深度（默认2）
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[RepairUtils] 【P2】启动递归上下文收集，最大深度: {max_depth}")
    
    # 第1步：确定性提取（从 Traceback）
    essential_paths = set(extract_critical_files(logs, all_generated_paths))
    logger.info(f"[RepairUtils] 【P2】从 Traceback 提取 {len(essential_paths)} 个关键文件")
    for p in essential_paths:
        logger.debug(f"[RepairUtils] 【P2】  - {p}")
    
    all_discovered = set(essential_paths)
    
    # 准备已知的文件内容
    known_contents = dict(file_contents)
    
    # 递归解析 import
    current_depth = 0
    current_paths = list(essential_paths)
    
    while current_depth < max_depth and current_paths:
        logger.info(f"[RepairUtils] 【P2】第 {current_depth + 1} 层递归，处理 {len(current_paths)} 个文件")
        next_paths = []
        
        for path in current_paths:
            content = known_contents.get(path, "")
            
            # 如果内容未知，尝试读取
            if not content and file_service:
                try:
                    read_res = await file_service.read_file(path)
                    if read_res.exists and read_res.content:
                        content = read_res.content
                        known_contents[path] = content
                        logger.debug(f"[RepairUtils] 【P2】从沙箱读取文件: {path} ({len(content)} 字符)")
                except Exception as e:
                    logger.debug(f"[RepairUtils] 【P2】无法读取文件 {path}: {e}")
                    continue
            
            if not content:
                continue
            
            # 【P2】解析所有 app.* import（不只是核心契约）
            imported_modules = parse_all_app_imports(content)
            
            if imported_modules:
                logger.debug(f"[RepairUtils] 【P2】{path} 导入 {len(imported_modules)} 个模块: {list(imported_modules)[:5]}")
            
            for module in imported_modules:
                dep_file_path = module_to_file_path(module)
                
                if dep_file_path not in all_discovered:
                    all_discovered.add(dep_file_path)
                    next_paths.append(dep_file_path)
                    logger.debug(f"[RepairUtils] 【P2】发现新依赖: {dep_file_path} (来自 {path})")
                    
                    # 尝试读取该文件内容（为下一轮递归做准备）
                    if file_service and dep_file_path not in known_contents:
                        try:
                            read_res = await file_service.read_file(dep_file_path)
                            if read_res.exists and read_res.content:
                                known_contents[dep_file_path] = read_res.content
                        except Exception:
                            pass
        
        logger.info(f"[RepairUtils] 【P2】第 {current_depth + 1} 层发现 {len(next_paths)} 个新文件")
        current_paths = next_paths
        current_depth += 1
    
    # 确保核心契约文件始终被包含
    core_contracts = [
        "app/core/response.py",
        "app/core/database.py",
        "app/core/config.py",
        "app/core/security.py",
    ]
    for core in core_contracts:
        if core not in all_discovered:
            all_discovered.add(core)
            logger.debug(f"[RepairUtils] 【P2】强制添加核心契约文件: {core}")
    
    final_list = list(all_discovered)[:15]  # 放宽到最多15个文件
    logger.info(f"[RepairUtils] 【P2】递归上下文收集完成，共 {len(final_list)} 个文件")
    for p in final_list[:10]:  # 只显示前10个避免日志过长
        logger.debug(f"[RepairUtils] 【P2】  - {p}")
    if len(final_list) > 10:
        logger.debug(f"[RepairUtils] 【P2】  ... 还有 {len(final_list) - 10} 个文件")
    
    return final_list


def extract_critical_files_with_imports(
    logs: str,
    all_generated_paths: List[str],
    file_contents: Dict[str, str]
) -> List[str]:
    """
    【Traceback 路径 + Import 关联路径】组合策略（非递归版本，向后兼容）

    1. 确定性提取：从 Traceback 提取所有提到的 app/*.py 和 tests/*.py
    2. 关联性提取：解析这些文件的 import，将引用的核心契约文件也加入
    """
    # 第1步：确定性提取（从 Traceback）
    essential_paths = set(extract_critical_files(logs, all_generated_paths))

    # 第2步：关联性提取（解析 import）
    for path in list(essential_paths):
        content = file_contents.get(path, "")
        if not content:
            continue

        # 解析该文件 import 了哪些核心库
        imported_cores = parse_local_imports(content, path)

        # 将被 import 的核心文件加入上下文
        for core_file in imported_cores:
            if core_file not in essential_paths:
                essential_paths.add(core_file)

    return list(essential_paths)[:10]  # 放宽到最多10个文件
