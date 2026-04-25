"""
Pipeline 数据模型定义
SQLModel 结构定义层
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from sqlmodel import SQLModel, Field, Relationship, Column, JSON

from app.core.timezone import now


class PipelineStatus(str, Enum):
    """Pipeline 状态枚举"""
    RUNNING = "running"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"


class StageName(str, Enum):
    """阶段名称枚举"""
    REQUIREMENT = "REQUIREMENT"
    DESIGN = "DESIGN"
    CODING = "CODING"
    CODE_REVIEW = "CODE_REVIEW"
    DELIVERY = "DELIVERY"


class StageStatus(str, Enum):
    """阶段状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class PipelineBase(SQLModel):
    """Pipeline 基础模型"""
    name: str = Field(default="", description="Pipeline 名称")
    description: str = Field(description="原始需求描述")
    status: PipelineStatus = Field(
        default=PipelineStatus.RUNNING,
        description="Pipeline 整体状态"
    )
    current_stage: Optional[StageName] = Field(
        default=None,
        description="当前执行阶段"
    )


class Pipeline(PipelineBase, table=True):
    """
    Pipeline 数据库表模型
    
    代表一个完整的研发流程实例
    """
    __tablename__ = "pipelines"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    
    # 关联的阶段
    stages: List["PipelineStage"] = Relationship(back_populates="pipeline")


class PipelineStageBase(SQLModel):
    """PipelineStage 基础模型"""
    name: StageName = Field(description="阶段名称")
    status: StageStatus = Field(default=StageStatus.PENDING)
    input_data: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON)
    )
    output_data: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON)
    )


class PipelineStage(PipelineStageBase, table=True):
    """
    PipelineStage 数据库表模型

    代表 Pipeline 中的一个阶段
    """
    __tablename__ = "pipeline_stages"

    id: Optional[int] = Field(default=None, primary_key=True)
    pipeline_id: int = Field(foreign_key="pipelines.id")
    created_at: datetime = Field(default_factory=now)
    completed_at: Optional[datetime] = Field(default=None)

    # 可观测性指标字段
    input_tokens: int = Field(default=0, description="输入 Token 数")
    output_tokens: int = Field(default=0, description="输出 Token 数")
    reasoning: Optional[str] = Field(default=None, description="AI 推理过程")
    duration_ms: int = Field(default=0, description="执行耗时（毫秒）")
    retry_count: int = Field(default=0, description="重试次数")

    # 关联的 Pipeline
    pipeline: Optional[Pipeline] = Relationship(back_populates="stages")


# Pydantic 模型用于 API 响应
class PipelineStageRead(SQLModel):
    """PipelineStage 读取模型 - 必须给所有字段默认值防止校验失败"""
    id: int
    name: StageName
    status: StageStatus
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    # 可观测性指标 - 必须标记为 Optional 并有默认值
    input_tokens: Optional[int] = 0
    output_tokens: Optional[int] = 0
    reasoning: Optional[str] = None
    duration_ms: Optional[int] = 0
    retry_count: Optional[int] = 0

    class Config:
        from_attributes = True


class PipelineRead(SQLModel):
    """Pipeline 读取模型 - 用于 API 响应"""
    id: int
    description: str
    status: PipelineStatus
    current_stage: Optional[StageName]
    created_at: datetime
    updated_at: datetime
    stages: Optional[List[PipelineStageRead]] = None
    
    class Config:
        from_attributes = True


class PipelineCreate(SQLModel):
    """Pipeline 创建模型 - 用于 API 请求"""
    description: str


class ArchitectOutput(SQLModel):
    """架构师 Agent 输出结构"""
    feature_description: str = Field(description="功能描述")
    affected_files: List[str] = Field(description="受影响文件列表")
    estimated_effort: str = Field(description="预估工作量")
    technical_design: Optional[str] = Field(default=None, description="技术设计方案")
