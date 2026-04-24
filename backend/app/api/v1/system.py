from fastapi import APIRouter, Request

from app.service.system_stats import SystemStatsService
from app.core.response import ResponseModel

router = APIRouter()

@router.get("/system/stats")
async def get_system_stats(request: Request):
    """获取服务器实时 CPU 使用率和内存占用情况"""
    request_id = getattr(request.state, "request_id", None)
    try:
        stats = SystemStatsService.collect_stats()
        return ResponseModel(
            success=True,
            data=stats.model_dump(),
            error=None,
            request_id=request_id
        )
    except Exception as e:
        return ResponseModel(
            success=False,
            data=None,
            error=str(e),
            request_id=request_id
        )