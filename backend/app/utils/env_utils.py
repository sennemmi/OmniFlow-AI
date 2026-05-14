"""
环境检查工具函数

提供环境变量加载、API Key 检查、Docker 检查等功能
"""

import os
import subprocess
from pathlib import Path
from typing import Optional


def load_env(backend_dir: Path) -> None:
    """
    从 .env 文件加载环境变量

    Args:
        backend_dir: 后端目录路径
    """
    env_file = backend_dir / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v


def check_api_key(backend_dir: Path) -> bool:
    """
    检查是否配置了 API Key

    Args:
        backend_dir: 后端目录路径

    Returns:
        是否配置了任一 API Key
    """
    load_env(backend_dir)
    return any(
        os.getenv(k)
        for k in ["MODELSCOPE_API_KEY", "OPENAI_API_KEY", "LITELLM_API_KEY"]
    )


def check_docker() -> bool:
    """
    检查 Docker 是否可用

    Returns:
        Docker 是否可用
    """
    try:
        r = subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def get_env_status(backend_dir: Path) -> dict:
    """
    获取环境状态摘要

    Args:
        backend_dir: 后端目录路径

    Returns:
        环境状态字典
    """
    return {
        "api_key_configured": check_api_key(backend_dir),
        "docker_available": check_docker(),
        "missing_requirements": []
    }
