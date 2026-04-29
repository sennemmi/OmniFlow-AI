"""检查配置加载情况"""
import os
import sys

print("=" * 60)
print("配置诊断")
print("=" * 60)

print(f"\n当前工作目录: {os.getcwd()}")
print(f"脚本所在目录: {os.path.dirname(os.path.abspath(__file__))}")

# 检查环境变量
env_path = os.environ.get('TARGET_PROJECT_PATH', '未设置')
print(f"\n环境变量 TARGET_PROJECT_PATH: {env_path}")

# 检查 .env 文件是否存在
env_file = os.path.join(os.getcwd(), '.env')
print(f"\n.env 文件路径: {env_file}")
print(f".env 文件存在: {os.path.exists(env_file)}")

if os.path.exists(env_file):
    print("\n.env 文件内容:")
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            if 'TARGET_PROJECT_PATH' in line:
                print(f"  {line.strip()}")

# 加载配置
print("\n" + "-" * 60)
print("加载 app.core.config.settings:")
from app.core.config import settings
print(f"TARGET_PROJECT_PATH: '{settings.TARGET_PROJECT_PATH}'")
print(f"USE_MODELSCOPE: {settings.USE_MODELSCOPE}")
print(f"DEFAULT_MODEL: {settings.DEFAULT_MODEL}")

# 检查路径解析
from pathlib import Path
if settings.TARGET_PROJECT_PATH:
    target_path = Path(settings.TARGET_PROJECT_PATH)
    print(f"\n路径解析:")
    print(f"  原始路径: {target_path}")
    print(f"  是否绝对路径: {target_path.is_absolute()}")
    if not target_path.is_absolute():
        backend_dir = Path(__file__).parent
        project_root_path = backend_dir.parent
        resolved = (project_root_path / target_path).resolve()
        print(f"  解析后路径: {resolved}")
else:
    print("\n警告: TARGET_PROJECT_PATH 为空!")

print("\n" + "=" * 60)
