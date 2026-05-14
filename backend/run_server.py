"""
OmniFlowAI 服务器启动脚本

这个脚本确保在 Windows 上使用正确的事件循环策略启动 Uvicorn
必须在任何异步导入之前设置事件循环策略
"""

import asyncio
import sys

# 必须在所有其他导入之前设置事件循环策略
if sys.platform == 'win32':
    # Windows 必须使用 ProactorEventLoop 才能支持子进程
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    print(f"[启动] 已设置 WindowsProactorEventLoopPolicy")

# 现在可以安全导入其他模块
import uvicorn
from app.core.config import settings


if __name__ == "__main__":
    # 确认当前事件循环类型
    current_loop = asyncio.get_event_loop()
    print(f"[启动] 当前事件循环类型: {type(current_loop).__name__}")

    if sys.platform == 'win32' and not isinstance(current_loop, asyncio.ProactorEventLoop):
        print(f"[警告] 当前不是 ProactorEventLoop，尝试重新创建...")
        # 关闭当前循环并创建新的
        current_loop.close()
        new_loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(new_loop)
        print(f"[启动] 已切换到 ProactorEventLoop")

    # 启动 Uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level="warning",
        access_log=False,
        loop="auto" if sys.platform != 'win32' else "asyncio",  # 显式指定 loop 类型
    )
