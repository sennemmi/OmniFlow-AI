"""
Stage Handler Base Interface

Defines unified interface for all stage handlers
"""

from abc import ABC, abstractmethod
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.sse_log_buffer import push_error_details, push_stage_start, push_stage_complete
from app.models.pipeline import StageName, PipelineStatus
from app.utils.agent_debug_utils import get_agent_debugger
from app.utils.log_utils import PipelineLogger, LogContext


@dataclass
class StageContext:
    """Stage execution context"""
    pipeline_id: int
    session: AsyncSession
    input_data: Dict[str, Any] = field(default_factory=dict)
    stage_id: Optional[int] = None
    previous_output: Optional[Dict[str, Any]] = None
    rejection_feedback: Optional[Dict[str, Any]] = None
    error_context: Optional[str] = None  # For passing error context (e.g., authorization to modify tests)

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from input_data"""
        return self.input_data.get(key, default)


@dataclass  
class StageResult:
    """Stage execution result"""
    success: bool
    status: PipelineStatus
    message: str
    output_data: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    # Optional extra data
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
        """Create success result"""
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
        """Create failure result"""
        return cls(
            success=False,
            status=status,
            message=message,
            output_data=output_data or {},
            **kwargs
        )


class StageHandler(ABC):
    """
    Stage Handler Abstract Base Class
    
    All Pipeline stage handlers must implement this interface
    """
    
    def __init__(self):
        """Initialize handler with global AgentDebugger instance"""
        self.debugger = get_agent_debugger()

    def _get_logger(self, pipeline_id: int) -> PipelineLogger:
        """Create a new PipelineLogger — stateless, no shared mutable state"""
        return PipelineLogger(pipeline_id, self.stage_name.value)

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
        [Encapsulated] Save Agent call log

        Simplifies Agent debugging recording in subclasses, reduces boilerplate code

        Args:
            agent_name: Agent name
            stage: Stage identifier
            input_data: Input data
            output_data: Output data
            system_prompt: System prompt
            **kwargs: Extra metadata
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
        """Return the stage name being processed"""
        pass
    
    @abstractmethod
    async def prepare(self, context: StageContext) -> StageContext:
        """
        Preparation phase: get input data, create stage record
        
        Args:
            context: Stage context
            
        Returns:
            StageContext: Updated context (containing stage_id)
        """
        pass
    
    @abstractmethod
    async def execute(self, context: StageContext) -> StageResult:
        """
        Execute stage core logic
        
        Args:
            context: Stage context
            
        Returns:
            StageResult: Execution result
        """
        pass
    
    @abstractmethod
    async def complete(self, context: StageContext, result: StageResult) -> None:
        """
        Complete phase: save results, update status
        
        Args:
            context: Stage context
            result: Execution result
        """
        pass
    
    async def handle_error(
        self,
        context: StageContext,
        error: Exception
    ) -> StageResult:
        """
        Error handling: can be overridden by subclasses for custom error handling
        
        Args:
            context: Stage context
            error: Exception object
            
        Returns:
            StageResult: Error result
        """
        logger = self._get_logger(context.pipeline_id)
        
        # Log detailed error with stack trace
        await logger.error_details(error, context=f"Stage {self.stage_name.value}")
        
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
        Processing logic after stage is approved
        
        Subclasses can override this method for custom post-approval logic.
        Default implementation returns success result, indicating direct entry to next stage.
        
        Args:
            context: Stage context
            notes: Approval notes
            feedback: Feedback suggestions
            
        Returns:
            StageResult: Processing result
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
        Processing logic after stage is rejected
        
        Subclasses can override this method for custom post-rejection logic.
        Default implementation returns success result, indicating re-execution of current stage.
        
        Args:
            context: Stage context
            reason: Rejection reason
            suggested_changes: Suggested changes
            
        Returns:
            StageResult: Processing result
        """
        return StageResult.success_result(
            message=f"{self.stage_name.value} stage rejected, will rerun",
            status=PipelineStatus.RUNNING
        )
    
    async def _save_stage_result(
        self,
        context: StageContext,
        result: StageResult
    ) -> None:
        """将阶段执行结果持久化到 stage 记录（供 complete 使用）"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage, StageStatus
        from app.core.timezone import now

        if not context.stage_id:
            return

        statement = select(PipelineStage).where(PipelineStage.id == context.stage_id)
        query_result = await context.session.execute(statement)
        stage = query_result.scalar_one_or_none()
        if not stage:
            return

        stage.output_data = result.output_data
        if result.success:
            if result.status == PipelineStatus.PAUSED:
                stage.status = StageStatus.SUCCESS
            elif result.status == PipelineStatus.SUCCESS:
                stage.status = StageStatus.SUCCESS
            elif result.status == PipelineStatus.RUNNING:
                stage.status = StageStatus.RUNNING
            else:
                stage.status = StageStatus.SUCCESS
        else:
            stage.status = StageStatus.FAILED
        stage.completed_at = now()
        stage.input_tokens = result.metrics.get("input_tokens", 0)
        stage.output_tokens = result.metrics.get("output_tokens", 0)
        stage.duration_ms = result.metrics.get("duration_ms", 0)
        stage.retry_count = result.metrics.get("retry_count", 0)
        stage.reasoning = result.metrics.get("reasoning")
        await context.session.commit()

    async def _update_pipeline_after_stage(
        self,
        context: StageContext,
        result: StageResult,
        *,
        remove_buffer_on_failure: bool = True
    ) -> None:
        """更新 Pipeline 状态（成功则暂停/成功，失败则标记失败）"""
        from app.service.workflow import WorkflowService

        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if not pipeline:
            return

        if result.success:
            if result.status == PipelineStatus.PAUSED:
                await WorkflowService.set_pipeline_paused(pipeline, context.session)
            elif result.status == PipelineStatus.RUNNING:
                await WorkflowService.set_pipeline_running(pipeline, context.session)
            else:
                await WorkflowService.set_pipeline_success(pipeline, context.session)
        else:
            await WorkflowService.set_pipeline_failed(pipeline, context.session)
            if remove_buffer_on_failure:
                from app.core.sse_log_buffer import remove_buffer
                remove_buffer(context.pipeline_id)

    async def run(self, context: StageContext) -> StageResult:
        """
        Run complete stage workflow

        All state is local — handler instances are shared across pipelines,
        so instance variables must not hold per-execution state.

        Args:
            context: Stage context

        Returns:
            StageResult: Execution result
        """
        logger = self._get_logger(context.pipeline_id)
        _start_time = time.perf_counter()

        try:
            # 1. Preparation phase - with logging
            await push_stage_start(context.pipeline_id, self.stage_name.value, context.input_data)
            context = await self.prepare(context)

            # 2. Execution phase
            result = await self.execute(context)

            # 3. Completion phase
            await self.complete(context, result)

            # Log stage completion
            duration_ms = int((time.perf_counter() - _start_time) * 1000)
            await push_stage_complete(
                context.pipeline_id,
                self.stage_name.value,
                result.success,
                result.output_data if result.success else None,
                duration_ms
            )

            return result

        except Exception as e:
            # Error handling with detailed logging
            duration_ms = int((time.perf_counter() - _start_time) * 1000)

            # Rollback 阶段中可能的部分写入，避免脏数据
            await context.session.rollback()

            # Log detailed error
            await push_error_details(context.pipeline_id, e, context=f"Stage {self.stage_name.value}")
            await push_stage_complete(
                context.pipeline_id,
                self.stage_name.value,
                False,
                None,
                duration_ms
            )

            result = await self.handle_error(context, e)
            await self.complete(context, result)
            return result
