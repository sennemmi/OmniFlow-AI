#!/usr/bin/env python3
"""
真实 CoderAgent 测试脚本
调用一次 CoderAgent 来修改简单的测试脚本
"""

import asyncio
import sys
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.coder import coder_agent
from app.agents.schemas import FileChange


async def test_coder_agent():
    """测试 CoderAgent"""

    # 读取测试脚本内容
    test_script_path = Path(__file__).parent / "test_simple_script.py"
    original_content = test_script_path.read_text(encoding='utf-8')

    print("=" * 60)
    print("原始文件内容:")
    print("=" * 60)
    print(original_content)
    print(f"\n总行数: {len(original_content.splitlines())}")

    # 准备输入数据
    design_output = {
        "api_endpoints": [],
        "function_changes": [
            {
                "file": "backend/scripts/test_simple_script.py",
                "function": "greet",
                "change_type": "modify",
                "description": "添加时间戳到问候语"
            },
            {
                "file": "backend/scripts/test_simple_script.py",
                "function": "calculate_sum",
                "change_type": "modify",
                "description": "添加乘法计算功能"
            }
        ],
        "affected_files": ["backend/scripts/test_simple_script.py"],
        "logic_flow": "1. 修改 greet 函数，添加当前时间戳\n2. 修改 calculate_sum 函数，同时返回乘积"
    }

    # 【改造】CoderAgent 现在使用工具按需读取文件，不再传入 target_files
    # 构建输入（移除 target_files）
    agent_input = {
        "design_output": design_output,
        "requirement": "修改 test_simple_script.py：\n1. 在 greet 函数中添加当前时间戳\n2. 在 calculate_sum 函数中同时计算并返回乘积"
    }

    print("\n" + "=" * 60)
    print("调用 CoderAgent...")
    print("=" * 60)

    try:
        # 调用 CoderAgent（使用正确的参数格式）
        result = await coder_agent.execute(
            pipeline_id=99999,  # 测试用的 pipeline_id
            stage_name="CODING",  # 阶段名称
            initial_state=agent_input  # 初始状态（包含业务输入）
        )

        print("\n" + "=" * 60)
        print("CoderAgent 执行结果:")
        print("=" * 60)
        print(f"成功: {result.get('success')}")
        print(f"错误: {result.get('error')}")

        output = result.get('output', {})
        if output:
            print(f"\n生成的文件数: {len(output.get('files', []))}")

            for f in output.get('files', []):
                print(f"\n文件: {f.file_path}")
                print(f"  change_type: {f.change_type}")
                print(f"  search_block: {f.search_block is not None}")
                if f.search_block:
                    print(f"  search_block 预览: {f.search_block[:80]}...")
                print(f"  replace_block: {f.replace_block is not None}")
                if f.replace_block:
                    print(f"  replace_block 预览: {f.replace_block[:80]}...")
                print(f"  fallback_start_line: {f.fallback_start_line}")
                print(f"  fallback_end_line: {f.fallback_end_line}")
                print(f"  content: {f.content is not None}")

        # 尝试应用修改
        print("\n" + "=" * 60)
        print("尝试应用修改...")
        print("=" * 60)

        from app.agents.multi_agent_coordinator import multi_agent_coordinator

        files = output.get('files', [])
        if not files:
            print("没有生成的文件")
            return

        current_content = original_content

        for i, f in enumerate(files):
            if f.search_block:
                new_content = multi_agent_coordinator._apply_search_replace(
                    current_content,
                    f.search_block,
                    f.replace_block or "",
                    f.fallback_start_line,
                    f.fallback_end_line
                )

                if new_content:
                    current_content = new_content
                    print(f"[PASS] 修改 {i+1}: 搜索替换成功")
                else:
                    print(f"[FAIL] 修改 {i+1}: 搜索替换失败，尝试 fallback 行号...")
                    # 尝试 fallback
                    if f.fallback_start_line and f.fallback_end_line:
                        lines = current_content.splitlines()
                        if 1 <= f.fallback_start_line <= f.fallback_end_line <= len(lines):
                            new_lines = (
                                lines[:f.fallback_start_line - 1] +
                                (f.replace_block or "").splitlines() +
                                lines[f.fallback_end_line:]
                            )
                            current_content = "\n".join(new_lines)
                            print(f"[PASS] 修改 {i+1}: fallback 行号替换成功")
                        else:
                            print(f"[FAIL] 修改 {i+1}: fallback 行号超出范围")
            else:
                print(f"[SKIP] 修改 {i+1}: 没有 search_block")

        # 显示最终结果
        print("\n" + "=" * 60)
        print("修改后的文件内容:")
        print("=" * 60)
        print(current_content)

        # 保存结果
        output_path = test_script_path.parent / "test_simple_script_modified.py"
        output_path.write_text(current_content, encoding='utf-8')
        print(f"\n结果已保存到: {output_path}")

    except Exception as e:
        print(f"\n[ERROR] 执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_coder_agent())
