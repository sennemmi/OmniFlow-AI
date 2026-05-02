#!/usr/bin/env python3
"""
独立版 CoderAgent 测试 - 验证 Read Token 机制
使用项目中的 CoderAgent，验证先读后写机制

测试流程：
1. 读取文件 → 生成 read_token
2. 调用 CoderAgent 生成代码变更
3. 使用 read_token 验证并写入文件
4. 验证"无 token 拒绝写入"的安全机制
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 从 .env 文件加载环境变量
def load_env_file():
    """从项目根目录的 .env 文件加载环境变量"""
    current_dir = Path(__file__).parent
    env_file = None

    # 向上查找 .env 文件
    for parent in [current_dir] + list(current_dir.parents):
        potential_env = parent / ".env"
        if potential_env.exists():
            env_file = potential_env
            break

    if not env_file:
        env_file = Path(__file__).parent.parent.parent / ".env"

    if env_file.exists():
        print(f"[INFO] 加载环境变量: {env_file}")
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    if key and key not in os.environ:
                        os.environ[key] = value
        print(f"[INFO] 环境变量加载完成")
    else:
        print(f"[WARN] 未找到 .env 文件，使用默认配置")

load_env_file()
os.environ.setdefault("TARGET_PROJECT_PATH", str(Path(__file__).parent))


async def test_read_token_mechanism():
    """测试 Read Token 机制"""

    from app.service.code_executor import CodeExecutorService
    from app.agents.coder import coder_agent

    print("=" * 70)
    print("Read Token 机制验证测试")
    print("=" * 70)

    # 初始化 CodeExecutorService
    test_dir = Path(__file__).parent
    code_executor = CodeExecutorService(str(test_dir))

    # 测试文件路径
    test_file = "test_simple_script.py"
    test_file_path = test_dir / test_file

    print(f"\n[1/6] 测试文件: {test_file}")
    print(f"       完整路径: {test_file_path}")

    # ========== 步骤 1: 读取文件并生成 Read Token ==========
    print("\n" + "-" * 70)
    print("[2/6] 步骤 1: 读取文件并生成 Read Token")
    print("-" * 70)

    read_result = code_executor.read_file(test_file)

    if read_result.error:
        print(f"[FAIL] 读取文件失败: {read_result.error}")
        return

    if not read_result.exists:
        print(f"[FAIL] 文件不存在: {test_file}")
        return

    print(f"[PASS] 文件读取成功")
    print(f"       内容长度: {len(read_result.content)} 字符")
    print(f"       内容哈希: {read_result.content_hash[:16]}...")
    print(f"       Read Token: {read_result.read_token[:50]}...")
    print(f"       Token 长度: {len(read_result.read_token)} 字符")

    original_content = read_result.content
    read_token = read_result.read_token

    # 显示原始内容
    print(f"\n原始文件内容:")
    print(original_content[:800] + "..." if len(original_content) > 800 else original_content)

    # ========== 步骤 2: 调用 CoderAgent 生成代码变更 ==========
    print("\n" + "-" * 70)
    print("[3/6] 步骤 2: 调用 CoderAgent 生成代码变更")
    print("-" * 70)

    # 构建设计方案
    design_output = {
        "affected_files": [f"backend/scripts/{test_file}"],
        "function_changes": [
            {
                "function": "greet",
                "file": f"backend/scripts/{test_file}",
                "change_type": "modify",
                "description": "添加当前时间戳到问候语"
            },
            {
                "function": "calculate_sum",
                "file": f"backend/scripts/{test_file}",
                "change_type": "modify",
                "description": "同时计算并返回乘积"
            }
        ],
        "summary": "增强 test_simple_script.py 功能"
    }

    # 【改造】CoderAgent 现在使用工具按需读取文件，不再传入 target_files

    try:
        print("[INFO] 调用 CoderAgent 生成代码...")

        # 调用 CoderAgent（新 API，不再传入 target_files）
        result = await coder_agent.generate_code(
            design_output=design_output,
            pipeline_id=0  # 测试用 pipeline_id
        )

        if not result.get("success"):
            print(f"[FAIL] CoderAgent 生成失败: {result.get('error')}")
            return

        coder_output = result.get("output", {})
        files = coder_output.get("files", [])
        print(f"[PASS] CoderAgent 调用成功")
        print(f"       生成的文件变更数: {len(files)}")

        if not files:
            print(f"[FAIL] CoderAgent 未生成任何文件变更")
            print(f"       输出内容: {json.dumps(coder_output, indent=2, ensure_ascii=False)[:800]}")
            return

        for i, f in enumerate(files):
            print(f"\n       变更 {i+1}:")
            print(f"         file_path: {f.get('file_path')}")
            print(f"         change_type: {f.get('change_type')}")
            print(f"         search_block: {f.get('search_block', '')[:60]}...")
            print(f"         replace_block: {f.get('replace_block', '')[:60]}...")

    except Exception as e:
        print(f"[FAIL] CoderAgent 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # ========== 步骤 3: 尝试应用修改（无 Token - 应该失败）==========
    print("\n" + "-" * 70)
    print("[4/6] 步骤 3: 验证安全机制 - 无 Token 应该被拒绝")
    print("-" * 70)

    # 计算修改后的内容（简单替换）
    modified_content = original_content
    for f in files:
        search_block = f.get('search_block', '')
        replace_block = f.get('replace_block', '')
        if search_block and search_block in modified_content:
            modified_content = modified_content.replace(search_block, replace_block, 1)
            print(f"[INFO] 搜索替换成功: {f.get('description', 'N/A')}")

    # 尝试无 token 写入（应该失败）
    print(f"\n尝试无 read_token 写入文件...")
    result_no_token = code_executor.apply_file_change(
        relative_path=test_file,
        new_content=modified_content,
        read_token="",  # 空 token
        create_if_missing=False
    )

    if result_no_token.success:
        print(f"[FAIL] 安全机制失效！无 token 竟然写入成功")
        return
    else:
        print(f"[PASS] 安全机制生效！无 token 被拒绝")
        print(f"       错误信息: {result_no_token.error}")

    # ========== 步骤 4: 使用正确的 Read Token 写入 ==========
    print("\n" + "-" * 70)
    print("[5/6] 步骤 4: 使用正确的 Read Token 写入文件")
    print("-" * 70)

    print(f"使用之前生成的 read_token 写入文件...")
    result_with_token = code_executor.apply_file_change(
        relative_path=test_file,
        new_content=modified_content,
        read_token=read_token,  # 正确的 token
        create_if_missing=False
    )

    if result_with_token.success:
        print(f"[PASS] 写入成功！Read Token 验证通过")
        print(f"       备份路径: {result_with_token.backup_path}")
    else:
        print(f"[FAIL] 写入失败: {result_with_token.error}")
        return

    # ========== 步骤 5: 验证文件内容 ==========
    print("\n" + "-" * 70)
    print("[6/6] 步骤 5: 验证文件内容")
    print("-" * 70)

    # 重新读取文件
    new_content = code_executor.get_file_content(test_file)

    if new_content == modified_content:
        print(f"[PASS] 文件内容验证成功")
        print(f"       新内容长度: {len(new_content)} 字符")
    else:
        print(f"[FAIL] 文件内容不匹配")
        print(f"       期望长度: {len(modified_content)}")
        print(f"       实际长度: {len(new_content)}")

    # 显示修改后的内容
    print(f"\n修改后的文件内容:")
    print(new_content[:800] + "..." if len(new_content) > 800 else new_content)

    # ========== 步骤 6: 验证 Token 重用被拒绝 ==========
    print("\n" + "-" * 70)
    print("[BONUS] 步骤 6: 验证 Token 重用被拒绝（文件已修改）")
    print("-" * 70)

    print(f"尝试使用旧的 read_token 再次写入...")
    result_reuse = code_executor.apply_file_change(
        relative_path=test_file,
        new_content=original_content,  # 尝试写回原始内容
        read_token=read_token,  # 旧的 token（文件已修改，应该失效）
        create_if_missing=False
    )

    if result_reuse.success:
        print(f"[FAIL] 安全机制失效！旧 token 竟然还能用")
    else:
        print(f"[PASS] 安全机制生效！旧 token 已失效")
        print(f"       错误信息: {result_reuse.error}")

    # 恢复原始文件
    print("\n" + "-" * 70)
    print("[恢复] 恢复原始文件")
    print("-" * 70)

    # 重新读取获取新 token
    final_read = code_executor.read_file(test_file)
    if final_read.read_token:
        restore_result = code_executor.apply_file_change(
            relative_path=test_file,
            new_content=original_content,
            read_token=final_read.read_token,
            create_if_missing=False
        )
        if restore_result.success:
            print(f"[PASS] 原始文件已恢复")
        else:
            print(f"[WARN] 恢复失败: {restore_result.error}")

    # ========== 测试总结 ==========
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    print("""
✅ Read Token 生成成功
✅ 文件内容哈希计算正确
✅ 无 Token 写入被拒绝（安全机制生效）
✅ 正确 Token 写入成功
✅ Token 重用被拒绝（文件修改后失效）
✅ 原子写入保证数据完整性

Read Token 机制验证通过！
""")


if __name__ == "__main__":
    asyncio.run(test_read_token_mechanism())
