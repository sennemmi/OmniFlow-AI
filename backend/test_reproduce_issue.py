"""
复刻 TestRunner 测试失败问题的脚本

问题描述:
- 工作区路径: C:\Users\98778\AppData\Local\Temp\omniflow_workspaces\pipeline_xxx\backend
- 但测试文件在: ...\omniflow_workspaces\pipeline_xxx\tests
- 导致 collected 0 items
"""
import asyncio
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from app.service.test_runner import TestRunnerService


async def reproduce_issue():
    """
    复刻问题:
    1. 创建临时目录结构模拟工作区
    2. 复制 backend 到工作区
    3. 复制 tests 到工作区根目录
    4. 从 backend/ 子目录运行测试
    """
    # 创建临时目录
    tmpdir = Path(tempfile.mkdtemp(prefix="test_pipeline_"))
    print(f"临时工作区: {tmpdir}")
    
    try:
        # 源项目路径
        source_project = Path("d:/feishuProj/workspace/feishutemp")
        source_backend = source_project / "backend"
        source_tests = source_project / "tests"
        
        print(f"\n源项目: {source_project}")
        print(f"源 backend: {source_backend} (exists: {source_backend.exists()})")
        print(f"源 tests: {source_tests} (exists: {source_tests.exists()})")
        
        # 模拟 WorkspaceService 的行为:
        # 它只复制 target_path (即 workspace/feishutemp) 到工作区
        # 但 execute_with_auto_fix 传入的是 workspace_path/backend
        
        # 创建工作区结构:
        # tmpdir/
        #   backend/          <- 这是传入的 workspace_path
        #     app/
        #     tests/          <- backend 自带的测试
        #   tests/            <- 项目根目录的测试 (应该被优先使用)
        
        workspace_backend = tmpdir / "backend"
        workspace_root_tests = tmpdir / "tests"
        
        # 复制 backend
        if source_backend.exists():
            shutil.copytree(source_backend, workspace_backend)
            print(f"\n复制 backend 到: {workspace_backend}")
        
        # 复制 tests 到根目录
        if source_tests.exists():
            shutil.copytree(source_tests, workspace_root_tests)
            print(f"复制 tests 到: {workspace_root_tests}")
        
        # 检查结构
        print(f"\n=== 工作区结构 ===")
        for item in tmpdir.iterdir():
            print(f"  {item.name}/")
        
        print(f"\nbackend/ 结构:")
        for item in workspace_backend.iterdir():
            print(f"  {item.name}/")
        
        # 关键: 模拟 execute_with_auto_fix 传入的路径
        # 它传入的是 workspace_path，而 workspace_path 是 backend/
        test_path = workspace_backend  # 这就是问题所在!
        
        print(f"\n=== 测试场景 ===")
        print(f"传入的 project_path: {test_path}")
        print(f"这是 backend/ 子目录，但测试在父目录的 tests/")
        
        # 运行测试
        print(f"\n=== 运行 TestRunnerService.run_tests ===")
        result = await TestRunnerService.run_tests(str(test_path), timeout=60)
        
        print(f"\n结果:")
        print(f"  success: {result['success']}")
        print(f"  exit_code: {result['exit_code']}")
        print(f"  summary: {result['summary']}")
        print(f"  error_type: {result.get('error_type')}")
        print(f"  logs 前500字符:\n{result['logs'][:500]}")
        
        # 分析问题
        print(f"\n=== 问题分析 ===")
        if result['exit_code'] == 5 and 'no tests ran' in result['summary'].lower():
            print("❌ 复刻成功: 测试未收集到 (exit_code=5)")
            print("   原因: 从 backend/ 运行，但测试在父目录的 tests/")
        elif result['success']:
            print("✅ 修复成功: 测试正常运行")
        else:
            print(f"⚠️ 其他错误: {result.get('error')}")
        
    finally:
        # 清理
        shutil.rmtree(tmpdir, ignore_errors=True)
        print(f"\n清理临时目录: {tmpdir}")


if __name__ == "__main__":
    asyncio.run(reproduce_issue())
