"""
Agent 输出模型基类
统一所有 Agent 的输出结构
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class BaseAgentOutput(BaseModel):
    """
    Agent 输出基类
    
    所有 Agent 的输出模型必须继承此类
    包含通用的元数据字段
    """
    summary: str = Field(default="", description="执行摘要")
    dependencies_added: List[str] = Field(default_factory=list, description="新增依赖列表")
    input_tokens: int = Field(default=0, description="输入 Token 数")
    output_tokens: int = Field(default=0, description="输出 Token 数")
    duration_ms: int = Field(default=0, description="执行耗时(毫秒)")
    reasoning: Optional[str] = Field(default=None, description="模型推理过程")


class FileChange(BaseModel):
    """
    文件变更模型 - Line-Number Based Patching Protocol

    采用 Claude Code 风格的行号坐标系统，避免 JSON 字段内大量换行和转义符导致的解析失败。
    """
    file_path: str = Field(description="文件相对路径")
    change_type: str = Field(description="变更类型: add | modify | delete")

    # 局部修改的核心字段（行号坐标系统）
    start_line: Optional[int] = Field(None, description="起始行号(1-based, 包含)")
    end_line: Optional[int] = Field(None, description="结束行号(1-based, 包含)")
    replace_block: Optional[str] = Field(None, description="新代码块，将替换 start_line 到 end_line 的所有行")

    # 仅用于新建文件 (change_type="add")
    content: Optional[str] = Field(None, description="完整文件内容（仅 add 时使用）")

    # 可选：用于验证的原始代码片段（帮助检测行号漂移）
    expected_original: Optional[str] = Field(None, description="预期被替换的原始代码片段（用于验证）")

    description: str = Field("", description="改动说明")


class TestFile(BaseModel):
    """测试文件模型"""
    file_path: str = Field(description="测试文件路径")
    content: str = Field(description="完整的测试文件内容")
    target_module: str = Field(description="被测试的模块路径")
    test_cases_count: int = Field(default=0, description="测试用例数量")


class ArchitectOutput(BaseAgentOutput):
    """
    架构师 Agent 输出
    
    负责分析需求并输出技术设计方案
    """
    feature_description: str = Field(description="功能描述")
    affected_files: List[str] = Field(description="受影响文件列表")
    estimated_effort: str = Field(description="预估工作量")
    technical_design: Optional[str] = Field(default=None, description="技术设计方案")


class DesignerOutput(BaseAgentOutput):
    """
    设计师 Agent 输出
    
    负责输出详细的技术设计方案
    """
    technical_design: str = Field(description="技术设计方案概述")
    api_endpoints: List[Dict[str, str]] = Field(default_factory=list, description="API 端点列表")
    function_changes: List[Dict[str, Any]] = Field(default_factory=list, description="函数修改列表")
    logic_flow: str = Field(default="", description="逻辑流图（文本描述）")
    affected_files: List[str] = Field(default_factory=list, description="受影响文件列表")


class CoderOutput(BaseAgentOutput):
    """
    编码 Agent 输出
    
    负责生成代码变更
    """
    files: List[FileChange] = Field(default_factory=list, description="变更的文件列表")
    tests_included: bool = Field(default=False, description="是否包含测试代码")


class TesterOutput(BaseAgentOutput):
    """
    测试 Agent 输出
    
    负责生成单元测试代码
    """
    test_files: List[TestFile] = Field(default_factory=list, description="测试文件列表")
    coverage_targets: List[str] = Field(default_factory=list, description="计划覆盖的测试目标")
