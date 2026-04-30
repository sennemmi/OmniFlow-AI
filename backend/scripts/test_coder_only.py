"""
轻量级测试脚本 - 只测试 CoderAgent 和 Auto-Fix 功能

这个脚本用于快速验证：
1. CoderAgent 能否正确生成代码
2. 代码能否正确写入 Sandbox
3. Auto-Fix 流程是否正常工作

不运行完整测试，只验证核心流程。
"""

import asyncio
import sys
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.coder import coder_agent
from app.service.sandbox_orchestrator import get_sandbox_orchestrator, cleanup_sandbox_orchestrator
from app.service.sandbox_file_service import SandboxFileService


async def test_coder_only():
    """轻量级测试：只测试 CoderAgent"""
    print("=" * 70)
    print("🧪 轻量级测试：CoderAgent + Auto-Fix 检测")
    print("=" * 70)
    
    pipeline_id = 99998  # 使用不同的 pipeline_id 避免冲突
    
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
        
        # 【Debug】检查 Sandbox 中的文件
        print("\n🔍 [Debug] 检查 Sandbox 中的 health.py 文件...")
        debug_result = await file_service.read_file("app/api/v1/health.py")
        if debug_result.exists:
            print(f"   ✅ 文件存在，长度: {len(debug_result.content)} 字符")
            print(f"   📄 文件前200字符:")
            print(f"      {debug_result.content[:200]}...")
        else:
            print(f"   ❌ 文件不存在: {debug_result.error}")
            # 列出目录内容
            ls_result = await file_service.list_directory("app/api/v1")
            print(f"   📁 目录内容: {ls_result}")
        
        # Step 1: 直接准备文件内容和需求（跳过 ArchitectAgent）
        print("\n📋 Step 1: 准备文件内容和需求...")
        
        # 读取原始文件内容
        original_content = debug_result.content if debug_result.exists else ""
        
        # 构建 injected_files
        injected_files = {
            "app/api/v1/health.py": original_content
        }
        
        # 构建 design_output
        # 【关键】明确指定 search_block 为文件末尾，让 CoderAgent 在文件末尾添加
        design_output = {
            "feature_description": "在 health.py 末尾添加 get_system_status 函数",
            "affected_files": ["app/api/v1/health.py"],
            "technical_design": f"""
在 app/api/v1/health.py 文件末尾添加一个新函数。

当前文件内容（最后100字符）：
```python
...{original_content[-100:]}
```

要添加的函数：
```python

def get_system_status():
    '''返回系统状态'''
    return {{"status": "ok", "timestamp": "2024-01-01"}}
```

要求：
1. search_block 必须是文件的最后几行（包括换行符）
2. replace_block 是原文件末尾内容 + 新函数
3. 保持原有代码不变，只在末尾添加
4. 使用正确的缩进（4个空格）
"""
        }
        
        print(f"   📁 文件: app/api/v1/health.py ({len(original_content)} 字符)")
        print(f"   📝 需求: 添加 get_system_status 函数")
        
        # Step 2: CoderAgent 生成代码
        print("\n📝 Step 2: CoderAgent 生成代码...")
        
        coder_result = await coder_agent.generate_code(
            design_output=design_output,
            pipeline_id=pipeline_id,
            injected_files=injected_files
        )
        
        if not coder_result['success']:
            print(f"❌ CoderAgent 失败: {coder_result.get('error')}")
            return False
        
        print("✅ CoderAgent 完成")
        
        code_output = coder_result.get('output', {})
        if hasattr(code_output, 'model_dump'):
            code_output = code_output.model_dump()
        
        files = code_output.get('files', [])
        print(f"   生成 {len(files)} 个文件变更:")
        
        for f in files:
            print(f"     - {f.get('file_path')} [{f.get('change_type', 'modify')}]")
            # 【Debug】显示 search_block 和 replace_block
            search_block = f.get('search_block', '')
            replace_block = f.get('replace_block', '')
            if search_block:
                print(f"       📄 search_block ({len(search_block)} 字符):")
                print(f"          {search_block[:100]}{'...' if len(search_block) > 100 else ''}")
            if replace_block:
                print(f"       📄 replace_block ({len(replace_block)} 字符):")
                print(f"          {replace_block[:100]}{'...' if len(replace_block) > 100 else ''}")
        
        # Step 3: 写入 Sandbox
        print("\n🐳 Step 3: 将代码写入 Docker Sandbox...")
        
        for file_change in files:
            file_path = file_change.get("file_path", "")
            change_type = file_change.get("change_type", "modify")
            
            print(f"\n   处理: {file_path} [{change_type}]")
            
            if change_type == "modify":
                search_block = file_change.get("search_block", "")
                replace_block = file_change.get("replace_block", "")
                
                print(f"   📄 search_block 长度: {len(search_block)}")
                print(f"   📄 replace_block 长度: {len(replace_block)}")
                
                if search_block:
                    # 读取原文件
                    print(f"   🔍 读取原文件...")
                    read_result = await file_service.read_file(file_path)
                    
                    if read_result.exists and read_result.content:
                        print(f"   ✅ 读取成功 ({len(read_result.content)} 字符)")
                        
                        # 【Debug】检查 search_block 是否匹配
                        if search_block in read_result.content:
                            print(f"   ✅ search_block 匹配成功")
                        else:
                            print(f"   ❌ search_block 不匹配!")
                            print(f"   📄 文件前200字符:")
                            print(f"      {read_result.content[:200]}...")
                            continue
                        
                        # 应用替换
                        new_content = read_result.content.replace(search_block, replace_block, 1)
                        print(f"   📝 新内容长度: {len(new_content)} 字符")
                        
                        # 写入新内容
                        write_result = await file_service.write_file(file_path, new_content)
                        if write_result.get("success"):
                            print(f"   ✅ 写入成功: {file_path}")
                        else:
                            print(f"   ❌ 写入失败: {file_path} - {write_result.get('error')}")
                    else:
                        print(f"   ❌ 无法读取: {file_path} - {read_result.error}")
                else:
                    print(f"   ⚠️  没有 search_block，跳过")
            elif change_type == "add":
                content = file_change.get("content", "")
                print(f"   📄 新文件内容长度: {len(content)}")
                write_result = await file_service.write_file(file_path, content)
                if write_result.get("success"):
                    print(f"   ✅ 写入成功: {file_path}")
                else:
                    print(f"   ❌ 写入失败: {file_path} - {write_result.get('error')}")
        
        print("\n✅ 代码写入完成")
        
        # Step 4: 验证写入结果
        print("\n🔍 Step 4: 验证写入结果...")
        
        # 读取写入后的文件
        verify_result = await file_service.read_file("app/api/v1/health.py")
        if verify_result.exists:
            content = verify_result.content
            print(f"   📄 文件长度: {len(content)} 字符")
            print(f"   📄 文件后300字符:")
            print(f"      {content[-300:]}")
            
            if "get_system_status" in content:
                print("\n✅ 函数已成功添加到 health.py")
                # 显示添加的代码
                lines = content.split('\n')
                for i, line in enumerate(lines[-10:], len(lines) - 9):
                    print(f"      {i}: {line}")
            else:
                print("\n❌ 函数未找到")
                return False
        else:
            print(f"\n❌ 无法读取文件: {verify_result.error}")
            return False
        
        print("\n" + "=" * 70)
        print("✅ 轻量级测试通过！")
        print("=" * 70)
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


if __name__ == "__main__":
    success = asyncio.run(test_coder_only())
    sys.exit(0 if success else 1)
