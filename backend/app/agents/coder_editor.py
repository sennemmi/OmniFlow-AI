# app/agents/coder_editor.py

"""
编辑者模式 Coder Agent
接收精确的编辑指令,执行工具调用
不做推理,不做规划,只做机械编辑
"""

import json
import logging
from typing import Dict, Any, List, Optional

from app.agents.tool_agent import ToolUsingAgent
from app.agents.schemas import CoderOutput

logger = logging.getLogger(__name__)


class EditorCoderAgent(ToolUsingAgent):
    """
    编辑者模式: 接收精确的编辑指令,执行工具调用
    不做推理,不做规划,只做机械编辑
    """

    # 【结构化输出】启用 JSON 格式化输出
    USE_JSON_FORMAT = True

    def __init__(self):
        super().__init__(agent_name="EditorCoder")

    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 编辑者执行模式"""
        return """
你是 OmniFlowAI 的代码编辑者,你收到的 edit_plan 是必须精确执行的指令清单。

【你的职责】
1. 逐条执行 edit_plan 中的每个 action
2. 使用对应的工具完成每个编辑操作
3. 报告每个操作的成功或失败
4. 不做任何额外的推理或修改

【你可以使用的工具】
1. **read_file** - 读取文件内容(确认修改前状态)
2. **code_apply** - 精确的 search/replace
3. **func_replace** - 替换整个函数
4. **insert_after** - 在指定行后插入代码
5. **delete_lines** - 删除指定行范围

【重要规则】
- 不要质疑或修改指令,只做机械操作
- 如果某个操作失败(如 code_apply 返回错误),报告失败原因
- 每次只执行一个操作,等待结果后再执行下一个
- 如果指令缺少必要参数,报告错误并停止

【输出格式】
执行完所有操作后,输出 JSON 总结:
{
  "files_modified": ["app/api/v1/health.py", "app/models/user.py"],
  "operations": [
    {"action": "func_replace", "file": "...", "success": true, "message": "..."},
    {"action": "insert_after", "file": "...", "success": false, "error": "..."}
  ],
  "summary": "成功执行 X 个操作,失败 Y 个",
  "all_success": true/false
}

【工作流程】
1. 读取当前 edit_plan
2. 对于每个 action:
   a. 如果需要,先 read_file 确认文件状态
   b. 调用对应的编辑工具
   c. 记录结果
3. 输出执行总结

【失败处理】
- 如果某个操作失败,记录错误并继续执行下一个
- 如果连续 3 个操作失败,停止执行并报告
- 不要尝试修复失败的指令,只报告问题
"""

    def build_user_prompt(self, initial_state: Dict[str, Any]) -> str:
        """构建用户提示"""
        # 可能是单条 action 或完整的 edit_plan
        current_action = initial_state.get("current_action")
        edit_plan = initial_state.get("edit_plan")

        if current_action:
            # 单条 action 模式
            prompt_parts = [
                "【当前编辑指令】",
                json.dumps(current_action, ensure_ascii=False, indent=2),
                "",
                "请执行以上编辑指令,使用对应的工具完成操作。",
                "执行完成后输出结果 JSON。"
            ]
        elif edit_plan:
            # 完整 edit_plan 模式
            prompt_parts = [
                "【编辑指令清单】",
                json.dumps(edit_plan, ensure_ascii=False, indent=2),
                "",
                "请逐条执行以上 edit_plan,使用对应的工具完成每个操作。",
                "执行完成后输出完整的执行结果 JSON。"
            ]
        else:
            prompt_parts = [
                "【错误】",
                "没有收到编辑指令。",
                "请输出错误 JSON: {\"error\": \"没有编辑指令\"}"
            ]

        return "\n".join(prompt_parts)

    def parse_output(self, raw_output: str) -> Optional[CoderOutput]:
        """解析 LLM 输出"""
        try:
            # 清理 Markdown 代码块标记
            cleaned_output = raw_output.strip()
            if cleaned_output.startswith("```json"):
                cleaned_output = cleaned_output[7:]  # 移除 ```json
            elif cleaned_output.startswith("```"):
                cleaned_output = cleaned_output[3:]  # 移除 ```
            if cleaned_output.endswith("```"):
                cleaned_output = cleaned_output[:-3]  # 移除结尾 ```
            cleaned_output = cleaned_output.strip()

            # 尝试解析 JSON
            data = json.loads(cleaned_output)

            # 检查是否有错误
            if "error" in data:
                logger.error(f"[EditorCoder] 执行错误: {data['error']}")
                return None

            # 转换为 CoderOutput 格式
            operations = data.get("operations", [])
            files_modified = data.get("files_modified", [])

            # 构建 files 列表
            files = []
            for op in operations:
                if op.get("success"):
                    file_item = {
                        "file_path": op.get("file", ""),
                        "change_type": "modify",
                        "description": op.get("message", ""),
                        "action": op.get("action", ""),
                    }
                    files.append(file_item)

            return CoderOutput(
                files=files,
                summary=data.get("summary", "Editor 执行完成"),
                all_success=data.get("all_success", False)
            )

        except json.JSONDecodeError as e:
            logger.error(f"[EditorCoder] JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[EditorCoder] 解析输出失败: {e}")
            return None

    def validate_output(self, output: CoderOutput) -> Optional[CoderOutput]:
        """验证输出"""
        if not output:
            logger.error("[EditorCoder] 输出为空")
            return None

        return output

    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
        """
        编辑工具定义
        编辑者可以读取和修改代码
        """
        # 获取基础工具定义
        base_tools = super().tool_definitions

        # 保留所有编辑工具
        edit_tools = [
            t for t in base_tools
            if t["function"]["name"] in (
                "read_file", "code_apply", "func_replace",
                "insert_after", "delete_lines", "glob", "grep"
            )
        ]

        return edit_tools
