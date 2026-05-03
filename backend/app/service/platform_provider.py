"""
平台提供商服务
支持 GitHub、GitLab 等代码托管平台的 PR/MR 创建
"""

from dataclasses import dataclass
from typing import Optional
import httpx

from app.core.config import settings


@dataclass
class PRResult:
    """PR 创建结果"""
    success: bool
    pr_url: str = ""
    pr_number: int = 0
    error: str = ""


class GitHubProviderService:
    """
    GitHub 平台服务

    负责：
    1. 创建 Pull Request
    2. 支持异步上下文管理器
    """

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.client.aclose()

    async def create_pull_request(
        self,
        head_branch: str,
        title: str,
        body: str,
        base_branch: str = "main"
    ) -> PRResult:
        """
        创建 Pull Request

        测试要求：
        1. 成功时返回 PRResult(success=True, pr_url=..., pr_number=...)
        2. 失败时 error 字段包含状态码数字（如 "422"）
        3. 网络异常时不抛出异常

        Args:
            head_branch: 源分支（包含变更的分支）
            title: PR 标题
            body: PR 描述
            base_branch: 目标分支，默认 main

        Returns:
            PRResult: 创建结果
        """
        url = f"https://api.github.com/repos/{settings.GITHUB_REPO}/pulls"
        headers = {
            "Authorization": f"token {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch
        }

        try:
            resp = await self.client.post(url, json=payload, headers=headers)
            if resp.status_code == 201:
                data = resp.json()
                return PRResult(
                    success=True,
                    pr_url=data["html_url"],
                    pr_number=data["number"]
                )
            else:
                # 关键修复：测试用例 Class 3 要求包含状态码数字
                return PRResult(
                    success=False,
                    error=f"创建 PR 失败 ({resp.status_code}): {resp.text}"
                )
        except Exception as e:
            return PRResult(success=False, error=f"网络异常: {str(e)}")


class GitLabProviderService:
    """
    GitLab 平台服务（预留接口）

    未来可支持 GitLab MR 创建
    """

    def __init__(self):
        self.token = getattr(settings, "GITLAB_TOKEN", None)
        self.project_id = getattr(settings, "GITLAB_PROJECT_ID", None)
        self.base_url = getattr(settings, "GITLAB_URL", "https://gitlab.com")
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        headers = {}
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token

        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=30.0
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.client:
            await self.client.aclose()

    async def create_merge_request(
        self,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str
    ) -> PRResult:
        """
        创建 Merge Request（预留）

        Args:
            source_branch: 源分支
            target_branch: 目标分支
            title: MR 标题
            description: MR 描述

        Returns:
            PRResult: 创建结果
        """
        return PRResult(
            success=False,
            error="GitLab 支持尚未实现"
        )
