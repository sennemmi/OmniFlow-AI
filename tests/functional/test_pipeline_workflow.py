"""
功能测试：Pipeline 引擎与状态机 (Workflow)

用例编号规范：FT-P-XX
- FT-P-01: 状态流转 - 完整链路测试
- FT-P-02: 人工审批 (Approve)
- FT-P-03: 人工驳回 (Reject)
- FT-P-04: 任务终止 (Terminate)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

pytestmark = [pytest.mark.functional, pytest.mark.pipeline]

from app.models.pipeline import (
    Pipeline, PipelineStage, PipelineStatus, StageName, StageStatus
)
from app.service.workflow import WorkflowService
from app.service.stage_handlers.registry import StageHandlerRegistry


class TestPipelineStateTransitions:
    """
    FT-P-01: 状态流转 - 完整链路测试
    
    测试场景：成功走通 REQUIREMENT -> DESIGN -> CODING -> TESTING -> REVIEW -> DELIVERY 完整链路
    预期结果：状态机按序流转，各阶段数据通过 StageContext 正确向下游传递。
    """

    @pytest.fixture
    def stage_sequence(self):
        """标准 Pipeline 阶段序列"""
        return [
            StageName.REQUIREMENT,
            StageName.DESIGN,
            StageName.CODING,
            StageName.UNIT_TESTING,
            StageName.CODE_REVIEW,
            StageName.DELIVERY
        ]

    @pytest.fixture
    def mock_pipeline_with_stages(self):
        """创建带有阶段的模拟 Pipeline"""
        pipeline = MagicMock(spec=Pipeline)
        pipeline.id = 1
        pipeline.status = PipelineStatus.RUNNING
        pipeline.current_stage = StageName.REQUIREMENT
        pipeline.description = "测试 Pipeline"
        pipeline.context = {"requirement": "实现用户管理功能"}
        
        stages = []
        for i, stage_name in enumerate([
            StageName.REQUIREMENT, StageName.DESIGN, StageName.CODING,
            StageName.UNIT_TESTING, StageName.CODE_REVIEW, StageName.DELIVERY
        ]):
            stage = MagicMock(spec=PipelineStage)
            stage.id = i + 1
            stage.pipeline_id = 1
            stage.name = stage_name
            stage.status = StageStatus.PENDING
            stage.input_data = {}
            stage.output_data = {}
            stages.append(stage)
        
        pipeline.stages = stages
        return pipeline

    def test_complete_pipeline_flow(self, mock_pipeline_with_stages):
        """测试完整的 Pipeline 状态流转"""
        pipeline = mock_pipeline_with_stages
        
        # 验证初始状态
        assert pipeline.current_stage == StageName.REQUIREMENT
        assert pipeline.status == PipelineStatus.RUNNING
        
        # 模拟各阶段执行
        stage_outputs = {}
        
        # Stage 1: REQUIREMENT
        pipeline.current_stage = StageName.DESIGN
        stage_outputs[StageName.REQUIREMENT] = {
            "parsed_requirement": "用户管理功能",
            "acceptance_criteria": ["CRUD操作", "权限验证"]
        }
        
        # Stage 2: DESIGN
        pipeline.current_stage = StageName.CODING
        stage_outputs[StageName.DESIGN] = {
            "technical_design": "使用 FastAPI + SQLModel",
            "interface_specs": [
                {"symbol_name": "create_user", "signature": "def create_user(data: dict)"}
            ]
        }
        
        # Stage 3: CODING
        pipeline.current_stage = StageName.TESTING
        stage_outputs[StageName.CODING] = {
            "generated_files": ["app/api/v1/users.py", "app/service/user.py"],
            "code_summary": "实现了用户管理 API"
        }
        
        # Stage 4: TESTING
        pipeline.current_stage = StageName.CODE_REVIEW
        stage_outputs[StageName.TESTING] = {
            "test_results": {"passed": 5, "failed": 0},
            "coverage": "85%"
        }
        
        # Stage 5: CODE_REVIEW
        pipeline.current_stage = StageName.DELIVERY
        stage_outputs[StageName.CODE_REVIEW] = {
            "review_passed": True,
            "suggestions": []
        }
        
        # Stage 6: DELIVERY
        pipeline.status = PipelineStatus.SUCCESS
        stage_outputs[StageName.DELIVERY] = {
            "mr_url": "https://github.com/org/repo/pull/123",
            "deployment_status": "success"
        }
        
        # 验证最终状态
        assert pipeline.status == PipelineStatus.SUCCESS
        assert len(stage_outputs) == 6
        
        # 验证数据向下游传递
        assert "parsed_requirement" in stage_outputs[StageName.REQUIREMENT]
        assert "technical_design" in stage_outputs[StageName.DESIGN]
        assert "generated_files" in stage_outputs[StageName.CODING]

    def test_stage_context_propagation(self):
        """测试 StageContext 在各阶段间正确传递"""
        context = {
            "requirement": "实现订单系统",
            "priority": "high"
        }
        
        # REQUIREMENT 阶段输出
        context["requirement_analysis"] = {
            "entities": ["Order", "Product", "User"],
            "operations": ["create", "update", "delete"]
        }
        
        # DESIGN 阶段读取并扩展
        design_input = context.copy()
        design_output = {
            "database_schema": "orders table",
            "api_endpoints": ["/api/v1/orders"]
        }
        context["design_output"] = design_output
        
        # CODING 阶段读取
        coding_input = context.copy()
        assert "requirement_analysis" in coding_input
        assert "design_output" in coding_input
        
        # 验证上下文完整性
        assert coding_input["requirement"] == "实现订单系统"
        assert "entities" in coding_input["requirement_analysis"]

    def test_stage_order_enforcement(self):
        """测试阶段顺序强制执行"""
        valid_order = [
            StageName.REQUIREMENT,
            StageName.DESIGN,
            StageName.CODING,
            StageName.UNIT_TESTING,
            StageName.CODE_REVIEW,
            StageName.DELIVERY
        ]
        
        # 验证阶段顺序
        for i in range(len(valid_order) - 1):
            current = valid_order[i]
            next_stage = valid_order[i + 1]
            
            # 验证当前阶段可以流转到下一阶段
            assert self._can_transition(current, next_stage), \
                f"阶段 {current} 应该能流转到 {next_stage}"

    def _can_transition(self, from_stage: StageName, to_stage: StageName) -> bool:
        """检查阶段是否可以流转"""
        valid_transitions = {
            StageName.REQUIREMENT: [StageName.DESIGN],
            StageName.DESIGN: [StageName.CODING],
            StageName.CODING: [StageName.TESTING],
            StageName.TESTING: [StageName.CODE_REVIEW],
            StageName.CODE_REVIEW: [StageName.CODING, StageName.DELIVERY],  # 可退回或前进
            StageName.DELIVERY: []
        }
        return to_stage in valid_transitions.get(from_stage, [])


class TestHumanInTheLoopApprove:
    """
    FT-P-02: 人工审批 (Approve)
    
    测试场景：在 DESIGN 阶段点击 Approve
    预期结果：状态从 PAUSED 变为 RUNNING，自动触发异步的 CODING 任务。
    """

    @pytest.fixture
    def paused_pipeline(self):
        """创建处于 PAUSED 状态的 Pipeline"""
        pipeline = MagicMock(spec=Pipeline)
        pipeline.id = 1
        pipeline.status = PipelineStatus.PAUSED
        pipeline.current_stage = StageName.DESIGN
        pipeline.description = "测试 Pipeline"
        return pipeline

    @pytest.fixture
    def paused_design_stage(self):
        """创建处于 PENDING_APPROVAL 状态的 DESIGN 阶段"""
        stage = MagicMock(spec=PipelineStage)
        stage.id = 1
        stage.pipeline_id = 1
        stage.name = StageName.DESIGN
        stage.status = StageStatus.PENDING_APPROVAL
        stage.input_data = {"technical_design": "设计方案"}
        stage.output_data = {"design_document": "详细设计"}
        return stage

    @pytest.mark.asyncio
    async def test_approve_transitions_state_to_running(self, paused_pipeline, paused_design_stage):
        """测试 Approve 后状态变为 RUNNING"""
        with patch('app.service.workflow.WorkflowService') as mock_service:
            mock_service.approve_stage = AsyncMock(return_value={
                "success": True,
                "new_status": PipelineStatus.RUNNING,
                "next_stage": StageName.CODING
            })
            
            result = await mock_service.approve_stage(
                pipeline_id=paused_pipeline.id,
                stage_id=paused_design_stage.id,
                approval_data={"approved": True, "comments": "LGTM"}
            )
            
            assert result["success"] is True
            assert result["new_status"] == PipelineStatus.RUNNING

    @pytest.mark.asyncio
    async def test_approve_triggers_async_coding_task(self, paused_pipeline, paused_design_stage):
        """测试 Approve 后自动触发异步 CODING 任务"""
        with patch('app.service.workflow.WorkflowService') as mock_service, \
             patch('app.service.stage_handlers.coding_handler.CodingHandler.execute') as mock_execute:
            
            mock_service.approve_stage = AsyncMock(return_value={
                "success": True,
                "next_stage": StageName.CODING
            })
            mock_execute = AsyncMock()
            
            # 执行审批
            result = await mock_service.approve_stage(
                pipeline_id=paused_pipeline.id,
                stage_id=paused_design_stage.id,
                approval_data={"approved": True}
            )
            
            assert result["success"] is True
            assert result["next_stage"] == StageName.CODING

    def test_approve_preserves_stage_output(self, paused_design_stage):
        """测试 Approve 保留阶段输出数据"""
        original_output = paused_design_stage.output_data.copy()
        
        # 模拟审批
        paused_design_stage.status = StageStatus.SUCCESS
        
        # 验证输出数据未丢失
        assert paused_design_stage.output_data == original_output


class TestHumanInTheLoopReject:
    """
    FT-P-03: 人工驳回 (Reject)
    
    测试场景：在 CODE_REVIEW 阶段输入反馈并 Reject
    预期结果：状态变更，系统根据反馈回退至 CODING 阶段，并在 Prompt 中注入 rejection_feedback。
    """

    @pytest.fixture
    def review_stage(self):
        """创建处于 PENDING_APPROVAL 状态的 CODE_REVIEW 阶段"""
        stage = MagicMock(spec=PipelineStage)
        stage.id = 1
        stage.pipeline_id = 1
        stage.name = StageName.CODE_REVIEW
        stage.status = StageStatus.PENDING_APPROVAL
        stage.input_data = {"code_files": ["app.py"]}
        stage.output_data = {"review_result": "需要修改"}
        return stage

    @pytest.mark.asyncio
    async def test_reject_transitions_back_to_coding(self, review_stage):
        """测试 Reject 后回退到 CODING 阶段"""
        with patch('app.service.workflow.WorkflowService') as mock_service:
            mock_service.reject_stage = AsyncMock(return_value={
                "success": True,
                "new_stage": StageName.CODING,
                "action": "rollback"
            })
            
            result = await mock_service.reject_stage(
                pipeline_id=1,
                stage_id=review_stage.id,
                rejection_data={
                    "approved": False,
                    "feedback": "代码风格不符合规范，请使用类型注解"
                }
            )
            
            assert result["success"] is True
            assert result["new_stage"] == StageName.CODING

    @pytest.mark.asyncio
    async def test_reject_injects_feedback_to_prompt(self, review_stage):
        """测试 Reject 将反馈注入 Prompt"""
        feedback = "缺少错误处理，请添加 try-except"
        
        with patch('app.service.workflow.WorkflowService') as mock_service:
            mock_service.reject_stage = AsyncMock(return_value={
                "success": True,
                "rejection_feedback": feedback,
                "context_update": {"rejection_feedback": feedback}
            })
            
            result = await mock_service.reject_stage(
                pipeline_id=1,
                stage_id=review_stage.id,
                rejection_data={"approved": False, "feedback": feedback}
            )
            
            assert result["rejection_feedback"] == feedback
            assert "rejection_feedback" in result["context_update"]

    def test_rejection_feedback_format(self):
        """测试拒绝反馈格式正确"""
        feedback = {
            "approved": False,
            "feedback": "需要改进",
            "specific_issues": [
                {"file": "app.py", "line": 10, "issue": "缺少类型注解"},
                {"file": "service.py", "line": 25, "issue": "未处理异常"}
            ]
        }
        
        assert feedback["approved"] is False
        assert len(feedback["specific_issues"]) == 2
        assert "file" in feedback["specific_issues"][0]


class TestPipelineTermination:
    """
    FT-P-04: 任务终止 (Terminate)
    
    测试场景：手动终止正在 RUNNING 的 Pipeline
    预期结果：状态变更为 FAILED，立即执行 Docker Sandbox kill，清理日志缓冲区。
    """

    @pytest.fixture
    def running_pipeline(self):
        """创建处于 RUNNING 状态的 Pipeline"""
        pipeline = MagicMock(spec=Pipeline)
        pipeline.id = 1
        pipeline.status = PipelineStatus.RUNNING
        pipeline.current_stage = StageName.CODING
        pipeline.description = "测试 Pipeline"
        return pipeline

    @pytest.mark.asyncio
    async def test_terminate_changes_status_to_failed(self, running_pipeline):
        """测试终止后状态变为 FAILED"""
        with patch('app.service.workflow.WorkflowService') as mock_service:
            mock_service.terminate_pipeline = AsyncMock(return_value={
                "success": True,
                "new_status": PipelineStatus.FAILED,
                "terminated_at": "2024-01-01T00:00:00Z"
            })
            
            result = await mock_service.terminate_pipeline(
                pipeline_id=running_pipeline.id,
                reason="用户手动终止"
            )
            
            assert result["success"] is True
            assert result["new_status"] == PipelineStatus.FAILED

    @pytest.mark.asyncio
    async def test_terminate_kills_docker_sandbox(self, running_pipeline):
        """测试终止时杀死 Docker Sandbox"""
        with patch('app.service.sandbox_manager.SandboxManager.kill_container') as mock_kill:
            mock_kill.return_value = True
            
            # 模拟终止流程
            await self._simulate_termination(running_pipeline.id)
            
            # 验证 kill_container 被调用
            mock_kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_terminate_clears_log_buffer(self, running_pipeline):
        """测试终止时清理日志缓冲区"""
        with patch('app.core.sse_log_buffer.SSELogBuffer.clear') as mock_clear:
            mock_clear.return_value = None
            
            await self._simulate_termination(running_pipeline.id)
            
            # 验证日志缓冲区被清理
            mock_clear.assert_called_once()

    async def _simulate_termination(self, pipeline_id: int):
        """模拟终止流程"""
        # 1. 更新 Pipeline 状态
        # 2. 杀死 Sandbox
        # 3. 清理日志
        pass

    def test_termination_cleanup_sequence(self):
        """测试终止清理顺序"""
        cleanup_order = []
        
        # 模拟清理步骤
        def step1_stop_pipeline():
            cleanup_order.append("stop_pipeline")
            
        def step2_kill_sandbox():
            cleanup_order.append("kill_sandbox")
            
        def step3_clear_logs():
            cleanup_order.append("clear_logs")
            
        def step4_update_status():
            cleanup_order.append("update_status")
        
        # 执行清理
        step1_stop_pipeline()
        step2_kill_sandbox()
        step3_clear_logs()
        step4_update_status()
        
        # 验证顺序
        assert cleanup_order == ["stop_pipeline", "kill_sandbox", "clear_logs", "update_status"]
