"""
Git 集成服务 - GitPython 重构版
使用 GitPython 库替代 subprocess 调用

核心改进：
1. 使用 GitPython 的 Repo 对象操作仓库（替代 subprocess）
2. 更简洁的 API 调用
3. 更好的异常处理
4. 类型安全

依赖：
pip install GitPython
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

from app.core.config import settings

# GitPython 导入
try:
    import git
    from git import Repo, GitCommandError
    GITPYTHON_AVAILABLE = True
except ImportError:
    GITPYTHON_AVAILABLE = False
    print("警告: GitPython 未安装，将回退到旧版 git_provider")


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


class GitPythonProviderService:
    """
    Git 集成服务 - GitPython 版
    
    使用 GitPython 库封装基础 Git 操作
    """
    
    def __init__(self, repo_path: Optional[str] = None):
        """
        初始化 Git 服务
        
        Args:
            repo_path: 仓库路径，默认使用 settings.TARGET_PROJECT_PATH
        """
        if not GITPYTHON_AVAILABLE:
            raise ImportError("GitPython 未安装，请运行: pip install GitPython")
        
        # 确定仓库路径
        if repo_path:
            self.repo_path = Path(repo_path).resolve()
        else:
            target_path = settings.TARGET_PROJECT_PATH
            
            if not target_path:
                raise GitProviderError(
                    "TARGET_PROJECT_PATH 未配置。\n"
                    "请在 .env 中设置 TARGET_PROJECT_PATH=workspace/your-repo\n"
                    "并确保目录下已 clone 目标仓库。"
                )
            
            target_path_obj = Path(target_path)
            if not target_path_obj.is_absolute():
                backend_dir = Path(__file__).parent.parent.parent
                project_root = backend_dir.parent
                target_path_obj = project_root / target_path
            
            self.repo_path = target_path_obj.resolve()
        
        # 初始化 Repo 对象
        try:
            self.repo = Repo(str(self.repo_path))
        except git.InvalidGitRepositoryError:
            raise GitProviderError(
                f"{self.repo_path} 不是 Git 仓库。\n"
                f"请先在 workspace 目录下 clone 目标仓库：\n"
                f"  git clone https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}.git {settings.TARGET_PROJECT_PATH}"
            )
    
    def _handle_git_error(self, e: GitCommandError) -> GitResult:
        """处理 Git 命令错误"""
        return GitResult(
            success=False,
            stdout=e.stdout if hasattr(e, 'stdout') else "",
            stderr=e.stderr if hasattr(e, 'stderr') else str(e),
            returncode=e.status if hasattr(e, 'status') else 1
        )
    
    def get_current_branch(self) -> str:
        """获取当前分支名"""
        try:
            return self.repo.active_branch.name
        except Exception as e:
            raise GitProviderError(f"获取当前分支失败: {e}")
    
    def branch_exists(self, branch_name: str) -> bool:
        """检查分支是否存在"""
        try:
            # 检查本地分支
            if branch_name in [b.name for b in self.repo.branches]:
                return True
            # 检查远程分支
            if branch_name in [b.name.split('/')[-1] for b in self.repo.remote().refs]:
                return True
            return False
        except Exception:
            return False
    
    def create_branch(self, branch_name: str, base_branch: str = "main") -> GitResult:
        """
        创建并切换到新分支
        
        Args:
            branch_name: 新分支名
            base_branch: 基础分支
        """
        try:
            # 检查分支是否已存在
            if self.branch_exists(branch_name):
                raise GitProviderError(f"分支已存在: {branch_name}")
            
            # 确保基础分支存在
            if not self.branch_exists(base_branch):
                if self.branch_exists("master"):
                    base_branch = "master"
                else:
                    raise GitProviderError(f"基础分支不存在: {base_branch}")
            
            # 切换到基础分支并更新（先 stash 本地修改）
            try:
                self.repo.git.stash("push", "-m", "Auto-stash before creating branch")
            except GitCommandError:
                pass  # 忽略 stash 失败（可能没有本地修改）
            self.repo.git.checkout(base_branch)
            try:
                self.repo.git.pull("origin", base_branch)
            except GitCommandError:
                pass  # 忽略 pull 失败
            
            # 创建并切换到新分支
            new_branch = self.repo.create_head(branch_name)
            new_branch.checkout()
            
            return GitResult(
                success=True,
                stdout=f"创建并切换到分支: {branch_name}",
                stderr="",
                returncode=0
            )
            
        except GitCommandError as e:
            return self._handle_git_error(e)
        except GitProviderError:
            raise
        except Exception as e:
            raise GitProviderError(f"创建分支失败: {e}")
    
    def checkout_branch(self, branch_name: str, force: bool = False) -> GitResult:
        """切换到指定分支"""
        try:
            if force:
                self.repo.git.checkout(branch_name, force=True)
            else:
                # 先 stash 本地修改
                try:
                    self.repo.git.stash("push", "-m", "Auto-stash before checkout")
                except GitCommandError:
                    pass  # 忽略 stash 失败
                self.repo.git.checkout(branch_name)
                # 尝试恢复 stash
                try:
                    self.repo.git.stash("pop")
                except GitCommandError:
                    pass  # 忽略 pop 失败
            return GitResult(
                success=True,
                stdout=f"切换到分支: {branch_name}",
                stderr="",
                returncode=0
            )
        except GitCommandError as e:
            return self._handle_git_error(e)
    
    def add_files(self, files: Optional[List[str]] = None) -> GitResult:
        """
        添加文件到暂存区
        
        Args:
            files: 文件列表，None 表示添加所有
        """
        try:
            if files:
                self.repo.git.add(files)
            else:
                self.repo.git.add(".")
            
            return GitResult(
                success=True,
                stdout="文件已添加到暂存区",
                stderr="",
                returncode=0
            )
        except GitCommandError as e:
            return self._handle_git_error(e)
    
    def commit_changes(self, message: str, author: Optional[str] = None) -> GitResult:
        """
        提交更改
        
        Args:
            message: 提交信息
            author: 作者信息
        """
        try:
            # 确保有更改可以提交
            if not self.has_changes():
                return GitResult(
                    success=True,
                    stdout="没有需要提交的更改",
                    stderr="",
                    returncode=0
                )
            
            # 提交
            if author:
                # 解析作者信息
                import re
                match = re.match(r"(.+) <(.+)>", author)
                if match:
                    name, email = match.groups()
                    self.repo.git.commit(
                        "-m", message,
                        author=f"{name} <{email}>"
                    )
                else:
                    self.repo.git.commit("-m", message)
            else:
                self.repo.git.commit("-m", message)
            
            return GitResult(
                success=True,
                stdout=f"提交成功: {message[:50]}",
                stderr="",
                returncode=0
            )
            
        except GitCommandError as e:
            return self._handle_git_error(e)
    
    def get_diff(self, cached: bool = False) -> str:
        """获取代码差异"""
        try:
            if cached:
                return self.repo.git.diff("--cached")
            else:
                return self.repo.git.diff()
        except GitCommandError:
            return ""
    
    def get_status(self) -> GitResult:
        """获取仓库状态"""
        try:
            status = self.repo.git.status("--short")
            return GitResult(
                success=True,
                stdout=status,
                stderr="",
                returncode=0
            )
        except GitCommandError as e:
            return self._handle_git_error(e)
    
    def has_changes(self) -> bool:
        """检查是否有未提交的更改"""
        try:
            # 检查暂存区
            if self.repo.index.diff("HEAD"):
                return True
            # 检查工作区
            if self.repo.index.diff(None):
                return True
            # 检查未跟踪文件
            if self.repo.untracked_files:
                return True
            return False
        except Exception:
            return False
    
    def get_last_commit_hash(self, short: bool = True) -> str:
        """获取最后一次提交的 hash"""
        try:
            if short:
                return self.repo.head.commit.hexsha[:7]
            else:
                return self.repo.head.commit.hexsha
        except Exception as e:
            raise GitProviderError(f"获取 commit hash 失败: {e}")
    
    def get_commit_message(self, commit_hash: Optional[str] = None) -> str:
        """获取提交信息"""
        try:
            if commit_hash:
                commit = self.repo.commit(commit_hash)
            else:
                commit = self.repo.head.commit
            return commit.message
        except Exception as e:
            raise GitProviderError(f"获取提交信息失败: {e}")
    
    def _ensure_remote_url(self) -> bool:
        """确保远程仓库 URL 正确设置"""
        token = settings.GITHUB_TOKEN
        owner = settings.GITHUB_OWNER
        repo = settings.GITHUB_REPO
        
        if not all([token, owner, repo]):
            print("[GitPythonProviderService] 警告: GitHub 配置不完整")
            return False
        
        try:
            remote = self.repo.remote("origin")
            current_url = remote.url
            
            # 构建带 Token 的远程 URL
            remote_url = f"https://{token}@github.com/{owner}/{repo}.git"
            
            # 如果当前 URL 不包含 token，则更新
            if token not in current_url:
                print(f"[GitPythonProviderService] 锁定远程地址到: {owner}/{repo}")
                remote.set_url(remote_url)
            
            return True
        except Exception as e:
            print(f"[GitPythonProviderService] 设置远程地址失败: {e}")
            return False
    
    def push_branch(self, branch_name: str, remote: str = "origin") -> GitResult:
        """推送分支到远程"""
        try:
            # 锁定远程地址
            self._ensure_remote_url()
            
            # 推送
            origin = self.repo.remote(remote)
            push_info = origin.push(branch_name, set_upstream=True)
            
            # 检查推送结果
            for info in push_info:
                if info.flags & info.ERROR:
                    return GitResult(
                        success=False,
                        stdout="",
                        stderr=f"推送失败: {info.summary}",
                        returncode=1
                    )
            
            return GitResult(
                success=True,
                stdout=f"成功推送到 {remote}/{branch_name}",
                stderr="",
                returncode=0
            )
            
        except GitCommandError as e:
            return self._handle_git_error(e)
        except Exception as e:
            return GitResult(
                success=False,
                stdout="",
                stderr=str(e),
                returncode=1
            )
    
    def get_file_content_at_commit(
        self,
        file_path: str,
        commit_hash: str = "HEAD"
    ) -> Optional[str]:
        """获取指定 commit 的文件内容"""
        try:
            commit = self.repo.commit(commit_hash)
            blob = commit.tree / file_path
            return blob.data_stream.read().decode('utf-8')
        except Exception:
            return None
    
    def create_commit_summary(self, max_files: int = 10) -> Dict[str, Any]:
        """创建提交摘要"""
        try:
            # 获取暂存区的文件
            diff_index = self.repo.index.diff("HEAD")
            
            files = []
            for diff_item in diff_index:
                files.append({
                    "status": diff_item.change_type[0].upper() if diff_item.change_type else "M",
                    "path": diff_item.a_path or diff_item.b_path
                })
            
            # 获取 diff 统计
            diff_stat = self.repo.git.diff("--cached", "--stat")
            
            return {
                "branch": self.get_current_branch(),
                "commit_hash": self.get_last_commit_hash(),
                "total_files": len(files),
                "files": files[:max_files],
                "has_more_files": len(files) > max_files,
                "diff_summary": diff_stat
            }
            
        except Exception as e:
            return {
                "branch": self.get_current_branch(),
                "commit_hash": "",
                "total_files": 0,
                "files": [],
                "has_more_files": False,
                "diff_summary": str(e)
            }


def get_git_service(
    repo_path: Optional[str] = None,
    use_gitpython: bool = True
) -> Any:
    """
    获取 Git 服务实例
    
    Args:
        repo_path: 仓库路径
        use_gitpython: 是否使用 GitPython 版本
        
    Returns:
        Git 服务实例
    """
    if use_gitpython and GITPYTHON_AVAILABLE:
        return GitPythonProviderService(repo_path)
    else:
        # 回退到旧版
        from app.service.git_provider import GitProviderService
        return GitProviderService(repo_path)
