"""
AST 工具函数

提供跨模块共享的 AST 解析工具，包括：
- 从函数定义提取返回字典键名
- 从 AST 值节点提取字典键名
- 从 AST 键节点提取键名字符串
"""

import ast
from typing import Set, Optional


def extract_return_keys_from_function(func_node: ast.FunctionDef) -> Set[str]:
    """
    从函数定义中提取所有可能的返回字典键名

    处理场景：
    1. 直接返回字典：return {"key": value}
    2. 返回变量：return result（跟踪变量赋值）
    3. 条件返回：if x: return {"a": 1} else: return {"b": 2}
    4. 合并字典：return {**dict1, **dict2}
    5. 返回 dict() 调用

    Args:
        func_node: AST 函数定义节点

    Returns:
        set: 所有可能的返回键名
    """
    actual_keys = set()
    local_vars = {}

    # 首先收集所有局部变量赋值
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    if isinstance(node.value, ast.Dict):
                        local_vars[var_name] = node.value
                    elif isinstance(node.value, ast.Call):
                        local_vars[var_name] = node.value
                    elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.BitOr):
                        local_vars[var_name] = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                var_name = node.target.id
                if isinstance(node.value, ast.Dict):
                    local_vars[var_name] = node.value
                elif isinstance(node.value, ast.Call):
                    local_vars[var_name] = node.value
                elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.BitOr):
                    local_vars[var_name] = node.value

    # 然后分析所有 return 语句
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return) and node.value:
            keys = extract_keys_from_value(node.value, local_vars)
            actual_keys.update(keys)

    return actual_keys


def extract_keys_from_value(value_node: ast.AST, local_vars: dict) -> Set[str]:
    """
    从 AST 值节点中提取字典键名

    Args:
        value_node: AST 值节点
        local_vars: 局部变量字典（变量名 -> AST 节点）

    Returns:
        set: 提取的键名
    """
    keys = set()

    # 情况 1: 直接返回字典
    if isinstance(value_node, ast.Dict):
        for key in value_node.keys:
            key_name = get_key_name(key)
            if key_name:
                keys.add(key_name)

    # 情况 2: 返回变量，尝试解析变量
    elif isinstance(value_node, ast.Name):
        var_name = value_node.id
        if var_name in local_vars:
            keys.update(extract_keys_from_value(local_vars[var_name], {}))

    # 情况 3: 返回字典合并操作 {**a, **b}
    elif isinstance(value_node, ast.BinOp) and isinstance(value_node.op, ast.BitOr):
        keys.update(extract_keys_from_value(value_node.left, local_vars))
        keys.update(extract_keys_from_value(value_node.right, local_vars))

    # 情况 4: 返回函数调用
    elif isinstance(value_node, ast.Call):
        if isinstance(value_node.func, ast.Name) and value_node.func.id == 'dict':
            for kw in value_node.keywords:
                keys.add(kw.arg)
            for arg in value_node.args:
                if isinstance(arg, (ast.List, ast.Tuple)):
                    for elt in arg.elts:
                        if isinstance(elt, (ast.List, ast.Tuple)) and len(elt.elts) >= 1:
                            key_name = get_key_name(elt.elts[0])
                            if key_name:
                                keys.add(key_name)

    # 情况 5: 返回条件表达式
    elif isinstance(value_node, ast.IfExp):
        keys.update(extract_keys_from_value(value_node.body, local_vars))
        keys.update(extract_keys_from_value(value_node.orelse, local_vars))

    return keys


def get_key_name(key_node: ast.AST) -> Optional[str]:
    """
    从 AST 键节点中提取键名字符串

    兼容 Python 3.8+ (ast.Constant) 和 Python < 3.8 (ast.Str)

    Args:
        key_node: AST 键节点

    Returns:
        str: 键名，如果无法提取则返回 None
    """
    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
        return key_node.value
    elif isinstance(key_node, ast.Str):  # Python < 3.8
        return key_node.s
    return None
