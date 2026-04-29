"""
Pytest 配置文件

提供测试共享的 fixtures 和配置
"""

import os
import pytest
import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

# 确保测试环境有基本的配置
os.environ.setdefault("USE_MODELSCOPE", "true")
os.environ.setdefault("DEFAULT_MODEL", "Qwen/Qwen2.5-72B-Instruct")
os.environ.setdefault("TARGET_PROJECT_PATH", "/tmp/test_project")


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """
    确保测试环境配置正确加载

    在导入任何使用配置的模块之前设置环境变量
    """
    # 强制重新加载配置模块，确保环境变量生效
    import importlib
    from app.core import config
    importlib.reload(config)
    yield


@pytest.fixture(scope="session")
def event_loop():
    """创建会话级别的事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_session():
    """提供模拟的数据库会话"""
    return MagicMock()


@pytest.fixture
def mock_pipeline():
    """提供模拟的 Pipeline 对象"""
    from app.models.pipeline import Pipeline, PipelineStatus, StageName

    pipeline = MagicMock(spec=Pipeline)
    pipeline.id = 1
    pipeline.status = PipelineStatus.RUNNING
    pipeline.current_stage = StageName.CODING
    pipeline.description = "Test pipeline"
    return pipeline


@pytest.fixture
def mock_pipeline_stage():
    """提供模拟的 PipelineStage 对象"""
    from app.models.pipeline import PipelineStage, StageStatus, StageName

    stage = MagicMock(spec=PipelineStage)
    stage.id = 1
    stage.pipeline_id = 1
    stage.name = StageName.CODING
    stage.status = StageStatus.PENDING
    stage.input_data = {}
    stage.output_data = {}
    return stage


@pytest.fixture
def sample_python_code():
    """提供示例 Python 代码用于测试"""
    return '''
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

class Calculator:
    """Simple calculator class."""

    def multiply(self, x: float, y: float) -> float:
        return x * y

    def divide(self, x: float, y: float) -> float:
        if y == 0:
            raise ValueError("Cannot divide by zero")
        return x / y
'''


@pytest.fixture
def sample_react_code():
    """提供示例 React/TypeScript 代码用于测试"""
    return '''
import React, { useState } from 'react';

interface CounterProps {
  initialValue?: number;
}

export const Counter: React.FC<CounterProps> = ({ initialValue = 0 }) => {
  const [count, setCount] = useState(initialValue);

  const increment = () => setCount(c => c + 1);
  const decrement = () => setCount(c => c - 1);

  return (
    <div className="counter">
      <button onClick={decrement}>-</button>
      <span>{count}</span>
      <button onClick={increment}>+</button>
    </div>
  );
};
'''


@pytest.fixture
def temp_project_dir(tmp_path):
    """提供临时项目目录"""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # 创建标准目录结构
    (project_dir / "backend" / "app").mkdir(parents=True)
    (project_dir / "backend" / "tests" / "unit").mkdir(parents=True)
    (project_dir / "backend" / "tests" / "ai_generated").mkdir(parents=True)

    return project_dir
