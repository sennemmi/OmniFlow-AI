"""
PR 描述生成服务
负责生成语义化的 Pull Request 描述
"""

import json
import logging
from typing import Dict, Any, List

from app.service.git_provider import GitProviderService
from app.core.config import settings

logger = logging.getLogger(__name__)

# 模块级导入，便于测试时 patch
try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None


class PRGeneratorService:
    """
    PR 描述生成服务

    职责：
    1. 根据多 Agent 输出生成 PR 描述
    2. 使用 LLM 生成语义化摘要和行级 diff 摘要
    3. 格式化文件变更列表
    4. 生成测试建议和依赖变更提示
    """

    @classmethod
    async def generate_pr_description(
        cls,
        pipeline_id: int,
        multi_agent_output: Dict[str, Any],
        execution_summary: Dict[str, Any],
        git_service: GitProviderService
    ) -> str:
        """
        生成语义化的 PR 描述（支持多 Agent 输出，LLM 驱动）

        测试 Class 5 要求：
        1. 包含 Pipeline ID
        2. 包含变更摘要、行级变更摘要
        3. 包含代码文件、测试文件分类
        4. 包含变更统计
        5. 包含审查清单

        Args:
            pipeline_id: Pipeline ID
            multi_agent_output: 多 Agent 协调器输出
            execution_summary: 代码执行摘要
            git_service: Git 服务实例

        Returns:
            str: PR 描述文本
        """
        git_info = git_service.create_commit_summary()

        # 降级逻辑 (Class 2)
        try:
            llm_res = await cls._generate_llm_summary(
                requirement=multi_agent_output.get("summary", ""),
                diff_text=git_info["diff_text"],
                diff_stat=git_info["diff_stat"]
            )
            semantic_summary = llm_res["semantic_summary"]
            diff_summary = llm_res["diff_summary"]
        except Exception:
            semantic_summary = multi_agent_output.get("summary", "无摘要")
            diff_summary = git_info["diff_stat"] or "文件变更"

        # 分类逻辑 (Class 5)
        code_files = []
        test_files = []
        for f in multi_agent_output.get("files", []):
            path = f.get("file_path", "")
            if "test" in path.lower():
                test_files.append(f"- `{path}`")
            else:
                code_files.append(f"- `{path}`")

        # Markdown 组装 (Class 5 必需区块)
        lines = [
            f"## Pipeline ID: #{pipeline_id}",
            "### 变更摘要",
            semantic_summary,
            "",
            "### 行级变更摘要",
            diff_summary,
            "",
            "### 代码文件",
            "\n".join(code_files) if code_files else "无",
            "",
            "### 测试文件",
            "\n".join(test_files) if test_files else "无",
            "",
            "### 变更统计",  # 关键标题
            f"- 总计: {execution_summary.get('total', 0)}",
            f"- 成功: {execution_summary.get('success', 0)}",
            f"- 失败: {execution_summary.get('failed', 0)}",
            "",
            "### 审查清单",  # 关键标题
            "- [ ] 代码逻辑正确",
            "- [ ] 测试已覆盖"
        ]
        return "\n".join(lines)

    @classmethod
    async def _generate_llm_summary(cls, requirement: str, diff_text: str, diff_stat: str) -> Dict[str, str]:
        """
        调用 LLM 生成两段摘要：语义化摘要和行级 diff 摘要

        Args:
            requirement: 需求描述
            diff_text: Git diff 文本
            diff_stat: Git diff 统计

        Returns:
            Dict: 包含 semantic_summary 和 diff_summary
        """
        try:
            # 检查 ChatOpenAI 是否可用
            if ChatOpenAI is None:
                raise ImportError("langchain_openai not available")

            # 创建 LLM 实例
            llm = ChatOpenAI(
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                base_url=settings.llm_api_base,
            )

            # 截断 diff_text 防止 token 超限
            truncated_diff = diff_text[:4000] if len(diff_text) > 4000 else diff_text
            if len(diff_text) > 4000:
                truncated_diff += "\n... (diff 已截断)"

            prompt = f"""你是一个代码审查助手，请根据以下信息生成 PR 描述。

需求描述：
{requirement}

Git diff stat：
{diff_stat}

Git diff（部分）：
{truncated_diff}

请以 JSON 格式返回，包含两个字段：
1. semantic_summary: 用一段话描述本次改动的业务含义（改了什么、为什么改），100-200字
2. diff_summary: 按文件列出主要的行级变更要点（每个文件1-2句话），突出关键逻辑变更

只返回 JSON，不要其他内容。格式示例：
{{"semantic_summary": "...", "diff_summary": "..."}}"""

            response = await llm.ainvoke(prompt)

            # 解析 JSON 响应
            try:
                content = response.content if hasattr(response, 'content') else str(response)
                # 尝试提取 JSON 部分
                json_start = content.find('{')
                json_end = content.rfind('}')
                if json_start != -1 and json_end != -1:
                    json_str = content[json_start:json_end + 1]
                    result = json.loads(json_str)
                    return {
                        "semantic_summary": result.get("semantic_summary", requirement),
                        "diff_summary": result.get("diff_summary", diff_stat)
                    }
                else:
                    return {
                        "semantic_summary": requirement,
                        "diff_summary": diff_stat
                    }
            except json.JSONDecodeError:
                # 如果解析失败，返回默认值
                return {
                    "semantic_summary": requirement,
                    "diff_summary": diff_stat
                }

        except Exception as e:
            # LLM 调用失败时返回默认值
            logger.error(f"[PRGeneratorService] LLM 摘要生成失败: {e}")
            return {
                "semantic_summary": requirement,
                "diff_summary": diff_stat
            }
