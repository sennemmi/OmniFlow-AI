"""
Repository 层

职责：
- 封装所有数据库查询逻辑
- 提供类型安全的查询接口
- 隐藏 SQL 表达式细节

设计原则：
- Service 层不直接接触 SQL 表达式
- 所有查询通过 Repository 方法完成
"""

from app.repositories.pipeline_stage_repository import PipelineStageRepository

__all__ = ["PipelineStageRepository"]
