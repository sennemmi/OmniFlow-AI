
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
