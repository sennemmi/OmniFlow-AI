"""
阶段处理器注册表

管理所有阶段处理器的注册和查找
"""

from typing import Dict, Optional, Type

from app.models.pipeline import StageName
from app.service.stage_handlers.base import StageHandler


class StageHandlerRegistry:
    """
    阶段处理器注册表
    
    单例模式管理所有阶段处理器
    """
    
    _instance: Optional["StageHandlerRegistry"] = None
    _handlers: Dict[StageName, StageHandler]
    
    def __new__(cls) -> "StageHandlerRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = {}
        return cls._instance
    
    def register(self, handler: StageHandler) -> None:
        """
        注册阶段处理器
        
        Args:
            handler: 阶段处理器实例
        """
        self._handlers[handler.stage_name] = handler
    
    def get(self, stage_name: StageName) -> Optional[StageHandler]:
        """
        获取阶段处理器
        
        Args:
            stage_name: 阶段名称
            
        Returns:
            Optional[StageHandler]: 阶段处理器，未找到返回 None
        """
        return self._handlers.get(stage_name)
    
    def has_handler(self, stage_name: StageName) -> bool:
        """
        检查是否有处理器
        
        Args:
            stage_name: 阶段名称
            
        Returns:
            bool: 是否有处理器
        """
        return stage_name in self._handlers
    
    def get_all_handlers(self) -> Dict[StageName, StageHandler]:
        """
        获取所有处理器
        
        Returns:
            Dict[StageName, StageHandler]: 所有处理器
        """
        return self._handlers.copy()
    
    def clear(self) -> None:
        """清空所有处理器（主要用于测试）"""
        self._handlers.clear()


def get_registry() -> StageHandlerRegistry:
    """获取注册表实例"""
    return StageHandlerRegistry()


def register_handler(handler_class: Type[StageHandler]) -> StageHandler:
    """
    装饰器：自动注册阶段处理器
    
    用法：
        @register_handler
        class MyHandler(StageHandler):
            ...
    """
    handler = handler_class()
    get_registry().register(handler)
    return handler
