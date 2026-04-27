"""
调试 TestRunnerService 的路径检测逻辑
"""
import asyncio
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))


async def debug_path_logic():
    """
    模拟 TestRunnerService 的路径检测逻辑
    """
    # 创建临时目录结构
    tmpdir = Path(tempfile.mkdtemp(prefix="debug_pipeline_"))
    
    try:
        # 创建工作区结构:
        # tmpdir/
        #   backend/
        #     app/
        #     tests/
        #   tests/          <- 应该优先使用这个
        
        (tmpdir / "backend" / "app").mkdir(parents=True)
        (tmpdir / "backend" / "tests").mkdir(parents=True)
        (tmpdir / "tests").mkdir(parents=True)
        
        # 创建测试文件
        (tmpdir / "tests" / "test_example.py").write_text("""
def test_example():
    assert True
""")
        (tmpdir / "backend" / "tests" / "test_backend.py").write_text("""
def test_backend():
    assert True
""")
        
        print(f"工作区: {tmpdir}")
        print(f"\n目录结构:")
        for item in tmpdir.rglob("*"):
            if item.is_file():
                print(f"  {item.relative_to(tmpdir)}")
        
        # 模拟 TestRunnerService 的逻辑
        cwd = tmpdir  # 这是传入的 project_path
        
        print(f"\n=== 路径检测逻辑 ===")
        print(f"cwd: {cwd}")
        print(f"cwd.name: {cwd.name}")
        
        root_tests_path = cwd / "tests"
        backend_path = cwd / "backend" if (cwd / "backend").exists() else None
        
        print(f"root_tests_path: {root_tests_path} (exists: {root_tests_path.exists()})")
        print(f"backend_path: {backend_path} (exists: {backend_path.exists() if backend_path else False})")
        
        # 检测父目录是否有 tests/
        parent_tests_path = cwd.parent / "tests" if cwd.name == "backend" else None
        print(f"parent_tests_path: {parent_tests_path}")
        
        if parent_tests_path and parent_tests_path.exists():
            print("-> 进入分支: cwd 是 backend/，使用父目录的 tests/")
            project_root = cwd.parent
            root_tests_path = parent_tests_path
        else:
            print("-> 进入分支: cwd 是项目根目录")
            project_root = cwd
        
        print(f"project_root: {project_root}")
        print(f"root_tests_path (最终): {root_tests_path}")
        
        # 确定 backend 路径
        if backend_path is None and (project_root / "backend").exists():
            backend_path = project_root / "backend"
        elif backend_path is None:
            backend_path = project_root
        
        print(f"backend_path (最终): {backend_path}")
        
        # 检查 tests/ 内容
        if root_tests_path.exists():
            items = list(root_tests_path.iterdir())
            print(f"\nroot_tests_path 内容: {items}")
            print(f"any(root_tests_path.iterdir()): {any(items)}")
        
        # 智能选择测试路径
        print(f"\n=== 测试路径选择 ===")
        if root_tests_path.exists() and any(root_tests_path.iterdir()):
            print(f"-> 选择: 项目根目录的 tests/")
            run_dir = project_root
            tests_path = root_tests_path
        elif (backend_path / "tests").exists():
            print(f"-> 选择: backend/tests/")
            run_dir = backend_path
            tests_path = backend_path / "tests"
        else:
            print(f"-> 选择: 默认根目录 tests/")
            run_dir = project_root
            tests_path = root_tests_path
        
        print(f"run_dir: {run_dir}")
        print(f"tests_path: {tests_path}")
        
        # 实际运行测试
        print(f"\n=== 实际运行测试 ===")
        from app.service.test_runner import TestRunnerService
        result = await TestRunnerService.run_tests(str(cwd), timeout=30)
        
        print(f"结果:")
        print(f"  success: {result['success']}")
        print(f"  exit_code: {result['exit_code']}")
        print(f"  summary: {result['summary']}")
        
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(debug_path_logic())
