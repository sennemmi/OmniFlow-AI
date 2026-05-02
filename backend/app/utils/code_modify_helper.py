"""
代码修改工具模块 - 提供代码修改相关的公共工具函数

职责：
- 文件路径处理
- Diff 生成
- 代码变更应用
- 文件读取上下文

使用场景：
- code_modify.py
- code_modify_batch.py
- 其他需要代码修改功能的模块
"""

import difflib
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass

from app.core.config import get_workspace_path, process_file_path
from app.core.logging import error, info


@dataclass
class FileContextResult:
    """文件上下文读取结果"""
    content: str
    surrounding: str
    start_line: int
    end_line: int


@dataclass
class DiffResult:
    """Diff 生成结果"""
    diff: str
    original_content: str
    new_content: str


def generate_diff(original: str, new: str, file_path: str) -> str:
    """
    生成统一格式的 diff

    Args:
        original: 原始内容
        new: 新内容
        file_path: 文件路径（用于 diff 头部）

    Returns:
        str: unified diff 格式字符串
    """
    original_lines = original.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm=""
    )

    return "".join(diff)


def read_file_context(
    file_path: str,
    target_line: int,
    context_lines: int = 20,
    workspace: Optional[Path] = None
) -> FileContextResult:
    """
    读取文件并提取目标行周围的上下文

    Args:
        file_path: 文件路径（相对或绝对）
        target_line: 目标行号（1-based）
        context_lines: 上下文行数
        workspace: 工作目录，默认为 frontend

    Returns:
        FileContextResult: 包含完整内容、周围代码、开始/结束行号

    Raises:
        FileNotFoundError: 文件不存在
    """
    if workspace is None:
        workspace = get_workspace_path("frontend")

    # 处理文件路径
    processed_path = process_file_path(file_path)
    full_path = workspace / processed_path

    if not full_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    content = full_path.read_text(encoding='utf-8')
    lines = content.splitlines()

    # 计算上下文范围
    start_line = max(1, target_line - context_lines)
    end_line = min(len(lines), target_line + context_lines)

    # 提取周围代码
    surrounding_lines = lines[start_line - 1:end_line]
    surrounding_code = '\n'.join(surrounding_lines)

    return FileContextResult(
        content=content,
        surrounding=surrounding_code,
        start_line=start_line,
        end_line=end_line
    )


def validate_file_path(
    file_path: str,
    workspace: Optional[Path] = None
) -> Tuple[bool, Optional[str]]:
    """
    验证文件路径是否合法（确保在工作目录内）

    Args:
        file_path: 文件路径
        workspace: 工作目录，默认为 frontend

    Returns:
        Tuple[bool, Optional[str]]: (是否合法, 错误信息)
    """
    if workspace is None:
        workspace = get_workspace_path("frontend")

    try:
        processed_path = process_file_path(file_path)
        full_path = workspace / processed_path
        full_path.resolve().relative_to(workspace.resolve())
        return True, None
    except ValueError:
        return False, "非法文件路径"
    except Exception as e:
        return False, f"路径验证失败: {e}"


def read_file_content(
    file_path: str,
    workspace: Optional[Path] = None
) -> Tuple[bool, str, Optional[str]]:
    """
    安全地读取文件内容

    Args:
        file_path: 文件路径
        workspace: 工作目录，默认为 frontend

    Returns:
        Tuple[bool, str, Optional[str]]: (是否成功, 内容, 错误信息)
    """
    # 验证路径
    is_valid, error_msg = validate_file_path(file_path, workspace)
    if not is_valid:
        return False, "", error_msg

    if workspace is None:
        workspace = get_workspace_path("frontend")

    try:
        processed_path = process_file_path(file_path)
        full_path = workspace / processed_path

        if not full_path.exists():
            return False, "", f"文件不存在: {file_path}"

        content = full_path.read_text(encoding='utf-8')
        return True, content, None
    except Exception as e:
        error(f"读取文件失败: {e}")
        return False, "", f"读取文件失败: {e}"


def write_file_content(
    file_path: str,
    content: str,
    workspace: Optional[Path] = None
) -> Tuple[bool, Optional[str]]:
    """
    安全地写入文件内容

    Args:
        file_path: 文件路径
        content: 文件内容
        workspace: 工作目录，默认为 frontend

    Returns:
        Tuple[bool, Optional[str]]: (是否成功, 错误信息)
    """
    # 验证路径
    is_valid, error_msg = validate_file_path(file_path, workspace)
    if not is_valid:
        return False, error_msg

    if workspace is None:
        workspace = get_workspace_path("frontend")

    try:
        processed_path = process_file_path(file_path)
        full_path = workspace / processed_path

        # 确保目录存在
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        full_path.write_text(content, encoding='utf-8')
        info(f"文件写入成功: {file_path}, 大小: {len(content)} 字符")
        return True, None
    except Exception as e:
        error(f"写入文件失败: {e}")
        return False, f"写入文件失败: {e}"


def create_diff_result(
    original_content: str,
    new_content: str,
    file_path: str
) -> DiffResult:
    """
    创建 Diff 结果

    Args:
        original_content: 原始内容
        new_content: 新内容
        file_path: 文件路径

    Returns:
        DiffResult: Diff 结果对象
    """
    diff = generate_diff(original_content, new_content, file_path)
    return DiffResult(
        diff=diff,
        original_content=original_content,
        new_content=new_content
    )


def build_element_context(
    tag: str,
    outer_html: str,
    element_id: Optional[str] = None,
    class_name: Optional[str] = None,
    text: Optional[str] = None,
    xpath: Optional[str] = None,
    selector: Optional[str] = None
) -> Dict[str, Any]:
    """
    构建元素上下文字典

    Args:
        tag: 元素标签
        outer_html: 元素 outerHTML
        element_id: 元素 ID
        class_name: 元素 class
        text: 元素文本
        xpath: 元素 XPath
        selector: CSS 选择器

    Returns:
        Dict[str, Any]: 元素上下文字典
    """
    return {
        "tag": tag,
        "id": element_id,
        "class_name": class_name,
        "outer_html": outer_html,
        "text": text,
        "xpath": xpath,
        "selector": selector,
    }
