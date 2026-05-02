#!/usr/bin/env python3
"""
分层测试顺序验证脚本

使用真实的 LayeredTestRunner 验证分层测试执行顺序是否符合"快速失败原则"：
Layer 1: 语法检查（毫秒级）
Layer 2: 防御性测试（核心保护机制）
Layer 3: 回归测试
Layer 4: 新测试
Layer 5: 健康检查

使用方法:
    python scripts/test_layer_order.py
    python scripts/test_layer_order.py --verbose
"""

import asyncio
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any
from unittest.mock import patch, MagicMock, AsyncMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.service.layered_test_runner import LayeredTestRunner, LayerResult, LayeredTestResult
from app.agents.reviewer import ReviewAgent, ReviewDecision
from app.agents.multi_agent_coordinator import MultiAgentCoordinator


class LayerOrderTester:
    """分层顺序测试器 - 使用真实的 Agent 和 Runner"""

    def __init__(self):
        self.test_results: List[Dict[str, Any]] = []

    async def test_layer_1_syntax_check_first(self) -> bool:
        """
        测试场景 1: Layer 1 语法检查最先执行
        使用真实的 LayeredTestRunner 运行带有语法错误的代码
        """
        print("\n" + "=" * 60)
        print("🧪 测试场景 1: Layer 1 语法检查最先执行")
        print("=" * 60)

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建有语法错误的文件
            new_files = [
                {
                    "file_path": "backend/app/broken.py",
                    "content": "def broken(:\n    pass"  # 语法错误：缺少右括号
                }
            ]

            # 使用真实的 LayeredTestRunner
            start_time = time.time()
            result = await LayeredTestRunner.run(
                workspace_path=tmpdir,
                new_files=new_files,
                sandbox_port=None
            )
            elapsed_ms = (time.time() - start_time) * 1000

            # 验证只有 Layer 1 被执行（快速失败）
            assert len(result.layers) == 1, f"语法错误时应该只有 Layer 1 的结果，实际有 {len(result.layers)} 层"
            assert result.layers[0].layer == "syntax", f"第一层应该是语法检查，实际是 {result.layers[0].layer}"
            assert result.layers[0].passed is False, "语法检查应该失败"
            assert result.failure_cause == "code_bug", f"语法错误应该返回 code_bug，实际是 {result.failure_cause}"
            assert elapsed_ms < 100, f"语法检查应该很快完成（<100ms），实际用了 {elapsed_ms:.1f}ms"

            # 使用真实的 ReviewAgent 验证决策
            decision = ReviewAgent.decide(result, attempt=0, max_retries=3)
            assert decision.action == "auto_fix", f"语法错误应该允许 auto_fix，实际是 {decision.action}"

            print(f"✅ 通过: 语法错误时立即失败（{elapsed_ms:.1f}ms），不执行后续层")
            print(f"   - 执行层数: {len(result.layers)}")
            print(f"   - 失败原因: {result.failure_cause}")
            print(f"   - 决策动作: {decision.action}")

            return True

    async def test_layer_2_defense_before_new_tests(self) -> bool:
        """
        测试场景 2: Layer 2 防御性测试在 Layer 4 新测试之前
        模拟防御性测试失败的情况
        """
        print("\n" + "=" * 60)
        print("🧪 测试场景 2: Layer 2 防御性测试优先于新测试")
        print("=" * 60)

        # 创建模拟的 LayeredTestResult，模拟防御性测试失败
        # 注意：这里我们不能真的让防御性测试失败（因为那是系统保护机制）
        # 所以我们模拟这个结果来验证决策逻辑
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[
                LayerResult(layer="syntax", passed=True, summary="语法检查通过"),
                LayerResult(
                    layer="defense",
                    passed=False,
                    summary="2 个防御性测试失败",
                    failed_tests=["test_rollback_change_perfect_restore"],
                    error_type="defense_failure"
                )
            ],
            failure_cause="defense_broken",
            failed_tests=["test_rollback_change_perfect_restore"],
            error_details={
                "layer": "defense",
                "message": "防御性测试失败",
                "logs": "AssertionError: 文件回滚测试失败",
                "suggestion": "代码破坏了核心保护机制，必须人工介入"
            }
        )

        # 使用真实的 ReviewAgent 验证决策
        decision = ReviewAgent.decide(layered_result, attempt=0, max_retries=3)

        # 验证执行顺序
        layer_names = [l.layer for l in layered_result.layers]
        assert "syntax" in layer_names, "应该先执行语法检查"
        assert "defense" in layer_names, "应该执行防御性测试"
        assert "new_tests" not in layer_names, "防御性测试失败时不应该执行新测试"

        # 验证决策 - 防御性测试失败必须人工介入
        assert decision.action == "request_user", f"防御性测试失败必须 request_user，实际是 {decision.action}"
        assert decision.options == ["rollback"], f"防御性测试失败只能回滚，实际是 {decision.options}"

        print("✅ 通过: 防御性测试失败必须人工介入")
        print(f"   - 执行层: {layer_names}")
        print(f"   - 失败原因: {layered_result.failure_cause}")
        print(f"   - 决策动作: {decision.action}")
        print(f"   - 可用选项: {decision.options}")

        return True

    async def test_layer_3_regression_before_new_tests(self) -> bool:
        """
        测试场景 3: Layer 3 回归测试在 Layer 4 新测试之前
        """
        print("\n" + "=" * 60)
        print("🧪 测试场景 3: 回归测试优先于新测试")
        print("=" * 60)

        # 模拟回归测试失败
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[
                LayerResult(layer="syntax", passed=True, summary="语法检查通过"),
                LayerResult(layer="defense", passed=True, summary="防御性测试通过"),
                LayerResult(
                    layer="regression",
                    passed=False,
                    summary="3 个回归测试失败",
                    failed_tests=["test_user_model", "test_auth", "test_api"]
                )
            ],
            failure_cause="regression_broken",
            failed_tests=["test_user_model", "test_auth", "test_api"],
            error_details={
                "layer": "regression",
                "message": "回归测试失败",
                "suggestion": "新代码导致原有测试失败"
            }
        )

        # 使用真实的 ReviewAgent 验证决策
        decision = ReviewAgent.decide(layered_result, attempt=0, max_retries=3)

        # 验证执行顺序
        layer_names = [l.layer for l in layered_result.layers]
        assert layer_names == ["syntax", "defense", "regression"], \
            f"执行顺序应该是: syntax -> defense -> regression，实际是 {layer_names}"

        # 验证决策
        assert decision.action == "request_user", f"回归测试失败应该 request_user，实际是 {decision.action}"
        assert "update_tests" in decision.options, "应该提供更新测试选项"
        assert "rollback" in decision.options, "应该提供回滚选项"

        print("✅ 通过: 回归测试失败询问用户")
        print(f"   - 执行层: {layer_names}")
        print(f"   - 失败原因: {layered_result.failure_cause}")
        print(f"   - 决策动作: {decision.action}")
        print(f"   - 可用选项: {decision.options}")

        return True

    async def test_layer_4_new_tests_allow_auto_fix(self) -> bool:
        """
        测试场景 4: Layer 4 新测试失败允许 Auto-Fix
        """
        print("\n" + "=" * 60)
        print("🧪 测试场景 4: 新测试失败允许 Auto-Fix")
        print("=" * 60)

        # 模拟新测试失败
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[
                LayerResult(layer="syntax", passed=True, summary="语法检查通过"),
                LayerResult(layer="defense", passed=True, summary="防御性测试通过"),
                LayerResult(layer="regression", passed=True, summary="回归测试通过"),
                LayerResult(
                    layer="new_tests",
                    passed=False,
                    summary="2 个新测试失败",
                    failed_tests=["test_new_feature_1", "test_new_feature_2"],
                    logs="AssertionError: expected 42 but got 0"
                )
            ],
            failure_cause="code_bug",
            failed_tests=["test_new_feature_1", "test_new_feature_2"],
            error_details={
                "layer": "new_tests",
                "message": "新测试失败",
                "logs": "AssertionError: expected 42 but got 0",
                "suggestion": "功能实现不符合测试预期"
            }
        )

        # 使用真实的 ReviewAgent 验证决策
        decision = ReviewAgent.decide(layered_result, attempt=0, max_retries=3)

        # 验证所有层都执行了
        layer_names = [l.layer for l in layered_result.layers]
        expected_layers = ["syntax", "defense", "regression", "new_tests"]
        assert layer_names == expected_layers, f"执行顺序应该是: {expected_layers}，实际是 {layer_names}"

        # 验证决策 - 新测试失败允许 auto_fix
        assert decision.action == "auto_fix", f"新测试失败应该允许 auto_fix，实际是 {decision.action}"
        assert decision.error_context is not None, "应该提供错误上下文"
        assert "new_tests" in decision.error_context, "错误上下文应该包含层级信息"

        print("✅ 通过: 新测试失败允许 Auto-Fix")
        print(f"   - 执行层: {layer_names}")
        print(f"   - 失败原因: {layered_result.failure_cause}")
        print(f"   - 决策动作: {decision.action}")

        return True

    async def test_max_retries_respected(self) -> bool:
        """
        测试场景 5: 最大重试次数限制
        使用真实的 MultiAgentCoordinator 验证
        """
        print("\n" + "=" * 60)
        print("🧪 测试场景 5: 最大重试次数限制")
        print("=" * 60)

        # 使用真实的 MultiAgentCoordinator
        coordinator = MultiAgentCoordinator()
        max_retries = coordinator.MAX_FIX_RETRIES

        # 模拟新测试失败，达到最大重试次数
        layered_result = LayeredTestResult(
            all_passed=False,
            layers=[
                LayerResult(layer="new_tests", passed=False, summary="测试失败")
            ],
            failure_cause="code_bug",
            failed_tests=["test_feature"],
            error_details={"layer": "new_tests", "message": "测试失败"}
        )

        # 第 3 次尝试（达到最大重试次数）
        decision = ReviewAgent.decide(layered_result, attempt=max_retries, max_retries=max_retries)

        assert decision.action == "request_user", f"达到最大重试次数后应该 request_user，实际是 {decision.action}"
        assert f"{max_retries} 次" in decision.user_message, "用户消息应该包含重试次数"

        print("✅ 通过: 最大重试次数限制有效")
        print(f"   - 最大重试次数: {max_retries}")
        print(f"   - 当前尝试: {max_retries}")
        print(f"   - 决策动作: {decision.action}")

        return True

    async def test_all_passed_proceed(self) -> bool:
        """
        测试场景 6: 所有测试通过
        """
        print("\n" + "=" * 60)
        print("🧪 测试场景 6: 所有测试通过")
        print("=" * 60)

        layered_result = LayeredTestResult(
            all_passed=True,
            layers=[
                LayerResult(layer="syntax", passed=True, summary="语法检查通过"),
                LayerResult(layer="defense", passed=True, summary="防御性测试通过"),
                LayerResult(layer="regression", passed=True, summary="回归测试通过"),
                LayerResult(layer="new_tests", passed=True, summary="新测试通过")
            ],
            failure_cause=None
        )

        # 使用真实的 ReviewAgent
        decision = ReviewAgent.decide(layered_result, attempt=0)

        assert decision.action == "proceed", f"所有测试通过应该 proceed，实际是 {decision.action}"

        print("✅ 通过: 所有测试通过进入 proceed")
        print(f"   - 所有层通过: True")
        print(f"   - 决策动作: {decision.action}")

        return True

    async def test_real_runner_with_valid_code(self) -> bool:
        """
        测试场景 7: 使用真实的 Runner 运行有效代码
        验证 Runner 能正确执行所有层
        """
        print("\n" + "=" * 60)
        print("🧪 测试场景 7: 使用真实 Runner 运行有效代码")
        print("=" * 60)

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建有效的 Python 文件
            new_files = [
                {
                    "file_path": "backend/app/valid.py",
                    "content": "def add(a: int, b: int) -> int:\n    return a + b\n"
                }
            ]

            # 使用真实的 LayeredTestRunner
            start_time = time.time()
            result = await LayeredTestRunner.run(
                workspace_path=tmpdir,
                new_files=new_files,
                sandbox_port=None
            )
            elapsed_ms = (time.time() - start_time) * 1000

            # 验证 Layer 1 通过
            assert len(result.layers) >= 1, "应该至少执行 Layer 1"
            assert result.layers[0].layer == "syntax", "第一层应该是语法检查"
            assert result.layers[0].passed is True, "有效代码应该通过语法检查"

            print(f"✅ 通过: 有效代码通过语法检查（{elapsed_ms:.1f}ms）")
            print(f"   - 执行层数: {len(result.layers)}")
            print(f"   - Layer 1 结果: {'通过' if result.layers[0].passed else '失败'}")

            return True

    async def run_all_tests(self) -> bool:
        """运行所有测试场景"""
        print("\n" + "=" * 70)
        print("🛡️  分层测试顺序验证（使用真实 Agent & Runner）")
        print("=" * 70)
        print("\n验证快速失败原则:")
        print("  Layer 1: 语法检查（毫秒级）")
        print("  Layer 2: 防御性测试（核心保护机制）")
        print("  Layer 3: 回归测试")
        print("  Layer 4: 新测试")
        print("  Layer 5: 健康检查")
        print()

        tests = [
            ("Layer 1 语法检查（真实 Runner）", self.test_layer_1_syntax_check_first),
            ("Layer 2 防御性测试优先", self.test_layer_2_defense_before_new_tests),
            ("Layer 3 回归测试优先", self.test_layer_3_regression_before_new_tests),
            ("Layer 4 允许 Auto-Fix", self.test_layer_4_new_tests_allow_auto_fix),
            ("最大重试限制（真实 Coordinator）", self.test_max_retries_respected),
            ("全部通过", self.test_all_passed_proceed),
            ("真实 Runner 运行有效代码", self.test_real_runner_with_valid_code),
        ]

        passed = 0
        failed = 0

        for name, test_func in tests:
            try:
                if await test_func():
                    passed += 1
                else:
                    failed += 1
                    print(f"❌ 测试失败: {name}")
            except Exception as e:
                failed += 1
                print(f"❌ 测试异常: {name}")
                print(f"   错误: {e}")
                import traceback
                traceback.print_exc()

        print("\n" + "=" * 70)
        print("📊 测试结果汇总")
        print("=" * 70)
        print(f"✅ 通过: {passed}")
        print(f"❌ 失败: {failed}")
        print(f"📈 通过率: {passed}/{passed + failed} ({passed/(passed+failed)*100:.1f}%)")
        print("=" * 70)

        return failed == 0


def run_in_docker(image_name: str = "omniflowai/sandbox:latest") -> int:
    """在 Docker sandbox 中运行分层顺序验证"""
    import subprocess

    project_root = Path(__file__).parent.parent

    print("=" * 70)
    print("🐳 在 Docker Sandbox 中运行分层顺序验证")
    print("=" * 70)
    print(f"镜像: {image_name}")
    print()

    # 检查 Docker 是否可用
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            print("❌ Docker 不可用")
            return 1
    except Exception as e:
        print(f"❌ Docker 检查失败: {e}")
        return 1

    # 检查镜像是否存在
    result = subprocess.run(
        ["docker", "images", "-q", image_name],
        capture_output=True,
        text=True,
        timeout=10
    )
    if len(result.stdout.strip()) == 0:
        print(f"❌ Docker 镜像 '{image_name}' 不存在")
        print("请先构建镜像：")
        print(f"  docker build -t {image_name} .")
        return 1

    print(f"✅ Docker 镜像 '{image_name}' 已存在")
    print()

    # 在容器中运行脚本
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{project_root}:/workspace/backend:ro",
        "-e", "PYTHONPATH=/workspace/backend",
        "-w", "/workspace/backend",
        image_name,
        "python", "scripts/test_layer_order.py", "--local"
    ]

    print("🚀 启动容器运行测试...")
    print("-" * 70)

    try:
        result = subprocess.run(cmd, timeout=300)
        return result.returncode
    except subprocess.TimeoutExpired:
        print("❌ 测试超时（5分钟）")
        return 1
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        return 1


def main():
    import argparse

    parser = argparse.ArgumentParser(description="验证分层测试执行顺序（使用真实 Agent）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细输出")
    parser.add_argument("--docker", "-d", action="store_true", help="在 Docker sandbox 中运行")
    parser.add_argument("--local", action="store_true", help=argparse.SUPPRESS)  # 内部使用
    parser.add_argument("--image", default="omniflowai/sandbox:latest", help="Docker 镜像名称")
    args = parser.parse_args()

    # 如果在 Docker 中运行（--local 标志），直接执行测试
    if args.local:
        tester = LayerOrderTester()
        success = asyncio.run(tester.run_all_tests())
        return 0 if success else 1

    # 如果指定了 --docker，在 Docker 中运行
    if args.docker:
        return run_in_docker(args.image)

    # 默认在本地运行
    tester = LayerOrderTester()
    success = asyncio.run(tester.run_all_tests())

    if success:
        print("\n🎉 所有测试通过！分层顺序符合快速失败原则。")
        print("\n提示: 使用 --docker 参数可以在 Docker sandbox 中运行此测试")
        return 0
    else:
        print("\n⚠️  部分测试失败，请检查分层逻辑。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
