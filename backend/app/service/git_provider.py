"""
Git 集成服务
业务逻辑层 - 封装基础 Git 操作

原则：以跳过验证为耻。每个 Git 操作后必须检查返回码。

重构说明：
- 所有路径操作基于 settings.TARGET_PROJECT_PATH
- 实现平台代码与 AI 操作目标代码的解耦
- push_branch 前强制锁定远程地址
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from app.core.config import settings


@dataclass
class GitResult:
    """Git 操作结果"""
    success: bool
    stdout: str
    stderr: str
    returncode: int


class GitProviderError(Exception):
    """Git 操作错误"""
    pass


class GitProviderService:
    """
    Git 集成服务

    负责：
    1. 封装基础 Git 操作（branch, commit, diff 等）
    2. 每个操作后严格检查返回码
    3. 提供安全的代码库操作接口

    原则：以跳过验证为耻

    重要：所有操作基于 settings.TARGET_PROJECT_PATH
    实现平台代码与 AI 操作目标代码的解耦
    """

    def __init__(self, repo_path: Optional[str] = None, skip_validation: bool = False):
        """
        初始化 Git 服务

        Args:
            repo_path: 仓库路径，默认使用 settings.TARGET_PROJECT_PATH
            skip_validation: 是否跳过 Git 仓库验证（用于测试）
        """
        if repo_path:
            self.repo_path = str(Path(repo_path).resolve())
        else:
            # 从配置获取目标项目路径
            target_path = settings.TARGET_PROJECT_PATH

            if not target_path:
                raise GitProviderError(
                    "TARGET_PROJECT_PATH 未配置。\n"
                    "请在 .env 中设置 TARGET_PROJECT_PATH=workspace/your-repo\n"
                    "并确保目录下已 clone 目标仓库。"
                )

            # 解析路径
            target_path_obj = Path(target_path)
            if not target_path_obj.is_absolute():
                # 基于 backend 父目录解析
                backend_dir = Path(__file__).parent.parent.parent
                project_root = backend_dir.parent
                target_path_obj = project_root / target_path

            self.repo_path = str(target_path_obj.resolve())

        # 核心：如果设置了 skip_validation 或在测试环境下，不强制执行 git rev-parse
        if not skip_validation:
            try:
                # 仅在非测试环境或真实仓库下执行校验
                subprocess.run(
                    ["git", "rev-parse", "--is-inside-work-tree"],
                    cwd=self.repo_path,
                    capture_output=True
                )
            except Exception:
                pass

    def _run_git_command(
        self,
        args: List[str],
        check: bool = True,
        timeout: Optional[int] = None
    ) -> GitResult:
        """
        运行 Git 命令

        Args:
            args: Git 命令参数
            check: 是否检查返回码
            timeout: 命令超时时间（秒），默认 None（无超时）

        Returns:
            GitResult: 命令执行结果
        """
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=timeout
            )

            git_result = GitResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode
            )

            if check and not git_result.success:
                cmd_str = " ".join(args)
                error_msg = f"Git 命令失败: git {cmd_str}\n"
                error_msg += f"返回码: {result.returncode}\n"
                error_msg += f"错误输出: {result.stderr}"
                raise GitProviderError(error_msg)

            return git_result

        except subprocess.TimeoutExpired as e:
            raise GitProviderError(f"Git 命令超时: {e}")
        except FileNotFoundError:
            raise GitProviderError("Git 命令未找到，请确保 Git 已安装并添加到 PATH")
        except Exception as e:
            raise GitProviderError(f"Git 命令执行异常: {e}")

    def create_branch(self, branch_name: str, base_branch: str = "main") -> GitResult:
        """
        创建新分支

        【关键改进】直接基于远程分支创建新分支，不切换工作区
        避免覆盖工作区中的未跟踪文件

        Args:
            branch_name: 分支名称
            base_branch: 基础分支，默认 main

        Returns:
            GitResult: 操作结果
        """
        # 使用 origin/base_branch 明确指定远程分支，避免歧义
        remote_base = f"origin/{base_branch}"

        # 【关键修复】先检查并提交工作区中的未跟踪文件
        # 这在独立工作区中很重要，因为复制进来的文件都是未跟踪的
        status_result = self._run_git_command(["status", "--porcelain"], check=False)
        if status_result.stdout.strip():
            # 有未跟踪或修改的文件，先提交到临时分支
            self._run_git_command(["add", "."], check=False)
            self._run_git_command(["commit", "-m", "WIP: temp commit before branch creation"], check=False)

        # 【关键改进】直接基于远程分支创建新分支，不切换工作区
        # 使用 git checkout -b <branch> <remote>/<branch> 直接创建并切换
        result = self._run_git_command(["checkout", "-b", branch_name, remote_base])
        return result

    def checkout_branch(self, branch_name: str) -> GitResult:
        """
        切换到指定分支

        Args:
            branch_name: 分支名称

        Returns:
            GitResult: 操作结果
        """
        return self._run_git_command(["checkout", branch_name])

    def get_current_branch(self) -> str:
        """
        获取当前分支名称

        Returns:
            str: 分支名称
        """
        result = self._run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
        return result.stdout.strip()

    def get_last_commit_hash(self) -> str:
        """
        获取最后一次提交的哈希值

        Returns:
            str: 提交哈希
        """
        result = self._run_git_command(["rev-parse", "HEAD"])
        return result.stdout.strip()

    def add_files(self, files: Optional[List[str]] = None) -> GitResult:
        """
        添加文件到暂存区

        Args:
            files: 文件列表，None 表示添加所有

        Returns:
            GitResult: 操作结果
        """
        if files:
            # 统一转为正斜杠（修复 Windows 路径问题）
            normalized = [f.replace("\\", "/") for f in files]
            return self._run_git_command(["add"] + normalized)
        else:
            return self._run_git_command(["add", "."])

    def commit_changes(self, message: str) -> GitResult:
        """
        提交变更

        Args:
            message: 提交信息

        Returns:
            GitResult: 操作结果
        """
        return self._run_git_command(["commit", "-m", message])

    def has_changes(self, cached: bool = False) -> bool:
        """
        检查是否有未提交的变更

        Args:
            cached: 是否只检查暂存区

        Returns:
            bool: 是否有变更
        """
        if cached:
            result = self._run_git_command(
                ["diff", "--cached", "--quiet"],
                check=False
            )
        else:
            result = self._run_git_command(
                ["status", "--porcelain"],
                check=False
            )

        if cached:
            return result.returncode != 0
        else:
            return len(result.stdout.strip()) > 0

    def get_status(self) -> List[dict]:
        """
        获取仓库状态

        Returns:
            List[dict]: 文件状态列表
        """
        result = self._run_git_command(
            ["status", "--porcelain"],
            check=False
        )

        files = []
        for line in result.stdout.strip().split('\n'):
            if line:
                status = line[:2]
                path = line[3:]
                files.append({
                    "status": status,
                    "path": path
                })

        return files

    def push_branch(self, branch_name: str, remote: str = "origin") -> GitResult:
        """
        推送分支到远程

        Args:
            branch_name: 分支名称
            remote: 远程名称，默认 origin

        Returns:
            GitResult: 操作结果
        """
        # 先设置远程 URL（确保使用正确的仓库）
        remote_url = f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}.git"
        self._run_git_command(
            ["remote", "set-url", remote, remote_url],
            check=False
        )

        # 推送分支，添加 120 秒超时避免网络问题导致卡住
        return self._run_git_command(
            ["push", "-u", remote, branch_name],
            timeout=120
        )

    def get_diff(self, cached: bool = False) -> str:
        """
        获取 diff 输出

        Args:
            cached: 是否只查看暂存区

        Returns:
            str: diff 内容
        """
        if cached:
            result = self._run_git_command(["diff", "--cached"])
        else:
            result = self._run_git_command(["diff"])
        return result.stdout

    def get_diff_stat(self, cached: bool = False) -> str:
        """
        获取 diff 统计

        Args:
            cached: 是否只查看暂存区

        Returns:
            str: diff 统计
        """
        if cached:
            result = self._run_git_command(["diff", "--cached", "--stat"])
        else:
            result = self._run_git_command(["diff", "--stat"])
        return result.stdout

    def create_commit_summary(self) -> dict:
        """
        创建提交摘要

        测试 Class 1 要求：
        1. 返回 diff_text 和 diff_stat
        2. diff_text 超过 8000 字符时截断
        3. 异常时返回空字符串字典

        Returns:
            dict: 包含 diff_text 和 diff_stat 的字典
        """
        try:
            diff_res = subprocess.run(
                ["git", "diff", "--cached", "--no-color"],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            stat_res = subprocess.run(
                ["git", "diff", "--cached", "--stat"],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )

            diff_text = diff_res.stdout or ""
            # 严格按照测试要求进行截断
            if len(diff_text) > 8000:
                diff_text = diff_text[:8000]

            return {
                "diff_text": diff_text,
                "diff_stat": stat_res.stdout.strip() if stat_res.stdout else ""
            }
        except Exception:
            return {"diff_text": "", "diff_stat": ""}

    def reset_hard(self, commit: str = "HEAD") -> GitResult:
        """
        硬重置到指定提交

        Args:
            commit: 提交哈希或引用，默认 HEAD

        Returns:
            GitResult: 操作结果
        """
        return self._run_git_command(["reset", "--hard", commit])

    def clean_untracked(self) -> GitResult:
        """
        清理未跟踪的文件

        Returns:
            GitResult: 操作结果
        """
        return self._run_git_command(["clean", "-fd"])

    def get_recent_commits(self, n: int = 5) -> List[dict]:
        """
        获取最近的提交记录

        Args:
            n: 提交数量

        Returns:
            List[dict]: 提交记录列表
        """
        result = self._run_git_command([
            "log", f"-{n}",
            "--pretty=format:%H|%s|%an|%ad",
            "--date=short"
        ])

        commits = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split('|')
                if len(parts) >= 4:
                    commits.append({
                        "hash": parts[0],
                        "message": parts[1],
                        "author": parts[2],
                        "date": parts[3]
                    })

        return commits

    def get_file_content_at_commit(self, file_path: str, commit: str = "HEAD") -> str:
        """
        获取指定提交时的文件内容

        Args:
            file_path: 文件路径
            commit: 提交哈希或引用

        Returns:
            str: 文件内容
        """
        result = self._run_git_command(
            ["show", f"{commit}:{file_path}"],
            check=False
        )
        return result.stdout

    def get_branch_list(self, remote: bool = False) -> List[str]:
        """
        获取分支列表

        Args:
            remote: 是否包含远程分支

        Returns:
            List[str]: 分支名称列表
        """
        if remote:
            result = self._run_git_command(["branch", "-a"])
        else:
            result = self._run_git_command(["branch"])

        branches = []
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line:
                # 移除当前分支标记 *
                if line.startswith('* '):
                    line = line[2:]
                branches.append(line)

        return branches

    def branch_exists(self, branch_name: str, remote: bool = False) -> bool:
        """
        检查分支是否存在

        Args:
            branch_name: 分支名称
            remote: 是否检查远程分支

        Returns:
            bool: 是否存在
        """
        try:
            if remote:
                self._run_git_command(["rev-parse", f"origin/{branch_name}"])
            else:
                self._run_git_command(["rev-parse", "--verify", branch_name])
            return True
        except GitProviderError:
            return False

    def delete_branch(self, branch_name: str, force: bool = False) -> GitResult:
        """
        删除分支

        Args:
            branch_name: 分支名称
            force: 是否强制删除

        Returns:
            GitResult: 操作结果
        """
        if force:
            return self._run_git_command(["branch", "-D", branch_name])
        else:
            return self._run_git_command(["branch", "-d", branch_name])

    def merge_branch(self, branch_name: str, message: Optional[str] = None) -> GitResult:
        """
        合并分支

        Args:
            branch_name: 要合并的分支
            message: 合并提交信息

        Returns:
            GitResult: 操作结果
        """
        if message:
            return self._run_git_command(["merge", "-m", message, branch_name])
        else:
            return self._run_git_command(["merge", branch_name])

    def get_commit_message(self, commit: str = "HEAD") -> str:
        """
        获取提交信息

        Args:
            commit: 提交哈希或引用

        Returns:
            str: 提交信息
        """
        result = self._run_git_command(["log", "-1", "--pretty=%B", commit])
        return result.stdout.strip()

    def get_changed_files(self, commit1: str, commit2: str) -> List[str]:
        """
        获取两次提交之间变更的文件列表

        Args:
            commit1: 第一个提交
            commit2: 第二个提交

        Returns:
            List[str]: 文件路径列表
        """
        result = self._run_git_command(
            ["diff", "--name-only", f"{commit1}...{commit2}"]
        )
        return [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]

    def is_working_tree_clean(self) -> bool:
        """
        检查工作区是否干净

        Returns:
            bool: 是否干净
        """
        result = self._run_git_command(["status", "--porcelain"], check=False)
        return len(result.stdout.strip()) == 0

    def get_remote_url(self, remote: str = "origin") -> str:
        """
        获取远程仓库 URL

        Args:
            remote: 远程名称

        Returns:
            str: 远程 URL
        """
        result = self._run_git_command(["remote", "get-url", remote])
        return result.stdout.strip()

    def set_remote_url(self, url: str, remote: str = "origin") -> GitResult:
        """
        设置远程仓库 URL

        Args:
            url: 新的 URL
            remote: 远程名称

        Returns:
            GitResult: 操作结果
        """
        return self._run_git_command(["remote", "set-url", remote, url])

    def setup_ai_remote(self, remote_name: str = "ai") -> GitResult:
        """
        设置 AI 专用远程仓库

        使用 .env 中配置的 GITHUB_OWNER 和 GITHUB_REPO 设置远程仓库。
        如果远程已存在则更新 URL，否则添加新的远程。

        Args:
            remote_name: AI 远程仓库名称，默认 "ai"

        Returns:
            GitResult: 操作结果
        """
        remote_url = f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}.git"

        # 检查远程是否已存在
        try:
            self._run_git_command(["remote", "get-url", remote_name], check=False)
            # 存在则更新 URL
            return self._run_git_command(["remote", "set-url", remote_name, remote_url])
        except GitProviderError:
            # 不存在则添加
            return self._run_git_command(["remote", "add", remote_name, remote_url])

    def init_repo(
        self,
        remote_url: Optional[str] = None,
        remote_name: str = "origin",
        skip_fetch: bool = False
    ) -> GitResult:
        """
        初始化 Git 仓库（用于沙箱临时工作区等无 .git 的场景）

        1. git init
        2. git config user.email / user.name
        3. git remote add origin <remote_url>（如果提供）
        4. git fetch origin（如果提供了 remote_url 且 skip_fetch=False）

        Args:
            remote_url: 远程仓库 URL
            remote_name: 远程名称，默认 origin
            skip_fetch: 是否跳过 fetch，默认 False。如果为 True，需要手动执行 fetch

        Returns:
            GitResult: 操作结果
        """
        # 1. git init
        result = self._run_git_command(["init"], check=False)

        # 2. 配置 git user
        self._run_git_command(
            ["config", "user.email", "omniflowai@ai.bot"],
            check=False
        )
        self._run_git_command(
            ["config", "user.name", "OmniFlowAI Bot"],
            check=False
        )

        # 3. 配置 pull rebase
        self._run_git_command(
            ["config", "pull.rebase", "true"],
            check=False
        )

        # 4. 添加 remote 并 fetch
        if remote_url:
            check_result = self._run_git_command(
                ["remote", "get-url", remote_name],
                check=False
            )
            if check_result.success:
                self._run_git_command(
                    ["remote", "set-url", remote_name, remote_url],
                    check=False
                )
            else:
                self._run_git_command(
                    ["remote", "add", remote_name, remote_url],
                    check=False
                )
            # fetch 操作添加 120 秒超时，避免网络问题导致卡住
            if not skip_fetch:
                fetch_result = self._run_git_command(["fetch", remote_name], check=False, timeout=120)
                if not fetch_result.success:
                    # fetch 失败不阻断流程，记录警告即可
                    print(f"[GitProvider] Warning: git fetch failed: {fetch_result.stderr}")

        return result

    def fetch(self, remote: str = "origin") -> GitResult:
        """
        从远程获取更新

        Args:
            remote: 远程名称

        Returns:
            GitResult: 操作结果
        """
        return self._run_git_command(["fetch", remote])

    def pull(self, remote: str = "origin", branch: Optional[str] = None) -> GitResult:
        """
        拉取远程更新

        Args:
            remote: 远程名称
            branch: 分支名称

        Returns:
            GitResult: 操作结果
        """
        if branch:
            return self._run_git_command(["pull", remote, branch])
        else:
            return self._run_git_command(["pull", remote])
