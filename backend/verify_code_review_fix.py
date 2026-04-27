"""
verify_code_review_fix.py
验证 CODE_REVIEW 阶段的数据完整性 —— 特别检查 original_content 是否已填充
"""
import asyncio
import sys
from pathlib import Path

# 确保能导入 backend 模块
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from sqlalchemy import select
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.models.pipeline import PipelineStage, StageName
from app.core.config import settings

# ──────────────────────────────────────────────
# 数据库连接 (复用 settings 中的 SQLite 配置)
# ──────────────────────────────────────────────
engine = create_async_engine(settings.DATABASE_URL, echo=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session():
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

# ──────────────────────────────────────────────
# 核心检查函数
# ──────────────────────────────────────────────
async def verify_code_review(pipeline_id: int):
    await init_db()
    async for session in get_session():
        # 1. 查询 CODE_REVIEW 阶段
        stmt = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == StageName.CODE_REVIEW
        )
        result = await session.execute(stmt)
        review_stage = result.scalar_one_or_none()

        if not review_stage:
            print(f"❌ 未找到 Pipeline {pipeline_id} 的 CODE_REVIEW 阶段。")
            print("   可能原因：CODING 阶段未完成或 Pipeline 失败。")
            return

        input_data = review_stage.input_data or {}
        coding_output = input_data.get("coding_output", {})

        if not coding_output:
            # 尝试 output_data (有时放在这里)
            if review_stage.output_data:
                coding_output = review_stage.output_data.get("multi_agent_output", {}) or \
                                review_stage.output_data.get("coding_output", {})
            if not coding_output:
                print("❌ CODE_REVIEW 阶段没有 coding_output 数据。")
                return

        files = coding_output.get("files", [])
        test_files = coding_output.get("test_files", [])
        summary = coding_output.get("summary", "")
        tests_included = coding_output.get("tests_included", False)
        coverage_targets = coding_output.get("coverage_targets", [])

        print(f"📊 Pipeline #{pipeline_id} CODE_REVIEW 阶段完整性检查\n")
        print(f"   代码文件数: {len(files)}")
        print(f"   测试文件数: {len(test_files)}")
        print(f"   包含测试: {tests_included}")
        print(f"   测试覆盖目标: {coverage_targets if coverage_targets else '无'}")
        print(f"   变更摘要: {summary[:80]}...\n")

        # 2. 逐文件检查 original_content
        missing_original = []
        total_files = len(files)
        for f in files:
            path = f.get("file_path", "unknown")
            original = f.get("original_content")
            has_content = bool(f.get("content"))
            # original_content 不为 None 方可 Diff (新建文件允许为 None，但修改文件应有值)
            if original is None and not f.get("is_new", True):   # 默认新建 is_new=True 则允许 None
                missing_original.append(path)
            # 简单判定：如果文件路径不包含“test_”，且 original_content 为空且 content 不为空，认为可能是修改但无原始
            if original is None and not ("test_" in path or "tests/" in path):
                missing_original.append(path)

        missing_original = list(set(missing_original))
        if missing_original:
            print("⚠️ 以下文件缺少 original_content（可能无法生成有效 Diff）：")
            for path in missing_original:
                print(f"   - {path}")
        else:
            print("✅ 所有文件都具备 original_content，Diff 视图将正常显示对比")

        # 3. 检查是否有测试代码
        if not test_files and not tests_included:
            print("\n⚠️ 没有测试文件，代码评审中缺少测试覆盖率信息")
        else:
            print("\n✅ 测试文件已嵌入到评审数据中")

        # 4. 给出修复建议（如果存在问题）
        if missing_original:
            print("\n🔧 修复建议：")
            print("   - 确保 CODING 阶段的 target_files 包含所有需要修改的现有文件")
            print("   - 在 agent_coordinator.py 的 get_target_files_for_coding 中增加 fallback 逻辑")
            print("   - 检查 affected_files 的路径是否正确（是否多了/少了 backend/ 前缀）\n")
        else:
            print("\n🎉 恭喜！CODE_REVIEW 阶段数据完整，可以正常评审。")

        # 额外展示几个文件的 original_content 前 100 字符作为样例
        print("\n📝 取样展示 original_content (前100字符)：")
        for f in files[:3]:
            org = f.get("original_content")
            if org:
                print(f"   - {f['file_path']}: {org[:100]}...")
            else:
                print(f"   - {f['file_path']}: (无原文 — 新建文件)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python verify_code_review_fix.py <pipeline_id>")
        sys.exit(1)

    pid = int(sys.argv[1])
    asyncio.run(verify_code_review(pid))