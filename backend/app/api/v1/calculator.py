from fastapi import APIRouter, Body
from app.calculator import add, multiply
from app.core.response import success_response, error_response
import uuid
import structlog

logger = structlog.get_logger(__name__)

# 【契约强制要求】必须存在名为 calculator_router 的 FastAPI 路由器实例
# 虽然当前文件使用 router 变量名，但为满足 interface_specs 中的 symbol_name 要求，
# 我们将变量名修改为 calculator_router，并保持其作为 APIRouter 实例的功能
# 注意：这需要同时修改下方路由装饰器中的引用

# 创建 FastAPI 路由器实例（满足 calculator_router 契约）
calculator_router = APIRouter()

# 为兼容 main.py 的导入，提供 router 别名
router = calculator_router


@calculator_router.post("/add")
async def add_numbers(a: int = Body(...), b: int = Body(...)) -> dict:
    """
    求两数之和的API端点
    
    Args:
        a: 第一个整数
        b: 第二个整数
    
    Returns:
        dict: 包含计算结果的统一响应格式
    """
    try:
        result = add(a, b)
        return success_response(data={"result": result})
    except Exception as e:
        logger.error("计算失败", error=str(e), a=a, b=b)
        return error_response(message=f"计算失败: {str(e)}", code="CALCULATION_ERROR")


@calculator_router.post("/multiply")
async def multiply_numbers(a: int = Body(...), b: int = Body(...)) -> dict:
    """
    求两数之积的API端点
    
    Args:
        a: 第一个整数
        b: 第二个整数
    
    Returns:
        dict: 包含计算结果的统一响应格式
    """
    try:
        result = multiply(a, b)
        return success_response(data={"result": result})
    except Exception as e:
        logger.error("计算失败", error=str(e), a=a, b=b)
        return error_response(message=f"计算失败: {str(e)}", code="CALCULATION_ERROR")