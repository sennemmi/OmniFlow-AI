"""
第三层：代码-测试契约防线（防止接口不匹配导致的 ImportError）

这是新增的一层防御，确保：
1. CoderAgent 必须实现 DesignerAgent 声明的所有接口
2. TesterAgent 只能测试契约中声明的接口
3. 在运行测试前进行前置契约检查，实现快速失败

测试列表：
1. test_interface_specs_validation - 接口契约验证测试
2. test_missing_symbol_detection - 缺失符号检测测试
3. test_contract_checker_fast_fail - 契约检查快速失败测试
4. test_test_import_violation_detection - 测试导入违规检测测试
"""

import pytest

pytestmark = [pytest.mark.defense, pytest.mark.layer3]
import ast
from typing import Dict, Any, List, Set
from unittest.mock import MagicMock, patch

from app.core.contract_checker import (
    extract_defined_symbols,
    extract_imported_symbols,
    verify_contract,
    verify_test_imports,
    check_contract_before_test,
    ContractViolationError,
)
from app.agents.schemas import InterfaceSpec, ArchitectOutput, DesignerOutput


class TestInterfaceSpecsValidation:
    """
    用例: 验证 DesignerOutput 中的 interface_specs 是否包含必需的字段。
    目的: 确保代码-测试契约的完整性。
    """

    def test_interface_spec_required_fields(self):
        """测试 InterfaceSpec 包含所有必需字段"""
        spec = InterfaceSpec(
            symbol_name="check_health",
            module="app/api/v1/health.py",
            signature="async def check_health() -> dict",
            expected_behavior="返回服务健康状态",
            is_async=True,
            return_type="dict",
            return_fields=[
                {"name": "status", "type": "str", "description": "健康状态", "required": True},
                {"name": "timestamp", "type": "str", "description": "时间戳", "required": True}
            ]
        )

        assert spec.symbol_name == "check_health"
        assert spec.module == "app/api/v1/health.py"
        assert spec.signature == "async def check_health() -> dict"
        assert spec.expected_behavior == "返回服务健康状态"
        assert spec.is_async is True
        assert spec.return_type == "dict"

    def test_designer_output_includes_interface_specs(self):
        """测试 DesignerOutput 包含 interface_specs 字段"""
        output = DesignerOutput(
            technical_design="测试设计",
            interface_specs=[
                InterfaceSpec(
                    symbol_name="get_user",
                    module="app/service/user.py",
                    signature="def get_user(user_id: int) -> User",
                    expected_behavior="根据ID获取用户",
                    return_type="User"
                )
            ]
        )

        assert len(output.interface_specs) == 1
        assert output.interface_specs[0].symbol_name == "get_user"

    def test_architect_output_includes_acceptance_criteria(self):
        """测试 ArchitectOutput 包含 acceptance_criteria 字段"""
        output = ArchitectOutput(
            feature_description="实现用户管理功能",
            affected_files=["app/api/v1/users.py"],
            estimated_effort="2小时",
            acceptance_criteria=[
                "必须实现 create_user 函数",
                "API 返回 201 状态码"
            ]
        )

        assert len(output.acceptance_criteria) == 2
        assert "create_user" in output.acceptance_criteria[0]


class TestMissingSymbolDetection:
    """
    用例: 模拟 CoderAgent 生成的代码缺少 DesignerAgent 声明的函数，
    测试 extract_missing_symbols 能否正确识别缺失的符号。
    目的: 在测试运行前发现接口不匹配问题。
    """

    def test_detect_missing_function(self):
        """测试检测缺失的函数"""
        # 模拟生成的代码（缺少声明的函数）
        code_files = {
            "app/api/v1/health.py": """
async def check_database():
    return {"status": "ok"}
"""  # 缺少 check_health 函数
        }

        # 契约规范要求实现 check_health
        interface_specs = [
            {
                "symbol_name": "check_health",
                "module": "app/api/v1/health.py",
                "signature": "async def check_health() -> dict",
                "expected_behavior": "返回健康状态"
            },
            {
                "symbol_name": "check_database",
                "module": "app/api/v1/health.py",
                "signature": "async def check_database() -> dict",
                "expected_behavior": "返回数据库状态"
            }
        ]

        missing = verify_contract(code_files, interface_specs)

        # 应该检测到 check_health 缺失
        assert len(missing) == 1
        assert "check_health" in missing[0]

    def test_detect_missing_class(self):
        """测试检测缺失的类"""
        code_files = {
            "app/service/user.py": """
def get_user(user_id: int):
    pass
"""  # 缺少 UserService 类
        }

        interface_specs = [
            {
                "symbol_name": "UserService",
                "module": "app/service/user.py",
                "signature": "class UserService:",
                "expected_behavior": "用户服务类"
            },
            {
                "symbol_name": "get_user",
                "module": "app/service/user.py",
                "signature": "def get_user(user_id: int)",
                "expected_behavior": "获取用户"
            }
        ]

        missing = verify_contract(code_files, interface_specs)

        # 应该检测到 UserService 类缺失
        assert len(missing) == 1
        assert "UserService" in missing[0]

    def test_all_symbols_present_passes(self):
        """测试所有符号都存在时通过检查"""
        code_files = {
            "app/api/v1/items.py": """
from typing import List

async def list_items() -> List[dict]:
    return []

async def create_item(data: dict) -> dict:
    return {"id": 1, **data}
"""
        }

        interface_specs = [
            {
                "symbol_name": "list_items",
                "module": "app/api/v1/items.py",
                "signature": "async def list_items() -> List[dict]",
                "expected_behavior": "列出所有项目"
            },
            {
                "symbol_name": "create_item",
                "module": "app/api/v1/items.py",
                "signature": "async def create_item(data: dict) -> dict",
                "expected_behavior": "创建新项目"
            }
        ]

        missing = verify_contract(code_files, interface_specs)

        # 不应该有缺失
        assert len(missing) == 0

    def test_detect_missing_file(self):
        """测试检测缺失的文件"""
        code_files = {}  # 空文件列表

        interface_specs = [
            {
                "symbol_name": "process_data",
                "module": "app/service/processor.py",
                "signature": "def process_data(data: dict) -> dict",
                "expected_behavior": "处理数据"
            }
        ]

        missing = verify_contract(code_files, interface_specs)

        # 应该检测到文件缺失
        assert len(missing) == 1
        assert "file missing" in missing[0]


class TestContractCheckerFastFail:
    """
    用例: 在测试运行前执行契约检查，如果代码不满足契约立即失败，
    不进入耗时的 pytest 执行阶段。
    目的: 实现快速失败（fail-fast），节省算力。
    """

    def test_contract_check_fails_fast_on_missing_symbols(self):
        """测试契约检查在符号缺失时快速失败"""
        design_output = {
            "technical_design": "测试设计",
            "interface_specs": [
                {
                    "symbol_name": "required_function",
                    "module": "app/test.py",
                    "signature": "def required_function()",
                    "expected_behavior": "必须实现的函数"
                }
            ]
        }

        # 代码中缺少必需的函数
        code_files = {
            "app/test.py": "# 空文件，没有实现 required_function"
        }

        result = check_contract_before_test(design_output, code_files)

        assert result["success"] is False
        assert result["type"] == "missing_implementation"
        assert len(result["violations"]) == 1

    def test_contract_check_passes_when_all_implemented(self):
        """测试所有接口实现时契约检查通过"""
        design_output = {
            "technical_design": "测试设计",
            "interface_specs": [
                {
                    "symbol_name": "health_check",
                    "module": "app/health.py",
                    "signature": "def health_check() -> dict",
                    "expected_behavior": "健康检查"
                }
            ]
        }

        code_files = {
            "app/health.py": """
def health_check() -> dict:
    return {"status": "healthy"}
"""
        }

        result = check_contract_before_test(design_output, code_files)

        assert result["success"] is True
        assert len(result["violations"]) == 0

    def test_contract_check_skips_when_no_specs(self):
        """测试没有契约规范时跳过检查"""
        design_output = {
            "technical_design": "测试设计"
            # 没有 interface_specs
        }

        code_files = {"app/test.py": "# any content"}

        result = check_contract_before_test(design_output, code_files)

        assert result["success"] is True
        assert len(result["violations"]) == 0


class TestTestImportViolationDetection:
    """
    用例: 验证 TesterAgent 生成的测试是否只导入了契约中声明的符号。
    目的: 防止测试导入未定义的函数导致 ImportError。
    """

    def test_detect_test_importing_undefined_symbol(self):
        """测试检测测试文件导入未定义的符号"""
        test_content = """
from app.service.user import UserService, get_user, undefined_helper

# 测试使用了未定义的 undefined_helper
"""

        interface_specs = [
            {
                "symbol_name": "UserService",
                "module": "app/service/user.py",
                "signature": "class UserService",
                "expected_behavior": "用户服务"
            },
            {
                "symbol_name": "get_user",
                "module": "app/service/user.py",
                "signature": "def get_user(user_id: int)",
                "expected_behavior": "获取用户"
            }
            # 注意：undefined_helper 不在契约中
        ]

        violations = verify_test_imports(test_content, {}, interface_specs)

        # 应该检测到 undefined_helper 违规导入
        assert len(violations) == 1
        assert "undefined_helper" in violations[0]

    def test_allow_importing_contracted_symbols(self):
        """测试允许导入契约中声明的符号"""
        test_content = """
from app.api.v1.health import check_health, check_database

async def test_health_check():
    result = await check_health()
    assert result["status"] == "ok"
"""

        interface_specs = [
            {
                "symbol_name": "check_health",
                "module": "app/api/v1/health.py",
                "signature": "async def check_health() -> dict",
                "expected_behavior": "健康检查"
            },
            {
                "symbol_name": "check_database",
                "module": "app/api/v1/health.py",
                "signature": "async def check_database() -> dict",
                "expected_behavior": "数据库检查"
            }
        ]

        violations = verify_test_imports(test_content, {}, interface_specs)

        # 不应该有违规
        assert len(violations) == 0

    def test_contract_check_detects_test_violations(self):
        """测试契约检查能检测测试文件的导入违规"""
        design_output = {
            "interface_specs": [
                {
                    "symbol_name": "public_function",
                    "module": "app/module.py",
                    "signature": "def public_function()",
                    "expected_behavior": "公开函数"
                }
            ]
        }

        code_files = {
            "app/module.py": "def public_function(): pass"
        }

        test_files = {
            "tests/test_module.py": """
from app.module import public_function, _private_function

# 测试导入了一个私有函数，不在契约中
"""
        }

        result = check_contract_before_test(design_output, code_files, test_files)

        assert result["success"] is False
        assert result["type"] == "test_import_violation"


class TestExtractDefinedSymbols:
    """测试 extract_defined_symbols 函数"""

    def test_extract_function_definitions(self):
        """测试提取函数定义"""
        code = """
def public_function():
    pass

async def async_function():
    pass

def _private_function():
    pass
"""
        symbols = extract_defined_symbols(code)

        assert "public_function" in symbols
        assert "async_function" in symbols
        assert "_private_function" not in symbols  # 私有函数被跳过

    def test_extract_class_definitions(self):
        """测试提取类定义"""
        code = """
class PublicClass:
    pass

class _PrivateClass:
    pass
"""
        symbols = extract_defined_symbols(code)

        assert "PublicClass" in symbols
        assert "_PrivateClass" not in symbols  # 私有类被跳过

    def test_handle_syntax_error(self):
        """测试处理语法错误"""
        code = "def broken(:"  # 语法错误
        symbols = extract_defined_symbols(code)

        assert len(symbols) == 0  # 返回空集合


class TestExtractImportedSymbols:
    """测试 extract_imported_symbols 函数"""

    def test_extract_from_imports(self):
        """测试提取 from ... import ..."""
        code = """
from app.models.user import User, UserCreate
from app.core.config import settings
"""
        imports = extract_imported_symbols(code)

        assert "app.models.user" in imports
        assert "User" in imports["app.models.user"]
        assert "UserCreate" in imports["app.models.user"]
        assert "settings" in imports["app.core.config"]

    def test_skip_wildcard_imports(self):
        """测试跳过通配符导入"""
        code = "from app.models import *"
        imports = extract_imported_symbols(code)

        # 通配符导入应该被跳过
        assert len(imports.get("app.models", set())) == 0


class TestContractViolationError:
    """测试 ContractViolationError 异常"""

    def test_contract_violation_error_with_symbols(self):
        """测试带有缺失符号的契约违反错误"""
        missing = ["func1", "func2"]
        error = ContractViolationError("Missing symbols", missing)

        assert str(error) == "Missing symbols"
        assert error.missing_symbols == missing


class TestPreContractCheckInMultiAgentCoordinator:
    """
    用例: 验证 MultiAgentCoordinator.execute_parallel 中的前置契约检查。
    目的: 确保在测试生成前验证代码是否实现了所有契约符号。
    """

    def test_pre_contract_check_blocks_test_generation_on_missing_symbols(self):
        """测试前置契约检查在符号缺失时阻止测试生成"""
        from unittest.mock import AsyncMock, MagicMock

        # 模拟设计输出，包含 interface_specs
        design_output = {
            "technical_design": "实现健康检查API",
            "interface_specs": [
                {
                    "symbol_name": "check_health",
                    "module": "app/api/v1/health.py",
                    "signature": "async def check_health() -> dict",
                    "expected_behavior": "返回健康状态"
                },
                {
                    "symbol_name": "check_database",
                    "module": "app/api/v1/health.py",
                    "signature": "async def check_database() -> dict",
                    "expected_behavior": "返回数据库状态"
                }
            ]
        }

        # 模拟代码输出（缺少 check_database）
        code_output = {
            "files": [
                {
                    "file_path": "backend/app/api/v1/health.py",
                    "change_type": "modify",
                    "content": "async def check_health(): return {'status': 'ok'}"
                }
            ]
        }

        # 验证契约检查能检测到缺失符号
        code_files_dict = {
            "backend/app/api/v1/health.py": "async def check_health(): return {'status': 'ok'}"
        }

        missing = verify_contract(code_files_dict, design_output["interface_specs"])

        # 应该检测到 check_database 缺失
        assert len(missing) == 1
        assert "check_database" in missing[0]

    def test_pre_contract_check_passes_when_all_symbols_implemented(self):
        """测试所有符号实现时前置契约检查通过"""
        design_output = {
            "technical_design": "实现健康检查API",
            "interface_specs": [
                {
                    "symbol_name": "check_health",
                    "module": "app/api/v1/health.py",
                    "signature": "async def check_health() -> dict",
                    "expected_behavior": "返回健康状态"
                }
            ]
        }

        # 代码实现了所有契约符号
        code_files_dict = {
            "backend/app/api/v1/health.py": """
async def check_health() -> dict:
    return {"status": "healthy"}
"""
        }

        missing = verify_contract(code_files_dict, design_output["interface_specs"])

        # 不应该有缺失
        assert len(missing) == 0


class TestTesterAgentReceivesInterfaceSpecs:
    """
    用例: 验证 TesterAgent 是否正确接收和使用 interface_specs。
    目的: 确保 TesterAgent 只能测试契约中声明的符号。
    """

    def test_tester_agent_builds_allowed_imports_from_interface_specs(self):
        """测试 TesterAgent 从 interface_specs 构建允许导入列表"""
        from app.agents.tester import tester_agent

        design_output = {
            "technical_design": "测试设计",
            "interface_specs": [
                {
                    "symbol_name": "get_user",
                    "module": "app/service/user.py",
                    "signature": "def get_user(user_id: int) -> User",
                    "expected_behavior": "获取用户"
                },
                {
                    "symbol_name": "create_user",
                    "module": "app/service/user.py",
                    "signature": "def create_user(data: dict) -> User",
                    "expected_behavior": "创建用户"
                }
            ]
        }

        # 调用 _build_allowed_imports_section 方法
        allowed_imports_section = tester_agent._build_allowed_imports_section(design_output)

        # 验证生成的提示包含契约符号
        assert "get_user" in allowed_imports_section
        assert "create_user" in allowed_imports_section
        assert "app.service.user" in allowed_imports_section
        assert "【测试生成规则 - 只能测试契约声明的符号】" in allowed_imports_section

    def test_tester_agent_allows_all_imports_when_no_interface_specs(self):
        """测试没有 interface_specs 时不限制导入"""
        from app.agents.tester import tester_agent

        design_output = {
            "technical_design": "测试设计"
            # 没有 interface_specs
        }

        allowed_imports_section = tester_agent._build_allowed_imports_section(design_output)

        # 没有契约限制时返回空字符串
        assert allowed_imports_section == ""


class TestContractAlignment:
    """
    用例: 验证 ArchitectAgent 的 required_symbols 与 DesignerAgent 的 interface_specs 对齐。
    目的: 确保 DesignerAgent 实现了 ArchitectAgent 要求的所有符号。
    """

    def test_contract_alignment_detects_missing_required_symbols(self):
        """测试契约对齐检测缺失的必需符号"""
        from app.core.contract_alignment import verify_contract_alignment

        required_symbols = [
            {"name": "check_health", "type": "function", "module": "app/api/v1/health.py"},
            {"name": "check_database", "type": "function", "module": "app/api/v1/health.py"}
        ]

        interface_specs = [
            {"symbol_name": "check_health", "module": "app/api/v1/health.py"}
            # 缺少 check_database
        ]

        is_aligned, missing, extra = verify_contract_alignment(required_symbols, interface_specs)

        assert is_aligned is False
        assert len(missing) == 1
        assert "check_database" in missing[0]

    def test_contract_alignment_passes_when_all_required_present(self):
        """测试所有必需符号都存在时对齐通过"""
        from app.core.contract_alignment import verify_contract_alignment

        required_symbols = [
            {"name": "check_health", "type": "function", "module": "app/api/v1/health.py"}
        ]

        interface_specs = [
            {"symbol_name": "check_health", "module": "app/api/v1/health.py"}
        ]

        is_aligned, missing, extra = verify_contract_alignment(required_symbols, interface_specs)

        assert is_aligned is True
        assert len(missing) == 0
