"""
单元测试：TestRunnerService 的解析方法（不运行真实子进程）
"""
import pytest
from app.service.test_runner import TestRunnerService


@pytest.mark.unit
class TestExtractSummary:
    def test_passed(self):
        logs = "test_foo PASSED\n1 passed in 0.05s"
        result = TestRunnerService._extract_summary(logs)
        assert "passed" in result

    def test_failed(self):
        logs = "test_bar FAILED\n1 failed, 0 passed in 0.10s"
        result = TestRunnerService._extract_summary(logs)
        assert "failed" in result

    def test_empty_logs(self):
        result = TestRunnerService._extract_summary("")
        assert result == "No summary available"

    def test_multiple_passed(self):
        """测试多个通过的情况"""
        logs = "5 passed in 0.20s"
        result = TestRunnerService._extract_summary(logs)
        assert "passed" in result

    def test_mixed_results(self):
        """测试混合结果"""
        logs = "3 passed, 2 failed, 1 skipped in 1.5s"
        result = TestRunnerService._extract_summary(logs)
        assert "passed" in result and "failed" in result

    def test_error_collecting(self):
        """测试收集错误的情况"""
        logs = "ERROR collecting test_session"
        result = TestRunnerService._extract_summary(logs)
        assert "ERROR" in result or "error" in result.lower()


@pytest.mark.unit
class TestAnalyzeErrorType:
    def test_syntax_error(self):
        logs = "SyntaxError: invalid syntax at line 5"
        assert TestRunnerService._analyze_error_type(logs) == "syntax_error"

    def test_import_error(self):
        logs = "ModuleNotFoundError: No module named 'app.service.xxx'"
        assert TestRunnerService._analyze_error_type(logs) == "import_error"

    def test_test_failure(self):
        logs = "AssertionError: assert False\n1 failed"
        assert TestRunnerService._analyze_error_type(logs) == "test_failure"

    def test_no_tests(self):
        logs = "collected 0 items\nno tests ran"
        assert TestRunnerService._analyze_error_type(logs) == "no_tests"

    def test_collection_error(self):
        """测试收集错误"""
        logs = "ERROR collecting test_file.py"
        assert TestRunnerService._analyze_error_type(logs) == "collection_error"

    def test_indentation_error(self):
        """测试缩进错误"""
        logs = "IndentationError: unexpected indent"
        assert TestRunnerService._analyze_error_type(logs) == "syntax_error"

    def test_unknown_error(self):
        """测试未知错误"""
        logs = "Some random error message"
        assert TestRunnerService._analyze_error_type(logs) == "unknown_error"

    def test_none_logs(self):
        """测试 None 输入"""
        assert TestRunnerService._analyze_error_type(None) is None


@pytest.mark.unit
class TestExtractFailedTests:
    def test_single_failure(self):
        logs = "FAILED tests/test_foo.py::test_bar - AssertionError"
        result = TestRunnerService._extract_failed_tests(logs)
        assert "tests/test_foo.py::test_bar" in result

    def test_multiple_failures(self):
        logs = "FAILED tests/a.py::test_1\nFAILED tests/b.py::test_2"
        result = TestRunnerService._extract_failed_tests(logs)
        assert len(result) == 2

    def test_no_failures(self):
        """测试没有失败的情况"""
        logs = "All tests passed!"
        result = TestRunnerService._extract_failed_tests(logs)
        assert len(result) == 0

    def test_empty_logs(self):
        """测试空日志"""
        result = TestRunnerService._extract_failed_tests("")
        assert len(result) == 0

    def test_error_not_failed(self):
        """测试 ERROR 标记"""
        logs = "ERROR tests/test_error.py::test_broken"
        result = TestRunnerService._extract_failed_tests(logs)
        assert "tests/test_error.py::test_broken" in result


@pytest.mark.unit
class TestExtractErrorMessage:
    """测试错误信息提取"""

    def test_extract_assertion_error(self):
        logs = "AssertionError: assert 1 == 2\nE       assert 1 == 2"
        result = TestRunnerService._extract_error_message(logs)
        assert "AssertionError" in result

    def test_extract_syntax_error(self):
        logs = "SyntaxError: invalid syntax\n    def foo(\n            ^"
        result = TestRunnerService._extract_error_message(logs)
        assert "SyntaxError" in result

    def test_extract_import_error(self):
        logs = "ImportError: cannot import name 'foo' from 'bar'"
        result = TestRunnerService._extract_error_message(logs)
        assert "ImportError" in result

    def test_empty_logs_return_unknown(self):
        result = TestRunnerService._extract_error_message("")
        assert result == "Unknown error"


@pytest.mark.unit
class TestExtractCoverageInfo:
    """测试覆盖率信息提取"""

    def test_extract_total_coverage(self):
        logs = "TOTAL                          100     10    90%"
        result = TestRunnerService._extract_coverage_info(logs)
        assert result is not None
        assert result.get('total') == '90%'

    def test_no_coverage_data(self):
        logs = "No coverage data available"
        result = TestRunnerService._extract_coverage_info(logs)
        assert result is None or result == {}

    def test_coverage_with_missing(self):
        logs = "app/service.py                 50     10    80%\nTOTAL                          100     20    80%"
        result = TestRunnerService._extract_coverage_info(logs)
        assert result is not None
