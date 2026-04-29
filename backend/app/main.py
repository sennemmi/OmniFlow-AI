"""
OmniFlowAI - 应用入口（用于沙箱和测试环境）

这是 backend/main.py 的包装，用于支持从 app 包导入
"""

# 直接从根目录的 main 导入所有内容
import sys
from pathlib import Path

# 确保 backend/ 根目录在路径中
backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

# 导入根目录 main.py 的所有内容
from main import (
    app,
    lifespan,
    settings,
)

__all__ = ["app", "lifespan", "settings"]
