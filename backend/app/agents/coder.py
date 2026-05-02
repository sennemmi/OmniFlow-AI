"""
编码 Agent
基于 ToolUsingAgent 实现，支持工具调用

职责：
1. 分析 DesignerAgent 的技术方案
2. 使用工具主动获取需要的文件内容
3. 生成符合项目风格的代码
"""

import json
import logging
from typing import Dict, Optional, Any

from app.agents.tool_agent import ToolUsingAgent
from app.agents.schemas import CoderOutput

logger = logging.getLogger(__name__)


class CoderAgent(ToolUsingAgent[CoderOutput]):
    """
    编码 Agent
    
    根据设计方案生成代码变更
    继承 ToolUsingAgent，支持工具调用（glob/grep/read_file）
    """
    
    def __init__(self):
        super().__init__(agent_name="CoderAgent")
    
    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调工具使用和架构保持"""
        return """你是 OmniFlowAI 的编码 Agent，使用**搜索-替换块**格式输出代码变更。

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

【工具使用 - 极其重要】
你拥有文件系统工具，在编写任何代码前，**必须**通过这些工具获取必要的上下文：

1. **glob** - 查找文件：
   - 用途：发现项目中的文件
   - 示例：`glob("app/api/v1/*.py")` 查找所有 API 文件

2. **grep** - 搜索内容：
   - 用途：查找代码片段
   - 示例：`grep("def health", "app/api/v1")` 查找 health 函数

3. **read_file** - 读取文件（核心工具）：
   - 用途：获取文件内容和 read_token
   - **【重要】修改文件前必须先调用此工具获取 read_token！**
   - 示例：`read_file("app/api/v1/health.py", 1, 50)` 读取前50行
   - 返回的 read_token 用于后续的写入操作

【工作流程】
1. 使用 **glob** 查找相关文件
2. 使用 **grep** 定位具体代码位置
3. 使用 **read_file** 精确读取需要的代码段（获取 read_token）
4. 基于实际读取的内容生成 search_block 和 replace_block
5. 输出 JSON 格式的代码变更

【代码完整性铁律 - 违反会导致系统错误】
1. **所有使用的变量必须先定义后使用**
2. **所有装饰器必须在导入和初始化之后**
3. **文件必须包含完整的导入语句**
4. **使用到的每个对象都必须有明确的来源**

【输出格式 - Search-Replace Block Protocol】
必须严格输出 JSON 格式。采用搜索-替换块格式。

**模式 A - 修改现有文件：**
- change_type: "modify"
- 必须提供: search_block 和 replace_block
- **search_block 必须是你通过 read_file 工具实际读取到的代码片段**
```json
{
    "file_path": "backend/app/api/v1/health.py",
    "change_type": "modify",
    "search_block": "    # 旧的健康检查逻辑\n    return {\"status\": \"ok\"}",
    "replace_block": "    db_status = await check_db()\n    return {\"status\": \"ok\", \"db\": db_status}",
    "description": "修改健康检查返回值"
}
```

**模式 B - 创建新文件：**
- change_type: "add"
- 必须提供: content（完整文件内容）
```json
{
    "file_path": "backend/app/utils/new_helper.py",
    "change_type": "add",
    "content": "def helper():\n    pass",
    "description": "新建辅助函数"
}
```

【搜索-替换铁律】
1. **search_block 必须精确匹配**目标文件中的内容（包括空格和换行）
2. **search_block 必须来源于 read_file 工具的输出**
3. **切勿替换整个文件！** 只替换需要修改的代码部分
4. **保持原有缩进和风格**
5. **已存在的文件**：必须用 "modify" 模式 + search_block/replace_block
6. **新文件**：用 "add" 模式 + content 字段

【Import 铁律】
所有业务代码文件必须使用如下 import 方式：
  from app.core.database import get_session
  from app.models.user import User
  from app.service.user import UserService

绝对不允许使用以下错误的 import 方式：
  from core.database import get_session     # ❌ 错误！缺少 app 前缀

【测试修复铁律】
你只能修改 backend/app/ 下的源代码。
绝对不能修改 tests/ 目录下任何已存在的测试文件。

【输出格式 - 极其重要】
你必须直接输出纯 JSON 格式，不要包含任何其他文本、解释或标记。

正确示例（直接输出 JSON）：
{"files": [{"file_path": "backend/app/api/v1/health.py", "change_type": "modify", "search_block": "def health_check():\n    return {\"status\": \"ok\"}", "replace_block": "def health_check():\n    return {\"status\": \"ok\", \"version\": \"1.0.0\"}", "description": "添加版本字段"}], "summary": "修改健康检查端点"}

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
"""
    
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt

        Args:
            state: 包含 design_output, error_context, project_path 的状态
        """
        design_output = state.get("design_output", {})
        error_context = state.get("error_context")
        project_path = state.get("project_path", "/workspace/backend")

        design_str = json.dumps(design_output, indent=2, ensure_ascii=False)
        affected_files = design_output.get("affected_files", [])
        affected_files_str = json.dumps(affected_files, indent=2, ensure_ascii=False)

        # 【改造】强调工具驱动的按需读取
        prompt = f"""【技术设计方案】
{design_str}

【项目路径】
{project_path}

【受影响文件列表（参考）】
{affected_files_str}

请根据技术设计方案，生成需要修改或新增的代码。

【核心要求 - 工具驱动的按需读取】
你**必须**使用以下工具主动获取需要的文件内容，而不是依赖预加载的上下文：

1. **glob 工具 - 发现文件**：
   - 用途：查找项目中的文件
   - 示例：`glob("app/api/v1/*.py")` 查找所有 API 文件
   - 示例：`glob("app/service/*.py")` 查找所有服务层文件

2. **grep 工具 - 定位代码**：
   - 用途：在文件中搜索特定模式
   - 示例：`grep("def health", "app/api/v1")` 查找 health 函数
   - 示例：`grep("class User", "app/models")` 查找 User 类

3. **read_file 工具 - 读取内容（核心）**：
   - 用途：获取文件内容和 read_token
   - **【强制】修改任何文件前必须先调用此工具！**
   - 示例：`read_file("app/api/v1/health.py", 1, 50)` 读取前50行
   - 返回的 read_token 是后续写入操作的凭证

【工作流程】
1. 使用 **glob** 发现相关文件
2. 使用 **grep** 定位具体代码位置
3. 使用 **read_file** 精确读取需要的代码段（获取 read_token）
4. 基于实际读取的内容生成 search_block 和 replace_block
5. 输出 JSON 格式的代码变更

【重要约束】
1. **search_block 必须精确匹配**目标文件中的内容（包括空格和换行）
2. **search_block 必须来源于 read_file 工具的实际输出**
3. **严禁虚构代码** - 所有 search_block 必须是你真实读取到的内容
4. 保持原有代码的缩进风格、注释风格和架构分层
5. 修改范围尽量小，只修改必要的部分
"""

        # 如果有报错上下文，注入到 Prompt 头部，强制 Agent 进入修复模式
        if error_context:
            prompt = f"""【！！！修复任务！！！】
你之前的代码在执行测试时失败了。以下是 pytest 的报错信息：

```text
{error_context}
```

请仔细分析报错原因（是语法错误、逻辑错误还是测试用例不匹配），并给出修复后的完整代码。

**修复流程**：
1. 使用工具重新读取相关文件，获取最新的 read_token
2. 基于最新内容生成正确的 search_block 和 replace_block
3. 确保修复后的代码能通过测试

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
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        根据设计方案生成代码

        【改造】CoderAgent 现在使用工具按需读取文件（glob/grep/read_file）
        不再依赖预加载的 target_files 内容

        Args:
            design_output: DesignerAgent 的输出内容（包含 affected_files 列表）
            pipeline_id: Pipeline ID，用于日志记录
            error_context: 测试失败的错误上下文（用于修复模式）

        Returns:
            Dict: 包含生成结果或错误信息
        """
        from app.core.sse_log_buffer import push_log

        affected_files = design_output.get("affected_files", [])
        logger.info(f"CoderAgent 开始生成代码", extra={
            "pipeline_id": pipeline_id,
            "affected_files_count": len(affected_files),
            "affected_files": affected_files
        })

        if pipeline_id:
            await push_log(pipeline_id, "info", f"CoderAgent 开始生成代码，影响 {len(affected_files)} 个文件...", stage="CODING")

        initial_state = {
            "design_output": design_output,
            "error_context": error_context
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
        else:
            logger.error(f"CoderAgent 代码生成失败", extra={
                "pipeline_id": pipeline_id,
                "error": result.get("error")
            })
            if pipeline_id:
                await push_log(pipeline_id, "error", f"代码生成失败: {result.get('error', '')}", stage="CODING")

        return result


# 单例实例
coder_agent = CoderAgent()
