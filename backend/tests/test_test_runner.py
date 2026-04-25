"""
TestRunnerService 单元测试

以单元测试为荣，以手工验证为耻
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
import asyncio
from pathlib import Path

from app.service.test_runner import TestRunnerService


class TestTestRunnerService:
    """测试 TestRunnerService"""

    @pytest.mark.asyncio
    async def test_run_tests_success(self):
        """测试运行测试 - 成功场景"""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(
            b"test_session_starts\ntest_passed\n1 passed in 0.01s",
            b""
        ))

        with patch.object(Path, 'exists', return_value=True):
            with patch(
                'asyncio.create_subprocess_exec',
                return_value=mock_process
            ):
                result = await TestRunnerService.run_tests("c:\\temp\\project")

                assert result["success"] is True
                assert result["exit_code"] == 0
                assert "passed" in result["logs"]
                assert result["error_type"] is None
                assert result["failed_tests"] == []

    @pytest.mark.asyncio
    async def test_run_tests_failure(self):
        """测试运行测试 - 失败场景"""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(
            b"test_session_starts\ntest_failed\n1 failed in 0.01s",
            b"AssertionError: expected True but got False"
        ))

        with patch.object(Path, 'exists', return_value=True):
            with patch(
                'asyncio.create_subprocess_exec',
                return_value=mock_process
            ):
                result = await TestRunnerService.run_tests("c:\\temp\\project")

                assert result["success"] is False
                assert result["exit_code"] == 1
                assert "failed" in result["logs"]
                assert result["error_type"] == "test_failure"

    @pytest.mark.asyncio
    async def test_run_tests_syntax_error(self):
        """测试运行测试 - 语法错误场景"""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(
            b"",
            b"SyntaxError: invalid syntax\n  File \"test.py\", line 5"
        ))

        with patch.object(Path, 'exists', return_value=True):
            with patch(
                'asyncio.create_subprocess_exec',
                return_value=mock_process
            ):
                result = await TestRunnerService.run_tests("c:\\temp\\project")

                assert result["success"] is False
                assert result["error_type"] == "syntax_error"

    @pytest.mark.asyncio
    async def test_run_tests_import_error(self):
        """测试运行测试 - 导入错误场景"""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(
            b"",
            b"ModuleNotFoundError: No module named 'pytest_asyncio'"
        ))

        with patch.object(Path, 'exists', return_value=True):
            with patch(
                'asyncio.create_subprocess_exec',
                return_value=mock_process
            ):
                result = await TestRunnerService.run_tests("c:\\temp\\project")

                assert result["success"] is False
                assert result["error_type"] == "import_error"

    @pytest.mark.asyncio
    async def test_run_tests_timeout(self):
        """测试运行测试 - 超时场景"""
        with patch.object(Path, 'exists', return_value=True):
            with patch(
                'asyncio.create_subprocess_exec',
                new_callable=AsyncMock
            ) as mock_exec:
                mock_process = AsyncMock()
                mock_process.communicate = AsyncMock(
                    side_effect=asyncio.TimeoutError()
                )
                mock_process.kill = Mock()
                mock_process.wait = AsyncMock()
                mock_exec.return_value = mock_process

                result = await TestRunnerService.run_tests("c:\\temp\\project", timeout=1)

                assert result["success"] is False
                assert result["error_type"] == "timeout"

    @pytest.mark.asyncio
    async def test_run_tests_pytest_not_found(self):
        """测试运行测试 - pytest 未安装"""
        with patch.object(Path, 'exists', return_value=True):
            with patch(
                'asyncio.create_subprocess_exec',
                side_effect=FileNotFoundError("pytest not found")
            ):
                result = await TestRunnerService.run_tests("c:\\temp\\project")

                assert result["success"] is False
                assert result["error_type"] == "pytest_not_found"

    @pytest.mark.asyncio
    async def test_run_tests_project_not_exists(self):
        """测试运行测试 - 项目路径不存在"""
        with patch.object(Path, 'exists', return_value=False):
            result = await TestRunnerService.run_tests("c:\\nonexistent\\project")

            assert result["success"] is False
            assert result["error_type"] == "path_error"

    def test_extract_summary_with_passed(self):
        """测试提取总结 - 包含 passed"""
        logs = "test_session_starts\ntest_passed\n1 passed in 0.01s"
        summary = TestRunnerService._extract_summary(logs)
        assert "passed" in summary.lower()

    def test_extract_summary_with_failed(self):
        """测试提取总结 - 包含 failed"""
        logs = "test_session_starts\ntest_failed\n1 failed in 0.01s"
        summary = TestRunnerService._extract_summary(logs)
        assert "failed" in summary.lower()

    def test_extract_summary_empty_logs(self):
        """测试提取总结 - 空日志"""
        summary = TestRunnerService._extract_summary("")
        assert summary == "No summary available"

    def test_extract_summary_whitespace_only(self):
        """测试提取总结 - 只有空白字符"""
        summary = TestRunnerService._extract_summary("   \n   \n   ")
        assert summary == "No summary available"

    def test_analyze_error_type_syntax_error(self):
        """测试错误类型分析 - 语法错误"""
        logs = "SyntaxError: invalid syntax"
        error_type = TestRunnerService._analyze_error_type(logs)
        assert error_type == "syntax_error"

    def test_analyze_error_type_import_error(self):
        """测试错误类型分析 - 导入错误"""
        logs = "ModuleNotFoundError: No module named 'pytest'"
        error_type = TestRunnerService._analyze_error_type(logs)
        assert error_type == "import_error"

    def test_analyze_error_type_test_failure(self):
        """测试错误类型分析 - 测试失败"""
        logs = "AssertionError: expected True but got False"
        error_type = TestRunnerService._analyze_error_type(logs)
        assert error_type == "test_failure"

    def test_extract_failed_tests(self):
        """测试提取失败的测试"""
        logs = "FAILED tests/test_example.py::test_function\nPASSED tests/test_other.py"
        failed_tests = TestRunnerService._extract_failed_tests(logs)
        assert "tests/test_example.py::test_function" in failed_tests

    def test_extract_error_message_assertion(self):
        """测试提取错误信息 - 断言错误"""
        logs = "AssertionError: expected True\n    assert False"
        error_msg = TestRunnerService._extract_error_message(logs)
        assert "AssertionError" in error_msg

    @pytest.mark.asyncio
    async def test_check_pytest_installed_true(self):
        """测试检查 pytest 安装 - 已安装"""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"pytest 7.0.0", b""))

        with patch(
            'asyncio.create_subprocess_exec',
            return_value=mock_process
        ):
            result = await TestRunnerService.check_pytest_installed("c:\\temp\\project")
            assert result is True

    @pytest.mark.asyncio
    async def test_check_pytest_installed_false(self):
        """测试检查 pytest 安装 - 未安装"""
        with patch(
            'asyncio.create_subprocess_exec',
            side_effect=FileNotFoundError()
        ):
            result = await TestRunnerService.check_pytest_installed("c:\\temp\\project")
            assert result is False

    @pytest.mark.asyncio
    async def test_run_tests_with_coverage(self):
        """测试运行测试带覆盖率"""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(
            b"test_session_starts\nCoverage report:\nTOTAL 100 10 90%\ntest_passed\n1 passed",
            b""
        ))

        with patch.object(Path, 'exists', return_value=True):
            with patch(
                'asyncio.create_subprocess_exec',
                return_value=mock_process
            ):
                result = await TestRunnerService.run_tests_with_coverage(
                    "c:\\temp\\project",
                    source_dirs=["app"]
                )

                assert result["success"] is True
                assert "coverage" in result
