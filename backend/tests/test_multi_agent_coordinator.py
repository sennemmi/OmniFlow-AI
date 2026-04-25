"""
多 Agent 协作协调器单元测试

以单元测试为荣，以手工验证为耻
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from typing import Dict, Any

from app.agents.multi_agent_coordinator import (
    MultiAgentCoordinator,
    MultiAgentState,
    CodeAndTestOutput
)
from app.agents.coder import coder_agent
from app.agents.tester import test_agent


@pytest.fixture
def coordinator():
    """创建协调器实例"""
    return MultiAgentCoordinator()


@pytest.fixture
def sample_design_output():
    """示例设计方案输出"""
    return {
        "feature_description": "用户登录功能",
        "affected_files": ["backend/app/api/v1/auth.py"],
        "api_endpoints": [
            {
                "path": "/api/v1/auth/login",
                "method": "POST",
                "description": "用户登录"
            }
        ]
    }


@pytest.fixture
def sample_target_files():
    """示例目标文件"""
    return {
        "backend/app/api/v1/auth.py": "# 现有代码..."
    }


@pytest.fixture
def sample_code_output():
    """示例代码输出"""
    return {
        "files": [
            {
                "file_path": "backend/app/api/v1/auth.py",
                "content": "# 生成的代码...",
                "change_type": "modify",
                "description": "添加登录接口"
            }
        ],
        "summary": "添加了用户登录功能",
        "dependencies_added": ["fastapi", "pydantic"],
        "tests_included": False
    }


@pytest.fixture
def sample_test_output():
    """示例测试输出"""
    return {
        "test_files": [
            {
                "file_path": "backend/tests/test_auth.py",
                "content": "# 测试代码...",
                "target_module": "backend.app.api.v1.auth",
                "test_cases_count": 5
            }
        ],
        "summary": "生成了 5 个测试用例",
        "coverage_targets": [
            "正常登录",
            "密码错误",
            "用户不存在"
        ],
        "dependencies_added": ["pytest", "pytest-asyncio"]
    }


class TestMultiAgentCoordinator:
    """测试多 Agent 协调器"""

    def test_max_fix_retries_constant(self, coordinator):
        """测试最大修复重试次数常量"""
        assert coordinator.MAX_FIX_RETRIES == 3

    @pytest.mark.asyncio
    async def test_execute_code_agent_success(
        self,
        coordinator,
        sample_design_output,
        sample_target_files,
        sample_code_output
    ):
        """测试 CoderAgent 执行 - 成功场景"""
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": True, "output": sample_code_output}
        ):
            result = await coordinator._execute_code_agent(
                sample_design_output,
                sample_target_files,
                pipeline_id=1
            )

            assert result["code_output"] == sample_code_output
            assert result["code_error"] is None

    @pytest.mark.asyncio
    async def test_execute_code_agent_failure(
        self,
        coordinator,
        sample_design_output,
        sample_target_files
    ):
        """测试 CoderAgent 执行 - 失败场景"""
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": False, "error": "代码生成失败"}
        ):
            result = await coordinator._execute_code_agent(
                sample_design_output,
                sample_target_files,
                pipeline_id=1
            )

            assert result["code_output"] is None
            assert result["code_error"] == "代码生成失败"

    @pytest.mark.asyncio
    async def test_execute_test_agent_success(
        self,
        coordinator,
        sample_design_output,
        sample_target_files,
        sample_code_output,
        sample_test_output
    ):
        """测试 TestAgent 执行 - 成功场景"""
        with patch.object(
            test_agent,
            'generate_tests',
            new_callable=AsyncMock,
            return_value={"success": True, "output": sample_test_output}
        ):
            result = await coordinator._execute_test_agent(
                sample_design_output,
                sample_code_output,
                sample_target_files,
                pipeline_id=1
            )

            assert result["test_output"] == sample_test_output
            assert result["test_error"] is None

    @pytest.mark.asyncio
    async def test_execute_test_agent_skipped(
        self,
        coordinator,
        sample_design_output,
        sample_target_files
    ):
        """测试 TestAgent 执行 - 代码生成失败时跳过"""
        result = await coordinator._execute_test_agent(
            sample_design_output,
            None,  # code_output 为 None
            sample_target_files,
            pipeline_id=1
        )

        assert result["test_output"] is None
        assert result["test_error"] is None

    def test_merge_results_success(
        self,
        coordinator,
        sample_target_files,
        sample_code_output,
        sample_test_output
    ):
        """测试合并结果 - 成功场景"""
        result = coordinator._merge_results(
            sample_code_output,
            sample_test_output,
            sample_target_files
        )

        assert result["final_output"] is not None
        assert result["error"] is None
        assert len(result["final_output"]["files"]) == 2  # 代码文件 + 测试文件
        assert result["final_output"]["tests_included"] is True
        assert "pytest" in result["final_output"]["dependencies_added"]

    def test_merge_results_code_error(self, coordinator, sample_target_files):
        """测试合并结果 - 代码生成错误"""
        result = coordinator._merge_results(
            None,
            None,
            sample_target_files,
            code_error="代码生成失败"
        )

        assert result["final_output"] is None
        assert "Code generation failed" in result["error"]

    def test_build_summary(self, coordinator, sample_code_output, sample_test_output):
        """测试摘要构建"""
        summary = coordinator._build_summary(sample_code_output, sample_test_output)

        assert "代码生成" in summary
        assert "测试生成" in summary
        assert "3 个测试目标" in summary

    def test_build_summary_no_test(self, coordinator, sample_code_output):
        """测试摘要构建 - 无测试输出"""
        summary = coordinator._build_summary(sample_code_output, None)

        assert "代码生成" in summary
        assert "测试生成" not in summary

    @pytest.mark.asyncio
    async def test_execute_parallel_success(
        self,
        coordinator,
        sample_design_output,
        sample_target_files,
        sample_code_output,
        sample_test_output
    ):
        """测试完整的并行执行流程 - 成功场景"""
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": True, "output": sample_code_output}
        ):
            with patch.object(
                test_agent,
                'generate_tests',
                new_callable=AsyncMock,
                return_value={"success": True, "output": sample_test_output}
            ):
                result = await coordinator.execute_parallel(
                    sample_design_output,
                    sample_target_files
                )

                assert result["success"] is True
                assert result["output"] is not None
                assert result["output"]["tests_included"] is True

    @pytest.mark.asyncio
    async def test_execute_parallel_failure(
        self,
        coordinator,
        sample_design_output,
        sample_target_files
    ):
        """测试完整的并行执行流程 - 失败场景"""
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": False, "error": "LLM 调用失败"}
        ):
            result = await coordinator.execute_parallel(
                sample_design_output,
                sample_target_files
            )

            assert result["success"] is False
            assert "LLM 调用失败" in result["error"]
            assert result["output"] is None

    @pytest.mark.asyncio
    async def test_execute_with_auto_fix_success_first_try(
        self,
        coordinator,
        sample_design_output,
        sample_target_files,
        sample_code_output,
        sample_test_output
    ):
        """测试自动修复 - 第一次就成功"""
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": True, "output": sample_code_output}
        ):
            with patch(
                'app.agents.multi_agent_coordinator.TestRunnerService.run_tests',
                new_callable=AsyncMock,
                return_value={"success": True, "logs": "All tests passed", "summary": "1 passed"}
            ):
                with patch.object(
                    test_agent,
                    'generate_tests',
                    new_callable=AsyncMock,
                    return_value={"success": True, "output": sample_test_output}
                ):
                    with patch(
                        'app.agents.multi_agent_coordinator.CodeExecutorService'
                    ) as MockExecutor:
                        result = await coordinator.execute_with_auto_fix(
                            sample_design_output,
                            sample_target_files,
                            pipeline_id=1,
                            workspace_path="/tmp/workspace"
                        )

                        assert result["success"] is True
                        assert result["output"] is not None
                        assert result["attempt"] == 0

    @pytest.mark.asyncio
    async def test_execute_with_auto_fix_retry_then_success(
        self,
        coordinator,
        sample_design_output,
        sample_target_files,
        sample_code_output,
        sample_test_output
    ):
        """测试自动修复 - 重试后成功"""
        # 第一次失败，第二次成功
        code_results = [
            {"success": True, "output": sample_code_output},
            {"success": True, "output": sample_code_output}
        ]
        test_results = [
            {"success": False, "logs": "Test failed", "summary": "1 failed"},
            {"success": True, "logs": "All tests passed", "summary": "1 passed"}
        ]

        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            side_effect=code_results
        ):
            with patch(
                'app.agents.multi_agent_coordinator.TestRunnerService.run_tests',
                new_callable=AsyncMock,
                side_effect=test_results
            ):
                with patch.object(
                    test_agent,
                    'generate_tests',
                    new_callable=AsyncMock,
                    return_value={"success": True, "output": sample_test_output}
                ):
                    with patch(
                        'app.agents.multi_agent_coordinator.CodeExecutorService'
                    ) as MockExecutor:
                        result = await coordinator.execute_with_auto_fix(
                            sample_design_output,
                            sample_target_files,
                            pipeline_id=1,
                            workspace_path="/tmp/workspace"
                        )

                        assert result["success"] is True
                        assert result["attempt"] == 1  # 重试了一次

    @pytest.mark.asyncio
    async def test_execute_with_auto_fix_max_retries_exceeded(
        self,
        coordinator,
        sample_design_output,
        sample_target_files,
        sample_code_output
    ):
        """测试自动修复 - 超过最大重试次数"""
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": True, "output": sample_code_output}
        ):
            with patch(
                'app.agents.multi_agent_coordinator.TestRunnerService.run_tests',
                new_callable=AsyncMock,
                return_value={"success": False, "logs": "Test failed", "summary": "1 failed"}
            ):
                with patch(
                    'app.agents.multi_agent_coordinator.CodeExecutorService'
                ) as MockExecutor:
                    result = await coordinator.execute_with_auto_fix(
                        sample_design_output,
                        sample_target_files,
                        pipeline_id=1,
                        workspace_path="/tmp/workspace"
                    )

                    assert result["success"] is False
                    assert "最大次数" in result["error"]
                    assert result["attempt"] == 4  # MAX_FIX_RETRIES + 1


class TestCodeAndTestOutput:
    """测试输出模型"""

    def test_valid_output(self):
        """测试有效的输出模型"""
        output = CodeAndTestOutput(
            code_files=[{"path": "test.py", "content": "code"}],
            test_files=[{"path": "test_test.py", "content": "test"}],
            code_summary="代码摘要",
            test_summary="测试摘要",
            tests_included=True
        )

        assert output.code_files[0]["path"] == "test.py"
        assert output.tests_included is True

    def test_default_values(self):
        """测试默认值"""
        output = CodeAndTestOutput(
            code_files=[],
            test_files=[],
            code_summary="",
            test_summary=""
        )

        assert output.dependencies_added == []
        assert output.tests_included is True


class TestMultiAgentState:
    """测试状态模型"""

    def test_state_creation(self):
        """测试状态创建"""
        state: MultiAgentState = {
            "design_output": {"key": "value"},
            "target_files": {"file.py": "content"},
            "code_output": None,
            "code_error": None,
            "test_output": None,
            "test_error": None,
            "final_output": None,
            "error": None
        }

        assert state["design_output"]["key"] == "value"
        assert state["code_output"] is None
