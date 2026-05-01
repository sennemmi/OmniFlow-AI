#!/usr/bin/env python3
"""
轻量级防御性测试脚本
启动 Sandbox 并运行 defense + regression 测试，用于快速验证环境
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.service.sandbox_orchestrator import get_sandbox_orchestrator, cleanup_sandbox_orchestrator
from app.service.sandbox_file_service import SandboxFileService
from app.service.layered_test_runner import LayeredTestRunner


PIPELINE_ID = 99998  # 使用不同的 pipeline_id 避免冲突

# 回归测试目录（排除 defense 目录，因为已在 Layer 2 执行）
# 注意：使用 --ignore 参数排除 defense 目录，而不是跳过整个目录
REGRESSION_DIRS = [
    ("backend/tests/unit", ["defense"]),  # (目录, 排除子目录列表)
    ("backend/tests/integration", [])
]


async def run_defense_tests(file_service) -> Dict[str, Any]:
    """运行防御性测试"""
    print("\n🛡️ Step 2: 运行防御性测试...")
    start = time.time()

    result = await LayeredTestRunner._run_tests_in_docker(
        file_service=file_service,
        test_path="backend/tests/unit/defense",
        timeout=300
    )

    duration = time.time() - start

    print(f"\n� 防御性测试结果:")
    print(f"   成功: {result['success']}")
    print(f"   退出码: {result['exit_code']}")
    print(f"   摘要: {result['summary']}")
    print(f"   错误类型: {result.get('error_type')}")
    print(f"   耗时: {duration:.1f}s")

    if result['failed_tests']:
        print(f"\n❌ 失败测试:")
        for test in result['failed_tests']:
            print(f"   - {test}")

    if not result['success']:
        print(f"\n📜 详细日志:")
        print(result['logs'][:3000])
        if len(result['logs']) > 3000:
            print(f"\n... (日志已截断，共 {len(result['logs'])} 字符)")

    return result


async def check_path_exists(file_service, path: str) -> bool:
    """检查路径是否存在"""
    try:
        result = await file_service.list_directory(path)
        return result.get("success", False)
    except Exception:
        return False


async def run_regression_tests(file_service) -> List[Dict[str, Any]]:
    """运行回归测试"""
    print("\n🔄 Step 3: 运行回归测试...")

    results = []
    total_failed = 0
    skipped_dirs = []

    for reg_dir, ignore_patterns in REGRESSION_DIRS:
        # 【修复】检查目录是否存在
        exists = await check_path_exists(file_service, reg_dir)
        if not exists:
            print(f"\n   ⏭️  跳过: {reg_dir} (目录不存在)")
            skipped_dirs.append(reg_dir)
            continue

        print(f"\n   📁 测试目录: {reg_dir}")
        if ignore_patterns:
            print(f"   ⏭️  排除子目录: {', '.join(ignore_patterns)}")

        start = time.time()

        # 【修复】传递 ignore_patterns 参数排除 defense 目录
        result = await LayeredTestRunner._run_tests_in_docker(
            file_service=file_service,
            test_path=reg_dir,
            timeout=300,
            ignore_patterns=ignore_patterns if ignore_patterns else None
        )

        duration = time.time() - start

        print(f"   成功: {result['success']}, 摘要: {result['summary']}, 耗时: {duration:.1f}s")

        if result['failed_tests']:
            print(f"   ❌ 失败测试 ({len(result['failed_tests'])} 个):")
            for test in result['failed_tests'][:5]:  # 只显示前5个
                print(f"      - {test}")
            if len(result['failed_tests']) > 5:
                print(f"      ... 还有 {len(result['failed_tests']) - 5} 个")

        results.append({
            "dir": reg_dir,
            "result": result,
            "duration": duration
        })

        if not result['success']:
            total_failed += len(result.get('failed_tests', []))

    print(f"\n📊 回归测试汇总:")
    print(f"   测试目录数: {len(results)}")
    print(f"   跳过目录数: {len(skipped_dirs)}")
    if skipped_dirs:
        for d in skipped_dirs:
            print(f"      - {d}")
    print(f"   总失败测试数: {total_failed}")

    return results


async def main():
    print("=" * 70)
    print("🧪 分层测试快速验证 (Defense + Regression)")
    print("=" * 70)

    backend_dir = Path(__file__).parent.parent
    project_root = str(backend_dir.parent)

    # Step 1: 启动 Sandbox
    print("\n🐳 Step 1: 启动 Docker Sandbox...")
    sandbox_orch = get_sandbox_orchestrator(PIPELINE_ID)
    sandbox_init = await sandbox_orch.initialize(project_root)

    if not sandbox_init["success"]:
        print(f"❌ Sandbox 启动失败: {sandbox_init.get('error')}")
        return 1

    file_service = sandbox_orch.get_file_service()
    print("✅ Sandbox 就绪")

    all_passed = True

    try:
        # Step 2: 运行防御性测试
        defense_result = await run_defense_tests(file_service)
        if not defense_result['success']:
            all_passed = False
            print("\n" + "=" * 70)
            print("❌ 防御性测试失败 - 停止后续测试")
            print("=" * 70)
            return 1

        # Step 3: 运行回归测试
        regression_results = await run_regression_tests(file_service)
        regression_failed = any(not r['result']['success'] for r in regression_results)
        if regression_failed:
            all_passed = False

        # 最终汇总
        print("\n" + "=" * 70)
        print("� 测试汇总")
        print("=" * 70)
        print(f"✅ 防御性测试: {'通过' if defense_result['success'] else '失败'}")
        print(f"🔄 回归测试: {'通过' if not regression_failed else '失败'}")
        for r in regression_results:
            status = "✅" if r['result']['success'] else "❌"
            print(f"   {status} {r['dir']}: {r['result']['summary']}")

        print("\n" + "=" * 70)
        if all_passed:
            print("✅ 所有测试通过")
        else:
            print("❌ 存在测试失败")
        print("=" * 70)

        return 0 if all_passed else 1

    finally:
        print("\n🧹 清理 Sandbox...")
        await cleanup_sandbox_orchestrator(PIPELINE_ID)
        print("✅ 清理完成")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
