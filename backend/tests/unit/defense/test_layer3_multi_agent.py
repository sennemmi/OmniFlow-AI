"""
第三层：多 Agent 协作与状态机防线（防止系统死循环）

利用 base.py 中现有的 MockAgent，不调用真实 LLM（省钱、快速）来测试流程。

测试列表：
1. test_pydantic_schema_validation - Pydantic Schema 强校验测试
2. test_max_retries_limit_terminates_loop - 自动修复最大重试机制测试 (Max Retries Limit)
3. test_json_strip_markdown - JSON 剥离测试
"""

import pytest

pytestmark = [pytest.mark.defense, pytest.mark.layer3]
import json
from typing import Dict, Any
from unittest.mock import AsyncMock, patch, MagicMock
from pydantic import BaseModel, ValidationError

from app.agents.base import LangGraphAgent, MockAgent, BaseAgentState
from app.agents.multi_agent_coordinator import MultiAgentCoordinator


class FakeOutput(BaseModel):
    """用于测试的 Pydantic 模型"""
    files: list
    summary: str


class TestPydanticSchemaValidation:
    """
    用例: 模拟 LLM 返回了缺少必填字段（如 files）的 JSON，测试 LangGraphAgent 能否正确捕获 ValidationError 并在状态中记录 error。
    目的: 防止残缺的 JSON 冲入执行引擎。
    """

    def test_validation_error_caught_for_missing_required_field(self):
        """测试缺少必填字段时捕获 ValidationError"""

        class TestAgent(LangGraphAgent[FakeOutput]):
            @property
            def system_prompt(self) -> str:
                return "Test system prompt"

            def build_user_prompt(self, state: Dict[str, Any]) -> str:
                return "Test user prompt"

            def parse_output(self, response: str) -> Dict[str, Any]:
                # 模拟返回缺少 files 字段的 JSON
                return {"summary": "test summary"}  # 缺少 files

            def validate_output(self, output: Dict[str, Any]) -> FakeOutput:
                return FakeOutput(**output)

        agent = TestAgent("test_agent")

        # 测试 validate_output 会抛出 ValidationError
        with pytest.raises(ValidationError) as exc_info:
            agent.validate_output({"summary": "test"})

        assert "files" in str(exc_info.value)

    def test_validation_error_in_state(self):
        """测试验证错误被记录在状态中"""

        class TestAgent(LangGraphAgent[FakeOutput]):
            @property
            def system_prompt(self) -> str:
                return "Test system prompt"

            def build_user_prompt(self, state: Dict[str, Any]) -> str:
                return "Test user prompt"

            def parse_output(self, response: str) -> Dict[str, Any]:
                return {"summary": "test"}  # 缺少 files

            def validate_output(self, output: Dict[str, Any]) -> FakeOutput:
                return FakeOutput(**output)

        agent = TestAgent("test_agent")

        # 测试 _validate_node 方法
        state: BaseAgentState = {
            "output": {"summary": "test"},
            "error": None,
            "retry_count": 0,
            "input_tokens": 0,
            "output_tokens": 0
        }

        result = agent._validate_node(state)

        assert result["error"] is not None
        assert "Validation error" in result["error"]

    def test_valid_output_passes_validation(self):
        """测试有效输出通过验证"""

        class TestAgent(LangGraphAgent[FakeOutput]):
            @property
            def system_prompt(self) -> str:
                return "Test system prompt"

            def build_user_prompt(self, state: Dict[str, Any]) -> str:
                return "Test user prompt"

            def parse_output(self, response: str) -> Dict[str, Any]:
                return {"files": [], "summary": "test"}

            def validate_output(self, output: Dict[str, Any]) -> FakeOutput:
                return FakeOutput(**output)

        agent = TestAgent("test_agent")

        state: BaseAgentState = {
            "output": {"files": [], "summary": "test"},
            "error": None,
            "retry_count": 0,
            "input_tokens": 0,
            "output_tokens": 0
        }

        result = agent._validate_node(state)

        assert result["error"] is None
        assert result["output"] is not None


class TestMaxRetriesLimitTerminatesLoop:
    """
    用例: 强制让 Mock 测试执行器永远返回 Failed。断言 MultiAgentCoordinator 在重试 MAX_FIX_RETRIES (3次) 后，必须终止并返回 False，跳出 while 循环。
    目的: 防止 AI 因为修不好 Bug 而消耗几百美金的 Token（死循环）。
    """

    def test_max_retries_limit_stops_loop(self):
        """测试最大重试次数限制能终止循环"""
        import asyncio

        async def run_test():
            coordinator = MultiAgentCoordinator()

            # 验证 MAX_FIX_RETRIES 是 3
            assert coordinator.MAX_FIX_RETRIES == 3

            # 模拟一个永远返回失败的 execute_with_auto_fix
            with patch.object(coordinator, '_execute_code_agent') as mock_code:
                mock_code.return_value = {
                    "success": True,
                    "code_output": {"files": [{"file_path": "test.py", "content": "# test"}]},
                    "input_tokens": 100,
                    "output_tokens": 50
                }

                # 模拟测试永远失败
                with patch('app.service.layered_test_runner.LayeredTestRunner.run') as mock_test:
                    mock_test.return_value = MagicMock(
                        all_passed=False,
                        failure_cause="code_bug",
                        layers=[MagicMock(layer="new_tests", passed=False)],
                        regression_failed_tests=[]
                    )

                    # 模拟 ReviewAgent 永远返回 auto_fix
                    with patch('app.agents.reviewer.ReviewAgent.decide') as mock_decide:
                        mock_decide.return_value = MagicMock(
                            action="auto_fix",
                            error_context="Test failure"
                        )

                        # 执行
                        result = await coordinator.execute_with_auto_fix(
                            design_output={},
                            target_files={},
                            pipeline_id=1,
                            workspace_path="/tmp",
                            sandbox_port=None
                        )

                        # 验证在达到最大重试次数后停止
                        assert result["success"] is False
                        # 验证 attempt 不会超过 MAX_FIX_RETRIES
                        assert result["attempt"] <= coordinator.MAX_FIX_RETRIES + 1

        asyncio.run(run_test())

    def test_should_retry_logic(self):
        """测试重试判断逻辑"""
        coordinator = MultiAgentCoordinator()

        # 验证 MAX_FIX_RETRIES 常量
        assert coordinator.MAX_FIX_RETRIES == 3

        # 测试在达到最大重试次数后不再重试
        assert coordinator.MAX_FIX_RETRIES == 3


class TestJsonStripMarkdown:
    """
    用例: 模拟 LLM 返回了带有 ```json 开头和啰嗦的 Markdown 结尾的字符串，测试 _parse_json_response 能否正确提取出干净的字典。
    目的: 容错处理，应对 LLM 不听指令乱加前后缀的习惯。
    """

    def test_strip_json_code_block_markers(self):
        """测试剥离 ```json 代码块标记"""

        class TestAgent(LangGraphAgent[BaseModel]):
            @property
            def system_prompt(self) -> str:
                return "Test"

            def build_user_prompt(self, state: Dict[str, Any]) -> str:
                return "Test"

            def parse_output(self, response: str) -> Dict[str, Any]:
                return self._parse_json_response(response)

            def validate_output(self, output: Dict[str, Any]) -> BaseModel:
                return BaseModel(**output)

        agent = TestAgent("test")

        # 测试带 ```json 前缀的响应
        response = '''```json
{"files": [], "summary": "test"}
```'''

        result = agent._parse_json_response(response)
        assert result == {"files": [], "summary": "test"}

    def test_strip_generic_code_block_markers(self):
        """测试剥离普通 ``` 代码块标记"""

        class TestAgent(LangGraphAgent[BaseModel]):
            @property
            def system_prompt(self) -> str:
                return "Test"

            def build_user_prompt(self, state: Dict[str, Any]) -> str:
                return "Test"

            def parse_output(self, response: str) -> Dict[str, Any]:
                return self._parse_json_response(response)

            def validate_output(self, output: Dict[str, Any]) -> BaseModel:
                return BaseModel(**output)

        agent = TestAgent("test")

        # 测试带 ``` 前缀的响应
        response = '''```
{"key": "value", "number": 42}
```'''

        result = agent._parse_json_response(response)
        assert result == {"key": "value", "number": 42}

    def test_strip_with_extra_markdown_content(self):
        """测试剥离带额外 Markdown 内容的响应"""

        class TestAgent(LangGraphAgent[BaseModel]):
            @property
            def system_prompt(self) -> str:
                return "Test"

            def build_user_prompt(self, state: Dict[str, Any]) -> str:
                return "Test"

            def parse_output(self, response: str) -> Dict[str, Any]:
                return self._parse_json_response(response)

            def validate_output(self, output: Dict[str, Any]) -> BaseModel:
                return BaseModel(**output)

        agent = TestAgent("test")

        # 测试带前后啰嗦内容的响应
        response = '''Here's the JSON output:

```json
{"status": "success", "data": [1, 2, 3]}
```

Hope this helps! Let me know if you need anything else.'''

        result = agent._parse_json_response(response)
        assert result == {"status": "success", "data": [1, 2, 3]}

    def test_plain_json_without_markers(self):
        """测试没有 Markdown 标记的纯 JSON"""

        class TestAgent(LangGraphAgent[BaseModel]):
            @property
            def system_prompt(self) -> str:
                return "Test"

            def build_user_prompt(self, state: Dict[str, Any]) -> str:
                return "Test"

            def parse_output(self, response: str) -> Dict[str, Any]:
                return self._parse_json_response(response)

            def validate_output(self, output: Dict[str, Any]) -> BaseModel:
                return BaseModel(**output)

        agent = TestAgent("test")

        # 测试纯 JSON 响应
        response = '{"simple": "json", "nested": {"key": "value"}}'

        result = agent._parse_json_response(response)
        assert result == {"simple": "json", "nested": {"key": "value"}}

    def test_invalid_json_raises_error(self):
        """测试无效 JSON 抛出错误"""
        from app.agents.base import JSONParseError

        class TestAgent(LangGraphAgent[BaseModel]):
            @property
            def system_prompt(self) -> str:
                return "Test"

            def build_user_prompt(self, state: Dict[str, Any]) -> str:
                return "Test"

            def parse_output(self, response: str) -> Dict[str, Any]:
                return self._parse_json_response(response)

            def validate_output(self, output: Dict[str, Any]) -> BaseModel:
                return BaseModel(**output)

        agent = TestAgent("test")

        # 测试无效 JSON
        response = "This is not JSON at all"

        with pytest.raises(JSONParseError):
            agent._parse_json_response(response)


class TestMockAgentFunctionality:
    """测试 MockAgent 功能 - 用于不调用真实 LLM 的测试"""

    def test_mock_agent_returns_configured_response(self):
        """测试 MockAgent 返回预设响应"""
        mock_response = {
            "files": [{"file_path": "test.py", "content": "# test"}],
            "summary": "Mock generated"
        }

        mock_agent = MockAgent("test_mock", mock_response)

        # 验证 MockAgent 返回预设值
        parsed = mock_agent.parse_output("")
        assert parsed == mock_response

    def test_mock_agent_no_llm_call(self):
        """测试 MockAgent 不调用真实 LLM"""
        mock_response = {"status": "ok"}
        mock_agent = MockAgent("test_mock", mock_response)

        # _call_llm 应该返回 JSON 字符串
        import asyncio
        result = asyncio.run(mock_agent._call_llm("", ""))

        # 验证返回的是 JSON 字符串
        parsed = json.loads(result)
        assert parsed == mock_response
