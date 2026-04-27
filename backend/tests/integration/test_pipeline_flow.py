"""
集成测试：Pipeline 审批流转逻辑
Mock 掉 LLM、Git、GitHub，只测 PipelineService 的状态机
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.integration
class TestPipelineApprovalFlow:

    async def test_approve_requirement_triggers_designer(self, mock_db_session):
        """审批 REQUIREMENT 阶段 → 触发 DesignerAgent"""
        from app.service.pipeline import PipelineService
        from app.models.pipeline import Pipeline, PipelineStatus, StageName

        mock_pipeline = MagicMock()
        mock_pipeline.current_stage = StageName.REQUIREMENT
        mock_pipeline.description = "test requirement"

        with patch("app.service.workflow.WorkflowService.get_pipeline_with_stages",
                   new_callable=AsyncMock, return_value=mock_pipeline), \
             patch("app.service.workflow.WorkflowService.validate_can_approve",
                   new_callable=AsyncMock, return_value=(True, None)), \
             patch("app.service.workflow.WorkflowService.transition_to_next_stage",
                   new_callable=AsyncMock, return_value=(True, None, None)), \
             patch.object(PipelineService, "_trigger_designer_analysis",
                          new_callable=AsyncMock) as mock_designer:

            result = await PipelineService.approve_pipeline(1, None, None, mock_db_session)

            assert result["success"] is True
            mock_designer.assert_called_once_with(1, mock_db_session)

    async def test_approve_nonexistent_pipeline_returns_error(self, mock_db_session):
        """Pipeline 不存在时应该返回明确错误"""
        from app.service.pipeline import PipelineService

        with patch("app.service.workflow.WorkflowService.get_pipeline_with_stages",
                   new_callable=AsyncMock, return_value=None):
            result = await PipelineService.approve_pipeline(999, None, None, mock_db_session)
            assert result["success"] is False
            assert "999" in result["error"]
