"""
数据库连接管理
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings

# 创建异步引擎 - echo=False 彻底关闭 SQLAlchemy 详细日志
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
)

# 创建异步会话工厂
async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_session() -> AsyncSession:
    """获取数据库会话（依赖注入使用）"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """初始化数据库表"""
    async with engine.begin() as conn:
        # 导入所有模型以确保它们被注册
        from app.models.pipeline import Pipeline, PipelineStage

        await conn.run_sync(SQLModel.metadata.create_all)

    # 设置 SQLAlchemy 慢查询监听
    from app.core.logging import setup_sqlalchemy_logging
    setup_sqlalchemy_logging(engine)
