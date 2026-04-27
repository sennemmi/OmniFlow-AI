"""
单元测试：PipelineService
测试 _build_pipeline_read、create_pipeline_record 等不依赖外部服务的逻辑
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from app.service.pipeline import PipelineService
from app.models.pipeline import Pipeline, PipelineStage, PipelineStatus, StageName, StageStatus


@pytest.mark.unit
class TestBuildPipelineRead:
    """测试内部数据转换方法"""

    def test_build_pipeline_read_basic(self):
        pipeline = Pipeline(
            id=1, description="test",
            status=PipelineStatus.RUNNING,
            current_stage=StageName.REQUIREMENT
        )
        pipeline.stages = []
        result = PipelineService._build_pipeline_read(pipeline)
        assert result.id == 1
        assert result.description == "test"
        assert result.status == PipelineStatus.RUNNING

    def test_build_pipeline_read_with_stages(self):
        pipeline = Pipeline(id=2, description="with stages", status=PipelineStatus.PAUSED)
        stage = PipelineStage(
            id=10, pipeline_id=2,
            name=StageName.DESIGN, status=StageStatus.SUCCESS,
            input_data={"key": "val"}, output_data={"result": "ok"}
        )
        pipeline.stages = [stage]
        result = PipelineService._build_pipeline_read(pipeline)
        assert len(result.stages) == 1
        assert result.stages[0].name == StageName.DESIGN

    def test_build_pipeline_read_no_stages(self):
        """测试 stages 为空列表的情况"""
        pipeline = Pipeline(id=3, description="no stages", status=PipelineStatus.FAILED)
        pipeline.stages = []  # SQLModel Relationship 不能设为 None，用空列表
        result = PipelineService._build_pipeline_read(pipeline)
        # stages 为空列表时应该返回 None
        assert result.stages is None

    def test_build_pipeline_read_multiple_stages(self):
        """测试多个阶段的转换"""
        pipeline = Pipeline(id=4, description="multi stages", status=PipelineStatus.RUNNING)
        stage1 = PipelineStage(id=11, pipeline_id=4, name=StageName.REQUIREMENT, status=StageStatus.SUCCESS)
        stage2 = PipelineStage(id=12, pipeline_id=4, name=StageName.DESIGN, status=StageStatus.RUNNING)
        pipeline.stages = [stage1, stage2]
        result = PipelineService._build_pipeline_read(pipeline)
        assert len(result.stages) == 2
        assert result.stages[0].name == StageName.REQUIREMENT
        assert result.stages[1].name == StageName.DESIGN


@pytest.mark.unit
class TestPipelineStatusTransitions:
    """测试 Pipeline 状态转换逻辑"""

    def test_pipeline_status_running(self):
        """测试 RUNNING 状态"""
        pipeline = Pipeline(id=1, description="test", status=PipelineStatus.RUNNING)
        assert pipeline.status == PipelineStatus.RUNNING

    def test_pipeline_status_paused(self):
        """测试 PAUSED 状态"""
        pipeline = Pipeline(id=2, description="test", status=PipelineStatus.PAUSED)
        assert pipeline.status == PipelineStatus.PAUSED

    def test_pipeline_status_success(self):
        """测试 SUCCESS 状态"""
        pipeline = Pipeline(id=3, description="test", status=PipelineStatus.SUCCESS)
        assert pipeline.status == PipelineStatus.SUCCESS

    def test_pipeline_status_failed(self):
        """测试 FAILED 状态"""
        pipeline = Pipeline(id=4, description="test", status=PipelineStatus.FAILED)
        assert pipeline.status == PipelineStatus.FAILED


@pytest.mark.unit
class TestStageStatusLogic:
    """测试阶段状态逻辑"""

    def test_stage_status_pending(self):
        """测试 PENDING 状态"""
        stage = PipelineStage(id=1, pipeline_id=1, name=StageName.REQUIREMENT, status=StageStatus.PENDING)
        assert stage.status == StageStatus.PENDING

    def test_stage_status_running(self):
        """测试 RUNNING 状态"""
        stage = PipelineStage(id=2, pipeline_id=1, name=StageName.DESIGN, status=StageStatus.RUNNING)
        assert stage.status == StageStatus.RUNNING

    def test_stage_status_success(self):
        """测试 SUCCESS 状态"""
        stage = PipelineStage(id=3, pipeline_id=1, name=StageName.CODING, status=StageStatus.SUCCESS)
        assert stage.status == StageStatus.SUCCESS

    def test_stage_status_failed(self):
        """测试 FAILED 状态"""
        stage = PipelineStage(id=4, pipeline_id=1, name=StageName.CODE_REVIEW, status=StageStatus.FAILED)
        assert stage.status == StageStatus.FAILED


@pytest.mark.unit
class TestStageNameEnum:
    """测试阶段名称枚举"""

    def test_stage_name_requirement(self):
        assert StageName.REQUIREMENT.value == "REQUIREMENT"

    def test_stage_name_design(self):
        assert StageName.DESIGN.value == "DESIGN"

    def test_stage_name_coding(self):
        assert StageName.CODING.value == "CODING"

    def test_stage_name_code_review(self):
        assert StageName.CODE_REVIEW.value == "CODE_REVIEW"

    def test_stage_name_delivery(self):
        assert StageName.DELIVERY.value == "DELIVERY"
