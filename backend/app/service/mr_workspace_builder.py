"""
MR 工作区构建器

封装创建独立 Git 工作区、分支、提交、推送、PR 创建的共享逻辑。
消除 code_modify.py (x2) 和 delivery_handler.py 之间的重复。
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

from app.core.logging import info, error


@dataclass
class MRResult:
    """MR 创建结果"""
    success: bool
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    branch: Optional[str] = None
    error: Optional[str] = None
    files_count: int = 0
    files: Optional[List[str]] = None


class MRWorkspaceBuilder:
    """
    MR 独立工作区构建器

    在临时目录中创建隔离的 Git 环境，避免本地未提交变更影响 MR。
    """

    # 复制项目文件时忽略的目录/文件
    COPY_IGNORE_PATTERNS = (
        '.git', '__pycache__', '*.pyc', '.pytest_cache',
        'node_modules', '.venv', 'venv', '.env'
    )

    # 查找文件时尝试的路径前缀
    SEARCH_PREFIXES = ['', 'frontend', 'backend']

    def __init__(self, project_path: Path, github_owner: str, github_repo: str, request_id: str):
        self.project_path = project_path
        self.remote_url = f"https://github.com/{github_owner}/{github_repo}.git"
        self.request_id = request_id
        self._workspace: Optional[Path] = None

    @property
    def workspace(self) -> Path:
        if self._workspace is None:
            raise RuntimeError("工作区尚未创建，请先调用 setup()")
        return self._workspace

    async def setup(self, prefix: str = "mr") -> "MRWorkspaceBuilder":
        """创建临时工作区并初始化 Git"""
        from app.service.git_provider import GitProviderService

        self._workspace = Path(tempfile.mkdtemp(prefix=f"omniflow-{prefix}-{self.request_id[:8]}-"))
        info(f"创建独立 MR 工作区: {self._workspace}", request_id=self.request_id)

        shutil.copytree(
            self.project_path,
            self._workspace,
            ignore=shutil.ignore_patterns(*self.COPY_IGNORE_PATTERNS),
            dirs_exist_ok=True
        )

        self._git = GitProviderService(str(self._workspace))
        self._git.init_repo(remote_url=self.remote_url)
        info("Git 仓库已初始化", request_id=self.request_id)
        return self

    def resolve_file_path(self, file_path: str) -> str:
        """将原始文件路径解析为工作区内的相对路径"""
        for prefix in self.SEARCH_PREFIXES:
            prefix_dir = self._workspace / prefix if prefix else self._workspace
            test_path = prefix_dir / file_path
            if test_path.exists():
                resolved = str(test_path.relative_to(self._workspace)).replace("\\", "/")
                info(f"文件路径调整: {file_path} -> {resolved}", request_id=self.request_id)
                return resolved

        # 按文件名搜索
        file_name = Path(file_path).name
        for root, _dirs, dir_files in os.walk(self._workspace):
            for filename in dir_files:
                if filename == file_name:
                    found_path = Path(root) / filename
                    resolved = str(found_path.relative_to(self._workspace)).replace("\\", "/")
                    info(f"通过搜索找到文件: {file_path} -> {resolved}", request_id=self.request_id)
                    return resolved

        raise FileNotFoundError(f"文件不存在于工作区: {file_path}")

    def resolve_file_paths(self, file_paths: List[str]) -> List[str]:
        """批量解析文件路径"""
        return [self.resolve_file_path(fp) for fp in file_paths]

    async def create_branch_and_commit(
        self,
        branch_name: str,
        file_paths: List[str],
        commit_msg: str,
    ) -> None:
        """创建分支、添加文件、提交"""
        self._git._run_git_command(["checkout", "--orphan", branch_name])
        self._git._run_git_command(["reset", "--mixed", "origin/main"])
        info(f"创建分支: {branch_name}", request_id=self.request_id)

        await asyncio.to_thread(self._git.add_files, file_paths)
        await asyncio.to_thread(self._git.commit_changes, commit_msg)
        info(f"提交变更: {commit_msg}", request_id=self.request_id)

    async def push_and_create_pr(
        self,
        branch_name: str,
        pr_title: str,
        pr_body: str,
        base_branch: str = "main",
    ) -> MRResult:
        """推送分支并创建 PR"""
        from app.service.platform_provider import GitHubProviderService

        await asyncio.to_thread(self._git.push_branch, branch_name)
        info(f"推送分支: {branch_name}", request_id=self.request_id)

        async with GitHubProviderService() as gh:
            pr_result = await gh.create_pull_request(
                head_branch=branch_name,
                title=pr_title,
                body=pr_body,
                base_branch=base_branch
            )

        if pr_result.success:
            info(f"PR 创建成功: {pr_result.pr_url}", request_id=self.request_id)
            return MRResult(success=True, pr_url=pr_result.pr_url,
                          pr_number=pr_result.pr_number, branch=branch_name)
        else:
            error(f"PR 创建失败: {pr_result.error}", request_id=self.request_id)
            return MRResult(success=False, error=pr_result.error)

    def cleanup(self) -> None:
        """清理临时工作区"""
        if self._workspace and self._workspace.exists():
            try:
                shutil.rmtree(self._workspace, ignore_errors=True)
                info(f"清理 MR 工作区: {self._workspace}", request_id=self.request_id)
            except Exception as e:
                error(f"清理 MR 工作区失败: {e}", request_id=self.request_id)
