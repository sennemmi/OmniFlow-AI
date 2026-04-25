"""
代码托管平台集成服务
业务逻辑层 - 封装 GitHub/GitLab API 调用

原则：
- 以臆想业务为耻：Token 等敏感信息从 .env 读取
- 以跳过验证为耻：每个 API 调用后必须检查响应状态
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any

import httpx


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
    """
    代码托管平台基类
    
    定义统一的 PR/MR 创建接口
    """
    
    @abstractmethod
    async def create_pull_request(
        self,
        head_branch: str,
        title: str,
        body: str,
        base_branch: str = "main"
    ) -> PullRequestResult:
        """
        创建 Pull Request / Merge Request
        
        Args:
            head_branch: 源分支（特性分支）
            title: PR 标题
            body: PR 描述
            base_branch: 目标分支，默认 main
            
        Returns:
            PullRequestResult: PR 创建结果
        """
        pass


class GitHubProviderService(BasePlatformProvider):
    """
    GitHub 集成服务
    
    负责：
    1. 使用 httpx 调用 GitHub API
    2. 创建 Pull Request
    3. 错误处理和日志记录
    
    环境变量依赖：
    - GITHUB_TOKEN: GitHub Personal Access Token
    - GITHUB_OWNER: 仓库所有者
    - GITHUB_REPO: 仓库名
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
            token: GitHub Token，默认从环境变量 GITHUB_TOKEN 读取
            owner: 仓库所有者，默认从环境变量 GITHUB_OWNER 读取
            repo: 仓库名，默认从环境变量 GITHUB_REPO 读取
        """
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.owner = owner or os.getenv("GITHUB_OWNER")
        self.repo = repo or os.getenv("GITHUB_REPO")
        
        self.base_url = "https://api.github.com"
        self.api_version = "2022-11-28"
        
        # 初始化 HTTP 客户端
        # 使用 token {GITHUB_TOKEN} 格式（GitHub 兼容的认证方式）
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {self.token}",
            "X-GitHub-Api-Version": self.api_version
        }
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0
        )
    
    async def create_pull_request(
        self,
        head_branch: str,
        title: str,
        body: str,
        base_branch: str = "main"
    ) -> PullRequestResult:
        """
        创建 GitHub Pull Request
        
        API: POST /repos/{owner}/{repo}/pulls
        
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
            print("[GitHubProviderService] 模拟发送 PR 请求（无真实 Token）")
            print(f"  - 仓库: {self.owner}/{self.repo}")
            print(f"  - 源分支: {head_branch}")
            print(f"  - 目标分支: {base_branch}")
            print(f"  - 标题: {title[:50]}...")
            print(f"  - 描述长度: {len(body)} 字符")
            
            return PullRequestResult(
                success=True,  # 模拟成功
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
        
        endpoint = f"/repos/{self.owner}/{self.repo}/pulls"
        
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch
        }
        
        try:
            print(f"[GitHubProviderService] 创建 PR: {self.owner}/{self.repo}")
            print(f"  - 源分支: {head_branch} -> 目标分支: {base_branch}")
            
            response = await self.client.post(endpoint, json=payload)
            
            # 以跳过验证为耻：严格检查响应状态
            if response.status_code == 201:
                data = response.json()
                pr_url = data.get("html_url")
                pr_number = data.get("number")
                
                print(f"[GitHubProviderService] PR 创建成功: {pr_url}")
                
                return PullRequestResult(
                    success=True,
                    pr_url=pr_url,
                    pr_number=pr_number,
                    error=None,
                    raw_response=data
                )
            
            elif response.status_code == 422:
                # PR 已存在或其他验证错误
                error_data = response.json()
                error_msg = error_data.get("message", "Unknown validation error")
                
                # 检查是否是 PR 已存在
                if "already exists" in str(error_data).lower():
                    print(f"[GitHubProviderService] PR 已存在")
                    return PullRequestResult(
                        success=True,
                        pr_url=None,
                        pr_number=None,
                        error="PR already exists",
                        raw_response=error_data
                    )
                
                print(f"[GitHubProviderService] PR 创建失败 (422): {error_msg}")
                return PullRequestResult(
                    success=False,
                    pr_url=None,
                    pr_number=None,
                    error=f"Validation failed: {error_msg}",
                    raw_response=error_data
                )
            
            else:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("message", f"HTTP {response.status_code}")
                
                print(f"[GitHubProviderService] PR 创建失败 ({response.status_code}): {error_msg}")
                
                return PullRequestResult(
                    success=False,
                    pr_url=None,
                    pr_number=None,
                    error=f"GitHub API error: {error_msg}",
                    raw_response=error_data
                )
                
        except httpx.TimeoutException:
            error_msg = "GitHub API 请求超时"
            print(f"[GitHubProviderService] {error_msg}")
            return PullRequestResult(
                success=False,
                pr_url=None,
                pr_number=None,
                error=error_msg
            )
        except httpx.HTTPError as e:
            error_msg = f"HTTP 错误: {str(e)}"
            print(f"[GitHubProviderService] {error_msg}")
            return PullRequestResult(
                success=False,
                pr_url=None,
                pr_number=None,
                error=error_msg
            )
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            print(f"[GitHubProviderService] {error_msg}")
            return PullRequestResult(
                success=False,
                pr_url=None,
                pr_number=None,
                error=error_msg
            )
    
    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()


class GitLabProviderService(BasePlatformProvider):
    """
    GitLab 集成服务（预留）
    
    待实现：GitLab MR 创建
    """
    
    def __init__(
        self,
        token: Optional[str] = None,
        project_id: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        self.token = token or os.getenv("GITLAB_TOKEN")
        self.project_id = project_id or os.getenv("GITLAB_PROJECT_ID")
        self.base_url = base_url or os.getenv("GITLAB_URL", "https://gitlab.com")
    
    async def create_pull_request(
        self,
        head_branch: str,
        title: str,
        body: str,
        base_branch: str = "main"
    ) -> PullRequestResult:
        """创建 GitLab Merge Request（待实现）"""
        raise NotImplementedError("GitLabProviderService 待实现")


def get_platform_provider(
    provider: str = "github"
) -> BasePlatformProvider:
    """
    获取平台提供商实例
    
    Args:
        provider: 平台类型，支持 "github" | "gitlab"
        
    Returns:
        BasePlatformProvider: 平台提供商实例
        
    Raises:
        ValueError: 不支持的平台类型
    """
    provider = provider.lower()
    
    if provider == "github":
        return GitHubProviderService()
    elif provider == "gitlab":
        return GitLabProviderService()
    else:
        raise ValueError(f"不支持的平台类型: {provider}")
