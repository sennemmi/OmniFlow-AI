import asyncio
import sys
import json
from pathlib import Path

# 将 backend 加入环境变量
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from app.core.database import async_session_factory
from app.models.pipeline import PipelineStage, StageName

async def dump_code(pipeline_id: int):
    print(f"🔍 正在从数据库提取 Pipeline #{pipeline_id} 的代码...")
    async with async_session_factory() as session:
        stmt = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == StageName.CODING
        )
        result = await session.execute(stmt)
        stage = result.scalar_one_or_none()

        if not stage or not stage.output_data:
            print("❌ 数据库中没有找到 CODING 阶段的输出数据。")
            return

        # 提取 multi_agent_output
        output = stage.output_data.get("multi_agent_output", {})
        files = output.get("files", [])
        
        if not files:
            print("❌ AI 没有返回任何文件内容！")
            print("完整的 output_data:", json.dumps(stage.output_data, ensure_ascii=False, indent=2))
            return

        print(f"\n✅ 找到了 {len(files)} 个被修改/生成的文件：\n" + "="*50)
        for f in files:
            print(f"\n📂 文件名: {f.get('file_path')}")
            print(f"🏷️ 类型: {f.get('change_type')}")
            print("-" * 50)
            print(f.get("content", "无内容"))
            print("-" * 50)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("请提供 Pipeline ID，例如: python dump_failed_code.py 12")
        sys.exit(1)
    asyncio.run(dump_code(int(sys.argv[1])))