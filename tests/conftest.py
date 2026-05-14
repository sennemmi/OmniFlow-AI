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


# 注意：pytest-asyncio 0.24+ 会自动管理事件循环
# 不需要自定义 event_loop fixture，否则可能导致兼容性问题


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
    (project_dir / "frontend" / "src" / "components").mkdir(parents=True)

    return project_dir


# 自定义 pytest 标记
def pytest_configure(config):
    """配置 pytest 标记"""
    config.addinivalue_line("markers", "functional: 功能测试")
    config.addinivalue_line("markers", "pipeline: Pipeline 测试")
    config.addinivalue_line("markers", "agent: Agent 测试")
    config.addinivalue_line("markers", "visual: 可视化工作区测试")
    config.addinivalue_line("markers", "defense: 防御性测试")
    config.addinivalue_line("markers", "security: 安全测试")
    config.addinivalue_line("markers", "performance: 性能测试")
    config.addinivalue_line("markers", "resilience: 弹性测试")
    config.addinivalue_line("markers", "e2e: 端到端测试")
    config.addinivalue_line("markers", "slow: 慢速测试")
