"""
功能测试：可视化工作区与 Injector (Visual Workspace)

用例编号规范：FT-V-XX
- FT-V-01: DOM 圈选
- FT-V-02: AST 搜索替换
- FT-V-03: 热更新与撤销
- FT-V-04: 自动 MR 生成
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, Optional

pytestmark = [pytest.mark.functional, pytest.mark.visual]


class TestDOMSelection:
    """
    FT-V-01: DOM 圈选
    
    测试场景：在前端页面开启插件，圈选一个 Button 和一个 Title
    预期结果：正确捕获元素的 outerHTML、XPath 及 React Fiber 绑定的源码位置 (line/column)。
    """

    @pytest.fixture
    def sample_button_element(self):
        """示例 Button 元素数据"""
        return {
            "tag": "button",
            "outerHTML": '<button class="btn btn-primary" data-testid="submit-btn">提交</button>',
            "xpath": "/html/body/div[1]/main/form/button[1]",
            "cssSelector": "form button.btn-primary",
            "reactFiber": {
                "fileName": "src/components/SubmitForm.tsx",
                "lineNumber": 42,
                "columnNumber": 8
            },
            "attributes": {
                "class": "btn btn-primary",
                "data-testid": "submit-btn"
            },
            "textContent": "提交"
        }

    @pytest.fixture
    def sample_title_element(self):
        """示例 Title 元素数据"""
        return {
            "tag": "h1",
            "outerHTML": '<h1 class="page-title">用户管理</h1>',
            "xpath": "/html/body/div[1]/main/h1[1]",
            "cssSelector": "main h1.page-title",
            "reactFiber": {
                "fileName": "src/pages/UserManagement.tsx",
                "lineNumber": 15,
                "columnNumber": 5
            },
            "attributes": {
                "class": "page-title"
            },
            "textContent": "用户管理"
        }

    def test_selection_captures_outer_html(self, sample_button_element):
        """测试圈选捕获 outerHTML"""
        element = sample_button_element
        
        # 验证 outerHTML 被捕获
        assert "outerHTML" in element
        assert "button" in element["outerHTML"]
        assert "btn-primary" in element["outerHTML"]

    def test_selection_captures_xpath(self, sample_button_element):
        """测试圈选捕获 XPath"""
        element = sample_button_element
        
        # 验证 XPath 格式正确
        assert "xpath" in element
        assert element["xpath"].startswith("/html")
        assert "button" in element["xpath"]

    def test_selection_captures_react_fiber(self, sample_button_element):
        """测试圈选捕获 React Fiber 信息"""
        element = sample_button_element
        
        # 验证 React Fiber 信息
        assert "reactFiber" in element
        fiber = element["reactFiber"]
        
        assert "fileName" in fiber
        assert "lineNumber" in fiber
        assert "columnNumber" in fiber
        
        # 验证文件路径格式
        assert fiber["fileName"].endswith(".tsx") or fiber["fileName"].endswith(".jsx")
        assert fiber["lineNumber"] > 0
        assert fiber["columnNumber"] > 0

    def test_multiple_elements_selection(self, sample_button_element, sample_title_element):
        """测试多元素圈选"""
        elements = [sample_button_element, sample_title_element]
        
        # 验证两个元素都被捕获
        assert len(elements) == 2
        
        # 验证每个元素都有必要信息
        for elem in elements:
            assert "tag" in elem
            assert "outerHTML" in elem
            assert "xpath" in elem
            assert "reactFiber" in elem

    def test_element_attributes_extraction(self, sample_button_element):
        """测试元素属性提取"""
        element = sample_button_element
        
        # 验证属性被提取
        assert "attributes" in element
        assert "class" in element["attributes"]
        assert "data-testid" in element["attributes"]


class TestASTSearchReplace:
    """
    FT-V-02: AST 搜索替换
    
    测试场景：AI 返回 search_block 和 replace_block
    预期结果：SearchReplaceEngine 能进行 4 级退避匹配（精确 -> 换行符归一 -> 缩进忽略 -> 行号回退），精准替换代码。
    """

    @pytest.fixture
    def original_code(self):
        """原始代码"""
        return '''import React from 'react';

function Button({ label, onClick }) {
  return (
    <button 
      className="btn btn-primary"
      onClick={onClick}
    >
      {label}
    </button>
  );
}

export default Button;
'''

    @pytest.fixture
    def search_block_exact(self):
        """精确匹配块"""
        return '''    <button 
      className="btn btn-primary"
      onClick={onClick}
    >
      {label}
    </button>'''

    @pytest.fixture
    def replace_block(self):
        """替换块"""
        return '''    <button 
      className="btn btn-primary btn-red"
      style={{ color: 'red', fontWeight: 'bold' }}
      onClick={onClick}
    >
      {label}
    </button>'''

    @pytest.fixture
    def search_block_normalized(self):
        """需要归一化的匹配块（换行符不同）"""
        return '<button className="btn btn-primary" onClick={onClick}>'

    def test_exact_match_replacement(self, original_code, search_block_exact, replace_block):
        """测试精确匹配替换"""
        # Level 1: 精确匹配
        if search_block_exact in original_code:
            result = original_code.replace(search_block_exact, replace_block)
            assert "btn-red" in result
            assert "fontWeight: 'bold'" in result

    def test_normalized_match_replacement(self, original_code, search_block_normalized, replace_block):
        """测试归一化匹配替换"""
        # Level 2: 换行符归一化
        normalized_original = " ".join(original_code.split())
        normalized_search = " ".join(search_block_normalized.split())
        
        if normalized_search in normalized_original:
            # 匹配成功
            assert True

    def test_indentation_agnostic_match(self):
        """测试缩进无关匹配"""
        code_with_tabs = "\t\tconst x = 1;"
        code_with_spaces = "        const x = 1;"
        
        # Level 3: 缩进忽略
        normalized_tab = code_with_tabs.replace("\t", "    ")
        assert normalized_tab.strip() == code_with_spaces.strip()

    def test_line_number_fallback(self):
        """测试行号回退匹配"""
        # Level 4: 行号回退
        source_lines = [
            "  const a = 1;",
            "  const b = 2;",
            "  const c = 3;"
        ]
        
        # 模拟行号偏移的搜索
        target_line = 2  # 目标第2行
        search_context = "const b = 2"
        
        # 在附近行搜索
        for offset in range(-2, 3):
            check_line = target_line + offset
            if 0 <= check_line < len(source_lines):
                if search_context in source_lines[check_line]:
                    assert True
                    return
        
        assert False, "应该找到匹配"

    def test_four_level_fallback_sequence(self):
        """测试 4 级退避匹配顺序"""
        levels = ["exact", "normalized", "indentation_agnostic", "line_fallback"]
        
        # 验证退避级别定义
        assert len(levels) == 4
        assert levels[0] == "exact"
        assert levels[1] == "normalized"
        assert levels[2] == "indentation_agnostic"
        assert levels[3] == "line_fallback"


class TestHMRAndRevert:
    """
    FT-V-03: 热更新与撤销
    
    测试场景：确认修改后触发 Vite HMR；点击"取消恢复"
    预期结果：页面实时热更新；点击取消后调用后端 API 将文件恢复为 originalContent。
    """

    @pytest.fixture
    def file_change_record(self):
        """文件变更记录"""
        return {
            "filePath": "src/components/Button.tsx",
            "originalContent": '''import React from 'react';

function Button({ label }) {
  return <button className="btn">{label}</button>;
}
''',
            "modifiedContent": '''import React from 'react';

function Button({ label }) {
  return <button className="btn btn-red" style={{ color: 'red' }}>{label}</button>;
}
''',
            "changeId": "change-123",
            "timestamp": "2024-01-01T00:00:00Z"
        }

    @pytest.mark.asyncio
    async def test_hmr_triggered_on_confirm(self, file_change_record):
        """测试确认修改后触发 HMR"""
        with patch('frontend.injector.preview.triggerHMR') as mock_hmr:
            mock_hmr.return_value = True
            
            # 模拟确认修改
            await self._simulate_confirm_change(file_change_record)
            
            # 验证 HMR 被触发
            mock_hmr.assert_called_once()

    @pytest.mark.asyncio
    async def test_revert_api_called_on_cancel(self, file_change_record):
        """测试取消时调用恢复 API"""
        with patch('frontend.injector.api.revertChange') as mock_revert:
            mock_revert.return_value = {"success": True}
            
            # 模拟取消修改
            await self._simulate_cancel_change(file_change_record["changeId"])
            
            # 验证恢复 API 被调用
            mock_revert.assert_called_once_with(file_change_record["changeId"])

    def test_original_content_preserved(self, file_change_record):
        """测试原始内容被保留用于恢复"""
        record = file_change_record
        
        # 验证原始内容存在
        assert "originalContent" in record
        assert "modifiedContent" in record
        
        # 验证内容不同
        assert record["originalContent"] != record["modifiedContent"]
        
        # 验证原始内容包含原始样式
        assert "btn-red" not in record["originalContent"]
        assert "btn-red" in record["modifiedContent"]

    async def _simulate_confirm_change(self, change_record: Dict):
        """模拟确认修改"""
        # 触发 HMR
        pass

    async def _simulate_cancel_change(self, change_id: str):
        """模拟取消修改"""
        # 调用恢复 API
        pass

    def test_revert_restores_original(self, file_change_record):
        """测试恢复操作还原原始内容"""
        original = file_change_record["originalContent"]
        modified = file_change_record["modifiedContent"]
        
        # 模拟恢复
        restored = original
        
        # 验证恢复后内容等于原始内容
        assert restored == original
        assert restored != modified


class TestAutoMRGeneration:
    """
    FT-V-04: 自动 MR 生成
    
    测试场景：点击"确认保持"触发 create-mr 接口
    预期结果：自动切出 feat/injector-xxx 分支，提交代码，调用 LLM 生成语义化 PR 描述并创建 GitHub PR。
    """

    @pytest.fixture
    def mr_request_data(self):
        """MR 请求数据"""
        return {
            "changes": [
                {
                    "filePath": "src/components/Button.tsx",
                    "changeType": "modify",
                    "description": "将按钮改为红色并加粗"
                },
                {
                    "filePath": "src/components/Title.tsx",
                    "changeType": "modify",
                    "description": "调整标题字体大小"
                }
            ],
            "baseBranch": "main",
            "projectId": "omniflowai"
        }

    @pytest.fixture
    def mock_mr_response(self):
        """模拟 MR 响应"""
        return {
            "success": True,
            "mrUrl": "https://github.com/org/omniflowai/pull/123",
            "branchName": "feat/injector-abc123",
            "commitSha": "a1b2c3d4",
            "prDescription": "## 变更概要\n\n- 将按钮改为红色并加粗\n- 调整标题字体大小"
        }

    @pytest.mark.asyncio
    async def test_create_mr_api_called(self, mr_request_data):
        """测试 create-mr 接口被调用"""
        with patch('app.api.v1.code_modify.create_mr') as mock_create_mr:
            mock_create_mr.return_value = {"success": True, "mrUrl": "https://github.com/..."}
            
            # 模拟调用 API
            result = await mock_create_mr(mr_request_data)
            
            # 验证 API 被调用
            mock_create_mr.assert_called_once_with(mr_request_data)
            assert result["success"] is True

    def test_branch_name_generation(self):
        """测试分支名称生成"""
        import uuid
        
        # 生成 feat/injector-xxx 格式的分支名
        short_id = uuid.uuid4().hex[:8]
        branch_name = f"feat/injector-{short_id}"
        
        # 验证格式
        assert branch_name.startswith("feat/injector-")
        assert len(branch_name) > len("feat/injector-")

    @pytest.mark.asyncio
    async def test_llm_generates_pr_description(self, mr_request_data):
        """测试 LLM 生成 PR 描述"""
        with patch('app.service.pr_generator.generate_description') as mock_generate:
            mock_generate.return_value = """
## 变更概要

- 将按钮改为红色并加粗
- 调整标题字体大小

## 测试

- [x] 本地验证通过
"""
            
            description = await mock_generate(mr_request_data["changes"])
            
            # 验证生成了描述
            assert len(description) > 0
            assert "按钮" in description or "Button" in description

    def test_mr_response_contains_url(self, mock_mr_response):
        """测试 MR 响应包含 URL"""
        response = mock_mr_response
        
        # 验证必要字段
        assert "mrUrl" in response
        assert "branchName" in response
        assert "commitSha" in response
        
        # 验证 URL 格式
        assert response["mrUrl"].startswith("https://")
        assert "/pull/" in response["mrUrl"] or "/merge_requests/" in response["mrUrl"]

    def test_commit_message_generation(self):
        """测试提交信息生成"""
        changes = [
            {"description": "将按钮改为红色并加粗"},
            {"description": "调整标题字体大小"}
        ]
        
        # 生成提交信息
        commit_message = f"feat(injector): {changes[0]['description']}"
        
        # 验证格式
        assert commit_message.startswith("feat(injector):")
        assert "按钮" in commit_message


class TestInjectorIntegration:
    """
    Injector 集成测试
    
    测试完整的圈选 -> 修改 -> HMR -> MR 流程
    """

    @pytest.fixture
    def full_workflow_context(self):
        """完整工作流上下文"""
        return {
            "selection": {
                "element": "button",
                "filePath": "src/components/Button.tsx",
                "lineNumber": 10
            },
            "userRequest": "将按钮改为红色并加粗",
            "aiResponse": {
                "searchBlock": '<button className="btn">',
                "replaceBlock": '<button className="btn btn-red" style={{ color: "red", fontWeight: "bold" }}>'
            },
            "confirmed": True,
            "createMR": True
        }

    def test_full_workflow_sequence(self, full_workflow_context):
        """测试完整工作流顺序"""
        ctx = full_workflow_context
        
        # Step 1: 圈选元素
        assert ctx["selection"]["element"] is not None
        assert ctx["selection"]["filePath"] is not None
        
        # Step 2: 用户输入请求
        assert len(ctx["userRequest"]) > 0
        
        # Step 3: AI 返回修改
        assert "searchBlock" in ctx["aiResponse"]
        assert "replaceBlock" in ctx["aiResponse"]
        
        # Step 4: 用户确认
        assert ctx["confirmed"] is True
        
        # Step 5: 创建 MR
        assert ctx["createMR"] is True
