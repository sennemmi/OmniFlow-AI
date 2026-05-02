#!/usr/bin/env python3
"""
一个简单的测试脚本，用于测试 CoderAgent 的搜索替换功能
"""


def greet(name: str) -> str:
    """简单的问候函数"""
    return f"Hello, {name}!"


def calculate_sum(a: int, b: int) -> int:
    """计算两个数的和"""
    result = a + b
    return result


if __name__ == "__main__":
    print(greet("World"))
    print(f"Sum: {calculate_sum(1, 2)}")
