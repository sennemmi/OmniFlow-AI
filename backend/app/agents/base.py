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
import asyncio
import random
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
    # 是否使用 JSON 格式化输出（结构化输出）
    USE_JSON_FORMAT: bool = False

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

            # 【结构化输出】如果启用 JSON 格式化，添加 response_format 参数
            response_format = {"type": "json_object"} if self.USE_JSON_FORMAT else None
            if response_format:
                logger.info(f"[{self.agent_name}] 使用结构化输出 (JSON)")

            # 调用 LLM（现在返回字典包含 Token 信息）
            response = await self._call_llm(
                self.system_prompt,
                user_prompt,
                response_format=response_format
            )

            # 【DEBUG】记录 LLM 原始返回
            raw_content = response.get("content", "")
            logger.info(f"[{self.agent_name}] LLM 原始返回 (前 500 字符): {raw_content[:500]}")
            logger.info(f"[{self.agent_name}] LLM 原始返回长度: {len(raw_content)}")

            # 尝试解析输出
            parsed_output = self.parse_output(raw_content)

            return {
                **state,
                "output": parsed_output,
                "error": None,
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0)
            }
        except Exception as e:
            logger.error(f"[{self.agent_name}] _process_node 异常: {e}", exc_info=True)
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
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        retry_count: int = 3,
        response_format: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        统一 LLM 调用方法（异步）

        使用注入的 LLM Provider 进行调用，支持指数退避重试

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            temperature: 温度参数
            max_tokens: 最大 Token 数
            retry_count: 重试次数
            response_format: 响应格式，如 {"type": "json_object"}

        Returns:
            Dict: {content, input_tokens, output_tokens}

        Raises:
            LLMCallError: 调用失败（所有重试都失败）
        """
        last_error = None

        for attempt in range(retry_count):
            try:
                # 检查 API Key
                if not settings.llm_api_key:
                    raise LLMCallError(
                        f"{self._llm_provider.provider_name} API Key 未配置"
                    )

                # 使用注入的 Provider 调用 LLM
                result = await self._llm_provider.call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format
                )

                # 成功返回
                if attempt > 0:
                    logger.info(f"[{self.agent_name}] LLM 调用在重试 {attempt} 次后成功")
                return result

            except LLMCallError as e:
                last_error = e
                error_msg = str(e)

                # 判断是否应该重试
                # 某些错误不应该重试（如 API Key 错误）
                if "API Key" in error_msg or "未配置" in error_msg:
                    raise  # 不重试，直接抛出

                # 记录重试日志
                if attempt < retry_count - 1:
                    # 指数退避 + 随机抖动
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"[{self.agent_name}] LLM 调用失败 (尝试 {attempt + 1}/{retry_count}): {error_msg[:100]}，"
                        f"{delay:.1f}s 后重试..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"[{self.agent_name}] LLM 调用失败，已重试 {retry_count} 次")

            except Exception as e:
                last_error = e
                logger.error(f"[{self.agent_name}] LLM 调用异常: {e}")
                if attempt < retry_count - 1:
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)

        # 所有重试都失败
        raise LLMCallError(f"LLM 调用失败（重试 {retry_count} 次）: {last_error}")
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """
        解析 LLM 返回的 JSON（工具方法）

        剥离 Markdown 代码块和前后文本，提取纯 JSON
        强力修复截断的不完整 JSON

        Args:
            response: LLM 响应字符串

        Returns:
            Dict: 解析后的 JSON

        Raises:
            JSONParseError: 解析失败
        """
        # 1. 强力剥离 Markdown 代码块标记
        clean_response = response.strip()

        # 1.1 先尝试提取 ```json 或 ``` 代码块中的内容
        # 匹配 ```json...``` 或 ```...``` 包裹的内容
        code_block_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', clean_response, re.DOTALL)
        if code_block_match:
            clean_response = code_block_match.group(1).strip()
        elif clean_response.startswith("```"):
            # 移除开头的 ```json 或 ```
            clean_response = re.sub(r'^```(?:json)?\s*', '', clean_response)
            # 移除结尾的 ```
            clean_response = re.sub(r'\s*```$', '', clean_response)

        clean_response = clean_response.strip()

        # 2. 尝试直接解析
        try:
            return json.loads(clean_response)
        except json.JSONDecodeError:
            pass  # 继续尝试修复

        # 3. 如果解析失败，尝试修复常见的截断问题
        # 统计大括号和中括号
        brace_count = clean_response.count('{') - clean_response.count('}')
        bracket_count = clean_response.count('[') - clean_response.count(']')

        fixed_response = clean_response

        # 如果还在字符串里（引号不匹配），先补个引号
        if fixed_response.count('"') % 2 != 0:
            fixed_response += '"'

        # 补全缺少的闭合符号
        fixed_response += '}' * brace_count
        fixed_response += ']' * bracket_count

        try:
            return json.loads(fixed_response)
        except json.JSONDecodeError:
            pass  # 继续尝试更激进的修复

        # 4. 【增强】尝试使用 _try_fix_truncated_json 进行深度修复
        logger.warning(f"[{self.agent_name}] JSON 解析失败，尝试深度修复截断的 JSON")
        fixed_json = self._try_fix_truncated_json(clean_response)
        if fixed_json:
            try:
                result = json.loads(fixed_json)
                logger.info(f"[{self.agent_name}] 成功修复截断的 JSON")
                return result
            except json.JSONDecodeError:
                pass  # 修复失败，继续抛出原始错误

        # 5. 如果还不行，报错原始信息
        raise JSONParseError(f"JSON 解析完全失败，内容截断严重。原始开头: {clean_response[:200]}")
    
    def _try_fix_truncated_json(self, json_str: str) -> Optional[str]:
        """
        尝试修复截断的不完整 JSON

        策略：
        1. 如果 JSON 以 { 开头但不以 } 结尾，尝试添加缺少的闭合符号
        2. 如果字符串在引号内被截断，尝试关闭引号并补全字段
        3. 如果字段不完整，尝试补全缺失的字段

        Args:
            json_str: 可能截断的 JSON 字符串

        Returns:
            Optional[str]: 修复后的 JSON 字符串，或 None 如果无法修复
        """
        if not json_str or not json_str.strip():
            return None

        fixed = json_str.strip()

        # 【增强】检查关键字段是否缺失，如果缺失则补全
        required_fields = ['"feature_description"', '"affected_files"', '"estimated_effort"',
                          '"technical_design"', '"acceptance_criteria"', '"required_symbols"']

        # 找到最后一个完整的字段
        last_complete_field_end = 0
        for field in required_fields:
            pos = fixed.rfind(field)
            if pos > last_complete_field_end:
                last_complete_field_end = pos

        # 如果在某个字段值内部被截断，截断到该字段的开始，并补全默认值
        if last_complete_field_end > 0:
            # 找到该字段的开始位置
            field_start = last_complete_field_end
            # 检查该字段是否完整（后面有逗号或右括号）
            rest = fixed[field_start:]

            # 如果看起来在字段值内部（有冒号但后面没有逗号或}）
            if ':' in rest and not (rest.rstrip().endswith(',') or rest.rstrip().endswith(']') or rest.rstrip().endswith('}')):
                # 截断到该字段之前
                fixed = fixed[:field_start].rstrip()
                # 如果最后一个字符是逗号，移除它
                if fixed.endswith(','):
                    fixed = fixed[:-1]

        # 统计各种符号的数量
        open_braces = fixed.count('{') - fixed.count('}')
        open_brackets = fixed.count('[') - fixed.count(']')

        # 检查是否在字符串内被截断（奇数个未闭合的引号）
        quote_count = 0
        i = 0
        while i < len(fixed):
            if fixed[i] == '"' and (i == 0 or fixed[i-1] != '\\'):
                quote_count += 1
            i += 1

        # 如果在字符串内被截断，先关闭字符串
        if quote_count % 2 == 1:
            last_quote = fixed.rfind('"')
            if last_quote > 0:
                after_quote = fixed[last_quote:].strip()
                if ':' in after_quote[:10]:
                    fixed = fixed + '": ""'
                else:
                    fixed = fixed + '"'

        # 【增强】补全缺失的必填字段
        if '"acceptance_criteria"' not in fixed:
            fixed = fixed.rstrip() + ',\n  "acceptance_criteria": []'
        if '"required_symbols"' not in fixed:
            fixed = fixed.rstrip() + ',\n  "required_symbols": []'

        # 补全闭合的大括号和方括号
        fixed = fixed + '}' * open_braces
        fixed = fixed + ']' * open_brackets

        # 检查是否修复成功
        if fixed.count('{') == fixed.count('}') and fixed.count('[') == fixed.count(']'):
            return fixed

        return None
    
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
                
                # 【关键修复】从结果中提取工具调用计数和工具结果
                tool_calls = result.get("tool_calls", 0)
                tool_results = result.get("tool_results", [])
                
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
                        "tool_calls": tool_calls,
                        "tool_results": tool_results,
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
                logger.info(f"[DEBUG] Agent={self.agent_name} returning metrics: input_tokens={total_input_tokens}, output_tokens={total_output_tokens}, duration_ms={duration_ms}, tool_calls={tool_calls}")

                return {
                    "success": True,
                    "output": result["output"],
                    "error": None,
                    "retry_count": result.get("retry_count", 0),
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "duration_ms": duration_ms,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
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
                    "tool_calls": result.get("tool_calls", 0) if result else 0,
                    "tool_results": result.get("tool_results", []) if result else [],
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
