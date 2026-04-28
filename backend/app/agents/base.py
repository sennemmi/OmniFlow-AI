"""
Agent 基类
统一 LLM 调用逻辑 - 唯一能调用 LLM 的地方

原则：
- 严禁在 agents/ 之外的地方编写模型调用逻辑
- 支持 ModelScope (魔搭) 和 OpenAI 运行时切换
- 保持 Pydantic 解析逻辑不变
- 自动捕获 Token 和耗时指标
- 使用策略模式注入 LLM Provider
"""

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, TypeVar, Generic, TypedDict

from pydantic import BaseModel, ValidationError
from langgraph.graph import StateGraph, END

from app.core.config import settings
from app.core.logging import agent_metrics_context, MetricsCollector, error
from app.core.sse_log_buffer import push_log
from app.agents.llm_providers import (
    LLMProvider, LLMCallError, get_llm_provider
)
import logging

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Agent 错误"""
    pass


class JSONParseError(AgentError):
    """JSON 解析错误"""
    pass


T = TypeVar('T', bound=BaseModel)


# 使用 Dict 而不是 TypedDict，以支持任意业务字段
BaseAgentState = Dict[str, Any]


class LangGraphAgent(ABC, Generic[T]):
    """
    基于 LangGraph 的 Agent 基类

    统一 LLM 调用逻辑，支持：
    - ModelScope (魔搭) 和 OpenAI 运行时切换（通过 Provider 策略）
    - 自动 Token 和耗时统计
    - JSON 输出解析和校验
    - 重试机制
    - LangGraph 状态机

    子类只需实现：
    - system_prompt: 系统 Prompt
    - build_user_prompt(): 构建用户 Prompt
    - parse_output(): 解析 LLM 输出
    - validate_output(): 校验输出为 Pydantic 模型

    八荣八耻：
    - 严禁在 agents/ 之外的地方编写模型调用逻辑
    """

    MAX_RETRIES: int = 3

    def __init__(self, agent_name: str, llm_provider: Optional[LLMProvider] = None):
        """
        初始化 Agent

        Args:
            agent_name: Agent 名称（用于日志和指标）
            llm_provider: LLM Provider 实例，None 则使用默认 Provider
        """
        self.agent_name = agent_name
        self.metrics_collector = MetricsCollector()
        self._llm_provider = llm_provider or get_llm_provider()
        self.graph = self._build_graph()
    
    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """系统 Prompt，子类必须实现"""
        pass
    
    @abstractmethod
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt，子类必须实现
        
        Args:
            state: 当前 LangGraph 状态
            
        Returns:
            str: 用户 Prompt
        """
        pass
    
    @abstractmethod
    def parse_output(self, response: str) -> Dict[str, Any]:
        """
        解析 LLM 输出，子类必须实现
        
        Args:
            response: LLM 原始响应
            
        Returns:
            Dict: 解析后的输出
        """
        pass
    
    @abstractmethod
    def validate_output(self, output: Dict[str, Any]) -> T:
        """
        校验输出，子类必须实现
        
        Args:
            output: 解析后的输出字典
            
        Returns:
            T: 校验后的 Pydantic 模型实例
        """
        pass
    
    def _build_graph(self) -> StateGraph:
        """
        构建 LangGraph 状态机（模板方法）
        
        统一的执行流程：
        entry_point -> process -> validate -> (success/retry/failed) -> END
        
        Returns:
            StateGraph: 编译后的状态图
        """
        # 定义状态图 - 使用基类状态类型
        workflow = StateGraph(BaseAgentState)
        
        # 添加节点
        workflow.add_node("process", self._process_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_node("retry", self._retry_node)
        
        # 添加边
        workflow.set_entry_point("process")
        workflow.add_edge("process", "validate")
        
        # 条件边：验证成功 -> END，失败且未超次 -> retry，失败且超次 -> END
        workflow.add_conditional_edges(
            "validate",
            self._should_retry,
            {
                "success": END,
                "retry": "retry",
                "failed": END
            }
        )
        workflow.add_edge("retry", "process")
        
        return workflow.compile()
    
    async def _process_node(self, state: BaseAgentState) -> BaseAgentState:
        """
        处理节点：调用 LLM 生成输出
        
        Args:
            state: 当前状态
            
        Returns:
            BaseAgentState: 更新后的状态（包含 Token 信息）
        """
        try:
            # 构建用户提示
            user_prompt = self.build_user_prompt(state)
            
            # 调用 LLM（现在返回字典包含 Token 信息）
            response = await self._call_llm(self.system_prompt, user_prompt)
            
            # 尝试解析输出
            parsed_output = self.parse_output(response["content"])
            
            return {
                **state,
                "output": parsed_output,
                "error": None,
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0)
            }
        except Exception as e:
            return {
                **state,
                "output": None,
                "error": str(e),
                "input_tokens": 0,
                "output_tokens": 0
            }
    
    def _validate_node(self, state: BaseAgentState) -> BaseAgentState:
        """
        验证节点：使用 Pydantic 校验输出
        
        Args:
            state: 当前状态
            
        Returns:
            BaseAgentState: 更新后的状态
        """
        if state["error"]:
            return state
        
        if not state["output"]:
            return {
                **state,
                "error": "No output generated"
            }
        
        try:
            # 使用 Pydantic 校验
            validated = self.validate_output(state["output"])
            return {
                **state,
                "output": validated.model_dump(),
                "error": None
            }
        except ValidationError as e:
            return {
                **state,
                "error": f"Validation error: {e}"
            }
    
    def _retry_node(self, state: BaseAgentState) -> BaseAgentState:
        """
        重试节点：增加重试计数
        
        Args:
            state: 当前状态
            
        Returns:
            BaseAgentState: 更新后的状态
        """
        return {
            **state,
            "retry_count": state["retry_count"] + 1
        }
    
    def _should_retry(self, state: BaseAgentState) -> str:
        """
        判断是否需要重试
        
        Args:
            state: 当前状态
            
        Returns:
            str: "success" | "retry" | "failed"
        """
        if state["error"] is None:
            return "success"
        elif state["retry_count"] < self.MAX_RETRIES:
            return "retry"
        else:
            return "failed"
    
    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        统一 LLM 调用方法（异步）

        使用注入的 LLM Provider 进行调用

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            temperature: 温度参数
            max_tokens: 最大 Token 数

        Returns:
            Dict: {content, input_tokens, output_tokens}

        Raises:
            LLMCallError: 调用失败
        """
        try:
            # 检查 API Key
            if not settings.llm_api_key:
                raise LLMCallError(
                    f"{self._llm_provider.provider_name} API Key 未配置"
                )

            # 使用注入的 Provider 调用 LLM
            return await self._llm_provider.call(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens
            )

        except Exception as e:
            raise LLMCallError(f"LLM 调用失败: {e}")
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """
        解析 LLM 返回的 JSON（工具方法）
        
        剥离 Markdown 代码块，提取纯 JSON
        
        Args:
            response: LLM 响应字符串
            
        Returns:
            Dict: 解析后的 JSON
            
        Raises:
            JSONParseError: 解析失败
        """
        try:
            # 去除 Markdown 代码块标记
            json_str = re.sub(r'^```json\s*', '', response.strip())
            json_str = re.sub(r'^```\s*', '', json_str)
            json_str = re.sub(r'```\s*$', '', json_str)
            json_str = json_str.strip()
            
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise JSONParseError(f"JSON 解析失败: {e}\n响应内容: {response[:500]}")
    
    async def execute(
        self,
        pipeline_id: int,
        stage_name: str,
        initial_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行 Agent

        完整的执行流程：
        1. 初始化状态
        2. 执行 LangGraph 状态机
        3. 记录指标（Token、耗时、推理过程）

        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            initial_state: 初始状态（包含业务相关字段）

        Returns:
            Dict: {success, output, error, retry_count, input_tokens, output_tokens, duration_ms, reasoning}
        """
        retry_count = 0
        total_input_tokens = 0
        total_output_tokens = 0
        reasoning_content = None

        # 记录开始时间
        start_time = time.perf_counter()

        # 使用上下文管理器记录指标
        with agent_metrics_context(self.agent_name, stage_name, pipeline_id) as metrics:
            # 推送开始日志
            await push_log(
                pipeline_id,
                "thought",
                f"[{self.agent_name}] 开始执行...",
                stage=stage_name
            )
            
            # 构建完整初始状态
            full_initial_state: BaseAgentState = {
                "output": None,
                "error": None,
                "retry_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                **initial_state  # 合并业务状态
            }
            
            try:
                # 执行状态机（异步）
                result = await self.graph.ainvoke(full_initial_state)
                
                # 计算耗时
                end_time = time.perf_counter()
                duration_ms = int((end_time - start_time) * 1000)
                
                # 从结果中提取 Token 信息（由 _process_node 添加）
                total_input_tokens = result.get("input_tokens", 0)
                total_output_tokens = result.get("output_tokens", 0)
                
                # 记录指标
                metrics.input_tokens = total_input_tokens
                metrics.output_tokens = total_output_tokens
                metrics.retry_count = result.get("retry_count", 0)
                
                if result.get("error"):
                    # 执行失败
                    error_msg = result["error"]
                    error(
                        f"[{self.agent_name}] 执行失败",
                        pipeline_id=pipeline_id,
                        stage=stage_name,
                        error=error_msg
                    )
                    await push_log(
                        pipeline_id,
                        "error",
                        f"[{self.agent_name}] 执行失败: {error_msg[:200]}",
                        stage=stage_name
                    )
                    
                    return {
                        "success": False,
                        "output": None,
                        "error": error_msg,
                        "retry_count": result.get("retry_count", 0),
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "duration_ms": duration_ms,
                        "reasoning": reasoning_content
                    }
                
                # 执行成功
                await push_log(
                    pipeline_id,
                    "thought",
                    f"[{self.agent_name}] 执行完成，耗时 {duration_ms}ms",
                    stage=stage_name
                )

                # ★ DEBUG: 打印返回的指标
                logger.info(f"[DEBUG] Agent={self.agent_name} returning metrics: input_tokens={total_input_tokens}, output_tokens={total_output_tokens}, duration_ms={duration_ms}")

                return {
                    "success": True,
                    "output": result["output"],
                    "error": None,
                    "retry_count": result.get("retry_count", 0),
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "duration_ms": duration_ms,
                    "reasoning": reasoning_content
                }
                
            except Exception as e:
                # 状态机执行异常
                end_time = time.perf_counter()
                duration_ms = int((end_time - start_time) * 1000)
                error_msg = f"执行异常: {str(e)}"
                
                error(
                    f"[{self.agent_name}] 状态机执行异常",
                    pipeline_id=pipeline_id,
                    stage=stage_name,
                    error=str(e),
                    exc_info=True
                )
                
                # 推送错误日志到前端
                await push_log(
                    pipeline_id,
                    "error",
                    f"[{self.agent_name}] 执行异常: {error_msg[:500]}",
                    stage=stage_name
                )
                
                return {
                    "success": False,
                    "output": None,
                    "error": error_msg,
                    "retry_count": retry_count,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "duration_ms": duration_ms,
                    "reasoning": reasoning_content
                }


# 保留旧的 BaseAgent 以兼容现有代码
class BaseAgent(LangGraphAgent[T]):
    """
    向后兼容的 BaseAgent 别名
    
    新代码应直接使用 LangGraphAgent
    """
    pass


class MockAgent(BaseAgent[BaseModel]):
    """
    模拟 Agent 基类
    
    用于测试，不实际调用 LLM
    """
    
    def __init__(self, agent_name: str, mock_response: Dict[str, Any]):
        super().__init__(agent_name)
        self._mock_response = mock_response
    
    @property
    def system_prompt(self) -> str:
        return "Mock system prompt"
    
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        return "Mock user prompt"
    
    def parse_output(self, response: str) -> Dict[str, Any]:
        return self._mock_response
    
    def validate_output(self, output: Dict[str, Any]) -> BaseModel:
        return BaseModel(**output)
    
    async def _call_llm(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        return json.dumps(self._mock_response)
