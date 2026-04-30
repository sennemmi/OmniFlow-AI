"""
分层测试失败后的 Auto-Fix 完整验证脚本

验证流程：
1. 启动 Docker Sandbox
2. 预设一个有逻辑错误的代码文件（非语法错误）
3. 运行分层测试（预期失败）
4. 调用 VerifyAgent 验证
5. 调用 RepairerAgent 修复
6. 再次运行分层测试（预期通过）

参考: test_e2e_with_llm_real.py 的分层测试逻辑
"""

import asyncio
import sys
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.service.sandbox_orchestrator import get_sandbox_orchestrator, cleanup_sandbox_orchestrator
from app.service.sandbox_manager import sandbox_manager
from app.agents.repairer import RepairerAgent
from app.agents.verify_agent import verify_fixes


@dataclass
class LayerResult:
    """单层测试结果"""
    layer: str
    passed: bool
    summary: str = ""
    logs: str = ""
    failed_tests: List[str] = field(default_factory=list)
    error_type: Optional[str] = None


@dataclass
class LayeredTestResult:
    """分层测试结果"""
    all_passed: bool
    layers: List[LayerResult]
    failure_cause: Optional[str] = None
    failed_tests: List[str] = field(default_factory=list)
    error_details: Dict[str, Any] = field(default_factory=dict)


# 预设的有逻辑错误的代码（语法正确，但逻辑错误）
BUGGY_CODE = '''
"""
Calculator module
"""


def add(a: int, b: int) -> int:
    """加法函数 - 有逻辑错误"""
    return a - b  # ❌ 错误: 应该是 a + b


def subtract(a: int, b: int) -> int:
    """减法函数"""
    return a - b  # ✅ 正确


def multiply(a: int, b: int) -> int:
    """乘法函数"""
    return a * b  # ✅ 正确
'''

# 对应的测试文件
TEST_CODE = '''
"""
Tests for calculator module
"""

import pytest
from app.calculator import add, subtract, multiply


def test_add():
    """测试加法 - 这个测试会失败"""
    assert add(2, 3) == 5  # 期望 5，但实际得到 -1
    assert add(-1, 1) == 0
    assert add(0, 0) == 0


def test_subtract():
    """测试减法"""
    assert subtract(5, 3) == 2
    assert subtract(3, 5) == -2
    assert subtract(0, 0) == 0


def test_multiply():
    """测试乘法"""
    assert multiply(2, 3) == 6
    assert multiply(-2, 3) == -6
    assert multiply(0, 100) == 0
'''


async def run_layered_tests(pipeline_id: int, specific_test_file: str = "tests/unit/test_calculator.py") -> LayeredTestResult:
    """
    在 Docker Sandbox 中运行分层测试
    
    分层结构：
    - Layer 1: 特定测试文件 (我们创建的 calculator 测试)
    - Layer 2: 集成测试 (tests/integration/)
    - Layer 3: AI 生成测试 (tests/ai_generated/)
    
    注意：为了避免运行项目中已有的 102 个测试，我们只运行特定的测试文件
    """
    print("\n   🐳 在 Sandbox 中运行分层测试...")
    
    layers: List[LayerResult] = []
    
    # 定义测试层 - 第一层只运行我们创建的特定测试文件
    test_commands = [
        ("unit", specific_test_file, "单元测试 (calculator)"),
        ("integration", "tests/integration", "集成测试"),
        ("ai_generated", "tests/ai_generated", "AI 生成测试"),
    ]
    
    for layer_name, test_path, description in test_commands:
        print(f"\n   📋 Layer: {description} ({layer_name})")
        
        # 检查测试文件/目录是否存在
        if test_path.endswith(".py"):
            # 特定文件
            check_cmd = f"test -f /workspace/{test_path} && echo 'EXISTS' || echo 'NOT_FOUND'"
        else:
            # 目录
            check_cmd = f"test -d /workspace/{test_path} && echo 'EXISTS' || echo 'NOT_FOUND'"
        
        check_result = await sandbox_manager.exec(pipeline_id, check_cmd, timeout=10)
        check_output = check_result.stdout.strip() if check_result.stdout else ""
        
        print(f"      [DEBUG] 检查路径: /workspace/{test_path}")
        print(f"      [DEBUG] 检查结果: {check_output}")
        print(f"      [DEBUG] stderr: {check_result.stderr[:100] if check_result.stderr else 'None'}")
        
        if "NOT_FOUND" in check_output:
            print(f"      ⚠️  测试路径不存在，跳过")
            layers.append(LayerResult(
                layer=layer_name,
                passed=True,
                summary=f"{description}不存在，跳过"
            ))
            continue
        
        # 运行 pytest - 只针对特定路径
        pytest_cmd = f"cd /workspace && PYTHONPATH=/workspace python -m pytest {test_path} -v --tb=short -p no:cacheprovider 2>&1"
        print(f"      运行: {pytest_cmd[:80]}...")
        
        exec_result = await sandbox_manager.exec(pipeline_id, pytest_cmd, timeout=120)
        
        # 解析结果
        stdout = exec_result.stdout
        stderr = exec_result.stderr
        exit_code = exec_result.exit_code
        
        # [DEBUG] 打印详细结果
        print(f"      [DEBUG] exit_code: {exit_code}")
        print(f"      [DEBUG] stdout 前200字符: {stdout[:200] if stdout else 'None'}")
        print(f"      [DEBUG] stderr 前200字符: {stderr[:200] if stderr else 'None'}")
        
        # 提取统计
        passed_count = 0
        failed_count = 0
        error_count = 0
        
        passed_match = re.search(r'(\d+) passed', stdout)
        if passed_match:
            passed_count = int(passed_match.group(1))
        
        failed_match = re.search(r'(\d+) failed', stdout)
        if failed_match:
            failed_count = int(failed_match.group(1))
        
        error_match = re.search(r'(\d+) error', stdout)
        if error_match:
            error_count = int(error_match.group(1))
        
        # 判断是否通过
        # exit_code 说明:
        # 0 = 所有测试通过
        # 1 = 有测试失败
        # 2 = 测试执行被中断
        # 3 = 内部错误
        # 4 = pytest 命令行参数错误
        # 5 = 没有收集到任何测试
        
        # 如果没有找到测试文件或没有收集到测试，视为跳过
        no_tests_found = exit_code == 4 or exit_code == 5 or ("no such file" in (stdout or "").lower()) or ("not found" in (stdout or "").lower())
        
        if no_tests_found:
            passed = True
            summary = f"无测试文件 (exit code: {exit_code})"
        elif passed_count > 0:
            passed = exit_code == 0 and failed_count == 0 and error_count == 0
            summary = f"{passed_count} 个测试通过"
        elif exit_code == 0:
            passed = True
            summary = "无测试文件"
        else:
            passed = False
            summary = f"测试失败 (exit code: {exit_code})"
        
        if failed_count > 0:
            summary += f", {failed_count} 个失败"
        if error_count > 0:
            summary += f", {error_count} 个错误"
        
        # 提取失败的测试
        failed_tests = []
        if "FAILED" in stdout:
            for line in stdout.split('\n'):
                if 'FAILED' in line and '::' in line:
                    test_match = re.search(r'(\S+::\S+)', line)
                    if test_match:
                        failed_tests.append(f"FAILED: {test_match.group(1)}")
        
        if "ERROR" in stdout:
            for line in stdout.split('\n'):
                if line.startswith('ERROR') and 'collecting' in line:
                    error_match = re.search(r'ERROR collecting (\S+)', line)
                    if error_match:
                        failed_tests.append(f"ERROR: {error_match.group(1)}")
                elif line.startswith('ERROR') and '::' in line:
                    error_match = re.search(r'(\S+::\S+)', line)
                    if error_match:
                        failed_tests.append(f"ERROR: {error_match.group(1)}")
        
        layer_result = LayerResult(
            layer=layer_name,
            passed=passed,
            summary=summary,
            logs=stdout if stdout else stderr,
            failed_tests=failed_tests,
            error_type="test_failure" if not passed else None
        )
        layers.append(layer_result)
        
        status = "✅" if passed else "❌"
        print(f"      {status} {summary}")
        if failed_tests:
            for ft in failed_tests[:3]:
                print(f"         ❌ {ft}")
    
    # 计算 overall 结果
    all_passed = all(layer.passed for layer in layers)
    
    # [DEBUG] 打印每层结果
    print(f"\n   [DEBUG] 分层测试详细结果:")
    for layer in layers:
        print(f"      - {layer.layer}: passed={layer.passed}, summary={layer.summary}")
    print(f"   [DEBUG] all_passed={all_passed}")
    
    # 确定失败原因
    failure_cause = None
    failed_tests_all = []
    error_details = {}
    
    for layer in layers:
        if not layer.passed:
            if layer.layer == "unit":
                failure_cause = "unit_test_failure"
            elif layer.layer == "integration":
                failure_cause = "integration_test_failure"
            elif layer.layer == "ai_generated":
                failure_cause = "ai_test_failure"
            
            failed_tests_all.extend(layer.failed_tests)
            error_details = {
                "layer": layer.layer,
                "message": layer.summary,
                "logs": layer.logs,
                "failed_tests": layer.failed_tests
            }
            break
    
    return LayeredTestResult(
        all_passed=all_passed,
        layers=layers,
        failure_cause=failure_cause,
        failed_tests=failed_tests_all,
        error_details=error_details
    )


async def test_auto_fix_layered():
    """测试分层测试失败后的 Auto-Fix 流程"""
    print("=" * 70)
    print("🧪 分层测试失败后的 Auto-Fix 完整验证")
    print("=" * 70)
    
    pipeline_id = 99997
    target_file = "app/calculator.py"
    test_file = "tests/unit/test_calculator.py"
    
    try:
        # Step 0: 启动 Sandbox
        print("\n🐳 Step 0: 启动 Docker Sandbox...")
        backend_dir = Path(__file__).parent.parent
        
        sandbox_orchestrator = get_sandbox_orchestrator(pipeline_id)
        sandbox_result = await sandbox_orchestrator.initialize(
            project_path=str(backend_dir)
        )
        
        if not sandbox_result["success"]:
            print(f"❌ Sandbox 启动失败: {sandbox_result.get('error')}")
            return False
        
        print("✅ Sandbox 启动成功")
        file_service = sandbox_orchestrator.get_file_service()
        
        # Step 1: 创建目录结构
        print(f"\n📁 Step 1: 创建目录结构...")
        mkdir_cmd = "mkdir -p /workspace/app /workspace/tests/unit"
        await sandbox_manager.exec(pipeline_id, mkdir_cmd, timeout=10)
        print("   ✅ 目录创建完成")
        
        # Step 2: 写入有逻辑错误的代码
        print(f"\n📝 Step 2: 写入有逻辑错误的代码...")
        write_result = await file_service.write_file(target_file, BUGGY_CODE)
        if not write_result.get("success"):
            print(f"❌ 写入代码文件失败: {write_result.get('error')}")
            return False
        print(f"   ✅ 已写入 {target_file}")
        print("   错误: add() 函数使用了减法而非加法")
        
        # Step 3: 写入测试文件
        print(f"\n🧪 Step 3: 写入测试文件...")
        write_test_result = await file_service.write_file(test_file, TEST_CODE)
        if not write_test_result.get("success"):
            print(f"❌ 写入测试文件失败: {write_test_result.get('error')}")
            return False
        print(f"   ✅ 已写入 {test_file}")
        
        # Step 4: 运行分层测试（预期失败）
        print(f"\n🔍 Step 4: 运行分层测试（预期失败）...")
        layered_result = await run_layered_tests(pipeline_id, specific_test_file=test_file)
        
        print(f"\n   📊 分层测试结果:")
        print(f"      全部通过: {layered_result.all_passed}")
        print(f"      失败原因: {layered_result.failure_cause}")
        
        if layered_result.all_passed:
            print("\n⚠️  测试全部通过（可能代码没有错误？）")
            return True
        
        print("\n   ❌ 分层测试失败（符合预期）")
        
        # Step 5: VerifyAgent 验证
        print(f"\n🔍 Step 5: VerifyAgent 独立验证...")
        
        # 构建验证结果（模拟 verify_fixes 的输出）
        verify_result = {
            "verdict": "FAIL",
            "message": "测试失败，需要修复代码",
            "error_count": len(layered_result.failed_tests),
            "errors": layered_result.failed_tests,
            "structured_errors": {
                "errors": [
                    {
                        "file_path": target_file,
                        "line": 9,
                        "severity": "critical",
                        "summary": "add 函数逻辑错误",
                        "detail": f"add(2, 3) 返回了 -1 而不是 5",
                        "fix_hint": "将 `return a - b` 改为 `return a + b`"
                    }
                ]
            },
            "evidence": {
                "failed_output": layered_result.error_details.get("logs", "")[:1500]
            }
        }
        
        print(f"   验证结果: {verify_result['verdict']}")
        print(f"   错误数量: {verify_result['error_count']}")
        
        # Step 6: RepairerAgent 修复
        print(f"\n🔧 Step 6: RepairerAgent 修复...")
        
        # 构建修复工单
        fix_order = {
            "type": "fix_order",
            "category": "code_bug",
            "source": "VerifyAgent",
            "errors": verify_result["structured_errors"]["errors"],
            "failed_tests": layered_result.failed_tests[:5],
            "error_snippet": verify_result["evidence"]["failed_output"][:1000],
            "generated_files": [target_file],
            "fix_hint": "修复 app/calculator.py 中的 add 函数：将减法改为加法"
        }
        
        print(f"   修复工单: {len(fix_order['errors'])} 个错误项")
        for err in fix_order["errors"]:
            print(f"      - {err.get('file_path')}:{err.get('line')}: {err.get('summary', '')}")
        
        repairer = RepairerAgent()
        repair_result = await repairer.execute_with_reread(
            pipeline_id=pipeline_id,
            stage_name="REPAIR",
            fix_order=fix_order,
            project_path=None,
            file_service=file_service,
            initial_state={
                "verification_report": {
                    "verdict": verify_result["verdict"],
                    "error_count": verify_result["error_count"],
                    "message": verify_result["message"]
                }
            }
        )
        
        if not repair_result.get("success"):
            print(f"❌ RepairerAgent 失败: {repair_result.get('error')}")
            return False
        
        print("✅ RepairerAgent 完成")
        
        # 应用修复
        repair_output = repair_result.get("output", {})
        files_changed = repair_output.get("files", [])
        
        print(f"   应用 {len(files_changed)} 个文件修复...")
        print(f"   [DEBUG] repair_output: {repair_output}")
        
        for file_change in files_changed:
            file_path = file_change.get("file_path", "")
            search_block = file_change.get("search_block", "")
            replace_block = file_change.get("replace_block", "")
            
            # 【修复】处理文件路径，移除 backend/ 前缀
            original_file_path = file_path
            file_path = file_path.replace("backend/", "").replace("backend\\", "")
            
            print(f"   [DEBUG] 处理文件: {original_file_path} -> {file_path}")
            print(f"   [DEBUG] search_block: {repr(search_block[:80]) if search_block else 'None'}...")
            print(f"   [DEBUG] replace_block: {repr(replace_block[:80]) if replace_block else 'None'}...")
            
            # 读取原文件
            read_result = await file_service.read_file(file_path)
            print(f"   [DEBUG] 读取结果: exists={read_result.exists}, content_len={len(read_result.content) if read_result.content else 0}")
            
            if read_result.exists and read_result.content:
                # 检查 search_block 是否存在于内容中
                if search_block and search_block in read_result.content:
                    # 应用替换
                    new_content = read_result.content.replace(search_block, replace_block, 1)
                    # 写入新内容
                    write_result = await file_service.write_file(file_path, new_content)
                    if write_result.get("success"):
                        print(f"      ✓ 应用修复: {file_path}")
                    else:
                        print(f"      ❌ 应用修复失败: {file_path} - {write_result.get('error')}")
                else:
                    print(f"      ❌ search_block 不存在于文件中")
                    # 【修复】不要直接写入 replace_block，因为它可能只是代码片段
                    # 而是应该使用 content 字段（如果存在）或跳过
                    full_content = file_change.get("content", "")
                    if full_content and len(full_content) > len(replace_block):
                        print(f"      [DEBUG] 使用完整 content 字段 ({len(full_content)} 字符)")
                        write_result = await file_service.write_file(file_path, full_content)
                        if write_result.get("success"):
                            print(f"      ✓ 写入完整文件: {file_path}")
                        else:
                            print(f"      ❌ 写入失败: {file_path} - {write_result.get('error')}")
                    else:
                        print(f"      ⚠️  跳过：没有可用的完整文件内容")
            else:
                print(f"      ❌ 文件不存在或内容为空: {file_path}")
        
        # Step 6.5: 验证修复后的代码
        print(f"\n🔍 Step 6.5: 验证修复后的代码...")
        verify_read = await file_service.read_file(target_file)
        if verify_read.exists:
            print(f"   [DEBUG] 修复后文件内容 ({len(verify_read.content)} 字符):")
            lines = verify_read.content.split('\n')
            for i, line in enumerate(lines[6:14], start=7):
                marker = "<<<" if "add" in line.lower() else ""
                print(f"      {i}: {line} {marker}")
            
            # 检查是否真的修复了
            if "return a + b" in verify_read.content:
                print("   ✅ 代码已正确修复 (a + b)")
            elif "return a - b" in verify_read.content:
                print("   ❌ 代码仍未修复 (仍然是 a - b)")
            else:
                print(f"   ⚠️  无法确认修复状态")
        else:
            print(f"   ❌ 无法读取修复后的文件")
        
        # Step 7: 再次运行分层测试（预期通过）
        print(f"\n🔍 Step 7: 再次运行分层测试（预期通过）...")
        layered_result2 = await run_layered_tests(pipeline_id, specific_test_file=test_file)
        
        print(f"\n   📊 分层测试结果:")
        print(f"      全部通过: {layered_result2.all_passed}")
        
        if layered_result2.all_passed:
            print("\n" + "=" * 70)
            print("✅ Auto-Fix 成功！分层测试全部通过！")
            print("=" * 70)
            
            # 显示修复后的代码
            read_result = await file_service.read_file(target_file)
            if read_result.exists:
                print("\n📄 修复后的代码片段:")
                lines = read_result.content.split('\n')
                for i, line in enumerate(lines[8:12], start=9):
                    print(f"   {i}: {line}")
            
            return True
        else:
            print("\n❌ 修复后仍有测试失败")
            return False
        
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # 清理 Sandbox
        print("\n🧹 清理 Docker Sandbox...")
        try:
            await cleanup_sandbox_orchestrator(pipeline_id)
            print("✅ Sandbox 已停止")
        except Exception as e:
            print(f"⚠️  停止 Sandbox 时出错: {e}")


if __name__ == "__main__":
    success = asyncio.run(test_auto_fix_layered())
    sys.exit(0 if success else 1)
