#!/usr/bin/env python3
"""
OmniFlowAI - 一键启动脚本
支持启动后端服务
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_backend():
    """启动后端服务"""
    backend_dir = Path(__file__).parent / "backend"
    
    print("🚀 启动 OmniFlowAI 后端服务...")
    print(f"📍 工作目录: {backend_dir}")
    
    try:
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
            cwd=backend_dir,
            check=True
        )
    except KeyboardInterrupt:
        print("\n👋 后端服务已停止")
    except subprocess.CalledProcessError as e:
        print(f"❌ 启动失败: {e}")
        sys.exit(1)


def install_deps():
    """安装依赖"""
    backend_dir = Path(__file__).parent / "backend"
    requirements_file = backend_dir / "requirements.txt"
    
    print("📦 安装后端依赖...")
    
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)],
            check=True
        )
        print("✅ 依赖安装完成")
    except subprocess.CalledProcessError as e:
        print(f"❌ 依赖安装失败: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="OmniFlowAI 启动脚本")
    parser.add_argument(
        "command",
        choices=["backend", "install"],
        help="选择要执行的命令: backend (启动后端), install (安装依赖)"
    )
    
    args = parser.parse_args()
    
    if args.command == "backend":
        run_backend()
    elif args.command == "install":
        install_deps()


if __name__ == "__main__":
    main()
