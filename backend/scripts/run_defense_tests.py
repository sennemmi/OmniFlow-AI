#!/usr/bin/env python3
"""
防御性测试运行脚本

用于快速验证系统的核心保护机制是否正常工作。
这些测试是系统的"免疫系统"，必须在任何代码变更前通过。

使用方法:
    python scripts/run_defense_tests.py
    python scripts/run_defense_tests.py --verbose
    python scripts/run_defense_tests.py --tb=long
"""

import subprocess
import sys
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="运行防御性测试（系统的核心保护机制）"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细输出"
    )
    parser.add_argument(
        "--tb",
        default="short",
        choices=["short", "long", "line", "native"],
        help="错误追溯格式 (默认: short)"
    )
    parser.add_argument(
        "--layer",
        choices=["1", "2", "3", "4"],
        help="只运行特定层的测试 (1=代码修改, 2=测试运行器, 3=多Agent, 4=工作流)"
    )
    args = parser.parse_args()

    # 确保在项目根目录运行
    project_root = Path(__file__).parent.parent
    defense_test_dir = project_root / "tests" / "unit" / "defense"

    if not defense_test_dir.exists():
        print(f"❌ 错误: 防御性测试目录不存在: {defense_test_dir}")
        sys.exit(1)

    # 构建 pytest 命令
    cmd = [
        "python", "-m", "pytest",
        str(defense_test_dir),
        "-v",
        f"--tb={args.tb}"
    ]

    if args.verbose:
        cmd.append("-s")  # 显示 print 输出

    # 如果指定了层，添加过滤
    if args.layer:
        layer_map = {
            "1": "test_layer1",
            "2": "test_layer2",
            "3": "test_layer3",
            "4": "test_layer4"
        }
        cmd.extend(["-k", layer_map[args.layer]])

    # 打印信息
    print("=" * 60)
    print("🛡️  运行防御性测试（系统免疫系统）")
    print("=" * 60)
    print()
    print("测试分层:")
    print("  Layer 1: 代码修改与沙箱防线（防止 AI 破坏物理文件）")
    print("  Layer 2: 测试运行器与决策防线（防止旧测试被篡改）")
    print("  Layer 3: 多 Agent 协作与状态机防线（防止系统死循环）")
    print("  Layer 4: 工作流与状态持久化（确保界面显示正确）")
    print()
    print(f"命令: {' '.join(cmd)}")
    print("-" * 60)
    print()

    # 运行测试
    result = subprocess.run(cmd, cwd=project_root)

    print()
    print("=" * 60)
    if result.returncode == 0:
        print("✅ 所有防御性测试通过！系统保护机制正常。")
    else:
        print("❌ 防御性测试失败！代码可能破坏了核心保护机制。")
        print()
        print("建议:")
        print("  1. 查看上面的错误信息")
        print("  2. 检查是否修改了 tests/unit/defense/ 下的测试")
        print("  3. 确认代码没有破坏文件回滚、路径安全等核心功能")
    print("=" * 60)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
