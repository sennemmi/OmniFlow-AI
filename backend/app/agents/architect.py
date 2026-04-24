"""
架构师 Agent
唯一能调用 LLM 的地方 - LangGraph 状态机实现

使用 BaseAgent 统一调用逻辑，支持 ModelScope (魔搭) 和 OpenAI 切换
"""

import json
from typing import Dict, List, Optional, TypedDict, Any

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field, ValidationError

from app.agents.base import BaseAgent, LLMCallError, JSONParseError


class ArchitectOutput(BaseModel):
    """架构师输出结构 - Pydantic 校验"""
    feature_description: str = Field(description="功能描述")
    affected_files: List[str] = Field(description="受影响文件列表")
    estimated_effort: str = Field(description="预估工作量")
    technical_design: Optional[str] = Field(default=None, description="技术设计方案")


class ArchitectState(TypedDict):
    """架构师 Agent 状态"""
    requirement: str
    file_tree: Dict[str, Any]
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    retry_count: int


class ArchitectAgent:
    """
    架构师 Agent
    
    基于 LangGraph 的状态机实现，负责：
    1. 分析用户需求
    2. 结合项目上下文（文件树）
    3. 输出结构化设计方案
    
    遵循"八荣八耻"准则
    使用 BaseAgent 统一 LLM 调用逻辑
    """
    
    # 系统 Prompt - 包含八荣八耻准则
    SYSTEM_PROMPT = """你是 OmniFlowAI 的架构师 Agent，负责分析需求并输出技术设计方案。

【八荣八耻准则】
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻  
以状态管理为荣，以随意变更全局为耻
以认真查询为荣，以随意假设为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以单元测试为荣，以手工验证为耻
以监控告警为荣，以故障未知为耻

【任务要求】
1. 仔细阅读用户需求
2. 分析项目文件树结构，理解现有代码组织
3. 输出结构化的 JSON 格式方案，包含：
   - feature_description: 功能描述（简洁明了）
   - affected_files: 受影响文件列表（相对路径）
   - estimated_effort: 预估工作量（如：2小时、1天）
   - technical_design: 技术设计方案（可选，详细描述）

【输出格式】
必须严格输出 JSON 格式，不要包含 Markdown 代码块标记：
{
    "feature_description": "...",
    "affected_files": ["file1.py", "file2.py"],
    "estimated_effort": "...",
    "technical_design": "..."
}

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- 文件路径使用相对路径
- 遵循项目现有的架构分层规范
"""
    
    MAX_RETRIES = 3
    
    def __init__(self):
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态机"""
        
        # 定义状态图
        workflow = StateGraph(ArchitectState)
        
        # 添加节点
        workflow.add_node("analyze", self._analyze_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_node("retry", self._retry_node)
        
        # 添加边
        workflow.set_entry_point("analyze")
        workflow.add_edge("analyze", "validate")
        
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
        workflow.add_edge("retry", "analyze")
        
        return workflow.compile()
    
    def _analyze_node(self, state: ArchitectState) -> ArchitectState:
        """分析节点：调用 LLM 生成方案"""
        
        try:
            # 使用 BaseAgent 的统一调用逻辑
            from app.agents.base import BaseAgent
            
            # 构建用户提示
            user_prompt = self._build_prompt(
                state["requirement"],
                state["file_tree"]
            )
            
            # 调用 LLM
            response = self._call_llm(self.SYSTEM_PROMPT, user_prompt)
            
            # 尝试解析 JSON
            parsed_output = self._parse_json_response(response)
            
            return {
                **state,
                "output": parsed_output,
                "error": None
            }
        except Exception as e:
            return {
                **state,
                "output": None,
                "error": str(e)
            }
    
    def _validate_node(self, state: ArchitectState) -> ArchitectState:
        """验证节点：使用 Pydantic 校验输出"""
        
        if state["error"]:
            return state
        
        if not state["output"]:
            return {
                **state,
                "error": "No output generated"
            }
        
        try:
            # 使用 Pydantic 校验 - 铁律检查
            validated = ArchitectOutput(**state["output"])
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
    
    def _retry_node(self, state: ArchitectState) -> ArchitectState:
        """重试节点：增加重试计数"""
        return {
            **state,
            "retry_count": state["retry_count"] + 1
        }
    
    def _should_retry(self, state: ArchitectState) -> str:
        """判断是否需要重试"""
        if state["error"] is None:
            return "success"
        elif state["retry_count"] < self.MAX_RETRIES:
            return "retry"
        else:
            return "failed"
    
    def _build_prompt(self, requirement: str, file_tree: Dict[str, Any]) -> str:
        """构建 LLM 提示"""
        
        file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
        
        return f"""【用户需求】
{requirement}

【项目文件树】
```
{file_tree_str}
```

请根据以上信息，输出结构化的技术设计方案（JSON 格式）。
"""
    
    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用 LLM - 使用 LiteLLM 统一接口
        
        支持 ModelScope (魔搭) 和 OpenAI 运行时切换
        """
        from app.core.config import settings
        
        # 检查 API Key
        if not settings.llm_api_key:
            provider = "ModelScope" if settings.USE_MODELSCOPE else "OpenAI"
            raise LLMCallError(f"{provider} API Key 未配置")
        
        try:
            if settings.USE_MODELSCOPE:
                # ModelScope 使用 OpenAI 兼容接口
                from openai import OpenAI
                
                client = OpenAI(
                    base_url=settings.llm_api_base,
                    api_key=settings.llm_api_key
                )
                
                response = client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7
                )
                
                if response and response.choices:
                    return response.choices[0].message.content
            else:
                # OpenAI 使用 LiteLLM
                import litellm
                litellm.set_verbose = False
                
                response = litellm.completion(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    api_key=settings.llm_api_key,
                    api_base=settings.llm_api_base,
                    temperature=0.7
                )
                
                if response and response.choices:
                    return response.choices[0].message.content
            
            raise LLMCallError("LLM 返回空响应")
            
        except Exception as e:
            raise LLMCallError(f"LLM 调用失败: {e}")
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """
        解析 LLM 返回的 JSON
        
        剥离 Markdown 代码块，提取纯 JSON
        """
        import re
        
        # 去除 Markdown 代码块标记
        json_str = re.sub(r'^```json\s*', '', response.strip())
        json_str = re.sub(r'^```\s*', '', json_str)
        json_str = re.sub(r'```\s*$', '', json_str)
        json_str = json_str.strip()
        
        return json.loads(json_str)
    
    async def analyze(self, requirement: str, file_tree: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析需求并输出方案
        
        Args:
            requirement: 用户需求描述
            file_tree: 项目文件树字典
            
        Returns:
            Dict: 包含分析结果或错误信息
        """
        initial_state: ArchitectState = {
            "requirement": requirement,
            "file_tree": file_tree,
            "output": None,
            "error": None,
            "retry_count": 0
        }
        
        # 执行状态机
        result = self.graph.invoke(initial_state)
        
        if result["error"]:
            return {
                "success": False,
                "error": result["error"],
                "output": None
            }
        
        return {
            "success": True,
            "error": None,
            "output": result["output"]
        }


# 单例实例
architect_agent = ArchitectAgent()
