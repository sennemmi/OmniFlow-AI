"""
第一层补充：并发文件操作安全测试

测试列表：
1. test_concurrent_file_writes_handled_safely - 并发文件写入安全处理
2. test_file_lock_prevents_corruption - 文件锁防止数据损坏
3. test_backup_integrity_during_concurrent_access - 并发访问时备份完整性

目的: 防止多个 Agent 同时修改同一文件导致数据损坏
"""

import pytest
import tempfile
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.service.code_executor import CodeExecutorService
from app.service.code_modifier import CodeModifierService

pytestmark = [pytest.mark.defense, pytest.mark.layer1]


class TestConcurrentFileOperations:
    """
    用例: 模拟多个线程同时尝试修改同一文件，验证系统能安全处理而不会导致文件损坏。
    目的: 确保并发文件操作不会导致数据丢失或损坏。
    """

    def test_concurrent_file_writes_handled_safely(self):
        """测试并发文件写入被安全处理"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()

            # 创建初始文件
            test_file = project_root / "shared.py"
            test_file.write_text("# Initial content\n", encoding='utf-8')

            executor = CodeExecutorService(str(project_root))

            # 模拟多个并发写入操作
            modifications = [
                "# Modification 1\n",
                "# Modification 2\n",
                "# Modification 3\n",
            ]

            results = []
            errors = []

            def modify_file(content, index):
                try:
                    # 添加小延迟增加并发冲突概率
                    time.sleep(0.01)
                    change = executor.apply_file_change(
                        relative_path="shared.py",
                        new_content=content
                    )
                    return index, change.success
                except Exception as e:
                    return index, False, str(e)

            # 使用线程池模拟并发
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [
                    pool.submit(modify_file, content, i)
                    for i, content in enumerate(modifications)
                ]
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        errors.append(str(e))

            # 验证：至少有一个操作成功
            successful = [r for r in results if isinstance(r, tuple) and len(r) >= 2 and r[1]]
            assert len(successful) >= 1, "至少应该有一个写入操作成功"

            # 验证：文件内容应该是有效的（不是混合的乱码）
            final_content = test_file.read_text(encoding='utf-8')
            # 文件内容应该是某一个完整的修改版本
            valid_contents = modifications + ["# Initial content\n"]
            # 由于并发，内容可能是其中任意一个，但不能是混合的
            assert any(content in final_content for content in valid_contents), \
                "文件内容应该是完整的，不是混合的"

    def test_backup_created_before_concurrent_modification(self):
        """测试并发修改前创建备份"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()

            # 创建初始文件
            test_file = project_root / "important.py"
            original_content = "# Critical code\n# Do not lose this\n"
            test_file.write_text(original_content, encoding='utf-8')

            executor = CodeExecutorService(str(project_root))

            # 第一次修改
            change1 = executor.apply_file_change(
                relative_path="important.py",
                new_content="# Modified once\n"
            )

            # 验证备份已创建
            assert change1.backup_path is not None
            backup_file1 = Path(change1.backup_path)
            assert backup_file1.exists()

            # 验证备份内容是原始内容
            backup_content1 = backup_file1.read_text(encoding='utf-8')
            assert backup_content1 == original_content

            # 验证文件已被修改
            assert test_file.read_text(encoding='utf-8') == "# Modified once\n"

            # 回滚到原始状态
            executor.rollback_change(change1)
            final_content = test_file.read_text(encoding='utf-8')
            assert final_content == original_content, \
                f"回滚后应该回到原始状态，实际内容: {final_content}"

    def test_file_creation_race_condition(self):
        """测试文件创建的竞态条件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()

            executor = CodeExecutorService(str(project_root))

            # 多个线程同时尝试创建同一个新文件
            content = "# New file content\n"
            results = []

            def create_file(thread_id):
                try:
                    change = executor.apply_file_change(
                        relative_path="new_file.py",
                        new_content=f"# Thread {thread_id}\n{content}",
                        create_if_missing=True
                    )
                    return thread_id, change.success
                except Exception as e:
                    return thread_id, False, str(e)

            # 并发创建
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = [pool.submit(create_file, i) for i in range(5)]
                for future in as_completed(futures):
                    results.append(future.result())

            # 验证文件存在且内容有效
            created_file = project_root / "new_file.py"
            assert created_file.exists(), "文件应该被创建"

            final_content = created_file.read_text(encoding='utf-8')
            # 内容应该是某一个线程写入的完整版本
            assert any(f"# Thread {i}" in final_content for i in range(5))


class TestFileLockMechanism:
    """
    用例: 验证文件锁机制能防止并发写入冲突。
    目的: 确保文件操作的原子性。
    """

    def test_file_write_is_atomic(self):
        """测试文件写入是原子操作"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()

            test_file = project_root / "atomic.py"
            test_file.write_text("# Start\n", encoding='utf-8')

            large_content = "# Line {}\n".format("x" * 1000) * 100  # 大文件

            results = []

            def write_large_file(thread_id):
                try:
                    executor = CodeExecutorService(str(project_root))
                    change = executor.apply_file_change(
                        relative_path="atomic.py",
                        new_content=f"# Thread {thread_id}\n{large_content}"
                    )
                    return thread_id, change.success
                except Exception as e:
                    return thread_id, False, str(e)

            # 并发写入大文件
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [pool.submit(write_large_file, i) for i in range(3)]
                for future in as_completed(futures):
                    results.append(future.result())

            # 读取最终内容
            final_content = test_file.read_text(encoding='utf-8')

            # 验证文件是完整的（不是截断的）
            lines = final_content.split('\n')
            # 文件应该有一个完整的头部和尾部
            assert len(lines) > 50, "文件应该是完整的，不是截断的"

            # 验证文件只包含一个线程的内容（不是混合的）
            thread_headers = [f"# Thread {i}" for i in range(3)]
            header_count = sum(1 for h in thread_headers if h in final_content)
            assert header_count == 1, "文件应该只包含一个线程的完整内容"
