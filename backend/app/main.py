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

# 【关键修复】避免循环导入：先导入模块，再从模块获取属性
# 不直接从 main import (app, lifespan, settings)，因为这会导致 main.py 导入 app.core.logging 时形成循环
import main as _main

# 导出必要的对象供测试使用
app = _main.app
lifespan = _main.lifespan
settings = _main.settings

__all__ = ["app", "lifespan", "settings"]
