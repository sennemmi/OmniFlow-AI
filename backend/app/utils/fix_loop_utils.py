"""
修复循环工具函数

提供统一的修复循环状态管理和执行逻辑
"""

import logging
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
    根据错误类型执行对应的修复
    
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
    
    if fix_type == "syntax":
        # 从 logs 中提取语法错误
        error_analysis = e2e_service.analyze_errors(logs, failed_tests)
        syntax_errors = error_analysis.get("syntax_errors", [])
        
        if not syntax_errors:
            return FixResult(success=False, message="未找到语法错误")
        
        fixed = await run_syntax_fix_loop(
            syntax_errors=[err.to_dict() for err in syntax_errors],
            files_to_check=[],
            file_service=file_service,
            design_output={**design_output, "pipeline_id": pipeline_id},
            max_retries=2
        )
        
        # TODO: 需要从 fixed 中提取新的文件内容
        return FixResult(success=bool(fixed), message=f"语法修复: {len(fixed)} 个文件")
    
    elif fix_type == "import":
        error_analysis = e2e_service.analyze_errors(logs, failed_tests)
        import_errors = error_analysis.get("import_errors", [])
        
        if not import_errors:
            return FixResult(success=False, message="未找到导入错误")
        
        fixed = await run_test_import_fix_loop(
            test_files=state.test_files,
            import_errors=[e.message for e in import_errors],
            file_service=file_service,
            design_output={**design_output, "pipeline_id": pipeline_id},
            code_output={"files": state.code_files}
        )
        
        return FixResult(success=fixed, message="导入错误修复完成")
    
    elif fix_type == "repair":
        # Repair 修复需要调用 RepairerAgent
        # 这里返回失败，让调用方处理
        return FixResult(
            success=False, 
            message="Repair 类型需要调用方处理",
            new_code_files=state.code_files,
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
