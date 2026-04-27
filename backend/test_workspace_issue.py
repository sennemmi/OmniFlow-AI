"""
测试脚本：重现工作区测试文件缺失问题
"""
import asyncio
import tempfile
from pathlib import Path
import shutil

from app.service.workspace import WorkspaceService
from app.service.test_runner import TestRunnerService


async def test_workspace_structure():
    """测试工作区目录结构"""
    pipeline_id = 999
    
    # 创建工作区
    ws = WorkspaceService(pipeline_id)
    workspace_path = await ws.create_workspace_async()
    
    print(f"工作区路径: {workspace_path}")
    print(f"工作区是否存在: {workspace_path.exists()}")
    
    # 检查目录结构
    def list_dir(path, indent=0):
        if not path.exists():
            print(" " * indent + f"[不存在] {path}")
            return
        print(" " * indent + f"[DIR] {path.name}")
        try:
            for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                if item.is_dir():
                    if item.name in ["__pycache__", ".git", "node_modules"]:
                        print(" " * (indent + 2) + f"[SKIP] {item.name}")
                    else:
                        list_dir(item, indent + 2)
                else:
                    print(" " * (indent + 2) + f"[FILE] {item.name}")
        except PermissionError:
            print(" " * (indent + 2) + "[权限不足]")
    
    print("\n=== 工作区目录结构 ===")
    list_dir(workspace_path)
    
    # 检查 tests 目录
    root_tests = workspace_path / "tests"
    backend_tests = workspace_path / "backend" / "tests"
    
    print(f"\n=== 测试目录检查 ===")
    print(f"根目录 tests/: {root_tests.exists()} - {root_tests}")
    print(f"backend/tests/: {backend_tests.exists()} - {backend_tests}")
    
    if root_tests.exists():
        print(f"\n根目录 tests/ 内容:")
        for item in root_tests.iterdir():
            print(f"  - {item.name}")
    
    if backend_tests.exists():
        print(f"\nbackend/tests/ 内容:")
        for item in backend_tests.iterdir():
            print(f"  - {item.name}")
    
    # 运行测试
    print(f"\n=== 运行测试 ===")
    result = await TestRunnerService.run_tests(str(workspace_path))
    print(f"测试成功: {result['success']}")
    print(f"退出码: {result['exit_code']}")
    print(f"总结: {result['summary']}")
    print(f"错误类型: {result.get('error_type')}")
    print(f"错误: {result.get('error')}")
    
    # 清理
    await ws.cleanup_async()
    print("\n工作区已清理")


if __name__ == "__main__":
    asyncio.run(test_workspace_structure())
