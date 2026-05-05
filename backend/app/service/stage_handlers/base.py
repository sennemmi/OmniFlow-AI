"""
阶段处理器基础接口

定义所有阶段处理器的统一接口
"""

from abc import ABC, abstractmethod
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.pipeline import StageName, PipelineStatus
from app.utils.agent_debug_utils import get_agent_debugger


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
    
    def __init__(self):
        """初始化处理器，使用全局 AgentDebugger 实例"""
        self.debugger = get_agent_debugger()

    def _save_agent_log(
        self,
        agent_name: str,
        stage: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        【封装】保存 Agent 调用日志

        简化子类中的 Agent 调试记录，减少样板代码

        Args:
            agent_name: Agent 名称
            stage: 阶段标识
            input_data: 输入数据
            output_data: 输出数据
            system_prompt: 系统提示词
            **kwargs: 额外的元数据
        """
        if not self.debugger:
            return

        metadata = {
            "input_tokens": output_data.get("input_tokens", 0),
            "output_tokens": output_data.get("output_tokens", 0),
            "duration_ms": output_data.get("duration_ms", 0),
        }
        metadata.update(kwargs)

        self.debugger.save_agent_io(
            agent_name=agent_name,
            stage=stage,
            input_data=input_data,
            output_data=output_data,
            metadata=metadata,
            success=output_data.get("success", False),
            error=output_data.get("error"),
            tool_calls=output_data.get("tool_results", []),
            system_prompt=system_prompt
        )

    def _build_metrics(
        self,
        agent_result: Dict[str, Any],
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Normalize agent metrics and estimate token counts when a provider omits usage."""
        input_tokens = agent_result.get("input_tokens", 0) or 0
        output_tokens = agent_result.get("output_tokens", 0) or 0

        if input_tokens <= 0 and input_data:
            input_tokens = max(1, int(len(json.dumps(input_data, ensure_ascii=False)) * 0.3))
        if output_tokens <= 0 and output_data:
            output_tokens = max(1, int(len(json.dumps(output_data, ensure_ascii=False)) * 0.3))

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_ms": agent_result.get("duration_ms", 0) or 0,
            "retry_count": agent_result.get("retry_count", 0) or 0,
            "reasoning": agent_result.get("reasoning"),
        }
    
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
    
    async def on_approved(
        self,
        context: StageContext,
        notes: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> StageResult:
        """
        阶段被批准后的处理逻辑
        
        子类可重写此方法实现自定义的审批后逻辑。
        默认实现返回成功结果，表示直接进入下一阶段。
        
        Args:
            context: 阶段上下文
            notes: 审批备注
            feedback: 反馈建议
            
        Returns:
            StageResult: 处理结果
        """
        return StageResult.success_result(
            message=f"{self.stage_name.value} stage approved",
            status=PipelineStatus.PAUSED
        )
    
    async def on_rejected(
        self,
        context: StageContext,
        reason: str,
        suggested_changes: Optional[str] = None
    ) -> StageResult:
        """
        阶段被驳回后的处理逻辑
        
        子类可重写此方法实现自定义的驳回后逻辑。
        默认实现返回成功结果，表示重新执行当前阶段。
        
        Args:
            context: 阶段上下文
            reason: 驳回原因
            suggested_changes: 建议修改
            
        Returns:
            StageResult: 处理结果
        """
        return StageResult.success_result(
            message=f"{self.stage_name.value} stage rejected, will rerun",
            status=PipelineStatus.RUNNING
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
