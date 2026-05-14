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
        """创建临时工作区并初始化 Git

        【重构】与 delivery_handler.py 保持一致：
        只创建空目录并 init，不复制文件。文件复制在 checkout 分支后进行。
        """
        from app.service.git_provider import GitProviderService

        self._workspace = Path(tempfile.mkdtemp(prefix=f"omniflow-{prefix}-{self.request_id[:8]}-"))
        info(f"创建独立 MR 工作区: {self._workspace}", request_id=self.request_id)

        self._git = GitProviderService(str(self._workspace))
        # 【修复】skip_fetch=True 避免全量 fetch，后续用浅克隆只 fetch main 分支
        self._git.init_repo(remote_url=self.remote_url, skip_fetch=True)
        info("Git 仓库已初始化（跳过 fetch）", request_id=self.request_id)
        return self

    def resolve_file_path(self, file_path: str) -> str:
        """将原始文件路径解析为项目内的相对路径

        【修复】改为在 project_path 中解析，而不是 workspace。
        因为 workspace 在 checkout 前是空的，无法用于路径搜索。
        """
        for prefix in self.SEARCH_PREFIXES:
            prefix_dir = self.project_path / prefix if prefix else self.project_path
            test_path = prefix_dir / file_path
            if test_path.exists():
                resolved = str(test_path.relative_to(self.project_path)).replace("\\", "/")
                info(f"文件路径调整: {file_path} -> {resolved}", request_id=self.request_id)
                return resolved

        # 按文件名在 project_path 里搜索
        file_name = Path(file_path).name
        for root, _dirs, dir_files in os.walk(self.project_path):
            for filename in dir_files:
                if filename == file_name:
                    found_path = Path(root) / filename
                    resolved = str(found_path.relative_to(self.project_path)).replace("\\", "/")
                    info(f"通过搜索找到文件: {file_path} -> {resolved}", request_id=self.request_id)
                    return resolved

        raise FileNotFoundError(f"文件不存在: {file_path}")

    def resolve_file_paths(self, file_paths: List[str]) -> List[str]:
        """批量解析文件路径"""
        return [self.resolve_file_path(fp) for fp in file_paths]

    async def create_branch_and_commit(
        self,
        branch_name: str,
        file_paths: List[str],
        commit_msg: str,
    ) -> None:
        """创建分支、复制文件、提交

        【重构】Git 流程与 delivery_handler.py 保持一致：
        init → fetch → checkout → 复制文件 → add → commit
        """
        from app.service.git_provider import GitProviderError

        # 1. 【修复】使用浅克隆只 fetch main 分支，避免全量 fetch 超时
        try:
            self._git._run_git_command(
                ["fetch", "origin", "main", "--depth=1"],
                check=True,
                timeout=60
            )
            info("获取远程 main 分支完成（浅克隆）", request_id=self.request_id)
        except Exception as fetch_error:
            raise ValueError(f"无法获取远程 main 分支: {fetch_error}")

        # 2. 从 origin/main 创建普通分支（此时工作区是空的，不会冲突）
        try:
            self._git._run_git_command(
                ["checkout", "-b", branch_name, "origin/main"],
                check=True
            )
            info(f"从 origin/main 创建分支: {branch_name}", request_id=self.request_id)
        except GitProviderError as e:
            # 如果分支已存在，则切换到该分支
            if "already exists" in str(e).lower():
                info(f"分支 {branch_name} 已存在，切换到该分支", request_id=self.request_id)
                self._git.checkout_branch(branch_name)
            else:
                raise

        # 3. 【重构】现在再复制需要修改的文件（覆盖 main 版本）
        copied_count = 0
        for file_path in file_paths:
            try:
                src = self.project_path / file_path
                if src.exists() and src.is_file():
                    dst = self._workspace / file_path
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    copied_count += 1
                else:
                    info(f"文件不存在或不是普通文件，跳过: {file_path}", request_id=self.request_id)
            except Exception as copy_error:
                info(f"复制文件失败 {file_path}: {copy_error}", request_id=self.request_id)

        if copied_count == 0:
            raise ValueError(f"没有文件被成功复制（共 {len(file_paths)} 个目标文件）")

        info(f"已复制 {copied_count} 个文件到工作区", request_id=self.request_id)

        # 4. add + commit
        await asyncio.to_thread(self._git.add_files, file_paths)
        info(f"已添加 {len(file_paths)} 个文件到暂存区", request_id=self.request_id)

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
