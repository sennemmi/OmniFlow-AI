"""
Workspace API - 文件系统管理
提供文件浏览、读取、编辑功能
"""
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/workspace", tags=["workspace"])

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent


class FileNode(BaseModel):
    """文件节点"""
    id: str
    name: str
    type: str  # "file" | "folder"
    path: str
    size: Optional[int] = None
    modified: Optional[str] = None
    language: Optional[str] = None


class FileListResponse(BaseModel):
    """文件列表响应"""
    success: bool
    data: List[FileNode]
    error: Optional[str] = None


class FileContentResponse(BaseModel):
    """文件内容响应"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None


class SaveFileRequest(BaseModel):
    """保存文件请求"""
    content: str


def get_language_by_extension(filename: str) -> Optional[str]:
    """根据文件扩展名获取语言"""
    ext = Path(filename).suffix.lower()
    language_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".txt": "text",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".sql": "sql",
        ".sh": "shell",
        ".dockerfile": "dockerfile",
    }
    return language_map.get(ext)


@router.get("/files", response_model=FileListResponse)
async def get_file_tree(
    path: str = Query("", description="相对路径，默认为根目录")
):
    """
    获取文件树结构（扁平化列表）
    """
    try:
        target_path = PROJECT_ROOT / path if path else PROJECT_ROOT

        # 安全检查
        try:
            target_path.resolve().relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        if target_path.is_file():
            raise HTTPException(status_code=400, detail="Path is a file")

        nodes = []
        
        # 扫描目录
        try:
            items = sorted(target_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            items = []

        for item in items:
            # 跳过隐藏文件和特定目录
            if item.name.startswith(".") or item.name in [
                "__pycache__", ".git", ".venv", "venv", 
                "node_modules", ".pytest_cache", ".mypy_cache",
                "dist", "build", ".omniflow_index"
            ]:
                continue

            rel_path = item.relative_to(PROJECT_ROOT).as_posix()
            
            try:
                stat = item.stat()
                modified = str(int(stat.st_mtime))
                size = stat.st_size if item.is_file() else None
            except:
                modified = None
                size = None

            node = FileNode(
                id=rel_path,
                name=item.name,
                type="folder" if item.is_dir() else "file",
                path=rel_path,
                size=size,
                modified=modified,
                language=get_language_by_extension(item.name) if item.is_file() else None,
            )
            nodes.append(node)

        return FileListResponse(success=True, data=nodes)

    except HTTPException:
        raise
    except Exception as e:
        return FileListResponse(success=False, data=[], error=str(e))


@router.get("/files/content", response_model=FileContentResponse)
async def get_file_content(
    path: str = Query(..., description="文件相对路径")
):
    """
    获取文件内容
    """
    try:
        file_path = PROJECT_ROOT / path

        # 安全检查
        try:
            file_path.resolve().relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        if file_path.is_dir():
            raise HTTPException(status_code=400, detail="Path is a directory")

        # 检查文件大小（限制 1MB）
        file_size = file_path.stat().st_size
        if file_size > 1024 * 1024:
            raise HTTPException(status_code=413, detail="File too large (max 1MB)")

        # 读取文件内容
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = "[Binary file - cannot display]"

        return FileContentResponse(
            success=True,
            data={
                "path": path,
                "name": file_path.name,
                "content": content,
                "size": file_size,
                "language": get_language_by_extension(file_path.name),
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        return FileContentResponse(success=False, data={}, error=str(e))


@router.post("/files/content", response_model=FileContentResponse)
async def save_file_content(
    path: str = Query(..., description="文件相对路径"),
    request: SaveFileRequest = None
):
    """
    保存文件内容
    """
    try:
        if request is None:
            raise HTTPException(status_code=400, detail="Content is required")

        file_path = PROJECT_ROOT / path

        # 安全检查
        try:
            file_path.resolve().relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        # 确保父目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        file_path.write_text(request.content, encoding="utf-8")

        return FileContentResponse(
            success=True,
            data={
                "path": path,
                "name": file_path.name,
                "size": file_path.stat().st_size,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        return FileContentResponse(success=False, data={}, error=str(e))


@router.get("/stats")
async def get_workspace_stats():
    """获取工作区统计信息"""
    try:
        total_files = 0
        total_dirs = 0

        for root, dirs, files in os.walk(PROJECT_ROOT):
            # 跳过隐藏目录
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in [
                    "__pycache__", ".git", ".venv", "venv",
                    "node_modules", ".pytest_cache", ".mypy_cache",
                    "dist", "build", ".omniflow_index"
                ]
            ]
            total_dirs += len(dirs)
            total_files += len([f for f in files if not f.startswith(".")])

        return {
            "success": True,
            "data": {
                "total_files": total_files,
                "total_dirs": total_dirs,
                "root_path": str(PROJECT_ROOT),
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
