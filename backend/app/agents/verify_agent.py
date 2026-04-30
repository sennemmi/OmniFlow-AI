"""
验证 Agent (VerifyAgent) - 独立验证代理

【核心原则：利益隔离】
1. 只运行测试，只报告事实（PASS/FAIL）
2. 绝不提供修复建议，绝不修改代码
3. 被编程为不相信 RepairerAgent 的工作，唯一的快乐就是找出错误

职责：
- 使用 TestRunner 运行测试
- 只输出 PASS/FAIL 和精确的失败证据
- 绝不提供修复建议
- 绝不修改代码
"""

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from app.service.error_context_parser import ErrorContextParser

logger = logging.getLogger(__name__)


class VerificationVerdict(Enum):
    """验证结果"""
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"  # 验证过程本身出错


@dataclass
class VerificationResult:
    """
    验证结果

    【利益隔离】只包含事实，不包含修复建议
    """
    verdict: VerificationVerdict
    errors: List[str] = field(default_factory=list)
    summary: str = ""
    raw_logs: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)  # 证据包

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "verdict": self.verdict.value,
            "errors": self.errors,
            "summary": self.summary,
            "raw_logs": self.raw_logs[:2000] if self.raw_logs else "",
            "evidence": self.evidence,
            # 【重要】绝不包含修复建议
            "message": self._build_message()
        }

    def _build_message(self) -> str:
        """
        构建验证报告消息

        【利益隔离】只报告事实，绝不提供修复建议
        """
        if self.verdict == VerificationVerdict.PASS:
            return "Verification PASSED: 所有测试通过。"
        elif self.verdict == VerificationVerdict.FAIL:
            return (
                "Verification FAILED: 代码未通过测试。以下是失败的测试清单和关键日志。"
                "请将本报告交还给修复系统，不要尝试修复。"
            )
        else:
            return f"Verification ERROR: 验证过程出错 - {self.summary}"


class VerifyAgent:
    """
    独立的验证代理

    【利益隔离核心】
    - 被剥夺了动手能力：只负责"检"，没有任何文件写入或代码修改权限
    - 只能如实报告，无法补救
    - 与 RepairerAgent 完全隔离
    """

    def __init__(self):
        self.name = "VerifyAgent"

    async def verify(
        self,
        test_runner: Any,
        test_path: str = "tests/",
        verbose: bool = False,
        project_path: Optional[str] = None
    ) -> VerificationResult:
        """
        执行验证

        【利益隔离】只运行测试，只报告事实

        Args:
            test_runner: 测试运行器类或实例（TestRunnerService）
            test_path: 测试路径
            verbose: 是否输出详细信息
            project_path: 项目路径（必需，用于 TestRunnerService）

        Returns:
            VerificationResult: 验证结果（只包含事实，无修复建议）
        """
        logger.info(f"[{self.name}] 开始验证: {test_path}")

        try:
            # 运行测试
            # 支持两种调用方式：
            # 1. test_runner.run_tests(project_path, test_path) - TestRunnerService 类方法
            # 2. test_runner.run_tests(test_path) - 实例方法
            if project_path:
                result = await test_runner.run_tests(
                    project_path=project_path,
                    test_path=test_path,
                    timeout=120
                )
            else:
                result = await test_runner.run_tests(
                    test_path=test_path,
                    verbose=verbose
                )

            # 解析结果 - 只提取事实
            if result.get("success"):
                logger.info(f"[{self.name}] 验证通过")
                return VerificationResult(
                    verdict=VerificationVerdict.PASS,
                    errors=[],
                    summary=result.get("summary", "所有测试通过"),
                    raw_logs=result.get("logs", ""),
                    evidence=result.get("evidence", {})
                )

            # 测试失败，提取错误清单（事实）
            errors = self._extract_errors(result.get("logs", ""))
            evidence = result.get("evidence", {})

            logger.warning(f"[{self.name}] 验证失败: 发现 {len(errors)} 个错误")

            return VerificationResult(
                verdict=VerificationVerdict.FAIL,
                errors=errors,
                summary=result.get("summary", "测试失败"),
                raw_logs=result.get("logs", ""),
                evidence=evidence
            )

        except Exception as e:
            logger.error(f"[{self.name}] 验证过程出错: {e}")
            return VerificationResult(
                verdict=VerificationVerdict.ERROR,
                errors=[f"验证过程出错: {str(e)}"],
                summary="验证过程异常",
                raw_logs=str(e),
                evidence={}
            )

    def _extract_errors(self, logs: str) -> List[str]:
        """
        从日志中提取简洁的错误清单

        【利益隔离】只提取关键错误信息，避免噪音，绝不解释或建议

        Args:
            logs: 测试日志

        Returns:
            List[str]: 错误清单（纯事实）
        """
        errors = []
        lines = logs.splitlines()

        for i, line in enumerate(lines):
            line = line.strip()

            # 提取 FAILED 行
            if line.startswith("FAILED "):
                errors.append(line)

            # 提取 ERROR 行（包括 "ERROR collecting" 等）
            elif "ERROR" in line and ("collecting" in line.lower() or line.startswith("ERROR ")):
                errors.append(line)

            # 提取 collection error
            elif "error during collection" in line.lower():
                errors.append(line)

            # 提取关键错误类型（纯事实）
            elif any(err in line for err in [
                "ImportError:",
                "ModuleNotFoundError:",
                "NameError:",
                "SyntaxError:",
                "AttributeError:",
                "TypeError:",
                "AssertionError:"
            ]):
                # 只保留错误类型和简要信息
                if len(line) > 150:
                    line = line[:150] + "..."
                errors.append(line)

            # 提取 "E   " 开头的错误详情（pytest 风格）
            elif line.startswith("E   "):
                err_content = line[3:].strip()
                if err_content and len(errors) < 20:  # 限制数量
                    if len(err_content) > 150:
                        err_content = err_content[:150] + "..."
                    errors.append(f"ERROR: {err_content}")

        # 去重并保持顺序
        seen = set()
        unique_errors = []
        for err in errors:
            if err not in seen:
                seen.add(err)
                unique_errors.append(err)

        return unique_errors

    async def verify_with_structured_errors(
        self,
        test_runner: Any,
        test_path: str = "tests/",
        generated_files: Optional[List[str]] = None,
        project_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行验证并返回结构化的错误信息

        【利益隔离】返回事实，不返回修复建议

        Args:
            test_runner: 测试运行器类或实例
            test_path: 测试路径
            generated_files: 生成的文件列表
            project_path: 项目路径（必需，用于 TestRunnerService）

        Returns:
            Dict[str, Any]: 包含验证结果和结构化错误（无修复建议）
        """
        # 执行基础验证
        result = await self.verify(test_runner, test_path, verbose=False, project_path=project_path)

        # 如果失败，解析结构化错误（仍然是事实）
        structured_errors = None
        if result.verdict == VerificationVerdict.FAIL:
            parser = ErrorContextParser()
            structured_errors = parser.parse_pytest_output(
                logs=result.raw_logs,
                failure_cause="test_failure",
                generated_files=generated_files or []
            ).to_dict()

        return {
            "verdict": result.verdict.value,
            "errors": result.errors,
            "summary": result.summary,
            "structured_errors": structured_errors,
            "error_count": len(result.errors),
            "evidence": result.evidence,
            # 【重要】包含消息，但绝不包含修复建议
            "message": result._build_message()
        }


# 便捷函数
async def verify_fixes(
    test_runner: Any,
    test_path: str = "tests/",
    generated_files: Optional[List[str]] = None,
    project_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    便捷函数：验证修复结果

    【利益隔离】只验证，不修复

    Args:
        test_runner: 测试运行器类或实例
        test_path: 测试路径
        generated_files: 生成的文件列表
        project_path: 项目路径（必需，用于 TestRunnerService）

    Returns:
        Dict[str, Any]: 验证结果（无修复建议）
    """
    agent = VerifyAgent()
    return await agent.verify_with_structured_errors(
        test_runner=test_runner,
        test_path=test_path,
        generated_files=generated_files,
        project_path=project_path
    )
