"""
RepairerAgent with Tools - 带测试运行工具的代码修复代理

支持多轮对话和快速测试验证：
1. 接收修复任务
2. 生成修复代码
3. 运行测试验证
4. 根据测试结果继续修复（多轮）
5. 保留完整上下文

与原版 RepairerAgent 的区别：
- 新增 run_tests 工具，可在修复后立即验证
- 支持多轮对话，根据测试结果迭代修复
- 保留完整对话上下文
"""

import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from app.agents.base import LangGraphAgent
from app.agents.schemas import CoderOutput
from app.service.sandbox_manager import sandbox_manager

logger = logging.getLogger(__name__)


@dataclass
class RepairerState:
    """RepairerAgent 状态（支持多轮对话）"""
    fix_order: Dict[str, Any] = field(default_factory=dict)
    target_files: Dict[str, str] = field(default_factory=dict)
    file_service: Optional[Any] = None
    pipeline_id: int = 0
    
    # 多轮对话上下文
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    current_round: int = 0
    max_rounds: int = 3
    
    # 测试结果跟踪
    test_results: List[Dict[str, Any]] = field(default_factory=list)
    last_test_output: str = ""
    
    def add_round(self, user_message: str, assistant_response: str, test_result: Optional[Dict] = None):
        """添加一轮对话到历史"""
        self.conversation_history.append({
            "round": self.current_round,
            "user": user_message,
            "assistant": assistant_response,
            "test_result": test_result
        })
        self.current_round += 1
    
    def get_context_for_prompt(self) -> str:
        """获取格式化的对话历史用于 prompt"""
        if not self.conversation_history:
            return ""
        
        context_parts = ["\n【修复历史 - 多轮对话上下文】"]
        for entry in self.conversation_history:
            context_parts.append(f"\n--- 第 {entry['round'] + 1} 轮 ---")
            context_parts.append(f"修复内容: {entry['assistant'][:500]}...")
            if entry.get('test_result'):
                success = entry['test_result'].get('success', False)
                context_parts.append(f"测试结果: {'通过' if success else '失败'}")
                if not success:
                    context_parts.append(f"错误: {entry['test_result'].get('error', '未知错误')[:300]}")
        
        return "\n".join(context_parts)


class RepairerAgentWithTools(LangGraphAgent[CoderOutput]):
    """
    带测试运行工具的代码修复代理
    
    支持多轮对话和快速测试验证
    """

    def __init__(self):
        super().__init__(agent_name="RepairerAgentWithTools")
        self.state: Optional[RepairerState] = None

    @property
    def system_prompt(self) -> str:
        return """你是 OmniFlowAI 的代码修复专家（增强版）。你的任务是根据测试失败日志修复代码。

【核心能力】
1. 分析错误日志，找出代码问题
2. 生成精确的修复代码（search_block/replace_block 格式）
3. **运行测试验证修复效果**（使用 run_tests 工具）
4. 根据测试结果继续修复（支持多轮对话）

【修复流程】
1. 阅读错误日志和代码上下文
2. 分析问题根源
3. 生成修复代码
4. **调用 run_tests 工具运行测试**
5. 如果测试通过 → 完成修复
6. 如果测试失败 → 分析新错误，继续修复（最多3轮）

【工具使用】
你有以下工具可用：
- run_tests: 运行测试验证修复效果
  参数: test_path (可选，默认为 "backend/tests/ai_generated")
  返回: {"success": true/false, "logs": "测试日志", "failed_tests": [...]}

【输出格式】
你必须输出 JSON 格式，包含：
{
  "files": [
    {
      "file_path": "backend/app/xxx.py",
      "change_type": "modify",
      "search_block": "旧代码",
      "replace_block": "新代码",
      "description": "修复说明"
    }
  ],
  "summary": "修复总结",
  "need_test": true  // 是否需要运行测试
}

【多轮对话规则】
1. 每轮修复后，系统会自动运行测试
2. 如果测试失败，你会收到新的错误日志
3. 基于新的错误日志继续修复
4. 最多3轮，如果仍未通过会返回当前进度

【重要提示】
- 每次只修复明确的问题
- 保留完整的 search_block 和 replace_block
- 如果多轮修复后仍有问题，如实报告
- 不要编造测试结果
"""

    async def run_tests_tool(self, test_path: str = "backend/tests/ai_generated") -> Dict[str, Any]:
        """
        运行测试工具
        
        Args:
            test_path: 测试路径，默认为新生成的测试目录
            
        Returns:
            Dict: 测试结果
        """
        if not self.state or not self.state.file_service:
            return {
                "success": False,
                "error": "文件服务未初始化",
                "logs": "",
                "failed_tests": []
            }
        
        pipeline_id = self.state.pipeline_id
        
        logger.info(f"[RepairerAgent] 运行测试: {test_path}")
        
        try:
            # 在沙箱中运行测试
            exec_result = await sandbox_manager.exec(
                pipeline_id,
                f"cd /workspace && PYTHONPATH=/workspace/backend python -m pytest {test_path} -v --tb=short --color=no 2>&1",
                timeout=120
            )
            
            logs = exec_result.stdout + "\n" + exec_result.stderr
            success = exec_result.exit_code == 0
            
            # 提取失败的测试
            import re
            failed_tests = re.findall(r'FAILED\s+(\S+)', logs)
            
            logger.info(f"[RepairerAgent] 测试结果: success={success}, failed={len(failed_tests)}")
            
            return {
                "success": success,
                "exit_code": exec_result.exit_code,
                "logs": logs[:2000],  # 限制日志长度
                "failed_tests": failed_tests,
                "error": None if success else f"{len(failed_tests)} 个测试失败"
            }
            
        except Exception as e:
            logger.error(f"[RepairerAgent] 运行测试失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "logs": str(e),
                "failed_tests": []
            }

    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt（支持多轮对话上下文）
        """
        fix_order = state.get("fix_order", {})
        target_files = state.get("target_files", {})
        repairer_state = state.get("repairer_state")
        
        # 提取关键信息
        failed_tests = fix_order.get("failed_tests", [])
        error_logs = fix_order.get("error_logs", "")
        
        # 构建文件内容部分
        files_section = []
        for path, content in target_files.items():
            numbered_lines = [f"{i+1:04d} | {line}" for i, line in enumerate(content.splitlines())]
            numbered_content = "\n".join(numbered_lines)
            files_section.append(f"""【文件: {path}】
```python
{numbered_content}
```""")
        
        files_str = "\n\n".join(files_section)
        
        # 构建 prompt
        prompt_parts = ["【修复任务】"]
        
        # 添加对话历史（如果有）
        if repairer_state and repairer_state.conversation_history:
            prompt_parts.append(repairer_state.get_context_for_prompt())
            prompt_parts.append(f"\n\n【第 {repairer_state.current_round + 1} 轮修复】")
        
        # 添加当前错误信息
        if repairer_state and repairer_state.current_round > 0:
            # 多轮对话中的新错误
            prompt_parts.append(f"\n【新的测试错误】")
            prompt_parts.append(f"上一轮修复后，测试仍然失败：")
            prompt_parts.append(f"```\n{repairer_state.last_test_output[:1500]}\n```")
        else:
            # 第一轮
            prompt_parts.append(f"\n【失败的测试】")
            if failed_tests:
                prompt_parts.append("\n".join(f"- {test}" for test in failed_tests))
            else:
                prompt_parts.append("多个测试失败，详见错误日志")
            
            prompt_parts.append(f"\n【错误日志】")
            prompt_parts.append(f"```\n{error_logs}\n```")
        
        prompt_parts.append(f"\n【目标文件】")
        prompt_parts.append(files_str)
        
        prompt_parts.append(f"""
【修复要求】
1. 分析错误原因，生成修复代码
2. 使用 search_block 和 replace_block 格式
3. 输出 JSON 格式，设置 "need_test": true
4. 系统会自动运行测试并反馈结果
5. 如果测试仍失败，你会收到新的错误日志继续修复

当前轮次: {repairer_state.current_round + 1 if repairer_state else 1}/3
""")
        
        return "\n".join(prompt_parts)

    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出"""
        return self._parse_json_response(response)

    def validate_output(self, output: Dict[str, Any]) -> CoderOutput:
        """
        校验输出为 Pydantic 模型

        Args:
            output: 解析后的输出字典

        Returns:
            CoderOutput: 校验后的模型实例
        """
        return CoderOutput.model_validate(output)

    async def execute_with_tools(
        self,
        pipeline_id: int,
        stage_name: str,
        fix_order: Dict[str, Any],
        target_files: Dict[str, str],
        file_service: Optional[Any] = None,
        max_rounds: int = 3
    ) -> Dict[str, Any]:
        """
        执行带工具的修复（支持多轮对话）
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            fix_order: 修复工单
            target_files: 目标文件内容
            file_service: 文件服务
            max_rounds: 最大修复轮数
            
        Returns:
            Dict: 修复结果
        """
        # 初始化状态
        self.state = RepairerState(
            fix_order=fix_order,
            target_files=target_files,
            file_service=file_service,
            pipeline_id=pipeline_id,
            max_rounds=max_rounds
        )
        
        all_files_modified = []
        
        for round_num in range(max_rounds):
            logger.info(f"[RepairerAgent] 开始第 {round_num + 1}/{max_rounds} 轮修复")
            
            # 构建状态
            state = {
                "fix_order": fix_order,
                "target_files": target_files,
                "repairer_state": self.state
            }
            
            # 执行修复
            result = await self.execute(
                pipeline_id=pipeline_id,
                stage_name=stage_name,
                initial_state=state
            )
            
            if not result.get("success"):
                logger.error(f"[RepairerAgent] 第 {round_num + 1} 轮修复失败")
                return result
            
            output = result.get("output", {})
            files_modified = output.get("files", [])
            all_files_modified.extend(files_modified)
            
            # 写入修复到沙箱
            if file_service and files_modified:
                for file_obj in files_modified:
                    file_path = file_obj.get("file_path", "")
                    search_block = file_obj.get("search_block", "")
                    replace_block = file_obj.get("replace_block", "")
                    
                    if search_block and replace_block:
                        clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                        current_result = await file_service.read_file(clean_path)
                        
                        if current_result.exists and current_result.content:
                            new_content = current_result.content.replace(search_block, replace_block, 1)
                            await file_service.write_file(clean_path, new_content)
            
            # 检查是否需要运行测试
            need_test = output.get("need_test", True)
            if not need_test:
                logger.info(f"[RepairerAgent] 第 {round_num + 1} 轮修复完成，跳过测试")
                break
            
            # 运行测试
            test_result = await self.run_tests_tool()
            
            # 记录到对话历史
            self.state.add_round(
                user_message=self.build_user_prompt(state),
                assistant_response=json.dumps(output, ensure_ascii=False),
                test_result=test_result
            )
            
            # 检查测试结果
            if test_result.get("success"):
                logger.info(f"[RepairerAgent] 第 {round_num + 1} 轮修复后测试通过！")
                return {
                    "success": True,
                    "output": {
                        "files": all_files_modified,
                        "summary": f"修复成功，经过 {round_num + 1} 轮修复后测试通过",
                        "rounds": round_num + 1
                    },
                    "test_result": test_result
                }
            else:
                # 测试失败，准备下一轮
                self.state.last_test_output = test_result.get("logs", "")
                logger.warning(f"[RepairerAgent] 第 {round_num + 1} 轮修复后测试仍失败，准备下一轮...")
                
                # 更新 fix_order 为新的错误
                fix_order = {
                    "type": "fix_order",
                    "category": "code_bug",
                    "source": "RepairerAgent",
                    "failed_tests": test_result.get("failed_tests", []),
                    "error_logs": test_result.get("logs", ""),
                    "fix_hint": "上一轮修复未完全解决问题，请根据新的错误日志继续修复"
                }
        
        # 达到最大轮数仍未通过
        logger.warning(f"[RepairerAgent] 达到最大轮数 {max_rounds}，测试仍未通过")
        return {
            "success": False,
            "output": {
                "files": all_files_modified,
                "summary": f"经过 {max_rounds} 轮修复，测试仍未通过",
                "rounds": max_rounds
            },
            "error": "达到最大修复轮数",
            "last_test_result": self.state.test_results[-1] if self.state.test_results else None
        }


# 便捷函数
async def repair_code_with_tools(
    fix_order: Dict[str, Any],
    target_files: Dict[str, str],
    file_service: Optional[Any] = None,
    pipeline_id: int = 0,
    max_rounds: int = 3
) -> Dict[str, Any]:
    """
    便捷函数：使用工具修复代码（支持多轮对话）
    
    Args:
        fix_order: 修复工单
        target_files: 完整文件内容字典
        file_service: SandboxFileService 实例
        pipeline_id: Pipeline ID
        max_rounds: 最大修复轮数
        
    Returns:
        Dict[str, Any]: 修复结果
    """
    agent = RepairerAgentWithTools()
    
    if not target_files:
        return {
            "success": False,
            "error": "必须提供 target_files 参数"
        }
    
    return await agent.execute_with_tools(
        pipeline_id=pipeline_id,
        stage_name="REPAIR",
        fix_order=fix_order,
        target_files=target_files,
        file_service=file_service,
        max_rounds=max_rounds
    )
