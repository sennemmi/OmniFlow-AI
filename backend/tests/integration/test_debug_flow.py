"""
集成测试：测试执行流程调试
验证 TestRunnerService 的不同场景
"""
import pytest
import os
import shutil
import time
from pathlib import Path
from app.service.test_runner import TestRunnerService


def safe_rmtree(path: Path, max_retries=3):
    """安全删除目录，处理 Windows 文件锁问题"""
    if not path.exists():
        return

    # 先尝试删除 .pytest_cache 目录
    pytest_cache = path / ".pytest_cache"
    if pytest_cache.exists():
        try:
            shutil.rmtree(pytest_cache)
        except:
            pass

    # 重试删除主目录
    for i in range(max_retries):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if i < max_retries - 1:
                time.sleep(0.5)
            else:
                try:
                    shutil.rmtree(path)
                except:
                    pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sandbox_environment_health():
    """
    验证测试沙盒环境是否能跑通最简单的逻辑
    如果失败，说明 TestRunnerService 的 PYTHONPATH 设置或基础命令有问题
    """
    test_dir = Path("./test_sandbox_1")
    test_dir.mkdir(exist_ok=True)

    # 模拟 AI 生成一个最简单的加法函数和测试
    code = "def add(a, b): return a + b"
    test_code = "from logic import add\ndef test_add(): assert add(1, 2) == 3"

    # 写入文件
    (test_dir / "logic.py").write_text(code)
    (test_dir / "test_logic.py").write_text(test_code)
    (test_dir / "__init__.py").touch()

    # 运行测试
    result = await TestRunnerService.run_tests(str(test_dir.absolute()))

    assert result["success"] is True, f"基础环境测试失败: {result['logs']}"

    safe_rmtree(test_dir)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deep_import_resolution():
    """
    验证深层目录嵌套时，导入是否会失败
    如果报错 ModuleNotFoundError，说明 TestRunnerService 的 env['PYTHONPATH'] 注入逻辑没写对
    """
    root = Path("./test_sandbox_2")
    # 模拟复杂结构
    (root / "app/models").mkdir(parents=True, exist_ok=True)
    (root / "app/service").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)

    # 补齐所有 __init__.py
    for p in [root, root/"app", root/"app/models", root/"app/service", root/"tests"]:
        (p / "__init__.py").touch()

    # 模拟代码引用
    (root / "app/models/user.py").write_text("class User: pass")
    (root / "app/service/auth.py").write_text("from app.models.user import User\ndef login(): return User()")
    (root / "tests/test_auth.py").write_text("from app.service.auth import login\ndef test_login(): assert login() is not None")

    # 运行测试
    result = await TestRunnerService.run_tests(str(root.absolute()))

    assert result["success"] is True, f"深度导入测试失败: {result['logs']}"

    safe_rmtree(root)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_code_execution():
    """
    验证 AI 生成的异步测试是否能正确识别并运行
    如果报错 'NoneType' has no attribute 'get_loop'，说明环境里缺 pytest-asyncio
    """
    root = Path("./test_sandbox_3")
    root.mkdir(exist_ok=True)
    (root / "__init__.py").touch()

    # 模拟异步代码
    (root / "logic.py").write_text("async def get_val(): return 100")
    (root / "test_async.py").write_text(
        "import pytest\n"
        "from logic import get_val\n"
        "@pytest.mark.asyncio\n"
        "async def test_val(): assert await get_val() == 100"
    )

    result = await TestRunnerService.run_tests(str(root.absolute()))

    assert result["success"] is True, f"异步代码测试失败: {result['logs']}"

    safe_rmtree(root)
