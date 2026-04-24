"""
OmniFlowAI - AI 驱动的研发全流程引擎
Backend 入口文件
"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.health import router as health_router
from app.api.v1.pipeline import router as pipeline_router
from app.api.v1.system import router as system_router
from app.core.config import settings
from app.core.database import init_db
from app.core.response import ResponseModel


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    print(f"🚀 OmniFlowAI Backend 启动中...")
    print(f"📍 环境: {settings.ENV}")
    
    # 初始化数据库
    print("📦 初始化数据库...")
    await init_db()
    print("✅ 数据库初始化完成")
    
    yield
    # 关闭时执行
    print("👋 OmniFlowAI Backend 已关闭")


app = FastAPI(
    title="OmniFlowAI API",
    description="AI 驱动的研发全流程引擎",
    version="0.1.0",
    lifespan=lifespan,
)

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
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理 - 统一响应格式"""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    
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
app.include_router(system_router, prefix="/api/v1", tags=["system"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )