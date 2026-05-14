"""
测试脚本：验证 _start_fastapi_in_sandbox 能否在 Sandbox 中正确启动 FastAPI

用法：
    cd backend
    python scripts/test_fastapi_startup.py [pipeline_id]

不传 pipeline_id 则自动查找一个运行中的 Sandbox 容器。
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.config import settings
from app.core.logging import info, error, warning, set_pipeline_id

DEBUG = True  # 开启详细调试输出


def debug(msg: str):
    """调试输出"""
    if DEBUG:
        print(f"  [DEBUG] {msg}")


async def find_running_sandbox() -> int:
    """查找一个运行中的 Sandbox 容器（通过 docker ps）"""
    import subprocess

    result = subprocess.run(
        ["docker", "ps", "--filter", "name=omniflow-sandbox-",
         "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=10
    )
    container_names = result.stdout.strip().split('\n')
    container_names = [n.strip() for n in container_names if n.strip()]

    debug(f"docker ps 找到的 sandbox 容器: {container_names}")

    for name in container_names:
        pid_str = name.replace("omniflow-sandbox-", "")
        try:
            pid = int(pid_str)
            return pid
        except ValueError:
            continue

    return None


async def test_start_fastapi(pipeline_id: int):
    """核心测试逻辑"""
    from app.service.pipeline import PipelineService
    from app.service.sandbox_manager import sandbox_manager

    set_pipeline_id(pipeline_id)

    print(f"\n{'='*60}")
    print(f"测试 Pipeline ID: {pipeline_id}")
    print(f"{'='*60}")

    # Step 1: 检查 Sandbox 状态
    print("\n[Step 1] 检查 Sandbox 状态...")
    sandbox_info = sandbox_manager.get_info(pipeline_id)
    if sandbox_info:
        print(f"  ✅ Sandbox 信息:")
        print(f"     container_id: {sandbox_info.container_id[:12] if sandbox_info.container_id else 'N/A'}")
        print(f"     port:         {sandbox_info.port}")
        print(f"     project_path: {sandbox_info.project_path}")
        print(f"     started_at:   {sandbox_info.started_at}")
    else:
        print(f"  ❌ 未找到 Sandbox 信息 (pipeline_id={pipeline_id})")
        print(f"     sandbox_manager._sandboxes keys: {list(sandbox_manager._sandboxes.keys())}")
        return False

    # Step 2: 检查 Sandbox 容器是否在运行
    print("\n[Step 2] 检查 Docker 容器状态...")
    import subprocess
    container_name = f"omniflow-sandbox-{pipeline_id}"
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={container_name}",
         "--format", "{{.Names}} {{.Status}} {{.Ports}}"],
        capture_output=True, text=True, timeout=10
    )
    if result.stdout.strip():
        print(f"  ✅ 容器运行中: {result.stdout.strip()}")
    else:
        print(f"  ❌ 容器未运行 ({container_name})")
        # 检查是否已退出
        result2 = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={container_name}",
             "--format", "{{.Names}} {{.Status}}"],
            capture_output=True, text=True, timeout=10
        )
        if result2.stdout.strip():
            print(f"  已退出的容器: {result2.stdout.strip()}")
        return False

    # Step 3: 检查 Sandbox 内当前 8000 端口状态
    print("\n[Step 3] 检查 Sandbox 内 8000 端口当前状态...")
    check_cmd = (
        "echo '--- 端口占用检查 ---'; "
        "fuser 8000/tcp 2>/dev/null && echo 'PORT_OCCUPIED' || echo 'PORT_FREE'; "
        "echo '--- 进程列表 (python) ---'; "
        "ps aux 2>/dev/null | grep python | grep -v grep || echo 'no python process'; "
        "echo '--- 磁盘空间 ---'; "
        "df -h /workspace 2>/dev/null | tail -1 || echo 'df failed'; "
        "echo '--- backend 目录 ---'; "
        "ls -la /workspace/backend/main.py 2>/dev/null || echo 'main.py NOT FOUND'; "
        "echo '--- uvicorn 可用性 ---'; "
        "which uvicorn 2>/dev/null || python -c 'import uvicorn; print(uvicorn.__file__)' 2>/dev/null || echo 'uvicorn NOT FOUND'; "
        "echo '--- END ---'"
    )
    try:
        exec_result = await sandbox_manager.exec(pipeline_id, check_cmd, timeout=15)
        print(f"  stdout:\n{exec_result.stdout}")
        if exec_result.stderr:
            print(f"  stderr:\n{exec_result.stderr[:1000]}")
        debug(f"  exit_code: {exec_result.exit_code}")
    except Exception as e:
        print(f"  ❌ exec 失败: {e}")
        return False

    # Step 4: 尝试启动 FastAPI
    print("\n[Step 4] 调用 _start_fastapi_in_sandbox...")
    t0 = time.perf_counter()
    try:
        result = await PipelineService._start_fastapi_in_sandbox(pipeline_id)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  耗时: {elapsed:.0f}ms")
        print(f"  返回: {result}")
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  ❌ 异常 (耗时 {elapsed:.0f}ms): {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 5: 启动后验证
    print("\n[Step 5] 启动后验证...")
    verify_cmd = (
        "echo '--- 端口 8000 进程 ---'; "
        "fuser 8000/tcp 2>/dev/null && echo 'PORT_OCCUPIED' || echo 'PORT_FREE'; "
        "echo '--- FastAPI 进程 ---'; "
        "ps aux 2>/dev/null | grep 'uvicorn' | grep -v grep || echo 'no uvicorn process'; "
        "echo '--- 健康检查 ---'; "
        "curl -s http://localhost:8000/api/v1/health 2>/dev/null | head -5 || echo 'HEALTH_CHECK_FAILED'; "
        "echo '--- FastAPI 日志 (最后 30 行) ---'; "
        "tail -30 /tmp/fastapi.log 2>/dev/null || echo 'no log file'"
    )
    try:
        exec_result = await sandbox_manager.exec(pipeline_id, verify_cmd, timeout=15)
        print(f"  stdout:\n{exec_result.stdout}")
        if exec_result.stderr:
            print(f"  stderr:\n{exec_result.stderr[:1000]}")
    except Exception as e:
        print(f"  ❌ exec 失败: {e}")

    # Step 6: 总结
    print(f"\n{'='*60}")
    if result.get("success"):
        print(f"  ✅ 测试通过! FastAPI 运行在 Sandbox 端口 {result.get('port')}")
        print(f"  测试地址: http://localhost:{result.get('port')}/api/v1/health")
    else:
        print(f"  ❌ 测试失败: {result.get('error')}")
    print(f"{'='*60}")

    return result.get("success", False)


async def main():
    pipeline_id = None

    # 尝试从命令行参数获取
    if len(sys.argv) > 1:
        try:
            pipeline_id = int(sys.argv[1])
        except ValueError:
            print(f"错误: 无效的 pipeline_id '{sys.argv[1]}'")
            sys.exit(1)

    # 自动查找
    if pipeline_id is None:
        print("未指定 pipeline_id，自动查找运行中的 Sandbox...")
        pipeline_id = await find_running_sandbox()

    if pipeline_id is None:
        print("\n❌ 未找到运行中的 Sandbox 容器")
        print("   请先启动一个 Pipeline 或确保有 Sandbox 容器在运行")
        print("   用法: python scripts/test_fastapi_startup.py <pipeline_id>")
        sys.exit(1)

    success = await test_start_fastapi(pipeline_id)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
