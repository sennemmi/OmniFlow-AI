"""
错误上下文解析服务

将杂乱的 pytest 日志解析为结构化的修复指令，让 AI 直接获得"哪个文件、哪一行、什么错误"。

原则：
1. 从原始日志中提取核心错误信息
2. 结构化输出包含文件路径、行号、错误类型、修复建议
3. 按严重程度排序，优先处理关键错误
"""

import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class ErrorSeverity(Enum):
    """错误严重程度"""
    CRITICAL = "critical"    # 导入错误、语法错误等，代码无法运行
    HIGH = "high"            # 属性错误、类型错误等，功能异常
    MEDIUM = "medium"        # 测试断言失败，功能不符合预期
    LOW = "low"              # 警告、建议
    UNKNOWN = "unknown"      # 无法识别的错误


@dataclass
class ParsedError:
    """解析后的错误条目"""
    severity: ErrorSeverity
    file_path: Optional[str]
    line: Optional[int]
    error_type: str
    summary: str
    detail: str
    fix_hint: str


@dataclass
class StructuredErrorContext:
    """结构化的错误上下文"""
    type: str = "fix_task"
    category: str = ""
    errors: List[ParsedError] = field(default_factory=list)
    generated_files: List[str] = field(default_factory=list)
    strict_order: str = (
        "阅读以上 errors 列表，按 severity 从高到低逐个修复。"
        "每个修复必须直接解决对应的错误，不得修改其他不相关的代码。"
        "完成所有修复后，请输出 JSON 格式的修复结果。"
    )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 JSON 序列化）"""
        return {
            "type": self.type,
            "category": self.category,
            "errors": [
                {
                    "severity": e.severity.value,
                    "file_path": e.file_path,
                    "line": e.line,
                    "error_type": e.error_type,
                    "summary": e.summary,
                    "detail": e.detail,
                    "fix_hint": e.fix_hint
                }
                for e in self.errors
            ],
            "generated_files": self.generated_files,
            "strict_order": self.strict_order
        }


class ErrorContextParser:
    """
    错误上下文解析器

    将 pytest 输出、编译错误等解析为结构化的修复指令。
    """

    def __init__(self):
        self.parsed_errors: List[ParsedError] = []

    def parse_pytest_output(
        self,
        logs: str,
        failure_cause: Optional[str] = None,
        generated_files: Optional[List[str]] = None
    ) -> StructuredErrorContext:
        """
        解析 pytest 输出为结构化错误上下文

        Args:
            logs: pytest 原始日志
            failure_cause: 失败原因分类
            generated_files: 生成的文件列表

        Returns:
            StructuredErrorContext: 结构化的错误上下文
        """
        context = StructuredErrorContext(
            category=failure_cause or "unknown",
            generated_files=generated_files or []
        )

        # 1. 解析 ImportError / ModuleNotFoundError
        self._parse_import_errors(logs, context)

        # 2. 解析 NameError / SyntaxError / AttributeError
        self._parse_runtime_errors(logs, context)

        # 3. 解析 AssertionError（测试失败差异）
        self._parse_assertion_errors(logs, context)

        # 4. 解析 TypeError
        self._parse_type_errors(logs, context)

        # 5. 如果没有解析到任何结构化错误，回退到摘要
        if not context.errors:
            self._parse_fallback(logs, context)

        # 按严重程度排序
        severity_order = {
            ErrorSeverity.CRITICAL: 0,
            ErrorSeverity.HIGH: 1,
            ErrorSeverity.MEDIUM: 2,
            ErrorSeverity.LOW: 3,
            ErrorSeverity.UNKNOWN: 4
        }
        context.errors.sort(key=lambda e: severity_order.get(e.severity, 5))

        return context

    def _parse_import_errors(self, logs: str, context: StructuredErrorContext) -> None:
        """解析导入错误"""
        # 模式1: ImportError: cannot import name 'X' from 'Y'
        import_pattern1 = re.compile(
            r"ImportError: cannot import name ['\"](\w+)['\"] from ['\"]([^'\"]+)['\"]",
            re.MULTILINE
        )
        for match in import_pattern1.finditer(logs):
            import_name = match.group(1)
            import_source = match.group(2)

            # 尝试找到文件路径和行号
            file_match = re.search(
                rf"File \"([^\"]+)\".*line (\d+).*\n.*from {re.escape(import_source)} import",
                logs[:match.start()],
                re.MULTILINE | re.DOTALL
            )
            file_path = file_match.group(1) if file_match else None
            line_no = int(file_match.group(2)) if file_match else None

            context.errors.append(ParsedError(
                severity=ErrorSeverity.CRITICAL,
                file_path=file_path,
                line=line_no,
                error_type="ImportError",
                summary=f"导入错误: 无法从 {import_source} 导入 {import_name}",
                detail=f"模块 {import_source} 中没有找到 {import_name}",
                fix_hint=f"检查 {import_source} 中是否定义了 {import_name}，或确认导入路径是否正确。"
            ))

        # 模式2: ModuleNotFoundError: No module named 'X'
        module_pattern = re.compile(
            r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]",
            re.MULTILINE
        )
        for match in module_pattern.finditer(logs):
            module_name = match.group(1)

            # 尝试找到文件路径和行号
            file_match = re.search(
                r"File \"([^\"]+)\".*line (\d+)",
                logs[:match.start()],
                re.MULTILINE | re.DOTALL
            )
            file_path = file_match.group(1) if file_match else None
            line_no = int(file_match.group(2)) if file_match else None

            context.errors.append(ParsedError(
                severity=ErrorSeverity.CRITICAL,
                file_path=file_path,
                line=line_no,
                error_type="ModuleNotFoundError",
                summary=f"模块未找到: {module_name}",
                detail=f"Python 无法找到模块 {module_name}",
                fix_hint=f"检查模块 {module_name} 是否已安装，或确认模块路径是否正确。"
            ))

    def _parse_runtime_errors(self, logs: str, context: StructuredErrorContext) -> None:
        """解析运行时错误（NameError, SyntaxError, AttributeError）"""
        # NameError
        name_error_pattern = re.compile(
            r"NameError: name ['\"](\w+)['\"] is not defined",
            re.MULTILINE
        )
        for match in name_error_pattern.finditer(logs):
            name = match.group(1)

            file_match = re.search(
                r"File \"([^\"]+)\".*line (\d+)",
                logs[:match.start()],
                re.MULTILINE | re.DOTALL
            )
            file_path = file_match.group(1) if file_match else None
            line_no = int(file_match.group(2)) if file_match else None

            context.errors.append(ParsedError(
                severity=ErrorSeverity.CRITICAL,
                file_path=file_path,
                line=line_no,
                error_type="NameError",
                summary=f"未定义变量: {name}",
                detail=f"变量或函数 {name} 未定义",
                fix_hint=f"检查是否需要导入 {name}，或在当前作用域定义它。"
            ))

        # SyntaxError
        syntax_pattern = re.compile(
            r"SyntaxError: (.+)\n.*\n.*File \"([^\"]+)\".*line (\d+)",
            re.MULTILINE | re.DOTALL
        )
        for match in syntax_pattern.finditer(logs):
            error_detail = match.group(1)
            file_path = match.group(2)
            line_no = int(match.group(3))

            context.errors.append(ParsedError(
                severity=ErrorSeverity.CRITICAL,
                file_path=file_path,
                line=line_no,
                error_type="SyntaxError",
                summary=f"语法错误: {error_detail}",
                detail=error_detail,
                fix_hint="检查 Python 语法，确保括号、缩进、冒号等正确。"
            ))

        # AttributeError
        attr_pattern = re.compile(
            r"AttributeError: ['\"]?([^'\"\s]+)['\"]?",
            re.MULTILINE
        )
        for match in attr_pattern.finditer(logs):
            error_detail = match.group(1)

            file_match = re.search(
                r"File \"([^\"]+)\".*line (\d+)",
                logs[:match.start()],
                re.MULTILINE | re.DOTALL
            )
            file_path = file_match.group(1) if file_match else None
            line_no = int(file_match.group(2)) if file_match else None

            context.errors.append(ParsedError(
                severity=ErrorSeverity.HIGH,
                file_path=file_path,
                line=line_no,
                error_type="AttributeError",
                summary=f"属性错误: {error_detail}",
                detail=error_detail,
                fix_hint="检查对象类型是否正确，或确认属性/方法名是否拼写正确。"
            ))

    def _parse_assertion_errors(self, logs: str, context: StructuredErrorContext) -> None:
        """解析测试断言错误"""
        # FAILED 测试名 - 改进版本，尝试提取文件路径
        failed_pattern = re.compile(
            r"FAILED\s+(\S+)\s+-\s+(.+)",
            re.MULTILINE
        )
        for match in failed_pattern.finditer(logs):
            test_name = match.group(1)
            assertion_detail = match.group(2)

            # 尝试从测试名中提取文件路径
            # 测试名格式: tests/test_file.py::test_function
            file_path = None
            if "::" in test_name:
                file_part = test_name.split("::")[0]
                # 转换为相对路径
                if file_part.startswith("tests/"):
                    file_path = file_part
                else:
                    file_path = f"tests/{file_part}"

            # 尝试在日志中找到对应的源文件（被测代码）
            source_file = None
            source_line = None

            # 从 generated_files 中推断源文件（非测试文件）
            if context.generated_files:
                for gf in context.generated_files:
                    if gf.endswith(".py") and not gf.startswith("test_") and "tests/" not in gf:
                        source_file = gf
                        break

            # 如果没有找到，尝试从 where 子句提取函数名
            if not source_file and "where" in assertion_detail:
                where_match = re.search(r"where\s+(\S+)\s*=", assertion_detail)
                if where_match:
                    func_call = where_match.group(1)
                    func_name = func_call.split("(")[0] if "(" in func_call else func_call
                    # 再次从 generated_files 中查找包含该函数的文件
                    if context.generated_files:
                        for gf in context.generated_files:
                            if gf.endswith(".py") and not gf.startswith("test_"):
                                source_file = gf
                                break

            # 使用源文件路径（优先）或测试文件路径
            final_file_path = source_file if source_file else file_path

            context.errors.append(ParsedError(
                severity=ErrorSeverity.MEDIUM,
                file_path=final_file_path,
                line=source_line,
                error_type="AssertionError",
                summary=f"测试失败: {test_name}",
                detail=assertion_detail,
                fix_hint=f"检查 {test_name} 对应的功能实现，确保满足断言条件。"
            ))

        # AssertionError with details
        assertion_pattern = re.compile(
            r"AssertionError:\s*(.+?)(?=\n\n|\nFAILED|$)",
            re.MULTILINE | re.DOTALL
        )
        for match in assertion_pattern.finditer(logs):
            detail = match.group(1).strip()
            if len(detail) > 200:
                detail = detail[:200] + "..."

            # 避免重复添加
            if not any(e.detail == detail for e in context.errors):
                context.errors.append(ParsedError(
                    severity=ErrorSeverity.MEDIUM,
                    file_path=None,
                    line=None,
                    error_type="AssertionError",
                    summary="断言失败",
                    detail=detail,
                    fix_hint="检查测试断言条件，确保实现逻辑正确。"
                ))

    def _parse_type_errors(self, logs: str, context: StructuredErrorContext) -> None:
        """解析类型错误"""
        type_pattern = re.compile(
            r"TypeError:\s*(.+?)(?=\n\n|\nFAILED|$)",
            re.MULTILINE | re.DOTALL
        )
        for match in type_pattern.finditer(logs):
            detail = match.group(1).strip()
            if len(detail) > 200:
                detail = detail[:200] + "..."

            file_match = re.search(
                r"File \"([^\"]+)\".*line (\d+)",
                logs[:match.start()],
                re.MULTILINE | re.DOTALL
            )
            file_path = file_match.group(1) if file_match else None
            line_no = int(file_match.group(2)) if file_match else None

            context.errors.append(ParsedError(
                severity=ErrorSeverity.HIGH,
                file_path=file_path,
                line=line_no,
                error_type="TypeError",
                summary=f"类型错误: {detail}",
                detail=detail,
                fix_hint="检查函数参数类型和数量是否正确。"
            ))

    def _parse_fallback(self, logs: str, context: StructuredErrorContext) -> None:
        """回退解析：当无法识别具体错误时"""
        # 提取关键摘要（尾部 2000 字符）
        summary = logs[-2000:] if len(logs) > 2000 else logs

        context.errors.append(ParsedError(
            severity=ErrorSeverity.UNKNOWN,
            file_path=None,
            line=None,
            error_type="Unknown",
            summary="测试运行失败，未能自动解析错误详情",
            detail="请查看以下关键摘要",
            fix_hint=summary
        ))


# 便捷函数
def parse_error_context(
    logs: str,
    failure_cause: Optional[str] = None,
    generated_files: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    便捷函数：解析错误上下文

    Args:
        logs: pytest 原始日志
        failure_cause: 失败原因分类
        generated_files: 生成的文件列表

    Returns:
        Dict[str, Any]: 结构化的错误上下文字典
    """
    parser = ErrorContextParser()
    context = parser.parse_pytest_output(logs, failure_cause, generated_files)
    return context.to_dict()
