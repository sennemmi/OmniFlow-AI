"""
Sandbox Tools - Agent 可调用的沙箱工具函数

提供文件操作、命令执行、Git 操作等功能，所有操作在 Docker 沙箱容器内执行。
"""

import base64

from app.service.sandbox_manager import sandbox_manager


async def read_file(pipeline_id: int, path: str) -> str:
    """
    读取容器内 /workspace/{path} 的文件内容

    Args:
        pipeline_id: Pipeline ID
        path: 文件路径（相对于 /workspace）

    Returns:
        str: 文件内容

    Raises:
        FileNotFoundError: 文件不存在或读取失败
    """
    result = await sandbox_manager.exec(pipeline_id, f"cat /workspace/{path}")
    if result.exit_code != 0:
        raise FileNotFoundError(result.stderr)
    return result.stdout


async def write_file(pipeline_id: int, path: str, content: str) -> bool:
    """
    将 content 写入容器内 /workspace/{path}

    Args:
        pipeline_id: Pipeline ID
        path: 文件路径（相对于 /workspace）
        content: 文件内容

    Returns:
        bool: 是否写入成功
    """
    # 用 base64 传输内容避免引号转义问题
    b64 = base64.b64encode(content.encode()).decode()
    result = await sandbox_manager.exec(
        pipeline_id,
        f"echo {b64} | base64 -d > /workspace/{path}"
    )
    return result.exit_code == 0


async def exec_command(pipeline_id: int, cmd: str, timeout: int = 30) -> dict:
    """
    在容器内执行命令

    Args:
        pipeline_id: Pipeline ID
        cmd: 要执行的命令
        timeout: 超时时间（秒）

    Returns:
        dict: 包含 stdout, stderr, exit_code, timed_out 的字典
    """
    result = await sandbox_manager.exec(pipeline_id, cmd, timeout)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out
    }


async def list_directory(pipeline_id: int, path: str = ".", depth: int = 2) -> str:
    """
    列出容器内目录内容

    Args:
        pipeline_id: Pipeline ID
        path: 目录路径（相对于 /workspace）
        depth: 遍历深度

    Returns:
        str: 目录列表字符串
    """
    result = await sandbox_manager.exec(
        pipeline_id, f"find /workspace/{path} -maxdepth {depth} -not -path '*/.git/*'"
    )
    return result.stdout


async def git_diff(pipeline_id: int) -> str:
    """
    获取 Git 变更差异

    Args:
        pipeline_id: Pipeline ID

    Returns:
        str: git diff 输出
    """
    result = await sandbox_manager.exec(pipeline_id, "cd /workspace && git diff")
    return result.stdout


async def git_reset(pipeline_id: int) -> bool:
    """
    重置 Git 工作区（丢弃所有变更）

    Args:
        pipeline_id: Pipeline ID

    Returns:
        bool: 是否重置成功
    """
    result = await sandbox_manager.exec(
        pipeline_id, "cd /workspace && git checkout -- . && git clean -fd"
    )
    return result.exit_code == 0
