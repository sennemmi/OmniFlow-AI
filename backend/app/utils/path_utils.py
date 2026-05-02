"""
文件路径标准化工具模块

统一处理文件路径的标准化，避免在多个地方重复相同的路径处理逻辑。
"""

import os
import re
from pathlib import Path
from typing import Optional


def normalize_relative_path(file_path: str, remove_backend_prefix: bool = True) -> str:
    """
    标准化相对路径

    统一处理：
    1. 移除 backend/ 或 backend\\ 前缀
    2. 统一使用正斜杠 /
    3. 去除首尾的斜杠
    4. 处理 Windows 反斜杠

    Args:
        file_path: 原始文件路径
        remove_backend_prefix: 是否移除 backend/ 前缀（默认 True）

    Returns:
        str: 标准化后的路径

    Examples:
        >>> normalize_relative_path("backend/app/main.py")
        'app/main.py'
        >>> normalize_relative_path("backend\\app\\main.py")
        'app/main.py'
        >>> normalize_relative_path("/backend/app/main.py")
        'app/main.py'
        >>> normalize_relative_path("app/main.py")
        'app/main.py'
    """
    if not file_path:
        return ""

    # 统一使用正斜杠
    path = file_path.replace("\\", "/")

    # 移除 backend/ 前缀（如果启用）
    if remove_backend_prefix:
        # 匹配开头或 / 后的 backend/
        path = re.sub(r'^(/?)backend/', '', path)

    # 去除首尾的斜杠
    path = path.strip("/")

    return path


def normalize_absolute_path(file_path: str) -> str:
    """
    标准化绝对路径

    统一使用正斜杠，并去除冗余的斜杠。

    Args:
        file_path: 原始文件路径

    Returns:
        str: 标准化后的绝对路径
    """
    if not file_path:
        return ""

    # 统一使用正斜杠
    path = file_path.replace("\\", "/")

    # 去除重复的斜杠（保留协议部分如 http://）
    path = re.sub(r'(?<!:)/+', '/', path)

    return path


def ensure_backend_prefix(file_path: str) -> str:
    """
    确保路径包含 backend/ 前缀

    如果路径不以 backend/ 开头，则添加。

    Args:
        file_path: 原始文件路径

    Returns:
        str: 带 backend/ 前缀的路径

    Examples:
        >>> ensure_backend_prefix("app/main.py")
        'backend/app/main.py'
        >>> ensure_backend_prefix("backend/app/main.py")
        'backend/app/main.py'
    """
    if not file_path:
        return ""

    normalized = normalize_relative_path(file_path, remove_backend_prefix=True)

    if normalized.startswith("backend/"):
        return normalized

    return f"backend/{normalized}"


def get_file_extension(file_path: str) -> str:
    """
    获取文件扩展名

    Args:
        file_path: 文件路径

    Returns:
        str: 扩展名（包含点，如 .py），如果没有则返回空字符串
    """
    return Path(file_path).suffix


def is_python_file(file_path: str) -> bool:
    """
    检查是否为 Python 文件

    Args:
        file_path: 文件路径

    Returns:
        bool: 是否为 .py 文件
    """
    return get_file_extension(file_path).lower() == ".py"


def is_test_file(file_path: str) -> bool:
    """
    检查是否为测试文件

    检查文件名是否包含 test 或路径中包含 tests/

    Args:
        file_path: 文件路径

    Returns:
        bool: 是否为测试文件
    """
    normalized = normalize_relative_path(file_path)
    return "test" in normalized.lower() or normalized.startswith("tests/")


def join_paths(*paths: str) -> str:
    """
    安全地连接多个路径部分

    使用正斜杠连接，避免双斜杠问题。

    Args:
        *paths: 路径部分

    Returns:
        str: 连接后的路径

    Examples:
        >>> join_paths("app", "utils", "helper.py")
        'app/utils/helper.py'
        >>> join_paths("app/", "utils", "/helper.py")
        'app/utils/helper.py'
    """
    # 标准化每个部分
    normalized_parts = []
    for i, path in enumerate(paths):
        if not path:
            continue
        part = path.replace("\\", "/").strip("/")
        if part:
            normalized_parts.append(part)

    return "/".join(normalized_parts)


def get_relative_to_project(file_path: str, project_root: Optional[str] = None) -> str:
    """
    获取相对于项目根目录的路径

    Args:
        file_path: 完整文件路径
        project_root: 项目根目录（可选，默认为当前工作目录）

    Returns:
        str: 相对路径
    """
    if project_root is None:
        project_root = os.getcwd()

    try:
        rel_path = os.path.relpath(file_path, project_root)
        return normalize_relative_path(rel_path)
    except ValueError:
        # Windows 上不同驱动器的问题
        return normalize_relative_path(file_path)


# 向后兼容的别名
normalize_path = normalize_relative_path
