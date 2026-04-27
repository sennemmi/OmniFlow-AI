"""
模拟完整的工作区创建和测试流程
"""
import asyncio
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from app.service.workspace import WorkspaceService
from app.service.test_runner import TestRunnerService


async def test_full_workflow():
    """
    测试完整流程:
    1. 创建 WorkspaceService
    2. 创建临时工作区
    3. 检查工作区结构
    4. 运行测试
    """
    pipeline_id = 99999
    
    # 创建服务
    ws = WorkspaceService(pipeline_id)
    
    print(f"目标项目路径: {ws.target_path}")
    print(f"目标项目是否存在: {ws.target_path.exists()}")
    
    # 检查源项目结构
    if ws.target_path.exists():
        print(f"\n=== 源项目结构 ===")
        for item in ws.target_path.iterdir():
            print(f"  {item.name}/" if item.is_dir() else f"  {item.name}")
        
        source_tests = ws.target_path / "tests"
        print(f"\n源项目 tests/ 存在: {source_tests.exists()}")
        if source_tests.exists():
            print(f"源项目 tests/ 内容:")
            for item in source_tests.iterdir():
                print(f"  {item.name}")
    
    # 创建工作区
    workspace_path = await ws.create_workspace_async()
    
    try:
        print(f"\n=== 工作区创建完成 ===")
        print(f"工作区路径: {workspace_path}")
        
        # 检查工作区结构
        print(f"\n=== 工作区结构 ===")
        for item in workspace_path.iterdir():
            print(f"  {item.name}/" if item.is_dir() else f"  {item.name}")
        
        # 检查 tests/
        ws_tests = workspace_path / "tests"
        print(f"\n工作区 tests/ 存在: {ws_tests.exists()}")
        if ws_tests.exists():
            print(f"工作区 tests/ 内容:")
            for item in ws_tests.iterdir():
                print(f"  {item.name}")
        else:
            print("❌ 工作区缺少 tests/ 目录!")
        
        # 检查 backend/
        ws_backend = workspace_path / "backend"
        print(f"\n工作区 backend/ 存在: {ws_backend.exists()}")
        if ws_backend.exists():
            print(f"工作区 backend/ 内容:")
            for item in ws_backend.iterdir():
                print(f"  {item.name}/" if item.is_dir() else f"  {item.name}")
        
        # 运行测试
        print(f"\n=== 运行测试 ===")
        print(f"传入的 project_path: {workspace_path}")
        
        result = await TestRunnerService.run_tests(str(workspace_path), timeout=60)
        
        print(f"\n测试结果:")
        print(f"  success: {result['success']}")
        print(f"  exit_code: {result['exit_code']}")
        print(f"  summary: {result['summary']}")
        print(f"  error_type: {result.get('error_type')}")
        print(f"  logs 前800字符:\n{result['logs'][:800]}")
        
    finally:
        # 清理
        await ws.cleanup_async()
        print(f"\n工作区已清理")


if __name__ == "__main__":
    asyncio.run(test_full_workflow())
