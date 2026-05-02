"""
架构师 Agent
基于 ToolUsingAgent 实现，支持工具调用（ReAct 模式）

职责：
1. 分析用户需求
2. 使用工具主动探索项目（glob/grep/read_file）
3. 输出结构化设计方案

【改造】从 LangGraphAgent 迁移到 ToolUsingAgent
- 支持工具调用循环
- 只读工具集（glob, grep, read_file）
- 自主探索项目代码
"""

import json
import logging
from typing import Dict, List, Optional, Any

from app.agents.tool_agent import ToolUsingAgent
from app.agents.schemas import ArchitectOutput

logger = logging.getLogger(__name__)


class ArchitectAgent(ToolUsingAgent[ArchitectOutput]):
    """
    架构师 Agent

    分析需求并输出技术设计方案
    继承 ToolUsingAgent，支持工具调用（只读工具集）
    """

    # 最大工具调用次数（防止过度探索）
    MAX_TOOL_CALLS = 5

    def __init__(self):
        super().__init__(agent_name="ArchitectAgent")

    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
        """
        只暴露只读工具给 ArchitectAgent

        ArchitectAgent 只能读取文件，不能修改：
        - glob: 查找文件
        - grep: 搜索内容
        - read_file: 读取文件内容
        """
        if self._agent_tools is None:
            return []

        # 获取所有工具定义，只保留前3个（glob, grep, read_file）
        all_tools = self._agent_tools.tool_definitions
        read_only_tools = all_tools[:3] if len(all_tools) >= 3 else all_tools

        logger.info(f"[ArchitectAgent] 加载只读工具: {[t['function']['name'] for t in read_only_tools]}")
        return read_only_tools

    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 包含八荣八耻准则和工具使用引导"""
        return """你是 OmniFlowAI 的架构师 Agent，负责分析需求并输出技术设计方案。

【八荣八耻准则】
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻
以状态管理为荣，以随意变更全局为耻
以认真查询为荣，以随意假设为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以单元测试为荣，以手工验证为耻
以监控告警为荣，以故障未知为耻

【工具使用 - 探索项目】
你可以使用以下工具主动探索项目代码：

1. **glob** - 查找文件：
   - 用途：发现项目中的文件
   - 示例：`glob("app/api/v1/*.py")` 查找所有 API 文件
   - 示例：`glob("app/service/*.py")` 查找服务层文件

2. **grep** - 搜索内容：
   - 用途：在文件中搜索特定模式
   - 示例：`grep("def authenticate", "app/service")` 查找认证函数
   - 示例：`grep("class User", "app/models")` 查找 User 模型

3. **read_file** - 读取文件：
   - 用途：获取文件内容，理解代码实现
   - 示例：`read_file("app/api/v1/auth.py", 1, 50)` 读取前50行

【探索指南】
- 在分析需求前，先使用工具了解相关代码
- 只阅读与需求直接相关的文件，避免过度探索
- 通过文件树和 glob 快速定位关键模块
- 使用 grep 查找函数定义和调用关系
- 使用 read_file 深入理解关键代码

【输出格式 - 极其重要】
探索完成后，你必须直接输出纯 JSON 格式，不要包含任何其他文本、解释或标记。
输出必须是一个有效的 JSON 对象。

正确示例（直接输出 JSON）：
{"feature_description": "实现用户登录功能", "affected_files": ["backend/app/api/v1/auth.py", "backend/app/service/auth_service.py"], "estimated_effort": "2小时", "technical_design": "使用JWT进行身份验证"}

错误示例（不要这样输出）：
- 不要添加 ```json 标记
- 不要添加解释文本
- 不要使用工具调用格式如 [TOOL_CALL]
- 不要输出 "我需要先分析..." 等思考过程
- 只输出纯 JSON

【强制要求】
- 直接输出 JSON，不要有任何前缀或后缀
- 确保 JSON 格式完整有效
- 不要输出任何其他内容

【字段说明】
- feature_description: 功能描述（简洁明了）
- affected_files: 受影响文件列表（相对路径）
- estimated_effort: 预估工作量（如：2小时、1天）
- technical_design: 技术设计方案（可选，详细描述）

【注意事项】
- 文件路径使用相对路径
- 遵循项目现有的架构分层规范
- 基于实际读取的代码进行分析，不要假设
"""

    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt

        Args:
            state: 包含 requirement, file_tree, element_context, project_path 的状态
        """
        requirement = state.get("requirement", "")
        file_tree = state.get("file_tree", {})
        element_context = state.get("element_context")
        project_path = state.get("project_path", "/workspace/backend")

        file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)

        # 构建 element_context 部分（简化版，不再包含 code_context）
        element_context_str = ""
        if element_context:
            element_context_str = f"""
【页面元素上下文】
- HTML: {element_context.get('html', 'N/A')}
- XPath: {element_context.get('xpath', 'N/A')}
- 数据源: {element_context.get('data_source', 'N/A')}

请根据以上元素上下文进行精准分析。
"""

        return f"""【用户需求】
{requirement}

【项目路径】
{project_path}

【项目文件树】
```
{file_tree_str}
```
{element_context_str}

【任务】
1. 使用工具探索项目代码（glob/grep/read_file）
2. 理解现有架构和代码风格
3. 分析需求并输出技术设计方案（JSON 格式）

请开始探索项目，然后输出结构化的技术设计方案。
"""

    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出为字典"""
        return self._parse_json_response(response)

    def validate_output(self, output: Dict[str, Any]) -> ArchitectOutput:
        """校验输出为 ArchitectOutput 模型"""
        return ArchitectOutput(**output)

    async def analyze(
        self,
        requirement: str,
        file_tree: Dict[str, Any],
        element_context: Optional[Dict[str, Any]] = None,
        pipeline_id: int = 0,
        project_path: str = "/workspace/backend"
    ) -> Dict[str, Any]:
        """
        分析需求并输出方案

        【改造】使用 ToolUsingAgent 的 execute 方法，支持工具调用

        Args:
            requirement: 用户需求描述
            file_tree: 项目文件树字典
            element_context: 页面元素上下文（可选）
            pipeline_id: Pipeline ID
            project_path: 项目路径（用于工具执行）

        Returns:
            Dict: 包含分析结果或错误信息
        """
        initial_state = {
            "requirement": requirement,
            "file_tree": file_tree,
            "element_context": element_context,
            "project_path": project_path
        }

        result = await self.execute(
            pipeline_id=pipeline_id,
            stage_name="ARCHITECT",
            initial_state=initial_state
        )

        return result


# 单例实例
architect_agent = ArchitectAgent()
