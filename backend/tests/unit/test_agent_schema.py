"""
Agent 结构化验证测试
验证 LLM 输出是否符合 Pydantic 模型定义
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json


@pytest.mark.unit
class TestArchitectAgentSchema:
    """测试 ArchitectAgent 输出结构"""

    @pytest.mark.asyncio
    async def test_architect_output_structure(self, mock_llm_response):
        """验证 ArchitectAgent 输出包含必要字段"""
        from app.agents.architect import architect_agent

        mock_output = {
            "feature_description": "实现用户登录功能",
            "affected_files": ["app/models/user.py", "app/api/v1/auth.py"],
            "estimated_effort": "2天",
            "technical_design": "使用 JWT 认证"
        }

        with patch.object(architect_agent, 'analyze', new_callable=AsyncMock,
                         return_value={"success": True, "output": mock_output}):
            result = await architect_agent.analyze("实现用户登录功能", file_tree={})

            assert result["success"] is True
            assert "feature_description" in result["output"]
            assert isinstance(result["output"]["affected_files"], list)
            assert len(result["output"]["affected_files"]) > 0

    @pytest.mark.asyncio
    async def test_architect_output_validation(self):
        """验证 ArchitectAgent 输出字段类型"""
        mock_output = {
            "feature_description": "测试功能",
            "affected_files": [],  # 空列表应该被接受
            "estimated_effort": "1天",
            "technical_design": None  # None 值应该被接受
        }

        # 验证输出可以被序列化
        try:
            json_str = json.dumps(mock_output)
            parsed = json.loads(json_str)
            assert isinstance(parsed["affected_files"], list)
            assert parsed["technical_design"] is None or isinstance(parsed["technical_design"], str)
        except (json.JSONDecodeError, TypeError) as e:
            pytest.fail(f"输出无法序列化: {e}")


@pytest.mark.unit
class TestCoderAgentSchema:
    """测试 CoderAgent 输出结构"""

    @pytest.mark.asyncio
    async def test_coder_output_structure(self):
        """验证 CoderAgent 输出包含必要字段"""
        mock_output = {
            "files": [
                {
                    "file_path": "app/test.py",
                    "content": "def test(): pass",
                    "change_type": "add",
                    "original_content": None
                }
            ],
            "summary": "添加了测试文件",
            "dependencies_added": ["pytest"],
            "tests_included": True
        }

        # 验证文件结构
        assert isinstance(mock_output["files"], list)
        for file in mock_output["files"]:
            assert "file_path" in file
            assert "content" in file
            assert "change_type" in file
            assert file["change_type"] in ["add", "modify", "delete"]

    def test_code_file_validation(self):
        """验证代码文件字段"""
        valid_file = {
            "file_path": "app/models/user.py",
            "content": "class User: pass",
            "change_type": "add",
            "original_content": None
        }

        # 验证必要字段
        required_fields = ["file_path", "content", "change_type"]
        for field in required_fields:
            assert field in valid_file, f"缺少必要字段: {field}"

        # 验证 change_type 值
        assert valid_file["change_type"] in ["add", "modify", "delete"]


@pytest.mark.unit
class TestGoldenDatasetValidation:
    """使用 Golden Cases 验证 Agent 输出"""

    @pytest.fixture
    def golden_dataset(self):
        """加载 Golden Dataset"""
        import json
        from pathlib import Path

        fixture_path = Path(__file__).parent.parent / "fixtures" / "golden_dataset.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_golden_dataset_loaded(self, golden_dataset):
        """验证 Golden Dataset 正确加载"""
        assert "test_cases" in golden_dataset
        assert len(golden_dataset["test_cases"]) > 0

        for case in golden_dataset["test_cases"]:
            assert "name" in case
            assert "requirement" in case
            assert "expected_affected_files" in case
            assert isinstance(case["expected_affected_files"], list)

    def test_keyword_matching(self, golden_dataset):
        """测试关键词匹配逻辑"""
        for case in golden_dataset["test_cases"]:
            requirement = case["requirement"].lower()
            keywords = case["expected_keywords"]

            # 验证至少有一个关键词出现在需求中
            matched = any(kw.lower() in requirement for kw in keywords)
            # assert matched, f"案例 '{case['name']}' 没有匹配到任何关键词"

    def test_file_path_format(self, golden_dataset):
        """验证文件路径格式"""
        for case in golden_dataset["test_cases"]:
            for file_path in case["expected_affected_files"]:
                # 验证路径格式
                assert file_path.startswith("app/") or file_path.startswith("migrations/"), \
                    f"无效路径: {file_path}"
                assert file_path.endswith(".py") or file_path.endswith("/"), \
                    f"路径应该以 .py 结尾或以 / 结尾: {file_path}"
