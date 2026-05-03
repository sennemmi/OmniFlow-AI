# app/agents/coder_architect.py

"""
架构师模式 Coder Agent
只负责理解需求、规划修改、读取代码
不执行任何写操作
"""

import json
import logging
from typing import Dict, Any, List, Optional

from app.agents.tool_agent import ToolUsingAgent
from app.agents.schemas import CoderOutput

logger = logging.getLogger(__name__)


class ArchitectCoderAgent(ToolUsingAgent):
    """
    架构师模式: 只负责理解需求、规划修改、读取代码
    不执行任何写操作
    """

    # 【结构化输出】启用 JSON 格式化输出
    USE_JSON_FORMAT = True

    def __init__(self):
        super().__init__(agent_name="ArchitectCoder")

    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 架构师只读模式"""
        return """
你是 OmniFlowAI 的代码架构师,负责分析需求和规划修改方案。

【你的职责】
1. 理解技术方案和需求
2. 读取相关代码文件,分析当前实现
3. 规划需要修改的地方
4. 输出精确的编辑指令清单给"编辑者"

【你可以使用的工具】
1. **read_file** - 读取文件内容(每次最多80行)
2. **grep_ast** - 结构化代码搜索
3. **glob** - 查找文件
4. **grep** - 文本搜索

【禁止】
- 禁止执行任何写操作
- 禁止直接修改代码
- 你的输出是给"编辑者"的指令,不是直接修改

【输出格式】
你必须输出一个 JSON 对象,包含 edit_plan 列表:
{
  "edit_plan": [
    {
      "action": "func_replace",
      "file": "app/api/v1/health.py",
      "func_name": "health_check",
      "reason": "需要添加数据库状态检查"
    },
    {
      "action": "insert_after",
      "file": "app/models/user.py",
      "after_line": 42,
      "reason": "需要添加新的字段"
    },
    {
      "action": "code_apply",
      "file": "app/service/user.py",
      "search_block": "...",
      "replace_block": "...",
      "reason": "修改逻辑"
    }
  ],
  "summary": "修改计划概述"
}

【edit_plan 字段说明】
- action: 编辑操作类型 (func_replace/insert_after/delete_lines/code_apply)
- file: 目标文件路径
- func_name: 函数名 (仅 func_replace 需要)
- after_line: 插入位置行号 (仅 insert_after 需要)
- search_block: 要替换的代码 (仅 code_apply 需要)
- replace_block: 新代码 (仅 code_apply 需要)
- reason: 修改原因说明

【工作流程】
1. 先读取相关文件,理解当前实现
2. 分析需要修改的地方
3. 规划每个修改步骤
4. 输出完整的 edit_plan

【重要】
- 每个 action 必须是可独立执行的
- 按依赖关系排序 (先改底层,再改上层)
- 提供清晰的 reason 说明
"""

    def build_user_prompt(self, initial_state: Dict[str, Any]) -> str:
        """构建用户提示"""
        design_output = initial_state.get("design_output", {})

        prompt_parts = [
            "【技术方案】",
            json.dumps(design_output, ensure_ascii=False, indent=2),
            "",
            "请分析以上技术方案,读取相关代码,并输出 edit_plan。",
            "记住: 你只负责规划,不直接修改代码!"
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

            # 转换为 CoderOutput 格式
            edit_plan = data.get("edit_plan", [])

            # 将 edit_plan 转换为 files 格式
            files = []
            for item in edit_plan:
                file_item = {
                    "file_path": item.get("file", ""),
                    "change_type": "modify",
                    "description": item.get("reason", ""),
                    "action": item.get("action", ""),
                }

                # 根据 action 类型添加额外字段
                if item.get("action") == "func_replace":
                    file_item["func_name"] = item.get("func_name", "")
                elif item.get("action") == "insert_after":
                    file_item["after_line"] = item.get("after_line", 0)
                elif item.get("action") == "code_apply":
                    file_item["search_block"] = item.get("search_block", "")
                    file_item["replace_block"] = item.get("replace_block", "")

                files.append(file_item)

            return CoderOutput(
                files=files,
                summary=data.get("summary", "Architect 规划完成")
            )

        except json.JSONDecodeError as e:
            logger.error(f"[ArchitectCoder] JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[ArchitectCoder] 解析输出失败: {e}")
            return None

    def validate_output(self, output: CoderOutput) -> Optional[CoderOutput]:
        """验证输出"""
        if not output or not output.files:
            logger.error("[ArchitectCoder] 输出为空或没有文件")
            return None

        # 验证每个 edit_plan 项
        for item in output.files:
            if not item.get("file_path"):
                logger.error("[ArchitectCoder] edit_plan 项缺少 file")
                return None
            if not item.get("action"):
                logger.error("[ArchitectCoder] edit_plan 项缺少 action")
                return None

        return output

    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
        """
        只读工具定义
        架构师只能读取代码,不能修改
        """
        # 获取基础工具定义
        base_tools = super().tool_definitions

        # 只保留只读工具
        read_only_tools = [
            t for t in base_tools
            if t["function"]["name"] in ("read_file", "grep_ast", "glob", "grep")
        ]

        return read_only_tools
