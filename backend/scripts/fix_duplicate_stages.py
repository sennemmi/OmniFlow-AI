"""
一次性脚本：清理 pipeline_stages 重复数据并添加唯一约束
用法：在 backend 目录下执行 python scripts/fix_duplicate_stages.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import async_session_factory, engine


async def main():
    async with async_session_factory() as session:
        # 1. 查找所有 (pipeline_id, name) 重复的记录
        find_dupes = text("""
            SELECT pipeline_id, name, COUNT(*) as cnt
            FROM pipeline_stages
            GROUP BY pipeline_id, name
            HAVING COUNT(*) > 1
        """)
        result = await session.execute(find_dupes)
        dupes = [(row.pipeline_id, row.name, row.cnt) for row in result.fetchall()]

        if not dupes:
            print("没有发现重复数据。")
        else:
            print(f"发现 {len(dupes)} 组重复：")
            for pid, name, cnt in dupes:
                print(f"  pipeline_id={pid}, name={name}, 重复{cnt}条")

            # 2. 删除重复行，保留 id 最大的那条
            # SQLite 不支持 DELETE ... JOIN，用子查询删除
            delete_dupes = text("""
                DELETE FROM pipeline_stages
                WHERE id NOT IN (
                    SELECT max_id FROM (
                        SELECT MAX(id) as max_id
                        FROM pipeline_stages
                        GROUP BY pipeline_id, name
                    )
                )
            """)
            result = await session.execute(delete_dupes)
            print(f"\n已删除 {result.rowcount} 条重复记录。")

        await session.commit()

    # 3. 创建唯一索引
    async with engine.begin() as conn:
        # 先检查索引是否已存在
        check_idx = text("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND tbl_name='pipeline_stages'
              AND name='uq_pipeline_stages_pipeline_id_name'
        """)
        result = await conn.execute(check_idx)
        if result.fetchone():
            print("唯一索引已存在，跳过创建。")
        else:
            create_idx = text("""
                CREATE UNIQUE INDEX uq_pipeline_stages_pipeline_id_name
                ON pipeline_stages(pipeline_id, name)
            """)
            await conn.execute(create_idx)
            print("唯一索引 uq_pipeline_stages_pipeline_id_name 创建成功。")


if __name__ == "__main__":
    asyncio.run(main())
