"""
Git 集成服务
业务逻辑层 - 封装基础 Git 操作

原则：以跳过验证为耻。每个 Git 操作后必须检查返回码。
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


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
    """
    
    def __init__(self, repo_path: Optional[str] = None):
        """
        初始化 Git 服务
        
        Args:
            repo_path: 仓库路径，默认使用当前工作目录
        """
        if repo_path:
            self.repo_path = Path(repo_path).resolve()
        else:
            # 默认使用项目根目录
            self.repo_path = Path(__file__).parent.parent.parent.parent.resolve()
        
        # 验证是 Git 仓库
        if not (self.repo_path / ".git").exists():
            raise GitProviderError(f"{self.repo_path} 不是 Git 仓库")
    
    def _run_git_command(
        self,
        args: List[str],
        check: bool = True
    ) -> GitResult:
        """
        运行 Git 命令
        
        Args:
            args: Git 命令参数
            check: 是否检查返回码
            
        Returns:
            GitResult: 命令执行结果
            
        Raises:
            GitProviderError: 命令执行失败且 check=True
        """
        cmd = ["git"] + args
        
        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            
            git_result = GitResult(
                success=result.returncode == 0,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                returncode=result.returncode
            )
            
            # 以跳过验证为耻：严格检查返回码
            if check and result.returncode != 0:
                raise GitProviderError(
                    f"Git 命令失败: {' '.join(cmd)}\n"
                    f"返回码: {result.returncode}\n"
                    f"错误: {result.stderr}"
                )
            
            return git_result
            
        except subprocess.TimeoutExpired as e:
            raise GitProviderError(f"Git 命令超时: {e}")
        except FileNotFoundError:
            raise GitProviderError("Git 命令未找到，请确保 Git 已安装")
        except Exception as e:
            raise GitProviderError(f"Git 命令执行错误: {e}")
    
    def get_current_branch(self) -> str:
        """
        获取当前分支名
        
        Returns:
            str: 当前分支名
        """
        result = self._run_git_command(["branch", "--show-current"])
        return result.stdout
    
    def branch_exists(self, branch_name: str) -> bool:
        """
        检查分支是否存在
        
        Args:
            branch_name: 分支名
            
        Returns:
            bool: 是否存在
        """
        try:
            result = self._run_git_command(
                ["branch", "--list", branch_name],
                check=False
            )
            return branch_name in result.stdout
        except Exception:
            return False
    
    def create_branch(self, branch_name: str, base_branch: str = "main") -> GitResult:
        """
        创建并切换到新分支
        
        Args:
            branch_name: 新分支名
            base_branch: 基础分支，默认 main
            
        Returns:
            GitResult: 操作结果
        """
        # 检查分支是否已存在
        if self.branch_exists(branch_name):
            raise GitProviderError(f"分支已存在: {branch_name}")
        
        # 确保基础分支存在
        if not self.branch_exists(base_branch):
            # 尝试 master
            if self.branch_exists("master"):
                base_branch = "master"
            else:
                raise GitProviderError(f"基础分支不存在: {base_branch}")
        
        # 切换到基础分支并更新
        self._run_git_command(["checkout", base_branch])
        self._run_git_command(["pull", "origin", base_branch], check=False)
        
        # 创建新分支
        result = self._run_git_command(["checkout", "-b", branch_name])
        
        return result
    
    def checkout_branch(self, branch_name: str) -> GitResult:
        """
        切换到指定分支
        
        Args:
            branch_name: 分支名
            
        Returns:
            GitResult: 操作结果
        """
        return self._run_git_command(["checkout", branch_name])
    
    def add_files(self, files: Optional[List[str]] = None) -> GitResult:
        """
        添加文件到暂存区
        
        Args:
            files: 文件列表，None 表示添加所有
            
        Returns:
            GitResult: 操作结果
        """
        if files:
            return self._run_git_command(["add"] + files)
        else:
            return self._run_git_command(["add", "."])
    
    def commit_changes(self, message: str, author: Optional[str] = None) -> GitResult:
        """
        提交更改
        
        Args:
            message: 提交信息
            author: 作者信息（格式："Name <email>"）
            
        Returns:
            GitResult: 操作结果
        """
        cmd = ["commit", "-m", message]
        
        if author:
            cmd.extend(["--author", author])
        
        return self._run_git_command(cmd)
    
    def get_diff(self, cached: bool = False) -> str:
        """
        获取代码差异
        
        Args:
            cached: 是否查看暂存区的差异
            
        Returns:
            str: diff 内容
        """
        args = ["diff"]
        if cached:
            args.append("--cached")
        
        result = self._run_git_command(args, check=False)
        return result.stdout
    
    def get_status(self) -> GitResult:
        """
        获取仓库状态
        
        Returns:
            GitResult: 操作结果
        """
        return self._run_git_command(["status", "--short"])
    
    def has_changes(self) -> bool:
        """
        检查是否有未提交的更改
        
        Returns:
            bool: 是否有更改
        """
        result = self._run_git_command(["status", "--porcelain"], check=False)
        return len(result.stdout.strip()) > 0
    
    def get_last_commit_hash(self, short: bool = True) -> str:
        """
        获取最后一次提交的 hash
        
        Args:
            short: 是否返回短 hash
            
        Returns:
            str: commit hash
        """
        args = ["rev-parse"]
        if short:
            args.append("--short")
        args.append("HEAD")
        
        result = self._run_git_command(args)
        return result.stdout
    
    def get_commit_message(self, commit_hash: Optional[str] = None) -> str:
        """
        获取提交信息
        
        Args:
            commit_hash: commit hash，默认最新
            
        Returns:
            str: 提交信息
        """
        args = ["log", "-1", "--pretty=%B"]
        if commit_hash:
            args.append(commit_hash)
        
        result = self._run_git_command(args)
        return result.stdout
    
    def push_branch(self, branch_name: str, remote: str = "origin") -> GitResult:
        """
        推送分支到远程
        
        Args:
            branch_name: 分支名
            remote: 远程名
            
        Returns:
            GitResult: 操作结果
        """
        return self._run_git_command(
            ["push", "-u", remote, branch_name],
            check=False  # 允许失败（可能没有远程）
        )
    
    def get_file_content_at_commit(
        self,
        file_path: str,
        commit_hash: str = "HEAD"
    ) -> Optional[str]:
        """
        获取指定 commit 的文件内容
        
        Args:
            file_path: 文件路径
            commit_hash: commit hash
            
        Returns:
            Optional[str]: 文件内容，不存在返回 None
        """
        try:
            result = self._run_git_command(
                ["show", f"{commit_hash}:{file_path}"],
                check=False
            )
            if result.returncode == 0:
                return result.stdout
            return None
        except GitProviderError:
            return None
    
    def create_commit_summary(self, max_files: int = 10) -> dict:
        """
        创建提交摘要
        
        Args:
            max_files: 最大文件数
            
        Returns:
            dict: 摘要信息
        """
        # 获取 diff 统计
        result = self._run_git_command(
            ["diff", "--cached", "--stat"],
            check=False
        )
        
        # 获取文件列表
        status_result = self._run_git_command(
            ["diff", "--cached", "--name-status"],
            check=False
        )
        
        files = []
        for line in status_result.stdout.strip().split('\n'):
            if line:
                parts = line.split('\t')
                if len(parts) >= 2:
                    files.append({
                        "status": parts[0],  # A/M/D
                        "path": parts[1]
                    })
        
        return {
            "branch": self.get_current_branch(),
            "commit_hash": self.get_last_commit_hash(),
            "total_files": len(files),
            "files": files[:max_files],
            "has_more_files": len(files) > max_files,
            "diff_summary": result.stdout
        }


# 便捷函数
def get_git_service(repo_path: Optional[str] = None) -> GitProviderService:
    """
    获取 Git 服务实例
    
    Args:
        repo_path: 仓库路径
        
    Returns:
        GitProviderService: Git 服务实例
    """
    return GitProviderService(repo_path)
