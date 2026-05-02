"""
自动修复服务

提供 Ruff 自动修复功能
"""

import logging
import subprocess
from typing import Any, Dict

from app.core.config import settings

logger = logging.getLogger(__name__)


class AutoHealService:
    """
    自动修复服务

    职责：
    1. 调用 Ruff 进行代码检查和自动修复
    2. 调用 Ruff 进行代码格式化
    """

    def __init__(self):
        """初始化自动修复服务"""
        self.ruff_available = self._check_ruff_available()

    def _check_ruff_available(self) -> bool:
        """检查 Ruff 是否可用"""
        try:
            result = subprocess.run(
                ["ruff", "--version"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def auto_heal(self, project_root: str) -> Dict[str, Any]:
        """
        调用 Ruff 进行静默修复 - Linter-based Auto-healing

        修复内容：
        - 未使用的 import
        - 代码格式化
        - 简单的语法问题

        Args:
            project_root: 项目根目录路径

        Returns:
            Dict: 修复结果统计
        """
        result = {
            "success": True,
            "check_fixed": 0,
            "format_fixed": 0,
            "errors": []
        }

        if not self.ruff_available:
            logger.debug("Ruff not found, skipping auto-heal")
            result["success"] = False
            result["errors"].append("ruff not installed")
            return result

        try:
            # 修复未使用的 import、简单语法问题等
            check_result = subprocess.run(
                ["ruff", "check", "--fix", project_root],
                capture_output=True,
                text=True,
                timeout=60
            )
            result["check_fixed"] = len([line for line in check_result.stdout.split("\n") if line.strip()])
            if check_result.returncode != 0 and check_result.stderr:
                result["errors"].append(f"ruff check error: {check_result.stderr[:200]}")

            # 代码格式化
            format_result = subprocess.run(
                ["ruff", "format", project_root],
                capture_output=True,
                text=True,
                timeout=60
            )
            result["format_fixed"] = len([line for line in format_result.stdout.split("\n") if line.strip()])
            if format_result.returncode != 0 and format_result.stderr:
                result["errors"].append(f"ruff format error: {format_result.stderr[:200]}")

            logger.info(f"Ruff auto-heal completed: {result}")

        except subprocess.TimeoutExpired:
            logger.warning("Ruff auto-heal timeout")
            result["success"] = False
            result["errors"].append("timeout")
        except Exception as e:
            logger.warning(f"Ruff auto-heal failed: {e}")
            result["success"] = False
            result["errors"].append(str(e))

        return result

    def check_code(self, file_path: str) -> Dict[str, Any]:
        """
        检查代码问题（不修复）

        Args:
            file_path: 文件路径

        Returns:
            Dict: 检查结果
        """
        result = {
            "success": True,
            "issues": [],
            "errors": []
        }

        if not self.ruff_available:
            result["success"] = False
            result["errors"].append("ruff not installed")
            return result

        try:
            check_result = subprocess.run(
                ["ruff", "check", file_path],
                capture_output=True,
                text=True,
                timeout=30
            )

            # 解析输出
            for line in check_result.stdout.split("\n"):
                if line.strip() and ":" in line:
                    result["issues"].append(line.strip())

            if check_result.returncode != 0 and check_result.stderr:
                result["errors"].append(check_result.stderr[:200])

        except Exception as e:
            result["success"] = False
            result["errors"].append(str(e))

        return result

    def format_code(self, file_path: str) -> Dict[str, Any]:
        """
        格式化代码

        Args:
            file_path: 文件路径

        Returns:
            Dict: 格式化结果
        """
        result = {
            "success": True,
            "formatted": False,
            "errors": []
        }

        if not self.ruff_available:
            result["success"] = False
            result["errors"].append("ruff not installed")
            return result

        try:
            format_result = subprocess.run(
                ["ruff", "format", file_path],
                capture_output=True,
                text=True,
                timeout=30
            )

            result["formatted"] = format_result.returncode == 0

            if format_result.returncode != 0 and format_result.stderr:
                result["errors"].append(format_result.stderr[:200])

        except Exception as e:
            result["success"] = False
            result["errors"].append(str(e))

        return result


# 单例实例
auto_heal = AutoHealService()
