"""
项目上下文服务
业务逻辑层 - 提供项目文件树等上下文信息

重构说明：
- 所有路径操作基于 settings.TARGET_PROJECT_PATH
- 实现平台代码与 AI 操作目标代码的解耦
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.core.config import settings


@dataclass
class FileNode:
    """文件树节点"""
    name: str
    path: str
    is_directory: bool
    children: List["FileNode"] = field(default_factory=list)


class ProjectService:
    """
    项目上下文服务
    
    提供项目相关的上下文信息，包括：
    - 文件树结构
    - 项目元数据
    
    遵循"以认真查询为荣"原则，让 Agent 了解工作环境
    
    重要：所有路径操作基于 settings.TARGET_PROJECT_PATH
    实现平台代码与 AI 操作目标代码的解耦
    """
    
    # 默认跳过的目录和文件模式
    SKIP_PATTERNS = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        ".venv",
        "venv",
        "env",
        ".env",
        ".idea",
        ".vscode",
        "dist",
        "build",
        ".egg-info",
        ".trae",
    }
    
    SKIP_EXTENSIONS = {
        ".pyc",
        ".pyo",
        ".pyd",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
    }
    
    @classmethod
    def get_file_tree(
        cls,
        path: str,
        max_depth: int = 5,
        current_depth: int = 0
    ) -> Optional[FileNode]:
        """
        递归获取项目目录结构
        
        Args:
            path: 项目根目录路径
            max_depth: 最大递归深度，防止过大目录
            current_depth: 当前深度（内部使用）
            
        Returns:
            FileNode: 文件树根节点，如果路径不存在返回 None
            
        Example:
            >>> tree = ProjectService.get_file_tree("/path/to/project")
            >>> print(tree.name)  # "project"
        """
        root_path = Path(path)
        
        if not root_path.exists():
            return None
        
        if not root_path.is_dir():
            return FileNode(
                name=root_path.name,
                path=str(root_path),
                is_directory=False
            )
        
        node = FileNode(
            name=root_path.name,
            path=str(root_path.absolute()),
            is_directory=True
        )
        
        # 达到最大深度，不再递归
        if current_depth >= max_depth:
            return node
        
        try:
            for item in sorted(root_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                # 跳过隐藏文件和指定模式
                if item.name.startswith(".") and item.name not in [".env", ".gitignore"]:
                    continue
                    
                # 跳过指定目录
                if item.name in cls.SKIP_PATTERNS:
                    continue
                
                # 跳过指定扩展名
                if item.suffix in cls.SKIP_EXTENSIONS:
                    continue
                
                if item.is_dir():
                    child = cls.get_file_tree(
                        str(item),
                        max_depth=max_depth,
                        current_depth=current_depth + 1
                    )
                    if child:
                        node.children.append(child)
                else:
                    node.children.append(FileNode(
                        name=item.name,
                        path=str(item.absolute()),
                        is_directory=False
                    ))
        except PermissionError:
            # 权限不足，跳过该目录
            pass
        
        return node
    
    @classmethod
    def get_project_summary(cls, path: str) -> dict:
        """
        获取项目摘要信息
        
        Args:
            path: 项目路径
            
        Returns:
            dict: 包含项目统计信息的字典
        """
        root_path = Path(path)
        
        if not root_path.exists():
            return {"error": "Path does not exist"}
        
        stats = {
            "path": str(root_path.absolute()),
            "total_files": 0,
            "total_dirs": 0,
            "file_types": {},
            "structure": None
        }
        
        def count_files(node: FileNode):
            if node.is_directory:
                stats["total_dirs"] += 1
                for child in node.children:
                    count_files(child)
            else:
                stats["total_files"] += 1
                ext = Path(node.name).suffix or "no_extension"
                stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1
        
        tree = cls.get_file_tree(path)
        if tree:
            stats["structure"] = tree
            count_files(tree)
        
        return stats
    
    @classmethod
    def file_tree_to_dict(cls, node: FileNode) -> dict:
        """
        将 FileNode 转换为字典格式（用于 JSON 序列化）
        
        Args:
            node: 文件树节点
            
        Returns:
            dict: 字典表示
        """
        result = {
            "name": node.name,
            "path": node.path,
            "is_directory": node.is_directory
        }
        
        if node.is_directory and node.children:
            result["children"] = [
                cls.file_tree_to_dict(child) for child in node.children
            ]
        
        return result


# 便捷函数
def get_current_project_tree(max_depth: int = 5) -> Optional[FileNode]:
    """
    获取目标项目的文件树
    
    基于 settings.TARGET_PROJECT_PATH 获取 AI 操作的目标项目文件树
    实现平台代码与目标代码的解耦
    
    Returns:
        FileNode: 目标项目的文件树根节点，未配置返回 None
    """
    # 从配置获取目标项目路径
    target_path = settings.TARGET_PROJECT_PATH
    
    if not target_path:
        # 未配置目标项目路径，返回 None
        print("[ProjectService] 警告: TARGET_PROJECT_PATH 未配置")
        return None
    
    # 如果是相对路径，基于 backend 父目录解析
    target_path_obj = Path(target_path)
    if not target_path_obj.is_absolute():
        # 获取 backend 的父目录（项目根目录）
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent.parent
        target_path_obj = project_root / target_path
    
    target_path_str = str(target_path_obj.resolve())
    
    # 验证路径存在
    if not target_path_obj.exists():
        print(f"[ProjectService] 警告: 目标项目路径不存在: {target_path_str}")
        return None
    
    return ProjectService.get_file_tree(target_path_str, max_depth=max_depth)


def get_target_project_path() -> Optional[Path]:
    """
    获取目标项目的绝对路径
    
    Returns:
        Optional[Path]: 目标项目路径，未配置返回 None
    """
    target_path = settings.TARGET_PROJECT_PATH
    
    if not target_path:
        return None
    
    target_path_obj = Path(target_path)
    if not target_path_obj.is_absolute():
        # 获取 backend 的父目录（项目根目录）
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent.parent
        target_path_obj = project_root / target_path
    
    return target_path_obj.resolve()
