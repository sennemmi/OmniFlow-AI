"""
ReviewAgent：分析 LayeredTestResult，输出路由决策。
不调用 LLM，是纯 Python 逻辑，保证快速且确定性。
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from app.service.layered_test_runner import LayeredTestResult


@dataclass
class ReviewDecision:
    action: str          # "proceed" | "auto_fix" | "request_user"
    # auto_fix 时的错误上下文（传给 CoderAgent）
    error_context: Optional[str] = None
    # request_user 时展示给用户的信息
    user_message: Optional[str] = None
    regression_failed_tests: List[str] = field(default_factory=list)
    options: List[str] = field(default_factory=list)  # ["update_tests", "rollback"]
    # 详细的错误信息
    error_details: Optional[Dict[str, Any]] = None


class ReviewAgent:
    """
    根据 LayeredTestResult 输出路由决策：
      - all_passed                       → proceed（进入人工 Review）
      - failure_cause=defense_broken     → request_user（防御性测试失败，必须人工介入）
      - failure_cause=regression_broken  → request_user（询问是否更新旧测试）
      - failure_cause=code_bug           → auto_fix（Coder 修复，最多 MAX_FIX_RETRIES 次）
    """

    @staticmethod
    def decide(result: LayeredTestResult, attempt: int = 0,
               max_retries: int = 3) -> ReviewDecision:

        if result.all_passed:
            return ReviewDecision(action="proceed")

        # 防御性测试失败 = 破坏了核心保护机制，必须人工介入
        if result.failure_cause == "defense_broken":
            failed_tests = result.failed_tests or []
            failed_str = "\n".join(f"  - {t}" for t in failed_tests)
            error_details = result.error_details or {}

            return ReviewDecision(
                action="request_user",
                user_message=(
                    f"🚨 防御性测试失败！代码破坏了系统的核心保护机制。\n\n"
                    f"失败的测试 ({len(failed_tests)} 个):\n"
                    f"{failed_str}\n\n"
                    f"错误信息:\n"
                    f"{error_details.get('logs', '无详细日志')[:1000]}\n\n"
                    f"说明：防御性测试是系统的'免疫系统'，包括文件回滚、路径安全、"
                    f"状态机保护等核心机制。这些测试失败意味着代码存在严重问题，"
                    f"必须人工检查，不能自动修复。"
                ),
                regression_failed_tests=failed_tests,
                options=["rollback"],  # 防御性测试失败只能回滚
                error_details=error_details
            )

        # 回归测试失败 = 旧测试不兼容，询问用户是否更新测试
        if result.failure_cause == "regression_broken":
            failed_tests = result.failed_tests or []
            failed_str = "\n".join(f"  - {t}" for t in failed_tests)
            error_details = result.error_details or {}

            return ReviewDecision(
                action="request_user",
                user_message=(
                    f"新代码导致 {len(failed_tests)} 个原有测试失败：\n"
                    f"{failed_str}\n\n"
                    f"错误信息:\n"
                    f"{error_details.get('logs', '无详细日志')[:800]}\n\n"
                    "请选择：\n"
                    "  [update_tests] 更新测试文件以适配新代码\n"
                    "  [rollback]     回滚本次代码变更"
                ),
                regression_failed_tests=failed_tests,
                options=["update_tests", "rollback"],
                error_details=error_details
            )

        # code_bug 情况：新测试失败或语法错误，可以 Auto-Fix
        if result.failure_cause == "code_bug":
            if attempt >= max_retries:
                return ReviewDecision(
                    action="request_user",
                    user_message=f"已自动修复 {max_retries} 次仍未通过，请人工介入。",
                    options=["rollback"],
                    error_details=result.error_details
                )

            # 构建详细的错误上下文给 CoderAgent
            error_details = result.error_details or {}
            layer = error_details.get("layer", "unknown")
            message = error_details.get("message", "未知错误")
            logs = error_details.get("logs", "")
            failed_tests = error_details.get("failed_tests", [])

            # 构建错误上下文
            error_context = f"""【测试失败详情】
失败层级: {layer}
错误描述: {message}

失败的测试:
"""
            if failed_tests:
                for test in failed_tests:
                    error_context += f"  - {test}\n"
            else:
                error_context += "  (无具体测试名称)\n"

            error_context += f"""
错误日志:
{logs[:1500]}

修复建议:
{error_details.get('suggestion', '请分析错误并修复代码')}
"""

            return ReviewDecision(
                action="auto_fix",
                error_context=error_context,
                error_details=error_details
            )

        # 未知失败原因，默认请求用户
        return ReviewDecision(
            action="request_user",
            user_message=f"未知错误类型: {result.failure_cause}，请人工检查。",
            options=["rollback"],
            error_details=result.error_details
        )


review_agent = ReviewAgent()
