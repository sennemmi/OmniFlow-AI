"""
工作区管理服务
负责临时工作区的创建、管理和清理
"""

import asyncio
import os
import shutil
import stat
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from app.core.config import settings
from app.core.logging import info, error

# 全局线程池，用于执行同步文件操作
_file_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="workspace_file_")


def _remove_readonly(func, path, _):
    """清除只读属性并重试删除（Windows 兼容）"""
    os.chmod(path, stat.S_IWRITE)
    func(path)


class WorkspaceService:
    """
    工作区管理服务
    
    职责：
    1. 创建临时工作区（从目标项目复制）
    2. 管理工作区生命周期
    3. 清理临时工作区
    """
    
    def __init__(self, pipeline_id: int):
        self.pipeline_id = pipeline_id
        self.workspace_dir: Optional[Path] = None
        self._target_path: Optional[Path] = None
    
    @property
    def target_path(self) -> Path:
        """获取目标项目路径"""
        if self._target_path is None:
            target_path = Path(settings.TARGET_PROJECT_PATH)
            if not target_path.is_absolute():
                # 基于 backend 父目录的父目录解析（与 CodeExecutorService 保持一致）
                backend_dir = Path(__file__).parent.parent.parent
                project_root = backend_dir.parent
                target_path = project_root / settings.TARGET_PROJECT_PATH
            self._target_path = target_path
            # 自动创建目标路径（如果不存在）
            self._target_path.mkdir(parents=True, exist_ok=True)
        return self._target_path
    
    async def create_workspace_async(self) -> Path:
        """
        异步创建临时工作区

        流程：
        1. 生成唯一工作区目录
        2. 从目标项目复制代码（在线程池中执行，避免阻塞事件循环）

        Returns:
            Path: 工作区目录路径
        """
        short_uuid = str(uuid.uuid4())[:8]
        self.workspace_dir = Path(tempfile.gettempdir()) / f"omniflow_workspaces/pipeline_{self.pipeline_id}_{short_uuid}"
        self.workspace_dir.parent.mkdir(parents=True, exist_ok=True)

        info(
            "创建临时工作区",
            pipeline_id=self.pipeline_id,
            workspace=str(self.workspace_dir)
        )

        # 复制目标项目到工作区（在线程池中执行，避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            _file_executor,
            shutil.copytree,
            self.target_path,
            self.workspace_dir
        )

        return self.workspace_dir

    def create_workspace(self) -> Path:
        """
        同步创建临时工作区（兼容旧代码）

        流程：
        1. 生成唯一工作区目录
        2. 从目标项目复制代码

        Returns:
            Path: 工作区目录路径
        """
        short_uuid = str(uuid.uuid4())[:8]
        self.workspace_dir = Path(tempfile.gettempdir()) / f"omniflow_workspaces/pipeline_{self.pipeline_id}_{short_uuid}"
        self.workspace_dir.parent.mkdir(parents=True, exist_ok=True)

        info(
            "创建临时工作区",
            pipeline_id=self.pipeline_id,
            workspace=str(self.workspace_dir)
        )

        # 复制目标项目到工作区
        shutil.copytree(self.target_path, self.workspace_dir)

        return self.workspace_dir

    async def cleanup_async(self) -> None:
        """异步清理临时工作区（在线程池中执行，Windows 兼容）"""
        if self.workspace_dir and self.workspace_dir.exists():
            try:
                info(
                    "清理临时工作区",
                    pipeline_id=self.pipeline_id,
                    workspace=str(self.workspace_dir)
                )
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    _file_executor,
                    lambda: shutil.rmtree(self.workspace_dir, onerror=_remove_readonly)
                )
                self.workspace_dir = None
            except Exception:
                error(
                    "清理临时工作区失败",
                    pipeline_id=self.pipeline_id,
                    workspace=str(self.workspace_dir),
                    exc_info=True
                )

    def cleanup(self) -> None:
        """同步清理临时工作区（兼容旧代码，Windows 兼容）"""
        if self.workspace_dir and self.workspace_dir.exists():
            try:
                info(
                    "清理临时工作区",
                    pipeline_id=self.pipeline_id,
                    workspace=str(self.workspace_dir)
                )
                shutil.rmtree(self.workspace_dir, onerror=_remove_readonly)
                self.workspace_dir = None
            except Exception:
                error(
                    "清理临时工作区失败",
                    pipeline_id=self.pipeline_id,
                    workspace=str(self.workspace_dir),
                    exc_info=True
                )

    def get_workspace_path(self) -> Optional[Path]:
        """获取当前工作区路径"""
        return self.workspace_dir
    
    def __enter__(self) -> "WorkspaceService":
        """上下文管理器入口"""
        self.create_workspace()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器出口 - 自动清理"""
        self.cleanup()


@contextmanager
def workspace_context(pipeline_id: int):
    """
    工作区上下文管理器（同步）

    使用示例：
        with workspace_context(pipeline_id) as ws:
            workspace_path = ws.get_workspace_path()
            # 在工作区中执行操作
            # 退出时自动清理

    Args:
        pipeline_id: Pipeline ID

    Yields:
        WorkspaceService: 工作区服务实例
    """
    service = WorkspaceService(pipeline_id)
    try:
        service.create_workspace()
        yield service
    finally:
        service.cleanup()


class AsyncWorkspaceContext:
    """
    异步工作区上下文管理器

    使用示例：
        async with async_workspace_context(pipeline_id) as ws:
            workspace_path = ws.get_workspace_path()
            # 在工作区中执行操作
            # 退出时自动清理
    """

    def __init__(self, pipeline_id: int):
        self.pipeline_id = pipeline_id
        self.service = WorkspaceService(pipeline_id)

    async def __aenter__(self) -> WorkspaceService:
        """异步上下文管理器入口"""
        await self.service.create_workspace_async()
        return self.service

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器出口 - 自动清理"""
        await self.service.cleanup_async()


def async_workspace_context(pipeline_id: int) -> AsyncWorkspaceContext:
    """
    创建异步工作区上下文管理器

    Args:
        pipeline_id: Pipeline ID

    Returns:
        AsyncWorkspaceContext: 异步上下文管理器
    """
    return AsyncWorkspaceContext(pipeline_id)
