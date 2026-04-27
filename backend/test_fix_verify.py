"""
验证 TestRunnerService 修复的测试脚本
"""
import asyncio
import sys
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent))

from app.service.test_runner import TestRunnerService


async def test_from_backend_subdir():
    """测试从 backend/ 子目录运行测试"""
    # 模拟工作区结构: pipeline_xxx/backend/
    # 但测试文件在 pipeline_xxx/tests/
    
    # 使用实际的项目路径测试
    project_root = Path("d:/feishuProj/workspace/feishutemp")
    backend_path = project_root / "backend"
    
    print("=== 测试场景: 从项目根目录运行 ===")
    print(f"项目根目录: {project_root}")
    print(f"backend 目录: {backend_path}")
    print(f"根目录 tests/: {project_root / 'tests'} (exists: {(project_root / 'tests').exists()})")
    print(f"backend/tests/: {backend_path / 'tests'} (exists: {(backend_path / 'tests').exists()})")
    
    # 测试从项目根目录运行
    result = await TestRunnerService.run_tests(str(project_root), timeout=60)
    print(f"\n从根目录运行结果:")
    print(f"  success: {result['success']}")
    print(f"  exit_code: {result['exit_code']}")
    print(f"  summary: {result['summary']}")
    print(f"  error_type: {result.get('error_type')}")
    
    print("\n=== 测试场景: 从 backend/ 子目录运行 ===")
    # 测试从 backend/ 子目录运行（模拟工作区情况）
    result2 = await TestRunnerService.run_tests(str(backend_path), timeout=60)
    print(f"\n从 backend/ 运行结果:")
    print(f"  success: {result2['success']}")
    print(f"  exit_code: {result2['exit_code']}")
    print(f"  summary: {result2['summary']}")
    print(f"  error_type: {result2.get('error_type')}")


if __name__ == "__main__":
    asyncio.run(test_from_backend_subdir())
