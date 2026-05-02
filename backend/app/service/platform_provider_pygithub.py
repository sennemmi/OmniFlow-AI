"""
代码托管平台集成服务 - PyGithub 重构版
使用 PyGithub 库替代手工 HTTP 调用

核心改进：
1. 使用 PyGithub 的 Github 对象操作 API（替代 httpx）
2. 更简洁的 API 调用（一行代码创建 PR）
3. 更好的异常处理
4. 自动处理分页和重试

依赖：
pip install PyGithub
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any

from app.core.config import settings
from app.core.logging import error

# PyGithub 导入
try:
    from github import Github, GithubException, BadCredentialsException
    from github.Repository import Repository
    from github.PullRequest import PullRequest
    PYGITHUB_AVAILABLE = True
except ImportError:
    PYGITHUB_AVAILABLE = False
    print("警告: PyGithub 未安装，将回退到旧版 platform_provider")


@dataclass
class PullRequestResult:
    """PR 创建结果"""
    success: bool
    pr_url: Optional[str]
    pr_number: Optional[int]
    error: Optional[str]
    raw_response: Optional[Dict[str, Any]] = None


class PlatformProviderError(Exception):
    """平台提供商错误"""
    pass


class BasePlatformProvider(ABC):
    """代码托管平台基类"""
    
    @abstractmethod
    async def create_pull_request(
        self,
        head_branch: str,
        title: str,
        body: str,
        base_branch: str = "main"
    ) -> PullRequestResult:
        """创建 Pull Request / Merge Request"""
        pass


class PyGithubProviderService(BasePlatformProvider):
    """
    GitHub 集成服务 - PyGithub 版
    
    使用 PyGithub 库封装 GitHub API 调用
    """
    
    def __init__(
        self,
        token: Optional[str] = None,
        owner: Optional[str] = None,
        repo: Optional[str] = None
    ):
        """
        初始化 GitHub 服务
        
        Args:
            token: GitHub Token
            owner: 仓库所有者
            repo: 仓库名
        """
        if not PYGITHUB_AVAILABLE:
            raise ImportError("PyGithub 未安装，请运行: pip install PyGithub")
        
        # 优先使用传入的参数，其次从 settings 读取，最后从环境变量读取
        self.token = token or settings.GITHUB_TOKEN or os.getenv("GITHUB_TOKEN")
        self.owner = owner or settings.GITHUB_OWNER or os.getenv("GITHUB_OWNER")
        self.repo = repo or settings.GITHUB_REPO or os.getenv("GITHUB_REPO")
        
        # 初始化 Github 客户端
        if self.token:
            self.github = Github(self.token)
        else:
            self.github = None
        
        # 缓存仓库对象
        self._repository: Optional[Repository] = None
    
    def _get_repository(self) -> Optional[Repository]:
        """获取仓库对象"""
        if not self.github:
            return None
        
        if self._repository is None:
            try:
                self._repository = self.github.get_repo(f"{self.owner}/{self.repo}")
            except Exception as e:
                print(f"[PyGithubProviderService] 获取仓库失败: {e}")
                return None
        
        return self._repository
    
    async def create_pull_request(
        self,
        head_branch: str,
        title: str,
        body: str,
        base_branch: str = "main"
    ) -> PullRequestResult:
        """
        创建 GitHub Pull Request
        
        使用 PyGithub，一行代码即可创建 PR
        
        Args:
            head_branch: 源分支（特性分支）
            title: PR 标题
            body: PR 描述
            base_branch: 目标分支，默认 main
            
        Returns:
            PullRequestResult: PR 创建结果
        """
        # 验证必要参数
        if not self.token:
            print("[PyGithubProviderService] 模拟发送 PR 请求（无真实 Token）")
            print(f"  - 仓库: {self.owner}/{self.repo}")
            print(f"  - 源分支: {head_branch}")
            print(f"  - 目标分支: {base_branch}")
            print(f"  - 标题: {title[:50]}...")
            print(f"  - 描述长度: {len(body)} 字符")
            
            return PullRequestResult(
                success=True,
                pr_url=f"https://github.com/{self.owner}/{self.repo}/pull/0",
                pr_number=0,
                error=None,
                raw_response={"simulated": True}
            )
        
        if not self.owner or not self.repo:
            return PullRequestResult(
                success=False,
                pr_url=None,
                pr_number=None,
                error="GitHub owner 或 repo 未配置"
            )
        
        try:
            print(f"[PyGithubProviderService] 创建 PR: {self.owner}/{self.repo}")
            print(f"  - 源分支: {head_branch} -> 目标分支: {base_branch}")
            
            # 获取仓库对象
            repo = self._get_repository()
            if not repo:
                return PullRequestResult(
                    success=False,
                    pr_url=None,
                    pr_number=None,
                    error="无法获取仓库对象"
                )
            
            # 使用 PyGithub 创建 PR（一行代码！）
            pr = repo.create_pull(
                title=title,
                body=body,
                head=head_branch,
                base=base_branch
            )
            
            print(f"[PyGithubProviderService] PR 创建成功: {pr.html_url}")
            
            return PullRequestResult(
                success=True,
                pr_url=pr.html_url,
                pr_number=pr.number,
                error=None,
                raw_response={
                    "id": pr.id,
                    "node_id": pr.node_id,
                    "state": pr.state,
                    "created_at": pr.created_at.isoformat() if pr.created_at else None
                }
            )
            
        except GithubException as e:
            # PyGithub 自动处理 HTTP 错误
            error_data = e.data if hasattr(e, 'data') else {}
            error_msg = error_data.get("message", str(e))
            
            # 检查是否是 PR 已存在
            if e.status == 422 and "already exists" in str(error_data).lower():
                print(f"[PyGithubProviderService] PR 已存在")
                return PullRequestResult(
                    success=True,
                    pr_url=None,
                    pr_number=None,
                    error="PR already exists",
                    raw_response=error_data
                )
            
            print(f"[PyGithubProviderService] PR 创建失败 ({e.status}): {error_msg}")
            return PullRequestResult(
                success=False,
                pr_url=None,
                pr_number=None,
                error=f"GitHub API error: {error_msg}",
                raw_response=error_data
            )
            
        except BadCredentialsException:
            error_msg = "GitHub Token 无效或已过期"
            print(f"[PyGithubProviderService] {error_msg}")
            return PullRequestResult(
                success=False,
                pr_url=None,
                pr_number=None,
                error=error_msg
            )
            
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            error("GitHub PR 创建失败", exc_info=True)
            return PullRequestResult(
                success=False,
                pr_url=None,
                pr_number=None,
                error=error_msg
            )
    
    async def get_pull_request(self, pr_number: int) -> Optional[Dict[str, Any]]:
        """
        获取 PR 详情
        
        Args:
            pr_number: PR 编号
            
        Returns:
            Optional[Dict]: PR 详情
        """
        try:
            repo = self._get_repository()
            if not repo:
                return None
            
            pr = repo.get_pull(pr_number)
            return {
                "number": pr.number,
                "title": pr.title,
                "body": pr.body,
                "state": pr.state,
                "url": pr.html_url,
                "created_at": pr.created_at.isoformat() if pr.created_at else None,
                "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
                "merged": pr.merged,
                "mergeable": pr.mergeable
            }
        except Exception as e:
            print(f"[PyGithubProviderService] 获取 PR 失败: {e}")
            return None
    
    async def list_pull_requests(
        self,
        state: str = "open",
        head: Optional[str] = None,
        base: Optional[str] = None
    ) -> list:
        """
        列出 PR
        
        Args:
            state: PR 状态 (open/closed/all)
            head: 源分支过滤
            base: 目标分支过滤
            
        Returns:
            list: PR 列表
        """
        try:
            repo = self._get_repository()
            if not repo:
                return []
            
            prs = repo.get_pulls(state=state, head=head, base=base)
            return [
                {
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "url": pr.html_url
                }
                for pr in prs
            ]
        except Exception as e:
            print(f"[PyGithubProviderService] 列出 PR 失败: {e}")
            return []
    
    def close(self):
        """关闭 Github 客户端"""
        if self.github:
            self.github.close()


def get_platform_provider(
    provider: str = "github",
    use_pygithub: bool = True
) -> BasePlatformProvider:
    """
    获取平台提供商实例
    
    Args:
        provider: 平台类型
        use_pygithub: 是否使用 PyGithub 版本
        
    Returns:
        BasePlatformProvider: 平台提供商实例
    """
    provider = provider.lower()
    
    if provider == "github":
        if use_pygithub and PYGITHUB_AVAILABLE:
            return PyGithubProviderService()
        else:
            # 回退到旧版
            from app.service.platform_provider import GitHubProviderService
            return GitHubProviderService()
    else:
        raise ValueError(f"不支持的平台类型: {provider}")
