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
import time
from typing import Dict, List, Optional, Any

from app.agents.tool_agent import ToolUsingAgent
from app.agents.schemas import ArchitectOutput
from app.agents.token_budget_allocator import TokenBudgetAllocator
from app.core.config import settings
from app.utils.path_utils import normalize_relative_path
from app.utils.prompt_builder import get_common_prompt

logger = logging.getLogger(__name__)


class ArchitectAgent(ToolUsingAgent[ArchitectOutput]):
    """
    架构师 Agent

    分析需求并输出技术设计方案
    继承 ToolUsingAgent，支持工具调用（只读工具集）
    """

    # 最大工具调用次数（防止过度探索）
    # 【强制】必须使用工具探索，最多 10 次
    MAX_TOOL_CALLS = 10

    # Architect 专用 JSON 截断修复字段
    _truncated_json_fields: List[str] = [
        '"feature_description"', '"affected_files"', '"estimated_effort"',
        '"technical_design"', '"acceptance_criteria"', '"required_symbols"'
    ]
    _truncated_json_defaults: Dict[str, Any] = {
        "acceptance_criteria": [],
        "required_symbols": []
    }

    def __init__(self):
        super().__init__(agent_name="ArchitectAgent")

    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
        """
        ArchitectAgent 工具定义 - 三件套工具

        支持：
        - glob: 按模式查找文件
        - grep_ast: 结构化代码搜索（函数/类/调用者/导入）
        - read_chunk: 按 AST 边界精准读取代码
        - semantic_search: 自然语言语义检索
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "glob",
                    "description": "按 glob 模式查找文件。用于确认文件路径是否存在。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Glob 模式，如 'app/api/v1/*.py' 或 '**/health.py'",
                            },
                            "max_results": {
                                "type": "integer",
                                "default": 20,
                                "description": "最大返回结果数",
                            },
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "grep_ast",
                    "description": (
                        "结构化代码搜索（比 grep 更智能）。"
                        "支持 search_type: 'text'（普通搜索）/ 'function'（找函数定义）/ "
                        "'class'（找类定义）/ 'callers'（找调用某函数的位置）/ 'import'（找导入某模块的文件）。"
                        "优先用此工具替代 grep，返回结果包含精确行号和上下文。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "搜索词（函数名、类名、模块名、或文本片段）",
                            },
                            "search_path": {
                                "type": "string",
                                "description": "搜索范围，默认为项目根目录",
                                "default": ".",
                            },
                            "search_type": {
                                "type": "string",
                                "enum": ["text", "function", "class", "callers", "import"],
                                "default": "text",
                                "description": "搜索类型",
                            },
                            "max_results": {
                                "type": "integer",
                                "default": 15,
                            },
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_chunk",
                    "description": (
                        "按 AST 边界读取代码，杜绝硬截断。"
                        "三种模式：\n"
                        " 1. 传 symbol_name → 精准读取该函数/类的完整定义\n"
                        " 2. 传 start_line + end_line → 按行号读取（自动扩展到 AST 边界）\n"
                        " 3. 都不传 → 返回文件摘要（imports + 顶层符号签名）\n"
                        "推荐顺序：先用 grep_ast 定位，再用 read_chunk 按 symbol_name 读取完整实现。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "相对路径，如 'app/api/v1/health.py'",
                            },
                            "symbol_name": {
                                "type": "string",
                                "description": "函数名或类名（最推荐）",
                            },
                            "start_line": {
                                "type": "integer",
                                "description": "起始行号（1-based）",
                            },
                            "end_line": {
                                "type": "integer",
                                "description": "结束行号（1-based）",
                            },
                        },
                        "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "semantic_search",
                    "description": (
                        "语义检索：用自然语言描述意图，找到最相关的代码块。"
                        "不需要猜正则或函数名，直接描述功能，如：\n"
                        " '处理用户密码验证的函数'\n"
                        " '数据库连接初始化'\n"
                        " 'FastAPI 健康检查路由'\n"
                        "返回最相关的代码块列表（含文件路径和行号）。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "自然语言查询",
                            },
                            "top_k": {
                                "type": "integer",
                                "default": 5,
                                "description": "返回最相关的 k 个结果",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
        ]

    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 包含八荣八耻准则和工具使用引导"""
        return f"""你是 OmniFlowAI 的架构师 Agent，负责分析需求并输出技术设计方案。

【八荣八耻准则】
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻
以状态管理为荣，以随意变更全局为耻
以认真查询为荣，以随意假设为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以单元测试为荣，以手工验证为耻
以监控告警为荣，以故障未知为耻

{get_common_prompt()}

【现有代码 - 必须严格遵守的权威事实】
下面的【相关代码上下文】部分已经包含了与需求相关的关键文件内容。
这些是现有项目的真实代码，是你设计的基础，**必须严格遵守**。

【设计原则】
1. **复用优先**：如果现有代码中已有类似功能，优先复用或扩展，不要重复造轮子
2. **签名一致**：required_symbols 中的函数签名必须与现有代码保持一致
3. **键名对齐**：返回字典的键名必须与现有代码返回的结构一致

【⚠️ 强制要求：必须使用工具探索】
**绝对禁止**在没有调用任何工具的情况下直接输出结果！

你必须使用以下工具主动探索项目代码：
1. **glob**: 查找文件路径（如 `glob("app/api/v1/*.py")`）
2. **grep_ast**: 搜索代码符号（如 `grep_ast("check_database", search_type="function")`）
3. **read_chunk**: 读取文件内容（如 `read_chunk("app/api/v1/health.py")`）
4. **semantic_search**: 语义检索（如 `semantic_search("处理用户登录的函数")`）

【工具调用硬性限制 - 违反将导致重试】
- **最多只能调用 10 次工具**，超过将强制终止
- **最少必须调用 1 次工具**，否则输出将被拒绝并要求重试
- 每次调用前思考是否必要，禁止无意义的工具调用
- 优先使用 grep_ast 快速定位，避免不必要的 read_chunk

【工具调用止损规则 - 极其重要】
1. grep 返回 0 matches 时，**绝对不要**连续尝试不同的模式！
2. 如果 2 次 grep 都返回空结果，立即改用 read_chunk 查看文件的实际内容。
3. 如果 read_chunk 也看不到预期内容（如文件已被修改），立即停止探索，在输出中用一个特殊的验收标准标记"需要人工确认文件内容"。
4. 你的目标是尽快输出结论，不是穷尽所有可能性。一旦获得了足够的信息（例如找到了需要修改的关键文件），立即输出 JSON，不再调用工具。
5. 前 5 次工具调用如果还没得到足够信息，也必须输出一个带有"需要人工补充"标记的结论，避免耗尽配额。

【探索指南】
- 在分析需求前，先使用工具了解相关代码
- **只阅读与需求直接相关的文件**，避免过度探索
- 通过文件树和 glob 快速定位关键模块
- 使用 grep 查找函数定义和调用关系
- 使用 read_file 分段读取关键代码（每次最多80行）
- **控制探索范围**，2-3 个关键文件足够，不要贪多

【输出格式】
探索完成后，输出 JSON 格式包含以下字段：
- feature_description: 功能描述（简洁明了）
- affected_files: 受影响文件列表（相对路径）
- estimated_effort: 预估工作量（如：2小时、1天）
- technical_design: 技术设计方案（可选，详细描述）
- acceptance_criteria: 可验证的验收标准列表（3-5条，每条包含具体行为或接口签名）
- required_symbols: **必需实现的符号清单**（极其重要，DesignerAgent 必须严格遵守）

【验收标准要求】
请输出 3-5 条可验证的验收标准，每条应包含具体行为或接口签名，例如：
- "函数 check_database_status 必须返回 status 字段和 response_time_ms 字段"

【字段说明】
- feature_description: 功能描述（简洁明了）
- affected_files: 受影响文件列表（相对路径）
- estimated_effort: 预估工作量（如：2小时、1天）
- technical_design: 技术设计方案（可选，详细描述）
- acceptance_criteria: 可验证的验收标准列表（3-5条，每条包含具体行为或接口签名）
- required_symbols: **必需实现的符号清单**（极其重要，DesignerAgent 必须严格遵守）

【验收标准要求】
请输出 3-5 条可验证的验收标准，每条应包含具体行为或接口签名，例如：
- "函数 check_database_status 必须返回 status 字段和 response_time_ms 字段"
- "API 端点 POST /api/v1/users 必须返回 201 状态码和创建的用户对象"
- "类 UserService 必须实现 async def get_by_id 方法"

【必需符号清单要求 - 强制 DesignerAgent 遵守】
除了验收标准，你还必须明确列出 **required_symbols**，要求 DesignerAgent 在 interface_specs 中实现这些符号。

每个 required_symbol 必须包含：
- name: 符号名称（如 "check_database_status"）
- type: 类型（function/class/endpoint）
- module: 所在模块（如 "app/service/health_service.py"）
- signature: 函数签名（可选，如 "async def check_database_status() -> dict"）
- description: 简短描述（可选）
- **return_fields: 【契约强制执行】返回值字段规范列表（极其重要！）**

**【P0】return_fields 强制要求**：
对于返回 dict 的函数，你必须明确列出所有返回字段的名称、类型和描述。这是机器可强制执行的契约，CoderAgent 将据此校验实现。

示例1 - 健康检查服务：
```json
{{
  "required_symbols": [
    {{
      "name": "check_database_status",
      "type": "function",
      "module": "app/service/health_service.py",
      "signature": "async def check_database_status() -> dict",
      "return_fields": [
        {{"name": "status", "type": "str", "description": "数据库状态: up/down"}},
        {{"name": "response_time_ms", "type": "float", "description": "响应时间(毫秒)"}}
      ]
    }}
  ]
}}
```

示例2 - 用户服务：
```json
{{
  "required_symbols": [
    {{
      "name": "get_user_profile",
      "type": "function",
      "module": "app/service/user_service.py",
      "signature": "async def get_user_profile(user_id: int) -> dict",
      "return_fields": [
        {{"name": "id", "type": "int", "description": "用户ID"}},
        {{"name": "username", "type": "str", "description": "用户名"}},
        {{"name": "email", "type": "str", "description": "邮箱地址"}}
      ]
    }},
    {{
      "name": "UserService",
      "type": "class",
      "module": "app/service/user_service.py",
      "signature": "class UserService",
      "return_fields": []
    }}
  ]
}}
```

示例3 - 时间戳服务：
```json
{{
  "required_symbols": [
    {{
      "name": "get_current_timestamp",
      "type": "function",
      "module": "app/service/timestamp_service.py",
      "signature": "def get_current_timestamp() -> dict",
      "return_fields": [
        {{"name": "timestamp", "type": "float", "description": "Unix时间戳"}},
        {{"name": "iso_format", "type": "str", "description": "ISO格式时间"}}
      ]
    }},
    {{
      "name": "timestamp_router",
      "type": "variable",
      "module": "app/api/v1/timestamp.py",
      "signature": "timestamp_router = APIRouter()",
      "return_fields": []
    }}
  ]
}}
```

**重要规则**：
1. required_symbols 中的每个符号都必须在 affected_files 中对应的文件里实现
2. 验收标准中提到的函数/类，必须在 required_symbols 中列出
3. **如果函数返回 dict，return_fields 必须非空，列出所有字段**
4. DesignerAgent 会严格对照此清单生成 interface_specs，遗漏任何符号或字段都会导致重试
5. 【绝对禁止】如果某个功能由类的方法实现（例如 HealthService 类的 get_component_health 方法），你只能将【类名】（HealthService）放入 required_symbols，严禁将类方法名作为独立的符号放入清单！

【注意事项】
- 文件路径使用相对路径
- 遵循项目现有的架构分层规范
- 基于实际读取的代码进行分析，不要假设

【极其重要：防止偷懒规则】
即便功能已经存在，也请将相关的核心文件放入 affected_files 列表中，以便进行代码质量检查和契约验证。
不要以"功能已存在"为由返回空的 affected_files！

【硬性规则 - 违反将导致输出被拒绝】
在输出最终 JSON 之前，你必须至少使用一次 read_file 尝试读取 affected_files 中列出的每一个文件。

【⚠️ 新文件处理规则 - 极其重要】
当 read_file 返回 `{{"exists": false}}` 时，表示该文件不存在（需要新建）。此时：
1. **不要惊慌**：文件不存在是正常情况，表示需要创建新文件
2. **继续设计**：在 required_symbols 中指定需要在该新文件中实现的符号
3. **明确标注**：在 technical_design 中说明"该文件需要新建"
4. **参考现有代码**：查看项目中类似的文件结构，确保新文件符合项目规范

示例：
- read_file 返回 `{{"exists": false, "error": "File not found"}}` → 文件不存在，需要新建
- 你应该在 affected_files 中保留该文件路径，并在 required_symbols 中定义需要实现的符号

读取检查清单（输出前必须完成）：
□ 是否使用 read_file 尝试读取了所有 affected_files 中的文件？
□ 对于不存在的文件，是否在 technical_design 中标注"需要新建"？
□ 是否使用 grep_ast 搜索了关键函数/类的定义？
□ 是否理解了现有代码的函数签名、返回结构、字典键名？
□ 输出的 required_symbols 是否与读取的代码一致（对于已存在的文件）？

警告：如果你输出的 required_symbols 与现有代码冲突（如要求实现已存在的函数但签名不同），
或要求返回与现有代码不一致的字典键名，你的设计将被拒绝！
"""

    # 项目契约卡 Prompt 模板
    ARCHITECT_PROJECT_CARD_PROMPT_SECTION = """
【项目契约卡 - 重要，请仔细阅读】

这是项目的结构化名片，包含以下信息：

1. directory_structure：目录结构（3层深度）
   - 用于确认文件是否存在，确定 affected_files 的正确路径

2. tech_stack：技术栈约束
   - frameworks：已使用的框架，你的设计必须与此兼容
   - databases：已使用的数据库/ORM，不要引入新的冲突依赖

3. entry_points：关键入口文件（⚠️ 高风险）
   - 标注了修改风险，如果你需要改这些文件，请在 technical_design 中说明原因

4. module_imports：模块间依赖关系
   - 格式：{{"dependent_file": ["files_that_depend_on_it", ...]}}
   - 用途：判断改动的波及范围，如果修改 service 层，检查哪些 api 文件会受影响

5. symbol_index：文件级符号索引
   - 包含函数签名和类的公开方法
   - 用于确认 required_symbols 中的符号是否已存在（复用优先）

```json
{project_card}
```
"""

    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt（快速索引模式）

        Args:
            state: 包含 requirement, element_context, project_path 的状态
        """
        requirement = state.get("requirement", "")
        element_context = state.get("element_context")
        project_path = state.get("project_path", "/workspace/backend")

        # 【快速索引模式】使用项目契约卡替代原来的 project_summary
        project_card_json = "{}"
        project_card_dict: Dict[str, Any] = {}
        if self._agent_tools:
            try:
                project_card_json = self._agent_tools.generate_project_card()
                project_card_dict = json.loads(project_card_json)
            except Exception as e:
                logger.warning(f"[ArchitectAgent] 生成项目契约卡失败: {e}")
                project_card_json = json.dumps({"error": str(e)})

        # 【强制注入方案】获取预加载的文件内容
        preloaded_files = state.get("preloaded_files", {})
        
        # 【新增】Token 预算控制：压缩代码上下文
        # 从 _file_cache 中获取已读取的文件内容（来自之前工具调用的缓存）
        injected_files: Dict[str, str] = {}
        if self._agent_tools:
            for path, cache in self._agent_tools._file_cache.items():
                if cache.get("content"):
                    injected_files[path] = cache["content"]
        
        # 【强制注入方案】合并预加载的文件（优先级更高）
        injected_files.update(preloaded_files)

        affected_files = state.get("affected_files", [])

        # 【强制注入方案】直接显示预加载的文件内容，不进行压缩
        if preloaded_files:
            preloaded_section = "【预加载的现有代码 - 必须基于这些代码设计】\n\n"
            for file_path, content in preloaded_files.items():
                # 截断过长的文件内容
                display_content = content[:8000] + "\n... (内容已截断)" if len(content) > 8000 else content
                preloaded_section += f"=== 文件: {file_path} ===\n```python\n{display_content}\n```\n\n"
            code_context_section = preloaded_section
        elif injected_files or affected_files:
            # 如果没有预加载文件，使用 TokenBudgetAllocator 压缩
            allocator = TokenBudgetAllocator(
                max_budget_tokens=8000,
                model_name=settings.llm_model,
            )
            compressed_context = allocator.allocate(
                project_card=project_card_dict,
                injected_files=injected_files,
                affected_files=affected_files
            )
            code_context_section = f"""
【相关代码上下文（已压缩）】
{compressed_context}

【提示】如需查看完整代码，请在工具调用中使用 read_chunk 按需读取。
"""
        else:
            code_context_section = ""

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

        # 构建项目契约卡 Prompt 部分
        project_card_section = self.ARCHITECT_PROJECT_CARD_PROMPT_SECTION.format(
            project_card=project_card_json
        )

        # 【强制工具探索】检查是否需要添加强制提示
        force_tool_section = ""
        retry_count = state.get("_retry_count", 0)
        force_tool_use = state.get("_force_tool_use", False)
        
        if retry_count > 0 or force_tool_use:
            force_tool_section = f"""
【⚠️ 强制要求 - 第 {retry_count} 次重试】
你之前没有使用任何工具探索代码就直接输出了！这是严格禁止的行为。

**必须执行以下操作**：
1. 使用 `glob` 查找相关文件路径
2. 使用 `grep_ast` 搜索关键函数或类
3. 使用 `read_chunk` 读取至少一个关键文件的内容
4. 然后基于实际读取的代码输出 JSON 结果

**绝对禁止**：
- ❌ 不使用任何工具直接输出 JSON
- ❌ 只基于预加载的代码片段做假设
- ❌ 臆想不存在的文件或函数

**正确流程示例**：
1. `glob("app/api/v1/*.py")` - 查找 API 文件
2. `grep_ast("login", search_type="function")` - 搜索登录相关函数
3. `read_chunk("app/api/v1/auth.py")` - 读取认证文件内容
4. 基于读取的内容输出设计方案

如果你仍然不调用工具直接输出，系统将再次要求重试！
"""

        # 根据阶段选择不同的任务描述
        phase = state.get("phase", "exploration")
        
        if phase == "exploration":
            # 【探索阶段】重点是识别 affected_files
            task_section = f"""【你的任务 - 探索阶段】
请使用工具自由探索项目代码库，识别与需求相关的文件。

**探索目标**：
1. 使用 `glob` 查找相关目录的文件结构
2. 使用 `grep_ast` 搜索关键函数、类或接口
3. 使用 `read_chunk` 读取关键文件的部分内容以确认相关性
4. **输出所有可能受影响的文件列表**

**输出要求**：
1. `feature_description`：用一句话总结功能
2. `affected_files`：**列出所有可能受影响的文件路径**（这是最重要的输出）
3. `estimated_effort`：预估工作量（粗略估计即可）
4. `technical_design`：简要的技术方案概述（不需要详细设计）
5. `acceptance_criteria`：3-5 条高层次的验收标准
6. `required_symbols`：**初步识别**可能需要修改的符号（不需要完整的签名）

**注意**：
- 重点是识别文件，不需要读取完整文件内容
- 使用工具确认文件存在和相关性
- 尽可能全面地列出所有可能受影响的文件
"""
        else:
            # 【设计阶段】由 _build_design_prompt 处理，这里不会用到
            task_section = """【你的任务】
基于提供的完整文件内容，输出详细的技术设计方案。
"""

        return f"""【用户需求】
{requirement}

{task_section}

{project_card_section}

{code_context_section}
{element_context_str}
{force_tool_section}

【重要提示】
- 在指定 `required_symbols` 的 `module` 时，必须参考【项目契约卡】中的 directory_structure 和 symbol_index
- 例如：如果文件树中有 `app/utils/system_monitor.py`，就不要指定 `app/utils/component_monitor.py`
- 如果不确定文件是否存在，优先使用工具探索确认，或在 `affected_files` 中明确标注需要创建新文件
- **必须使用工具探索后输出，禁止直接输出**

直接输出 JSON，不要有任何前缀或后缀。
"""

    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出为字典"""
        return self._parse_json_response(response)

    def validate_output(self, output: Dict[str, Any]) -> ArchitectOutput:
        """校验输出为 ArchitectOutput 模型"""
        return ArchitectOutput(**output)

    def _build_output_from_tool_results(self, tool_results: List[Dict[str, Any]]) -> Optional[ArchitectOutput]:
        """
        从工具调用结果构建 ArchitectOutput（当达到最大工具调用次数时使用）

        基于工具读取的文件路径构建一个基础的设计方案。
        """
        from typing import Any, Optional

        # 收集所有成功读取的文件路径
        affected_files = []
        for tool_result in tool_results:
            if tool_result.get("tool") == "read_file":
                result_data = tool_result.get("result", {})
                if result_data.get("exists"):
                    file_path = result_data.get("file", "")
                    if file_path and file_path not in affected_files:
                        affected_files.append(file_path)

        if not affected_files:
            return None

        # 构建一个基础的 ArchitectOutput（强化降级输出，确保验收标准不为空）
        return ArchitectOutput(
            feature_description="【降级输出 - 需要人工确认】基于工具探索自动生成的功能描述",
            affected_files=affected_files,
            estimated_effort="待评估（降级输出）",
            technical_design="通过工具调用探索了项目代码，但由于上下文限制未能完成完整分析。建议人工补充详细需求。",
            acceptance_criteria=[
                "【需要人工补充 - 系统无法自动推导】请明确本次变更需要满足的具体验收条件",
                "例如：API 端点必须返回特定的状态码和响应格式",
                "例如：函数必须实现特定的输入输出签名"
            ]
        )

    async def analyze(
        self,
        requirement: str,
        element_context: Optional[Dict[str, Any]] = None,
        pipeline_id: int = 0,
        project_path: str = "/workspace/backend"
    ) -> Dict[str, Any]:
        """
        分析需求并输出方案

        【两步式流程】
        第一步：自由探索 - 让 Agent 使用工具探索项目，输出 affected_files
        第二步：详细设计 - 读取 affected_files 的完整内容，生成详细设计方案

        Args:
            requirement: 用户需求描述
            element_context: 页面元素上下文（可选）
            pipeline_id: Pipeline ID
            project_path: 项目路径（用于工具执行）

        Returns:
            Dict: 包含分析结果或错误信息，以及 injected_files（读取的文件内容）
        """
        from app.core.sse_log_buffer import push_log
        started_at = time.time()

        # ============================================================
        # 【第一步：自由探索】让 Agent 自由探索项目，识别 affected_files
        # ============================================================
        t1 = time.time()
        logger.info(f"[ArchitectAgent] 第一步：自由探索项目...", extra={"pipeline_id": pipeline_id})
        if pipeline_id:
            await push_log(pipeline_id, "info", "🏗️ ArchitectAgent 第一步：自由探索项目代码...", stage="ARCHITECT")

        # 构建探索阶段的 state（不包含预加载文件，让 Agent 自由探索）
        exploration_state = {
            "requirement": requirement,
            "element_context": element_context,
            "project_path": project_path,
            "phase": "exploration",  # 标记为探索阶段
            "preloaded_files": {}  # 探索阶段不预加载，让 Agent 自己探索
        }
        
        # 执行探索阶段
        exploration_result = await self._run_exploration_phase(
            exploration_state=exploration_state,
            pipeline_id=pipeline_id
        )
        
        if not exploration_result.get("success"):
            logger.error(f"[ArchitectAgent] 探索阶段失败: {exploration_result.get('error')}")
            return exploration_result
        
        # 获取探索阶段识别的 affected_files
        affected_files = exploration_result.get("output", {}).get("affected_files", [])
        if not affected_files:
            logger.error(f"[ArchitectAgent] 探索阶段未识别到任何 affected_files")
            return {
                "success": False,
                "error": "探索阶段未识别到任何受影响的文件",
                "output": exploration_result.get("output")
            }
        
        exploration_ms = int((time.time() - t1) * 1000)
        logger.info(f"[ArchitectAgent] 探索阶段完成 (耗时 {exploration_ms}ms)，识别到 {len(affected_files)} 个 affected_files: {affected_files}", extra={"pipeline_id": pipeline_id, "exploration_ms": exploration_ms})
        if pipeline_id:
            await push_log(pipeline_id, "info", f"🔍 识别到 {len(affected_files)} 个可能受影响的文件", stage="ARCHITECT")
            for f in affected_files[:5]:
                await push_log(pipeline_id, "info", f"   - {f}", stage="ARCHITECT")
            if len(affected_files) > 5:
                await push_log(pipeline_id, "info", f"   ... 等共 {len(affected_files)} 个文件", stage="ARCHITECT")
        
        # ============================================================
        # 【第二步：详细设计】读取 affected_files 完整内容，生成详细方案
        # ============================================================
        t2 = time.time()
        logger.info(f"[ArchitectAgent] 第二步：读取文件并生成详细设计方案...", extra={"pipeline_id": pipeline_id})
        if pipeline_id:
            await push_log(pipeline_id, "info", "📋 ArchitectAgent 第二步：读取文件内容并生成详细设计方案...", stage="ARCHITECT")
        
        # 读取所有 affected_files 的完整内容
        full_file_contents = await self._read_affected_files(
            affected_files=affected_files,
            project_path=project_path,
            pipeline_id=pipeline_id
        )
        
        if not full_file_contents:
            logger.error(f"[ArchitectAgent] 无法读取任何 affected_files 的内容")
            return {
                "success": False,
                "error": "无法读取 affected_files 的内容",
                "affected_files": affected_files
            }
        
        logger.info(f"[ArchitectAgent] 成功读取 {len(full_file_contents)} 个文件的完整内容")
        if pipeline_id:
            await push_log(pipeline_id, "info", f"📖 已读取 {len(full_file_contents)} 个文件的完整内容", stage="ARCHITECT")
        
        # 构建详细设计阶段的 state
        design_state = {
            "requirement": requirement,
            "element_context": element_context,
            "project_path": project_path,
            "phase": "design",  # 标记为设计阶段
            "exploration_result": exploration_result.get("output", {}),  # 探索阶段的结果
            "full_file_contents": full_file_contents,  # 完整文件内容
            "affected_files": affected_files
        }
        
        # 执行详细设计阶段
        design_result = await self._run_design_phase(
            design_state=design_state,
            pipeline_id=pipeline_id
        )

        # 【关键修复】合并探索阶段的工具调用计数到设计阶段结果
        exploration_tool_calls = exploration_result.get("tool_calls", 0)
        design_tool_calls = design_result.get("tool_calls", 0)
        total_tool_calls = exploration_tool_calls + design_tool_calls

        # 【新增】合并 tool_results
        exploration_tool_results = exploration_result.get("tool_results", [])
        design_tool_results = design_result.get("tool_results", [])
        all_tool_results = exploration_tool_results + design_tool_results
        
        # 【调试】记录 tool_results 的详细信息
        logger.info(f"[ArchitectAgent] exploration_tool_results 数量: {len(exploration_tool_results)}")
        logger.info(f"[ArchitectAgent] design_tool_results 数量: {len(design_tool_results)}")
        logger.info(f"[ArchitectAgent] all_tool_results 数量: {len(all_tool_results)}")
        if exploration_tool_results:
            logger.info(f"[ArchitectAgent] exploration_tool_results 第一项: {exploration_tool_results[0]}")
        if design_tool_results:
            logger.info(f"[ArchitectAgent] design_tool_results 第一项: {design_tool_results[0]}")

        # 合并结果
        if design_result.get("success"):
            # 【修复】过滤掉内容为空的文件（表示文件不存在），避免 CoderAgent 误用 modify 操作
            filtered_file_contents = {k: v for k, v in full_file_contents.items() if v}
            
            # 将 injected_files 添加到结果中
            if design_result.get("output"):
                design_result["output"]["injected_files"] = filtered_file_contents
                design_result["injected_files"] = filtered_file_contents
            
            # 【新增】记录被过滤掉的文件（新文件）
            new_files = [k for k, v in full_file_contents.items() if not v]
            if new_files:
                logger.info(f"[ArchitectAgent] 发现 {len(new_files)} 个新文件（将使用 add 操作）: {new_files}")

            # 【关键修复】保存总的工具调用计数
            design_result["tool_calls"] = total_tool_calls
            design_result["exploration_tool_calls"] = exploration_tool_calls
            design_result["design_tool_calls"] = design_tool_calls
            # 【新增】保存合并后的 tool_results
            design_result["tool_results"] = all_tool_results

            logger.info(f"[ArchitectAgent] 两步式分析完成，成功生成设计方案（共使用 {total_tool_calls} 次工具调用）")
            if pipeline_id:
                await push_log(pipeline_id, "info", f"✅ ArchitectAgent 完成，已生成详细设计方案（使用了 {total_tool_calls} 次工具调用）", stage="ARCHITECT")
        else:
            # 即使失败也保存工具调用计数（用于调试）
            design_result["tool_calls"] = total_tool_calls
            design_result["exploration_tool_calls"] = exploration_tool_calls
            design_result["design_tool_calls"] = design_tool_calls
            # 【新增】保存合并后的 tool_results
            design_result["tool_results"] = all_tool_results

        # 【关键】调用工具探索配额检查
        await self._enforce_tool_exploration_quota(design_result, pipeline_id)
        total_duration_ms = int((time.time() - started_at) * 1000)
        design_ms = int((time.time() - t2) * 1000)

        # 记录两阶段耗时日志（仅当 pipeline_id 有效时）
        if pipeline_id:
            logger.info(
                f"[ArchitectAgent] 两阶段耗时: 探索={exploration_ms}ms, 设计={design_ms}ms, 总计={total_duration_ms}ms",
                extra={"pipeline_id": pipeline_id}
            )
            await push_log(
                pipeline_id, "info",
                f"⏱️ ArchitectAgent 耗时: 探索阶段 {exploration_ms}ms + 设计阶段 {design_ms}ms = {total_duration_ms}ms",
                stage="ARCHITECT"
            )
        design_result["duration_ms"] = design_result.get("duration_ms") or total_duration_ms
        design_result["input_tokens"] = (
            (exploration_result.get("input_tokens", 0) or 0)
            + (design_result.get("input_tokens", 0) or 0)
        )
        design_result["output_tokens"] = (
            (exploration_result.get("output_tokens", 0) or 0)
            + (design_result.get("output_tokens", 0) or 0)
        )

        # 【关键】验证 required_symbols 中的文件是否存在于 affected_files 中
        if design_result.get("success") and design_result.get("output"):
            output = design_result["output"]
            required_symbols = output.get("required_symbols", [])
            affected_files = output.get("affected_files", [])

            if required_symbols:
                # 【简化】合并 P0-1 日志，只保留一条汇总日志
                symbols_with_contract = [
                    s for s in required_symbols
                    if s.get("return_fields")
                ]
                if symbols_with_contract:
                    contract_summary = {s.get("name"): [f.get("name") for f in s.get("return_fields", [])] for s in symbols_with_contract}
                    logger.info(f"[ArchitectAgent] 发现 {len(symbols_with_contract)} 个带契约的符号", extra={
                        "pipeline_id": pipeline_id,
                        "contract_summary": contract_summary
                    })

                # 构建 affected_files 的集合（标准化路径）
                affected_set = set()
                for f in affected_files:
                    clean = normalize_relative_path(f)
                    affected_set.add(clean)
                    affected_set.add(f"backend/{clean}")

                # 验证每个 required_symbol
                validated_symbols = []
                for symbol in required_symbols:
                    module = symbol.get("module", "")
                    if not module:
                        continue

                    # 【重构】使用 path_utils 标准化模块路径
                    clean_module = normalize_relative_path(module)

                    # 检查是否在 affected_files 中
                    if clean_module in affected_set or f"backend/{clean_module}" in affected_set:
                        validated_symbols.append(symbol)
                    else:
                        # 【放宽】如果文件在预加载的代码中，也认为是有效的
                        preloaded = output.get("_preloaded_files", [])
                        if clean_module in preloaded or f"backend/{clean_module}" in preloaded:
                            validated_symbols.append(symbol)
                            logger.info(f"[ArchitectAgent] required_symbol 文件在预加载列表中: {module}", extra={
                                "pipeline_id": pipeline_id,
                                "symbol": symbol.get("name")
                            })
                        else:
                            logger.warning(f"[ArchitectAgent] required_symbol 中的文件不存在: {module}", extra={
                                "pipeline_id": pipeline_id,
                                "symbol": symbol.get("name"),
                                "module_path": module
                            })
                
                # 更新 required_symbols 为验证后的列表
                if len(validated_symbols) != len(required_symbols):
                    logger.info(f"[ArchitectAgent] 过滤后的 required_symbols: {len(validated_symbols)}/{len(required_symbols)}")
                    output["required_symbols"] = validated_symbols
                    # 同时更新 result 中的 output
                    design_result["output"] = output

        return design_result

    async def _enforce_tool_exploration_quota(
        self,
        result: Dict[str, Any],
        pipeline_id: int
    ) -> None:
        """
        【改进1】工具调用探索配额后置检查
        
        验证 ArchitectAgent 输出的 affected_files 中的每个文件是否已被充分探索。
        如果存在未读取的文件，在 result 中添加警告信息。
        
        【强制】必须至少调用 1 次工具，否则标记为失败。
        """
        output = result.get("output", {})
        affected_files = output.get("affected_files", [])
        tool_results = result.get("tool_results", [])
        tool_call_count = result.get("tool_calls", 0)
        
        if tool_call_count == 0:
            logger.error(
                f"[ArchitectAgent] 未进行任何工具调用就直接输出！affected_files={affected_files}",
                extra={"pipeline_id": pipeline_id}
            )
            # 【强制】标记为失败，要求重试
            result["success"] = False
            result["error"] = (
                "ArchitectAgent 未使用任何工具探索代码。"
                "根据项目规则，架构师必须使用工具探索项目代码后才能输出设计方案。"
                "请重试或检查系统配置。"
            )
            output["_exploration_error"] = (
                "严重错误：未使用任何工具探索代码。"
                "必须使用 glob/grep_ast/read_chunk/semantic_search 等工具探索项目后，"
                "基于实际代码输出设计方案。"
            )
            result["output"] = output
            return
        
        # 检查 affected_files 中哪些未被读取
        unread_files = []
        read_files = set()
        
        if self._agent_tools:
            for path in self._agent_tools._file_cache:
                clean = normalize_relative_path(path)
                read_files.add(clean)
                read_files.add(f"backend/{clean}")

        for f in affected_files:
            clean = normalize_relative_path(f)
            if clean not in read_files and f"backend/{clean}" not in read_files:
                unread_files.append(f)
        
        if unread_files:
            logger.warning(
                f"[ArchitectAgent] affected_files 中有 {len(unread_files)} 个未被读取: {unread_files}",
                extra={"pipeline_id": pipeline_id}
            )
            output["_exploration_warning"] = (
                f"以下文件未被充分探索: {unread_files}。"
                "这些文件的代码结构可能未被准确理解。"
            )
            result["output"] = output
        else:
            logger.info(
                f"[ArchitectAgent] 所有 {len(affected_files)} 个 affected_files 均已充分探索",
                extra={"pipeline_id": pipeline_id}
            )

    def _build_reuse_table(self, full_files_context: Dict[str, str]) -> str:
        """
        【改进2】从 full_files_context 构建现有函数复用表
        
        解析每个文件中的函数定义、签名和返回键名，生成可读的复用表。
        """
        import re
        
        if not full_files_context:
            return ""
        
        lines = ["【现有函数复用表 - 设计时必须参考以下现有函数，优先复用而非创建新函数】\n"]
        
        for file_path, content in full_files_context.items():
            lines.append(f"\n### 文件: {file_path}")
            
            # 提取所有函数定义
            func_pattern = r"(?P<async>async\s+)?def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)(?:\s*->\s*(?P<ret>[^:]+))?:\s*"
            for m in re.finditer(func_pattern, content):
                func_name = m.group("name")
                is_async = "async " if m.group("async") else ""
                params = m.group("params")
                ret_type = m.group("ret").strip() if m.group("ret") else "Any"
                
                # 尝试提取函数返回字典的键名
                return_keys = []
                # 查找函数体内第一个 return { ... } 语句
                func_start = m.end()
                brace_depth = 0
                in_return = False
                return_content = []
                
                for i, ch in enumerate(content[func_start:], func_start):
                    if ch == '\n' and i + 1 < len(content) and content[i+1] in ' \t':
                        continue
                    if not in_return and content[i:i+7].strip() == "return" and '{' in content[i:i+20]:
                        in_return = True
                        brace_start = content.index('{', i)
                        brace_depth = 1
                        for j, c in enumerate(content[brace_start + 1:], brace_start + 1):
                            if c == '{':
                                brace_depth += 1
                            elif c == '}':
                                brace_depth -= 1
                                if brace_depth == 0:
                                    return_content.append(content[brace_start:j + 1])
                                    break
                        break
                
                if return_content:
                    # 解析返回字典的键名
                    for rc in return_content:
                        keys = re.findall(r"['\"](\w+)['\"]\s*:", rc)
                        return_keys.extend(keys)
                
                lines.append(
                    f"  - {is_async}def {func_name}({params}) -> {ret_type}"
                )
                if return_keys:
                    lines.append(f"    返回键名: {', '.join(return_keys)}")
        
        return "\n".join(lines)

    async def _preload_relevant_code(
        self,
        requirement: str,
        file_tree: Dict[str, Any],
        project_path: str,
        pipeline_id: int,
        max_files: int = 5
    ) -> Dict[str, str]:
        """
        【强制注入方案】预检索与需求相关的代码
        
        根据需求关键词，自动检索相关文件并读取内容，注入到 Prompt 中。
        这样 LLM 无需调用工具就能基于现有代码进行分析。
        
        Args:
            requirement: 用户需求描述
            file_tree: 项目文件树
            project_path: 项目路径
            pipeline_id: Pipeline ID
            max_files: 最大预加载文件数
            
        Returns:
            Dict[str, str]: 文件路径到内容的映射
        """
        import re
        from app.service.sandbox_orchestrator import get_sandbox_orchestrator
        
        preloaded = {}
        
        # 1. 从需求中提取关键词（健康检查相关）
        keywords = []
        requirement_lower = requirement.lower()
        
        # 健康检查相关关键词映射
        keyword_mapping = {
            "health": ["health", "healthcheck", "health_check"],
            "database": ["database", "db", "postgres", "mysql"],
            "disk": ["disk", "storage", "硬盘", "磁盘"],
            "memory": ["memory", "ram", "内存"],
            "cpu": ["cpu", "processor", "处理器"],
            "monitor": ["monitor", "监控", "状态"],
        }
        
        for category, terms in keyword_mapping.items():
            if any(term in requirement_lower for term in terms):
                keywords.append(category)
        
        if not keywords:
            keywords = ["api", "service"]  # 默认关键词
        
        logger.info(f"[ArchitectAgent] 预检索关键词: {keywords}", extra={"pipeline_id": pipeline_id})
        
        # 2. 根据关键词猜测相关文件路径
        candidate_files = []
        
        # 常见的健康检查相关文件模式
        file_patterns = {
            "health": ["app/api/v1/health.py", "app/service/health_service.py", "app/utils/system_monitor.py"],
            "database": ["app/core/database.py", "app/utils/db_utils.py"],
            "disk": ["app/utils/system_monitor.py", "app/utils/disk_utils.py"],
            "memory": ["app/utils/system_monitor.py", "app/utils/memory_utils.py"],
            "monitor": ["app/utils/system_monitor.py", "app/service/monitoring.py"],
        }
        
        for keyword in keywords:
            if keyword in file_patterns:
                candidate_files.extend(file_patterns[keyword])
        
        # 去重并检查文件是否存在
        candidate_files = list(dict.fromkeys(candidate_files))  # 保持顺序去重
        
        # 3. 使用 SandboxFileService 读取文件内容
        from app.service.sandbox_file_service import SandboxFileService
        file_service = SandboxFileService(pipeline_id)
        
        for file_path in candidate_files[:max_files]:
            try:
                result = await file_service.read_file(file_path)
                if result.exists and result.content:
                    preloaded[file_path] = result.content
                    logger.info(f"[ArchitectAgent] 预加载成功: {file_path} ({len(result.content)} 字符)", 
                               extra={"pipeline_id": pipeline_id})
            except Exception as e:
                logger.warning(f"[ArchitectAgent] 预加载失败: {file_path} - {e}", 
                              extra={"pipeline_id": pipeline_id})
        
        return preloaded

    async def _run_exploration_phase(
        self,
        exploration_state: Dict[str, Any],
        pipeline_id: int
    ) -> Dict[str, Any]:
        """
        【第一步：自由探索阶段】
        
        让 Agent 自由使用工具探索项目代码，识别可能受影响的文件。
        这个阶段的目标是输出 affected_files 列表。
        
        Args:
            exploration_state: 探索阶段的初始状态
            pipeline_id: Pipeline ID
            
        Returns:
            Dict: 探索结果，包含 affected_files
        """
        from app.core.sse_log_buffer import push_log
        
        max_retries = 2
        retry_count = 0
        result = None
        
        while retry_count <= max_retries:
            result = await self.execute(
                pipeline_id=pipeline_id,
                stage_name="ARCHITECT_EXPLORATION",
                initial_state=exploration_state,
                max_tokens=16384,
                # 【关键】探索阶段不使用 response_format，让 LLM 自由调用工具
                response_format=None
            )
            
            # 检查是否调用了工具
            tool_call_count = result.get("tool_calls", 0)
            tool_results_from_execute = result.get("tool_results", [])
            
            # 【调试】记录 tool_results 的详细信息
            logger.info(f"[ArchitectAgent] 探索阶段 result.get('tool_calls'): {tool_call_count}")
            logger.info(f"[ArchitectAgent] 探索阶段 result.get('tool_results') 数量: {len(tool_results_from_execute)}")
            if tool_results_from_execute:
                logger.info(f"[ArchitectAgent] 探索阶段 tool_results 第一项: {tool_results_from_execute[0]}")
            else:
                logger.warning(f"[ArchitectAgent] 探索阶段 tool_results 为空！result keys: {result.keys()}")
            
            if tool_call_count > 0:
                logger.info(f"[ArchitectAgent] 探索阶段成功调用 {tool_call_count} 次工具")
                break
            
            # 没有调用工具，需要重试
            retry_count += 1
            if retry_count <= max_retries:
                logger.warning(
                    f"[ArchitectAgent] 探索阶段未调用工具，第 {retry_count}/{max_retries} 次重试..."
                )
                if pipeline_id:
                    await push_log(
                        pipeline_id, 
                        "warning", 
                        f"探索阶段未使用工具，正在进行第 {retry_count}次重试...", 
                        stage="ARCHITECT"
                    )
                
                exploration_state["_retry_count"] = retry_count
                exploration_state["_force_tool_use"] = True
                if self._agent_tools:
                    self._agent_tools._file_cache.clear()
            else:
                logger.error(f"[ArchitectAgent] 探索阶段重试 {max_retries} 次后仍未调用工具")
                if pipeline_id:
                    await push_log(
                        pipeline_id, 
                        "error", 
                        f"探索阶段重试 {max_retries} 次后仍未使用工具", 
                        stage="ARCHITECT"
                    )
        
        # 后置检查：验证是否调用了工具
        if result and result.get("success") and result.get("output"):
            await self._enforce_tool_exploration_quota(result, pipeline_id)
        
        return result

    async def _read_affected_files(
        self,
        affected_files: List[str],
        project_path: str,
        pipeline_id: int
    ) -> Dict[str, str]:
        """
        读取所有 affected_files 的完整内容
        
        Args:
            affected_files: 文件路径列表
            project_path: 项目路径
            pipeline_id: Pipeline ID
            
        Returns:
            Dict[str, str]: 文件路径到内容的映射
        """
        from app.service.sandbox_file_service import SandboxFileService
        
        full_contents = {}
        file_service = SandboxFileService(pipeline_id)
        
        for file_path in affected_files:
            # 【重构】使用 path_utils 标准化路径
            clean_path = normalize_relative_path(file_path)
            
            try:
                result = await file_service.read_file(clean_path)
                if result.exists and result.content:
                    full_contents[clean_path] = result.content
                    logger.info(f"[ArchitectAgent] 成功读取文件: {clean_path} ({len(result.content)} 字符)")
                else:
                    # 【改进】区分"文件不存在"和"读取错误"
                    error_msg = result.error or ""
                    if "No such file" in error_msg or "not found" in error_msg.lower():
                        # 文件不存在，标记为新文件（需要创建）
                        full_contents[clean_path] = ""  # 空内容表示新文件
                        logger.info(f"[ArchitectAgent] 文件不存在，将作为新文件创建: {clean_path}")
                    else:
                        logger.warning(f"[ArchitectAgent] 无法读取文件: {clean_path}, error={result.error}")
            except Exception as e:
                logger.error(f"[ArchitectAgent] 读取文件失败: {clean_path} - {e}")
        
        return full_contents

    async def _run_design_phase(
        self,
        design_state: Dict[str, Any],
        pipeline_id: int
    ) -> Dict[str, Any]:
        """
        【第二步：详细设计阶段】
        
        基于完整的文件内容，生成详细的技术设计方案。
        这个阶段输出完整的设计方案，包括 interface_specs 等。
        
        Args:
            design_state: 设计阶段的初始状态（包含 full_file_contents）
            pipeline_id: Pipeline ID
            
        Returns:
            Dict: 详细设计结果
        """
        from app.core.sse_log_buffer import push_log
        
        # 构建设计阶段的 user_prompt
        design_prompt = self._build_design_prompt(design_state)
        
        # 使用父类的 _call_llm_with_tools 方法，但不传递工具
        # 因为我们已经有完整的文件内容，不需要再调用工具
        result = await self._call_llm_with_tools(
            system_prompt=self.system_prompt,
            user_prompt=design_prompt,
            project_path=design_state.get("project_path", "/workspace/backend"),
            pipeline_id=pipeline_id,
            max_tokens=32768,
            response_format={"type": "json_object"}
        )
        
        # 解析和验证输出
        if result.get("content"):
            try:
                parsed_output = self.parse_output(result["content"])
                validated_output = self.validate_output(parsed_output)
                
                output_dict = validated_output.model_dump() if hasattr(validated_output, 'model_dump') else validated_output
                
                return {
                    "success": True,
                    "output": output_dict,
                    "input_tokens": result.get("input_tokens", 0),
                    "output_tokens": result.get("output_tokens", 0),
                    "duration_ms": result.get("duration_ms", 0),
                    "tool_calls": result.get("tool_calls", 0),
                    "tool_results": result.get("tool_results", []),
                    "raw_output": result["content"]
                }
            except Exception as e:
                logger.error(f"[ArchitectAgent] 设计阶段输出验证失败: {e}")
                return {
                    "success": False,
                    "error": f"设计阶段输出验证失败: {e}",
                    "input_tokens": result.get("input_tokens", 0),
                    "output_tokens": result.get("output_tokens", 0),
                    "duration_ms": result.get("duration_ms", 0),
                    "tool_calls": result.get("tool_calls", 0),
                    "tool_results": result.get("tool_results", []),
                    "raw_output": result.get("content", "")[:500]
                }
        else:
            return {
                "success": False,
                "error": "设计阶段 LLM 返回空内容",
                "input_tokens": result.get("input_tokens", 0),
                "output_tokens": result.get("output_tokens", 0),
                "duration_ms": result.get("duration_ms", 0),
                "tool_calls": result.get("tool_calls", 0),
                "tool_results": result.get("tool_results", []),
                "raw_output": ""
            }

    def _build_design_prompt(self, design_state: Dict[str, Any]) -> str:
        """
        构建设计阶段的 Prompt
        
        Args:
            design_state: 设计阶段状态
            
        Returns:
            str: Prompt 字符串
        """
        requirement = design_state.get("requirement", "")
        affected_files = design_state.get("affected_files", [])
        full_file_contents = design_state.get("full_file_contents", {})
        exploration_result = design_state.get("exploration_result", {})
        
        # 构建文件内容部分
        files_section = []
        new_files = []  # 新文件列表
        for file_path, content in full_file_contents.items():
            if content == "":
                # 空内容表示新文件
                new_files.append(file_path)
                files_section.append(f"""
=== 文件: {file_path} (🆕 新文件，需要创建) ===
该文件不存在，需要新建。请参考项目现有代码结构设计实现。
""")
            else:
                files_section.append(f"""
=== 文件: {file_path} ===
```python
{content}
```
""")
        files_str = "\n".join(files_section)
        
        # 构建新文件提示
        new_files_hint = ""
        if new_files:
            new_files_hint = f"""

【🆕 新文件提示】
以下文件不存在，需要新建：
{chr(10).join(f'- {f}' for f in new_files)}

请在 required_symbols 中指定需要在这些新文件中实现的符号。
"""
        
        # 构建探索阶段的结论
        exploration_summary = f"""
【探索阶段结论】
- 功能描述: {exploration_result.get('feature_description', 'N/A')}
- 预估工作量: {exploration_result.get('estimated_effort', 'N/A')}
- 技术方案概要: {exploration_result.get('technical_design', 'N/A')[:500] if exploration_result.get('technical_design') else 'N/A'}
"""
        
        return f"""【用户需求】
{requirement}

{exploration_summary}
{new_files_hint}
【受影响文件列表】
{affected_files}

【完整文件内容】
{files_str}

【你的任务】
基于以上完整的文件内容，输出详细的技术设计方案。

要求：
1. `feature_description`: 用一句话总结功能（可以基于探索阶段的结论优化）
2. `affected_files`: 受影响文件列表（与上面列表一致）
3. `estimated_effort`: 预估工作量
4. `technical_design`: 详细的技术方案（基于完整代码分析，对于新文件说明需要实现的逻辑）
5. `acceptance_criteria`: 3-5 条可验证的验收标准
6. `required_symbols`: 必需实现的符号清单（基于代码分析）
   - 每个符号必须包含: name, type, module, signature
   - 只列出需要修改或新增的符号
   - 对于新文件，列出需要在该文件中实现的所有符号

【输出格式】
直接输出纯 JSON，不要有任何前缀或后缀。
"""


# 单例实例
architect_agent = ArchitectAgent()
