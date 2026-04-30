"""
OmniFlowAI - AI 驱动的研发全流程引擎
Backend 入口文件
"""

import asyncio
import os
import sys

# Windows 平台特殊处理（必须在所有其他 import 之前）
if sys.platform == 'win32':
    # 1. 设置事件循环策略以支持子进程（关键修复）
    # SelectorEventLoop 不支持子进程，必须使用 ProactorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # 2. Windows 控制台 UTF-8 编码修复
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.health import router as health_router
from app.api.v1.pipeline import router as pipeline_router
from app.api.v1.system import router as system_router
from app.api.v1.workspace import router as workspace_router
from app.api.v1.code_modify import router as code_modify_router
from app.api.v1.code_modify_batch import router as code_modify_batch_router
from app.core.config import settings
from app.core.database import init_db
from app.core.response import ResponseModel
from app.core.logging import (
    logger, info, error, RequestLogMiddleware,
    log_exception, op_logger, set_request_id
)


async def _periodic_buffer_cleanup():
    """定期清理 SSE Log Buffer，防止内存泄漏"""
    from app.core.sse_log_buffer import _cleanup_expired_buffers
    while True:
        try:
            await asyncio.sleep(600)  # 每 10 分钟清理一次
            _cleanup_expired_buffers()
        except Exception:
            error("SSE Buffer 清理任务异常", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    import asyncio

    # Windows 平台：确保使用 ProactorEventLoop（支持子进程）
    # 注意：Uvicorn 可能会覆盖我们在文件开头设置的策略，所以在这里再次确认
    if sys.platform == 'win32':
        current_loop = asyncio.get_event_loop()
        if not isinstance(current_loop, asyncio.ProactorEventLoop):
            # 如果当前不是 ProactorEventLoop，需要重新设置
            # 注意：这通常发生在 Uvicorn 覆盖了我们的设置时
            error(
                "当前事件循环不是 ProactorEventLoop，子进程功能可能无法正常工作",
                current_loop_type=type(current_loop).__name__
            )
            # 尝试设置策略（虽然可能已晚，但记录日志有助于调试）
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # 启动时执行
    info("OmniFlowAI Backend 启动中...", env=settings.ENV, debug=settings.DEBUG)

    # 初始化数据库
    info("初始化数据库...")
    try:
        await init_db()
        info("数据库初始化完成")
    except Exception:
        error("数据库初始化失败", exc_info=True)
        raise

    # 启动 SSE Buffer 定期清理任务
    cleanup_task = asyncio.create_task(_periodic_buffer_cleanup())
    info("SSE Buffer 定期清理任务已启动")

    yield

    # 关闭时执行
    info("OmniFlowAI Backend 关闭中...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="OmniFlowAI 核心 API 服务",
    description="""
    OmniFlowAI 的后端服务，支持 Pipeline 全生命周期管理。

    ## 核心功能
    * **Pipeline CRUD**: 创建、读取、更新和删除流水线
    * **执行触发**: 触发特定的 Pipeline 任务
    * **状态查询**: 实时监控 Pipeline 运行状态
    * **审批管理**: 支持 Pipeline 的审批和驳回操作
    * **系统监控**: 实时查看服务器 CPU 和内存使用情况

    ## 统一响应格式
    所有 API 返回统一的响应格式：
    ```json
    {
        "success": true,
        "data": { ... },
        "error": null,
        "request_id": "uuid-string"
    }
    ```
    """,
    version="0.1.2",
    contact={
        "name": "OmniFlowAI Team",
        "url": "https://github.com/sennemmi/feishutemp",
    },
    lifespan=lifespan,
)

# 请求日志中间件（必须在 CORS 之前）
app.add_middleware(RequestLogMiddleware)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """为每个请求添加唯一 request_id"""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    # 设置日志上下文中的 request_id
    set_request_id(request_id)

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理 - 统一响应格式"""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # 记录详细错误日志
    log_exception(
        exc,
        context={
            "path": request.url.path,
            "method": request.method,
            "client": request.client.host if request.client else "unknown",
        },
        request_id=request_id
    )

    return JSONResponse(
        status_code=500,
        content=ResponseModel(
            success=False,
            data=None,
            error=str(exc),
            request_id=request_id
        ).model_dump()
    )


# 注册路由
app.include_router(health_router, prefix="/api/v1", tags=["health"])
app.include_router(pipeline_router, prefix="/api/v1", tags=["pipeline"])
app.include_router(code_modify_router, prefix="/api/v1", tags=["code-modify"])
app.include_router(code_modify_batch_router, prefix="/api/v1", tags=["code-modify-batch"])
app.include_router(system_router, prefix="/api/v1", tags=["system"])
app.include_router(workspace_router, prefix="/api/v1", tags=["workspace"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,  # 强制关闭自动重启，避免日志写入导致无限循环
        log_level="warning",  # 减少 Uvicorn 自身日志噪音
        access_log=False,  # 关闭访问日志（由我们的 RequestLogMiddleware 处理）
    )