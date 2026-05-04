"""
文件操作工具函数

提供统一的文件读取、写入和大小限制功能
与 E2E 测试脚本和 Pipeline 保持一致
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def read_files_with_size_limit(
    file_paths: List[str],
    all_generated_files: List[Dict],
    executor,
    max_file_size: int = 8000,
    path_prefix: str = "backend"
) -> Dict[str, str]:
    """
    读取文件内容并应用大小限制
    
    【与 E2E 测试脚本和 Pipeline 保持一致】
    
    Args:
        file_paths: 文件路径列表
        all_generated_files: 所有生成的文件（用于回退读取）
        executor: 代码执行器（需实现 read_file 方法）
        max_file_size: 最大文件大小（字符数），超过则截断
        path_prefix: 路径前缀，用于替换（如 "backend"）
        
    Returns:
        文件路径到内容的映射
    """
    file_contents = {}
    
    for path in file_paths:
        try:
            # 移除路径前缀以匹配 executor 的路径格式
            clean_path = path.replace(f"{path_prefix}/", "").replace(f"{path_prefix}\\", "")
            content = executor.read_file(clean_path)
            
            if content:
                if len(content) > max_file_size:
                    truncated = content[:max_file_size] + f"\n\n# ... (文件内容已截断，共 {len(content)} 字符)"
                    file_contents[path] = truncated
                    logger.warning(f"[FileUtils] 文件 {path} 过大 ({len(content)} 字符)，已截断至 {max_file_size}")
                else:
                    file_contents[path] = content
        except Exception:
            # 如果读取失败，尝试从 all_generated_files 获取
            for f in all_generated_files:
                if f.get("file_path") == path and f.get("content"):
                    content = f["content"]
                    if len(content) > max_file_size:
                        file_contents[path] = content[:max_file_size] + f"\n\n# ... (文件内容已截断，共 {len(content)} 字符)"
                    else:
                        file_contents[path] = content
                    break
    
    return file_contents


def extract_file_paths(file_list: List[Dict]) -> List[str]:
    """
    从文件列表中提取文件路径
    
    Args:
        file_list: 文件信息列表，每个元素包含 "file_path" 键
        
    Returns:
        文件路径列表
    """
    return [f.get("file_path", "") for f in file_list if f.get("file_path")]


def merge_files_content(
    code_files: List[Dict],
    test_files: List[Dict]
) -> List[Dict]:
    """
    合并代码文件和测试文件列表
    
    Args:
        code_files: 代码文件列表
        test_files: 测试文件列表
        
    Returns:
        合并后的文件列表
    """
    return code_files + test_files


def normalize_file_path(
    file_path: str,
    add_prefix: Optional[str] = "backend",
    remove_prefix: Optional[str] = None
) -> str:
    """
    规范化文件路径
    
    Args:
        file_path: 原始文件路径
        add_prefix: 添加的前缀（如 "backend"）
        remove_prefix: 移除的前缀
        
    Returns:
        规范化后的路径
    """
    path = file_path
    
    if remove_prefix and path.startswith(remove_prefix):
        path = path[len(remove_prefix):].lstrip("/\\")
    
    if add_prefix and not path.startswith(add_prefix):
        path = f"{add_prefix}/{path}"
    
    return path


def truncate_file_content(
    content: str,
    max_size: int,
    truncation_message: Optional[str] = None
) -> str:
    """
    截断文件内容到指定大小
    
    Args:
        content: 原始内容
        max_size: 最大字符数
        truncation_message: 截断提示信息
        
    Returns:
        截断后的内容
    """
    if len(content) <= max_size:
        return content
    
    msg = truncation_message or f"\n\n# ... (文件内容已截断，共 {len(content)} 字符)"
    return content[:max_size] + msg
