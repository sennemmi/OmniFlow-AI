"""
错误分析服务

提供测试日志分析、错误分类提取等功能
"""

import logging
import re
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class ErrorInfo:
    """错误信息"""
    def __init__(self, error_type: str, message: str, **kwargs):
        self.type = error_type
        self.message = message
        self.extra = kwargs
        # 将 kwargs 中的属性直接设置到实例上，方便通过 getattr 访问
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            **self.extra
        }


class ErrorAnalysisService:
    """
    错误分析服务

    职责：
    1. 从测试日志中提取各类错误
    2. 分类错误类型（语法错误、导入错误、逻辑错误、类型错误）
    3. 生成错误摘要报告
    """

    def __init__(self):
        pass

    def extract_syntax_errors(self, logs: str) -> List[ErrorInfo]:
        """从日志中提取 SyntaxError"""
        errors = []

        # 提取所有文件路径（SyntaxError 前最近的 File "..." 行）
        file_pattern = r'File "([^"]+)"'
        files = re.findall(file_pattern, logs)

        # 提取 SyntaxError 及其行号
        syntax_pattern = r'File "([^"]+)".*?line (\d+).*?SyntaxError:\s*(.+?)(?:\n|$)'
        for match in re.finditer(syntax_pattern, logs, re.MULTILINE | re.DOTALL):
            errors.append(ErrorInfo(
                error_type="SyntaxError",
                message=match.group(3).strip(),
                file=match.group(1),
                line=int(match.group(2))
            ))

        # 如果没有匹配到带文件路径的格式，尝试简单匹配
        if not errors:
            simple_pattern = r'SyntaxError:\s*(.+?)(?:\n|$)'
            for match in re.finditer(simple_pattern, logs, re.MULTILINE):
                # 尝试找到最近的文件路径
                file_path = files[-1] if files else ""
                errors.append(ErrorInfo(
                    error_type="SyntaxError",
                    message=match.group(1).strip(),
                    file=file_path,
                    line=0
                ))

        return errors

    def extract_import_errors(self, logs: str) -> List[ErrorInfo]:
        """从日志中提取 ImportError"""
        errors = []
        patterns = [
            r'ImportError:\s*(.+?)(?:\n|$)',
            r'ModuleNotFoundError:\s*(.+?)(?:\n|$)',
            r'cannot import name [\'"](\w+)[\'"]',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, logs, re.MULTILINE):
                symbol = match.group(1).strip() if match.lastindex >= 1 else None
                errors.append(ErrorInfo(
                    error_type="ImportError",
                    message=match.group(0).strip(),
                    symbol=symbol
                ))
        return errors

    def extract_logic_errors(self, logs: str, failed_tests: List[str]) -> List[ErrorInfo]:
        """从日志中提取代码逻辑错误"""
        errors = []
        for test in failed_tests:
            errors.append(ErrorInfo(
                error_type="LogicError",
                message=f"Test failed: {test}",
                test=test
            ))
        return errors

    def extract_type_errors_in_test(self, logs: str) -> List[ErrorInfo]:
        """
        提取测试文件中的 TypeError（如 datetime mock 错误）
        """
        errors = []
        type_error_pattern = r'TypeError:\s*(.+?)(?:\n|$)'
        type_error_matches = re.findall(type_error_pattern, logs)

        for error_msg in type_error_matches:
            # 检查是否是 datetime 相关的 mock 错误
            if 'datetime' in error_msg.lower() or 'utcnow' in error_msg.lower():
                errors.append(ErrorInfo(
                    error_type="TypeError",
                    message=error_msg,
                    file="test_file",
                    is_test_file=True
                ))

        return errors

    def extract_missing_symbols(self, logs: str) -> List[str]:
        """从测试日志中提取缺失的符号（ImportError）"""
        missing = set()
        for pattern in [
            r"ImportError: cannot import name '(\w+)'",
            r"cannot import name '(\w+)'",
        ]:
            missing.update(re.findall(pattern, logs))
        return list(missing)

    def is_test_import_error(self, import_errors: List[ErrorInfo]) -> bool:
        """判断导入错误是否来自测试文件"""
        return len(import_errors) > 0

    def analyze_error_summary(self, logs: str) -> Dict[str, Any]:
        """
        生成错误摘要统计

        Args:
            logs: 测试日志

        Returns:
            错误统计信息
        """
        error_patterns = {
            "AssertionError": r"AssertionError:\s*(.+?)(?:\n|$)",
            "ImportError": r"ImportError:\s*(.+?)(?:\n|$)",
            "ModuleNotFoundError": r"ModuleNotFoundError:\s*(.+?)(?:\n|$)",
            "TypeError": r"TypeError:\s*(.+?)(?:\n|$)",
            "AttributeError": r"AttributeError:\s*(.+?)(?:\n|$)",
            "NameError": r"NameError:\s*(.+?)(?:\n|$)",
        }

        error_counts = {}
        for error_type, pattern in error_patterns.items():
            matches = re.findall(pattern, logs, re.MULTILINE)
            if matches:
                error_counts[error_type] = len(matches)

        # 提取失败测试名称
        failed_tests = re.findall(r'FAILED\s+(\S+)', logs)

        # 提取 short test summary
        summary_match = re.search(
            r'={10,}\s*short test summary info\s*={10,}(.*?)(?:={10,}|$)',
            logs,
            re.DOTALL
        )
        summary = ""
        if summary_match:
            summary_lines = summary_match.group(1).strip().split('\n')
            summary = '\n'.join([line.strip() for line in summary_lines[:5] if line.strip()])

        return {
            "error_counts": error_counts,
            "failed_tests": failed_tests,
            "total_failed": len(failed_tests),
            "summary": summary
        }

    def print_preliminary_error_summary(self, logs: str, max_display: int = 10) -> str:
        """
        打印预测试错误摘要

        Args:
            logs: 测试日志
            max_display: 最多显示的失败测试数

        Returns:
            格式化的错误摘要字符串
        """
        lines = []
        lines.append("\n   [预测试] 错误信息摘要:")
        lines.append("   " + "-" * 60)

        # 错误类型统计
        error_patterns = {
            "AssertionError": r"AssertionError:\s*(.+?)(?:\n|$)",
            "ImportError": r"ImportError:\s*(.+?)(?:\n|$)",
            "ModuleNotFoundError": r"ModuleNotFoundError:\s*(.+?)(?:\n|$)",
            "TypeError": r"TypeError:\s*(.+?)(?:\n|$)",
            "AttributeError": r"AttributeError:\s*(.+?)(?:\n|$)",
            "NameError": r"NameError:\s*(.+?)(?:\n|$)",
        }

        error_counts = {}
        for error_type, pattern in error_patterns.items():
            matches = re.findall(pattern, logs, re.MULTILINE)
            if matches:
                error_counts[error_type] = len(matches)

        if error_counts:
            lines.append("   错误类型统计:")
            for error_type, count in error_counts.items():
                lines.append(f"     - {error_type}: {count} 个")

        # 失败测试列表
        failed_tests = re.findall(r'FAILED\s+(\S+)', logs)
        if failed_tests:
            lines.append(f"\n   失败测试列表 (前{max_display}个):")
            for i, test in enumerate(failed_tests[:max_display], 1):
                lines.append(f"     {i}. {test}")
            if len(failed_tests) > max_display:
                lines.append(f"     ... 还有 {len(failed_tests) - max_display} 个失败测试")

        # 错误详情示例
        lines.append(f"\n   错误详情示例:")
        for error_type, pattern in error_patterns.items():
            matches = re.findall(pattern, logs, re.MULTILINE)
            if matches:
                lines.append(f"\n   [{error_type}]:")
                for i, match in enumerate(matches[:2], 1):
                    error_msg = match.strip()[:100]
                    lines.append(f"     {i}. {error_msg}...")

        # 测试摘要
        summary_match = re.search(
            r'={10,}\s*short test summary info\s*={10,}(.*?)(?:={10,}|$)',
            logs,
            re.DOTALL
        )
        if summary_match:
            lines.append(f"\n   测试摘要:")
            summary_lines = summary_match.group(1).strip().split('\n')
            for line in summary_lines[:5]:
                line = line.strip()
                if line:
                    lines.append(f"     {line}")

        lines.append("   " + "-" * 60)
        return '\n'.join(lines)


# 单例实例
error_analysis_service = ErrorAnalysisService()
