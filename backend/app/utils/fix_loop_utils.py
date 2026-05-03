"""
修复循环工具函数

提供统一的修复循环状态管理和执行逻辑
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.service.e2e_test_service import E2ETestService
from app.service.sandbox_file_service import SandboxFileService
from app.utils.agent_output_utils import merge_files_content
from app.utils.repair_loop_utils import (
    run_syntax_fix_loop,
    run_test_import_fix_loop,
    run_test_syntax_fix_loop,
)

logger = logging.getLogger(__name__)


class ErrorContextBuilder:
    """
    【新增】错误上下文构建器

    根据错误类型构建不同的上下文策略：
    - SyntaxError: 仅传递出错的单个文件，且只传递出错行附近的上下文（±20行）
    - ImportError: 仅传递测试文件和被测模块文件，不传递整个项目
    - AssertionError: 当前策略，但过滤掉体积超过阈值的无关文件
    """

    def __init__(self, logs: str, state: 'FixLoopState', file_service: SandboxFileService):
        self.logs = logs
        self.state = state
        self.file_service = file_service
        self.max_file_size = 8000  # 最大文件大小阈值
        self.syntax_context_lines = 20  # SyntaxError 上下文行数

    async def build_syntax_error_context(self, syntax_errors: List[Any]) -> List[Tuple[str, str]]:
        """
        【SyntaxError 策略】仅传递出错文件的关键行（±20行）

        Args:
            syntax_errors: 语法错误列表

        Returns:
            List[Tuple[str, str]]: (文件路径, 精简内容) 列表
        """
        focused_files = []

        for error in syntax_errors:
            file_path = getattr(error, 'file', None) or error.get('file', '')
            line_no = getattr(error, 'line', None) or error.get('line', 0)

            if not file_path:
                continue

            # 读取文件内容
            read_result = await self.file_service.read_file(file_path)
            if not read_result.exists or not read_result.content:
                continue

            content = read_result.content
            lines = content.split('\n')

            # 提取出错行附近的上下文（±20行）
            start_line = max(0, line_no - self.syntax_context_lines - 1)
            end_line = min(len(lines), line_no + self.syntax_context_lines)

            focused_content = '\n'.join(lines[start_line:end_line])
            focused_content = f"# ... (文件 {file_path} 的第 {start_line+1}-{end_line} 行，共 {len(lines)} 行)\n{focused_content}\n# ..."

            focused_files.append((file_path, focused_content))
            logger.info(f"[ContextBuilder] SyntaxError 上下文: {file_path} 第 {line_no} 行附近")

        return focused_files

    async def build_import_error_context(self, import_errors: List[Any]) -> List[Dict]:
        """
        【ImportError 策略】仅传递测试文件和被测模块文件

        Args:
            import_errors: 导入错误列表

        Returns:
            List[Dict]: 精简后的文件列表
        """
        # 从导入错误中提取涉及的模块
        relevant_modules = set()

        for error in import_errors:
            error_msg = getattr(error, 'message', None) or error.get('message', '')

            # 提取导入的模块名（如 "from app.models.health import HealthStatus"）
            import_matches = re.findall(r'from\s+([\w.]+)\s+import', error_msg)
            relevant_modules.update(import_matches)

            # 提取测试文件路径
            test_file_matches = re.findall(r'File "([^"]+)"', error_msg)
            for match in test_file_matches:
                clean_path = match.replace('/workspace/backend/', '').replace('/workspace/', '').lstrip('/')
                if clean_path.endswith('.py'):
                    relevant_modules.add(clean_path.replace('/', '.').replace('.py', ''))

        # 只保留相关的代码文件
        focused_files = []
        for file_info in self.state.code_files:
            file_path = file_info.get('file_path', '')
            module_name = file_path.replace('/', '.').replace('.py', '')

            # 检查是否是相关模块
            is_relevant = any(
                module_name == rel or module_name.endswith('.' + rel.split('.')[-1])
                for rel in relevant_modules
            )

            if is_relevant:
                focused_files.append(file_info)
                logger.info(f"[ContextBuilder] ImportError 相关文件: {file_path}")

        # 如果没有找到相关文件，返回测试文件
        if not focused_files and self.state.test_files:
            return self.state.test_files

        return focused_files

    async def build_repair_context(self) -> List[Dict]:
        """
        【AssertionError 策略】过滤掉体积过大的无关文件

        Returns:
            List[Dict]: 过滤后的文件列表
        """
        focused_files = []

        for file_info in self.state.code_files:
            file_path = file_info.get('file_path', '')
            content = file_info.get('content', '')

            # 如果文件过大，进行截断
            if len(content) > self.max_file_size:
                truncated_content = content[:self.max_file_size] + f"\n\n# ... (文件已截断，共 {len(content)} 字符)"
                focused_files.append({
                    **file_info,
                    'content': truncated_content
                })
                logger.warning(f"[ContextBuilder] Repair 上下文截断: {file_path} ({len(content)} -> {self.max_file_size})")
            else:
                focused_files.append(file_info)

        return focused_files


@dataclass
class FixLoopState:
    """修复循环状态"""
    code_files: List[Dict]
    test_files: List[Dict]
    attempt: int = 0
    max_retries: int = 3
    fix_history: List[Dict] = field(default_factory=list)
    
    @property
    def all_generated_files(self) -> List[Dict]:
        """获取所有生成的文件"""
        return merge_files_content(self.code_files, self.test_files)
    
    def update_code_files(self, new_code_files: List[Dict]) -> None:
        """更新代码文件列表"""
        self.code_files = new_code_files
    
    def update_test_files(self, new_test_files: List[Dict]) -> None:
        """更新测试文件列表"""
        self.test_files = new_test_files
    
    def record_fix(self, fix_type: str, success: bool, details: Dict) -> None:
        """记录修复历史"""
        self.fix_history.append({
            "attempt": self.attempt,
            "type": fix_type,
            "success": success,
            "details": details
        })


@dataclass
class FixResult:
    """修复结果"""
    success: bool
    new_code_files: Optional[List[Dict]] = None
    new_test_files: Optional[List[Dict]] = None
    message: str = ""


async def execute_fix_by_type(
    fix_type: str,
    state: FixLoopState,
    file_service: SandboxFileService,
    design_output: Dict,
    e2e_service: E2ETestService,
    logs: str = "",
    failed_tests: List[str] = None
) -> FixResult:
    """
    【改进】根据错误类型执行对应的修复，使用错误类型感知的上下文构建策略

    Args:
        fix_type: 修复类型 (syntax, import, type, repair)
        state: 修复循环状态
        file_service: 文件服务
        design_output: 设计输出
        e2e_service: E2E 测试服务
        logs: 错误日志
        failed_tests: 失败的测试列表

    Returns:
        修复结果
    """
    if failed_tests is None:
        failed_tests = []

    pipeline_id = design_output.get("pipeline_id", 0)

    # 【新增】根据错误类型构建不同的上下文
    context_builder = ErrorContextBuilder(logs, state, file_service)

    if fix_type == "syntax":
        # 【SyntaxError 策略】仅传递出错的单个文件，且只传递出错行附近的上下文（±20行）
        logger.info("[FixLoop] 使用 SyntaxError 策略：精简上下文")

        error_analysis = e2e_service.analyze_errors(logs, failed_tests)
        syntax_errors = error_analysis.get("syntax_errors", [])

        if not syntax_errors:
            return FixResult(success=False, message="未找到语法错误")

        # 构建精简上下文：仅包含出错文件的关键行
        focused_context = await context_builder.build_syntax_error_context(syntax_errors)

        fixed = await run_syntax_fix_loop(
            syntax_errors=[err.to_dict() for err in syntax_errors],
            files_to_check=focused_context,
            file_service=file_service,
            design_output={**design_output, "pipeline_id": pipeline_id},
            max_retries=2
        )

        return FixResult(success=bool(fixed), message=f"语法修复: {len(fixed)} 个文件")

    elif fix_type == "import":
        # 【ImportError 策略】仅传递测试文件和被测模块文件，不传递整个项目
        logger.info("[FixLoop] 使用 ImportError 策略：仅传递相关模块")

        error_analysis = e2e_service.analyze_errors(logs, failed_tests)
        import_errors = error_analysis.get("import_errors", [])

        if not import_errors:
            return FixResult(success=False, message="未找到导入错误")

        # 构建精简上下文：仅包含测试文件和被测模块
        focused_context = await context_builder.build_import_error_context(import_errors)

        fixed = await run_test_import_fix_loop(
            test_files=state.test_files,
            import_errors=[e.message for e in import_errors],
            file_service=file_service,
            design_output={**design_output, "pipeline_id": pipeline_id},
            code_output={"files": focused_context}
        )

        return FixResult(success=fixed, message="导入错误修复完成")

    elif fix_type == "repair":
        # 【AssertionError 策略】当前策略，但过滤掉体积过大的无关文件
        logger.info("[FixLoop] 使用 Repair 策略：过滤大文件")

        # 构建精简上下文：过滤掉过大的文件
        focused_context = await context_builder.build_repair_context()

        # Repair 修复需要调用 RepairerAgent
        return FixResult(
            success=False,
            message="Repair 类型需要调用方处理",
            new_code_files=focused_context,
            new_test_files=state.test_files
        )

    else:
        return FixResult(success=False, message=f"未知的修复类型: {fix_type}")


def determine_fix_type(error_analysis: Dict) -> Optional[str]:
    """
    根据错误分析确定修复类型
    
    Args:
        error_analysis: 错误分析结果
        
    Returns:
        修复类型或 None
    """
    if error_analysis.get("syntax_errors"):
        return "syntax"
    elif error_analysis.get("import_errors"):
        return "import"
    elif error_analysis.get("type_errors"):
        return "type"
    else:
        return "repair"


def build_enhanced_design_output(
    design_output: Dict,
    fix_history: List[Dict],
    current_error: str
) -> Dict:
    """
    构建增强的设计输出，包含修复历史
    
    Args:
        design_output: 原始设计输出
        fix_history: 修复历史
        current_error: 当前错误信息
        
    Returns:
        增强的设计输出
    """
    enhanced = {**design_output}
    
    # 添加上一轮修复信息
    if fix_history:
        last_fix = fix_history[-1]
        enhanced["previous_fix"] = {
            "attempt": last_fix["attempt"],
            "type": last_fix["type"],
            "success": last_fix["success"]
        }
    
    # 添加当前错误上下文
    enhanced["current_error"] = current_error
    enhanced["fix_attempt_count"] = len(fix_history)
    
    return enhanced
