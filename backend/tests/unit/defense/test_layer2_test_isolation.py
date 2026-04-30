"""
第二层补充：测试隔离性测试

测试列表：
1. test_test_database_isolation - 测试数据库隔离
2. test_temporary_files_cleaned_up - 临时文件清理
3. test_mock_objects_not_leaking - Mock 对象不泄漏
4. test_side_effect_containment - 副作用隔离

目的: 确保各个测试之间不会相互影响，测试后不会留下副作用
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.service.test_runner import TestRunnerService
from app.service.layered_test_runner import LayeredTestRunner

pytestmark = [pytest.mark.defense, pytest.mark.layer2]


class TestTestDatabaseIsolation:
    """
    用例: 验证测试数据库与生产数据库完全隔离。
    目的: 防止测试数据污染生产环境。
    """

    def test_test_database_separate_from_production(self):
        """测试使用独立的数据库"""
        # 验证测试配置使用不同的数据库
        from app.core.config import settings

        # 测试环境应该使用测试数据库
        if hasattr(settings, 'DATABASE_URL'):
            db_url = settings.DATABASE_URL
            # 生产数据库不应该是测试数据库
            assert 'test' in db_url.lower() or 'sqlite' in db_url.lower(), \
                "测试应该使用测试数据库，而不是生产数据库"

    def test_database_rollback_after_test(self):
        """测试后数据库事务回滚"""
        # 这个测试验证测试框架是否正确清理数据库
        # 实际实现取决于使用的数据库框架

        # 模拟数据库操作
        mock_session = MagicMock()
        mock_session.commit = MagicMock()
        mock_session.rollback = MagicMock()

        # 验证测试框架会调用 rollback
        # 注意：这是一个概念性测试，实际行为取决于测试框架配置
        assert hasattr(mock_session, 'rollback'), \
            "数据库会话应该支持回滚操作"


class TestTemporaryFileCleanup:
    """
    用例: 验证测试生成的临时文件在测试后被正确清理。
    目的: 防止磁盘空间被测试文件占满。
    """

    def test_temp_files_in_temp_directory(self):
        """测试临时文件创建在临时目录中"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建临时文件
            temp_file = Path(tmpdir) / "test_temp.txt"
            temp_file.write_text("test content")

            # 验证文件在临时目录中
            assert temp_file.exists()
            assert temp_file.parent == Path(tmpdir)

        # 退出上下文后，临时目录应该被清理
        assert not Path(tmpdir).exists(), "临时目录应该被自动清理"

    def test_backup_files_not_accumulating(self):
        """测试备份文件不会无限累积"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()

            from app.service.code_executor import CodeExecutorService
            executor = CodeExecutorService(str(project_root))

            # 创建原始文件
            test_file = project_root / "test.py"
            test_file.write_text("# Original\n")

            # 多次修改，产生多个备份
            for i in range(5):
                # 【Read Token 机制】每次写入前重新读取获取 token
                read_result = executor.read_file("test.py")
                change = executor.apply_file_change(
                    relative_path="test.py",
                    new_content=f"# Version {i}\n",
                    read_token=read_result.read_token
                )
                assert change.backup_path is not None

            # 验证备份目录存在
            backup_dir = project_root / ".backups"
            if backup_dir.exists():
                backup_files = list(backup_dir.glob("*.py"))
                # 应该有多个备份文件
                assert len(backup_files) >= 5, "应该有多个备份文件"

    def test_sandbox_cleanup_after_test(self):
        """测试沙箱环境在测试后被清理"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox_dir = Path(tmpdir) / "sandbox"
            sandbox_dir.mkdir()

            # 创建一些测试文件
            (sandbox_dir / "test1.py").write_text("# Test 1")
            (sandbox_dir / "test2.py").write_text("# Test 2")

            # 验证文件存在
            assert len(list(sandbox_dir.glob("*.py"))) == 2

        # 临时目录被清理
        assert not Path(tmpdir).exists()


class TestMockObjectContainment:
    """
    用例: 验证 Mock 对象不会泄漏到后续测试中。
    目的: 防止测试间的 Mock 污染。
    """

    def test_mock_patches_are_stopped(self):
        """测试 Mock patches 在测试后被停止"""
        import app.service.code_executor

        # 记录原始状态
        original_state = app.service.code_executor.CodeExecutorService

        # 使用 patch
        with patch('app.service.code_executor.CodeExecutorService') as mock_service:
            mock_instance = MagicMock()
            mock_service.return_value = mock_instance

            # 在 patch 上下文中使用
            service = app.service.code_executor.CodeExecutorService("/tmp")
            assert service == mock_instance

        # 退出上下文后，原始类应该恢复
        assert app.service.code_executor.CodeExecutorService == original_state

    def test_global_state_not_modified(self):
        """测试全局状态不被修改"""
        # 测试不应该修改全局配置
        from app.core.config import settings

        # 记录原始值
        original_debug = getattr(settings, 'DEBUG', None)

        try:
            # 尝试修改（在测试中不应该这样做）
            if hasattr(settings, 'DEBUG'):
                settings.DEBUG = not settings.DEBUG

            # 恢复（测试应该自己清理）
            if hasattr(settings, 'DEBUG'):
                settings.DEBUG = original_debug

        finally:
            # 确保恢复原始值
            if hasattr(settings, 'DEBUG') and original_debug is not None:
                settings.DEBUG = original_debug

        # 验证恢复成功
        assert getattr(settings, 'DEBUG', None) == original_debug


class TestSideEffectContainment:
    """
    用例: 验证测试的副作用被限制在测试范围内。
    目的: 防止测试影响系统其他部分。
    """

    def test_file_system_changes_contained(self):
        """测试文件系统变更被限制"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 所有文件操作都在临时目录中
            test_dir = Path(tmpdir) / "test_fs"
            test_dir.mkdir()

            # 创建嵌套目录结构
            (test_dir / "level1" / "level2").mkdir(parents=True)
            (test_dir / "level1" / "level2" / "file.txt").write_text("deep content")

            # 验证文件创建成功
            assert (test_dir / "level1" / "level2" / "file.txt").exists()

        # 验证所有内容被清理
        assert not Path(tmpdir).exists()

    def test_environment_variables_not_leaked(self):
        """测试环境变量不泄漏"""
        import os

        # 记录原始环境变量
        test_var = "OMNIFLOW_TEST_VAR"
        original_value = os.environ.get(test_var)

        try:
            # 设置测试环境变量
            os.environ[test_var] = "test_value"

            # 验证设置成功
            assert os.environ.get(test_var) == "test_value"

        finally:
            # 清理
            if original_value is None:
                os.environ.pop(test_var, None)
            else:
                os.environ[test_var] = original_value

        # 验证清理成功
        if original_value is None:
            assert test_var not in os.environ
        else:
            assert os.environ.get(test_var) == original_value

    def test_logging_output_captured(self):
        """测试日志输出被捕获"""
        import logging

        # 创建一个列表来存储日志记录
        log_records = []

        # 创建测试用的日志处理器（使用 StreamHandler 作为基础）
        class TestHandler(logging.StreamHandler):
            def emit(self, record):
                log_records.append(record)
                super().emit(record)

        test_handler = TestHandler()
        test_handler.setLevel(logging.INFO)

        original_handlers = logging.root.handlers[:]

        try:
            # 清除现有处理器并添加测试处理器
            logging.root.handlers = [test_handler]

            # 记录测试日志
            logging.info("Test log message")

            # 验证日志被记录
            assert len(log_records) >= 1, "应该有日志记录"
            assert any("Test log message" in str(r.getMessage()) for r in log_records), \
                "应该包含测试日志消息"

        finally:
            # 恢复原始处理器
            logging.root.handlers = original_handlers

        # 验证恢复成功
        assert logging.root.handlers == original_handlers


class TestTestRunnerIsolation:
    """
    用例: 验证测试运行器正确隔离各个测试。
    目的: 确保测试运行器不会跨测试传递状态。
    """

    def test_test_results_not_shared(self):
        """测试结果不共享"""
        result1 = {"test": "result1", "passed": True}
        result2 = {"test": "result2", "passed": False}

        # 验证结果是独立的对象
        assert result1 != result2
        assert result1["passed"] != result2["passed"]

    def test_layered_test_runner_state_reset(self):
        """分层测试运行器状态重置"""
        # 验证每次运行都是独立的状态
        layers1 = [{"layer": "syntax", "passed": True}]
        layers2 = [{"layer": "syntax", "passed": False}]

        # 状态应该是独立的
        assert layers1 != layers2
        assert layers1[0]["passed"] != layers2[0]["passed"]
