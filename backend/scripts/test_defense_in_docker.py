#!/usr/bin/env python3
"""
Docker 沙箱环境中的防御性测试运行脚本

此脚本用于验证防御性测试在隔离的 Docker 环境中是否能正常运行。
主要用于 CI/CD 流程和发布前的最终验证。

使用方法:
    python scripts/test_defense_in_docker.py
    python scripts/test_defense_in_docker.py --layer=1
    python scripts/test_defense_in_docker.py --verbose
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Tuple


class DockerDefenseTester:
    """Docker 沙箱防御性测试运行器"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.backend_dir = project_root / "backend"
        self.scripts_dir = self.backend_dir / "scripts"
        self.defense_test_dir = self.backend_dir / "tests" / "unit" / "defense"

    def check_docker_available(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def check_image_exists(self, image_name: str = "omniflowai-defense-test") -> bool:
        """检查 Docker 镜像是否存在"""
        try:
            result = subprocess.run(
                ["docker", "images", "-q", image_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            return len(result.stdout.strip()) > 0
        except Exception:
            return False

    def run_tests_in_container(
        self,
        layer: str = None,
        verbose: bool = False,
        keep_container: bool = False,
        image_name: str = "omniflowai/sandbox:latest"
    ) -> Tuple[bool, str]:
        """在 Docker 容器中运行测试"""
        print(f"🐳 在 Docker 容器中运行防御性测试（镜像: {image_name}）...")

        # 挂载整个 backend 目录到 /workspace/backend
        cmd = [
            "docker", "run",
            "--rm" if not keep_container else "",
            "-v", f"{self.backend_dir}:/workspace/backend:ro",
            "-e", "PYTHONPATH=/workspace/backend",
            "-e", "TARGET_PROJECT_PATH=/tmp/test_workspace",
            "-w", "/workspace/backend",
            image_name
        ]

        # 构建 pytest 命令
        # 添加 -p no:cacheprovider 禁用缓存（只读文件系统无法写入缓存）
        pytest_cmd = ["python", "-m", "pytest", "-p", "no:cacheprovider", "tests/unit/defense"]

        if layer:
            pytest_cmd.extend(["-m", f"layer{layer}"])

        if verbose:
            pytest_cmd.extend(["-v", "--tb=long"])
        else:
            pytest_cmd.extend(["-v", "--tb=short"])

        cmd.extend(pytest_cmd)

        # 过滤空字符串
        cmd = [c for c in cmd if c]

        try:
            result = subprocess.run(
                cmd,
                capture_output=False,
                text=True,
                timeout=600  # 10 分钟超时
            )

            return result.returncode == 0, "测试完成"

        except subprocess.TimeoutExpired:
            return False, "测试超时（10分钟）"
        except Exception as e:
            return False, f"运行失败: {e}"



    def verify_test_isolation(self, image_name: str = "omniflowai/sandbox:latest") -> bool:
        """验证测试隔离性"""
        print("🔒 验证 Docker 沙箱隔离性...")

        # 检查容器内的文件系统是否隔离
        check_cmd = [
            "docker", "run", "--rm",
            "-v", f"{self.backend_dir}:/workspace/backend:ro",
            "-w", "/workspace/backend",
            image_name,
            "python", "-c",
            "import os; print('Container ID:', os.uname().nodename); print('Workspace:', os.listdir('/tmp/test_workspace') if os.path.exists('/tmp/test_workspace') else 'Not exists'); print('Backend files:', len(os.listdir('/workspace/backend')) if os.path.exists('/workspace/backend') else 'Not mounted')"
        ]

        try:
            result = subprocess.run(
                check_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                print("✅ Docker 沙箱环境正常")
                print(result.stdout)
                return True
            else:
                print("❌ Docker 沙箱环境检查失败")
                print(result.stderr)
                return False

        except Exception as e:
            print(f"❌ 隔离性检查失败: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description="在 Docker 沙箱中运行防御性测试"
    )
    parser.add_argument(
        "--layer",
        choices=["1", "2", "3", "4"],
        help="只运行特定层的测试"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细输出"
    )
    parser.add_argument(
        "--keep-container",
        action="store_true",
        help="测试后保留容器（用于调试）"
    )
    parser.add_argument(
        "--image",
        default="omniflowai/sandbox:latest",
        help="Docker 镜像名称（默认: omniflowai/sandbox:latest）"
    )

    args = parser.parse_args()

    # 获取项目根目录
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent.parent
    backend_dir = project_root / "backend"

    print("=" * 70)
    print("🛡️  Docker 沙箱防御性测试")
    print("=" * 70)
    print()

    tester = DockerDefenseTester(project_root)

    # 检查 Docker 可用性
    if not tester.check_docker_available():
        print("❌ Docker 不可用，请安装 Docker 并确保服务正在运行")
        sys.exit(1)

    print("✅ Docker 可用")
    print()

    # 检查镜像是否存在
    if not tester.check_image_exists(args.image):
        print(f"❌ Docker 镜像 '{args.image}' 不存在")
        print("请先构建镜像：")
        print(f"  docker build -t {args.image} .")
        sys.exit(1)

    print(f"✅ Docker 镜像 '{args.image}' 已存在")
    print()

    # 验证隔离性
    if not tester.verify_test_isolation(args.image):
        print("❌ Docker 沙箱隔离性验证失败")
        sys.exit(1)
    print()

    # 运行测试
    print("🧪 开始运行防御性测试...")
    print("-" * 70)

    success, message = tester.run_tests_in_container(
        layer=args.layer,
        verbose=args.verbose,
        keep_container=args.keep_container,
        image_name=args.image
    )
    if not success:
        print(f"❌ {message}")

    print("-" * 70)
    print()

    if success:
        print("✅ 所有防御性测试在 Docker 沙箱中通过！")
        print()
        print("说明：")
        print("  - 防御性测试在隔离环境中正常运行")
        print("  - 文件系统操作被正确限制在容器内")
        print("  - 测试不会影响到宿主机环境")
        sys.exit(0)
    else:
        print("❌ 防御性测试在 Docker 沙箱中失败")
        print()
        print("可能的原因：")
        print("  - 测试代码依赖宿主机特定环境")
        print("  - 文件路径硬编码了宿主机路径")
        print("  - 缺少必要的系统依赖")
        sys.exit(1)


if __name__ == "__main__":
    main()
