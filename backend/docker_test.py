import asyncio
from app.service.sandbox_manager import sandbox_manager

async def test():
    print("=" * 50)
    print("测试 SandboxManager")
    print("=" * 50)

    # 1. 启动沙箱
    print("\n[1] 启动沙箱容器...")
    info = await sandbox_manager.start(999, 'd:/feishuProj')
    print(f"✓ 容器ID: {info.container_id[:12]}")
    print(f"✓ 端口: {info.port}")
    print(f"✓ 启动时间: {info.started_at}")

    # 2. 测试 exec 命令
    print("\n[2] 测试 exec 命令...")
    result = await sandbox_manager.exec(999, 'echo "Hello from sandbox!"')
    print(f"✓ stdout: {result.stdout.strip()}")
    print(f"✓ exit_code: {result.exit_code}")

    # 3. 测试文件操作
    print("\n[3] 测试文件操作...")
    result = await sandbox_manager.exec(999, 'ls -la /workspace/')
    print(f"✓ 目录列表:\n{result.stdout}")

    # 4. 测试端口访问（简单的 HTTP 请求）
    print("\n[4] 测试端口访问...")
    import httpx
    try:
        # 尝试访问根路径（简单 HTTP 服务器应该可用）
        r = httpx.get(f'http://localhost:{info.port}/', timeout=5)
        print(f"✓ HTTP 状态码: {r.status_code}")
        print(f"✓ 响应长度: {len(r.text)} 字符")
    except Exception as e:
        print(f"✗ HTTP 访问失败: {e}")
        print("  (这是正常的，因为容器内可能没有运行 HTTP 服务)")

    # 5. 获取沙箱信息
    print("\n[5] 获取沙箱信息...")
    sandbox_info = sandbox_manager.get_info(999)
    if sandbox_info:
        print(f"✓ pipeline_id: {sandbox_info.pipeline_id}")
        print(f"✓ project_path: {sandbox_info.project_path}")

    # 6. 列出活动沙箱
    print("\n[6] 列出活动沙箱...")
    active = sandbox_manager.list_active()
    print(f"✓ 活动沙箱数量: {len(active)}")
    for s in active:
        print(f"  - Pipeline {s.pipeline_id}: port={s.port}")

    # 7. 停止沙箱
    print("\n[7] 停止沙箱容器...")
    success = await sandbox_manager.stop(999)
    print(f"✓ 停止成功: {success}")

    print("\n" + "=" * 50)
    print("测试完成！")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(test())
