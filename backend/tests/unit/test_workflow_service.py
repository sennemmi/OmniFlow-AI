"""
单元测试：WorkflowService
测试状态机转换、阶段流转等核心逻辑
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.service.workflow import WorkflowService
from app.models.pipeline import Pipeline, PipelineStatus, StageName, StageStatus, PipelineStage


@pytest.mark.unit
class TestGetNextStage:
    """测试阶段流转逻辑"""

    async def test_get_next_stage_requirement_to_design(self):
        """REQUIREMENT -> DESIGN"""
        result = await WorkflowService.get_next_stage(StageName.REQUIREMENT)
        assert result == StageName.DESIGN

    async def test_get_next_stage_design_to_coding(self):
        """DESIGN -> CODING"""
        result = await WorkflowService.get_next_stage(StageName.DESIGN)
        assert result == StageName.CODING

    async def test_get_next_stage_coding_to_code_review(self):
        """CODING -> CODE_REVIEW"""
        result = await WorkflowService.get_next_stage(StageName.CODING)
        assert result == StageName.CODE_REVIEW

    async def test_get_next_stage_code_review_to_delivery(self):
        """CODE_REVIEW -> DELIVERY"""
        result = await WorkflowService.get_next_stage(StageName.CODE_REVIEW)
        assert result == StageName.DELIVERY

    async def test_get_next_stage_delivery_is_last(self):
        """DELIVERY 是最后阶段，返回 None"""
        result = await WorkflowService.get_next_stage(StageName.DELIVERY)
        assert result is None


@pytest.mark.unit
class TestValidateCanApprove:
    """测试审批验证逻辑"""

    async def test_can_approve_when_paused(self):
        """PAUSED 状态可以审批"""
        pipeline = MagicMock()
        pipeline.status = PipelineStatus.PAUSED
        can_approve, error = await WorkflowService.validate_can_approve(pipeline)
        assert can_approve is True
        assert error is None

    async def test_cannot_approve_when_running(self):
        """RUNNING 状态不能审批"""
        pipeline = MagicMock()
        pipeline.status = PipelineStatus.RUNNING
        can_approve, error = await WorkflowService.validate_can_approve(pipeline)
        assert can_approve is False
        assert error is not None

    async def test_cannot_approve_when_failed(self):
        """FAILED 状态不能审批"""
        pipeline = MagicMock()
        pipeline.status = PipelineStatus.FAILED
        can_approve, error = await WorkflowService.validate_can_approve(pipeline)
        assert can_approve is False
        assert error is not None

    async def test_cannot_approve_none_pipeline(self):
        """Pipeline 为 None 时不能审批"""
        can_approve, error = await WorkflowService.validate_can_approve(None)
        assert can_approve is False
        assert "not found" in error


@pytest.mark.unit
class TestValidateCanReject:
    """测试驳回验证逻辑"""

    async def test_can_reject_when_paused(self):
        """PAUSED 状态可以驳回"""
        pipeline = MagicMock()
        pipeline.status = PipelineStatus.PAUSED
        can_reject, error = await WorkflowService.validate_can_reject(pipeline)
        assert can_reject is True
        assert error is None

    async def test_cannot_reject_when_running(self):
        """RUNNING 状态不能驳回"""
        pipeline = MagicMock()
        pipeline.status = PipelineStatus.RUNNING
        can_reject, error = await WorkflowService.validate_can_reject(pipeline)
        assert can_reject is False
        assert error is not None

    async def test_cannot_reject_none_pipeline(self):
        """Pipeline 为 None 时不能驳回"""
        can_reject, error = await WorkflowService.validate_can_reject(None)
        assert can_reject is False
        assert "not found" in error


@pytest.mark.unit
class TestStageFlowOrder:
    """测试阶段流转顺序"""

    def test_stage_flow_length(self):
        """阶段流应该包含 5 个阶段"""
        assert len(WorkflowService.STAGE_FLOW) == 5

    def test_stage_flow_order(self):
        """阶段流顺序应该正确"""
        expected = [
            StageName.REQUIREMENT,
            StageName.DESIGN,
            StageName.CODING,
            StageName.CODE_REVIEW,
            StageName.DELIVERY,
        ]
        assert WorkflowService.STAGE_FLOW == expected

    def test_stage_flow_first_is_requirement(self):
        """第一个阶段是 REQUIREMENT"""
        assert WorkflowService.STAGE_FLOW[0] == StageName.REQUIREMENT

    def test_stage_flow_last_is_delivery(self):
        """最后一个阶段是 DELIVERY"""
        assert WorkflowService.STAGE_FLOW[-1] == StageName.DELIVERY
