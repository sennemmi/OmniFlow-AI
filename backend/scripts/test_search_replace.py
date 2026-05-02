#!/usr/bin/env python3
"""
搜索替换功能测试脚本
用于诊断 _apply_search_replace 的问题
"""

import difflib
import re
from typing import Optional, List


def apply_search_replace(
    original: str,
    search_block: str,
    replace_block: str,
    fallback_start: Optional[int] = None,
    fallback_end: Optional[int] = None
) -> Optional[str]:
    """
    搜索替换引擎，支持三级匹配和行号回退
    """
    if not search_block:
        return None

    # 第1级：精确匹配
    if search_block in original:
        return original.replace(search_block, replace_block, 1)

    # 第2级：换行符归一化匹配
    orig_norm = original.replace('\r\n', '\n')
    search_norm = search_block.replace('\r\n', '\n')
    repl_norm = replace_block.replace('\r\n', '\n')
    if search_norm in orig_norm:
        return orig_norm.replace(search_norm, repl_norm, 1)

    # 第3级：行级别宽松匹配（忽略首尾空格）
    def clean_lines(text: str) -> List[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    orig_lines_clean = clean_lines(orig_norm)
    search_lines_clean = clean_lines(search_norm)
    repl_lines = repl_norm.splitlines()

    search_len = len(search_lines_clean)
    if search_len > 0 and len(orig_lines_clean) >= search_len:
        for i in range(len(orig_lines_clean) - search_len + 1):
            window = orig_lines_clean[i:i + search_len]
            if window == search_lines_clean:
                # 找到匹配，计算在原文件中的实际位置
                orig_lines = orig_norm.splitlines()
                match_start = 0
                matched_count = 0

                for j, line in enumerate(orig_lines):
                    if line.strip() and matched_count < i:
                        matched_count += 1
                        if matched_count == i:
                            match_start = j
                            break

                # 计算匹配结束位置
                match_end = match_start
                matched_count = 0
                for j in range(match_start, len(orig_lines)):
                    if orig_lines[j].strip():
                        matched_count += 1
                        if matched_count == search_len:
                            match_end = j
                            break

                # 执行替换
                new_lines = orig_lines[:match_start] + repl_lines + orig_lines[match_end + 1:]
                return '\n'.join(new_lines)

    # 第4级：行号回退
    if fallback_start and fallback_end:
        lines = orig_norm.splitlines()
        if 1 <= fallback_start <= fallback_end <= len(lines):
            new_lines = lines[:fallback_start - 1] + repl_norm.splitlines() + lines[fallback_end:]
            return '\n'.join(new_lines)

    return None  # 完全失败


def test_search_replace():
    """测试搜索替换功能"""

    # 模拟 health.py 的原始内容
    original_content = '''from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

router = APIRouter()

class HealthStatus(BaseModel):
    """健康状态响应模型"""
    status: str
    message: str

@router.get("/", response_model=ResponseModel)
async def health_check(request: Request):
    """健康检查端点"""
    return {"status": "ok", "message": "healthy"}
'''

    # 测试用例 1: 精确匹配
    print("=" * 60)
    print("测试用例 1: 精确匹配")
    print("=" * 60)

    search_block_1 = '''@router.get("/", response_model=ResponseModel)
async def health_check(request: Request):
    """健康检查端点"""
    return {"status": "ok", "message": "healthy"}'''

    replace_block_1 = '''@router.get("/", response_model=ResponseModel)
async def health_check(request: Request):
    """健康检查端点"""
    db_status = await check_db()
    return {"status": "ok", "message": "healthy", "db_status": db_status}'''

    print(f"搜索块长度: {len(search_block_1)}")
    print(f"搜索块预览:\n{search_block_1[:100]}...")
    print(f"\n原始内容中是否包含搜索块: {search_block_1 in original_content}")

    result = apply_search_replace(
        original_content,
        search_block_1,
        replace_block_1,
        fallback_start=9,
        fallback_end=12
    )

    if result:
        print("[PASS] 测试用例 1 通过: 精确匹配成功")
        print(f"结果预览:\n{result[:200]}...")
    else:
        print("[FAIL] 测试用例 1 失败: 精确匹配失败")

    # 测试用例 2: 带 fallback 行号
    print("\n" + "=" * 60)
    print("测试用例 2: 使用 fallback 行号")
    print("=" * 60)

    # 故意使用不匹配的搜索块
    wrong_search_block = '''@router.get("/", response_model=WrongModel)'''

    result2 = apply_search_replace(
        original_content,
        wrong_search_block,
        replace_block_1,
        fallback_start=9,
        fallback_end=12
    )

    if result2:
        print("[PASS] 测试用例 2 通过: fallback 行号生效")
    else:
        print("[FAIL] 测试用例 2 失败: fallback 行号也失败了")

    # 测试用例 3: 缩进差异
    print("\n" + "=" * 60)
    print("测试用例 3: 缩进差异（行级别宽松匹配）")
    print("=" * 60)

    # 搜索块有额外的缩进
    indented_search_block = '''    @router.get("/", response_model=ResponseModel)
    async def health_check(request: Request):
        """健康检查端点"""
        return {"status": "ok", "message": "healthy"}'''

    result3 = apply_search_replace(
        original_content,
        indented_search_block,
        replace_block_1,
        fallback_start=None,
        fallback_end=None
    )

    if result3:
        print("[PASS] 测试用例 3 通过: 缩进差异处理成功")
    else:
        print("[FAIL] 测试用例 3 失败: 缩进差异无法处理")

    # 测试用例 4: 打印原始内容用于调试
    print("\n" + "=" * 60)
    print("调试信息: 原始内容")
    print("=" * 60)
    print(original_content)
    print("\n原始内容行数:", len(original_content.splitlines()))


if __name__ == "__main__":
    test_search_replace()
