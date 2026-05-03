"""
设计师 Agent
基于 LangGraph 状态机实现，继承 BaseAgent 统一调用逻辑

职责：
1. 分析 ArchitectAgent 的输出
2. 结合项目文件树（特别是 backend/app/api/ 风格）
3. 结合代码库上下文（语义检索 + 完整文件内容）
4. 输出详细的技术设计方案

使用 Instructor 强制执行结构化输出
"""

import json
import logging
import time
from typing import Dict, Optional, Any

import instructor
from instructor import Mode
import litellm

from app.agents.base import LangGraphAgent
from app.agents.schemas import DesignerOutput, DesignerOutputV2
from app.core.config import settings

logger = logging.getLogger(__name__)


class DesignerAgent(LangGraphAgent[DesignerOutput]):
    """
    设计师 Agent
    
    根据架构师输出进行详细技术设计
    继承 LangGraphAgent，只需实现业务差异部分
    """
    
    def __init__(self):
        super().__init__(agent_name="DesignerAgent")
    
    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调复用现有风格"""
        return """你是 OmniFlowAI 的设计师 Agent，负责根据架构师的分析输出详细的技术设计方案。

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

【项目标准对象字典 - 强制遵守】
• ResponseModel: 这是一个 FastAPI 统一响应包装对象。
  ◦ 结构: {success: bool, data: Any, error: Optional[str], request_id: str}
  ◦ 访问方式: 测试代码必须通过 response.data["key"] 访问业务数据
  ◦ 构造方式: 实现代码必须使用 success_response(data={...}) 或 error_response(message=...)
  ◦ 禁止: 直接返回裸字典或裸对象

• ComponentStatus: 这是一个枚举，值必须是 "healthy", "degraded", "unhealthy"
  ◦ 用于: 系统组件健康状态标记
  ◦ 转换: 底层状态 "up"/"down" 需要映射为 ComponentStatus

• HealthCheckResponse: 健康检查标准响应结构
  ◦ status: str - 整体状态 ("healthy"/"unhealthy"/"degraded")
  ◦ health_score: int - 健康度评分 (0-100)
  ◦ components: dict - 各组件状态详情
  ◦ timestamp: str - ISO格式时间戳

• DiskUsage / MemoryUsage / DatabaseStatus: 标准监控数据结构
  ◦ 必须使用标准键名: usage_percent (不是 used_percent), total_gb, used_gb, free_gb
  ◦ 禁止发明新的键名，必须与现有代码保持一致

【任务要求】
1. 仔细阅读 ArchitectAgent 的输出（功能描述、受影响文件列表）
2. 分析项目文件树，特别是 backend/app/api/ 目录下的现有 API 风格
3. 【重要】仔细阅读提供的代码上下文（related_code_context 和 full_files_context）
4. 参考现有代码的组织方式、命名规范和实现风格
5. 输出详细的技术设计方案

【输出格式 - 极其重要】
你必须直接输出纯 JSON 格式，不要包含任何其他文本、解释或标记。
输出必须是一个有效的 JSON 对象。

正确示例（直接输出 JSON）：
{"technical_design": "实现用户认证系统", "api_endpoints": [{"method": "POST", "path": "/api/v1/auth/login", "description": "用户登录"}], "function_changes": [{"file": "backend/app/api/v1/auth.py", "function": "login", "action": "add", "description": "添加登录接口"}], "logic_flow": "1. 接收用户名密码 2. 验证 3. 返回token", "dependencies": ["fastapi", "sqlmodel"], "affected_files": ["backend/app/api/v1/auth.py"]}

错误示例（不要这样输出）：
- 不要添加 ```json 标记
- 不要添加解释文本
- 不要使用工具调用格式如 [TOOL_CALL]
- 不要输出 "我需要先查看..." 等思考过程
- 只输出纯 JSON

【强制要求】
- 直接输出 JSON，不要有任何前缀或后缀
- 确保 JSON 格式完整有效
- 不要输出任何其他内容

【字段说明】
- technical_design: 技术设计方案概述
- api_endpoints: API 端点列表（包含 method, path, description, request_body, response_fields）
- function_changes: 函数修改列表（包含 file, function, action: add/modify/delete, description）
- logic_flow: 逻辑流图（文本描述形式）
- dependencies: 新增依赖列表
- affected_files: 受影响文件列表（相对路径）
- interface_specs: 接口契约清单（代码-测试契约，详见下方要求）

【接口契约生成要求 - 极其重要】
你必须输出 `interface_specs`，包含所有新增或修改的公开函数/API 端点，确保 Coder 和 Tester 能基于此清单对齐。

【接口契约格式要求 - 绝对禁止违反】
- symbol_name **只能是模块级的函数名或类名**！
- 【致命错误防范】绝对禁止将类里面的方法（如静态方法、实例方法）作为独立的 symbol_name 提取出来！
- 如果你需要暴露/使用类中的某个方法（例如 HealthService.get_component_health），你的 symbol_name 必须填写该【类名】（即 "HealthService"），并在 expected_behavior 中说明你需要使用它的哪个方法。
- 绝对不允许使用 "ClassName.method" 这类点分符号。
- 错误的 symbol_name: "get_component_health" (因为它是类方法)
- 正确的 symbol_name: "HealthService" (导出整个类)

每个 interface_spec 必须包含：
- symbol_name: 函数/类名（如 "check_database_status"）
- module: 所在模块路径（如 "app/api/v1/health.py"）
- signature: 函数签名（如 "async def check_database_status() -> dict"）
- expected_behavior: 简短行为描述（如 "返回数据库连接状态"）
- is_async: 是否为异步函数（true/false）
- return_type: 返回类型（可选，如 "dict", "User", "List[Item]")
- covers_criteria: 该接口覆盖的验收标准索引列表（从1开始）
- return_fields: 【运行时约束】如果返回 dict 或对象，必须列出所有必填字段
- error_responses: 【新增】错误响应规范列表，定义错误情况的返回格式

【运行时约束 - 极其重要】
如果函数返回 dict 或对象，必须在 return_fields 中明确声明所有必填字段：
- name: 字段名称（如 "status", "usage_percent"）
- type: 字段类型（如 "str", "int", "float", "dict", "list"）
- description: 字段描述（可选）
- required: 是否必填（默认 true）

这是**强制性要求**，目的是让 CoderAgent 生成代码时键名保持一致，避免 "used_percent" vs "usage_percent" 这类错误！

【错误响应规范 - 新增】
为了减少测试脆弱性，你必须为每个可能出错的情况定义 error_responses：
- error_code: 错误码（如 "SERVICE_UNAVAILABLE", "VALIDATION_ERROR"）
- message_format: 错误消息格式模板（如 "Service unavailable: {reason}"）
- message_contains: 错误消息中必须包含的关键字列表（用于模糊匹配）
- status_code: HTTP 状态码（如 503, 400）

【关键】这样 TesterAgent 可以使用 `assert "unavailable" in result["error"]` 而不是 `assert result["error"] == "Service unavailable"`，避免因为前缀变化导致测试失败！

【interface_specs.mock_dependencies 填写规则 - 必须遵守】
每个 interface_spec 如果其实现内部调用了以下任何一种外部资源，必须填写对应的 mock_dependencies：
- 系统调用（psutil、os.statvfs、subprocess）
- 数据库 IO（SQLAlchemy session、任何 ORM 查询）
- 网络 IO（httpx、aiohttp、requests）
- 文件 IO（open、pathlib）
- 时间（datetime.now、time.time）

mock_dependencies 字段格式：
- patch_target: 完整 patch 路径，必须与被测模块的 import 方式一致
  * 被测文件是 app/service/health_service.py
  * 该文件顶部写了 `import psutil`
  * 则 patch_target = "app.service.health_service.psutil"
  * 该文件顶部写了 `from psutil import virtual_memory`
  * 则 patch_target = "app.service.health_service.virtual_memory"
- mock_return_value: 默认 mock 返回值（happy path），如 {"percent": 30.0}
- is_async: 被 mock 的目标是否是 async 函数，是则用 AsyncMock
- description: 说明这个依赖的作用

正确示例：
{
  "symbol_name": "check_system_health",
  "module": "app/service/health_service.py",
  "signature": "def check_system_health() -> dict",
  "mock_dependencies": [
    {
      "patch_target": "app.service.health_service.psutil",
      "mock_return_value": {"cpu_percent": 30.0, "virtual_memory": {"percent": 45.0}},
      "is_async": false,
      "description": "系统资源监控库，用于获取 CPU 和内存使用率"
    },
    {
      "patch_target": "app.service.health_service.get_session",
      "mock_return_value": null,
      "is_async": true,
      "description": "数据库 session，async 函数"
    }
  ]
}

【Mock 铁律】
1. 只要函数内部调用了外部 IO，就必须在 mock_dependencies 中声明
2. patch_target 必须与被测代码的 import 方式完全一致
3. 不声明 mock_dependencies 会导致测试访问真实资源，测试失败！

正确示例1 - 健康检查服务：
```json
{{
  "interface_specs": [
    {{
      "symbol_name": "check_database_status",
      "module": "app/api/v1/health.py",
      "signature": "async def check_database_status() -> dict",
      "expected_behavior": "返回数据库连接状态，包含 status 和 response_time_ms 字段",
      "is_async": true,
      "return_type": "dict",
      "covers_criteria": [1, 2],
      "return_fields": [
        {{"name": "status", "type": "str", "description": "数据库状态: up/down", "required": true}},
        {{"name": "response_time_ms", "type": "float", "description": "响应时间(毫秒)", "required": true}}
      ],
      "error_responses": [
        {{
          "error_code": "SERVICE_UNAVAILABLE",
          "message_format": "Service unavailable: {{reason}}",
          "message_contains": ["unavailable", "service"],
          "status_code": 503
        }}
      ]
    }}
  ]
}}
```

正确示例2 - 用户服务：
```json
{{
  "interface_specs": [
    {{
      "symbol_name": "get_user_profile",
      "module": "app/api/v1/user.py",
      "signature": "async def get_user_profile(user_id: int) -> dict",
      "expected_behavior": "返回用户信息",
      "is_async": true,
      "return_type": "dict",
      "covers_criteria": [1],
      "return_fields": [
        {{"name": "id", "type": "int", "description": "用户ID", "required": true}},
        {{"name": "username", "type": "str", "description": "用户名", "required": true}},
        {{"name": "email", "type": "str", "description": "邮箱地址", "required": true}}
      ],
      "error_responses": [
        {{
          "error_code": "USER_NOT_FOUND",
          "message_format": "User not found: {{user_id}}",
          "message_contains": ["not found"],
          "status_code": 404
        }}
      ]
    }},
    {{
      "symbol_name": "UserService",
      "module": "app/service/user_service.py",
      "signature": "class UserService",
      "expected_behavior": "用户服务类，提供用户相关操作",
      "is_async": false,
      "return_type": "class",
      "covers_criteria": [1, 2],
      "return_fields": [],
      "error_responses": []
    }}
  ]
}}
```

正确示例3 - 时间戳服务：
```json
{{
  "interface_specs": [
    {{
      "symbol_name": "get_current_timestamp",
      "module": "app/service/timestamp_service.py",
      "signature": "def get_current_timestamp() -> dict",
      "expected_behavior": "返回当前时间戳",
      "is_async": false,
      "return_type": "dict",
      "covers_criteria": [1],
      "return_fields": [
        {{"name": "timestamp", "type": "float", "description": "Unix时间戳", "required": true}},
        {{"name": "iso_format", "type": "str", "description": "ISO格式时间", "required": true}}
      ],
      "error_responses": []
    }},
    {{
      "symbol_name": "timestamp_router",
      "module": "app/api/v1/timestamp.py",
      "signature": "timestamp_router = APIRouter()",
      "expected_behavior": "时间戳 API 路由器",
      "is_async": false,
      "return_type": "APIRouter",
      "covers_criteria": [1],
      "return_fields": [],
      "error_responses": []
    }}
  ]
}}
```

【禁止】不要遗漏任何字段，不要假设 CoderAgent 会自己决定键名！

【验收标准与接口契约映射 - 强制要求】
你必须输出 `contract_alignment`，明确说明每条验收标准如何被接口契约覆盖。

这是**强制性要求**，不输出或输出不完整将导致设计被拒绝！

【重试模式关键规则 - 绝对禁止遗漏符号】
如果你收到了反馈要求修正设计（rejection_feedback），必须遵守以下规则：
1. **保留所有必需符号**：ArchitectAgent 在 required_symbols 中列出的所有符号必须出现在 interface_specs 中
2. **不要删除已有符号**：即使你在修正 contract_alignment，也不要删除或遗漏任何 interface_specs 中的符号
3. **累加而非替换**：新的设计应该是在之前设计的基础上累加修正，而不是重新生成
4. **必需符号清单检查**：输出前必须检查 required_symbols 中的所有符号是否都在 interface_specs 中

contract_alignment 格式（使用 DesignerOutputV2）：
{
  "contract_alignment": [
    {
      "acceptance_criteria": "API 返回健康状态字段 overall_health",
      "covered_by": ["health_check", "HealthService"],
      "mapping_reason": "health_check 函数返回的 dict 中包含 overall_health 字段，由 HealthService 计算得出"
    },
    {
      "acceptance_criteria": "系统组件状态包含 database、disk、memory",
      "covered_by": ["get_system_health"],
      "mapping_reason": "get_system_health 返回的 components 字段包含所有子系统状态"
    }
  ]
}

映射要求：
1. **每条验收标准都必须有对应的映射**（acceptance_criteria 字段对应验收标准描述）
2. **covered_by 中的符号必须在 interface_specs 中存在**
3. **mapping_reason 必须具体说明接口如何满足验收标准**，不能写空话
4. **如果一条验收标准需要多个接口共同满足，列出所有相关接口**
5. **对齐率必须达到 100%**，缺少任何一条映射都会导致失败

生成 checklist（输出前自检）：
□ 是否列出了所有验收标准的映射（contract_alignment）？
□ 每个映射的 covered_by 是否在 interface_specs 中？
□ mapping_reason 是否具体说明了如何满足标准？
□ required_symbols 中的所有符号是否都包含在 interface_specs 中？（重试模式必须检查）

【接口契约设计原则 - 极其重要】
1. **尽可能沿用 `generated_files` 中已经存在的函数名和结构**
2. **不要引入全新的复杂类，除非现有代码完全无法满足需求**
3. **契约中每增加一个文件，你都需要明确说明原因**
4. **优先扩展现有函数，而不是创建全新的函数**
5. **如果现有代码中有类似功能的函数，直接复用其名称和签名**

【风格参考】
- 路由层：backend/app/api/v1/*.py，使用 FastAPI APIRouter
- 业务层：backend/app/service/*.py，实现业务逻辑
- 模型层：backend/app/models/*.py，使用 SQLModel
- 所有 API 返回统一格式：{success, data, error, request_id}

【代码上下文参考 - 重要】
我们为你检索了项目中相关的现有代码片段（在 related_code_context 字段中）。
同时提供了完整文件内容（在 full_files_context 字段中）。

【核心铁律 - 违反将导致设计被拒绝】
- 以复用现有逻辑为荣，以重复造轮子为耻！
- **必须仔细阅读 full_files_context 中的每一个文件内容**
- **interface_specs 必须与现有代码中的函数签名、类结构、返回字典的键名完全对齐**
- 如果发现现有代码中已有功能相似的函数，必须优先复用或扩展它们，而不是发明新的函数名
- 现有代码返回 {"status": "up"|"down", "response_time_ms": int}，你的契约就不能要求返回 {"status": "healthy"|"degraded"}
- 现有代码有 check_database 函数，你的契约就不能要求实现 check_database_health

【现有代码对齐检查清单】
输出前必须检查：
□ 是否阅读了 full_files_context 中的所有文件？
□ interface_specs 中的函数名是否与现有代码一致？
□ 返回字段的键名是否与现有代码返回的字典键名一致？
□ 如果发现类似功能，是否复用了现有函数名而不是创建新的？
□ 是否对比了现有函数的签名（参数、返回值类型）？

【函数签名一致性 - 强制要求】
对于每个 interface_spec，你必须：
1. 在 full_files_context 中找到对应的文件
2. 如果函数已存在，提取其完整签名（包括参数名、类型注解、async标记）
3. 在 interface_spec 中引用现有签名，并说明是否需要修改
4. 如果修改签名，必须在 expected_behavior 中说明修改理由

签名引用格式：
```
symbol_name: check_database
module: app/utils/monitor.py
existing_signature: async def check_database() -> dict  # 从现有代码提取
proposed_signature: async def check_database() -> dict  # 保持不变
signature_change_reason: 无需修改，复用现有函数
```

【代码上下文参考 - 重要】
请务必参考这些片段的风格、类定义和工具函数来设计你的方案
如果检索到的代码中有类似的实现，请优先复用或扩展，而不是从头创建
注意保持与现有代码的命名规范、参数风格和错误处理方式一致
仔细阅读完整文件内容，理解现有代码的架构和模式
**不要创建新的类来封装已有功能，优先使用函数**

【项目结构参考】
在 project_structure_summary 字段中提供了项目整体结构摘要，帮助你理解代码库规模和组织方式。

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- **优先复用现有的接口和模式，不要创造新的抽象**
- 遵循项目现有的架构分层规范
- 如果检索到的代码中有可用的工具函数或类，请在设计中明确引用
- affected_files 必须包含所有需要修改或新增的文件路径
- **interface_specs 中的每个符号都必须是真实存在的或明确需要新建的**
- **不要假设某个函数"应该存在"，只列出实际看到的或明确需要创建的**
"""
    
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt
        
        Args:
            state: 包含 architect_output, file_tree, related_code_context, full_files_context 的状态
        """
        architect_output = state.get("architect_output", {})
        file_tree = state.get("file_tree", {})
        related_code_context = state.get("related_code_context")
        full_files_context = state.get("full_files_context")
        
        architect_str = json.dumps(architect_output, indent=2, ensure_ascii=False)
        file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
        
        # 构建代码上下文部分
        code_context_section = ""
        
        # 第一层：语义检索结果
        if related_code_context:
            code_context_section += f"""
【相关代码片段 - 语义检索结果】
以下是通过 RAG 检索到的与需求相关的代码片段：

{related_code_context}
"""
        
        # 第二层：完整文件内容
        if full_files_context:
            # 【改进2】生成现有函数复用表，强制对齐
            reuse_table = self._build_reuse_table(full_files_context)
            if reuse_table:
                code_context_section += f"""
{reuse_table}

"""
            files_content = []
            for file_path, content in full_files_context.items():
                # 限制每个文件的内容长度，避免超出 token 限制
                max_content_length = 3000  # 约 1000 tokens
                truncated_content = content[:max_content_length]
                if len(content) > max_content_length:
                    truncated_content += f"\n... (文件剩余 {len(content) - max_content_length} 字符已省略)"
                
                files_content.append(f"""--- 文件: {file_path} ---
```python
{truncated_content}
```""")
            
            full_files_str = "\n\n".join(files_content)
            code_context_section += f"""
【完整文件内容】
以下是相关文件的完整内容（用于理解代码风格和架构）：

{full_files_str}
"""
        
        return f"""【ArchitectAgent 输出】
{architect_str}

【项目文件树】
```
{file_tree_str}
```
{code_context_section}

请根据以上信息，输出详细的技术设计方案（JSON 格式）。
注意参考 backend/app/api/ 目录下的现有 API 风格，优先复用现有接口和模式。
"""
    
    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出为字典"""
        return self._parse_json_response(response)
    
    def validate_output(self, output: Dict[str, Any]) -> DesignerOutput:
        """校验输出为 DesignerOutput 模型"""
        return DesignerOutput(**output)
    
    async def design(
        self,
        architect_output: Dict[str, Any],
        file_tree: Dict[str, Any],
        related_code_context: Optional[str] = None,
        full_files_context: Optional[Dict[str, str]] = None,
        pipeline_id: int = 0,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        使用 Instructor 强制执行的结构化设计

        特点：
        1. 使用 Instructor 在 API 层强制约束输出格式为 DesignerOutputV2
        2. contract_alignment 成为必填字段，在 API 层就验证
        3. 无需手动解析 JSON，直接返回校验后的 Pydantic 对象
        4. 生成后自动验证验收标准对齐

        Args:
            architect_output: ArchitectAgent 的输出内容（必须包含 acceptance_criteria）
            file_tree: 项目文件树
            related_code_context: 语义检索结果（代码片段）
            full_files_context: 完整文件内容映射
            pipeline_id: Pipeline ID
            max_retries: Instructor 最大重试次数

        Returns:
            Dict: 包含设计结果或错误信息
        """
        from app.core.sse_log_buffer import push_log
        
        # 记录开始时间
        start_time = time.perf_counter()
        
        await push_log(pipeline_id, "info", "结构化设计师 Agent 开始工作（Instructor 模式）...", stage="DESIGN")
        
        # ========== 1. 前置静态检查 ==========
        acceptance_criteria = architect_output.get("acceptance_criteria", [])
        if not acceptance_criteria:
            error_msg = "Missing acceptance_criteria in architect_output，无法执行契约对齐设计"
            logger.error(f"[DesignerAgent] {error_msg}")
            await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
            return {
                "success": False,
                "error": error_msg,
                "output": None
            }
        
        logger.info(f"[DesignerAgent] 验收标准数量: {len(acceptance_criteria)}")
        await push_log(pipeline_id, "info", f"检测到 {len(acceptance_criteria)} 条验收标准，开始结构化设计...", stage="DESIGN")
        
        # ========== 2. 准备 Prompt ==========
        initial_state = {
            "architect_output": architect_output,
            "file_tree": file_tree,
            "related_code_context": related_code_context,
            "full_files_context": full_files_context
        }
        user_prompt = self.build_user_prompt(initial_state)
        
        # 在 Prompt 中注入验收标准数量提醒
        user_prompt += f"""

【重要提醒】
本次设计必须包含 {len(acceptance_criteria)} 条验收标准的映射（contract_alignment 列表长度必须等于 {len(acceptance_criteria)}）。
"""
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # ========== 3. 创建 Instructor 客户端（使用 TOOLS 模式兼容 MiniMax） ==========
        client = instructor.from_litellm(
            litellm.acompletion,
            mode=Mode.TOOLS  # 使用工具调用模式，兼容不支持 response_format 的模型
        )
        
        # ========== 4. 调用 LLM，强制输出 DesignerOutputV2 ==========
        try:
            logger.info(f"[DesignerAgent] 调用 Instructor 生成结构化输出...")
            await push_log(pipeline_id, "info", "调用 LLM 生成结构化设计方案...", stage="DESIGN")
            
            designer_output = await client.chat.completions.create(
                model=f"openai/{settings.llm_model}",
                messages=messages,
                response_model=DesignerOutputV2,
                temperature=0.0,
                max_retries=max_retries,
                max_tokens=8192,
                api_key=settings.llm_api_key,
                api_base=settings.llm_api_base
            )
            
            logger.info(f"[DesignerAgent] Instructor 输出成功，接口数量: {len(designer_output.interface_specs)}")
            await push_log(
                pipeline_id, 
                "info", 
                f"LLM 输出完成（{len(designer_output.interface_specs)} 个接口，{len(designer_output.contract_alignment)} 个映射）", 
                stage="DESIGN"
            )
            
        except Exception as e:
            error_msg = f"Instructor 结构化输出失败: {str(e)}"
            logger.error(f"[DesignerAgent] {error_msg}", exc_info=True)
            await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
            return {
                "success": False,
                "error": error_msg,
                "output": None
            }
        
        # ========== 5. 生成后对齐校验 ==========
        is_aligned, missing_criteria = self._validate_contract_alignment(
            designer_output, acceptance_criteria
        )
        
        if not is_aligned:
            error_msg = f"契约对齐校验失败，缺失 {len(missing_criteria)} 条验收标准映射: {missing_criteria}"
            logger.error(f"[DesignerAgent] {error_msg}")
            await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
            return {
                "success": False,
                "error": error_msg,
                "output": designer_output.model_dump()
            }
        
        logger.info(f"[DesignerAgent] 契约对齐校验通过，所有 {len(acceptance_criteria)} 条验收标准已映射")
        await push_log(pipeline_id, "info", "✅ 契约对齐校验通过，所有验收标准已映射到接口契约", stage="DESIGN")

        # ========== 6. 【关键修复】验证并自动修正 interface_specs 符号 ==========
        # 确保所有 symbol_name 都是模块级可导入的（类或模块级函数），而不是类方法
        # 如果发现类方法被错误地作为独立符号，自动将其转换为类名
        corrected_specs, correction_log = self._auto_correct_interface_specs(
            designer_output.interface_specs, full_files_context
        )
        if correction_log:
            logger.warning(f"[DesignerAgent] 自动修正契约符号: {correction_log}")
            await push_log(pipeline_id, "warning", f"自动修正契约符号: {correction_log}", stage="DESIGN")
            # 更新 interface_specs 为修正后的版本
            designer_output.interface_specs = corrected_specs

        # 再次验证，确保修正后没有错误
        import_errors = self._validate_interface_specs_importable(
            designer_output.interface_specs, full_files_context
        )
        if import_errors:
            error_msg = f"契约符号不可直接导入（必须是模块级函数或类，不能是类方法）: {import_errors}"
            logger.error(f"[DesignerAgent] {error_msg}")
            await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
            return {
                "success": False,
                "error": error_msg,
                "output": designer_output.model_dump()
            }

        # ========== 7. 【新增】契约-现有代码对齐检查（仅警告，不阻断）==========
        if full_files_context:
            alignment_errors = self._validate_interface_specs_alignment(
                designer_output.interface_specs, full_files_context
            )
            if alignment_errors:
                # 【修改】将错误降级为警告，不阻断流程
                # 因为现有代码可能需要演进，新设计可能与旧实现不同
                warning_msg = f"契约与现有代码存在差异（将作为架构演进处理）: {len(alignment_errors)} 处"
                logger.warning(f"[DesignerAgent] {warning_msg}")
                for err in alignment_errors:
                    logger.warning(f"  - {err['symbol']}: {err['error']}")
                    logger.warning(f"    现有: {err.get('existing_keys', [])}")
                    logger.warning(f"    契约: {err.get('required_keys', [])}")
                await push_log(pipeline_id, "warning", warning_msg, stage="DESIGN")
                # 【重要】将差异信息附加到输出中，供 CoderAgent 参考
                designer_output._alignment_warnings = alignment_errors
            else:
                logger.info("[DesignerAgent] 契约-现有代码对齐检查通过")
                await push_log(pipeline_id, "info", "✅ 契约-现有代码对齐检查通过", stage="DESIGN")
        
        # ========== 7. 返回与原有接口兼容的结果 ==========
        # 计算耗时
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)
        
        return {
            "success": True,
            "output": designer_output.model_dump(),
            "error": None,
            "input_tokens": 0,  # Instructor 暂不直接返回 usage，可从 litellm 全局统计获取
            "output_tokens": 0,
            "duration_ms": duration_ms,
            "total_tokens": 0,
            "interface_specs_count": len(designer_output.interface_specs),
            "contract_alignment_count": len(designer_output.contract_alignment)
        }
    
    def _validate_contract_alignment(
        self,
        output: DesignerOutputV2,
        acceptance_criteria: list
    ) -> tuple[bool, list]:
        """
        检查每条验收标准是否都有对应的接口契约
        
        Args:
            output: DesignerOutputV2 输出
            acceptance_criteria: 验收标准列表
            
        Returns:
            tuple[是否对齐, 缺失的标准列表]
        """
        # 提取已映射的验收标准
        covered = set()
        for item in output.contract_alignment:
            if item.acceptance_criteria:
                covered.add(item.acceptance_criteria.strip())
        
        # 找出未映射的标准
        missing = [c for c in acceptance_criteria if c.strip() not in covered]
        
        if missing:
            logger.warning(f"[DesignerAgent] Missing alignment for criteria: {missing}")
            return False, missing
        
        return True, []
    
    def _build_reuse_table(self, full_files_context: Dict[str, str]) -> str:
        """
        【改进2】从 full_files_context 构建现有函数复用表
        """
        import re
        
        if not full_files_context:
            return ""
        
        lines = ["【现有函数复用表 - 设计时必须参考，优先复用而非创建新函数】\n"]
        
        for file_path, content in full_files_context.items():
            lines.append(f"\n### {file_path}")
            func_pattern = r"(?P<async>async\s+)?def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)(?:\s*->\s*(?P<ret>[^:]+))?:\s*"
            for m in re.finditer(func_pattern, content):
                func_name = m.group("name")
                is_async = "async " if m.group("async") else ""
                params = m.group("params").strip()
                ret_type = m.group("ret").strip() if m.group("ret") else "Any"
                
                # 提取函数返回字典的键名
                return_keys = []
                func_body = content[m.end():]
                brace_match = re.search(r'return\s+\{([^}]*(?:\{[^}]*\}[^}]*)*)\}', func_body, re.DOTALL)
                if brace_match:
                    keys = re.findall(r"['\"](\w+)['\"]\s*:", brace_match.group(1))
                    return_keys = list(dict.fromkeys(keys))[:8]
                
                args_str = params[:80] + ("..." if len(params) > 80 else "")
                lines.append(f"  - {is_async}def {func_name}({args_str}) -> {ret_type}")
                if return_keys:
                    lines.append(f"    return_keys: [{', '.join(return_keys)}]")
        
        return "\n".join(lines)

    def _auto_correct_interface_specs(
        self,
        interface_specs: list,
        full_files_context: Dict[str, str]
    ) -> tuple[list, list]:
        """
        【自动修正】将类方法符号自动转换为类名符号

        问题背景：
        - LLM 可能错误地将类方法（如 HealthService.get_component_health）作为独立符号提取
        - 但类方法不能通过 `from module import symbol` 直接导入
        - 此方法自动将类方法符号替换为类名符号

        修正逻辑：
        1. 对于每个 interface_spec，检查其 symbol_name 是否是某个类的方法
        2. 如果是类方法，将 symbol_name 替换为类名
        3. 在 expected_behavior 中说明实际使用的是类的方法

        Args:
            interface_specs: 接口契约列表
            full_files_context: 完整文件内容映射

        Returns:
            tuple[修正后的契约列表, 修正日志列表]
        """
        import ast
        import copy

        corrected_specs = copy.deepcopy(interface_specs)
        correction_log = []

        for i, spec in enumerate(corrected_specs):
            # 处理 InterfaceSpec 对象或字典
            if hasattr(spec, 'symbol_name'):
                symbol_name = spec.symbol_name
                module = spec.module
                is_object = True
            else:
                symbol_name = spec.get("symbol_name", "")
                module = spec.get("module", "")
                is_object = False

            if not symbol_name or not module:
                continue

            # 标准化模块路径
            clean_module = module.replace("backend/", "").replace("backend\\", "").lstrip("/")
            if not clean_module.endswith(".py"):
                clean_module += ".py"

            # 查找对应的文件内容
            file_content = None
            for path, content in full_files_context.items():
                path_clean = path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                if path_clean == clean_module or path_clean == clean_module.replace(".py", ""):
                    file_content = content
                    break

            if not file_content:
                # 文件不在上下文中，可能是新文件，跳过
                continue

            try:
                tree = ast.parse(file_content)

                # 检查符号是否是模块级可导入的
                is_module_level = False
                is_class_method = False
                parent_class = None
                method_signature = ""

                for node in tree.body:
                    # 检查是否是模块级函数或类
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol_name:
                        is_module_level = True
                        break
                    elif isinstance(node, ast.ClassDef) and node.name == symbol_name:
                        is_module_level = True
                        break

                # 如果不是模块级的，检查是否是类方法
                if not is_module_level:
                    for node in tree.body:
                        if isinstance(node, ast.ClassDef):
                            for item in node.body:
                                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                    if item.name == symbol_name:
                                        is_class_method = True
                                        parent_class = node.name
                                        # 提取方法签名
                                        args = [arg.arg for arg in item.args.args]
                                        method_signature = f"def {symbol_name}({', '.join(args)})"
                                        break
                        if is_class_method:
                            break

                # 如果是类方法，自动修正为类名
                if is_class_method and parent_class:
                    old_symbol = symbol_name
                    new_symbol = parent_class

                    if is_object:
                        spec.symbol_name = new_symbol
                        # 更新 expected_behavior 说明实际使用的是类的方法
                        old_behavior = spec.expected_behavior or ""
                        spec.expected_behavior = f"使用类 {parent_class} 的 {old_symbol} 方法。{old_behavior}"
                        # 更新 signature 为类定义
                        spec.signature = f"class {parent_class}:"
                    else:
                        spec["symbol_name"] = new_symbol
                        # 更新 expected_behavior 说明实际使用的是类的方法
                        old_behavior = spec.get("expected_behavior", "")
                        spec["expected_behavior"] = f"使用类 {parent_class} 的 {old_symbol} 方法。{old_behavior}"
                        # 更新 signature 为类定义
                        spec["signature"] = f"class {parent_class}:"

                    correction_log.append(
                        f"'{old_symbol}' -> '{new_symbol}' (类方法转为类名)"
                    )

            except SyntaxError:
                # 文件有语法错误，跳过
                continue

        return corrected_specs, correction_log

    def _validate_interface_specs_importable(
        self,
        interface_specs: list,
        full_files_context: Dict[str, str]
    ) -> list:
        """
        【关键修复】验证 interface_specs 中的符号是否都是模块级可导入的

        问题背景：
        - DesignerAgent 可能错误地将类方法（如 HealthService.get_component_health）记录为契约符号
        - 但类方法不能通过 `from module import symbol` 直接导入
        - 这会导致 TesterAgent 生成错误的 import 语句，引发 ImportError

        验证逻辑：
        1. 对于每个 interface_spec，检查其 symbol_name 是否存在于对应模块的顶层
        2. 如果 symbol_name 是类名（如 HealthService），允许
        3. 如果 symbol_name 是模块级函数，允许
        4. 如果 symbol_name 实际上是某个类的方法，拒绝并返回错误

        Args:
            interface_specs: 接口契约列表
            full_files_context: 完整文件内容映射

        Returns:
            list: 错误列表，空列表表示所有符号都可导入
        """
        import ast
        errors = []

        for spec in interface_specs:
            # 处理 InterfaceSpec 对象或字典
            if hasattr(spec, 'symbol_name'):
                symbol_name = spec.symbol_name
                module = spec.module
            else:
                symbol_name = spec.get("symbol_name", "")
                module = spec.get("module", "")

            if not symbol_name or not module:
                continue

            # 标准化模块路径
            clean_module = module.replace("backend/", "").replace("backend\\", "").lstrip("/")
            if not clean_module.endswith(".py"):
                clean_module += ".py"

            # 查找对应的文件内容
            file_content = None
            for path, content in full_files_context.items():
                path_clean = path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                if path_clean == clean_module or path_clean == clean_module.replace(".py", ""):
                    file_content = content
                    break

            if not file_content:
                # 文件不在上下文中，可能是新文件，跳过验证
                continue

            try:
                tree = ast.parse(file_content)

                # 检查符号是否是模块级可导入的
                is_module_level = False
                is_class_method = False
                parent_class = None

                for node in tree.body:
                    # 检查是否是模块级函数或类
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol_name:
                        is_module_level = True
                        break
                    elif isinstance(node, ast.ClassDef) and node.name == symbol_name:
                        is_module_level = True
                        break

                # 如果不是模块级的，检查是否是类方法
                if not is_module_level:
                    for node in tree.body:
                        if isinstance(node, ast.ClassDef):
                            for item in node.body:
                                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                    if item.name == symbol_name:
                                        is_class_method = True
                                        parent_class = node.name
                                        break
                        if is_class_method:
                            break

                if is_class_method:
                    errors.append({
                        "symbol": symbol_name,
                        "module": module,
                        "error": f"'{symbol_name}' 是类 '{parent_class}' 的方法，不是模块级符号",
                        "suggestion": f"应该改为导出类 '{parent_class}'，或者将 '{symbol_name}' 改为模块级函数"
                    })

            except SyntaxError:
                # 文件有语法错误，跳过验证
                continue

        return errors

    def _validate_interface_specs_alignment(
        self,
        interface_specs: list,
        full_files_context: Dict[str, str]
    ) -> list:
        """
        【契约-现有代码对齐检查器】
        检查 interface_specs 是否与现有代码一致
        
        检查项：
        1. 函数名是否已存在但签名不同
        2. 返回字段的键名是否与现有代码一致
        
        Args:
            interface_specs: 接口契约列表
            full_files_context: 完整文件内容映射
            
        Returns:
            list: 对齐错误列表，空列表表示无错误
        """
        import re
        errors = []
        
        for spec in interface_specs:
            # 处理 InterfaceSpec 对象或字典
            if hasattr(spec, 'symbol_name'):
                symbol_name = spec.symbol_name
                module = spec.module
                return_fields = spec.return_fields if spec.return_fields else []
            else:
                symbol_name = spec.get("symbol_name", "")
                module = spec.get("module", "")
                return_fields = spec.get("return_fields", [])
            
            if not symbol_name or not module:
                continue
            
            # 标准化模块路径
            clean_module = module.replace("backend/", "").replace("backend\\", "").lstrip("/")
            if not clean_module.endswith(".py"):
                clean_module += ".py"
            
            # 查找对应的文件内容
            file_content = None
            for path, content in full_files_context.items():
                path_clean = path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                if path_clean == clean_module or path_clean == clean_module.replace(".py", ""):
                    file_content = content
                    break
            
            if not file_content:
                continue
            
            # 检查函数是否已存在
            # 匹配函数定义：async def symbol_name( 或 def symbol_name(
            func_pattern = rf"(?:async\s+)?def\s+{re.escape(symbol_name)}\s*\("
            if re.search(func_pattern, file_content):
                # 函数已存在，检查返回字段是否一致
                if return_fields:
                    # 提取现有函数返回的字典键名
                    # 匹配 return { ... } 语句
                    return_pattern = rf"(?:async\s+)?def\s+{re.escape(symbol_name)}\s*\([^)]*\)(?:\s*->\s*[^:]+)?:\s*(?:[^#]*#.*\n|[^\n]*\n)+?(?:\s*return\s+\{{([^}}]+)\}})"
                    match = re.search(return_pattern, file_content, re.MULTILINE | re.DOTALL)
                    
                    if match:
                        # 提取现有返回字典中的键名
                        return_dict_content = match.group(1)
                        existing_keys = set(re.findall(r"['\"](\w+)['\"]\s*:", return_dict_content))
                        
                        # 提取契约要求的键名（处理 ReturnFieldSpec 对象或字典）
                        def get_field_name(f):
                            return f.name if hasattr(f, 'name') else f.get("name", "")
                        def get_field_required(f):
                            return f.required if hasattr(f, 'required') else f.get("required", True)
                        required_keys = set(get_field_name(f) for f in return_fields if get_field_required(f))
                        
                        # 检查是否有冲突
                        if existing_keys and required_keys:
                            # 如果有共同键名但可能值不同，记录警告
                            common_keys = existing_keys & required_keys
                            if common_keys:
                                logger.info(f"[DesignerAgent] 函数 {symbol_name} 已存在，键名一致: {common_keys}")
                            else:
                                # 键名完全不匹配，可能是不同的返回结构
                                logger.warning(
                                    f"[DesignerAgent] 函数 {symbol_name} 已存在但返回键名不匹配: "
                                    f"现有 {existing_keys} vs 契约要求 {required_keys}"
                                )
                                errors.append({
                                    "symbol": symbol_name,
                                    "module": module,
                                    "error": f"函数已存在但返回键名不匹配",
                                    "existing_keys": list(existing_keys),
                                    "required_keys": list(required_keys),
                                    "suggestion": f"请检查现有代码，复用已有的键名 {list(existing_keys)} 或扩展现有函数"
                                })
        
        return errors


# 单例实例
designer_agent = DesignerAgent()
