"""
第二层：测试运行器与决策防线（防止"旧测试"被 AI 随意篡改）

AI 在修复报错时，最容易出现"为了让测试通过，直接把测试代码删了改了"的偷懒行为。

【分层测试执行顺序 - 快速失败原则】
Layer 1: 语法检查（毫秒级）
Layer 2: 防御性测试（本层，核心保护机制）
Layer 3: 新测试（AI 生成功能测试）
Layer 4: 健康检查

测试列表：
1. test_layer1_syntax_error_interception - Layer 1 语法错误拦截测试
2. test_defense_protection_rejects_auto_fix - 防御性测试保护测试（防御性测试失败必须人工介入）
3. test_regression_protection_rejects_auto_fix - 回归测试保护测试（旧测试失败询问用户）
4. test_new_tests_allow_auto_fix - 新测试运行测试（新测试失败可 Auto-Fix）
"""

import pytest

pytestmark = [pytest.mark.defense, pytest.mark.layer2]
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from app.service.layered_test_runner import LayeredTestRunner, LayerResult, LayeredTestResult
from app.agents.reviewer import ReviewAgent, ReviewDecision


class TestLayer1SyntaxErrorInterception:
    """
    用例: 模拟 AI 输出缺少闭合括号的 Python 代码，LayeredTestRunner 应该在 ast.parse 阶段秒级报错，且不触发耗时的子进程。
    目的: 节省算力，防止低级语法错误进入后续流程。
    """

    def test_syntax_error_detected_in_layer1(self):
        """测试 Layer 1 能检测语法错误"""
        # 模拟 AI 生成的有语法错误的代码（缺少闭合括号）
        new_files = [
            {
                "file_path": "backend/app/calculator.py",
                "content": '''def add(a, b:
    """Add two numbers"""
    return a + b
'''  # 语法错误：缺少右括号
            }
        ]

        result = LayeredTestRunner._check_syntax(new_files)

        assert result.passed is False
        assert result.layer == "syntax"
        assert result.error_type == "syntax_error"
        assert "SyntaxError" in result.logs

    def test_syntax_error_stops_early_no_subprocess(self):
        """测试语法错误在早期拦截，不触发子进程测试"""
        # 使用 Mock 验证不会调用 TestRunnerService
        with patch('app.service.layered_test_runner.TestRunnerService') as mock_service:
            mock_service.run_tests = AsyncMock()

            new_files = [
                {
                    "file_path": "backend/app/broken.py",
                    "content": "def broken(:\n    pass"  # 明显语法错误
                }
            ]

            # 只调用 Layer 1 检查
            result = LayeredTestRunner._check_syntax(new_files)

            # 验证语法检查失败
            assert result.passed is False

            # 验证没有调用耗时的子进程测试
            mock_service.run_tests.assert_not_called()

    def test_valid_syntax_passes_layer1(self):
        """测试有效代码通过 Layer 1 检查"""
        new_files = [
            {
                "file_path": "backend/app/valid.py",
                "content": '''def add(a, b):
    """Add two numbers"""
    return a + b

class Calculator:
    def multiply(self, x, y):
        return x * y
'''
            }
        ]

        result = LayeredTestRunner._check_syntax(new_files)

        assert result.passed is True
        assert result.layer == "syntax"
        assert result.summary == "语法检查通过"

    def test_multiple_files_syntax_check(self):
        """测试批量检查多个文件的语法"""
        new_files = [
            {
                "file_path": "backend/app/valid1.py",
                "content": "def f1(): pass"
            },
            {
                "file_path": "backend/app/valid2.py",
                "content": "def f2(): pass"
            },
            {
                "file_path": "backend/app/broken.py",
                "content": "def broken(: pass"  # 语法错误
            }
        ]

        result = LayeredTestRunner._check_syntax(new_files)

        assert result.passed is False
        assert "broken.py" in result.logs


class TestDefenseProtectionRejectsAutoFix:
    """
    用例: 模拟 AI 修改了代码导致防御性测试（backend/tests/unit/defense/）失败。
    断言 ReviewAgent.decide() 返回的 action 是 request_user（挂起询问人类），而不是 auto_fix。
    目的: 防御性测试是系统的"免疫系统"，失败说明代码破坏了核心保护机制，必须人工介入。
    """

    def test_defense_failure_triggers_request_user(self):
        """测试防御性测试失败时触发 request_user 而不是 auto_fix"""
        # 模拟防御性测试失败的结果
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[
                LayerResult(layer="syntax", passed=True, summary="语法检查通过"),
                LayerResult(
                    layer="defense",
                    passed=False,
                    summary="2 个防御性测试失败",
                    failed_tests=["test_rollback_change_perfect_restore", "test_path_traversal_protection"],
                    logs="AssertionError: 文件回滚失败"
                )
            ],
            failure_cause="defense_broken",
            failed_tests=["test_rollback_change_perfect_restore", "test_path_traversal_protection"],
            error_details={
                "layer": "defense",
                "message": "防御性测试失败",
                "logs": "代码破坏了文件回滚机制",
                "suggestion": "必须人工检查代码"
            }
        )

        decision = ReviewAgent.decide(layered_result, attempt=0, max_retries=3)

        # 关键断言：必须是 request_user，不能是 auto_fix
        assert decision.action == "request_user", \
            f"防御性测试失败时应该 request_user，而不是 {decision.action}"
        # 防御性测试失败只能回滚，不能更新测试
        assert decision.options == ["rollback"], \
            "防御性测试失败只能回滚，不能更新测试"

    def test_defense_failure_includes_error_details(self):
        """测试防御性测试失败包含详细的错误信息"""
        error_details = {
            "layer": "defense",
            "message": "防御性测试失败: 3 个测试未通过",
            "logs": "test_import_sanitizer_interception failed...",
            "failed_tests": ["test_import_sanitizer_interception"],
            "suggestion": "代码破坏了核心保护机制"
        }

        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[],
            failure_cause="defense_broken",
            failed_tests=["test_import_sanitizer_interception"],
            error_details=error_details
        )

        decision = ReviewAgent.decide(layered_result, attempt=0)

        # 验证错误详情被传递
        assert decision.error_details == error_details
        assert "防御性测试" in decision.user_message


class TestRegressionProtectionRejectsAutoFix:
    """
    用例: 模拟 AI 修改了业务代码导致 backend/tests/unit/ 下的旧测试失败（不包括防御性测试）。
    断言 ReviewAgent.decide() 返回的 action 是 request_user（挂起询问人类），而不是 auto_fix。
    目的: 这是保证"不破坏原有代码"的最重要用例。严禁 AI 私自修改旧的测试用例。
    """

    def test_regression_failure_triggers_request_user(self):
        """测试回归测试失败时触发 request_user 而不是 auto_fix"""
        # 模拟回归测试失败的结果
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[
                LayerResult(layer="syntax", passed=True, summary="语法检查通过"),
                LayerResult(layer="defense", passed=True, summary="防御性测试通过"),
                LayerResult(
                    layer="regression",
                    passed=False,
                    summary="2 个回归测试失败",
                    failed_tests=["test_user_model", "test_auth_flow"],
                    logs="AssertionError in test_user_model"
                )
            ],
            failure_cause="regression_broken",
            failed_tests=["test_user_model", "test_auth_flow"],
            error_details={
                "layer": "regression",
                "message": "回归测试失败",
                "logs": "AssertionError in test_user_model",
                "failed_tests": ["test_user_model", "test_auth_flow"],
                "suggestion": "新代码导致原有测试失败"
            }
        )

        decision = ReviewAgent.decide(layered_result, attempt=0, max_retries=3)

        # 关键断言：必须是 request_user，不能是 auto_fix
        assert decision.action == "request_user", \
            f"回归测试失败时应该 request_user，而不是 {decision.action}"
        assert "update_tests" in decision.options
        assert "rollback" in decision.options
        assert len(decision.regression_failed_tests) == 2

    def test_regression_failure_includes_failed_tests_in_message(self):
        """测试回归失败信息包含具体失败的测试名称"""
        failed_tests = ["test_calculator_add", "test_calculator_divide", "test_user_login"]

        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[],
            failure_cause="regression_broken",
            failed_tests=failed_tests,
            error_details={
                "layer": "regression",
                "message": "回归测试失败",
                "failed_tests": failed_tests
            }
        )

        decision = ReviewAgent.decide(layered_result, attempt=0)

        # 验证用户消息包含失败的测试列表
        assert decision.user_message is not None
        for test in failed_tests:
            assert test in decision.user_message, f"用户消息应包含失败的测试: {test}"

    def test_regression_failure_never_auto_fix_even_on_retry(self):
        """测试即使在重试过程中，回归测试失败也不会触发 auto_fix"""
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[],
            failure_cause="regression_broken",
            failed_tests=["test_critical_feature"],
            error_details={
                "layer": "regression",
                "message": "回归测试失败",
                "failed_tests": ["test_critical_feature"]
            }
        )

        # 即使在第 2 次尝试，回归失败也应该 request_user
        decision = ReviewAgent.decide(layered_result, attempt=2, max_retries=3)

        assert decision.action == "request_user", \
            "即使在重试中，回归测试失败也必须 request_user"


class TestNewTestsAllowAutoFix:
    """
    用例: 模拟 AI 在 backend/tests/ai_generated/ 下生成了新测试并运行失败。
    断言返回 action == "auto_fix"。
    目的: 允许 AI 修复自己刚刚生成的新代码和新测试。
    """

    def test_new_test_failure_allows_auto_fix(self):
        """测试新测试失败时允许 auto_fix"""
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[
                LayerResult(layer="syntax", passed=True, summary="语法检查通过"),
                LayerResult(layer="defense", passed=True, summary="防御性测试通过"),
                LayerResult(layer="regression", passed=True, summary="回归测试通过"),
                LayerResult(
                    layer="new_tests",
                    passed=False,
                    summary="1 个新测试失败",
                    failed_tests=["test_new_feature"],
                    logs="AssertionError: expected 42 but got 0"
                )
            ],
            failure_cause="code_bug",  # 新测试失败属于 code_bug
            failed_tests=["test_new_feature"],
            error_details={
                "layer": "new_tests",
                "message": "新测试失败",
                "logs": "AssertionError: expected 42 but got 0",
                "failed_tests": ["test_new_feature"],
                "suggestion": "功能实现不符合测试预期"
            }
        )

        decision = ReviewAgent.decide(layered_result, attempt=0, max_retries=3)

        # 新测试失败应该允许 auto_fix
        assert decision.action == "auto_fix", \
            f"新测试失败时应该允许 auto_fix，而不是 {decision.action}"
        assert decision.error_context is not None
        assert "new_tests" in decision.error_context

    def test_new_test_failure_respects_max_retries(self):
        """测试新测试失败时尊重最大重试次数"""
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[
                LayerResult(
                    layer="new_tests",
                    passed=False,
                    summary="测试失败"
                )
            ],
            failure_cause="code_bug",
            failed_tests=["test_feature"],
            error_details={
                "layer": "new_tests",
                "message": "测试失败",
                "failed_tests": ["test_feature"]
            }
        )

        # 第 3 次尝试（attempt=3，max_retries=3）应该 request_user
        decision = ReviewAgent.decide(layered_result, attempt=3, max_retries=3)

        assert decision.action == "request_user", \
            "达到最大重试次数后应该 request_user"
        assert "3 次" in decision.user_message

    def test_syntax_error_allows_auto_fix(self):
        """测试语法错误时允许 auto_fix"""
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[
                LayerResult(
                    layer="syntax",
                    passed=False,
                    summary="1 个文件存在语法错误",
                    error_type="syntax_error",
                    logs="SyntaxError: invalid syntax"
                )
            ],
            failure_cause="code_bug",
            error_details={
                "layer": "syntax",
                "message": "语法错误",
                "logs": "SyntaxError: invalid syntax"
            }
        )

        decision = ReviewAgent.decide(layered_result, attempt=0, max_retries=3)

        assert decision.action == "auto_fix"


class TestLayeredTestRunnerIntegration:
    """分层测试运行器的集成测试"""

    def test_full_layered_execution_stops_at_syntax_error(self):
        """测试完整执行在语法错误时提前终止"""
        import asyncio

        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                # 创建有语法错误的文件
                new_files = [
                    {
                        "file_path": "backend/app/broken.py",
                        "content": "def broken(:\n    pass"  # 语法错误
                    }
                ]

                # 运行分层测试
                result = await LayeredTestRunner.run(
                    workspace_path=tmpdir,
                    new_files=new_files,
                    sandbox_port=None
                )

                # 验证在语法层失败
                assert result.all_passed is False
                assert result.failure_cause == "code_bug"

                # 验证只有语法层的结果
                assert len(result.layers) == 1
                assert result.layers[0].layer == "syntax"

        asyncio.run(run_test())

    def test_decision_proceed_when_all_pass(self):
        """测试全部通过时返回 proceed"""
        layered_result = LayeredTestResult(
            all_passed=True,
            layers=[
                LayerResult(layer="syntax", passed=True, summary="语法检查通过"),
                LayerResult(layer="defense", passed=True, summary="防御性测试通过"),
                LayerResult(layer="regression", passed=True, summary="回归测试通过"),
                LayerResult(layer="new_tests", passed=True, summary="新测试通过")
            ],
            failure_cause=None
        )

        decision = ReviewAgent.decide(layered_result, attempt=0)

        assert decision.action == "proceed"
