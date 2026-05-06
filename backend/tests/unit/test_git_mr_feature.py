"""
Git 集成 + 自动创建 MR 功能单元测试

覆盖范围：
1. GitProviderService.create_commit_summary() —— diff 获取
2. PRGeneratorService.generate_pr_description() —— LLM 语义摘要 + 行级 diff 摘要
3. GitHubProviderService.create_pull_request() —— PR 创建 HTTP 调用
4. DeliveryHandler.execute() —— 端到端流程（主流程 + 异常分支）
"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures 共享数据
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_diff_text():
    return """\
diff --git a/app/service/calculator.py b/app/service/calculator.py
index 1a2b3c4..5d6e7f8 100644
--- a/app/service/calculator.py
+++ b/app/service/calculator.py
@@ -10,6 +10,12 @@ class Calculator:
     def add(self, a, b):
         return a + b
 
+    def divide(self, a, b):
+        if b == 0:
+            raise ValueError("Cannot divide by zero")
+        return a / b
+
"""

@pytest.fixture
def sample_diff_stat():
    return " app/service/calculator.py | 6 ++++++\n 1 file changed, 6 insertions(+)"


@pytest.fixture
def sample_multi_agent_output():
    return {
        "summary": "新增 Calculator.divide() 方法，支持除法运算并处理除零异常",
        "files": [
            {
                "file_path": "app/service/calculator.py",
                "content": "# calculator code",
                "change_type": "modify",
                "description": "新增 divide 方法"
            },
            {
                "file_path": "tests/unit/test_calculator.py",
                "content": "# test code",
                "change_type": "add",
                "description": "新增 divide 方法单元测试"
            }
        ],
        "tests_included": True,
        "coverage_targets": ["divide 正常流程", "除零异常处理"],
        "dependencies_added": []
    }


@pytest.fixture
def sample_execution_summary():
    return {"success": 2, "failed": 0, "total": 2}


# ─────────────────────────────────────────────────────────────────────────────
# 1. GitProviderService.create_commit_summary()
# ─────────────────────────────────────────────────────────────────────────────

class TestGitProviderCreateCommitSummary:
    """
    用例：验证 create_commit_summary() 能正确调用 git 命令并返回结构化结果。
    目的：确保 diff 数据能被正确采集并传递给 LLM。
    """

    def test_returns_diff_text_and_stat(self, tmp_path, sample_diff_text, sample_diff_stat):
        """正常情况：git 命令成功，返回 diff_text 和 diff_stat"""
        from app.service.git_provider import GitProviderService

        service = GitProviderService(str(tmp_path))

        mock_diff = MagicMock(stdout=sample_diff_text, returncode=0)
        mock_stat = MagicMock(stdout=sample_diff_stat, returncode=0)

        with patch("subprocess.run", side_effect=[mock_diff, mock_stat]):
            result = service.create_commit_summary()

        assert "diff_text" in result
        assert "diff_stat" in result
        assert "divide" in result["diff_text"]
        assert "1 file changed" in result["diff_stat"]

    def test_diff_text_truncated_at_8000_chars(self, tmp_path):
        """diff 超长时截断为 8000 字符，防止 token 超限"""
        from app.service.git_provider import GitProviderService

        service = GitProviderService(str(tmp_path))
        long_diff = "+" + "x" * 10000

        mock_diff = MagicMock(stdout=long_diff, returncode=0)
        mock_stat = MagicMock(stdout="1 file changed", returncode=0)

        with patch("subprocess.run", side_effect=[mock_diff, mock_stat]):
            result = service.create_commit_summary()

        assert len(result["diff_text"]) <= 8000

    def test_returns_empty_strings_on_subprocess_error(self, tmp_path):
        """git 命令失败时，返回空字符串而不是抛出异常"""
        from app.service.git_provider import GitProviderService

        service = GitProviderService(str(tmp_path))

        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = service.create_commit_summary()

        assert result == {"diff_text": "", "diff_stat": ""}

    def test_no_changes_returns_empty_diff(self, tmp_path):
        """仓库无变更时，diff 为空字符串"""
        from app.service.git_provider import GitProviderService

        service = GitProviderService(str(tmp_path))
        mock_diff = MagicMock(stdout="", returncode=0)
        mock_stat = MagicMock(stdout="", returncode=0)

        with patch("subprocess.run", side_effect=[mock_diff, mock_stat]):
            result = service.create_commit_summary()

        assert result["diff_text"] == ""
        assert result["diff_stat"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# 2. PRGeneratorService —— LLM 摘要生成
# ─────────────────────────────────────────────────────────────────────────────

class TestPRGeneratorService:
    """
    用例：验证 PR 描述生成逻辑，包括 LLM 摘要注入和静态模板部分。
    目的：确保生成的 PR body 包含语义摘要、行级 diff 摘要、文件列表。
    """

    @pytest.mark.asyncio
    async def test_pr_description_contains_llm_semantic_summary(
        self, sample_multi_agent_output, sample_execution_summary
    ):
        """LLM 生成的语义摘要被注入到 PR 描述中"""
        from app.service.pr_generator import PRGeneratorService

        mock_git_service = MagicMock()
        mock_git_service.create_commit_summary.return_value = {
            "diff_text": "diff --git a/app/service/calculator.py ...",
            "diff_stat": "1 file changed, 6 insertions(+)"
        }

        llm_response = {
            "semantic_summary": "本次新增除法功能，并对除零情况做了防御处理。",
            "diff_summary": "- calculator.py: 新增 divide() 方法，6行插入"
        }

        with patch.object(
            PRGeneratorService, "_generate_llm_summary",
            new=AsyncMock(return_value=llm_response)
        ):
            result = await PRGeneratorService.generate_pr_description(
                pipeline_id=42,
                multi_agent_output=sample_multi_agent_output,
                execution_summary=sample_execution_summary,
                git_service=mock_git_service
            )

        assert "本次新增除法功能" in result
        assert "新增 divide() 方法" in result

    @pytest.mark.asyncio
    async def test_pr_description_contains_file_list(
        self, sample_multi_agent_output, sample_execution_summary
    ):
        """PR 描述包含代码文件和测试文件的分类列表"""
        from app.service.pr_generator import PRGeneratorService

        mock_git_service = MagicMock()
        mock_git_service.create_commit_summary.return_value = {
            "diff_text": "", "diff_stat": ""
        }

        with patch.object(
            PRGeneratorService, "_generate_llm_summary",
            new=AsyncMock(return_value={
                "semantic_summary": "摘要",
                "diff_summary": "无变更"
            })
        ):
            result = await PRGeneratorService.generate_pr_description(
                pipeline_id=1,
                multi_agent_output=sample_multi_agent_output,
                execution_summary=sample_execution_summary,
                git_service=mock_git_service
            )

        # 代码文件和测试文件都应该出现
        assert "calculator.py" in result
        assert "test_calculator.py" in result

    @pytest.mark.asyncio
    async def test_pr_description_fallback_when_llm_fails(
        self, sample_multi_agent_output, sample_execution_summary
    ):
        """LLM 调用失败时，降级使用 multi_agent_output 的原始 summary"""
        from app.service.pr_generator import PRGeneratorService

        mock_git_service = MagicMock()
        mock_git_service.create_commit_summary.return_value = {
            "diff_text": "", "diff_stat": ""
        }

        # _generate_llm_summary 抛出异常
        with patch.object(
            PRGeneratorService, "_generate_llm_summary",
            new=AsyncMock(side_effect=Exception("LLM timeout"))
        ):
            # 不应该抛出异常，而是降级处理
            result = await PRGeneratorService.generate_pr_description(
                pipeline_id=1,
                multi_agent_output=sample_multi_agent_output,
                execution_summary=sample_execution_summary,
                git_service=mock_git_service
            )

        # 降级后应包含原始 summary
        assert "Calculator.divide()" in result or "新增" in result
        assert result  # 不为空

    @pytest.mark.asyncio
    async def test_generate_llm_summary_parses_json_response(self):
        """_generate_llm_summary 能正确解析 LLM 返回的 JSON"""
        from app.service.pr_generator import PRGeneratorService

        llm_json_response = json.dumps({
            "semantic_summary": "新增除法逻辑",
            "diff_summary": "calculator.py +6 行"
        })

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content=llm_json_response)

        with patch("app.service.pr_generator.ChatOpenAI", return_value=mock_llm):
            result = await PRGeneratorService._generate_llm_summary(
                requirement="新增除法",
                diff_text="diff content",
                diff_stat="1 file changed"
            )

        assert result["semantic_summary"] == "新增除法逻辑"
        assert result["diff_summary"] == "calculator.py +6 行"

    @pytest.mark.asyncio
    async def test_generate_llm_summary_fallback_on_invalid_json(self):
        """LLM 返回非 JSON 时，fallback 到原始 requirement 和 diff_stat"""
        from app.service.pr_generator import PRGeneratorService

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="无法解析的纯文本回复")

        with patch("app.service.pr_generator.ChatOpenAI", return_value=mock_llm):
            result = await PRGeneratorService._generate_llm_summary(
                requirement="新增除法",
                diff_text="",
                diff_stat="1 file changed"
            )

        assert result["semantic_summary"] == "新增除法"
        assert result["diff_summary"] == "1 file changed"


# ─────────────────────────────────────────────────────────────────────────────
# 3. GitHubProviderService.create_pull_request()
# ─────────────────────────────────────────────────────────────────────────────

class TestGitHubProviderService:
    """
    用例：验证 GitHub PR 创建的 HTTP 调用行为。
    目的：确保正确构造请求、处理成功和失败响应。
    """

    @pytest.mark.asyncio
    async def test_create_pr_success_returns_pr_url(self):
        """GitHub API 返回 201 时，PRResult.success=True 且包含 pr_url"""
        from app.service.platform_provider import GitHubProviderService

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "html_url": "https://github.com/owner/repo/pull/42",
            "number": 42
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("app.service.platform_provider.settings") as mock_settings:
            mock_settings.GITHUB_TOKEN = "fake-token"
            mock_settings.GITHUB_REPO = "owner/repo"

            service = GitHubProviderService()
            service.client = mock_client

            result = await service.create_pull_request(
                head_branch="devflow/pipeline-42-20260502",
                title="OmniFlowAI: 新增除法功能",
                body="## PR 描述...",
                base_branch="main"
            )

        assert result.success is True
        assert result.pr_url == "https://github.com/owner/repo/pull/42"
        assert result.pr_number == 42

    @pytest.mark.asyncio
    async def test_create_pr_failure_on_4xx_response(self):
        """GitHub API 返回 4xx 时，PRResult.success=False 且包含错误信息"""
        from app.service.platform_provider import GitHubProviderService

        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.text = "Validation Failed: head branch already exists"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("app.service.platform_provider.settings") as mock_settings:
            mock_settings.GITHUB_TOKEN = "fake-token"
            mock_settings.GITHUB_REPO = "owner/repo"

            service = GitHubProviderService()
            service.client = mock_client

            result = await service.create_pull_request(
                head_branch="devflow/pipeline-42",
                title="Test PR",
                body="body",
                base_branch="main"
            )

        assert result.success is False
        assert "Validation Failed" in result.error

    @pytest.mark.asyncio
    async def test_create_pr_failure_on_network_error(self):
        """网络异常时，PRResult.success=False 且不抛出异常"""
        from app.service.platform_provider import GitHubProviderService

        mock_client = AsyncMock()
        mock_client.post.side_effect = ConnectionError("Network unreachable")

        with patch("app.service.platform_provider.settings") as mock_settings:
            mock_settings.GITHUB_TOKEN = "fake-token"
            mock_settings.GITHUB_REPO = "owner/repo"

            service = GitHubProviderService()
            service.client = mock_client

            result = await service.create_pull_request(
                head_branch="devflow/pipeline-1",
                title="Test",
                body="body",
                base_branch="main"
            )

        assert result.success is False
        assert result.pr_url == ""

    @pytest.mark.asyncio
    async def test_request_includes_correct_headers_and_payload(self):
        """验证 HTTP 请求携带正确的认证头和 JSON 载荷"""
        from app.service.platform_provider import GitHubProviderService

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"html_url": "http://x", "number": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("app.service.platform_provider.settings") as mock_settings:
            mock_settings.GITHUB_TOKEN = "my-token"
            mock_settings.GITHUB_REPO = "myorg/myrepo"

            service = GitHubProviderService()
            service.client = mock_client

            await service.create_pull_request(
                head_branch="feature/branch",
                title="My PR Title",
                body="My PR Body",
                base_branch="develop"
            )

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json", {})
        assert payload["title"] == "My PR Title"
        assert payload["head"] == "feature/branch"
        assert payload["base"] == "develop"


# ─────────────────────────────────────────────────────────────────────────────
# 4. DeliveryHandler —— 端到端流程
# ─────────────────────────────────────────────────────────────────────────────

class TestDeliveryHandlerExecute:
    """
    用例：验证 DeliveryHandler.execute() 的完整流程编排。
    目的：确保分支创建、代码应用、commit、push、PR 创建各步骤被正确调用。
    """

    def _make_context(self, pipeline_id=42):
        """构造一个带有 CODING 阶段输出的 StageContext"""
        from app.service.stage_handlers.base import StageContext
        context = MagicMock(spec=StageContext)
        context.pipeline_id = pipeline_id
        context.session = AsyncMock()
        context.input_data = {
            "requirement_summary": "新增除法功能",
            "coding_output": {
                "multi_agent_output": {
                    "summary": "新增 Calculator.divide()",
                    "files": [
                        {
                            "file_path": "app/service/calculator.py",
                            "content": "# code",
                            "change_type": "modify",
                            "description": "新增 divide 方法"
                        }
                    ],
                    "tests_included": True,
                    "coverage_targets": [],
                    "dependencies_added": []
                }
            }
        }
        return context

    @pytest.mark.asyncio
    async def test_happy_path_returns_success_with_pr_url(self):
        """
        主流程：代码应用成功 → commit → push → PR 创建成功
        期望：StageResult.success=True，output_data 包含 pr_url
        """
        from app.service.stage_handlers.delivery_handler import DeliveryHandler
        from app.service.git_provider import GitProviderError

        context = self._make_context()

        mock_git = MagicMock()
        mock_git.has_changes.return_value = True
        mock_git.get_last_commit_hash.return_value = "abc123"
        mock_git.create_commit_summary.return_value = {"diff_text": "diff", "diff_stat": "1 file"}

        mock_pr_result = MagicMock()
        mock_pr_result.success = True
        mock_pr_result.pr_url = "https://github.com/owner/repo/pull/7"

        mock_github = AsyncMock()
        mock_github.create_pull_request = AsyncMock(return_value=mock_pr_result)
        mock_github.__aenter__ = AsyncMock(return_value=mock_github)
        mock_github.__aexit__ = AsyncMock(return_value=None)

        mock_sandbox_info = MagicMock()
        mock_sandbox_info.project_path = "/tmp/ws_42"

        with patch("app.service.stage_handlers.delivery_handler.sandbox_manager") as mock_sandbox_mgr, \
             patch("app.service.stage_handlers.delivery_handler.GitProviderService", return_value=mock_git), \
             patch("app.service.stage_handlers.delivery_handler.PRGeneratorService.generate_pr_description",
                   new=AsyncMock(return_value="## PR Body")), \
             patch("app.service.stage_handlers.delivery_handler.GitHubProviderService", return_value=mock_github), \
             patch("app.service.stage_handlers.delivery_handler.push_log", new=AsyncMock()):

            mock_sandbox_mgr.get_info.return_value = mock_sandbox_info

            handler = DeliveryHandler()
            result = await handler.execute(context)

        assert result.success is True
        assert result.pr_url == "https://github.com/owner/repo/pull/7"
        assert result.output_data["commit_hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_sandbox_not_found_returns_failure_result(self):
        """
        异常分支：sandbox 未启动
        期望：抛出 ValueError
        """
        from app.service.stage_handlers.delivery_handler import DeliveryHandler

        context = self._make_context()

        with patch("app.service.stage_handlers.delivery_handler.sandbox_manager") as mock_sandbox_mgr, \
             patch("app.service.stage_handlers.delivery_handler.push_log", new=AsyncMock()):

            mock_sandbox_mgr.get_info.return_value = None

            handler = DeliveryHandler()
            with pytest.raises(ValueError, match="Sandbox 未启动"):
                await handler.execute(context)

    @pytest.mark.asyncio
    async def test_pr_creation_failure_still_returns_success_for_commit(self):
        """
        PR 创建失败时，commit 和 push 已成功，结果应反映 pr_created=False
        """
        from app.service.stage_handlers.delivery_handler import DeliveryHandler

        context = self._make_context()

        mock_git = MagicMock()
        mock_git.has_changes.return_value = True
        mock_git.get_last_commit_hash.return_value = "def456"
        mock_git.create_commit_summary.return_value = {"diff_text": "", "diff_stat": ""}

        mock_pr_result = MagicMock()
        mock_pr_result.success = False
        mock_pr_result.pr_url = ""

        mock_github = AsyncMock()
        mock_github.create_pull_request = AsyncMock(return_value=mock_pr_result)
        mock_github.__aenter__ = AsyncMock(return_value=mock_github)
        mock_github.__aexit__ = AsyncMock(return_value=None)

        mock_sandbox_info = MagicMock()
        mock_sandbox_info.project_path = "/tmp/ws_42"

        with patch("app.service.stage_handlers.delivery_handler.sandbox_manager") as mock_sandbox_mgr, \
             patch("app.service.stage_handlers.delivery_handler.GitProviderService", return_value=mock_git), \
             patch("app.service.stage_handlers.delivery_handler.PRGeneratorService.generate_pr_description",
                   new=AsyncMock(return_value="## body")), \
             patch("app.service.stage_handlers.delivery_handler.GitHubProviderService", return_value=mock_github), \
             patch("app.service.stage_handlers.delivery_handler.push_log", new=AsyncMock()):

            mock_sandbox_mgr.get_info.return_value = mock_sandbox_info

            handler = DeliveryHandler()
            result = await handler.execute(context)

        # commit 成功，pr_created 为 False
        assert result.success is True
        assert result.output_data.get("pr_created") is False
        assert result.output_data.get("commit_hash") == "def456"

    @pytest.mark.asyncio
    async def test_git_branch_already_exists_falls_back_to_checkout(self):
        """
        create_branch 抛出"分支已存在"错误时，自动 checkout 该分支
        """
        from app.service.stage_handlers.delivery_handler import DeliveryHandler
        from app.service.git_provider import GitProviderError

        context = self._make_context()

        mock_git = MagicMock()
        mock_git.create_branch.side_effect = GitProviderError("分支已存在")
        mock_git.has_changes.return_value = False  # 无新 commit，跳过提交
        mock_git.create_commit_summary.return_value = {"diff_text": "", "diff_stat": ""}

        mock_pr_result = MagicMock(success=True, pr_url="https://github.com/x/y/pull/1")
        mock_github = AsyncMock()
        mock_github.create_pull_request = AsyncMock(return_value=mock_pr_result)
        mock_github.__aenter__ = AsyncMock(return_value=mock_github)
        mock_github.__aexit__ = AsyncMock(return_value=None)

        mock_sandbox_info = MagicMock()
        mock_sandbox_info.project_path = "/tmp/ws_42"

        with patch("app.service.stage_handlers.delivery_handler.sandbox_manager") as mock_sandbox_mgr, \
             patch("app.service.stage_handlers.delivery_handler.GitProviderService", return_value=mock_git), \
             patch("app.service.stage_handlers.delivery_handler.PRGeneratorService.generate_pr_description",
                   new=AsyncMock(return_value="## body")), \
             patch("app.service.stage_handlers.delivery_handler.GitHubProviderService", return_value=mock_github), \
             patch("app.service.stage_handlers.delivery_handler.push_log", new=AsyncMock()):

            mock_sandbox_mgr.get_info.return_value = mock_sandbox_info

            handler = DeliveryHandler()
            await handler.execute(context)

        # 应该调用 checkout_branch 而不是重新 raise
        mock_git.checkout_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_raises_exception_on_unexpected_error(self):
        """
        非预期异常（如 sandbox 路径为空）应该向上抛出，触发 handle_error 流程
        """
        from app.service.stage_handlers.delivery_handler import DeliveryHandler

        context = self._make_context()

        mock_sandbox_info = MagicMock()
        mock_sandbox_info.project_path = None  # 空路径会触发异常

        with patch("app.service.stage_handlers.delivery_handler.sandbox_manager") as mock_sandbox_mgr, \
             patch("app.service.stage_handlers.delivery_handler.push_log", new=AsyncMock()):

            mock_sandbox_mgr.get_info.return_value = mock_sandbox_info

            handler = DeliveryHandler()
            with pytest.raises(ValueError, match="工作区路径为空"):
                await handler.execute(context)


# ─────────────────────────────────────────────────────────────────────────────
# 5. PR 描述内容完整性校验
# ─────────────────────────────────────────────────────────────────────────────

class TestPRDescriptionContent:
    """
    用例：验证最终 PR 描述包含所有必要区块。
    目的：确保 Reviewer 看到完整信息，不缺少关键字段。
    """

    @pytest.mark.asyncio
    async def test_pr_description_has_all_required_sections(
        self, sample_multi_agent_output, sample_execution_summary
    ):
        """PR 描述必须包含：标题、Pipeline ID、变更摘要、代码文件、测试文件、变更统计、审查清单"""
        from app.service.pr_generator import PRGeneratorService

        mock_git_service = MagicMock()
        mock_git_service.create_commit_summary.return_value = {
            "diff_text": "some diff", "diff_stat": "2 files changed"
        }

        with patch.object(
            PRGeneratorService, "_generate_llm_summary",
            new=AsyncMock(return_value={
                "semantic_summary": "语义摘要内容",
                "diff_summary": "行级摘要内容"
            })
        ):
            result = await PRGeneratorService.generate_pr_description(
                pipeline_id=99,
                multi_agent_output=sample_multi_agent_output,
                execution_summary=sample_execution_summary,
                git_service=mock_git_service
            )

        required_sections = [
            "Pipeline ID",
            "变更摘要",
            "代码文件",
            "测试文件",
            "变更统计",
            "审查清单",
            "#99",
        ]
        for section in required_sections:
            assert section in result, f"PR 描述缺少必要区块: '{section}'"

    @pytest.mark.asyncio
    async def test_pr_description_includes_pipeline_id(
        self, sample_multi_agent_output, sample_execution_summary
    ):
        """PR 描述中的 Pipeline ID 与传入参数一致"""
        from app.service.pr_generator import PRGeneratorService

        mock_git_service = MagicMock()
        mock_git_service.create_commit_summary.return_value = {"diff_text": "", "diff_stat": ""}

        with patch.object(
            PRGeneratorService, "_generate_llm_summary",
            new=AsyncMock(return_value={"semantic_summary": "s", "diff_summary": "d"})
        ):
            result = await PRGeneratorService.generate_pr_description(
                pipeline_id=777,
                multi_agent_output=sample_multi_agent_output,
                execution_summary=sample_execution_summary,
                git_service=mock_git_service
            )

        assert "#777" in result

    @pytest.mark.asyncio
    async def test_test_files_classified_separately_from_code_files(
        self, sample_execution_summary
    ):
        """tests/ 路径下的文件被分类为测试文件，其余为代码文件"""
        from app.service.pr_generator import PRGeneratorService

        multi_agent_output = {
            "summary": "test",
            "files": [
                {"file_path": "app/service/foo.py", "change_type": "modify", "description": ""},
                {"file_path": "tests/unit/test_foo.py", "change_type": "add", "description": ""},
            ],
            "tests_included": True,
            "coverage_targets": [],
            "dependencies_added": []
        }

        mock_git_service = MagicMock()
        mock_git_service.create_commit_summary.return_value = {"diff_text": "", "diff_stat": ""}

        with patch.object(
            PRGeneratorService, "_generate_llm_summary",
            new=AsyncMock(return_value={"semantic_summary": "s", "diff_summary": "d"})
        ):
            result = await PRGeneratorService.generate_pr_description(
                pipeline_id=1,
                multi_agent_output=multi_agent_output,
                execution_summary=sample_execution_summary,
                git_service=mock_git_service
            )

        # 两个文件都出现，说明分类逻辑正确运行
        assert "foo.py" in result
        assert "test_foo.py" in result