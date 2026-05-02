"""
阶段处理器基础接口

定义所有阶段处理器的统一接口
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pipeline import StageName, PipelineStatus


@dataclass
class StageContext:
    """阶段执行上下文"""
    pipeline_id: int
    session: AsyncSession
    input_data: Dict[str, Any] = field(default_factory=dict)
    stage_id: Optional[int] = None
    previous_output: Optional[Dict[str, Any]] = None
    rejection_feedback: Optional[Dict[str, Any]] = None
    error_context: Optional[str] = None  # 用于传递错误上下文（如允许修改测试的授权）

    def get(self, key: str, default: Any = None) -> Any:
        """从 input_data 获取值"""
        return self.input_data.get(key, default)


@dataclass  
class StageResult:
    """阶段执行结果"""
    success: bool
    status: PipelineStatus
    message: str
    output_data: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    # 可选的额外数据
    git_branch: Optional[str] = None
    commit_hash: Optional[str] = None
    pr_url: Optional[str] = None
    
    @classmethod
    def success_result(
        cls,
        message: str,
        output_data: Optional[Dict[str, Any]] = None,
        status: PipelineStatus = PipelineStatus.SUCCESS,
        **kwargs
    ) -> "StageResult":
        """创建成功结果"""
        return cls(
            success=True,
            status=status,
            message=message,
            output_data=output_data or {},
            **kwargs
        )
    
    @classmethod
    def failure_result(
        cls,
        message: str,
        output_data: Optional[Dict[str, Any]] = None,
        status: PipelineStatus = PipelineStatus.FAILED,
        **kwargs
    ) -> "StageResult":
        """创建失败结果"""
        return cls(
            success=False,
            status=status,
            message=message,
            output_data=output_data or {},
            **kwargs
        )


class StageHandler(ABC):
    """
    阶段处理器抽象基类
    
    所有 Pipeline 阶段处理器必须实现此接口
    """
    
    @property
    @abstractmethod
    def stage_name(self) -> StageName:
        """返回处理的阶段名称"""
        pass
    
    @abstractmethod
    async def prepare(self, context: StageContext) -> StageContext:
        """
        准备阶段：获取输入数据、创建阶段记录
        
        Args:
            context: 阶段上下文
            
        Returns:
            StageContext: 更新后的上下文（包含 stage_id）
        """
        pass
    
    @abstractmethod
    async def execute(self, context: StageContext) -> StageResult:
        """
        执行阶段核心逻辑
        
        Args:
            context: 阶段上下文
            
        Returns:
            StageResult: 执行结果
        """
        pass
    
    @abstractmethod
    async def complete(self, context: StageContext, result: StageResult) -> None:
        """
        完成阶段：保存结果、更新状态
        
        Args:
            context: 阶段上下文
            result: 执行结果
        """
        pass
    
    async def handle_error(
        self,
        context: StageContext,
        error: Exception
    ) -> StageResult:
        """
        错误处理：可被子类覆盖实现自定义错误处理
        
        Args:
            context: 阶段上下文
            error: 异常对象
            
        Returns:
            StageResult: 错误结果
        """
        return StageResult.failure_result(
            message=f"{self.stage_name.value} phase failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )
    
    async def run(self, context: StageContext) -> StageResult:
        """
        运行完整阶段流程
        
        Args:
            context: 阶段上下文
            
        Returns:
            StageResult: 执行结果
        """
        try:
            # 1. 准备阶段
            context = await self.prepare(context)
            
            # 2. 执行阶段
            result = await self.execute(context)
            
            # 3. 完成阶段
            await self.complete(context, result)
            
            return result
            
        except Exception as e:
            # 错误处理
            result = await self.handle_error(context, e)
            await self.complete(context, result)
            return result
