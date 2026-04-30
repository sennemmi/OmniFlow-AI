"""
Auto-Fix 修复流程验证脚本

只验证核心的 auto-fix 循环：
1. 生成有错误的代码
2. 运行测试（预期失败）
3. 调用 VerifyAgent 验证
4. 调用 RepairerAgent 修复
5. 再次运行测试（预期通过）

使用方法:
    cd backend
    python scripts/test_auto_fix_only.py
"""

import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List

# 添加 backend 到路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.repairer import RepairerAgent
from app.agents.verify_agent import VerifyAgent, verify_fixes
from app.service.test_runner import TestRunnerService
from app.service.code_executor import CodeExecutorService


class AutoFixTester:
    """Auto-Fix 流程测试器"""

    def __init__(self):
        self.test_results = []

    async def run_test(self):
        """运行 Auto-Fix 测试"""
        print("=" * 70)
        print("🧪 Auto-Fix 修复流程验证")
        print("=" * 70)

        # 创建临时工作目录
        workspace = tempfile.mkdtemp(prefix="autofix_test_")
        print(f"\n📁 创建工作目录: {workspace}")

        try:
            # 准备测试项目
            await self._prepare_test_project(workspace)

            # 运行测试流程
            success = await self._run_auto_fix_loop(workspace)

            if success:
                print("\n" + "=" * 70)
                print("✅ Auto-Fix 流程验证通过!")
                print("=" * 70)
            else:
                print("\n" + "=" * 70)
                print("❌ Auto-Fix 流程验证失败!")
                print("=" * 70)

            return success

        finally:
            # 清理
            shutil.rmtree(workspace, ignore_errors=True)
            print(f"\n🗑️  清理工作目录")

    async def _prepare_test_project(self, workspace: str):
        """准备测试项目 - 创建一个简单的有错误的 Python 项目"""
        print("\n📦 准备测试项目...")

        ws_path = Path(workspace)

        # 创建项目结构
        (ws_path / "app").mkdir()
        (ws_path / "tests").mkdir()

        # 创建有错误的代码文件
        # 错误: add 函数返回了错误的计算结果
        buggy_code = '''
def add(a, b):
    """加法函数 - 有错误"""
    return a - b  # ❌ 错误: 应该是 a + b

def subtract(a, b):
    """减法函数"""
    return a - b
'''

        (ws_path / "app" / "calculator.py").write_text(buggy_code, encoding="utf-8")
        print("   ✓ 创建有错误的 calculator.py")

        # 创建测试文件
        test_code = '''
import pytest
from app.calculator import add, subtract

def test_add():
    """测试加法"""
    assert add(2, 3) == 5  # 期望 5，但实际得到 -1

def test_subtract():
    """测试减法"""
    assert subtract(5, 3) == 2
'''

        (ws_path / "tests" / "test_calculator.py").write_text(test_code, encoding="utf-8")
        print("   ✓ 创建测试文件 test_calculator.py")

        # 创建 __init__.py
        (ws_path / "app" / "__init__.py").touch()
        (ws_path / "tests" / "__init__.py").touch()
        print("   ✓ 创建 __init__.py 文件")

    async def _run_auto_fix_loop(self, workspace: str) -> bool:
        """运行 Auto-Fix 循环"""
        print("\n" + "=" * 70)
        print("🔄 开始 Auto-Fix 循环")
        print("=" * 70)

        max_retries = 3
        attempt = 1

        while attempt <= max_retries:
            print(f"\n📍 第 {attempt}/{max_retries} 次尝试")
            print("-" * 70)

            # Step 1: 运行测试
            print("\n[Step 1] 运行测试...")
            test_result = await TestRunnerService.run_tests(
                project_path=workspace,
                test_path="tests/",
                timeout=60
            )

            if test_result["success"]:
                print("   ✅ 测试通过!")
                return True

            print(f"   ❌ 测试失败: {test_result['summary']}")

            # Step 2: VerifyAgent 验证
            print("\n[Step 2] VerifyAgent 独立验证...")
            verify_result = await verify_fixes(
                test_runner=TestRunnerService,
                test_path="tests/",
                generated_files=["app/calculator.py"],
                project_path=workspace
            )

            print(f"   验证结果: {verify_result['verdict']}")
            print(f"   错误数量: {verify_result['error_count']}")

            if verify_result['errors']:
                print("   错误列表:")
                for err in verify_result['errors'][:3]:
                    print(f"      - {err}")

            if verify_result['verdict'] == "PASS":
                print("   ✅ 验证通过!")
                return True

            # Step 3: RepairerAgent 修复
            print("\n[Step 3] RepairerAgent 修复...")

            # 构建修复工单 - 始终使用正确的源文件路径
            # 注意：不要依赖 structured_errors 中的 file_path，因为它可能是测试文件路径
            errors_list = [
                {
                    "file_path": "app/calculator.py",
                    "line": 4,
                    "severity": "critical",
                    "summary": "add 函数计算错误",
                    "detail": "add(2, 3) 返回了 -1 而不是 5，期望返回 5",
                    "fix_hint": "将 `return a - b` 改为 `return a + b`"
                }
            ]

            fix_order = {
                "type": "fix_order",
                "category": "code_bug",
                "source": "VerifyAgent",
                "errors": errors_list,
                "generated_files": ["app/calculator.py"],
                "fix_hint": "修复 app/calculator.py 中的 add 函数：将减法改为加法"
            }

            print(f"   修复工单: {len(errors_list)} 个错误项")
            for err in errors_list:
                print(f"      - {err.get('file_path')}:{err.get('line')}: {err.get('summary', '')}")

            repairer = RepairerAgent()
            repair_result = await repairer.execute_with_reread(
                pipeline_id=99999,
                stage_name="AUTOFIX_TEST",
                fix_order=fix_order,
                project_path=workspace
            )

            if not repair_result.get("success"):
                print(f"   ❌ RepairerAgent 修复失败: {repair_result.get('error', '未知错误')}")
                attempt += 1
                continue

            # 应用修复
            repair_output = repair_result.get("output", {})
            files_changed = repair_output.get("files", [])

            print(f"   ✅ RepairerAgent 完成，生成 {len(files_changed)} 个文件修复")

            # 使用 CodeExecutorService 应用修复
            code_executor = CodeExecutorService(workspace)

            for file_change in files_changed:
                file_path = file_change.get("file_path", "")
                relative_path = file_path.replace("backend/", "").replace("backend\\", "")

                # 读取文件获取 read_token
                read_result = code_executor.read_file(relative_path)

                # 应用修改
                search_block = file_change.get("search_block", "")
                replace_block = file_change.get("replace_block", "")

                if search_block and read_result.content:
                    new_content = read_result.content.replace(search_block, replace_block, 1)

                    result = code_executor.apply_file_change(
                        relative_path=relative_path,
                        new_content=new_content,
                        read_token=read_result.read_token
                    )

                    if result.success:
                        print(f"      ✓ 应用修复: {file_path}")
                    else:
                        print(f"      ❌ 应用修复失败: {file_path} - {result.error}")

            print(f"\n   🔄 修复已应用，准备下一次验证...")
            attempt += 1

        print(f"\n❌ 达到最大重试次数 ({max_retries})，Auto-Fix 失败")
        return False


async def main():
    """主函数"""
    tester = AutoFixTester()
    success = await tester.run_test()

    # 返回退出码
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
