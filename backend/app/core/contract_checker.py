"""
契约检查模块

在测试运行前验证代码是否满足测试文件的 import 需求
实现"前置契约检查"，实现快速失败（fail-fast）
"""

import ast
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

from app.utils.ast_utils import extract_return_keys_from_function

logger = logging.getLogger(__name__)


class ContractViolationError(Exception):
    """契约违反错误"""

    def __init__(self, message: str, missing_symbols: List[str] = None):
        super().__init__(message)
        self.missing_symbols = missing_symbols or []


def extract_defined_symbols(content: str, file_path: str = "<unknown>") -> Set[str]:
    """
    从 Python 代码中提取定义的符号（函数、类、模块级变量、重导出符号）

    Args:
        content: Python 源代码
        file_path: 文件路径（用于错误日志）

    Returns:
        定义的符号名称集合
    """
    defined = set()

    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        # 提取语法错误附近的代码片段，帮助定位问题
        error_line = e.lineno or 0
        lines = content.splitlines()
        context_start = max(0, error_line - 3)
        context_end = min(len(lines), error_line + 2)
        context_lines = lines[context_start:context_end]
        
        context_str = "\n".join([
            f"  {context_start + i + 1:4d} | {line}"
            for i, line in enumerate(context_lines)
        ])
        
        logger.error(
            f"【语法错误】{file_path}: {e}\n"
            f"错误位置（第 {error_line} 行附近）:\n{context_str}\n"
            f"提示: 代码存在语法错误，无法提取符号进行契约检查"
        )
        return defined

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # 跳过私有函数（以下划线开头）
            if not node.name.startswith("_"):
                defined.add(node.name)
        elif isinstance(node, ast.ClassDef):
            # 跳过私有类
            if not node.name.startswith("_"):
                defined.add(node.name)
        elif isinstance(node, ast.Assign):
            # 模块级变量赋值（如 router = APIRouter()）
            for target in node.targets:
                if isinstance(target, ast.Name):
                    # 跳过私有变量和单下划线变量
                    # ast.Name 使用 id 属性而非 name
                    if not target.id.startswith("_"):
                        defined.add(target.id)
        # ===== 增加对带类型注解变量的支持 =====
        elif isinstance(node, ast.AnnAssign):
            # 如 calculator_router: APIRouter = APIRouter()
            if isinstance(node.target, ast.Name):
                if not node.target.id.startswith("_"):
                    defined.add(node.target.id)
        # ========== 新增部分：处理重导出 ==========
        elif isinstance(node, ast.ImportFrom):
            # 处理 from X import Y 中的 Y（重导出符号）
            for alias in node.names:
                # 只添加非下划线开头的符号
                if not alias.name.startswith("_"):
                    defined.add(alias.name)
        elif isinstance(node, ast.Import):
            # 处理 import xxx 的情况，将整个模块名加入
            for alias in node.names:
                if not alias.name.startswith("_"):
                    defined.add(alias.name.split('.')[0])  # 只加顶级名
        # =========================================

    return defined


def extract_defined_symbols_with_types(content: str, file_path: str = "<unknown>") -> Dict[str, str]:
    """
    【改进】从 Python 代码中提取定义的符号及其类型
    
    类型包括：
    - "module_level_function": 模块级函数
    - "class": 类定义
    - "static_method": 静态方法（必须通过类名调用）
    - "class_method": 类方法（必须通过类名调用）
    - "instance_method": 实例方法（必须通过实例调用）
    - "variable": 模块级变量
    - "reexport": 重导出的符号

    Args:
        content: Python 源代码
        file_path: 文件路径（用于错误日志）

    Returns:
        符号名称到类型的映射
    """
    symbols = {}
    current_class = None
    
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return symbols
    
    for node in ast.walk(tree):
        # 检测类定义
        if isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                symbols[node.name] = "class"
                current_class = node.name
                
                # 检测类内部的方法
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_name = item.name
                        if method_name.startswith("_"):
                            continue
                            
                        # 检测装饰器
                        decorators = [d.id if isinstance(d, ast.Name) else 
                                     d.attr if isinstance(d, ast.Attribute) else ""
                                     for d in item.decorator_list]
                        
                        if "staticmethod" in decorators:
                            symbols[f"{current_class}.{method_name}"] = "static_method"
                        elif "classmethod" in decorators:
                            symbols[f"{current_class}.{method_name}"] = "class_method"
                        else:
                            symbols[f"{current_class}.{method_name}"] = "instance_method"
        
        # 检测模块级函数
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                symbols[node.name] = "module_level_function"
        
        # 检测模块级变量赋值
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    symbols[target.id] = "variable"
        # ===== 增加对带类型注解变量的支持 =====
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
                symbols[node.target.id] = "variable"

        # 检测重导出
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if not alias.name.startswith("_"):
                    symbols[alias.name] = "reexport"
        
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("_"):
                    top_name = alias.name.split('.')[0]
                    symbols[top_name] = "module"
    
    return symbols


def extract_imported_symbols(content: str) -> Dict[str, Set[str]]:
    """
    从 Python 代码中提取导入的符号

    Args:
        content: Python 源代码

    Returns:
        模块到符号集合的映射，如 {"app.api.v1.health": {"check_status"}}
    """
    imports = {}

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module not in imports:
                imports[module] = set()

            for alias in node.names:
                # 跳过通配符导入
                if alias.name != "*":
                    imports[module].add(alias.name)

    return imports


def verify_contract(
    code_files: Dict[str, str],
    specs: List[Dict[str, Any]]
) -> List[str]:
    """
    验证代码是否满足接口契约

    Args:
        code_files: 文件路径到内容的映射
        specs: 接口规范列表，每项包含 symbol_name, module 等

    Returns:
        缺失的符号列表，如果为空则表示契约满足
    """
    missing = []

    for spec in specs:
        module_path = spec.get("module", "")
        symbol_name = spec.get("symbol_name", "")

        if not module_path or not symbol_name:
            continue

        # 确保模块路径以 .py 结尾
        file_path = module_path
        if not file_path.endswith(".py"):
            file_path += ".py"

        # 尝试多种路径格式匹配
        # 因为 code_files 的键可能包含 backend/ 前缀或不包含
        # 同时处理 spec 中的 module 可能带或不带 backend/ 前缀的情况
        possible_paths = [
            file_path,                          # 原始路径: app/api/v1/health.py
            f"backend/{file_path}",             # 添加 backend/ 前缀: backend/app/api/v1/health.py
        ]
        
        # 如果 file_path 已经有 backend/ 前缀，也尝试不带前缀的
        if file_path.startswith("backend/"):
            possible_paths.append(file_path[8:])  # 移除 backend/ 前缀

        content = None
        matched_path = None
        for path in possible_paths:
            content = code_files.get(path)
            if content is not None:
                matched_path = path
                break

        if content is None:
            missing.append(f"{symbol_name} in {module_path} (file missing)")
            continue

        # 提取定义的符号（传入文件路径用于错误日志）
        defined_symbols = extract_defined_symbols(content, matched_path or file_path)

        if symbol_name not in defined_symbols:
            missing.append(f"{symbol_name} in {module_path}")

    return missing


def verify_test_imports(
    test_content: str,
    code_files: Dict[str, str],
    interface_specs: List[Dict[str, Any]]
) -> List[str]:
    """
    验证测试文件的导入是否在契约范围内

    Args:
        test_content: 测试文件内容
        code_files: 源代码文件映射
        interface_specs: 接口规范列表

    Returns:
        违规导入的符号列表
    """
    # 构建允许的符号集合
    allowed_symbols: Set[str] = set()
    for spec in interface_specs:
        allowed_symbols.add(spec.get("symbol_name", ""))

    # 提取测试文件的导入
    imports = extract_imported_symbols(test_content)

    violations = []

    for module, symbols in imports.items():
        # 只检查从 app 包导入的符号
        if module.startswith("app."):
            for symbol in symbols:
                if symbol not in allowed_symbols:
                    violations.append(f"{symbol} from {module}")

    return violations


def verify_return_fields_consistency(
    code_files: Dict[str, str],
    interface_specs: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    【跨文件一致性检查】验证代码中的返回字段与契约是否一致
    
    检查函数实际返回的字典键名是否包含契约要求的所有 return_fields。
    
    Args:
        code_files: 代码文件映射 {file_path: content}
        interface_specs: 接口契约列表
        
    Returns:
        不一致的错误列表
    """
    mismatches = []
    
    for spec in interface_specs:
        symbol_name = spec.get("symbol_name", "")
        return_fields = spec.get("return_fields", [])
        
        if not symbol_name or not return_fields:
            continue
        
        # 提取契约要求的键名
        required_keys = set()
        for field in return_fields:
            field_name = field.get("name", "") if isinstance(field, dict) else getattr(field, "name", "")
            if field_name:
                required_keys.add(field_name)
        
        if not required_keys:
            continue
        
        # 在所有代码文件中查找该函数
        found = False
        for file_path, content in code_files.items():
            try:
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.name == symbol_name:
                            found = True
                            actual_keys = extract_return_keys_from_function(node)
                            
                            if actual_keys:
                                missing_keys = required_keys - actual_keys
                                if missing_keys:
                                    mismatches.append({
                                        "symbol": symbol_name,
                                        "file": file_path,
                                        "error": "返回字段与契约不一致",
                                        "missing_keys": list(missing_keys),
                                        "required_keys": list(required_keys),
                                        "actual_keys": list(actual_keys)
                                    })
                            break
                
                if found:
                    break
                    
            except SyntaxError:
                logger.warning(f"[ContractChecker] 无法解析文件进行返回字段检查: {file_path}")
                continue
    
    return mismatches


def check_contract_before_test(
    design_output: Dict[str, Any],
    code_files: Dict[str, str],
    test_files: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    测试运行前的契约检查（快速失败）

    Args:
        design_output: DesignerAgent 的输出，包含 interface_specs
        code_files: 生成的代码文件映射
        test_files: 生成的测试文件映射（可选）

    Returns:
        检查结果，包含 success 和 violations
    """
    interface_specs = design_output.get("interface_specs", [])

    if not interface_specs:
        logger.warning("没有接口契约规范，跳过契约检查")
        return {"success": True, "violations": []}

    logger.info(f"开始契约检查，共 {len(interface_specs)} 个接口规范")

    # 1. 检查代码是否实现了所有契约符号
    missing = verify_contract(code_files, interface_specs)

    if missing:
        logger.error(f"契约违反: 缺少 {len(missing)} 个必需符号")
        for m in missing:
            logger.error(f"  - {m}")

        return {
            "success": False,
            "violations": missing,
            "type": "missing_implementation"
        }

    # 2. 【新增】检查返回字段与契约的一致性（跨文件一致性检查）
    return_field_mismatches = verify_return_fields_consistency(code_files, interface_specs)
    if return_field_mismatches:
        logger.error(f"契约违反: 发现 {len(return_field_mismatches)} 个返回字段不一致")
        for mismatch in return_field_mismatches:
            logger.error(
                f"  - {mismatch['symbol']} in {mismatch['file']}: "
                f"缺少键 {mismatch['missing_keys']}"
            )
        
        violations = [
            f"{m['symbol']} in {m['file']}: 缺少返回键 {m['missing_keys']} "
            f"(契约要求: {m['required_keys']}, 实际: {m['actual_keys']})"
            for m in return_field_mismatches
        ]
        
        return {
            "success": False,
            "violations": violations,
            "type": "return_field_mismatch",
            "details": return_field_mismatches
        }

    # 3. 检查测试文件是否只导入了契约内的符号
    if test_files:
        test_violations = []
        for test_path, test_content in test_files.items():
            violations = verify_test_imports(test_content, code_files, interface_specs)
            if violations:
                test_violations.extend([
                    f"{v} (in {test_path})" for v in violations
                ])

        if test_violations:
            logger.error(f"契约违反: 测试文件导入了未定义的符号")
            for v in test_violations:
                logger.error(f"  - {v}")

            return {
                "success": False,
                "violations": test_violations,
                "type": "test_import_violation"
            }

    logger.info("契约检查通过")
    return {"success": True, "violations": []}

