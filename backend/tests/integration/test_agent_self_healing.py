"""
Agent 自我诊断测试
验证 MultiAgentCoordinator 的自动修复逻辑
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path


@pytest.mark.integration
class TestAgentSelfHealing:
    """测试 Agent 自我诊断和修复能力"""

    @pytest.fixture
    def buggy_code_output(self):
        """包含语法错误的代码输出"""
        return {
            "files": [
                {
                    "file_path": "app/test_bug.py",
                    "content": "def broken_function(\n    print('missing parenthesis'",  # 语法错误：缺少右括号
                    "change_type": "add",
                    "original_content": None
                }
            ],
            "summary": "有 Bug 的代码",
            "dependencies_added": [],
            "tests_included": False
        }

    @pytest.fixture
    def fixed_code_output(self):
        """修复后的代码输出"""
        return {
            "files": [
                {
                    "file_path": "app/test_bug.py",
                    "content": "def broken_function():\n    print('fixed')",
                    "change_type": "add",
                    "original_content": None
                }
            ],
            "summary": "修复后的代码",
            "dependencies_added": [],
            "tests_included": False
        }

    @pytest.mark.asyncio
    async def test_syntax_error_detection(self, buggy_code_output):
        """测试 TestRunner 能否正确识别语法错误"""
        from app.service.test_runner import TestRunnerService

        # 创建临时目录和文件
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            # 写入有语法错误的文件
            test_file = Path(tmpdir) / "test_syntax.py"
            test_file.write_text(buggy_code_output["files"][0]["content"])

            # 运行测试
            result = await TestRunnerService.run_tests(tmpdir)

            # 验证识别为语法错误
            assert result["success"] is False
            assert result["error_type"] == "syntax_error"
            assert "syntax" in result["logs"].lower() or "parse" in result["logs"].lower()

    @pytest.mark.asyncio
    async def test_auto_fix_attempt_counter(self, buggy_code_output, fixed_code_output):
        """测试 attempt 计数器是否正确增加"""
        from app.agents.multi_agent_coordinator import MultiAgentCoordinator
        from app.service.test_runner import TestRunnerService

        coordinator = MultiAgentCoordinator()

        design_output = {"feature_description": "测试功能"}
        target_files = {}

        # 模拟 TestRunner：第一次失败，第二次成功
        test_results = [
            {"success": False, "logs": "SyntaxError", "summary": "1 failed", "error_type": "syntax_error"},
            {"success": True, "logs": "All tests passed", "summary": "1 passed"}
        ]

        with patch.object(
            coordinator, '_execute_code_agent',
            new_callable=AsyncMock,
            side_effect=[{"code_output": buggy_code_output, "code_error": None},
                        {"code_output": fixed_code_output, "code_error": None}]
        ):
            with patch.object(
                TestRunnerService, 'run_tests',
                new_callable=AsyncMock,
                side_effect=test_results
            ):
                with patch(
                    'app.agents.multi_agent_coordinator.CodeExecutorService'
                ) as MockExecutor:
                    result = await coordinator.execute_with_auto_fix(
                        design_output,
                        target_files,
                        pipeline_id=1,
                        workspace_path="/tmp/test"
                    )

                    # 验证重试了一次
                    assert result["attempt"] == 1
                    assert result["success"] is True

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, buggy_code_output):
        """测试超过最大重试次数后的行为"""
        from app.agents.multi_agent_coordinator import MultiAgentCoordinator
        from app.service.test_runner import TestRunnerService

        coordinator = MultiAgentCoordinator()

        design_output = {"feature_description": "测试功能"}
        target_files = {}

        # 始终返回 Bug 代码
        with patch.object(
            coordinator, '_execute_code_agent',
            new_callable=AsyncMock,
            return_value={"code_output": buggy_code_output, "code_error": None}
        ):
            with patch.object(
                TestRunnerService, 'run_tests',
                new_callable=AsyncMock,
                return_value={"success": False, "logs": "SyntaxError", "summary": "1 failed", "error_type": "syntax_error"}
            ):
                with patch(
                    'app.agents.multi_agent_coordinator.CodeExecutorService'
                ) as MockExecutor:
                    result = await coordinator.execute_with_auto_fix(
                        design_output,
                        target_files,
                        pipeline_id=1,
                        workspace_path="/tmp/test"
                    )

                    # 验证达到最大重试次数后失败
                    assert result["success"] is False
                    assert result["attempt"] >= coordinator.MAX_FIX_RETRIES
                    assert "最大次数" in result["error"] or "max" in result["error"].lower()




@pytest.mark.integration
class TestTestRunnerErrorAnalysis:
    """测试 TestRunner 错误分析能力"""

    @pytest.mark.asyncio
    async def test_import_error_detection(self):
        """测试导入错误识别"""
        from app.service.test_runner import TestRunnerService
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建有导入错误的文件
            test_file = Path(tmpdir) / "test_import.py"
            test_file.write_text("import nonexistent_module\ndef test_foo(): pass")

            result = await TestRunnerService.run_tests(tmpdir)

            assert result["success"] is False
            assert result["error_type"] == "import_error"

    @pytest.mark.asyncio
    async def test_assertion_error_detection(self):
        """测试断言错误识别"""
        from app.service.test_runner import TestRunnerService
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建有断言错误的测试
            test_file = Path(tmpdir) / "test_assert.py"
            test_file.write_text("def test_fail(): assert False, 'expected failure'")

            result = await TestRunnerService.run_tests(tmpdir)

            assert result["success"] is False
            assert result["error_type"] == "test_failure"
            assert "AssertionError" in result["logs"] or "failed" in result["logs"].lower()
