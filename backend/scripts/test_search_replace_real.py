#!/usr/bin/env python3
"""
真实场景测试：模拟 E2E 中的搜索替换
"""

import sys
from pathlib import Path

# 模拟 E2E 中的处理逻辑
def apply_search_replace(
    original: str,
    search_block: str,
    replace_block: str,
    fallback_start=None,
    fallback_end=None
):
    """简化版搜索替换"""
    if not search_block:
        return None

    # 精确匹配
    if search_block in original:
        return original.replace(search_block, replace_block, 1)

    # 换行符归一化
    orig_norm = original.replace('\r\n', '\n')
    search_norm = search_block.replace('\r\n', '\n')
    repl_norm = replace_block.replace('\r\n', '\n')

    if search_norm in orig_norm:
        return orig_norm.replace(search_norm, repl_norm, 1)

    # fallback 行号
    if fallback_start and fallback_end:
        lines = orig_norm.splitlines()
        if 1 <= fallback_start <= fallback_end <= len(lines):
            new_lines = lines[:fallback_start - 1] + repl_norm.splitlines() + lines[fallback_end:]
            return '\n'.join(new_lines)

    return None


def test_real_scenario():
    """测试真实场景"""

    # 读取真实的 health.py 文件
    health_py_path = Path(r"d:\feishuProj\backend\app\api\v1\health.py")

    if not health_py_path.exists():
        print(f"[ERROR] 文件不存在: {health_py_path}")
        return

    original = health_py_path.read_text(encoding='utf-8')
    print("=" * 60)
    print("真实 health.py 文件内容:")
    print("=" * 60)
    print(original)
    print(f"\n总行数: {len(original.splitlines())}")

    # 模拟 CoderAgent 可能生成的搜索块（基于常见的修改场景）
    test_cases = [
        {
            "name": "修改 health_check 函数",
            "search": '''@router.get("/")
async def health_check():
    return {"status": "ok"}''',
            "replace": '''@router.get("/")
async def health_check():
    db_status = await check_db()
    return {"status": "ok", "db": db_status}''',
            "fallback_start": 8,
            "fallback_end": 10
        },
        {
            "name": "修改导入语句",
            "search": '''from fastapi import APIRouter''',
            "replace": '''from fastapi import APIRouter, Depends''',
            "fallback_start": 1,
            "fallback_end": 1
        }
    ]

    print("\n" + "=" * 60)
    print("测试搜索替换场景:")
    print("=" * 60)

    for i, case in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {case['name']}")
        print(f"  搜索块: {case['search'][:50]}...")
        print(f"  fallback: {case['fallback_start']}-{case['fallback_end']}")

        # 检查搜索块是否在原始内容中
        search_in_original = case['search'] in original
        print(f"  搜索块是否在原始内容中: {search_in_original}")

        if not search_in_original:
            # 显示差异
            print("  [DEBUG] 搜索块与实际内容的差异:")
            orig_lines = original.splitlines()
            search_lines = case['search'].splitlines()
            for j, (o, s) in enumerate(zip(orig_lines[:len(search_lines)], search_lines)):
                if o != s:
                    print(f"    行 {j+1}: 原始='{o}' vs 搜索='{s}'")

        result = apply_search_replace(
            original,
            case['search'],
            case['replace'],
            case['fallback_start'],
            case['fallback_end']
        )

        if result:
            print(f"  [PASS] 替换成功")
        else:
            print(f"  [FAIL] 替换失败")


if __name__ == "__main__":
    test_real_scenario()
