import asyncio
from app.service.sandbox_manager import sandbox_manager
from app.service.sandbox_tools import write_file, exec_command, git_diff

async def test():
    print("=" * 60)
    print("诊断 git_diff 问题")
    print("=" * 60)

    project_path = 'd:/feishuProj'

    # 启动沙箱
    print("\n[1] 启动沙箱...")
    info = await sandbox_manager.start(997, project_path)
    print(f"[OK] 沙箱启动成功 (端口: {info.port})")

    try:
        # 检查 git 状态
        print("\n[2] 检查 git 状态...")
        result = await exec_command(997, 'cd /workspace && git status')
        print(f"stdout: {result['stdout']}")
        print(f"stderr: {result['stderr']}")
        print(f"exit_code: {result['exit_code']}")

        # 检查 git 配置
        print("\n[3] 检查 git 配置...")
        result = await exec_command(997, 'cd /workspace && git config --list')
        print(f"git config: {result['stdout'][:500]}")

        # 写入一个新文件
        print("\n[4] 写入测试文件...")
        await write_file(997, 'backend/test_git_file.py', '# test file for git diff\nprint("test")')
        print("[OK] 文件写入成功")

        # 检查文件状态
        print("\n[5] 检查文件系统...")
        result = await exec_command(997, 'ls -la /workspace/backend/test_git_file.py')
        print(f"文件存在: {result['stdout']}")

        # 再次检查 git status
        print("\n[6] 再次检查 git status...")
        result = await exec_command(997, 'cd /workspace && git status')
        print(f"stdout:\n{result['stdout']}")

        # 测试 git diff
        print("\n[7] 测试 git_diff...")
        diff = await git_diff(997)
        print(f"git_diff 返回值: '{diff}'")
        print(f"git_diff 长度: {len(diff)}")

        # 直接执行 git diff 命令对比
        print("\n[8] 直接执行 git diff 命令...")
        result = await exec_command(997, 'cd /workspace && git diff')
        print(f"stdout: '{result['stdout']}'")
        print(f"stderr: '{result['stderr']}'")
        print(f"exit_code: {result['exit_code']}")

        # 尝试 git add 后再 diff
        print("\n[9] git add 后检查 diff --cached...")
        await exec_command(997, 'cd /workspace && git add backend/test_git_file.py')
        result = await exec_command(997, 'cd /workspace && git diff --cached')
        print(f"cached diff: '{result['stdout'][:500]}'")

        # 清理
        print("\n[10] 清理测试文件...")
        await exec_command(997, 'rm /workspace/backend/test_git_file.py')
        await exec_command(997, 'cd /workspace && git reset')
        print("[OK] 清理完成")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("\n[11] 停止沙箱...")
        await sandbox_manager.stop(997)
        print("[OK] 沙箱已停止")

    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test())
