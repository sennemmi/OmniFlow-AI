"""清除 Python 缓存文件"""
import shutil
from pathlib import Path

def clear_pycache():
    backend_dir = Path(__file__).parent
    
    # 删除所有 __pycache__ 目录
    for pycache in backend_dir.rglob("__pycache__"):
        print(f"删除: {pycache}")
        shutil.rmtree(pycache, ignore_errors=True)
    
    # 删除所有 .pyc 文件
    for pyc in backend_dir.rglob("*.pyc"):
        print(f"删除: {pyc}")
        pyc.unlink()
    
    print("缓存清理完成!")

if __name__ == "__main__":
    clear_pycache()
