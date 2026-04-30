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

import json
import logging
from typing import Dict, Optional, Any

from app.agents.base import LangGraphAgent
from app.agents.schemas import CoderOutput

logger = logging.getLogger(__name__)


class CoderAgent(LangGraphAgent[CoderOutput]):
    """
    编码 Agent

    根据设计方案生成代码变更
    继承 LangGraphAgent，纯代码生成，不持有任何工具
    所需文件内容由上游（ArchitectAgent）预读后注入到 state 中
    """

    def __init__(self):
        super().__init__(agent_name="CoderAgent")

    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调纯 JSON 输出"""
        return """你是 OmniFlowAI 的编码 Agent，负责生成代码变更。

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

【代码完整性铁律 - 违反会导致系统错误】
1. **所有使用的变量必须先定义后使用**
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

【测试修复铁律】
你只能修改 backend/app/ 下的源代码。
绝对不能修改 tests/ 目录下任何已存在的测试文件。

【输出格式 - 极其重要】
你必须直接输出纯 JSON 格式，不要包含任何其他文本、解释或标记。
输出必须是一个有效的 JSON 对象。

正确示例（直接输出 JSON）：
{"files": [{"file_path": "app/api/v1/health.py", "change_type": "modify", "search_block": "def health_check():\\n    return {\"status\": \"ok\"}", "replace_block": "def health_check():\\n    db_status = await check_db()\\n    return {\"status\": \"ok\", \"db\": db_status}", "description": "添加数据库状态检查"}]}

错误示例（不要这样输出）：
- 不要添加 ```json 标记
- 不要添加解释文本
- 不要输出 "我需要先分析..." 等思考过程
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
  - description: 改动说明
- summary: 变更摘要
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

        # 【核心改造】使用上游注入的文件内容，不再让 LLM 自己读取
        injected_files: Dict[str, str] = state.get("injected_files", {})
        
        # 【调试】记录 injected_files 信息
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[CoderAgent] 接收到的 injected_files: {len(injected_files)} 个文件")
        for path in injected_files.keys():
            content_len = len(injected_files[path])
            logger.info(f"[CoderAgent]   - {path}: {content_len} 字符")

        files_section = ""
        if injected_files:
            files_section = "\n【已存在文件列表 - 这些文件已存在，必须使用 change_type=\"modify\"】\n"
            files_section += "文件路径列表：\n"
            for path in injected_files.keys():
                files_section += f"  - {path} (已存在，使用 modify)\n"

            files_section += "\n【文件现有内容 - search_block 必须从这里精确复制】\n"
            for path, content in injected_files.items():
                # 限制每个文件最多 150 行，避免 prompt 过长
                lines = content.splitlines()
                shown = "\n".join(lines[:150])
                truncated = f"\n... (共{len(lines)}行，已截断)" if len(lines) > 150 else ""
                files_section += f"\n### {path}\n```python\n{shown}{truncated}\n```\n"
        else:
            files_section = "\n⚠️ 警告：未提供文件内容，请确保 search_block 与实际文件完全一致\n"

        prompt = f"""【技术设计方案】
{design_str}
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
