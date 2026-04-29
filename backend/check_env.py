"""检查环境配置"""
import os
import sys

print("当前工作目录:", os.getcwd())
print("Python 路径:", sys.executable)

# 尝试加载配置
try:
    from app.core.config import settings
    print("\n配置加载成功!")
    print(f"TARGET_PROJECT_PATH: {settings.TARGET_PROJECT_PATH}")
except Exception as e:
    print(f"\n配置加载失败: {e}")
    import traceback
    traceback.print_exc()
