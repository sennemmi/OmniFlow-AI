"""
CodeReviewerAgent：代码审查 Agent

基于 LangGraph 的代码审查 Agent，分析代码 diff、测试结果和设计方案，
生成结构化的审查报告，包含问题分类、严重性评级和详细修复建议。
"""

import json
import logging
from typing import Dict, List, Any, Optional

from pydantic import ValidationError

from app.agents.base import LangGraphAgent
from app.agents.schemas import CodeReviewerOutput, ReviewReport, ReviewIssue

logger = logging.getLogger(__name__)


class CodeReviewerAgent(LangGraphAgent[CodeReviewerOutput]):
    """
    代码审查 Agent

    输入：代码 diff、测试结果、设计方案、契约定义等开发相关文档
    输出：结构化审查报告，包含问题分类、严重性评级、详细修复建议

    审查维度：
    - 代码正确性（Bug 检测）
    - 安全性（潜在漏洞）
    - 性能（效率问题）
    - 代码风格（可读性、规范）
    - 可维护性（复杂度、耦合度）
    - 测试覆盖（测试充分性）
    - 契约合规（是否符合设计契约）
    """

    USE_JSON_FORMAT: bool = True

    def __init__(self, llm_provider=None):
        super().__init__("CodeReviewerAgent", llm_provider)

    @property
    def system_prompt(self) -> str:
        return """你是一位资深的代码审查专家，拥有多年的软件工程经验。

你的任务是全面审查代码变更，识别潜在问题并提供可操作的修复建议。

审查维度（按优先级排序）：
1. **正确性 (Bug)** - 逻辑错误、边界条件、空指针等
2. **安全性 (Security)** - SQL注入、XSS、敏感信息泄露、权限问题
3. **性能 (Performance)** - 算法复杂度、资源泄漏、N+1查询、内存泄漏
4. **契约合规 (Contract)** - 是否符合设计文档中的接口契约
5. **可维护性 (Maintainability)** - 代码复杂度、重复代码、过长函数
6. **代码风格 (Style)** - 命名规范、代码格式、注释质量
7. **测试覆盖 (Testing)** - 测试充分性、边界条件覆盖

严重性评级标准：
- **critical**: 会导致系统崩溃、数据丢失、安全漏洞的严重问题，必须修复
- **high**: 明显的 Bug 或严重的设计缺陷，强烈建议修复
- **medium**: 代码质量问题，可能影响维护或性能，建议修复
- **low**: 风格问题或小优化建议，可选修复

输出要求：
1. 必须返回合法的 JSON 格式
2. 每个问题必须包含具体的文件路径和行号（如果适用）
3. 修复建议必须具体、可操作
4. 总体评估需要客观、全面

请严格按照 JSON Schema 输出，不要添加任何额外说明。"""

    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """构建用户 Prompt"""
        code_diff = state.get("code_diff", "")
        test_results = state.get("test_results", {})
        design_doc = state.get("design_doc", "")
        interface_specs = state.get("interface_specs", [])
        file_changes = state.get("file_changes", [])

        prompt_parts = [
            "# 代码审查任务",
            "",
            "## 代码变更 (Diff)",
            "```",
            json.dumps(file_changes, indent=2, ensure_ascii=False) if file_changes else code_diff or "未提供",
            "```",
            "",
            "## 测试结果",
            "```json",
            json.dumps(test_results, indent=2, ensure_ascii=False) if test_results else "未提供",
            "```",
            "",
        ]

        if design_doc:
            prompt_parts.extend([
                "## 设计方案",
                "```",
                design_doc[:3000] if len(design_doc) > 3000 else design_doc,
                "```",
                "",
            ])

        if interface_specs:
            prompt_parts.extend([
                "## 接口契约定义",
                "```json",
                json.dumps(interface_specs, indent=2, ensure_ascii=False),
                "```",
                "",
            ])

        prompt_parts.extend([
            "## 输出要求",
            "请基于以上信息生成代码审查报告，返回以下 JSON 格式：",
            "",
            "```json",
            json.dumps({
                "review_report": {
                    "issues": [
                        {
                            "description": "问题描述",
                            "category": "bug|security|performance|style|maintainability",
                            "severity": "critical|high|medium|low",
                            "file_path": "文件路径（可选）",
                            "line_number": 123,
                            "suggestion": "具体的修复建议",
                            "code_snippet": "相关代码片段（可选）"
                        }
                    ],
                    "overall_assessment": "总体评估摘要（100-300字）",
                    "summary": "执行摘要",
                    "improvement_suggestions": ["改进建议1", "改进建议2"],
                    "risk_level": "low|medium|high|critical",
                    "approval_recommendation": "approve|approve_with_caution|reject"
                }
            }, indent=2, ensure_ascii=False),
            "```",
            "",
            "注意：",
            "1. 如果没有发现问题，issues 可以为空数组",
            "2. 必须根据发现的问题给出客观的 approval_recommendation",
            "3. critical 或 high 级别问题存在时，不应给出 approve 建议",
        ])

        return "\n".join(prompt_parts)

    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出"""
        try:
            parsed = self._parse_json_response(response)

            # 处理可能的嵌套结构
            if "review_report" in parsed:
                return parsed
            else:
                # 如果 LLM 直接返回了报告内容，包装成标准格式
                return {"review_report": parsed}

        except Exception as e:
            logger.error(f"解析审查报告失败: {e}")
            raise

    def validate_output(self, output: Dict[str, Any]) -> CodeReviewerOutput:
        """校验输出为 Pydantic 模型"""
        try:
            # 确保 review_report 存在
            if "review_report" not in output:
                raise ValueError("输出缺少 review_report 字段")

            report_data = output["review_report"]

            # 构建 ReviewReport
            issues = []
            for issue_data in report_data.get("issues", []):
                try:
                    issue = ReviewIssue(**issue_data)
                    issues.append(issue)
                except ValidationError as ve:
                    logger.warning(f"问题项验证失败: {ve}, 数据: {issue_data}")
                    # 尝试修复并继续
                    issue = ReviewIssue(
                        description=issue_data.get("description", "未知问题"),
                        category=issue_data.get("category", "maintainability"),
                        severity=issue_data.get("severity", "low"),
                        suggestion=issue_data.get("suggestion", "请人工检查"),
                        file_path=issue_data.get("file_path"),
                        line_number=issue_data.get("line_number"),
                        code_snippet=issue_data.get("code_snippet")
                    )
                    issues.append(issue)

            review_report = ReviewReport(
                issues=issues,
                overall_assessment=report_data.get("overall_assessment", "未提供总体评估"),
                summary=report_data.get("summary", ""),
                improvement_suggestions=report_data.get("improvement_suggestions", []),
                risk_level=report_data.get("risk_level", "low"),
                approval_recommendation=report_data.get("approval_recommendation", "approve")
            )

            # 构建完整输出
            return CodeReviewerOutput(
                review_report=review_report,
                summary=f"发现 {len(issues)} 个问题",
                dependencies_added=[],
                input_tokens=output.get("input_tokens", 0),
                output_tokens=output.get("output_tokens", 0),
                duration_ms=output.get("duration_ms", 0)
            )

        except Exception as e:
            logger.error(f"验证审查报告失败: {e}")
            # 返回一个带有错误信息的有效输出
            return CodeReviewerOutput(
                review_report=ReviewReport(
                    issues=[],
                    overall_assessment=f"审查报告生成异常: {str(e)}",
                    risk_level="high",
                    approval_recommendation="approve_with_caution"
                ),
                summary="审查报告生成异常"
            )


# 全局实例
code_reviewer_agent = CodeReviewerAgent()
