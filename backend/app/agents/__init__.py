# AI Agent 层 - 唯一能调用 LLM 的地方

from app.agents.architect import architect_agent
from app.agents.designer import designer_agent
from app.agents.coder import coder_agent
from app.agents.tester import tester_agent, test_agent
from app.agents.file_writer import FileWriterAgent, get_file_writer
from app.agents.schemas import (
    BaseAgentOutput,
    ArchitectOutput,
    DesignerOutput,
    CoderOutput,
    TesterOutput,
    FileChange,
    TestFile,
)

__all__ = [
    # Agent 实例
    "architect_agent",
    "designer_agent",
    "coder_agent",
    "tester_agent",
    "test_agent",  # 向后兼容
    # 文件写入 Agent（纯 Python，不走 LLM）
    "FileWriterAgent",
    "get_file_writer",
    # 输出模型
    "BaseAgentOutput",
    "ArchitectOutput",
    "DesignerOutput",
    "CoderOutput",
    "TesterOutput",
    # 辅助模型
    "FileChange",
    "TestFile",
]
