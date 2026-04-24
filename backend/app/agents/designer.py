"""
设计师 Agent
唯一能调用 LLM 的地方 - 技术设计实现

使用 OpenAI 兼容接口，支持 ModelScope (魔搭) 和 OpenAI 切换
"""

import json
import re
from typing import Dict, List, Optional, TypedDict, Any

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field, ValidationError

from app.agents.base import LLMCallError


class DesignerState(TypedDict):
    """设计师 Agent 状态"""
    architect_output: Dict[str, Any]
    file_tree: Dict[str, Any]
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    retry_count: int


class DesignerOutput(BaseModel):
    """设计师输出结构 - Pydantic 校验"""
    technical_design: str = Field(description="技术设计方案概述")
    api_endpoints: List[Dict[str, str]] = Field(description="API 端点列表")
    function_changes: List[Dict[str, Any]] = Field(description="函数修改列表")
    logic_flow: str = Field(description="逻辑流图（文本描述）")
    dependencies: List[str] = Field(default_factory=list, description="新增依赖")


class DesignerAgent:
    """
    设计师 Agent
    
    基于 LangGraph 的状态机实现，负责：
    1. 分析 ArchitectAgent 的输出
    2. 结合项目文件树（特别是 backend/app/api/ 风格）
    3. 输出详细的技术设计方案
    
    原则：以创造接口为耻，以复用现有为荣
    使用 OpenAI 兼容接口，支持 ModelScope (魔搭) 和 OpenAI 切换
    """
    
    # 系统 Prompt - 强调复用现有风格
    SYSTEM_PROMPT = """你是 OmniFlowAI 的设计师 Agent，负责根据架构师的分析输出详细的技术设计方案。

【八荣八耻准则】
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻  
以状态管理为荣，以随意变更全局为耻
以认真查询为荣，以随意假设为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以单元测试为荣，以手工验证为耻
以监控告警为荣，以故障未知为耻

【核心原则】
以创造接口为耻，以复用现有为荣！

【任务要求】
1. 仔细阅读 ArchitectAgent 的输出（功能描述、受影响文件列表）
2. 分析项目文件树，特别是 backend/app/api/ 目录下的现有 API 风格
3. 参考现有代码的组织方式和命名规范
4. 输出详细的技术设计方案，包含：
   - technical_design: 技术设计方案概述
   - api_endpoints: API 端点列表（包含 method, path, description）
   - function_changes: 函数修改列表（包含 file, function, action: add/modify/delete, description）
   - logic_flow: 逻辑流图（文本描述形式）
   - dependencies: 新增依赖列表

【输出格式】
必须严格输出 JSON 格式，不要包含 Markdown 代码块标记：
{
    "technical_design": "...",
    "api_endpoints": [
        {"method": "POST", "path": "/api/v1/...", "description": "..."}
    ],
    "function_changes": [
        {"file": "backend/app/...", "function": "...", "action": "add", "description": "..."}
    ],
    "logic_flow": "...",
    "dependencies": ["..."]
}

【风格参考】
- 路由层：backend/app/api/v1/*.py，使用 FastAPI APIRouter
- 业务层：backend/app/service/*.py，实现业务逻辑
- 模型层：backend/app/models/*.py，使用 SQLModel
- 所有 API 返回统一格式：{success, data, error, request_id}

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- 优先复用现有的接口和模式
- 遵循项目现有的架构分层规范
"""
    
    MAX_RETRIES = 3
    
    def __init__(self):
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态机"""
        
        # 定义状态图
        workflow = StateGraph(DesignerState)
        
        # 添加节点
        workflow.add_node("design", self._design_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_node("retry", self._retry_node)
        
        # 添加边
        workflow.set_entry_point("design")
        workflow.add_edge("design", "validate")
        
        # 条件边
        workflow.add_conditional_edges(
            "validate",
            self._should_retry,
            {
                "success": END,
                "retry": "retry",
                "failed": END
            }
        )
        workflow.add_edge("retry", "design")
        
        return workflow.compile()
    
    def _design_node(self, state: DesignerState) -> DesignerState:
        """设计节点：调用 LLM 生成技术方案"""
        
        # 构建用户提示
        user_prompt = self._build_prompt(
            state["architect_output"],
            state["file_tree"]
        )
        
        try:
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
    
    def _validate_node(self, state: DesignerState) -> DesignerState:
        """验证节点：使用 Pydantic 校验输出"""
        
        if state["error"]:
            return state
        
        if not state["output"]:
            return {
                **state,
                "error": "No output generated"
            }
        
        try:
            # 使用 Pydantic 校验
            validated = DesignerOutput(**state["output"])
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
    
    def _retry_node(self, state: DesignerState) -> DesignerState:
        """重试节点：增加重试计数"""
        return {
            **state,
            "retry_count": state["retry_count"] + 1
        }
    
    def _should_retry(self, state: DesignerState) -> str:
        """判断是否需要重试"""
        if state["error"] is None:
            return "success"
        elif state["retry_count"] < self.MAX_RETRIES:
            return "retry"
        else:
            return "failed"
    
    def _build_prompt(self, architect_output: Dict[str, Any], file_tree: Dict[str, Any]) -> str:
        """构建 LLM 提示"""
        
        architect_str = json.dumps(architect_output, indent=2, ensure_ascii=False)
        file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
        
        return f"""【ArchitectAgent 输出】
{architect_str}

【项目文件树】
```
{file_tree_str}
```

请根据以上信息，输出详细的技术设计方案（JSON 格式）。
注意参考 backend/app/api/ 目录下的现有 API 风格，优先复用现有接口和模式。
"""
    
    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用 LLM - 使用 OpenAI 兼容接口
        
        支持 ModelScope (魔搭) 和 OpenAI 运行时切换
        """
        from app.core.config import settings
        from app.core.logging import logger
        
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
                
                logger.info("DesignerAgent 正在请求模型...")
                response = client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    timeout=90
                )
                logger.info("DesignerAgent 模型响应成功")
                
                if response and response.choices:
                    return response.choices[0].message.content
            else:
                # OpenAI 使用 LiteLLM
                import litellm
                litellm.set_verbose = False
                
                logger.info("DesignerAgent 正在请求模型...")
                response = litellm.completion(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    api_key=settings.llm_api_key,
                    api_base=settings.llm_api_base,
                    temperature=0.7,
                    timeout=90
                )
                logger.info("DesignerAgent 模型响应成功")
                
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
        # 去除 Markdown 代码块标记
        json_str = re.sub(r'^```json\s*', '', response.strip())
        json_str = re.sub(r'^```\s*', '', json_str)
        json_str = re.sub(r'```\s*$', '', json_str)
        json_str = json_str.strip()
        
        return json.loads(json_str)
    
    async def design(self, architect_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据架构师输出进行技术设计
        
        Args:
            architect_output: ArchitectAgent 的输出内容
            
        Returns:
            Dict: 包含设计结果或错误信息
        """
        # 获取项目文件树
        from app.service.project import get_current_project_tree, ProjectService
        file_tree_node = get_current_project_tree(max_depth=4)
        file_tree = ProjectService.file_tree_to_dict(file_tree_node) if file_tree_node else {}
        
        initial_state: DesignerState = {
            "architect_output": architect_output,
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
designer_agent = DesignerAgent()
