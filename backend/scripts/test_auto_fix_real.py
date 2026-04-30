"""
Auto-Fix 真实流程测试脚本

直接预设一个有语法错误的代码文件，然后测试 RepairerAgent 的修复能力。
流程：
1. 直接在 Sandbox 中写入一个有语法错误的文件
2. 使用 VerifyAgent 验证代码（分层测试）
3. 如果测试失败，使用 RepairerAgent 修复
4. 再次验证
"""

import asyncio
import sys
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.service.sandbox_orchestrator import get_sandbox_orchestrator, cleanup_sandbox_orchestrator
from app.service.sandbox_manager import sandbox_manager
from app.agents.repairer import RepairerAgent


# 预设的有语法错误的代码
BROKEN_CODE = '''
"""
Health check endpoints
"""

from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok"}

# 这是一个有语法错误的函数（缺少冒号）
def broken_function()
    """这个函数有语法错误"""
    return {"broken": True}
'''


async def test_auto_fix_real():
    """测试真实的 Auto-Fix 流程"""
    print("=" * 70)
    print("🧪 Auto-Fix 真实流程测试")
    print("=" * 70)
    
    pipeline_id = 99996
    target_file = "app/api/v1/health.py"
    
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
        
        # Step 1: 直接写入有语法错误的代码（不调用 CoderAgent）
        print(f"\n📝 Step 1: 直接写入有语法错误的代码到 {target_file}...")
        
        write_result = await file_service.write_file(target_file, BROKEN_CODE)
        if not write_result.get("success"):
            print(f"❌ 写入文件失败: {write_result.get('error')}")
            return False
        
        print("✅ 已写入有语法错误的代码")
        print("   错误: broken_function() 缺少冒号")
        
        # Step 2: 验证代码（语法检查）
        print("\n🔍 Step 2: 验证代码...")
        
        # 在 Sandbox 中运行 Python 语法检查
        syntax_cmd = f"cd /workspace && python -m py_compile {target_file} 2>&1"
        exec_result = await sandbox_manager.exec(pipeline_id, syntax_cmd, timeout=30)
        
        syntax_valid = exec_result.exit_code == 0
        syntax_output = exec_result.stdout
        
        if syntax_valid:
            print("✅ 代码语法正确（可能已经被修复了？）")
            return True
        else:
            print("❌ 检测到语法错误（符合预期）")
            print(f"   错误信息: {syntax_output[:200]}...")
        
        # Step 3: 启动 Auto-Fix
        print("\n🔧 Step 3: 启动 Auto-Fix...")
        
        # 构建修复工单
        fix_order = {
            "type": "fix_order",
            "category": "syntax_error",
            "source": "VerifyAgent",
            "errors": [
                {
                    "file_path": target_file,
                    "summary": "语法错误：函数定义缺少冒号",
                    "error_type": "syntax"
                }
            ],
            "failed_tests": [],
            "error_snippet": syntax_output[:500],
            "generated_files": [target_file],
            "fix_hint": "修复 broken_function 函数定义的语法错误，在参数列表后添加冒号"
        }
        
        # 调用 RepairerAgent
        repairer = RepairerAgent()
        repair_result = await repairer.execute_with_reread(
            pipeline_id=pipeline_id,
            stage_name="REPAIR",
            fix_order=fix_order,
            project_path=None,
            file_service=file_service,
            initial_state={
                "verification_report": {
                    "verdict": "FAIL",
                    "error_count": 1,
                    "message": "语法错误：函数定义缺少冒号"
                }
            }
        )
        
        if not repair_result.get("success"):
            print(f"❌ RepairerAgent 失败: {repair_result.get('error')}")
            return False
        
        print("✅ RepairerAgent 完成")
        
        # Step 4: 再次验证修复结果
        print("\n🔍 Step 4: 再次验证修复结果...")
        
        syntax_cmd2 = f"cd /workspace && python -m py_compile {target_file} 2>&1"
        exec_result2 = await sandbox_manager.exec(pipeline_id, syntax_cmd2, timeout=30)
        
        syntax_valid2 = exec_result2.exit_code == 0
        
        if syntax_valid2:
            print("✅ 语法检查通过！代码已修复")
            
            # 读取修复后的代码
            read_result = await file_service.read_file(target_file)
            if read_result.exists:
                print("\n📄 修复后的代码片段:")
                lines = read_result.content.split('\n')
                for i, line in enumerate(lines[-10:], start=len(lines)-9):
                    print(f"   {i}: {line}")
        else:
            print("❌ 修复后仍有语法错误")
            print(f"   错误: {exec_result2.stdout[:200]}...")
            return False
        
        # Step 5: 运行测试验证
        print("\n🧪 Step 5: 运行测试验证...")
        
        test_result = await run_tests_in_sandbox(pipeline_id)
        
        print(f"   测试结果: {'通过' if test_result.get('success') else '失败'}")
        print(f"   通过: {test_result.get('passed', 0)}")
        print(f"   失败: {test_result.get('failed', 0)}")
        
        if test_result.get("success"):
            print("\n" + "=" * 70)
            print("✅ Auto-Fix 真实流程测试完成！")
            print("=" * 70)
            return True
        else:
            print("\n⚠️  测试未通过，但语法错误已修复")
            return True
        
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


async def run_tests_in_sandbox(pipeline_id: int) -> dict:
    """
    在 Sandbox 中运行测试（分层测试）
    """
    print("   🐳 在 Sandbox 中运行测试...")
    
    # 运行 pytest
    pytest_cmd = "cd /workspace && PYTHONPATH=/workspace python -m pytest tests/ -v --tb=short -p no:cacheprovider 2>&1"
    exec_result = await sandbox_manager.exec(pipeline_id, pytest_cmd, timeout=120)
    
    output = exec_result.stdout
    exit_code = exec_result.exit_code
    
    # 解析结果
    passed = output.count(" passed") if " passed" in output else 0
    failed = output.count(" failed") if " failed" in output else 0
    
    # 提取失败信息
    failures = []
    if "FAILED" in output:
        lines = output.split('\n')
        for line in lines:
            if "FAILED" in line:
                failures.append({"test": line.strip(), "error": "测试失败"})
    
    return {
        "success": exit_code == 0 and failed == 0,
        "returncode": exit_code,
        "passed": passed,
        "failed": failed,
        "failures": failures,
        "output": output
    }


if __name__ == "__main__":
    success = asyncio.run(test_auto_fix_real())
    sys.exit(0 if success else 1)
