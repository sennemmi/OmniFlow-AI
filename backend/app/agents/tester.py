"""
测试 Agent
基于 LangGraph 实现，专门负责生成单元测试代码

铁律：
- 以单元测试为荣，以手工验证为耻
- 保持与主代码一致的缩进和注释风格
- 严禁在 agents/ 之外调用 LLM
"""

import json
import logging
import re
from typing import Dict, List, Optional, TypedDict, Any

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field, ValidationError

from app.agents.base import LLMCallError

logger = logging.getLogger(__name__)


class TesterState(TypedDict):
    """测试 Agent 状态"""
    design_output: Dict[str, Any]
    code_output: Dict[str, Any]  # CoderAgent 的输出
    target_files: Dict[str, str]  # 文件路径 -> 当前内容
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    retry_count: int


class TestFile(BaseModel):
    """测试文件"""
    file_path: str = Field(description="测试文件路径，通常以 test_ 开头或放在 tests/ 目录下")
    content: str = Field(description="完整的测试文件内容")
    target_module: str = Field(description="被测试的模块路径")
    test_cases_count: int = Field(default=0, description="测试用例数量")


class TesterOutput(BaseModel):
    """测试 Agent 输出结构 - Pydantic 校验"""
    test_files: List[TestFile] = Field(description="测试文件列表")
    summary: str = Field(description="测试生成摘要")
    coverage_targets: List[str] = Field(default_factory=list, description="计划覆盖的测试目标")
    dependencies_added: List[str] = Field(default_factory=list, description="新增依赖（如 pytest）")


class TestAgent:
    """
    测试 Agent

    基于 LangGraph 的状态机实现，负责：
    1. 分析 DesignerAgent 的技术方案
    2. 分析 CoderAgent 生成的代码
    3. 生成符合项目风格的单元测试代码

    铁律：
    - 以单元测试为荣，以手工验证为耻
    - 保持与主代码一致的缩进和注释风格
    - 测试代码必须可执行且覆盖核心逻辑

    使用 LiteLLM 统一接口，支持 ModelScope (魔搭) 和 OpenAI 切换
    """

    # 系统 Prompt - 强调测试覆盖和代码风格
    SYSTEM_PROMPT = """你是 OmniFlowAI 的测试 Agent，负责根据技术设计方案和生成的代码编写单元测试。

【八荣八耻准则】
以单元测试为荣，以手工验证为耻
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以监控告警为荣，以故障未知为耻

【核心铁律】
以单元测试为荣！

【任务要求】
1. 仔细阅读 DesignerAgent 的技术方案（API 端点、函数变更、逻辑流）
2. 仔细阅读 CoderAgent 生成的代码
3. 生成测试代码时必须遵守：
   - 使用 pytest 框架
   - 保持与主代码相同的缩进风格（空格或Tab数量）
   - 保持与主代码相同的注释风格（井号或三引号）
   - 测试函数名以 test_ 开头
   - 使用 pytest-asyncio 测试异步函数
   - 使用 pytest-mock 进行必要的 mock
   - 覆盖正常路径和异常路径
   - 测试边界条件和错误处理
   - 不要测试与需求无关的代码

【输出格式】
必须严格输出 JSON 格式，不要包含 Markdown 代码块标记：
{
    "test_files": [
        {
            "file_path": "backend/tests/test_example.py",
            "content": "完整的测试文件内容...",
            "target_module": "backend.app.api.v1.example",
            "test_cases_count": 5
        }
    ],
    "summary": "本次生成了 5 个测试用例，覆盖了用户认证功能的正常路径和异常路径",
    "coverage_targets": [
        "用户登录接口 - 正常登录",
        "用户登录接口 - 密码错误",
        "用户登录接口 - 用户不存在"
    ],
    "dependencies_added": ["pytest", "pytest-asyncio", "pytest-mock"]
}

【测试编写原则】
- 每个测试函数只测试一个概念
- 使用 Arrange-Act-Assert 结构
- 使用描述性的测试函数名
- 使用 fixtures 共享测试数据
- 使用 parametrize 测试多组数据
- 测试异步函数时使用 @pytest.mark.asyncio
- 测试数据库操作时使用 mock 或测试数据库

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- 测试文件内容必须是完整的，不是 diff 格式
- 测试代码必须可以直接运行
- 优先使用 pytest 的最佳实践
"""

    MAX_RETRIES = 3

    def __init__(self):
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态机"""

        # 定义状态图
        workflow = StateGraph(TesterState)

        # 添加节点
        workflow.add_node("generate_tests", self._generate_tests_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_node("retry", self._retry_node)

        # 添加边
        workflow.set_entry_point("generate_tests")
        workflow.add_edge("generate_tests", "validate")

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
        workflow.add_edge("retry", "generate_tests")

        return workflow.compile()

    async def _generate_tests_node(self, state: TesterState) -> TesterState:
        """生成测试节点：调用 LLM 生成测试代码（异步）"""

        # 构建用户提示
        user_prompt = self._build_prompt(
            state["design_output"],
            state["code_output"],
            state["target_files"]
        )

        try:
            # 调用 LLM（异步）
            response = await self._call_llm(self.SYSTEM_PROMPT, user_prompt)

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

    def _validate_node(self, state: TesterState) -> TesterState:
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
            validated = TesterOutput(**state["output"])
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

    def _retry_node(self, state: TesterState) -> TesterState:
        """重试节点：增加重试计数"""
        return {
            **state,
            "retry_count": state["retry_count"] + 1
        }

    def _should_retry(self, state: TesterState) -> str:
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
        code_output: Dict[str, Any],
        target_files: Dict[str, str]
    ) -> str:
        """构建 LLM 提示"""

        design_str = json.dumps(design_output, indent=2, ensure_ascii=False)
        code_str = json.dumps(code_output, indent=2, ensure_ascii=False)

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

【CoderAgent 生成的代码】
{code_str}

【目标文件当前内容】
{files_str}

请根据技术设计方案和生成的代码，编写完整的单元测试。
注意：
1. 使用 pytest 框架
2. 保持与主代码相同的缩进风格和注释风格
3. 覆盖正常路径、异常路径和边界条件
4. 测试代码必须可以直接运行
"""

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用 LLM - 使用 OpenAI 兼容接口（异步）

        支持 ModelScope (魔搭) 和 OpenAI 运行时切换
        使用异步接口避免阻塞事件循环
        """
        from app.core.config import settings

        # 检查 API Key
        if not settings.llm_api_key:
            provider = "ModelScope" if settings.USE_MODELSCOPE else "OpenAI"
            raise LLMCallError(f"{provider} API Key 未配置")

        try:
            if settings.USE_MODELSCOPE:
                # ModelScope 使用 OpenAI 兼容接口（异步）
                from openai import AsyncOpenAI

                client = AsyncOpenAI(
                    base_url=settings.llm_api_base,
                    api_key=settings.llm_api_key
                )

                response = await client.chat.completions.create(
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
                # OpenAI 使用 LiteLLM 异步接口
                import litellm
                litellm.set_verbose = False

                response = await litellm.acompletion(
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

    async def generate_tests(
        self,
        design_output: Dict[str, Any],
        code_output: Dict[str, Any],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        根据设计方案和生成的代码生成测试

        Args:
            design_output: DesignerAgent 的输出内容
            code_output: CoderAgent 的输出内容
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 包含生成结果或错误信息
        """
        from app.core.sse_log_buffer import push_log

        code_files_count = len(code_output.get("files", [])) if isinstance(code_output, dict) else 0
        logger.info(f"TesterAgent 开始生成测试", extra={
            "pipeline_id": pipeline_id,
            "code_files_count": code_files_count
        })

        if pipeline_id:
            await push_log(pipeline_id, "info", f"TesterAgent 开始生成测试代码...", stage="CODING")

        initial_state: TesterState = {
            "design_output": design_output,
            "code_output": code_output,
            "target_files": target_files,
            "output": None,
            "error": None,
            "retry_count": 0
        }

        # 执行状态机（使用异步接口）
        result = await self.graph.ainvoke(initial_state)

        if result["error"]:
            logger.error(f"TesterAgent 测试生成失败", extra={
                "pipeline_id": pipeline_id,
                "error": result["error"]
            })
            if pipeline_id:
                await push_log(pipeline_id, "error", f"测试生成失败: {result['error']}", stage="CODING")
            return {
                "success": False,
                "error": result["error"],
                "output": None
            }

        test_files = result["output"].get("test_files", [])
        logger.info(f"TesterAgent 测试生成完成", extra={
            "pipeline_id": pipeline_id,
            "test_files_count": len(test_files)
        })

        if pipeline_id:
            await push_log(pipeline_id, "info", f"测试生成完成，共 {len(test_files)} 个测试文件", stage="CODING")

        return {
            "success": True,
            "error": None,
            "output": result["output"]
        }


# 单例实例
test_agent = TestAgent()
