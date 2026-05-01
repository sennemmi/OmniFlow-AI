"""
RepairerAgent - 代码修复代理
基于 LangGraphAgent 实现，不再使用工具调用

职责：
1. 接收结构化的修复工单
2. 直接基于提供的完整文件内容进行修复
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

from app.agents.base import LangGraphAgent
from app.agents.schemas import CoderOutput
from app.service.code_executor import CodeExecutorService

logger = logging.getLogger(__name__)


class RepairerAgent(LangGraphAgent[CoderOutput]):
    """
    代码修复代理

    接收结构化的修复工单和完整文件内容，直接执行精确修复。
    继承 LangGraphAgent，不再使用工具调用。
    """

    def __init__(self):
        super().__init__(agent_name="RepairerAgent")

    @property
    def system_prompt(self) -> str:
        return """你是 OmniFlowAI 的代码修复专家。你的唯一任务是根据提供的精确"修复工单"修正代码错误。

【核心铁律 - 利益隔离】
1. 你只能修复工单中指出的具体错误，严禁添加任何新功能、重构无关代码、调整代码风格或简化测试逻辑。
2. 每个修复必须使用 search_block 和 replace_block 格式，且 search_block 必须来自于你刚刚读取到的文件内容（严禁凭记忆编造）。
3. 【全局视角】工单中可能有多个 errors，你必须统筹考虑所有错误，一次性生成所有修复块。
4. 禁止引入新的第三方依赖，除非工单显式要求。
5. 禁止删除或注释掉任何测试断言。
6. 【绝对禁止】你没有任何测试工具的访问权限，严禁运行任何测试（pytest、unittest 等）。
7. 【重要】你可以修改测试文件和被测试文件，根据错误根源决定修复目标。
   - 如果被测代码逻辑错误 → 修复被测代码
   - 如果测试文件本身有问题（如错误的 mock、错误的断言）→ 修复测试文件
   - 如果两者都有问题 → 可以同时修复两者
8. 你的职责仅是提交修复代码，验证工作由独立的 VerificationAgent 完成。

【利益隔离说明】
- 你是 RepairerAgent，只负责"修"
- VerificationAgent 负责"检"，它会独立运行测试并报告结果
- 你永远不会看到测试结果，因此无法偷懒（比如删除测试）
- 你只能通过修复代码来解决问题，不能绕过测试

【错误解析】
工单中会包含错误列表，每个错误有 file_path、line、summary、fix_hint 等字段。你必须基于 fix_hint 和代码上下文进行修正。

【多错误统筹修复 - 关键改进】
1. 【全局视角】不要逐个修复错误，而是先阅读所有错误，分析它们之间的关联关系。
2. 【关联分析】多个错误可能由同一个根源引起：
   - 如果多个错误都指向同一个函数返回值问题 → 一次性修复该函数
   - 如果多个错误都是 KeyError 且键名相似 → 统一修正键名
   - 如果多个测试都因为同一个 mock 问题失败 → 统一修复 mock
3. 【批量修复】在 `files` 数组中为每个需要修改的文件提供一个修复块，即使这意味着要修改多个文件。
4. 【避免连锁失败】修复时要考虑：修改 A 文件是否会影响到 B 文件的测试？如果是，确保你的修复能同时解决所有相关问题。

【多文件修复能力】
1. 你可以修改工单中列出的任何文件（generated_files 字段中的所有文件），而不仅仅是最初报错的那个。
2. 如果工单指出某个函数返回了空结果或错误的键名，你需要追踪到该函数定义所在的文件并修复。

【根源分析 - 极其重要】
如果错误表现为某个文件返回了空结果或 KeyError，请执行根源分析：
1. 错误可能是某个 API 端点返回空 → 追踪到该端点调用的 service 函数
2. service 函数返回空 → 追踪到该函数内部的数据来源（如 system_monitor.py 中的检查函数）
3. 找到真正的根源后，修复那个文件中的错误
4. 不要只修复"调用方"的异常捕获，必须修复数据生产方的实际 bug

例如：
- 错误：health API 返回空的 components → 根源：system_monitor.py 中 check_disk 返回了不存在的字典键 'used_percent'（应为 'usage_percent'）
- 修复目标：system_monitor.py，而不是 health.py

【输出格式 - 极其重要】
你必须直接输出纯 JSON 格式，不要包含任何其他文本、解释或标记。
输出必须是一个有效的 JSON 对象，包含 files 数组。

正确示例（直接输出 JSON）：
{"files": [{"file_path": "backend/app/core/calculator.py", "change_type": "modify", "search_block": "def add(a, b):\n    return a - b", "replace_block": "def add(a, b):\n    return a + b", "description": "修复加法错误"}], "summary": "修复 calculator 加法错误"}

多文件修复示例：
{"files": [{"file_path": "backend/app/service/health.py", "change_type": "modify", "search_block": "return {'used_percent': 50}", "replace_block": "return {'usage_percent': 50}", "description": "修正键名 usage_percent"}, {"file_path": "backend/tests/test_health.py", "change_type": "modify", "search_block": "assert result['used'] == 50", "replace_block": "assert result['usage_percent'] == 50", "description": "同步更新测试断言"}], "summary": "统一修正 usage_percent 键名"}

错误示例（不要这样输出）：
- 不要添加 ```json 标记
- 不要添加解释文本
- 不要使用工具调用格式
- 只输出纯 JSON

【强制要求】
- 直接输出 JSON，不要有任何前缀或后缀
- 确保 JSON 格式完整有效
- 不要输出任何其他内容
- 【重要】一次性修复所有错误，不要只修复一个就停止
"""

    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt

        Args:
            state: 包含 fix_order, target_files 的状态
        """
        fix_order = state.get("fix_order", {})
        target_files = state.get("target_files", {})

        # 【DEBUG】记录输入状态
        logger.info(f"[RepairerAgent] build_user_prompt 被调用")
        logger.info(f"[RepairerAgent] fix_order 类型: {type(fix_order)}")
        logger.info(f"[RepairerAgent] fix_order 内容: {json.dumps(fix_order, indent=2, ensure_ascii=False)[:500]}")
        logger.info(f"[RepairerAgent] target_files 数量: {len(target_files)}")
        for path in target_files.keys():
            logger.info(f"[RepairerAgent] target_file: {path}")

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

        # 【简化】提取关键信息
        failed_tests = fix_order.get("failed_tests", [])
        error_logs = fix_order.get("error_logs", "")
        missing_symbols = fix_order.get("missing_symbols", [])
        fix_hint = fix_order.get("fix_hint", "")

        prompt = f"""【修复任务】
以下测试运行失败，请分析错误日志并修复代码。

【失败的测试】
{chr(10).join(f"- {test}" for test in failed_tests) if failed_tests else "多个测试失败，详见错误日志"}

【错误日志】
```
{error_logs}
```

【修复提示】
{fix_hint}

【目标文件（已有内容，带行号）】
{files_str}

【修复要求】
1. 仔细阅读错误日志，找出所有失败的原因
2. 分析错误根源：API → Service → 数据源函数
3. 提供精确的 search_block 和 replace_block 进行修复
4. search_block 必须与当前文件内容完全一致，包括缩进和空格
5. 一次性修复所有错误，不要只修复一个就停止
6. 如果多个错误由同一个根源引起，修复根源即可
"""
        # 【DEBUG】记录生成的 prompt 长度
        logger.info(f"[RepairerAgent] 生成的 prompt 长度: {len(prompt)} 字符")
        return prompt

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

    async def execute_with_files(
        self,
        pipeline_id: int,
        stage_name: str,
        fix_order: Dict[str, Any],
        target_files: Dict[str, str],
        project_path: Optional[str] = None,
        file_service: Optional[Any] = None,
        initial_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行修复（直接接收完整文件内容）

        【改造】不再自己读取文件，而是直接接收 target_files 参数中的完整文件内容。
        调用方需要确保提供所有相关文件的完整内容（包括 Coder 修改过的文件和 Tester 生成的文件）。

        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            fix_order: 修复工单
            target_files: 完整文件内容字典 {file_path: content}
            project_path: 项目路径（可选，用于日志记录）
            file_service: SandboxFileService 实例（可选，用于写入修复）
            initial_state: 初始状态（可选）

        Returns:
            Dict[str, Any]: 执行结果
        """
        logger.info(f"[Pipeline {pipeline_id}] RepairerAgent 开始执行（直接接收文件内容）")
        logger.info(f"[Pipeline {pipeline_id}] 接收到 {len(target_files)} 个文件的完整内容")

        if not target_files:
            logger.error(f"[Pipeline {pipeline_id}] 没有接收到任何文件内容")
            return {
                "success": False,
                "error": "没有接收到任何文件内容，请确保传入 target_files 参数",
                "output": None
            }

        for path, content in target_files.items():
            logger.info(f"[Pipeline {pipeline_id}] 文件: {path} ({len(content)} 字符)")

        # 构建状态
        state = initial_state or {}
        state.update({
            "fix_order": fix_order,
            "target_files": target_files,
            "file_service": file_service  # 传递给后续步骤用于写入
        })

        # 调用父类的 execute 方法（LangGraphAgent，不使用工具）
        result = await self.execute(
            pipeline_id=pipeline_id,
            stage_name=stage_name,
            initial_state=state
        )

        # 如果提供了 file_service 且修复成功，将修改写回 Sandbox
        if file_service and result.get("success") and result.get("output"):
            output = result["output"]
            if isinstance(output, dict) and "files" in output:
                for file_obj in output["files"]:
                    file_path = file_obj.get("file_path", "")
                    search_block = file_obj.get("search_block", "")
                    replace_block = file_obj.get("replace_block", "")

                    if search_block and replace_block:
                        # 读取当前文件内容
                        clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                        current_result = await file_service.read_file(clean_path)

                        if current_result.exists and current_result.content:
                            # 应用替换
                            new_content = current_result.content.replace(search_block, replace_block, 1)
                            # 写回 Sandbox
                            write_result = await file_service.write_file(clean_path, new_content)
                            if write_result.get("success"):
                                logger.info(f"[Pipeline {pipeline_id}] 成功将修复写入 Sandbox: {file_path}")
                            else:
                                logger.error(f"[Pipeline {pipeline_id}] 写入 Sandbox 失败: {file_path} - {write_result.get('error')}")

        return result


# 便捷函数
async def repair_code(
    fix_order: Dict[str, Any],
    target_files: Dict[str, str],
    file_service: Optional[Any] = None,
    pipeline_id: int = 0
) -> Dict[str, Any]:
    """
    便捷函数：修复代码

    Args:
        fix_order: 修复工单
        target_files: 完整文件内容字典（必须传入）
        file_service: SandboxFileService 实例（可选，用于写入修复）
        pipeline_id: Pipeline ID

    Returns:
        Dict[str, Any]: 修复结果
    """
    agent = RepairerAgent()

    if not target_files:
        return {
            "success": False,
            "error": "必须提供 target_files 参数"
        }

    return await agent.execute_with_files(
        pipeline_id=pipeline_id,
        stage_name="REPAIR",
        fix_order=fix_order,
        target_files=target_files,
        file_service=file_service
    )
