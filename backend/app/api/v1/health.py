
"""
Health check endpoints
"""

from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok"}

# 这是一个有语法错误的函数（缺少冒号）
def broken_function():
    """这个函数有语法错误"""
    return {"broken": True}
