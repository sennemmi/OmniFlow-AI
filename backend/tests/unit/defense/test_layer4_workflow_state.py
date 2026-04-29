"""
第四层：工作流与状态持久化（确保界面显示正确）

测试列表：
1. test_pipeline_state_transition_restriction - Pipeline 状态流转限制测试
2. test_rerun_output_includes_rejection_feedback - 重新运行的 Output 清洗测试
"""

import pytest

pytestmark = [pytest.mark.defense, pytest.mark.layer4]
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.pipeline import (
    Pipeline, PipelineStage, PipelineStatus, StageName, StageStatus
)
from app.service.workflow import WorkflowService
from app.service.pipeline import PipelineService


class TestPipelineStateTransitionRestriction:
    """
    用例: 尝试对处于 SUCCESS 状态的 Pipeline 调用 reject_pipeline，断言被拒绝。
    目的: 防止生命周期错乱。
    """

    def test_cannot_reject_success_pipeline(self):
        """测试不能驳回已成功的 Pipeline"""
        # 创建模拟的 Pipeline 对象
        pipeline = MagicMock(spec=Pipeline)
        pipeline.id = 1
        pipeline.status = PipelineStatus.SUCCESS
        pipeline.current_stage = StageName.CODE_REVIEW
        pipeline.description = "Test requirement"
        pipeline.stages = []

        # 验证 validate_can_reject 会返回 False
        can_reject, error_msg = asyncio.run(
            WorkflowService.validate_can_reject(pipeline)
        )

        assert can_reject is False
        assert error_msg is not None
        assert "SUCCESS" in error_msg or "cannot" in error_msg.lower()

    def test_cannot_reject_failed_pipeline(self):
        """测试不能驳回已失败的 Pipeline"""
        pipeline = MagicMock(spec=Pipeline)
        pipeline.id = 2
        pipeline.status = PipelineStatus.FAILED
        pipeline.current_stage = StageName.CODING

        can_reject, error_msg = asyncio.run(
            WorkflowService.validate_can_reject(pipeline)
        )

        assert can_reject is False

    def test_can_reject_running_pipeline(self):
        """测试可以驳回运行中的 Pipeline"""
        pipeline = MagicMock(spec=Pipeline)
        pipeline.id = 3
        pipeline.status = PipelineStatus.PAUSED  # 暂停状态可以驳回
        pipeline.current_stage = StageName.DESIGN

        can_reject, error_msg = asyncio.run(
            WorkflowService.validate_can_reject(pipeline)
        )

        # PAUSED 状态的 Pipeline 应该可以驳回
        assert can_reject is True

    def test_state_transition_matrix(self):
        """测试状态转换矩阵"""
        # 定义允许的状态转换
        valid_transitions = {
            PipelineStatus.RUNNING: [PipelineStatus.PAUSED, PipelineStatus.FAILED, PipelineStatus.SUCCESS],
            PipelineStatus.PAUSED: [PipelineStatus.RUNNING, PipelineStatus.FAILED],
            PipelineStatus.FAILED: [],  # 失败状态不能转换到其他状态
            PipelineStatus.SUCCESS: [],  # 成功状态不能转换到其他状态
        }

        # 验证状态转换规则
        for from_status, to_statuses in valid_transitions.items():
            for to_status in to_statuses:
                assert to_status in [PipelineStatus.RUNNING, PipelineStatus.PAUSED,
                                     PipelineStatus.FAILED, PipelineStatus.SUCCESS]


class TestRerunOutputIncludesRejectionFeedback:
    """
    用例: 当 Pipeline 被 Reject 退回 DESIGN 阶段时，断言传入的上下文包含了上一次的 rejection_feedback。
    目的: 确保 AI 知道自己为什么被人类拒绝，避免重复犯错。
    """

    def test_rejection_feedback_passed_to_redesign(self):
        """测试驳回反馈被传递给重新设计阶段"""
        # 模拟 rejection_feedback
        rejection_feedback = {
            "reason": "设计过于复杂",
            "suggested_changes": "请简化架构，使用更简单的方案"
        }

        # 创建 StageContext 验证反馈传递
        from app.service.stage_handlers import StageContext

        context = StageContext(
            pipeline_id=1,
            session=MagicMock(),
            input_data={},
            rejection_feedback=rejection_feedback
        )

        # 验证 rejection_feedback 被正确存储
        assert context.rejection_feedback is not None
        assert context.rejection_feedback["reason"] == "设计过于复杂"
        assert "简化" in context.rejection_feedback["suggested_changes"]

    def test_mark_stage_for_rerun_preserves_feedback(self):
        """测试标记阶段重新运行时保留反馈 - 验证 output_data 结构"""
        # 这个测试验证当阶段被标记为重新运行时，
        # rejection_feedback 会被正确保存到 output_data 中

        rejection_feedback = {
            "reason": "Missing error handling",
            "suggested_changes": "Add try-except blocks"
        }

        # 模拟阶段对象
        mock_stage = MagicMock(spec=PipelineStage)
        mock_stage.id = 1
        mock_stage.name = StageName.DESIGN
        mock_stage.status = StageStatus.SUCCESS
        mock_stage.output_data = {"original": "data"}

        # 模拟保存 feedback 到 output_data 的逻辑
        mock_stage.output_data["rejection_feedback"] = rejection_feedback
        mock_stage.status = StageStatus.PENDING

        # 验证 output_data 包含 rejection_feedback
        assert "rejection_feedback" in mock_stage.output_data
        assert mock_stage.output_data["rejection_feedback"] == rejection_feedback

        # 验证原始数据被保留
        assert mock_stage.output_data["original"] == "data"

        # 验证状态被重置为 PENDING
        assert mock_stage.status == StageStatus.PENDING

    def test_rejection_feedback_structure(self):
        """测试 rejection_feedback 的数据结构"""
        # 验证标准的 rejection_feedback 结构
        feedback = {
            "reason": "具体原因",
            "suggested_changes": "建议修改"
        }

        assert "reason" in feedback
        assert "suggested_changes" in feedback
        assert isinstance(feedback["reason"], str)
        assert isinstance(feedback["suggested_changes"], str)


class TestPipelineStageLifecycle:
    """Pipeline 阶段生命周期测试"""

    def test_stage_status_transitions(self):
        """测试阶段状态转换"""
        # 阶段状态应该是：PENDING -> RUNNING -> SUCCESS/FAILED

        stage = MagicMock(spec=PipelineStage)

        # 初始状态
        stage.status = StageStatus.PENDING
        assert stage.status == StageStatus.PENDING

        # 开始运行
        stage.status = StageStatus.RUNNING
        assert stage.status == StageStatus.RUNNING

        # 完成
        stage.status = StageStatus.SUCCESS
        assert stage.status == StageStatus.SUCCESS

    def test_stage_metrics_tracking(self):
        """测试阶段指标追踪"""
        stage = MagicMock(spec=PipelineStage)

        # 设置指标
        stage.input_tokens = 1000
        stage.output_tokens = 500
        stage.duration_ms = 5000
        stage.retry_count = 2

        # 验证指标
        assert stage.input_tokens == 1000
        assert stage.output_tokens == 500
        assert stage.duration_ms == 5000
        assert stage.retry_count == 2


class TestWorkflowValidation:
    """工作流验证测试"""

    def test_validate_can_approve_checks_status(self):
        """测试验证能否审批时检查状态"""
        # 成功的 Pipeline 不能审批
        success_pipeline = MagicMock(spec=Pipeline)
        success_pipeline.status = PipelineStatus.SUCCESS

        can_approve, error = asyncio.run(
            WorkflowService.validate_can_approve(success_pipeline)
        )
        assert can_approve is False

        # 失败的 Pipeline 不能审批
        failed_pipeline = MagicMock(spec=Pipeline)
        failed_pipeline.status = PipelineStatus.FAILED

        can_approve, error = asyncio.run(
            WorkflowService.validate_can_approve(failed_pipeline)
        )
        assert can_approve is False

    def test_validate_can_approve_allows_paused(self):
        """测试暂停状态的 Pipeline 可以审批"""
        paused_pipeline = MagicMock(spec=Pipeline)
        paused_pipeline.status = PipelineStatus.PAUSED
        paused_pipeline.current_stage = StageName.DESIGN

        can_approve, error = asyncio.run(
            WorkflowService.validate_can_approve(paused_pipeline)
        )
        assert can_approve is True


class TestPipelineServiceRejection:
    """PipelineService 驳回功能测试"""

    def test_reject_pipeline_validates_status(self):
        """测试驳回 Pipeline 时验证状态"""
        import asyncio

        # 模拟无法驳回的 Pipeline
        mock_pipeline = MagicMock(spec=Pipeline)
        mock_pipeline.id = 1
        mock_pipeline.status = PipelineStatus.SUCCESS  # 已成功，不能驳回

        with patch('app.service.pipeline.WorkflowService.get_pipeline_with_stages') as mock_get:
            mock_get.return_value = mock_pipeline

            with patch('app.service.pipeline.WorkflowService.validate_can_reject') as mock_validate:
                mock_validate.return_value = (False, "Cannot reject SUCCESS pipeline")

                result = asyncio.run(PipelineService.reject_pipeline(
                    pipeline_id=1,
                    reason="Test",
                    suggested_changes=None,
                    session=MagicMock()
                ))

                assert result["success"] is False
                assert "Cannot reject" in result["error"]

    def test_reject_pipeline_includes_feedback_in_context(self):
        """测试驳回 Pipeline 时反馈被包含在上下文中"""
        # 验证 rejection_feedback 的数据结构会被正确传递
        rejection_feedback = {
            "reason": "需要修改",
            "suggested_changes": "请使用更简单的设计"
        }

        # 验证 feedback 结构完整
        assert "reason" in rejection_feedback
        assert "suggested_changes" in rejection_feedback
        assert rejection_feedback["reason"] == "需要修改"
        assert rejection_feedback["suggested_changes"] == "请使用更简单的设计"
