"""
RepairerAgent - 代码修复代理
基于 ToolUsingAgent 实现，支持工具调用

职责：
1. 接收结构化的修复工单
2. 使用工具主动获取文件内容
3. 严格执行精确修复，不得做任何多余的事
4. 每个修复必须使用 search_block/replace_block 格式

原则：
- 只修复工单中指出的具体错误
- 严禁添加新功能、重构无关代码、调整代码风格
- 禁止引入新的第三方依赖（除非工单显式要求）
- 禁止删除或注释掉任何测试断言
"""

import json
import logging
from typing import Dict, Any, Optional, List

from app.agents.tool_agent import ToolUsingAgent
from app.agents.schemas import CoderOutput
from app.service.code_executor import CodeExecutorService

logger = logging.getLogger(__name__)


class RepairerAgent(ToolUsingAgent[CoderOutput]):
    """
    代码修复代理

    接收结构化的修复工单，使用工具获取文件，严格执行精确修复。
    继承 ToolUsingAgent，支持工具调用（glob/grep/read_file）。
    """

    def __init__(self):
        super().__init__(agent_name="RepairerAgent")

    @property
    def system_prompt(self) -> str:
        return """你是 OmniFlowAI 的代码修复专家。你的唯一任务是根据提供的精确"修复工单"修正代码错误。

【核心铁律 - 利益隔离】
1. 你只能修复工单中指出的具体错误，严禁添加任何新功能、重构无关代码、调整代码风格或简化测试逻辑。
2. 每个修复必须使用 search_block 和 replace_block 格式，且 search_block 必须来自于你刚刚读取到的文件内容（严禁凭记忆编造）。
3. 一次只能处理一个修复项，若工单有多个错误，需逐个生成修复块。
4. 禁止引入新的第三方依赖，除非工单显式要求。
5. 禁止删除或注释掉任何测试断言。
6. 【绝对禁止】你没有任何测试工具的访问权限，严禁运行任何测试（pytest、unittest 等）。
7. 【绝对禁止】你不得修改任何测试文件，只能修复被测代码。
8. 你的职责仅是提交修复代码，验证工作由独立的 VerificationAgent 完成。

【利益隔离说明】
- 你是 RepairerAgent，只负责"修"
- VerificationAgent 负责"检"，它会独立运行测试并报告结果
- 你永远不会看到测试结果，因此无法偷懒（比如删除测试）
- 你只能通过修复代码来解决问题，不能绕过测试

【错误解析】
工单中会包含错误列表，每个错误有 file_path、line、summary、fix_hint 等字段。你必须基于 fix_hint 和代码上下文进行修正。

【输出格式 - 极其重要】
你必须直接输出纯 JSON 格式，不要包含任何其他文本、解释或标记。
输出必须是一个有效的 JSON 对象，包含 files 数组。

正确示例（直接输出 JSON）：
{"files": [{"file_path": "backend/app/core/calculator.py", "change_type": "modify", "search_block": "def add(a, b):\n    return a - b", "replace_block": "def add(a, b):\n    return a + b", "description": "修复加法错误"}], "summary": "修复 calculator 加法错误"}

错误示例（不要这样输出）：
- 不要添加 ```json 标记
- 不要添加解释文本
- 不要使用工具调用格式
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
            state: 包含 fix_order, target_files 的状态
        """
        fix_order = state.get("fix_order", {})
        target_files = state.get("target_files", {})

        # 将权威目标文件（已重新读取）嵌入提示
        files_section = []
        for path, content in target_files.items():
            # 给每一行加上行号
            numbered_lines = [f"{i+1:04d} | {line}" for i, line in enumerate(content.splitlines())]
            numbered_content = "\n".join(numbered_lines)
            files_section.append(f"""【文件: {path}】
```python
{numbered_content}
```""")

        files_str = "\n\n".join(files_section)

        return f"""【修复工单（必须严格遵循）】
{json.dumps(fix_order, indent=2, ensure_ascii=False)}

【目标文件（已最新内容，带行号）】
{files_str}

请基于工单逐个修复错误。对于每个修复，提供精确的 search_block (从上方文件内容中复制) 和 replace_block。
注意：
1. search_block 必须与当前文件内容完全一致，包括缩进和空格
2. 只修复工单中指出的错误，不要做其他修改
3. 如果多个错误在同一文件，请分别提供修复块
"""

    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出"""
        return self._parse_json_response(response)

    def validate_output(self, output: Dict[str, Any]) -> CoderOutput:
        """
        校验输出为 CoderOutput 模型

        处理 AI 可能返回的各种格式
        """
        # 如果 output 是列表，将其包装为 CoderOutput 的 files 字段
        if isinstance(output, list):
            logger.warning(f"RepairerAgent output is a list, auto-wrapping to CoderOutput format")
            output = {"files": output}

        # 如果 output 是单个文件对象（有 file_path 但没有 files 字段），包装为列表
        elif isinstance(output, dict):
            if "files" not in output and "file_path" in output:
                logger.warning(f"RepairerAgent output is a single file object, auto-wrapping to files list")
                output = {"files": [output]}

        return CoderOutput(**output)

    async def execute_with_reread(
        self,
        pipeline_id: int,
        stage_name: str,
        fix_order: Dict[str, Any],
        project_path: str,
        initial_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行修复（带强制重新读取）

        在调用 RepairerAgent 前，强制重新读取所有出错的文件，
        确保 target_files 中的内容是磁盘上最新版本。

        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            fix_order: 修复工单
            project_path: 项目路径
            initial_state: 初始状态（可选）

        Returns:
            Dict[str, Any]: 执行结果
        """
        logger.info(f"[Pipeline {pipeline_id}] RepairerAgent 开始执行（带强制重新读取）")

        # 1. 从 fix_order 中提取需要读取的文件
        files_to_read = set()
        for err in fix_order.get("errors", []):
            file_path = err.get("file_path")
            if file_path:
                # 移除 backend/ 前缀
                clean_path = file_path.replace("backend/", "").replace("backend\\", "")
                files_to_read.add(clean_path)

        logger.info(f"[Pipeline {pipeline_id}] 需要重新读取 {len(files_to_read)} 个文件")

        # 2. 强制重新读取所有文件
        code_executor = CodeExecutorService(project_path)
        target_files = {}
        read_tokens = {}  # 记录 read_token 用于后续写入

        for clean_path in files_to_read:
            read_result = code_executor.read_file(clean_path)
            if read_result.exists and read_result.content is not None:
                # 存储完整路径（带 backend/ 前缀）
                full_path = f"backend/{clean_path}"
                target_files[full_path] = read_result.content
                read_tokens[full_path] = read_result.read_token
                logger.debug(f"[Pipeline {pipeline_id}] 重新读取: {full_path}")
            else:
                logger.warning(f"[Pipeline {pipeline_id}] 无法读取文件: {clean_path}")

        if not target_files:
            logger.error(f"[Pipeline {pipeline_id}] 没有成功读取任何文件")
            return {
                "success": False,
                "error": "无法读取任何目标文件",
                "output": None
            }

        logger.info(f"[Pipeline {pipeline_id}] 成功读取 {len(target_files)} 个文件")

        # 3. 构建状态
        state = initial_state or {}
        state.update({
            "fix_order": fix_order,
            "target_files": target_files,
            "read_tokens": read_tokens  # 传递给后续写入步骤
        })

        # 4. 调用父类的 execute 方法
        result = await self.execute(
            pipeline_id=pipeline_id,
            stage_name=stage_name,
            initial_state=state
        )

        # 5. 将 read_tokens 附加到输出中（供后续写入使用）
        if result.get("success") and result.get("output"):
            output = result["output"]
            if isinstance(output, dict) and "files" in output:
                for file_obj in output["files"]:
                    file_path = file_obj.get("file_path", "")
                    if file_path in read_tokens:
                        file_obj["read_token"] = read_tokens[file_path]

        return result


# 便捷函数
async def repair_code(
    fix_order: Dict[str, Any],
    project_path: str,
    pipeline_id: int = 0
) -> Dict[str, Any]:
    """
    便捷函数：修复代码

    Args:
        fix_order: 修复工单
        project_path: 项目路径
        pipeline_id: Pipeline ID

    Returns:
        Dict[str, Any]: 修复结果
    """
    agent = RepairerAgent()
    return await agent.execute_with_reread(
        pipeline_id=pipeline_id,
        stage_name="REPAIR",
        fix_order=fix_order,
        project_path=project_path
    )
