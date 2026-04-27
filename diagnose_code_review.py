"""
diagnose_code_review.py
诊断 CODE_REVIEW 阶段的输入输出，定位「评审不通过」根因
"""
import asyncio
import sys
import json
import textwrap
from pathlib import Path

# 确保 backend 可导入
sys.path.insert(0, str(Path(__file__).parent / "backend"))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.models.pipeline import (
    Pipeline, PipelineStage, StageName, StageStatus, PipelineStatus
)
from app.service.pipeline import PipelineService
from app.core.config import settings

# ──────────────────────────────────────────────
# 1. 准备内存数据库 + 模拟数据
# ──────────────────────────────────────────────
engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session():
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

# ══════════════════════════════════════════════
# 2. Mock 各个 Agent 的输出（模拟一次完整流程）
# ══════════════════════════════════════════════
MOCK_ARCHITECT_OUTPUT = {
    "success": True,
    "output": {
        "feature_description": "实现用户登录功能",
        "affected_files": ["app/api/v1/auth.py", "app/service/auth.py"],
        "estimated_effort": "2天",
        "technical_design": "使用 JWT 认证，新建 auth 模块"
    },
    "input_tokens": 100,
    "output_tokens": 80,
    "duration_ms": 1200,
    "reasoning": None
}

MOCK_DESIGNER_OUTPUT = {
    "success": True,
    "output": {
        "technical_design": "增加登录接口，调用 AuthService",
        "api_endpoints": [{"method": "POST", "path": "/api/v1/auth/login", "description": "用户登录"}],
        "function_changes": [
            {"file": "app/service/auth.py", "function": "login", "action": "add", "description": "登录逻辑"},
            {"file": "app/api/v1/auth.py", "function": "login_endpoint", "action": "add", "description": "登录接口"}
        ],
        "logic_flow": "请求 -> 验证 -> 签发JWT -> 返回",
        "dependencies": ["pyjwt"],
        "affected_files": ["app/api/v1/auth.py", "app/service/auth.py"]
    },
    "input_tokens": 200,
    "output_tokens": 150,
    "duration_ms": 1500,
    "reasoning": None
}

# 模拟多 Agent 协调器的输出（包含了代码文件和测试文件）
MOCK_MULTI_AGENT_OUTPUT = {
    "success": True,
    "output": {
        "files": [
            {
                "file_path": "backend/app/api/v1/auth.py",
                "content": "from fastapi import APIRouter\nrouter = APIRouter()\n@router.post('/login')\ndef login(): ...",
                "change_type": "add",
                "description": "新增登录接口",
                "original_content": None   # 新建文件，original_content 为 null
            },
            {
                "file_path": "backend/app/service/auth.py",
                "content": "import jwt\nclass AuthService:\n    def login(): ...",
                "change_type": "add",
                "description": "新增认证服务",
                "original_content": None
            }
        ],
        "tests_included": True,
        "test_files": [
            {
                "file_path": "backend/tests/test_auth.py",
                "content": "def test_login(): ...",
                "target_module": "app.api.v1.auth",
                "test_cases_count": 3
            }
        ],
        "summary": "添加了用户登录功能及对应测试",
        "dependencies_added": ["pyjwt"],
        "coverage_targets": ["正常登录", "密码错误", "用户不存在"]
    },
    "input_tokens": 300,
    "output_tokens": 400,
    "duration_ms": 5000,
    "reasoning": None
}

# ══════════════════════════════════════════════
# 3. 辅助函数：以可读形式输出阶段数据
# ══════════════════════════════════════════════
def censor_content(obj, max_len=200):
    """截断长字符串，方便观察结构"""
    if isinstance(obj, str) and len(obj) > max_len:
        return obj[:max_len] + "..."
    elif isinstance(obj, dict):
        return {k: censor_content(v, max_len) for k, v in obj.items()}
    elif isinstance(obj, list):
        if len(obj) > 3:
            return [censor_content(item, max_len) for item in obj[:3]] + [f"...({len(obj)-3} more)"]
        return [censor_content(item, max_len) for item in obj]
    return obj

def print_stage_data(stage: PipelineStage):
    """美观打印一个阶段的数据"""
    print(f"  ├─ 阶段: {stage.name.value}")
    print(f"  ├─ 状态: {stage.status.value}")
    input_data = censor_content(stage.input_data)
    output_data = censor_content(stage.output_data)
    print(f"  ├─ input_data: {json.dumps(input_data, indent=4, ensure_ascii=False)}")
    print(f"  └─ output_data: {json.dumps(output_data, indent=4, ensure_ascii=False)}\n")

# ══════════════════════════════════════════════
# 4. 主诊断流程
# ══════════════════════════════════════════════
async def diagnose():
    await init_db()
    async for session in get_session():
        # ───── 准备目标项目路径（空目录也可以，不影响逻辑）─────
        # 从 .env 读取，如果不存在则创建一个临时目录
        target = settings.TARGET_PROJECT_PATH
        if not target:
            # 创建一个临时目录模拟目标项目
            import tempfile
            tmpdir = tempfile.TemporaryDirectory()
            target = tmpdir.name
            settings.TARGET_PROJECT_PATH = target
            print(f"⚠️ 未配置 TARGET_PROJECT_PATH，使用临时目录: {target}")

        # ───── 模拟 LLM 调用 ─────
        with patch("app.agents.architect.architect_agent.analyze", new_callable=AsyncMock) as mock_arch, \
             patch("app.agents.designer.designer_agent.design", new_callable=AsyncMock) as mock_design, \
             patch("app.agents.multi_agent_coordinator.multi_agent_coordinator.execute_parallel", new_callable=AsyncMock) as mock_multi:
            
            mock_arch.return_value = MOCK_ARCHITECT_OUTPUT
            mock_design.return_value = MOCK_DESIGNER_OUTPUT
            mock_multi.return_value = MOCK_MULTI_AGENT_OUTPUT

            # ── 步骤 1: 创建 Pipeline ──
            print("🔵 创建 Pipeline ...")
            pipeline_read = await PipelineService.create_pipeline(
                requirement="实现用户登录功能",
                session=session
            )
            pipeline_id = pipeline_read.id
            print(f"   Pipeline ID: {pipeline_id}\n")

            # ── 步骤 2: 审批 REQUIREMENT，进入 DESIGN ──
            print("🔵 审批 REQUIREMENT → 触发 DESIGN")
            await PipelineService.approve_pipeline(
                pipeline_id, notes="架构合理", feedback=None,
                session=session
            )
            # 重新加载数据
            pipeline = await PipelineService.get_pipeline_status(pipeline_id, session)
            stages = pipeline.stages
            req_stage = next(s for s in stages if s.name == StageName.REQUIREMENT)
            des_stage = next(s for s in stages if s.name == StageName.DESIGN)
            print_stage_data(req_stage)
            print_stage_data(des_stage)

            # ── 步骤 3: 审批 DESIGN，进入 CODING ──
            print("🔵 审批 DESIGN → 触发 CODING")
            # 因为 _trigger_coding_phase 内部会调 run_coding_task 等，我们手动调用
            # 直接使用 trigger_coding_phase 方法，但需要 mock workspace 和 git 等
            with patch("app.service.pipeline.PipelineService._trigger_coding_phase", new_callable=AsyncMock) as mock_coding_phase:
                mock_coding_phase.return_value = {
                    "success": True,
                    "status": PipelineStatus.PAUSED.value,
                    "message": "Code generated",
                    "files_count": 2
                }
                with patch("app.service.workspace.workspace_context") as mock_ws:
                    mock_ws.return_value.__enter__.return_value.get_workspace_path.return_value = Path("/tmp/fake")
                    await PipelineService.approve_pipeline(
                        pipeline_id, notes="设计合理", feedback=None,
                        session=session
                    )
            
            # 手动创建 CODING 阶段、CODE_REVIEW 阶段（模拟 _trigger_coding_phase 部分逻辑）
            # 因为我们 patch 掉了真实的 _trigger_coding_phase，所以需要手动插入数据
            coding_stage = PipelineStage(
                pipeline_id=pipeline_id,
                name=StageName.CODING,
                status=StageStatus.SUCCESS,
                input_data=MOCK_DESIGNER_OUTPUT["output"],
                output_data={
                    "multi_agent_output": MOCK_MULTI_AGENT_OUTPUT["output"],
                    "tests_included": True,
                    "auto_fix_attempts": 0
                }
            )
            session.add(coding_stage)
            # 创建 CODE_REVIEW 阶段
            review_stage = PipelineStage(
                pipeline_id=pipeline_id,
                name=StageName.CODE_REVIEW,
                status=StageStatus.PENDING,
                input_data={
                    "coding_output": MOCK_MULTI_AGENT_OUTPUT["output"],
                    "target_files": {}   # 简化
                }
            )
            session.add(review_stage)
            # 更新 pipeline 当前阶段
            pipeline_orm = await session.get(Pipeline, pipeline_id)
            pipeline_orm.current_stage = StageName.CODE_REVIEW
            pipeline_orm.status = PipelineStatus.PAUSED
            await session.commit()

            # ── 步骤 4: 查看 CODE_REVIEW 阶段数据 ──
            print("🔵 进入 CODE_REVIEW 阶段，提取评审关键数据...")
            pipeline = await PipelineService.get_pipeline_status(pipeline_id, session)
            review = next((s for s in pipeline.stages if s.name == StageName.CODE_REVIEW), None)
            if review:
                print_stage_data(review)

                # 专门提取 diff 相关字段
                input_data = review.input_data
                coding_out = input_data.get("coding_output", {})
                files = coding_out.get("files", [])
                test_files = coding_out.get("test_files", [])
                print(f"  ├─ 待评审文件数: {len(files)}")
                for f in files:
                    has_original = "original_content" in f and f["original_content"] is not None
                    has_content = bool(f.get("content"))
                    print(f"  │   • {f['file_path']} (original_content: {has_original}, content: {has_content})")
                print(f"  ├─ 测试文件数: {len(test_files)}")
                print(f"  ├─ 包含测试: {coding_out.get('tests_included')}")
                print(f"  └─ 测试覆盖目标: {coding_out.get('coverage_targets')}")

            # ── 步骤 5: 与参考模型对比 ──
            print("\n🔵 对比研发流程参考模型")
            print("  参考模型阶段: 需求分析 → 方案设计 → 代码生成 → 测试生成 → 代码评审 → 交付集成")
            print("  本项目阶段:   REQUIREMENT → DESIGN → CODING(含测试生成) → CODE_REVIEW → DELIVERY")
            print("  差异:")
            print("    - 测试生成未独立成阶段，合并在 CODING 中由 MultiAgentCoordinator 自动完成")
            print("    - 代码评审目前仅依赖 CODING 输出的文件 diff，缺少系统化的“评审报告”生成")
            print("    - 交付集成阶段对应 DELIVERY，但需要在 CODE_REVIEW 审批后才能触发")

            # 关键检查：code_review 的 input_data 是否包含评审所需的全部信息
            print("\n🔍 CODE_REVIEW 数据完整性检查")
            checks = []
            if review:
                input_data = review.input_data
                files = input_data.get("coding_output", {}).get("files", [])
                if not files:
                    checks.append("❌ 无待评审文件")
                else:
                    for f in files:
                        if "original_content" not in f:
                            checks.append(f"⚠️ 文件 {f['file_path']} 缺少 original_content（无法做 diff）")
                        if "content" not in f or not f["content"]:
                            checks.append(f"❌ 文件 {f['file_path']} 缺少 content")
                if not input_data.get("coding_output", {}).get("tests_included"):
                    checks.append("⚠️ 未包含测试代码")
                if not input_data.get("coding_output", {}).get("summary"):
                    checks.append("⚠️ 缺少变更摘要")
            else:
                checks.append("❌ 未找到 CODE_REVIEW 阶段")

            if checks:
                print("\n  发现以下问题:")
                for c in checks:
                    print(f"    {c}")
            else:
                print("  ✅ 所有必要字段完整")

            # 如果发现问题，给出建议
            print("\n📢 诊断结论:")
            print("  若自动测试反复失败，请检查 CODING 阶段的 test_runner 报错日志（可在流水线详情页 Agent 终端查看）")
            print("  若 CODE_REVIEW 数据不完整，请检查 coder_agent 的 prompt 模板是否输出了完整字段，以及 _merge_results 是否正确注入了 original_content")
            print("  与参考模型的差距主要在于缺少独立的测试生成阶段和自动评审报告，可通过扩展 StageName 枚举实现")

if __name__ == "__main__":
    asyncio.run(diagnose())