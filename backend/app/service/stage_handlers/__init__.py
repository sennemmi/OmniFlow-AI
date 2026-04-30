"""
阶段处理器模块

提供 Pipeline 各阶段的统一处理接口
使用策略模式将阶段逻辑从 PipelineService 中解耦
"""

from app.service.stage_handlers.base import StageHandler, StageContext, StageResult
from app.service.stage_handlers.requirement_handler import RequirementHandler
from app.service.stage_handlers.design_handler import DesignHandler
from app.service.stage_handlers.coding_handler import CodingHandler
from app.service.stage_handlers.testing_handler import TestingHandler
from app.service.stage_handlers.delivery_handler import DeliveryHandler
from app.service.stage_handlers.registry import StageHandlerRegistry

__all__ = [
    "StageHandler",
    "StageContext", 
    "StageResult",
    "RequirementHandler",
    "DesignHandler",
    "CodingHandler",
    "TestingHandler",
    "DeliveryHandler",
    "StageHandlerRegistry",
]
