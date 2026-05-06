"""
Pipeline 初始化耗时检测脚本

测量从 Pipeline 创建到 REQUIREMENT 阶段完成的各环节耗时，
识别瓶颈阶段并给出优化建议。

用法：
    cd backend
    python -m pytest tests/test_pipeline_init_timing.py -v -s

或独立运行（需要先启动后端）：
    cd backend
    python tests/test_pipeline_init_timing.py
"""

import asyncio
import time
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# ============================================================
# 阶段计时器
# ============================================================

@dataclass
class PhaseTiming:
    """单个阶段的计时数据"""
    name: str
    start_ms: float = 0
    end_ms: float = 0
    duration_ms: float = 0
    metadata: dict = field(default_factory=dict)

    @property
    def duration_sec(self) -> float:
        return self.duration_ms / 1000


class PipelineTimer:
    """Pipeline 初始化全流程计时器"""

    def __init__(self):
        self.phases: List[PhaseTiming] = []
        self._current_phase: Optional[PhaseTiming] = None
        self._overall_start = time.time()

    def start_phase(self, name: str, **metadata):
        """开始计时一个阶段"""
        phase = PhaseTiming(name=name, start_ms=time.time() * 1000, metadata=metadata)
        self._current_phase = phase
        return phase

    def end_phase(self, **extra_metadata):
        """结束当前阶段计时"""
        if self._current_phase:
            self._current_phase.end_ms = time.time() * 1000
            self._current_phase.duration_ms = self._current_phase.end_ms - self._current_phase.start_ms
            self._current_phase.metadata.update(extra_metadata)
            self.phases.append(self._current_phase)
            self._current_phase = None

    def report(self) -> str:
        """生成耗时报告"""
        total_ms = sum(p.duration_ms for p in self.phases)
        lines = []
        lines.append("=" * 70)
        lines.append("Pipeline 初始化各阶段耗时报告")
        lines.append("=" * 70)
        lines.append(f"{'阶段':<42} {'耗时(ms)':>10} {'占比':>8}")
        lines.append("-" * 70)

        for phase in self.phases:
            pct = (phase.duration_ms / total_ms * 100) if total_ms > 0 else 0
            lines.append(
                f"{phase.name:<42} {phase.duration_ms:>10.0f} {pct:>7.1f}%"
            )

        lines.append("-" * 70)
        lines.append(f"{'总计':<42} {total_ms:>10.0f} {'100.0%':>8}")

        # 分类统计
        db_phases = [p for p in self.phases if p.name.startswith("DB_")]
        llm_phases = [p for p in self.phases if p.name.startswith("LLM_")]
        io_phases = [p for p in self.phases if p.name.startswith("IO_")]
        sandbox_phases = [p for p in self.phases if "Sandbox" in p.name or "sandbox" in p.name.lower()]

        lines.append("")
        lines.append("分类统计:")
        if sandbox_phases:
            lines.append(f"  Sandbox 操作: {sum(p.duration_ms for p in sandbox_phases):.0f}ms ({sum(p.duration_ms for p in sandbox_phases)/total_ms*100:.1f}%)")
        if db_phases:
            lines.append(f"  数据库操作:   {sum(p.duration_ms for p in db_phases):.0f}ms ({sum(p.duration_ms for p in db_phases)/total_ms*100:.1f}%)")
        if llm_phases:
            lines.append(f"  LLM 调用:     {sum(p.duration_ms for p in llm_phases):.0f}ms ({sum(p.duration_ms for p in llm_phases)/total_ms*100:.1f}%)")
        if io_phases:
            lines.append(f"  文件 I/O:      {sum(p.duration_ms for p in io_phases):.0f}ms ({sum(p.duration_ms for p in io_phases)/total_ms*100:.1f}%)")
        other_ms = total_ms - sum(
            sum(p.duration_ms for p in group)
            for group in [sandbox_phases, db_phases, llm_phases, io_phases]
        )
        if other_ms > 0:
            lines.append(f"  其他:          {other_ms:.0f}ms ({other_ms/total_ms*100:.1f}%)")

        lines.append("")
        lines.append("瓶颈分析:")
        lines.extend(self._analyze_bottlenecks())

        return "\n".join(lines)

    def _analyze_bottlenecks(self) -> List[str]:
        """分析瓶颈"""
        lines = []
        sorted_phases = sorted(self.phases, key=lambda p: p.duration_ms, reverse=True)

        # Top 3 最慢的阶段
        lines.append("  Top 3 最慢阶段:")
        for i, phase in enumerate(sorted_phases[:3], 1):
            pct = (phase.duration_ms / sum(p.duration_ms for p in self.phases) * 100)
            flag = " ⚠️  主要瓶颈!" if pct > 30 else ""
            lines.append(f"    {i}. {phase.name}: {phase.duration_ms:.0f}ms ({pct:.1f}%){flag}")

        # LLM 调用次数
        llm_count = sum(
            p.metadata.get("llm_calls", 0) for p in self.phases
        )
        if llm_count > 0:
            lines.append(f"  LLM API 调用次数: {llm_count}")
            if llm_count > 5:
                lines.append(f"    ⚠️  LLM 调用过多 ({llm_count} 次)，建议减少工具调用轮数或合并阶段")

        # 可并行化的串行操作
        db_phases = [p for p in self.phases if p.name.startswith("DB_")]
        if len(db_phases) > 3:
            lines.append(f"    ⚠️  数据库查询过多 ({len(db_phases)} 次)，建议合并查询")

        return lines


# ============================================================
# 模拟环境下的快速计时测试（不需要真实 LLM）
# ============================================================

class SimulatedArchitectAgent:
    """
    模拟的 ArchitectAgent，返回固定输出但记录实际调用耗时。
    用于在不依赖真实 LLM 的情况下测量非 LLM 环节的耗时。
    """

    MOCK_OUTPUT = {
        "feature_description": "模拟需求分析输出",
        "affected_files": ["app/api/v1/health.py", "app/service/health_service.py"],
        "estimated_effort": "中等",
        "technical_design": "基于模拟数据的架构方案",
        "acceptance_criteria": ["端点正确响应", "错误处理完善", "单元测试覆盖"],
        "required_symbols": [],
    }

    async def analyze(self, requirement: str, element_context=None,
                      pipeline_id: int = 0, project_path: str = "/workspace/backend"):
        """模拟 analyze 调用"""
        await asyncio.sleep(0.001)  # 模拟最小延迟
        return {
            "success": True,
            "output": dict(self.MOCK_OUTPUT),
            "input_tokens": 100,
            "output_tokens": 200,
            "duration_ms": 1,
            "tool_calls": 3,
            "tool_results": [],
        }


async def measure_pipeline_creation_io(timer: PipelineTimer):
    """
    测量 Pipeline 创建过程中的数据库 I/O 和文件 I/O 耗时。
    不依赖真实 LLM，只测量框架层开销。
    """
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

    # ----------------------------------------------------------
    # 1. 测量数据库初始化
    # ----------------------------------------------------------
    timer.start_phase("DB_init_database")
    from app.core.database import init_db
    await init_db()
    timer.end_phase()

    from app.core.database import async_session_factory
    from app.models.pipeline import Pipeline, PipelineStatus, StageName, StageStatus

    # ----------------------------------------------------------
    # 2. 测量 Pipeline 记录创建
    # ----------------------------------------------------------
    timer.start_phase("DB_create_pipeline_record")
    async with async_session_factory() as session:
        pipeline = Pipeline(
            description="测试需求：添加健康检查接口",
            status=PipelineStatus.RUNNING,
            current_stage=StageName.REQUIREMENT
        )
        session.add(pipeline)
        await session.flush()
        pipeline_id = pipeline.id

        from app.models.pipeline import PipelineStage
        stage = PipelineStage(
            pipeline_id=pipeline_id,
            name=StageName.REQUIREMENT,
            status=StageStatus.PENDING,
            input_data={"requirement": "测试需求：添加健康检查接口"}
        )
        session.add(stage)
        await session.flush()
        await session.commit()
    timer.end_phase(pipeline_id=pipeline_id)

    # ----------------------------------------------------------
    # 3. 测量 Sandbox 获取（预热池路径）
    # ----------------------------------------------------------
    timer.start_phase("Sandbox_acquire_from_pool")
    from app.service.sandbox_manager import sandbox_manager
    from app.core.config import settings
    from pathlib import Path

    sandbox_info = await sandbox_manager.acquire_from_pool(pipeline_id)
    if sandbox_info is None:
        # 回退到正常启动（计时包含 docker run + docker cp）
        project_path = str(Path(settings.TARGET_PROJECT_PATH).resolve())
        sandbox_info = await sandbox_manager.start(pipeline_id, project_path)
    timer.end_phase(
        from_pool=(sandbox_info is not None),
        container_id=sandbox_info.container_id[:12] if sandbox_info else "N/A"
    )

    # ----------------------------------------------------------
    # 4. 测量 DB 查询 Pipeline + Stage
    # ----------------------------------------------------------
    timer.start_phase("DB_get_pipeline_with_stages")
    async with async_session_factory() as session:
        from app.service.workflow import WorkflowService
        pipeline_obj = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
    timer.end_phase(stages_count=len(pipeline_obj.stages) if pipeline_obj and pipeline_obj.stages else 0)

    # ----------------------------------------------------------
    # 5. 测量 RequirementHandler.prepare()
    # ----------------------------------------------------------
    timer.start_phase("DB_requirement_prepare")
    async with async_session_factory() as session:
        from app.repositories import PipelineStageRepository
        stage = await PipelineStageRepository.get_by_pipeline_and_name(
            pipeline_id, StageName.REQUIREMENT, session
        )
    timer.end_phase(stage_found=stage is not None)

    # ----------------------------------------------------------
    # 6. 测量 AgentCoordinatorService
    # ----------------------------------------------------------
    timer.start_phase("SVC_build_architect_context")
    from app.service.agent_coordinator_service import agent_coordinator_service
    context = await agent_coordinator_service.build_architect_context(
        requirement="测试需求：添加健康检查接口",
        element_context=None,
        pipeline_id=pipeline_id
    )
    timer.end_phase()

    # ----------------------------------------------------------
    # 7. 测量 ArchitectAgent.analyze() — 模拟模式
    # ----------------------------------------------------------
    timer.start_phase("LLM_architect_analyze__SIMULATED")
    mock_agent = SimulatedArchitectAgent()
    result = await mock_agent.analyze(
        requirement="测试需求：添加健康检查接口",
        pipeline_id=pipeline_id
    )
    timer.end_phase(success=result.get("success"))

    # ----------------------------------------------------------
    # 8. 测量 complete 阶段（DB 写入）
    # ----------------------------------------------------------
    timer.start_phase("DB_requirement_complete")
    async with async_session_factory() as session:
        from sqlmodel import select
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == StageName.REQUIREMENT
        )
        query_result = await session.execute(statement)
        stage_obj = query_result.scalar_one_or_none()
        if stage_obj:
            from app.core.timezone import now
            stage_obj.output_data = result.get("output", {})
            stage_obj.status = StageStatus.SUCCESS
            stage_obj.completed_at = now()
            stage_obj.input_tokens = result.get("input_tokens", 0)
            stage_obj.output_tokens = result.get("output_tokens", 0)
            stage_obj.duration_ms = result.get("duration_ms", 0)
            await session.commit()
    timer.end_phase()

    # ----------------------------------------------------------
    # 9. 清理
    # ----------------------------------------------------------
    timer.start_phase("Cleanup")
    try:
        await sandbox_manager.stop(pipeline_id, fast=True)
    except Exception:
        pass
    timer.end_phase()

    return pipeline_id


# ============================================================
# 集成计时测试（需要真实 LLM API）
# ============================================================

async def measure_full_pipeline_startup(timer: PipelineTimer):
    """
    完整 Pipeline 启动计时（需要真实的 LLM API 配置）。
    请确保 backend/.env 中的 LLM_PROVIDER 和 API Key 已配置。
    """
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

    from app.core.database import init_db, async_session_factory
    from app.service.sandbox_manager import sandbox_manager
    from app.core.config import settings
    from pathlib import Path

    await init_db()

    # Step 1: 创建 Pipeline 记录
    timer.start_phase("DB_create_pipeline")
    async with async_session_factory() as session:
        from app.models.pipeline import Pipeline, PipelineStage, PipelineStatus, StageName, StageStatus
        pipeline = Pipeline(
            description="测试需求：添加健康检查接口",
            status=PipelineStatus.RUNNING,
            current_stage=StageName.REQUIREMENT
        )
        session.add(pipeline)
        await session.flush()
        pipeline_id = pipeline.id

        stage = PipelineStage(
            pipeline_id=pipeline_id,
            name=StageName.REQUIREMENT,
            status=StageStatus.PENDING,
            input_data={"requirement": "测试需求：添加健康检查接口"}
        )
        session.add(stage)
        await session.flush()
        await session.commit()
    timer.end_phase(pipeline_id=pipeline_id)

    # Step 2: 获取 Sandbox
    timer.start_phase("Sandbox_acquire")
    sandbox_info = await sandbox_manager.acquire_from_pool(pipeline_id)
    if sandbox_info is None:
        project_path = str(Path(settings.TARGET_PROJECT_PATH).resolve())
        timer.end_phase(from_pool=False)
        timer.start_phase("Sandbox_start_docker_run")
        sandbox_info = await sandbox_manager.start(pipeline_id, project_path)
        timer.end_phase()
    else:
        timer.end_phase(from_pool=True)

    # Step 3: 执行 REQUIREMENT 阶段
    timer.start_phase("LLM_requirement_total")
    async with async_session_factory() as session:
        from app.service.pipeline import PipelineService
        result = await PipelineService.run_architect_task(
            pipeline_id=pipeline_id,
            requirement="测试需求：添加健康检查接口",
            element_context=None,
            session=session
        )
        await session.commit()
    timer.end_phase()

    # Step 4: 获取完整状态
    timer.start_phase("DB_get_status")
    async with async_session_factory() as session:
        from app.service.workflow import WorkflowService
        pipeline_obj = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
        requirement_stage = None
        for s in (pipeline_obj.stages or []):
            if s.name == StageName.REQUIREMENT:
                requirement_stage = s
                break
    timer.end_phase()

    # 从 stage 中提取 LLM 子阶段耗时
    if requirement_stage:
        timer.phases[-1].metadata.update({
            "stage_status": requirement_stage.status.value,
            "input_tokens": requirement_stage.input_tokens or 0,
            "output_tokens": requirement_stage.output_tokens or 0,
            "duration_ms": requirement_stage.duration_ms or 0,
            "retry_count": requirement_stage.retry_count or 0,
        })

    # Cleanup
    timer.start_phase("Cleanup")
    try:
        await sandbox_manager.stop(pipeline_id, fast=True)
    except Exception:
        pass
    timer.end_phase()


# ============================================================
# 主入口
# ============================================================

async def main():
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

    # 加载环境变量
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
    except ImportError:
        pass

    timer = PipelineTimer()

    provider = (os.environ.get("LLM_PROVIDER") or "").upper()
    api_key_var = f"{provider}_API_KEY" if provider else ""
    use_real_llm = bool(provider and os.environ.get(api_key_var))

    print("\nPipeline 初始化耗时检测")
    print("=" * 70)

    if use_real_llm:
        print("模式: 真实 LLM 调用（将实际调用 AI API）")
        print("注意: 这会花费实际 API 费用和等待时间")
        print()
        await measure_full_pipeline_startup(timer)
    else:
        print("模式: 模拟 LLM（仅测量框架层 / DB / Sandbox 开销）")
        print("提示: 设置 .env 中的 LLM_PROVIDER 和 API_KEY 可开启真实模式")
        print()
        await measure_pipeline_creation_io(timer)

    print()
    print(timer.report())

    # 输出 JSON 格式（方便程序化解析）
    print("\n--- JSON 输出 ---")
    json_output = [
        {
            "name": p.name,
            "duration_ms": p.duration_ms,
            "metadata": p.metadata
        }
        for p in timer.phases
    ]
    print(json.dumps(json_output, ensure_ascii=False, indent=2))

    return timer


if __name__ == "__main__":
    asyncio.run(main())
