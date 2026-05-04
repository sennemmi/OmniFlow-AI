#!/usr/bin/env python3
"""
测试脚本：简化版 DELIVERY 阶段测试（无需真实 Pipeline）

此脚本：
1. 使用模拟的 Pipeline ID
2. 直接把后端项目文件复制到临时工作区
3. 执行 Git 分支创建、提交、推送
4. 创建 PR

使用方式:
  python scripts/test_delivery_simple.py
  
环境变量:
  TARGET_PROJECT_PATH: 目标项目路径 (默认: 当前目录)
"""

import asyncio
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings

# ========================== 配置 ==========================
TARGET_PROJECT_PATH = os.environ.get("TARGET_PROJECT_PATH", str(Path(__file__).parent.parent.parent))
TEST_PIPELINE_ID = 99999  # 模拟的 Pipeline ID

# 要复制的文件列表（模拟从 Sandbox 获取的文件）
TEST_FILES = [
    "backend/app/main.py",
    "backend/app/models/__init__.py",
    "backend/app/api/v1/__init__.py",
    "backend/requirements.txt",
    ".gitignore",
]


async def test_delivery_simple():
    """
    简化版 DELIVERY 阶段测试
    """
    print("🧪 简化版 DELIVERY 阶段测试")
    print(f"   目标项目: {TARGET_PROJECT_PATH}")
    print(f"   模拟 Pipeline ID: {TEST_PIPELINE_ID}")

    try:
        # ========== Step 1: 导入服务 ==========
        print("\n" + "="*60)
        print("Step 1: 初始化服务")
        print("="*60)

        from app.service.workspace import workspace_context
        from app.service.git_provider import GitProviderService
        from app.service.platform_provider import GitHubProviderService
        from app.core.timezone import now

        print("   ✅ 服务导入成功")

        # ========== Step 2: 创建临时工作区 ==========
        print("\n" + "="*60)
        print("Step 2: 创建临时工作区")
        print("="*60)

        with workspace_context(TEST_PIPELINE_ID) as ws:
            workspace_dir = ws.get_workspace_path()
            print(f"   ✅ 工作区创建: {workspace_dir}")

            # ========== Step 3: 复制文件到工作区 ==========
            print("\n" + "="*60)
            print("Step 3: 复制项目文件到工作区")
            print("="*60)

            source_dir = Path(TARGET_PROJECT_PATH)
            copied_count = 0
            failed_files = []

            # 复制整个 backend 目录
            backend_source = source_dir / "backend"
            backend_target = workspace_dir / "backend"

            if backend_source.exists():
                print(f"   复制 backend 目录...")
                try:
                    # 使用 shutil 复制整个目录（保留 .git 目录以便 Git 操作）
                    shutil.copytree(
                        backend_source,
                        backend_target,
                        ignore=shutil.ignore_patterns(
                            "__pycache__",
                            "*.pyc",
                            ".pytest_cache",
                            "*.egg-info",
                            "node_modules"
                        ),
                        dirs_exist_ok=True
                    )
                    copied_count += 1
                    print(f"   ✅ backend 目录复制完成（含 .git）")
                except Exception as e:
                    print(f"   ⚠️ backend 目录复制失败: {e}")
                    failed_files.append("backend/")
            else:
                print(f"   ⚠️ backend 目录不存在: {backend_source}")

            # 复制其他文件
            for file_path in TEST_FILES:
                source_file = source_dir / file_path
                if source_file.exists():
                    try:
                        target_file = workspace_dir / file_path
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_file, target_file)
                        copied_count += 1
                        print(f"   ✅ {file_path}")
                    except Exception as e:
                        print(f"   ⚠️ 复制失败 {file_path}: {e}")
                        failed_files.append(file_path)
                else:
                    print(f"   ⚠️ 文件不存在: {file_path}")
                    failed_files.append(file_path)

            print(f"\n   📊 复制统计:")
            print(f"      - 成功: {copied_count}")
            print(f"      - 失败: {len(failed_files)}")

            # 记录成功复制的文件列表，用于后续 Git 添加
            copied_files = [f for f in TEST_FILES if (workspace_dir / f).exists()]
            if backend_source.exists():
                copied_files.append("backend/")

            # ========== Step 4: Git 操作 ==========
            print("\n" + "="*60)
            print("Step 4: Git 操作")
            print("="*60)

            git_service = GitProviderService(str(workspace_dir))

            # 【关键】设置 AI 远程仓库
            try:
                git_service.setup_ai_remote("ai")
                print(f"   ✅ 设置 AI 远程仓库: {settings.GITHUB_OWNER}/{settings.GITHUB_REPO}")
            except Exception as e:
                print(f"   ⚠️ 设置 AI 远程仓库失败: {e}")

            # 【关键】重置工作区，丢弃所有本地修改（避免分支切换冲突）
            try:
                git_service.reset_hard("HEAD")
                git_service.clean_untracked()
                print("   ✅ 重置工作区，丢弃本地修改")
            except Exception as e:
                print(f"   ⚠️ 重置工作区失败: {e}")

            timestamp = now().strftime("%Y%m%d_%H%M%S")
            git_branch = f"devflow/test-delivery-{TEST_PIPELINE_ID}-{timestamp}"

            # 创建分支（基于 AI 远程的 main 分支）
            try:
                # 先获取 AI 远程的最新代码
                git_service.fetch("ai")
                # 从 AI 远程的 main 分支创建新分支
                git_service._run_git_command(["checkout", "-b", git_branch, "ai/main"])
                print(f"   ✅ 创建分支: {git_branch} (基于 ai/main)")
            except Exception as e:
                print(f"   ⚠️ 创建分支失败: {e}")
                # 尝试使用已有分支
                git_branch = f"devflow/test-delivery-{TEST_PIPELINE_ID}"
                try:
                    git_service.checkout_branch(git_branch)
                    print(f"   ✅ 切换到已有分支: {git_branch}")
                except Exception as e2:
                    print(f"   ❌ 分支操作失败: {e2}")
                    return

            # 添加文件（只添加我们复制的文件，避免扫描整个工作区）
            print("   ⏳ 添加文件到暂存区...")
            start_time = time.time()
            for file_path in copied_files:
                try:
                    git_service.add_files([file_path])
                except Exception as e:
                    print(f"   ⚠️ 添加文件失败 {file_path}: {e}")
            elapsed = time.time() - start_time
            print(f"   ✅ 添加文件到暂存区 ({elapsed:.2f}s)")

            # 提交
            if git_service.has_changes():
                print("   ⏳ 提交变更...")
                start_time = time.time()
                commit_message = f"feat(test-delivery-{TEST_PIPELINE_ID}): 测试交付阶段\n\n- 从工作区复制文件\n- 测试 Git 提交流程\n- 验证 PR 创建"
                git_service.commit_changes(commit_message)
                commit_hash = git_service.get_last_commit_hash()
                elapsed = time.time() - start_time
                print(f"   ✅ 提交: {commit_hash[:8]} ({elapsed:.2f}s)")
            # 推送到 AI 远程仓库
            if commit_hash:
                print(f"   ⏳ 推送到 AI 远程: {git_branch}...")
                start_time = time.time()
                try:
                    git_service._run_git_command(["push", "-u", "ai", git_branch])
                    elapsed = time.time() - start_time
                    print(f"   ✅ 推送到 AI 远程: {git_branch} ({elapsed:.2f}s)")
                except Exception as e:
                    elapsed = time.time() - start_time
                    print(f"   ⚠️ 推送失败 ({elapsed:.2f}s): {e}")
                    print("   可能原因: 远程仓库未配置或网络问题")

            # ========== Step 5: 创建 PR ==========
            print("\n" + "="*60)
            print("Step 5: 创建 Pull Request")
            print("="*60)

            pr_title = f"Test Delivery: 简化版测试 #{TEST_PIPELINE_ID}"
            pr_body = f"""## 测试交付阶段（简化版）

**测试信息:**
- Pipeline ID: {TEST_PIPELINE_ID} (模拟)
- 分支: `{git_branch}`
- 提交: `{commit_hash[:8] if commit_hash else 'N/A'}`
- 时间: {datetime.now().isoformat()}

**文件变更:**
- 复制了 {copied_count} 个文件/目录
- 源目录: `{source_dir}`
- 目标工作区: `{workspace_dir}`

**测试目的:**
验证 DELIVERY 阶段的完整流程：
1. ✅ 创建临时工作区
2. ✅ 复制文件到工作区
3. ✅ 创建 Git 分支
4. ✅ 提交代码
5. ✅ 推送到远程
6. ⏳ 创建 PR

**备注:**
这是一个自动化测试 PR，用于验证 OmniFlowAI 的交付流程。
"""

            try:
                async with GitHubProviderService() as github:
                    pr_result = await github.create_pull_request(
                        head_branch=git_branch,
                        title=pr_title,
                        body=pr_body,
                        base_branch="main"
                    )

                    if pr_result.success:
                        print(f"   ✅ PR 创建成功!")
                        print(f"   📎 URL: {pr_result.pr_url}")
                        print(f"   🔢 PR Number: {pr_result.pr_number}")
                    else:
                        print(f"   ❌ PR 创建失败: {pr_result.error}")
            except Exception as e:
                print(f"   ❌ PR 创建异常: {e}")
                import traceback
                traceback.print_exc()

        # ========== Step 6: 完成 ==========
        print("\n" + "="*60)
        print("✅ DELIVERY 阶段测试完成!")
        print("="*60)
        print(f"\n   📊 测试摘要:")
        print(f"      - Pipeline ID: {TEST_PIPELINE_ID} (模拟)")
        print(f"      - 工作区: {workspace_dir}")
        print(f"      - 分支: {git_branch}")
        print(f"      - 提交: {commit_hash[:8] if commit_hash else 'N/A'}")
        print(f"      - 复制文件数: {copied_count}")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    """直接运行测试"""
    print("="*60)
    print("🚀 简化版 DELIVERY 阶段测试")
    print("="*60)
    print(f"\n配置:")
    print(f"   目标项目: {TARGET_PROJECT_PATH}")
    print(f"   Pipeline ID: {TEST_PIPELINE_ID} (模拟)")

    # 运行测试
    asyncio.run(test_delivery_simple())

    print("\n" + "="*60)
    print("✨ 测试完成!")
    print("="*60)
