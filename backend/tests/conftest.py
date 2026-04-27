import asyncio
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel

# 确保 backend 目录在路径中
sys.path.insert(0, str(Path(__file__).parent.parent))

# ─── 数据库 Fixture：SQLite 内存数据库 ───────────────────────────────────────

@pytest_asyncio.fixture
async def db_session():
    """
    使用 SQLite 内存数据库创建真实的数据库 session
    每个测试运行在独立环境，自动建表和销毁
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # 创建 session
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    # 清理
    await engine.dispose()


@pytest.fixture
def override_get_session(db_session):
    """用于 FastAPI 依赖注入的 Override"""
    async def _get_db():
        yield db_session
    return _get_db


# ─── 全局 Fixture：Mock 掉所有外部依赖 ───────────────────────────────────────

@pytest.fixture
def mock_llm_response():
    """mock Claude API 响应，避免真实调用"""
    return {
        "success": True,
        "output": {
            "files": [
                {"file_path": "app/service/example.py", "content": "def hello(): return 'world'", "change_type": "add"}
            ],
            "summary": "mock output",
            "dependencies_added": []
        }
    }


@pytest.fixture
def mock_db_session_mock():
    """mock 数据库 session，避免真实 DB 连接（用于不需要真实 DB 的测试）"""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_git_service():
    """mock Git 操作"""
    git = MagicMock()
    git.create_branch = MagicMock()
    git.add_files = MagicMock()
    git.has_changes = MagicMock(return_value=True)
    git.commit_changes = MagicMock()
    git.get_last_commit_hash = MagicMock(return_value="abc123")
    git.push_branch = MagicMock(return_value=MagicMock(success=True))
    return git


# ─── VCR Fixture：用于录制/回放 LLM 响应 ───────────────────────────────────────

@pytest.fixture(scope="module")
def vcr_config():
    """VCR 配置"""
    return {
        "filter_headers": [("authorization", "DUMMY")],
        "filter_query_parameters": [("api_key", "DUMMY")],
    }
