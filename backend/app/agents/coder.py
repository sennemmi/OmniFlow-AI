"""
编码 Agent
基于 LangGraphAgent 实现，纯代码生成，不持有任何工具

职责：
1. 分析 DesignerAgent 的技术方案
2. 基于上游注入的文件内容生成代码变更
3. 输出 JSON 格式的 search_block/replace_block 变更

【改造】从 ToolUsingAgent 迁移到 LangGraphAgent
- 不再直接调用工具（glob/grep/read_file/replace_lines）
- 所需文件内容由上游（ArchitectAgent）预读后注入到 state 中
- 纯 LLM 生成，只输出 JSON 格式的变更描述
"""

import ast
import json
import logging
from typing import Dict, Optional, Any, List

from app.agents.base import LangGraphAgent
from app.agents.schemas import CoderOutput
from app.agents.project_card_builder import ProjectCardBuilder, get_conventions_for_agent

logger = logging.getLogger(__name__)


class CoderAgent(LangGraphAgent[CoderOutput]):
    """
    编码 Agent

    根据设计方案生成代码变更
    继承 LangGraphAgent，纯代码生成，不持有任何工具
    所需文件内容由上游（ArchitectAgent）预读后注入到 state 中
    """

    # 【结构化输出】启用 JSON 格式化输出
    USE_JSON_FORMAT = True

    def __init__(self):
        super().__init__(agent_name="CoderAgent")

    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调纯 JSON 输出和契约强制"""
        # 【软编码】从 CONVENTIONS.md 加载项目约定
        conventions = get_conventions_for_agent()

        # 构建约定部分
        if conventions:
            conventions_section = conventions + "\n\n---\n"
        else:
            conventions_section = ""
        
        # 使用字符串拼接避免 f-string 嵌套问题
        base_prompt = """你是 OmniFlowAI 的编码 Agent，负责生成代码变更。

"""
        base_prompt += conventions_section
        base_prompt += """
【绝对契约 - 不可违反，违反将导致工作被拒绝】
1. 你必须严格实现技术方案中 interface_specs 声明的所有函数/类及其签名。
2. 如果一个类或函数在契约中声明了，你绝对不能遗漏它。哪怕需要新建文件，也必须创建。
3. 你需要生成的文件列表必须在数量上 >= interface_specs 中涉及的文件数量。
4. 不要假设某个函数"已经存在所以不用生成了"，合约里有的，你都要保证它出现在你输出的代码变更中。
5. 如果契约要求新建类或函数，即使现有代码中有类似功能，也必须按照契约实现，不能偷懒修改旧代码。
6. **任何一项契约缺失都将导致你的工作被拒绝，不会进入测试阶段**。

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

【模块导出契约 - 绝对禁止违反】
以下核心模块的公共 API **绝对禁止删除或重命名**，只能追加新功能：

1. **app/core/database.py**：
   - 禁止删除 `get_session` 函数（被大量文件依赖）
   - 禁止修改 `engine` 或 `async_session_factory` 的创建逻辑
   - 可以追加新的数据库工具函数

2. **app/core/response.py**：
   - 禁止删除 `success_response` 或 `error_response` 函数
   - 禁止修改 `ResponseModel` 的定义

3. **app/core/config.py**：
   - 禁止删除 `settings` 对象

违反上述契约会导致系统级错误，你的修改会被拒绝！

【错误处理铁律 - 强制使用统一响应函数】
所有 API 端点必须使用 `success_response` 和 `error_response` 函数返回响应，禁止手动构建字典！

【铁律 - 返回类型注解】
所有 API 端点函数必须声明返回类型为 `ResponseModel`：`async def xxx(...) -> ResponseModel:`
禁止使用 `-> dict`、`-> Any` 或无返回类型注解！这是导致 FastAPI 响应校验失败的直接原因。

【关键 - 错误响应必须设置 HTTP 状态码】
当返回错误响应时，必须使用 `JSONResponse` 包装并设置正确的 HTTP 状态码（如 500, 400, 404 等）：

正确示例1 - 健康检查 API（带状态码）：
```python
from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.response import success_response, error_response

@router.get("/health")
async def health_check(request: Request) -> ResponseModel:  # 【必须引入 request 以获取 request_id】
    request_id = getattr(request.state, "request_id", "")
    try:
        status = await check_system()
        return success_response(data=status, request_id=request_id)
    except Exception as e:
        # 【关键】错误响应必须设置 HTTP 状态码 500
        error_data = error_response(error=f"健康检查失败: {str(e)}", request_id=request_id)
        return JSONResponse(status_code=500, content=error_data.dict())
```

正确示例2 - 用户 API（带状态码）：
```python
from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.response import success_response, error_response

@router.get("/users/{user_id}")
async def get_user(user_id: int, request: Request) -> ResponseModel:
    request_id = getattr(request.state, "request_id", "")
    try:
        user = await user_service.get_by_id(user_id)
        if not user:
            # 404 错误
            error_data = error_response(error="用户不存在", request_id=request_id)
            return JSONResponse(status_code=404, content=error_data.dict())
        return success_response(data=user, request_id=request_id)
    except Exception as e:
        # 500 错误
        error_data = error_response(error=f"获取用户失败: {str(e)}", request_id=request_id)
        return JSONResponse(status_code=500, content=error_data.dict())
```

正确示例3 - 时间戳 API：
```python
from fastapi import Request
from app.core.response import success_response, error_response
from datetime import datetime

@router.get("/timestamp")
async def get_timestamp(request: Request) -> ResponseModel:  # 【必须引入 request 以获取 request_id】
    request_id = getattr(request.state, "request_id", "")
    try:
        return success_response(data={
            "timestamp": datetime.now().timestamp(),
            "iso_format": datetime.now().isoformat()
        }, request_id=request_id)
    except Exception as e:
        return error_response(error=f"获取时间戳失败: {str(e)}", request_id=request_id)
```

错误示例（绝对禁止）：
```python
# ❌ 错误！手动构建响应字典
@router.get("/health")
async def health_check():
    return {{"success": True, "data": status}}  # 禁止！

# ❌ 错误！直接返回原始数据
@router.get("/health")
async def health_check():
    return status  # 禁止！
```

【代码完整性铁律 - 违反会导致系统错误】
1. **所有使用的变量必须先定义后使用** — 这是 Python 最基本规则
   - 例如 `app.include_router(...)` 必须放在 `app = FastAPI(...)` 之后，不能在 import 段直接调用
   - 当同时添加 import 和函数调用时，import 放在文件顶部 import 段，函数调用放在对应的变量定义之后
2. **所有装饰器必须在导入和初始化之后**
3. **文件必须包含完整的导入语句**
4. **使用到的每个对象都必须有明确的来源**

【Import 铁律】
所有业务代码文件必须使用如下 import 方式：
  from app.core.database import get_session
  from app.models.user import User
  from app.service.user import UserService

绝对不允许使用以下错误的 import 方式：
  from core.database import get_session     # ❌ 错误！缺少 app 前缀

【依赖注入铁律 - 强制使用 FastAPI Depends】
所有服务依赖必须通过 FastAPI 的 Depends 注入，绝对禁止使用全局变量或手动实例化！

正确示例1 - 健康检查服务：
```python
from fastapi import Depends
from app.service.health import HealthService
from app.core.database import get_session

@router.get("/health")
async def health_check(
    health_service: HealthService = Depends(),
    session: AsyncSession = Depends(get_session)
):
    return await health_service.check()
```

正确示例2 - 用户服务：
```python
from fastapi import Depends
from app.service.user import UserService
from app.core.database import get_session

@router.get("/users/{{user_id}}")
async def get_user(
    user_id: int,
    user_service: UserService = Depends(),
    session: AsyncSession = Depends(get_session)
):
    return await user_service.get_by_id(user_id)
```

正确示例3 - 时间戳服务：
```python
from fastapi import APIRouter, Depends
from app.service.timestamp import TimestampService

timestamp_router = APIRouter()

@timestamp_router.get("/timestamp")
async def get_timestamp(
    ts_service: TimestampService = Depends()
):
    return await ts_service.get_current()
```

错误示例（绝对禁止）：
```python
# ❌ 错误！使用全局变量
health_service = HealthService()

@router.get("/health")
async def health_check():
    return await health_service.check()  # 全局变量

# ❌ 错误！手动实例化
@router.get("/health")
async def health_check():
    service = HealthService()  # 手动实例化
    return await service.check()
```

【测试修复铁律】
你只能修改 backend/app/ 下的源代码。
绝对不能修改 tests/ 目录下任何已存在的测试文件。

【数据键名参考库 - 必须使用这些标准键名，禁止随意发明】
当函数需要返回字典数据时，必须使用以下标准键名，确保与项目其他部分保持一致：

1. **磁盘使用 (disk_usage)** 返回字段：
   - `total_gb`: float - 总容量（GB）
   - `used_gb`: float - 已使用容量（GB）
   - `free_gb`: float - 剩余容量（GB）
   - `usage_percent`: float - 使用百分比（0-100）
   - ❌ 禁止使用: `used_percent`, `percent`, `disk_percent` 等非标准键名

2. **内存使用 (memory)** 返回字段：
   - `total_mb`: int - 总内存（MB）
   - `used_mb`: int - 已使用内存（MB）
   - `available_mb`: int - 可用内存（MB）
   - `usage_percent`: float - 使用百分比（0-100）
   - ❌ 禁止使用: `used_percent`, `percent_used`, `memory_percent` 等非标准键名

3. **数据库状态 (database)** 返回字段：
   - `status`: str - 状态（"healthy"/"unhealthy"/"degraded"）
   - `response_time_ms`: float - 响应时间（毫秒）
   - `connection_count`: int - 当前连接数（可选）
   - `error`: str - 错误信息（如果有）

4. **健康检查 (health)** 返回字段：
   - `status`: str - 整体状态（"healthy"/"unhealthy"/"degraded"）
   - `health_score`: int - 健康度评分（0-100）
   - `components`: dict - 各组件状态详情
   - `timestamp`: str - ISO格式时间戳

【键名一致性检查清单】
在输出代码前，请检查：
□ 如果返回磁盘使用数据，键名是否为 usage_percent（不是 used_percent）？
□ 如果返回内存使用数据，键名是否为 usage_percent（不是 used_percent）？
□ 所有键名是否与上述参考库一致？
□ 是否存在拼写错误或使用了非标准键名？

违反键名规范会导致 KeyError 错误和测试失败！

【⚠️ 修改已有函数时的强制规则 - 极其重要】
如果你修改的代码块是一个已存在的函数，且契约要求它返回的字典中包含原本**没有**的字段（如 health_score、health_status）：

1. **你必须在 replace_block 中成功添加这些缺少的字段，哪怕原函数没有！**
2. **禁止**因为原代码缺少这些字段就省略它们。如果遗漏，你的输出会被静态检查直接拒绝。
3. **这是强制性要求，不是可选优化！** 遗漏字段会导致你的工作被立即拒绝，不会进入测试阶段。

添加字段的具体方法（三选一）：

方法A：直接在 return 语句中添加新键值对（推荐）
```python
# 原函数返回（缺少 health_status 和 health_score）
return {
    "status": status,
    "response_time_ms": response_time,
    "message": "Database connection successful"
}

# 修改后（必须追加缺失字段）
return {
    "status": status,
    "response_time_ms": response_time,
    "message": "Database connection successful",
    "health_status": "healthy" if status == "up" else "unhealthy",  # 【强制添加】
    "health_score": 100 if status == "up" else 0                   # 【强制添加】
}
```

方法B：使用变量组装后返回
```python
result = {
    "status": status,
    "response_time_ms": response_time,
    "message": "Database connection successful"
}
# 【强制】追加契约要求的字段
result["health_status"] = "healthy" if status == "up" else "unhealthy"
result["health_score"] = 100 if status == "up" else 0
return result
```

方法C：使用 dict.update()
```python
result = {
    "status": status,
    "response_time_ms": response_time,
    "message": "Database connection successful"
}
# 【强制】批量追加契约字段
result.update({
    "health_status": "healthy" if status == "up" else "unhealthy",
    "health_score": 100 if status == "up" else 0
})
return result
```

【检查清单 - 输出前必须确认】
□ 我是否检查了 interface_specs 中所有函数的 return_fields？
□ 每个返回字典是否包含了所有必需的字段？
□ 特别是 health_status 和 health_score 是否已添加？
□ 我是否因为"原函数没有这些字段"而省略了它们？（如果是，立即修正！）

【错误示例 - 会导致验证失败】
```python
# ❌ 致命错误！遗漏了 health_status 和 health_score
return {
    "status": status,
    "response_time_ms": response_time,
    "message": "Database connection successful"
}
```

【后果警告】
如果静态检查发现你遗漏了任何 return_fields 中声明的字段：
- 你的工作会被立即拒绝
- 不会进入测试阶段
- 必须重新生成直到字段完整

不要试图省略字段来"保持简洁"，契约完整性是第一优先级！

【强制完整文件覆盖信号】
如果 design_output 中包含 "force_full_file": true，请使用 change_type: "add" 直接输出完整文件内容，而不是 search_block + replace_block。

【输出格式 - 极其重要】
你必须直接输出纯 JSON 格式，不要包含任何其他文本、解释或标记。
输出必须是一个有效的 JSON 对象。

【关键】search_block 和 replace_block 中的换行符：
- 使用实际的换行符（按 Enter 键），不是 \\n 字符串
- 确保代码块的每一行都有正确的缩进
- 代码块末尾应该有换行符，除非这是文件的最后一行

正确示例（注意：这是多行格式，不是单行）：
{
  "files": [{
    "file_path": "app/api/v1/health.py",
    "change_type": "modify",
    "search_block": "def health_check():\n    return {\"status\": \"ok\"}",
    "replace_block": "def health_check():\n    db_status = await check_db()\n    return {\"status\": \"ok\", \"db\": db_status}",
    "description": "添加数据库状态检查"
  }]
}

错误示例（不要这样输出）：
- 不要添加 ```json 标记
- 不要添加解释文本
- 不要输出 "我需要先分析..." 等思考过程
- 不要在 JSON 中使用 \\n 字符串代替实际换行符
- 只输出纯 JSON

【强制要求】
- 直接输出 JSON，不要有任何前缀或后缀
- 确保 JSON 格式完整有效
- 不要输出任何其他内容

【字段说明】
- files: 变更文件列表
  - file_path: 文件相对路径
  - change_type: 变更类型 (add/modify/delete)
  - search_block: 要替换的旧代码块（精确匹配）
  - replace_block: 新代码块
  - content: 完整文件内容（当 modify 难以精准匹配时使用）
  - description: 改动说明
- summary: 变更摘要

【modify vs add 选择策略】
1. 优先使用 modify (search_block + replace_block) 进行精准修改
2. **【关键规则】同一文件需要修改多个不连续位置时，必须为每个修改点输出独立的 files 条目**
   例如 main.py 需要同时：①在文件顶部 import 段添加一行，②在文件底部路由注册段添加一行 →
   必须输出 2 个 {"file_path": "backend/main.py", "change_type": "modify", ...} 条目，分别处理各自位置
   ❌ 绝对禁止将两个不连续位置的修改合并到一个 replace_block 中
3. 对于小文件（<200行），如果 modify 复杂，直接用 add 返回完整内容更可靠
4. **【重要限制】如果文件超过 300 行，禁止使用 add 模式输出完整内容**（会导致 Token 溢出和 JSON 截断）
5. 对于长文件（>300行），必须使用 modify 模式，每个 files 条目只修改 3-10 行，必要时拆分为多个条目

正确示例（modify - 精准替换）：
```json
{"files": [{"file_path": "app/api/v1/health.py", "change_type": "modify", "search_block": "def health_check():\n    return {\"status\": \"ok\"}", "replace_block": "def health_check():\n    return {\"status\": \"ok\", \"health_score\": 95}", "description": "添加 health_score 字段"}]}
```

正确示例（add - 完整覆盖，适用于小文件或复杂修改）：
```json
{"files": [{"file_path": "app/utils/system_monitor.py", "change_type": "add", "content": "# 完整文件内容...", "description": "完整更新系统监控模块"}]}
```

【新增工具 - code_apply(用于验证 search_block 精确性)】
在输出最终的 JSON 之前,你可以先调用 `code_apply` 工具验证 search_block 是否能精确匹配:

使用流程:
1. read_file 读取目标文件内容
2. 调用 code_apply(file_path, search_block, replace_block) 进行试替换
3. 如果 code_apply 返回 success: true,说明 search_block 精确,可以输出 JSON
4. 如果 code_apply 返回错误,根据错误信息修正 search_block,再次尝试

【重要】code_apply 工具仅用于验证,不会实际修改文件！
验证成功后,你仍然必须输出完整的 JSON 格式,包含所有 files。
E2E 测试脚本会读取你的 JSON 输出并调用 _apply_coder_result 来实际写入文件。

【注意】code_apply 只做精确匹配,不做模糊匹配！
如果 search_block 与文件内容不完全一致,它会告诉你原因和建议。

【最终输出要求】
无论是否使用了 code_apply 工具验证,最后都必须输出标准 JSON 格式:
{"files": [...], "summary": "..."}
"""
        
        return base_prompt

    def _build_interface_specs_section(self, design_output: Dict[str, Any]) -> str:
        """
        构建接口契约清单部分

        从 design_output 中提取 interface_specs，生成 Prompt 中的契约说明
        【修复】现在包含 return_fields 要求
        """
        interface_specs = design_output.get("interface_specs", [])
        if not interface_specs:
            return ""

        specs_lines = []
        for spec in interface_specs:
            # 处理 InterfaceSpec 对象或字典
            if hasattr(spec, 'symbol_name'):
                symbol = spec.symbol_name
                module = spec.module
                signature = spec.signature
                behavior = spec.expected_behavior
                return_fields = spec.return_fields if spec.return_fields else []
            else:
                symbol = spec.get('symbol_name', '')
                module = spec.get('module', '')
                signature = spec.get('signature', '')
                behavior = spec.get('expected_behavior', '')
                return_fields = spec.get('return_fields', [])

            specs_lines.append(f"  - {symbol} in {module}: {signature}")
            if behavior:
                specs_lines.append(f"    行为: {behavior}")

            # 【修复】添加 return_fields 要求
            if return_fields:
                specs_lines.append("    【必须返回的字段 - 遗漏会导致测试失败】")
                for field in return_fields:
                    if hasattr(field, 'name'):
                        field_name = field.name
                        field_type = field.type
                        field_desc = field.description or ""
                        field_required = field.required
                    else:
                        field_name = field.get('name', '')
                        field_type = field.get('type', '')
                        field_desc = field.get('description', '')
                        field_required = field.get('required', True)

                    required_mark = "(必填)" if field_required else "(可选)"
                    specs_lines.append(f"      - {field_name}: {field_type} {required_mark} {field_desc}")

        specs_str = "\n".join(specs_lines)

        return f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         【⚠️ 绝对契约 - 返回字段列表 - 遗漏将导致工作被拒绝】                    ║
╚══════════════════════════════════════════════════════════════════════════════╝

{specs_str}

【⚠️ 绝对契约 - 返回字段强制性要求】
1. 上面的 return_fields 是**强制性要求**，即使现有代码中没有这些字段，也必须添加到返回的字典中！
2. 如果你修改的是已存在的函数，请在原有返回字典中**追加缺失的字段**，而不是只返回原有的内容。
3. 返回的键名必须与契约完全一致，包括大小写。
4. **任何字段遗漏都将导致验证失败，你的工作会被拒绝！**

正确示例（追加字段到现有返回）：
```python
# 原有代码
def check_health():
    return {{"status": "ok"}}  # 缺少 health_status 和 health_score

# 修改后（追加缺失字段）
def check_health():
    return {{
        "status": "ok",
        "health_status": "healthy",  # 【新增】必须包含
        "health_score": 95           # 【新增】必须包含
    }}
```

错误示例（遗漏字段）：
```python
# ❌ 错误！遗漏了 health_status 和 health_score
def check_health():
    return {{"status": "ok"}}
```

【契约强制要求 - 违反会导致测试失败】
1. ✅ 必须实现上述清单中的每一个符号（函数/类）
2. ✅ 函数签名必须与清单完全一致（包括参数名、类型注解、async 标记）
3. ✅ 【极其重要】返回字典必须包含上述列出的所有【必须返回的字段】，键名必须完全一致
4. ✅ 如果契约要求新建文件，必须创建（不能只在已有文件上修改）
5. ✅ 不要假设某个函数"已存在"，契约里有的都要实现
6. ❌ 遗漏任何契约中的符号或返回字段都会导致测试失败和修复循环

【实现检查清单】
在输出 JSON 前，请逐一检查：
□ 是否实现了契约中的所有函数？
□ 是否实现了契约中的所有类？
□ 函数签名是否与契约一致？
□ 【极其重要】返回字典是否包含所有【必须返回的字段】？
□ 返回字段的键名是否与契约完全一致（如 overall_health_score 不能写成 overall）？
□ 是否创建了契约中要求的新文件？
"""

    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt

        Args:
            state: 包含 design_output, injected_files, error_context 的状态
        """
        design_output = state.get("design_output", {})
        error_context = state.get("error_context")

        design_str = json.dumps(design_output, indent=2, ensure_ascii=False)

        # 【常驻基础设施上下文】注入地基代码
        evergreen_context = state.get("evergreen_context", "")
        evergreen_section = f"""
{evergreen_context}

""" if evergreen_context else ""

        # 【接口契约】生成契约清单部分
        interface_specs_section = self._build_interface_specs_section(design_output)

        # 【核心改造】使用上游注入的文件内容，不再让 LLM 自己读取
        injected_files: Dict[str, str] = state.get("injected_files", {})
        
        # 【调试】记录 injected_files 信息
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[CoderAgent] 接收到的 injected_files: {len(injected_files)} 个文件")
        for path in injected_files.keys():
            content = injected_files[path]
            if content is None:
                logger.warning(f"[CoderAgent]   - {path}: 内容为空 (None)")
            else:
                content_len = len(content)
                logger.info(f"[CoderAgent]   - {path}: {content_len} 字符")

        files_section = ""
        if injected_files:
            files_section = "\n【已存在文件列表 - 这些文件已存在，必须使用 change_type=\"modify\"】\n"
            files_section += "文件路径列表：\n"
            for path in injected_files.keys():
                files_section += f"  - {path} (已存在，使用 modify)\n"

            files_section += "\n【文件现有内容 - search_block 必须从这里精确复制】\n"
            for path, content in injected_files.items():
                # 【修复】跳过 None 内容的文件
                if content is None:
                    logger.warning(f"[CoderAgent] injected_files 中的文件内容为空，跳过: {path}")
                    continue
                # 限制每个文件最多 150 行，避免 prompt 过长
                lines = content.splitlines()
                shown = "\n".join(lines[:150])
                truncated = f"\n... (共{len(lines)}行，已截断)" if len(lines) > 150 else ""
                files_section += f"\n### {path}\n```python\n{shown}{truncated}\n```\n"
        else:
            files_section = "\n⚠️ 警告：未提供文件内容，请确保 search_block 与实际文件完全一致\n"

        prompt = f"""{evergreen_section}【技术设计方案】
{design_str}
{interface_specs_section}
{files_section}

请根据设计方案，对上述文件输出 JSON 格式的 search_block/replace_block 变更。
不要输出任何解释，只输出 JSON。

【change_type 选择规则 - 极其重要】
1. **如果文件在【已存在文件列表】中，必须使用 change_type="modify"**
2. **只有真正的新文件（不在上述列表中）才使用 change_type="add"**
3. modify 文件需要 search_block（从文件内容中精确复制）
4. add 文件不需要 search_block，直接提供 content

【search_block/replace_block 格式说明】
1. **search_block: 必须从上方【文件现有内容】中精确复制**，禁止猜测或编造
2. replace_block: 替换后的新代码块
3. 必须保持原有的缩进和换行

【⚠️ 关键警告 - 违反会导致写入失败】
- **injected_files 中的文件都是已存在的，必须用 modify，禁止用 add**
- search_block 必须与文件现有内容**完全一致**（包括空格、换行、注释）
- **绝对禁止在 search_block 中使用 "..." 省略号** - 必须复制完整的代码块
- **绝对禁止在 search_block 中使用 "# ..." 或 "// ..." 等省略标记**
- 如果不确定文件内容，请只修改你确定的部分
- 错误的 search_block 会导致写入失败

【示例】
如果文件内容是：
```python
def hello():
    print("hello")
```

要修改为：
```python
def hello():
    print("hello world")
```

则输出：
```json
{{
  "files": [
    {{
      "file_path": "app/example.py",
      "change_type": "modify",
      "search_block": "def hello():\\n    print(\"hello\")",
      "replace_block": "def hello():\\n    print(\"hello world\")",
      "description": "修改问候语"
    }}
  ],
  "summary": "修改问候语"
}}
```
"""

        # 如果有报错上下文，注入到 Prompt 头部，强制 Agent 进入修复模式
        if error_context:
            prompt = f"""【！！！修复任务！！！】
你之前的代码在执行测试时失败了。以下是 pytest 的报错信息：

```text
{error_context}
```

请仔细分析报错原因（是语法错误、逻辑错误还是测试用例不匹配），并给出修复后的完整代码。

**修复要求**：
1. 基于上述文件内容生成正确的 search_block 和 replace_block
2. 确保修复后的代码能通过测试
3. 只输出 JSON 格式的变更

---

{prompt}"""

        return prompt

    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出为字典"""
        return self._parse_json_response(response)

    def validate_output(self, output: Dict[str, Any]) -> CoderOutput:
        """
        校验输出为 CoderOutput 模型

        处理 AI 可能返回的各种格式（容错）：
        - 列表格式: [{...}, {...}] → {"files": [...]}
        - 单个对象: {...} → {"files": [{...}]}
        - 标准格式: {"files": [...]}
        """
        # 如果 output 是列表，将其包装为 CoderOutput 的 files 字段
        if isinstance(output, list):
            logger.warning(f"CoderAgent output is a list, auto-wrapping to CoderOutput format")
            output = {"files": output}

        # 如果 output 是单个文件对象（有 file_path 但没有 files 字段），包装为列表
        elif isinstance(output, dict):
            if "files" not in output and "file_path" in output:
                logger.warning(f"CoderAgent output is a single file object, auto-wrapping to files list")
                output = {"files": [output]}

            # 如果 output 缺少 files 字段但有其他列表字段，尝试适配
            elif "files" not in output and any(isinstance(v, list) for v in output.values()):
                # 找到列表类型的值，假设它是 files
                for key, value in output.items():
                    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                        if "file_path" in value[0] if value else False:
                            logger.warning(f"CoderAgent output missing 'files' key, using '{key}' as files")
                            output = {"files": value}
                            break

        # 兼容 SearchReplaceChange 格式：将 search_block/replace_block 映射到标准格式
        if isinstance(output, dict) and "files" in output:
            files = output["files"]
            if isinstance(files, list):
                for f in files:
                    if isinstance(f, dict):
                        # 如果存在 search_block，说明是 SearchReplaceChange 格式
                        if f.get("search_block"):
                            # 保持原有字段，确保兼容性
                            pass
                        # 兼容旧格式：将 start_line/end_line 映射到 fallback 字段
                        elif f.get("start_line") and not f.get("fallback_start_line"):
                            f["fallback_start_line"] = f.get("start_line")
                            f["fallback_end_line"] = f.get("end_line")

        return CoderOutput(**output)

    async def generate_code(
        self,
        design_output: Dict[str, Any],
        pipeline_id: Optional[int] = None,
        error_context: Optional[str] = None,
        injected_files: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        根据设计方案生成代码

        【改造】CoderAgent 现在是纯代码生成器，不直接调用工具
        所需文件内容由上游（ArchitectAgent）预读后通过 injected_files 注入

        Args:
            design_output: DesignerAgent 的输出内容（包含 affected_files 列表）
            pipeline_id: Pipeline ID，用于日志记录
            error_context: 测试失败的错误上下文（用于修复模式）
            injected_files: 上游预读取的文件内容 {path: content}

        Returns:
            Dict: 包含生成结果或错误信息
        """
        from app.core.sse_log_buffer import push_log

        affected_files = design_output.get("affected_files", [])
        logger.info(f"CoderAgent 开始生成代码", extra={
            "pipeline_id": pipeline_id,
            "affected_files_count": len(affected_files),
            "affected_files": affected_files,
            "injected_files_count": len(injected_files) if injected_files else 0
        })

        if pipeline_id:
            await push_log(pipeline_id, "info", f"CoderAgent 开始生成代码，影响 {len(affected_files)} 个文件...", stage="CODING")

        initial_state = {
            "design_output": design_output,
            "error_context": error_context,
            "injected_files": injected_files or {}  # 【核心】上游注入的文件内容
        }

        result = await self.execute(
            pipeline_id=pipeline_id or 0,
            stage_name="CODING",
            initial_state=initial_state
        )

        if result.get("success"):
            output_files = result.get("output", {}).get("files", [])
            logger.info(f"CoderAgent 代码生成完成", extra={
                "pipeline_id": pipeline_id,
                "generated_files_count": len(output_files),
                "generated_files": [f.get("file_path") for f in output_files]
            })
            if pipeline_id:
                await push_log(pipeline_id, "info", f"代码生成完成，共 {len(output_files)} 个文件", stage="CODING")
            
            interface_specs = design_output.get("interface_specs", [])

            if interface_specs and not design_output.get("force_full_file"):
                # 【新增】验证符号是否存在
                logger.info(f"[CoderAgent] 开始符号存在性校验: {len(interface_specs)} 个 interface_specs")

                # 【修复模式】syntax_fix_mode 下仅检查本次实际输出的文件
                if design_output.get("fix_mode") and design_output.get("syntax_fix_mode"):
                    # 只提取 output_files 中涉及的文件，对其中的符号进行校验
                    files_to_check = set()
                    for f in output_files:
                        fp = f.get("file_path", "")
                        if fp:
                            files_to_check.add(fp)
                    if files_to_check:
                        missing_symbols = self._validate_symbols_exist(
                            output_files, interface_specs, injected_files or {},
                            restrict_files=files_to_check  # 新增参数，仅检查指定文件
                        )
                    else:
                        missing_symbols = []
                else:
                    missing_symbols = self._validate_symbols_exist(output_files, interface_specs, injected_files or {})

                if missing_symbols:
                    error_msg = f"生成的代码缺少契约要求的符号: {missing_symbols}"
                    logger.error(f"[CoderAgent] {error_msg}")
                    if pipeline_id:
                        await push_log(pipeline_id, "error", error_msg, stage="CODING")
                    return {
                        "success": False,
                        "error": error_msg,
                        "output": result.get("output")
                    }
                logger.info("[CoderAgent] 符号存在性验证通过")
                
                # 验证返回键名
                logger.info(f"[CoderAgent] 开始键名校验: {len(interface_specs)} 个 interface_specs")
                key_mismatches = self._validate_return_keys(output_files, interface_specs, injected_files or {})
                
                if key_mismatches:
                    error_msg = f"生成的代码返回键名与契约不一致: {key_mismatches}"
                    logger.error(f"[CoderAgent] {error_msg}")
                    if pipeline_id:
                        await push_log(pipeline_id, "error", error_msg, stage="CODING")
                    return {
                        "success": False,
                        "error": error_msg,
                        "output": result.get("output")
                    }
                logger.info("[CoderAgent] 返回键名与契约一致，验证通过")
            elif design_output.get("force_full_file"):
                logger.info("[CoderAgent] 强制完整文件覆盖模式，跳过键名校验")
                result["needs_post_check"] = True
        else:
            logger.error(f"CoderAgent 代码生成失败", extra={
                "pipeline_id": pipeline_id,
                "error": result.get("error")
            })
            if pipeline_id:
                await push_log(pipeline_id, "error", f"代码生成失败: {result.get('error', '')}", stage="CODING")

        return result
    
    def _validate_return_keys(
        self,
        output_files: List[Dict],
        interface_specs: List[Dict],
        injected_files: Dict[str, str] = None
    ) -> List[Dict]:
        """
        【新增】静态验证：检查生成的代码是否符合 interface_specs 中的 return_fields
        
        使用 AST 解析生成的代码，提取函数返回的字典键名，与契约中的 return_fields 进行比对。
        
        策略：
        1. 对于 add 类型，直接使用 content
        2. 对于 modify 类型，使用 injected_files 中的原始内容 + 应用修改
        
        Args:
            output_files: 生成的文件列表
            interface_specs: 接口契约列表
            injected_files: 注入的原始文件内容 {file_path: content}
            
        Returns:
            List: 键名不匹配的错误列表
        """
        import re
        import ast
        mismatches = []
        injected_files = injected_files or {}
        
        # 【辅助函数】标准化路径，用于匹配
        def normalize_path(p: str) -> str:
            p = p.replace("\\", "/")
            if p.startswith("backend/"):
                p = p[8:]  # 去掉 backend/ 前缀
            return p.lstrip("/")
        
        # 【改进】构建标准化的 injected_files 查找表
        normalized_injected_files = {}
        for path, content in injected_files.items():
            normalized_injected_files[normalize_path(path)] = content
        
        # 【改进】构建文件路径到内容的映射，处理 modify 类型
        file_contents = {}
        
        for f in output_files:
            fp = f.get("file_path", "")
            content = f.get("content", "")
            change_type = f.get("change_type", "")
            
            if change_type == "add" and content:
                file_contents[fp] = content
            elif change_type == "modify":
                # 【修复】对于 modify 类型，从 injected_files 获取原始内容，然后应用修改
                # 使用标准化路径查找
                normalized_fp = normalize_path(fp)
                original_content = normalized_injected_files.get(normalized_fp, "")
                
                if not original_content:
                    logger.warning(f"[CoderAgent] modify 操作缺少原始文件内容，跳过验证: {fp} (标准化: {normalized_fp})")
                    logger.debug(f"[CoderAgent] 可用的 injected_files 键: {list(normalized_injected_files.keys())}")
                    continue
                
                # 应用修改
                search_block = f.get("search_block", "")
                replace_block = f.get("replace_block", "")
                if search_block and replace_block:
                    modified_content = original_content.replace(search_block, replace_block, 1)
                    file_contents[fp] = modified_content
                elif content:
                    # 如果提供了完整 content，直接使用
                    file_contents[fp] = content
                else:
                    logger.warning(f"[CoderAgent] modify 操作缺少 search_block/replace_block，跳过验证: {fp}")
        
        for spec in interface_specs:
            # 处理 InterfaceSpec 对象或字典
            if hasattr(spec, 'symbol_name'):
                symbol_name = spec.symbol_name
                return_fields = spec.return_fields if spec.return_fields else []
            else:
                symbol_name = spec.get("symbol_name", "")
                return_fields = spec.get("return_fields", [])
            
            if not symbol_name or not return_fields:
                continue
            
            # 提取契约要求的键名
            def get_field_name(f):
                return f.name if hasattr(f, 'name') else f.get("name", "")
            required_keys = set(get_field_name(f) for f in return_fields if get_field_name(f))
            if not required_keys:
                continue
            
            # 在所有生成的文件中查找该函数
            for fp, content in file_contents.items():
                try:
                    # 【改进】使用 AST 解析代码
                    tree = ast.parse(content)
                    
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if node.name == symbol_name:
                                # 找到函数，提取所有 return 语句
                                actual_keys = set()
                                
                                # 【改进】使用更健壮的键名提取
                                actual_keys = self._extract_return_keys_from_function(node)
                                
                                # 检查键名匹配
                                if actual_keys:
                                    missing_keys = required_keys - actual_keys
                                    extra_keys = actual_keys - required_keys
                                    
                                    if missing_keys:
                                        mismatches.append({
                                            "symbol": symbol_name,
                                            "file": fp,
                                            "error": "缺少契约要求的返回键",
                                            "missing_keys": list(missing_keys),
                                            "required_keys": list(required_keys),
                                            "actual_keys": list(actual_keys)
                                        })
                                    if extra_keys:
                                        logger.warning(
                                            f"[CoderAgent] 函数 {symbol_name} 返回了契约未要求的键: {extra_keys}"
                                        )
                                
                                break  # 找到函数，跳出节点遍历
                
                except SyntaxError:
                    # 如果 AST 解析失败，降级到正则匹配
                    logger.warning(f"[CoderAgent] AST 解析失败，降级到正则匹配: {fp}")
                    func_pattern = rf"(?:async\s+)?def\s+{re.escape(symbol_name)}\s*\("
                    if re.search(func_pattern, content):
                        # 使用改进的正则，支持多行
                        return_pattern = rf"return\s*\{{([\s\S]*?)\}}"
                        matches = re.findall(return_pattern, content)
                        
                        for match in matches:
                            actual_keys = set(re.findall(r"['\"](\w+)['\"]\s*:", match))
                            
                            if actual_keys:
                                missing_keys = required_keys - actual_keys
                                if missing_keys:
                                    mismatches.append({
                                        "symbol": symbol_name,
                                        "file": fp,
                                        "error": "缺少契约要求的返回键",
                                        "missing_keys": list(missing_keys),
                                        "required_keys": list(required_keys),
                                        "actual_keys": list(actual_keys)
                                    })
        
        return mismatches

    def _extract_return_keys_from_function(self, func_node: ast.FunctionDef) -> set:
        """
        【改进】从函数定义中提取所有可能的返回字典键名
        
        使用更健壮的 AST 遍历，处理：
        1. 直接返回字典：return {"key": value}
        2. 返回变量：return result（跟踪变量赋值）
        3. 条件返回：if x: return {"a": 1} else: return {"b": 2}
        4. 合并字典：return {**dict1, **dict2}
        
        Args:
            func_node: AST 函数定义节点
            
        Returns:
            set: 所有可能的返回键名
        """
        actual_keys = set()
        local_vars = {}  # 跟踪局部变量赋值
        
        # 首先收集所有局部变量赋值
        for node in ast.walk(func_node):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        # 记录变量赋值的内容类型
                        if isinstance(node.value, ast.Dict):
                            local_vars[var_name] = node.value
                        elif isinstance(node.value, ast.Call):
                            local_vars[var_name] = node.value
                        elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.BitOr):
                            # 处理 {**a, **b} 这种合并
                            local_vars[var_name] = node.value
            # ===== 增加对带类型注解变量的支持 =====
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    var_name = node.target.id
                    # 记录变量赋值的内容类型
                    if isinstance(node.value, ast.Dict):
                        local_vars[var_name] = node.value
                    elif isinstance(node.value, ast.Call):
                        local_vars[var_name] = node.value
                    elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.BitOr):
                        # 处理 {**a, **b} 这种合并
                        local_vars[var_name] = node.value

        # 然后分析所有 return 语句
        for node in ast.walk(func_node):
            if isinstance(node, ast.Return) and node.value:
                keys = self._extract_keys_from_value(node.value, local_vars)
                actual_keys.update(keys)
        
        return actual_keys

    def _extract_keys_from_value(self, value_node: ast.AST, local_vars: dict) -> set:
        """
        从 AST 值节点中提取字典键名
        
        Args:
            value_node: AST 值节点
            local_vars: 局部变量字典
            
        Returns:
            set: 提取的键名
        """
        keys = set()
        
        # 情况 1: 直接返回字典
        if isinstance(value_node, ast.Dict):
            for key in value_node.keys:
                key_name = self._get_key_name(key)
                if key_name:
                    keys.add(key_name)
        
        # 情况 2: 返回变量，尝试解析变量
        elif isinstance(value_node, ast.Name):
            var_name = value_node.id
            if var_name in local_vars:
                # 递归解析变量赋值
                keys.update(self._extract_keys_from_value(local_vars[var_name], {}))
        
        # 情况 3: 返回字典合并操作 {**a, **b}
        elif isinstance(value_node, ast.BinOp) and isinstance(value_node.op, ast.BitOr):
            # 递归处理左右两边
            keys.update(self._extract_keys_from_value(value_node.left, local_vars))
            keys.update(self._extract_keys_from_value(value_node.right, local_vars))
        
        # 情况 4: 返回函数调用（尝试解析常见模式）
        elif isinstance(value_node, ast.Call):
            # 如果是 dict() 调用
            if isinstance(value_node.func, ast.Name) and value_node.func.id == 'dict':
                # 解析 dict(key=value) 或 dict([(key, value)])
                for kw in value_node.keywords:
                    keys.add(kw.arg)
                for arg in value_node.args:
                    if isinstance(arg, (ast.List, ast.Tuple)):
                        for elt in arg.elts:
                            if isinstance(elt, (ast.List, ast.Tuple)) and len(elt.elts) >= 1:
                                key_name = self._get_key_name(elt.elts[0])
                                if key_name:
                                    keys.add(key_name)
        
        # 情况 5: 返回条件表达式
        elif isinstance(value_node, ast.IfExp):
            keys.update(self._extract_keys_from_value(value_node.body, local_vars))
            keys.update(self._extract_keys_from_value(value_node.orelse, local_vars))
        
        return keys

    def _get_key_name(self, key_node: ast.AST) -> str:
        """
        从 AST 键节点中提取键名字符串
        
        Args:
            key_node: AST 键节点
            
        Returns:
            str: 键名，如果无法提取则返回 None
        """
        # Python 3.8+: ast.Constant
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            return key_node.value
        # Python < 3.8: ast.Str
        elif isinstance(key_node, ast.Str):
            return key_node.s
        return None

    def _validate_symbols_exist(
        self,
        output_files: List[Dict],
        interface_specs: List[Dict],
        injected_files: Dict[str, str] = None,
        restrict_files: Optional[set] = None  # 【新增】仅检查指定文件
    ) -> List[str]:
        """
        【新增】验证生成的代码是否定义了 interface_specs 中的所有符号

        使用 AST 解析生成的代码，检查所有 symbol_name 是否已定义。

        Args:
            output_files: 生成的文件列表
            interface_specs: 接口契约列表
            injected_files: 注入的原始文件内容 {file_path: content}
            restrict_files: 【新增】仅检查这些文件中的符号（用于修复模式）

        Returns:
            List[str]: 缺失的符号列表
        """
        import ast
        from typing import Set
        missing_symbols = []
        injected_files = injected_files or {}

        def normalize_path(p: str) -> str:
            p = p.replace("\\", "/")
            if p.startswith("backend/"):
                p = p[8:]
            return p.lstrip("/")
        
        # 构建文件路径到内容的映射
        file_contents = {}
        normalized_injected_files = {normalize_path(p): c for p, c in injected_files.items()}
        
        for f in output_files:
            fp = f.get("file_path", "")
            content = f.get("content", "")
            change_type = f.get("change_type", "")
            search_block = f.get("search_block", "")
            replace_block = f.get("replace_block", "")
            
            if change_type == "add" and content:
                file_contents[fp] = content
            elif change_type == "modify":
                normalized_fp = normalize_path(fp)
                original_content = normalized_injected_files.get(normalized_fp, "")
                
                # 【修复】处理各种 modify 情况
                if search_block and replace_block:
                    # 标准 search-replace 模式
                    if original_content:
                        modified_content = original_content.replace(search_block, replace_block, 1)
                        file_contents[fp] = modified_content
                    else:
                        # 原始文件为空，但 replace_block 有内容，使用 replace_block
                        file_contents[fp] = replace_block
                elif replace_block and not search_block:
                    # search_block 为空但 replace_block 有内容 -> 视为新文件内容
                    file_contents[fp] = replace_block
                elif content:
                    # 使用 content 字段
                    file_contents[fp] = content
        
        # 构建模块到文件的映射
        module_to_file = {}
        for spec in interface_specs:
            if hasattr(spec, 'symbol_name'):
                symbol_name = spec.symbol_name
                module = spec.module if hasattr(spec, 'module') else ""
            else:
                symbol_name = spec.get("symbol_name", "")
                module = spec.get("module", "")
            
            if symbol_name and module:
                module_to_file[symbol_name] = module
        
        # 检查每个符号是否已定义
        for spec in interface_specs:
            if hasattr(spec, 'symbol_name'):
                symbol_name = spec.symbol_name
                module = spec.module if hasattr(spec, 'module') else ""
            else:
                symbol_name = spec.get("symbol_name", "")
                module = spec.get("module", "")

            if not symbol_name:
                continue

            # 标准化模块路径
            normalized_module = normalize_path(module)
            if not normalized_module.endswith(".py"):
                normalized_module += ".py"

            # 【新增】如果指定了 restrict_files，只检查这些文件
            if restrict_files is not None:
                # 将 restrict_files 中的路径标准化后比较
                normalized_restrict_files = {normalize_path(f) for f in restrict_files}
                if normalized_module not in normalized_restrict_files:
                    continue  # 跳过不在此次修复范围内的文件

            # 查找对应的文件内容
            content = None
            for fp, fc in file_contents.items():
                if normalize_path(fp) == normalized_module:
                    content = fc
                    break
            
            if not content:
                # 文件未生成，符号缺失
                missing_symbols.append(f"{symbol_name} in {module} (文件未生成)")
                continue
            
            # 使用 AST 解析检查符号是否定义
            try:
                tree = ast.parse(content)
                defined_symbols = set()
                
                for node in ast.walk(tree):
                    # 函数定义
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not node.name.startswith("_"):
                            defined_symbols.add(node.name)
                    # 类定义
                    elif isinstance(node, ast.ClassDef):
                        if not node.name.startswith("_"):
                            defined_symbols.add(node.name)
                    # 模块级变量赋值
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                if not target.id.startswith("_"):
                                    defined_symbols.add(target.id)
                    # 带类型注解的变量
                    elif isinstance(node, ast.AnnAssign):
                        if isinstance(node.target, ast.Name):
                            if not node.target.id.startswith("_"):
                                defined_symbols.add(node.target.id)
                
                if symbol_name not in defined_symbols:
                    missing_symbols.append(f"{symbol_name} in {module}")
                    
            except SyntaxError as e:
                logger.warning(f"[CoderAgent] 语法错误，无法验证符号: {module} - {e}")
                # 语法错误时不添加到缺失列表，让后续的语法检查处理
        
        return missing_symbols

# 单例实例
coder_agent = CoderAgent()
