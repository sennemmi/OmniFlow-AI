"""
端到端全链路测试

测试场景：
1. 输入需求 -> Pipeline 启动 -> 状态流转
2. 人工审批/驳回流程
3. 可视化工作区圈选 -> 修改 -> HMR -> MR
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class TestPipelineE2E:
    """
    Pipeline 端到端测试
    
    环节一：在控制台输入需求，清晰展示 Requirement -> Design -> Coding 的状态流转
    环节一：在 Design 阶段人为点击 Reject 并输入意见，展示系统打回重做的流转
    """

    def test_create_pipeline_from_requirement(self, page: Page):
        """测试从需求创建 Pipeline"""
        # 访问控制台
        page.goto("http://localhost:5173/console")
        
        # 点击创建 Pipeline
        page.click("text=创建 Pipeline")
        
        # 输入需求
        page.fill("[placeholder='输入需求描述']", "实现用户管理功能，包含 CRUD 操作")
        
        # 提交
        page.click("text=开始")
        
        # 验证 Pipeline 创建成功
        expect(page.locator("text=REQUIREMENT")).to_be_visible()

    def test_pipeline_state_transitions(self, page: Page):
        """测试 Pipeline 状态流转"""
        page.goto("http://localhost:5173/pipelines/1")
        
        # 验证各阶段存在
        stages = ["REQUIREMENT", "DESIGN", "CODING", "TESTING", "CODE_REVIEW", "DELIVERY"]
        for stage in stages:
            expect(page.locator(f"text={stage}")).to_be_visible()

    def test_human_approve_at_design_stage(self, page: Page):
        """测试在 Design 阶段人工审批"""
        page.goto("http://localhost:5173/pipelines/1")
        
        # 等待 DESIGN 阶段
        expect(page.locator("text=等待审批")).to_be_visible()
        
        # 点击审批
        page.click("text=审批")
        
        # 输入审批意见
        page.fill("[placeholder='输入审批意见']", "设计方案合理，继续执行")
        
        # 确认
        page.click("text=确认通过")
        
        # 验证状态变为 RUNNING
        expect(page.locator("text=RUNNING")).to_be_visible()

    def test_human_reject_at_design_stage(self, page: Page):
        """测试在 Design 阶段人工驳回"""
        page.goto("http://localhost:5173/pipelines/1")
        
        # 等待 DESIGN 阶段
        expect(page.locator("text=等待审批")).to_be_visible()
        
        # 点击驳回
        page.click("text=驳回")
        
        # 输入驳回原因
        page.fill("[placeholder='输入驳回原因']", "缺少数据库设计，请补充")
        
        # 确认驳回
        page.click("text=确认驳回")
        
        # 验证状态回退
        expect(page.locator("text=已驳回")).to_be_visible()


class TestInjectorE2E:
    """
    Injector 端到端测试
    
    环节二：打开前端业务页面，点开悬浮球，圈选一个 Button
    环节二：对话框输入"将按钮改为红色并加粗"，点击提交
    环节二：页面不刷新，按钮样式瞬间变为红色（Vite HMR 生效）
    环节二：展示右侧弹出的 Diff 对比和 MR 链接
    """

    def test_open_injector_floating_ball(self, page: Page):
        """测试打开 Injector 悬浮球"""
        # 访问业务页面
        page.goto("http://localhost:5173/workspace")
        
        # 点击悬浮球
        page.click("[data-testid='injector-floating-ball']")
        
        # 验证 Injector 面板打开
        expect(page.locator("text=OmniFlow Injector")).to_be_visible()

    def test_select_element_on_page(self, page: Page):
        """测试在页面上圈选元素"""
        page.goto("http://localhost:5173/workspace")
        
        # 打开 Injector
        page.click("[data-testid='injector-floating-ball']")
        
        # 点击圈选按钮
        page.click("text=圈选元素")
        
        # 点击页面上的按钮
        page.click("button:has-text('提交')")
        
        # 验证元素被选中
        expect(page.locator("text=已选择: button")).to_be_visible()

    def test_submit_modification_request(self, page: Page):
        """测试提交修改请求"""
        page.goto("http://localhost:5173/workspace")
        
        # 打开 Injector 并圈选元素
        page.click("[data-testid='injector-floating-ball']")
        page.click("text=圈选元素")
        page.click("button:has-text('提交')")
        
        # 输入修改请求
        page.fill("[placeholder='描述你想要的修改']", "将按钮改为红色并加粗")
        
        # 提交
        page.click("text=生成修改")
        
        # 验证 AI 响应
        expect(page.locator("text=修改建议")).to_be_visible()

    def test_hmr_applies_changes_instantly(self, page: Page):
        """测试 HMR 即时生效"""
        page.goto("http://localhost:5173/workspace")
        
        # 执行修改流程
        page.click("[data-testid='injector-floating-ball']")
        page.click("text=圈选元素")
        page.click("button:has-text('提交')")
        page.fill("[placeholder='描述你想要的修改']", "将按钮改为红色")
        page.click("text=生成修改")
        
        # 确认修改
        page.click("text=确认修改")
        
        # 验证按钮样式变化（不刷新页面）
        button = page.locator("button:has-text('提交')")
        expect(button).to_have_css("color", "rgb(255, 0, 0)")

    def test_diff_viewer_shows_changes(self, page: Page):
        """测试 Diff 查看器显示变更"""
        page.goto("http://localhost:5173/workspace")
        
        # 执行修改流程
        page.click("[data-testid='injector-floating-ball']")
        page.click("text=圈选元素")
        page.click("button:has-text('提交')")
        page.fill("[placeholder='描述你想要的修改']", "将按钮改为红色")
        page.click("text=生成修改")
        
        # 验证 Diff 面板
        expect(page.locator("text=代码对比")).to_be_visible()
        expect(page.locator("text=原始")).to_be_visible()
        expect(page.locator("text=修改后")).to_be_visible()

    def test_mr_link_generation(self, page: Page):
        """测试 MR 链接生成"""
        page.goto("http://localhost:5173/workspace")
        
        # 执行修改流程并确认
        page.click("[data-testid='injector-floating-ball']")
        page.click("text=圈选元素")
        page.click("button:has-text('提交')")
        page.fill("[placeholder='描述你想要的修改']", "将按钮改为红色")
        page.click("text=生成修改")
        page.click("text=确认修改")
        page.click("text=创建 MR")
        
        # 验证 MR 链接
        expect(page.locator("text=MR 已创建")).to_be_visible()
        expect(page.locator("a:has-text('查看 MR')")).to_be_visible()


class TestDemoChecklist:
    """
    现场演示验证 CheckList
    """

    def test_demo_step_1_pipeline_creation(self, page: Page):
        """演示环节一：Pipeline 创建与状态流转"""
        page.goto("http://localhost:5173/console")
        
        # 创建 Pipeline
        page.click("text=创建 Pipeline")
        page.fill("[placeholder='输入需求描述']", "实现用户管理功能")
        page.click("text=开始")
        
        # 验证状态流转
        expect(page.locator("text=REQUIREMENT")).to_be_visible(timeout=5000)

    def test_demo_step_2_human_reject(self, page: Page):
        """演示环节一：人工驳回流程"""
        page.goto("http://localhost:5173/pipelines/1")
        
        # 等待审批
        expect(page.locator("text=等待审批")).to_be_visible(timeout=10000)
        
        # 驳回
        page.click("text=驳回")
        page.fill("[placeholder='输入驳回原因']", "需要补充数据库设计")
        page.click("text=确认驳回")
        
        # 验证回退
        expect(page.locator("text=已驳回")).to_be_visible()

    def test_demo_step_3_element_selection(self, page: Page):
        """演示环节二：元素圈选"""
        page.goto("http://localhost:5173/workspace")
        
        # 打开 Injector
        page.click("[data-testid='injector-floating-ball']")
        
        # 圈选按钮
        page.click("text=圈选元素")
        page.click("button:has-text('提交')")
        
        # 验证选中
        expect(page.locator("text=已选择")).to_be_visible()

    def test_demo_step_4_ai_modification(self, page: Page):
        """演示环节二：AI 修改与 HMR"""
        page.goto("http://localhost:5173/workspace")
        
        # 圈选并请求修改
        page.click("[data-testid='injector-floating-ball']")
        page.click("text=圈选元素")
        page.click("button:has-text('提交')")
        page.fill("[placeholder='描述你想要的修改']", "将按钮改为红色并加粗")
        page.click("text=生成修改")
        
        # 确认修改
        page.click("text=确认修改")
        
        # 验证 HMR 生效
        button = page.locator("button:has-text('提交')")
        expect(button).to_have_css("color", "rgb(255, 0, 0)", timeout=3000)

    def test_demo_step_5_mr_creation(self, page: Page):
        """演示环节二：MR 创建"""
        page.goto("http://localhost:5173/workspace")
        
        # 完成修改流程
        page.click("[data-testid='injector-floating-ball']")
        page.click("text=圈选元素")
        page.click("button:has-text('提交')")
        page.fill("[placeholder='描述你想要的修改']", "将按钮改为红色")
        page.click("text=生成修改")
        page.click("text=确认修改")
        page.click("text=创建 MR")
        
        # 验证 MR 创建
        expect(page.locator("text=MR 已创建")).to_be_visible(timeout=10000)
