"""
编码 Agent
唯一能调用 LLM 的地方 - 代码生成实现

铁律：System Prompt 强调"以破坏架构为耻"
Agent 必须保持原有的缩进、注释风格和分层逻辑

使用 LiteLLM 统一接口，支持 ModelScope (魔搭) 和 OpenAI 切换
"""

import json
import re
from typing import Dict, List, Optional, TypedDict, Any

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field, ValidationError

from app.agents.base import LLMCallError


class CoderState(TypedDict):
    """编码 Agent 状态"""
    design_output: Dict[str, Any]
    target_files: Dict[str, str]  # 文件路径 -> 当前内容
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    retry_count: int


class FileChange(BaseModel):
    """文件变更"""
    file_path: str = Field(description="文件相对路径")
    content: str = Field(description="完整的文件内容")
    change_type: str = Field(default="modify", description="变更类型: add/modify/delete")
    description: str = Field(default="", description="变更说明")


class CoderOutput(BaseModel):
    """编码 Agent 输出结构 - Pydantic 校验"""
    files: List[FileChange] = Field(description="变更的文件列表")
    summary: str = Field(description="变更摘要")
    dependencies_added: List[str] = Field(default_factory=list, description="新增依赖")
    tests_included: bool = Field(default=False, description="是否包含测试代码")


class CoderAgent:
    """
    编码 Agent

    基于 LangGraph 的状态机实现，负责：
    1. 分析 DesignerAgent 的技术方案
    2. 读取目标文件当前内容
    3. 生成符合项目风格的代码

    铁律：
    - 以破坏架构为耻
    - 保持原有缩进和注释风格
    - 保持分层逻辑
    - 优先复用现有代码模式

    使用 LiteLLM 统一接口，支持 ModelScope (魔搭) 和 OpenAI 切换
    """

    # 系统 Prompt - 强调保持架构和风格
    SYSTEM_PROMPT = """你是 OmniFlowAI 的编码 Agent，负责根据技术设计方案生成代码。

【八荣八耻准则】
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻
以状态管理为荣，以随意变更全局为耻
以认真查询为荣，以随意假设为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以单元测试为荣，以手工验证为耻
以监控告警为荣，以故障未知为耻

【核心铁律】
以破坏架构为耻！

【任务要求】
1. 仔细阅读 DesignerAgent 的技术方案（API 端点、函数变更、逻辑流）
2. 分析目标文件的当前内容和代码风格
3. 生成代码时必须遵守：
   - 保持原有的缩进风格（空格/Tab 数量）
   - 保持原有的注释风格（# 或 \"\"\"）
   - 保持架构分层（api/service/model 分离）
   - 复用现有的工具函数和模式
   - 遵循项目的命名规范
   - 不要修改与需求无关的代码

【输出格式】
必须严格输出 JSON 格式，不要包含 Markdown 代码块标记：
{
    "files": [
        {
            "file_path": "backend/app/api/v1/example.py",
            "content": "完整的文件内容...",
            "change_type": "add",
            "description": "新增示例 API"
        }
    ],
    "summary": "本次变更添加了用户认证功能，包含登录和注册接口",
    "dependencies_added": [],
    "tests_included": false
}

【风格保持原则】
- 如果原文件使用 4 空格缩进，新代码也必须使用 4 空格
- 如果原文件使用双引号字符串，新代码也使用双引号
- 如果原文件有特定的导入排序风格，保持相同风格
- 如果原文件使用特定的错误处理方式，保持相同方式
- 遵循 FastAPI 和 SQLModel 的最佳实践

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- 文件内容必须是完整的，不是 diff 格式
- 优先复用现有的接口和模式
- 保持代码的可读性和可维护性
"""

    MAX_RETRIES = 3

    def __init__(self):
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态机"""

        # 定义状态图
        workflow = StateGraph(CoderState)

        # 添加节点
        workflow.add_node("code", self._code_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_node("retry", self._retry_node)

        # 添加边
        workflow.set_entry_point("code")
        workflow.add_edge("code", "validate")

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
        workflow.add_edge("retry", "code")

        return workflow.compile()

    def _code_node(self, state: CoderState) -> CoderState:
        """编码节点：调用 LLM 生成代码"""

        # 构建用户提示
        user_prompt = self._build_prompt(
            state["design_output"],
            state["target_files"]
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

    def _validate_node(self, state: CoderState) -> CoderState:
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
            validated = CoderOutput(**state["output"])
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

    def _retry_node(self, state: CoderState) -> CoderState:
        """重试节点：增加重试计数"""
        return {
            **state,
            "retry_count": state["retry_count"] + 1
        }

    def _should_retry(self, state: CoderState) -> str:
        """判断是否需要重试"""
        if state["error"] is None:
            return "success"
        elif state["retry_count"] < self.MAX_RETRIES:
            return "retry"
        else:
            return "failed"

    def _build_prompt(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str]
    ) -> str:
        """构建 LLM 提示"""

        design_str = json.dumps(design_output, indent=2, ensure_ascii=False)

        # 构建文件内容部分
        files_content = []
        for file_path, content in target_files.items():
            files_content.append(f"""【文件: {file_path}】
```python
{content}
```""")

        files_str = "\n\n".join(files_content)

        return f"""【技术设计方案】
{design_str}

【目标文件当前内容】
{files_str}

请根据技术设计方案，生成需要修改或新增的代码。
注意保持原有代码的缩进风格、注释风格和架构分层。
输出完整的文件内容（不是 diff 格式）。
"""

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用 LLM - 使用 OpenAI 兼容接口

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
        # 去除 Markdown 代码块标记
        json_str = re.sub(r'^```json\s*', '', response.strip())
        json_str = re.sub(r'^```\s*', '', json_str)
        json_str = re.sub(r'```\s*$', '', json_str)
        json_str = json_str.strip()

        return json.loads(json_str)

    async def generate_code(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        根据设计方案生成代码

        Args:
            design_output: DesignerAgent 的输出内容
            target_files: 目标文件路径到内容的映射

        Returns:
            Dict: 包含生成结果或错误信息
        """
        initial_state: CoderState = {
            "design_output": design_output,
            "target_files": target_files,
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
coder_agent = CoderAgent()
