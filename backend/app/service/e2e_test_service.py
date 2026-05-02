"""
端到端测试服务

整合 E2E 测试流程中的各类验证和分析功能
"""

import logging
import re
from typing import Dict, List, Optional, Any, Tuple

from app.service.sandbox_file_service import SandboxFileService
from app.service.code_validation_service import CodeValidationService, SyntaxErrorInfo
from app.service.error_analysis_service import ErrorAnalysisService, ErrorInfo
from app.service.mock_extraction_service import MockExtractionService, MockTarget
from app.service.layered_test_runner import LayeredTestRunner, LayeredTestResult
from app.core.contract_checker import verify_contract

logger = logging.getLogger(__name__)


class E2ETestService:
    """
    端到端测试服务

    职责：
    1. 整合代码验证、错误分析、mock 提取等功能
    2. 提供统一的 E2E 测试辅助方法
    3. 协调各服务的调用
    """

    def __init__(
        self,
        code_validation_service: Optional[CodeValidationService] = None,
        error_analysis_service: Optional[ErrorAnalysisService] = None,
        mock_extraction_service: Optional[MockExtractionService] = None
    ):
        self.code_validation = code_validation_service or CodeValidationService()
        self.error_analysis = error_analysis_service or ErrorAnalysisService()
        self.mock_extraction = mock_extraction_service or MockExtractionService()

    async def validate_code_syntax(
        self,
        code_files: List[Dict],
        file_service: SandboxFileService
    ) -> List[SyntaxErrorInfo]:
        """
        验证代码语法

        Args:
            code_files: 代码文件列表
            file_service: 文件服务

        Returns:
            语法错误列表
        """
        return await self.code_validation.check_syntax_with_py_compile(
            code_files, file_service
        )

    async def validate_test_imports(
        self,
        test_files: List[Dict],
        file_service: SandboxFileService
    ) -> List[str]:
        """
        验证测试文件导入

        Args:
            test_files: 测试文件列表
            file_service: 文件服务

        Returns:
            导入错误列表
        """
        return await self.code_validation.validate_test_imports(
            test_files, file_service
        )

    def extract_mock_targets(
        self,
        symbol_name: str,
        module_path: str,
        code_files: List[Dict],
        external_libs: Optional[List[str]] = None
    ) -> List[MockTarget]:
        """
        提取 mock 目标

        Args:
            symbol_name: 符号名称
            module_path: 模块路径
            code_files: 代码文件列表
            external_libs: 外部库列表

        Returns:
            Mock 目标列表
        """
        return self.mock_extraction.extract_mock_targets(
            symbol_name, module_path, code_files, external_libs
        )

    async def verify_contract(
        self,
        file_service: SandboxFileService,
        code_files: List[Dict],
        interface_specs: List[Dict]
    ) -> List[str]:
        """
        验证接口契约

        Args:
            file_service: 文件服务
            code_files: 代码文件列表
            interface_specs: 接口规范列表

        Returns:
            缺失的符号列表
        """
        # 构建 code_files 字典
        code_files_dict = {}
        for f in code_files:
            fp = f.get("file_path", "")
            content = f.get("content", "")
            change_type = f.get("change_type", "")

            if not fp:
                continue

            normalized_fp = fp.replace("backend/", "").replace("backend\\", "")

            if change_type == "add" and content:
                code_files_dict[normalized_fp] = content
            elif change_type == "modify":
                read_res = await file_service.read_file(normalized_fp)
                if read_res.exists:
                    code_files_dict[normalized_fp] = read_res.content
                elif content:
                    code_files_dict[normalized_fp] = content
            else:
                if content:
                    code_files_dict[normalized_fp] = content

        # 对于 interface_specs 中提到的文件，如果不在 code_files_dict 中，尝试从沙箱读取
        for spec in interface_specs:
            module = spec.get("module", "")
            if not module:
                continue

            normalized_module = module.replace("backend/", "").replace("backend\\", "")
            if not normalized_module.endswith(".py"):
                normalized_module += ".py"

            if normalized_module not in code_files_dict:
                read_res = await file_service.read_file(normalized_module)
                if read_res.exists:
                    code_files_dict[normalized_module] = read_res.content

        # 调用后端的契约检查函数
        return verify_contract(code_files_dict, interface_specs)

    def analyze_errors(
        self,
        logs: str,
        failed_tests: Optional[List[str]] = None
    ) -> Dict[str, List[ErrorInfo]]:
        """
        分析错误日志

        Args:
            logs: 测试日志
            failed_tests: 失败的测试列表

        Returns:
            分类的错误信息
        """
        if failed_tests is None:
            failed_tests = []

        return {
            "syntax_errors": self.error_analysis.extract_syntax_errors(logs),
            "import_errors": self.error_analysis.extract_import_errors(logs),
            "logic_errors": self.error_analysis.extract_logic_errors(logs, failed_tests),
            "type_errors": self.error_analysis.extract_type_errors_in_test(logs)
        }

    def extract_missing_symbols(self, logs: str) -> List[str]:
        """
        从日志中提取缺失符号

        Args:
            logs: 测试日志

        Returns:
            缺失的符号列表
        """
        return self.error_analysis.extract_missing_symbols(logs)

    def print_error_summary(self, logs: str, max_display: int = 10) -> str:
        """
        打印错误摘要

        Args:
            logs: 测试日志
            max_display: 最多显示的失败测试数

        Returns:
            格式化的错误摘要
        """
        return self.error_analysis.print_preliminary_error_summary(logs, max_display)

    async def run_layered_tests(
        self,
        pipeline_id: int,
        generated_files: List[Dict[str, Any]],
        file_service: SandboxFileService,
        timeout: int = 120
    ) -> LayeredTestResult:
        """
        运行分层测试

        Args:
            pipeline_id: Pipeline ID
            generated_files: 生成的文件列表
            file_service: 文件服务
            timeout: 超时时间

        Returns:
            分层测试结果
        """
        return await LayeredTestRunner.run(
            workspace_path="/workspace",
            new_files=generated_files,
            sandbox_port=None,
            timeout=timeout,
            file_service=file_service
        )

    def build_missing_specs_prompt(
        self,
        missing_syms: List[str],
        interface_specs: List[Dict]
    ) -> List[Dict]:
        """
        根据缺失符号列表，从 interface_specs 中提取对应的完整契约条目

        Args:
            missing_syms: 缺失符号列表
            interface_specs: 接口规范列表

        Returns:
            命中的契约条目列表
        """
        if not missing_syms:
            return []

        missing_specs = []
        for sym_entry in missing_syms:
            # 解析 "symbol_name in module_path" 格式
            parts = sym_entry.split(" in ")
            symbol_name = parts[0].strip()
            module_path = parts[-1].strip() if len(parts) > 1 else ""

            # 在 interface_specs 中查找匹配的完整条目
            found = False
            for spec in interface_specs:
                spec_name = spec.get("symbol_name", "")
                spec_module = spec.get("module", "")
                spec_module_clean = spec_module.replace(".py", "").replace("\\", "/")
                module_clean = module_path.replace(".py", "").replace("\\", "/")
                if spec_name == symbol_name and spec_module_clean.rstrip("/") == module_clean.rstrip("/"):
                    missing_specs.append(spec)
                    found = True
                    break

            if not found:
                # 模糊匹配：只要符号名一致就纳入
                for spec in interface_specs:
                    if spec.get("symbol_name", "") == symbol_name:
                        missing_specs.append(spec)
                        break

        return missing_specs

    async def run_preliminary_test(
        self,
        pipeline_id: int,
        test_files: List[Dict],
        file_service: SandboxFileService,
        sandbox_manager = None
    ) -> Dict[str, Any]:
        """
        预测试：快速运行新测试

        Args:
            pipeline_id: Pipeline ID
            test_files: 测试文件列表
            file_service: 文件服务
            sandbox_manager: 沙箱管理器（可选，如果不提供则尝试导入）

        Returns:
            测试结果
        """
        if sandbox_manager is None:
            from app.service.sandbox_manager import sandbox_manager

        if not test_files:
            return {"success": True, "logs": "", "failed_tests": [], "error": None}

        # 构建测试路径
        test_paths = []
        for tf in test_files:
            fp = tf.get("file_path", "")
            if fp:
                if "tests/ai_generated" in fp:
                    clean_path = fp
                else:
                    filename = fp.split("/")[-1]
                    clean_path = f"backend/tests/ai_generated/{filename}"
                test_paths.append(clean_path)

        if not test_paths:
            return {"success": True, "logs": "", "failed_tests": [], "error": None}

        test_path_str = " ".join(test_paths)

        try:
            exec_result = await sandbox_manager.exec(
                pipeline_id,
                f"cd /workspace && PYTHONPATH=/workspace/backend python -m pytest {test_path_str} -v --tb=short --color=no 2>&1",
                timeout=120
            )

            logs = exec_result.stdout + "\n" + exec_result.stderr
            success = exec_result.exit_code == 0

            failed_tests = re.findall(r'FAILED\s+(\S+)', logs)

            return {
                "success": success,
                "logs": logs,
                "failed_tests": failed_tests,
                "error": None if success else f"{len(failed_tests)} 个测试失败"
            }

        except Exception as e:
            return {
                "success": False,
                "logs": str(e),
                "failed_tests": [],
                "error": str(e)
            }


# 单例实例
e2e_test_service = E2ETestService()
