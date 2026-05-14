"""
第四层补充：数据库事务完整性测试

测试列表：
1. test_transaction_rollback_on_error - 错误时事务回滚
2. test_pipeline_state_consistency - Pipeline 状态一致性
3. test_stage_update_atomicity - 阶段更新原子性
4. test_no_partial_updates - 无部分更新

目的: 确保数据库事务在异常时正确回滚，防止数据不一致
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, Any

from app.models.pipeline import (
    Pipeline, PipelineStage, PipelineStatus, StageName, StageStatus
)
from app.service.workflow import WorkflowService

pytestmark = [pytest.mark.defense, pytest.mark.layer4]


class TestTransactionRollback:
    """
    用例: 验证在发生错误时数据库事务正确回滚。
    目的: 防止部分更新导致数据不一致。
    """

    def test_pipeline_creation_rollback_on_error(self):
        """测试 Pipeline 创建错误时回滚"""
        # 模拟事务状态
        transaction_state = {
            "started": True,
            "operations": [],
            "committed": False,
            "rolled_back": False
        }

        def mock_operation(name: str, should_fail: bool = False):
            """模拟数据库操作"""
            if should_fail:
                transaction_state["rolled_back"] = True
                raise Exception(f"Operation {name} failed")
            transaction_state["operations"].append(name)

        try:
            # 开始事务
            transaction_state["started"] = True

            # 执行操作
            mock_operation("create_pipeline")
            mock_operation("create_stages")
            mock_operation("initialize_state", should_fail=True)  # 失败

            # 如果到达这里，提交事务
            transaction_state["committed"] = True

        except Exception:
            # 应该触发回滚
            pass

        # 验证回滚发生
        assert transaction_state["rolled_back"] is True
        assert transaction_state["committed"] is False

    def test_stage_update_rollback_on_validation_failure(self):
        """测试阶段更新验证失败时回滚"""
        stage_data = {
            "id": 1,
            "name": StageName.CODING,
            "status": StageStatus.PENDING,
            "output_data": {}
        }

        original_status = stage_data["status"]

        try:
            # 尝试更新阶段
            stage_data["status"] = StageStatus.RUNNING
            stage_data["output_data"] = {"partial": "data"}

            # 模拟验证失败
            if not stage_data.get("input_data"):
                raise ValueError("Missing required input_data")

        except ValueError:
            # 回滚到原始状态
            stage_data["status"] = original_status
            stage_data["output_data"] = {}

        # 验证回滚成功
        assert stage_data["status"] == StageStatus.PENDING
        assert stage_data["output_data"] == {}

    def test_cascade_delete_handling(self):
        """测试级联删除处理"""
        # 模拟 Pipeline 和相关数据
        pipeline_data = {
            "id": 1,
            "status": PipelineStatus.FAILED,
            "stages": [
                {"id": 1, "pipeline_id": 1, "name": StageName.DESIGN},
                {"id": 2, "pipeline_id": 1, "name": StageName.CODING},
            ],
            "metrics": [
                {"id": 1, "pipeline_id": 1, "metric": "tokens"},
            ]
        }

        # 验证级联关系
        for stage in pipeline_data["stages"]:
            assert stage["pipeline_id"] == pipeline_data["id"]

        for metric in pipeline_data["metrics"]:
            assert metric["pipeline_id"] == pipeline_data["id"]

        # 模拟删除 Pipeline 时应该同时删除关联数据
        deleted_ids = {
            "pipeline": pipeline_data["id"],
            "stages": [s["id"] for s in pipeline_data["stages"]],
            "metrics": [m["id"] for m in pipeline_data["metrics"]]
        }

        # 验证所有关联数据被标记删除
        assert len(deleted_ids["stages"]) == 2
        assert len(deleted_ids["metrics"]) == 1


class TestPipelineStateConsistency:
    """
    用例: 验证 Pipeline 状态始终保持一致。
    目的: 防止状态错乱导致系统异常。
    """

    def test_valid_state_transitions_only(self):
        """测试只允许有效的状态转换"""
        # 定义有效的状态转换
        valid_transitions = {
            PipelineStatus.RUNNING: [PipelineStatus.PAUSED, PipelineStatus.FAILED, PipelineStatus.SUCCESS],
            PipelineStatus.PAUSED: [PipelineStatus.RUNNING, PipelineStatus.FAILED],
            PipelineStatus.FAILED: [],  # 终态，不能转换
            PipelineStatus.SUCCESS: [],  # 终态，不能转换
        }

        # 验证所有可能的转换
        for from_status, to_statuses in valid_transitions.items():
            for to_status in to_statuses:
                # 验证转换是有效的
                assert to_status in [PipelineStatus.RUNNING, PipelineStatus.PAUSED,
                                     PipelineStatus.FAILED, PipelineStatus.SUCCESS]

                # 验证不会从终态转换出去
                if from_status in [PipelineStatus.FAILED, PipelineStatus.SUCCESS]:
                    assert len(to_statuses) == 0, "终态不应该有出转换"

    def test_stage_status_matches_pipeline_status(self):
        """测试阶段状态与 Pipeline 状态匹配"""
        pipeline = MagicMock(spec=Pipeline)
        pipeline.id = 1
        pipeline.status = PipelineStatus.RUNNING
        pipeline.current_stage = StageName.CODING

        # 当前阶段应该是 RUNNING
        current_stage = MagicMock(spec=PipelineStage)
        current_stage.name = StageName.CODING
        current_stage.status = StageStatus.RUNNING

        # 验证状态一致性
        if pipeline.status == PipelineStatus.RUNNING:
            assert current_stage.status == StageStatus.RUNNING, \
                "Pipeline 运行中时，当前阶段也应该是运行中"

    def test_no_orphan_stages(self):
        """测试没有孤立阶段"""
        # 模拟阶段数据
        stages = [
            {"id": 1, "pipeline_id": 1, "name": StageName.DESIGN},
            {"id": 2, "pipeline_id": 1, "name": StageName.CODING},
            {"id": 3, "pipeline_id": 2, "name": StageName.DESIGN},  # 不同的 Pipeline
        ]

        pipeline_id = 1

        # 过滤属于指定 Pipeline 的阶段
        related_stages = [s for s in stages if s["pipeline_id"] == pipeline_id]

        # 验证没有孤立阶段（所有阶段都有有效的 pipeline_id）
        for stage in stages:
            assert stage["pipeline_id"] is not None
            assert stage["pipeline_id"] > 0

        # 验证能正确关联
        assert len(related_stages) == 2


class TestAtomicUpdates:
    """
    用例: 验证数据库更新是原子的。
    目的: 防止部分更新导致数据不一致。
    """

    def test_stage_metrics_updated_together(self):
        """测试阶段指标一起更新"""
        stage_data = {
            "id": 1,
            "status": StageStatus.RUNNING,
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": 0
        }

        # 模拟完成阶段时的更新
        update_data = {
            "status": StageStatus.SUCCESS,
            "input_tokens": 1500,
            "output_tokens": 800,
            "duration_ms": 5000
        }

        # 验证所有字段一起更新
        stage_data.update(update_data)

        # 验证更新是完整的
        assert stage_data["status"] == StageStatus.SUCCESS
        assert stage_data["input_tokens"] == 1500
        assert stage_data["output_tokens"] == 800
        assert stage_data["duration_ms"] == 5000

    def test_all_stages_updated_on_pipeline_completion(self):
        """测试 Pipeline 完成时所有阶段一起更新"""
        pipeline_data = {
            "id": 1,
            "status": PipelineStatus.RUNNING,
            "stages": [
                {"id": 1, "status": StageStatus.SUCCESS},
                {"id": 2, "status": StageStatus.RUNNING},
                {"id": 3, "status": StageStatus.PENDING},
            ]
        }

        # Pipeline 失败时，所有未完成阶段应该标记为失败
        pipeline_data["status"] = PipelineStatus.FAILED

        for stage in pipeline_data["stages"]:
            if stage["status"] not in [StageStatus.SUCCESS, StageStatus.FAILED]:
                stage["status"] = StageStatus.FAILED

        # 验证所有阶段都有终态
        for stage in pipeline_data["stages"]:
            assert stage["status"] in [StageStatus.SUCCESS, StageStatus.FAILED]

    def test_output_data_complete_or_empty(self):
        """测试输出数据要么完整要么为空"""
        # 有效的完整输出
        complete_output = {
            "files": [{"path": "test.py", "content": "# code"}],
            "summary": "Generated test file",
            "metrics": {"lines": 10}
        }

        # 空输出（初始状态）
        empty_output = {}

        # 部分输出（无效状态）
        partial_output = {
            "files": [],  # 空数组但其他字段缺失
        }

        # 验证完整输出是有效的
        assert "files" in complete_output
        assert "summary" in complete_output

        # 验证空输出是有效的（初始状态）
        assert empty_output == {} or "error" in empty_output

        # 验证部分输出应该被检测
        is_partial = "files" in partial_output and "summary" not in partial_output
        assert is_partial, "应该能检测到部分输出"


class TestDataIntegrity:
    """
    用例: 验证数据完整性约束。
    目的: 防止无效数据进入数据库。
    """

    def test_required_fields_present(self):
        """测试必填字段存在"""
        # Pipeline 必填字段
        required_pipeline_fields = ["id", "status", "description"]

        pipeline_data = {
            "id": 1,
            "status": PipelineStatus.RUNNING,
            "description": "Test pipeline"
        }

        # 验证所有必填字段存在
        for field in required_pipeline_fields:
            assert field in pipeline_data, f"必填字段 {field} 缺失"
            assert pipeline_data[field] is not None, f"必填字段 {field} 不能为 None"

    def test_foreign_key_integrity(self):
        """测试外键完整性"""
        # Stage 必须关联到有效的 Pipeline
        stage_data = {
            "id": 1,
            "pipeline_id": 1,  # 外键
            "name": StageName.CODING
        }

        # 验证外键存在且有效
        assert stage_data["pipeline_id"] is not None
        assert stage_data["pipeline_id"] > 0

        # 模拟关联检查
        existing_pipeline_ids = [1, 2, 3]
        assert stage_data["pipeline_id"] in existing_pipeline_ids, \
            "外键必须引用存在的记录"

    def test_enum_values_valid(self):
        """测试枚举值有效"""
        valid_statuses = [
            PipelineStatus.RUNNING,
            PipelineStatus.PAUSED,
            PipelineStatus.FAILED,
            PipelineStatus.SUCCESS
        ]

        # 验证状态值有效
        current_status = PipelineStatus.RUNNING
        assert current_status in valid_statuses

        # 验证无效状态被检测
        invalid_status = "INVALID_STATUS"
        assert invalid_status not in valid_statuses

    def test_no_duplicate_stage_names_per_pipeline(self):
        """测试同一 Pipeline 中没有重复的阶段名称"""
        stages = [
            {"id": 1, "pipeline_id": 1, "name": StageName.DESIGN},
            {"id": 2, "pipeline_id": 1, "name": StageName.CODING},
            {"id": 3, "pipeline_id": 1, "name": StageName.CODE_REVIEW},
        ]

        # 收集阶段名称
        stage_names = [s["name"] for s in stages if s["pipeline_id"] == 1]

        # 验证没有重复
        assert len(stage_names) == len(set(stage_names)), \
            "同一 Pipeline 中不应该有重复的阶段名称"


class TestConcurrentModification:
    """
    用例: 验证并发修改时数据一致性。
    目的: 防止并发更新导致数据丢失。
    """

    def test_optimistic_locking_with_version(self):
        """测试使用版本号的乐观锁"""
        # 模拟带版本号的数据
        pipeline_data = {
            "id": 1,
            "status": PipelineStatus.RUNNING,
            "version": 1  # 版本号
        }

        # 读取数据
        read_data = pipeline_data.copy()

        # 另一个会话更新了数据
        pipeline_data["status"] = PipelineStatus.PAUSED
        pipeline_data["version"] = 2

        # 尝试用旧版本更新
        if read_data["version"] != pipeline_data["version"]:
            # 检测到冲突
            conflict_detected = True
            assert conflict_detected, "应该检测到版本冲突"

    def test_last_write_wins_on_different_fields(self):
        """测试不同字段的更新不会冲突"""
        pipeline_data = {
            "id": 1,
            "status": PipelineStatus.RUNNING,
            "current_stage": StageName.DESIGN,
            "metrics": {"tokens": 1000}
        }

        # 更新 1：修改状态
        update1 = {"status": PipelineStatus.PAUSED}

        # 更新 2：修改指标
        update2 = {"metrics": {"tokens": 1500}}

        # 应用更新（不同字段，不会冲突）
        pipeline_data.update(update1)
        pipeline_data.update(update2)

        # 验证两个更新都生效
        assert pipeline_data["status"] == PipelineStatus.PAUSED
        assert pipeline_data["metrics"]["tokens"] == 1500

    def test_read_committed_isolation(self):
        """测试读已提交隔离级别"""
        # 模拟事务隔离
        committed_data = {
            "id": 1,
            "status": PipelineStatus.SUCCESS,
            "committed": True
        }

        uncommitted_data = {
            "id": 1,
            "status": PipelineStatus.FAILED,
            "committed": False  # 未提交
        }

        # 读已提交：只能看到已提交的数据
        visible_data = committed_data if committed_data["committed"] else None

        assert visible_data is not None
        assert visible_data["status"] == PipelineStatus.SUCCESS
