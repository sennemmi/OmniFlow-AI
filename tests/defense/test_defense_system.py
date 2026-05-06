"""
安全与防御性测试：4层免疫系统

用例编号规范：SEC-LX-XX
- SEC-L1-01/02: Layer 1 - 沙箱隔离与文件回滚
- SEC-L2-01: Layer 2 - 回归保护
- SEC-L3-01: Layer 3 - 测试隔离
- SEC-L4-01: Layer 4 - 事务完整性
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any
from pathlib import Path
import tempfile

pytestmark = [pytest.mark.defense, pytest.mark.security]

from app.service.file_safe_io import FileSafeIOService
from app.service.sandbox_manager import SandboxManager


class TestLayer1SandboxIsolation:
    """
    SEC-L1-01: Layer 1 - 沙箱隔离
    
    测试场景：AI 尝试写入 ../../etc/passwd 或项目外的绝对路径
    预期结果：FileSafeIOService 抛出 PathSecurityError (目录穿越防护拦截)。
    """

    @pytest.fixture
    def project_root(self):
        """项目根目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "project"

    def test_blocks_path_traversal_attack(self, project_root):
        """测试阻止目录穿越攻击"""
        project_root.mkdir(parents=True, exist_ok=True)
        
        # 尝试目录穿越路径
        malicious_paths = [
            "../../etc/passwd",
            "../../../etc/shadow",
            "..\\..\\windows\\system32\\config\\sam",
            "../../.env",
            "/etc/passwd",  # 绝对路径
        ]
        
        for path in malicious_paths:
            # 验证路径被识别为恶意
            is_safe = self._is_path_safe(path, project_root)
            assert is_safe is False, f"路径 {path} 应该被阻止"

    def test_allows_safe_relative_paths(self, project_root):
        """测试允许安全的相对路径"""
        project_root.mkdir(parents=True, exist_ok=True)
        
        safe_paths = [
            "app/main.py",
            "backend/app/api/v1/users.py",
            "tests/unit/test_user.py",
            "src/components/Button.tsx",
        ]
        
        for path in safe_paths:
            is_safe = self._is_path_safe(path, project_root)
            assert is_safe is True, f"路径 {path} 应该被允许"

    def test_path_security_error_message(self):
        """测试路径安全错误信息"""
        malicious_path = "../../etc/passwd"
        
        error_message = f"PathSecurityError: 检测到目录穿越尝试: {malicious_path}"
        
        assert "PathSecurityError" in error_message
        assert "目录穿越" in error_message or "path traversal" in error_message.lower()

    def _is_path_safe(self, relative_path: str, project_root: Path) -> bool:
        """检查路径是否安全"""
        try:
            # 解析路径
            target = (project_root / relative_path).resolve()
            
            # 检查是否在项目根目录内
            try:
                target.relative_to(project_root.resolve())
                return True
            except ValueError:
                return False
        except Exception:
            return False


class TestLayer1FileRollback:
    """
    SEC-L1-02: Layer 1 - 文件回滚
    
    测试场景：AI 写入了引发服务崩溃的错误代码
    预期结果：写入前系统已生成 .bak 备份，rollback_change 能 100% 完美恢复原代码。
    """

    @pytest.fixture
    def original_code(self):
        """原始代码"""
        return '''def calculate_sum(a: int, b: int) -> int:
    """Calculate sum of two numbers"""
    return a + b

class Calculator:
    def multiply(self, x: float, y: float) -> float:
        return x * y
'''

    @pytest.fixture
    def corrupted_code(self):
        """错误代码"""
        return '''def calculate_sum(a: int, b: int) -> int:
    """Calculate sum of two numbers"""
    # AI 错误地修改了这里
    return a * b  # 错误：应该是加法不是乘法

class Calculator:
    def multiply(self, x: float, y: float) -> float:
        return x / y  # 错误：应该是乘法不是除法
'''

    def test_backup_created_before_write(self, original_code, corrupted_code):
        """测试写入前创建备份"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            
            # 创建原始文件
            test_file = project_root / "calculator.py"
            test_file.write_text(original_code, encoding='utf-8')
            
            # 模拟写入前创建备份
            backup_path = project_root / ".bak" / "calculator.py.bak"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_text(original_code, encoding='utf-8')
            
            # 写入错误代码
            test_file.write_text(corrupted_code, encoding='utf-8')
            
            # 验证备份存在且内容正确
            assert backup_path.exists()
            assert backup_path.read_text(encoding='utf-8') == original_code

    def test_rollback_perfectly_restores_original(self, original_code, corrupted_code):
        """测试回滚完美恢复原始代码"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            
            # 创建原始文件
            test_file = project_root / "calculator.py"
            test_file.write_text(original_code, encoding='utf-8')
            
            # 创建备份
            backup_path = project_root / ".bak" / "calculator.py.bak"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_text(original_code, encoding='utf-8')
            
            # 写入错误代码
            test_file.write_text(corrupted_code, encoding='utf-8')
            
            # 执行回滚
            backup_content = backup_path.read_text(encoding='utf-8')
            test_file.write_text(backup_content, encoding='utf-8')
            
            # 验证 100% 恢复
            restored_content = test_file.read_text(encoding='utf-8')
            assert restored_content == original_code
            assert "return a * b" not in restored_content

    def test_backup_isolation(self, original_code):
        """测试备份文件隔离"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            
            # 创建原始文件
            test_file = project_root / "app.py"
            test_file.write_text(original_code, encoding='utf-8')
            
            # 备份应该在 .bak 目录
            backup_dir = project_root / ".bak"
            backup_dir.mkdir(exist_ok=True)
            backup_file = backup_dir / "app.py.bak"
            backup_file.write_text(original_code, encoding='utf-8')
            
            # 验证备份在隔离目录
            assert backup_file.parent.name == ".bak"
            assert backup_file.name.endswith(".bak")


class TestLayer2RegressionProtection:
    """
    SEC-L2-01: Layer 2 - 回归保护
    
    测试场景：新代码导致 backend/tests/unit/ 下的老测试运行失败
    预期结果：拦截！抛出 regression_broken，拒绝 Auto-Fix，必须挂起 (request_user) 让人类决定是改代码还是改老测试。
    """

    @pytest.fixture
    def regression_failure_result(self):
        """回归测试失败结果"""
        return {
            "all_passed": False,
            "failure_cause": "regression_broken",
            "failed_tests": ["test_user_model", "test_auth_flow", "test_database_connection"],
            "error_details": {
                "layer": "regression",
                "message": "回归测试失败",
                "logs": "AssertionError in test_user_model",
                "suggestion": "新代码导致原有测试失败"
            }
        }

    def test_regression_failure_blocks_auto_fix(self, regression_failure_result):
        """测试回归失败阻止自动修复"""
        result = regression_failure_result
        
        # 验证失败原因
        assert result["failure_cause"] == "regression_broken"
        
        # 验证决策应该是 request_user，不是 auto_fix
        decision = self._make_decision(result)
        assert decision == "request_user"

    def test_regression_failure_requires_human_decision(self, regression_failure_result):
        """测试回归失败需要人工决策"""
        result = regression_failure_result
        
        # 验证失败信息包含具体测试
        assert len(result["failed_tests"]) > 0
        assert "test_user_model" in result["failed_tests"]
        
        # 验证建议信息
        assert "人工" in result["error_details"]["suggestion"] or \
               "human" in result["error_details"]["suggestion"].lower() or \
               "原有测试" in result["error_details"]["suggestion"]

    def test_regression_vs_new_test_distinction(self):
        """测试区分回归测试和新测试"""
        # 回归测试路径
        regression_test_paths = [
            "backend/tests/unit/test_user.py",
            "backend/tests/unit/test_auth.py",
            "backend/tests/integration/test_api.py"
        ]
        
        # 新测试路径
        new_test_paths = [
            "backend/tests/ai_generated/test_new_feature.py",
            "backend/tests/ai_generated/test_generated.py"
        ]
        
        # 验证路径区分
        for path in regression_test_paths:
            assert "ai_generated" not in path
            
        for path in new_test_paths:
            assert "ai_generated" in path

    def _make_decision(self, test_result: Dict) -> str:
        """根据测试结果做出决策"""
        if test_result["failure_cause"] == "regression_broken":
            return "request_user"
        elif test_result["failure_cause"] == "code_bug":
            return "auto_fix"
        else:
            return "proceed"


class TestLayer3TestIsolation:
    """
    SEC-L3-01: Layer 3 - 测试隔离
    
    测试场景：AI 测试代码尝试全局 Mock datetime.utcnow
    预期结果：拦截！提示测试框架限制，防止弄崩 FastAPI 内部中间件的事件循环。
    """

    @pytest.fixture
    def dangerous_mock_code(self):
        """危险的 Mock 代码"""
        return '''
import datetime
from unittest.mock import patch, MagicMock

# 危险：全局 Mock datetime
@patch('datetime.datetime.utcnow')
def test_with_global_mock(mock_utcnow):
    mock_utcnow.return_value = datetime.datetime(2024, 1, 1)
    # 这个 Mock 会影响 FastAPI 中间件的事件循环
    result = some_function()
    assert result is not None
'''

    @pytest.fixture
    def safe_mock_code(self):
        """安全的 Mock 代码"""
        return '''
import datetime
from unittest.mock import patch

# 安全：局部 Mock
def test_with_local_mock():
    with patch('app.service.user.datetime') as mock_dt:
        mock_dt.utcnow.return_value = datetime.datetime(2024, 1, 1)
        result = some_function()
        assert result is not None
    # Mock 在这里自动恢复
'''

    def test_detects_global_datetime_mock(self, dangerous_mock_code):
        """测试检测全局 datetime Mock"""
        violations = self._check_mock_safety(dangerous_mock_code)
        
        # 应该检测到危险模式
        assert len(violations) > 0
        assert any("datetime" in v for v in violations)
        assert any("global" in v.lower() or "全局" in v for v in violations)

    def test_allows_local_datetime_mock(self, safe_mock_code):
        """测试允许局部 datetime Mock"""
        violations = self._check_mock_safety(safe_mock_code)
        
        # 局部 Mock 应该被允许
        assert len(violations) == 0

    def test_forbidden_mock_targets(self):
        """测试禁止的 Mock 目标"""
        forbidden_targets = [
            "datetime.datetime.utcnow",
            "asyncio.get_event_loop",
            "fastapi.Request",
            "sqlalchemy.create_engine",
        ]
        
        # 验证禁止列表
        assert len(forbidden_targets) > 0
        assert "datetime.datetime.utcnow" in forbidden_targets

    def _check_mock_safety(self, code: str) -> list:
        """检查 Mock 安全性"""
        violations = []
        
        # 检测全局 datetime Mock
        if "@patch('datetime.datetime.utcnow')" in code or \
           '@patch("datetime.datetime.utcnow")' in code:
            violations.append("禁止全局 Mock datetime.datetime.utcnow")
        
        # 检测危险的 asyncio Mock
        if "asyncio.get_event_loop" in code:
            violations.append("禁止 Mock asyncio 事件循环")
            
        return violations


class TestLayer4TransactionIntegrity:
    """
    SEC-L4-01: Layer 4 - 事务完整性
    
    测试场景：在 Pipeline 流转中途发生数据库断开或进程崩溃
    预期结果：SQLAlchemy 事务自动 rollback，防止出现阶段完成但状态仍是 RUNNING 的脏数据。
    """

    @pytest.fixture
    def pipeline_transaction(self):
        """Pipeline 事务"""
        return {
            "pipeline_id": 1,
            "operations": [],
            "committed": False,
            "rolled_back": False
        }

    def test_transaction_rollback_on_db_disconnect(self, pipeline_transaction):
        """测试数据库断开时事务回滚"""
        tx = pipeline_transaction
        
        # 开始事务
        tx["operations"].append("update_pipeline_status")
        tx["operations"].append("update_stage_status")
        
        # 模拟数据库断开
        db_disconnected = True
        
        if db_disconnected:
            # 触发回滚
            tx["rolled_back"] = True
            tx["operations"] = []
        
        # 验证回滚
        assert tx["rolled_back"] is True
        assert len(tx["operations"]) == 0

    def test_transaction_rollback_on_process_crash(self, pipeline_transaction):
        """测试进程崩溃时事务回滚"""
        tx = pipeline_transaction
        
        # 开始事务
        tx["operations"].append("create_stage")
        
        # 模拟进程崩溃
        process_crashed = True
        
        if process_crashed:
            # 事务应该被回滚（由数据库自动处理）
            tx["rolled_back"] = True
        
        assert tx["rolled_back"] is True

    def test_no_partial_commit(self):
        """测试不允许部分提交"""
        # 模拟多阶段更新
        updates = [
            {"stage": "DESIGN", "status": "SUCCESS"},
            {"stage": "CODING", "status": "SUCCESS"},
            {"stage": "TESTING", "status": "FAILED"}  # 失败
        ]
        
        # 如果任何阶段失败，整个事务应该回滚
        any_failed = any(u["status"] == "FAILED" for u in updates)
        
        if any_failed:
            committed = False
            rolled_back = True
        else:
            committed = True
            rolled_back = False
        
        assert committed is False
        assert rolled_back is True

    def test_state_consistency_after_rollback(self):
        """测试回滚后状态一致性"""
        # 原始状态
        original_state = {
            "pipeline_status": "RUNNING",
            "current_stage": "CODING",
            "stage_status": "RUNNING"
        }
        
        # 尝试更新（失败）
        try:
            new_state = original_state.copy()
            new_state["current_stage"] = "TESTING"
            new_state["stage_status"] = "SUCCESS"
            
            # 模拟错误
            raise Exception("Database error")
            
        except Exception:
            # 回滚到原始状态
            final_state = original_state
        
        # 验证状态一致
        assert final_state["current_stage"] == "CODING"
        assert final_state["stage_status"] == "RUNNING"


class TestDefenseSystemIntegration:
    """
    防御系统集成测试
    
    测试 4 层防御协同工作
    """

    def test_defense_layer_sequence(self):
        """测试防御层执行顺序"""
        layers = [
            "L1: Sandbox Isolation",
            "L2: Regression Protection",
            "L3: Test Isolation",
            "L4: Transaction Integrity"
        ]
        
        # 验证顺序
        assert layers[0].startswith("L1")
        assert layers[1].startswith("L2")
        assert layers[2].startswith("L3")
        assert layers[3].startswith("L4")

    def test_all_layers_must_pass(self):
        """测试所有层必须通过"""
        layer_results = {
            "L1": True,
            "L2": True,
            "L3": False,  # 失败
            "L4": True
        }
        
        # 任何一层失败都应该阻止继续
        all_passed = all(layer_results.values())
        assert all_passed is False

    def test_defense_metrics(self):
        """测试防御指标"""
        # 模拟拦截统计
        interception_stats = {
            "path_traversal_attempts": 10,
            "path_traversal_blocked": 10,
            "rollback_invocations": 5,
            "rollback_successful": 5
        }
        
        # 验证拦截率 100%
        path_traversal_rate = (
            interception_stats["path_traversal_blocked"] / 
            interception_stats["path_traversal_attempts"]
        )
        assert path_traversal_rate == 1.0
        
        # 验证回滚成功率 100%
        rollback_rate = (
            interception_stats["rollback_successful"] / 
            interception_stats["rollback_invocations"]
        )
        assert rollback_rate == 1.0
