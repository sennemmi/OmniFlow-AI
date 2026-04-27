"""
数据持久层测试
验证 SQLModel 关系、JSON 字段约束、事务回滚
"""
import pytest
from sqlalchemy.orm import selectinload
from sqlmodel import select
from app.models.pipeline import Pipeline, PipelineStage, PipelineStatus, StageName, StageStatus


@pytest.mark.unit
class TestPipelinePersistence:
    """测试 Pipeline 数据库持久化"""

    @pytest.mark.asyncio
    async def test_create_pipeline_with_stages(self, db_session):
        """测试创建 Pipeline 并关联多个 Stage"""
        # 创建 Pipeline
        pipeline = Pipeline(
            description="测试流水线",
            status=PipelineStatus.RUNNING,
            current_stage=StageName.REQUIREMENT
        )
        db_session.add(pipeline)
        await db_session.flush()

        # 创建 Stage
        stage1 = PipelineStage(
            pipeline_id=pipeline.id,
            name=StageName.REQUIREMENT,
            status=StageStatus.SUCCESS,
            input_data={"requirement": "测试需求"},
            output_data={"feature_description": "功能描述"}
        )
        stage2 = PipelineStage(
            pipeline_id=pipeline.id,
            name=StageName.DESIGN,
            status=StageStatus.RUNNING,
            input_data={"design": "设计方案"}
        )
        db_session.add(stage1)
        db_session.add(stage2)
        await db_session.commit()

        # 验证关联查询
        statement = select(Pipeline).where(Pipeline.id == pipeline.id).options(
            selectinload(Pipeline.stages)
        )
        result = await db_session.execute(statement)
        loaded_pipeline = result.scalar_one()

        assert loaded_pipeline is not None
        assert len(loaded_pipeline.stages) == 2
        assert loaded_pipeline.stages[0].name == StageName.REQUIREMENT
        assert loaded_pipeline.stages[1].name == StageName.DESIGN

    @pytest.mark.asyncio
    async def test_json_field_storage(self, db_session):
        """测试 JSON 字段存储复杂数据"""
        complex_data = {
            "multi_agent_output": {
                "files": [
                    {"file_path": "app/test.py", "content": "print(1)"}
                ],
                "nested": {
                    "deep": {
                        "value": 123
                    }
                }
            }
        }

        pipeline = Pipeline(
            description="JSON测试",
            status=PipelineStatus.PAUSED
        )
        db_session.add(pipeline)
        await db_session.flush()

        stage = PipelineStage(
            pipeline_id=pipeline.id,
            name=StageName.CODING,
            status=StageStatus.SUCCESS,
            output_data=complex_data
        )
        db_session.add(stage)
        await db_session.commit()

        # 验证 JSON 数据正确存储和读取
        statement = select(PipelineStage).where(PipelineStage.id == stage.id)
        result = await db_session.execute(statement)
        loaded_stage = result.scalar_one()

        assert loaded_stage.output_data["multi_agent_output"]["files"][0]["file_path"] == "app/test.py"
        assert loaded_stage.output_data["multi_agent_output"]["nested"]["deep"]["value"] == 123

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, db_session):
        """测试事务回滚"""
        pipeline = Pipeline(
            description="回滚测试",
            status=PipelineStatus.RUNNING
        )
        db_session.add(pipeline)
        await db_session.flush()

        # 记录 ID
        pipeline_id = pipeline.id

        # 回滚事务
        await db_session.rollback()

        # 验证数据未保存
        statement = select(Pipeline).where(Pipeline.id == pipeline_id)
        result = await db_session.execute(statement)
        loaded = result.scalar_one_or_none()

        assert loaded is None

    @pytest.mark.asyncio
    async def test_stage_status_transition(self, db_session):
        """测试 Stage 状态流转"""
        pipeline = Pipeline(description="状态测试", status=PipelineStatus.RUNNING)
        db_session.add(pipeline)
        await db_session.flush()

        stage = PipelineStage(
            pipeline_id=pipeline.id,
            name=StageName.CODING,
            status=StageStatus.PENDING
        )
        db_session.add(stage)
        await db_session.commit()

        # 更新状态
        stage.status = StageStatus.RUNNING
        await db_session.commit()

        # 验证状态更新
        statement = select(PipelineStage).where(PipelineStage.id == stage.id)
        result = await db_session.execute(statement)
        loaded = result.scalar_one()

        assert loaded.status == StageStatus.RUNNING


@pytest.mark.unit
class TestPipelineRelationships:
    """测试 Pipeline 关系映射"""

    @pytest.mark.asyncio
    async def test_pipeline_cascade_delete(self, db_session):
        """测试 Pipeline 删除时级联删除 Stage"""
        pipeline = Pipeline(description="级联测试", status=PipelineStatus.RUNNING)
        db_session.add(pipeline)
        await db_session.flush()

        stage = PipelineStage(
            pipeline_id=pipeline.id,
            name=StageName.REQUIREMENT,
            status=StageStatus.SUCCESS
        )
        db_session.add(stage)
        await db_session.commit()

        stage_id = stage.id

        # 删除 Pipeline
        await db_session.delete(pipeline)
        await db_session.commit()

        # 验证 Stage 也被删除
        statement = select(PipelineStage).where(PipelineStage.id == stage_id)
        result = await db_session.execute(statement)
        loaded = result.scalar_one_or_none()

        assert loaded is None

    @pytest.mark.asyncio
    async def test_empty_stages_list(self, db_session):
        """测试 Pipeline 没有 Stage 的情况"""
        pipeline = Pipeline(description="空Stage测试", status=PipelineStatus.RUNNING)
        db_session.add(pipeline)
        await db_session.commit()

        statement = select(Pipeline).where(Pipeline.id == pipeline.id).options(
            selectinload(Pipeline.stages)
        )
        result = await db_session.execute(statement)
        loaded = result.scalar_one()

        assert loaded.stages == []
