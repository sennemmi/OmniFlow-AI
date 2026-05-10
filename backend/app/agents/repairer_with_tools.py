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

from app.agents.tool_agent import ToolUsingAgent
from app.agents.schemas import CoderOutput
from app.agents.repairer_with_tools_prompts import SYSTEM_PROMPT
from app.service.sandbox_manager import sandbox_manager
from app.utils.repair_utils import extract_pytest_failures

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


class RepairerAgentWithTools(ToolUsingAgent[CoderOutput]):
    """
    带测试运行工具的代码修复代理

    支持多轮对话和快速测试验证
    继承 ToolUsingAgent 以获得工具调用能力
    """

    def __init__(self):
        super().__init__(agent_name="RepairerAgentWithTools")
        self.state: Optional[RepairerState] = None

    def _get_agent_tools(self, project_path: str, pipeline_id: int = 0):
        """
        强制使用 repairer 角色获取工具列表

        【关键】直接调用父类方法但强制 agent_role="repairer"，
        确保 run_tests / install_dependency 始终可用，不依赖名称推断。
        """
        from app.agents.tools import get_agent_tools

        agent_role = "repairer"

        if (self._agent_tools is None or
            self._agent_tools.project_path != project_path or
            self._agent_tools._pipeline_id != pipeline_id or
            self._agent_tools._agent_role != agent_role):
            self._agent_tools = get_agent_tools(
                project_path,
                file_service=self._file_service,
                pipeline_id=pipeline_id,
                agent_role=agent_role
            )
            logger.info(
                f"[RepairerAgentWithTools] AgentTools 已创建/重建, "
                f"agent_role={agent_role!r}, "
                f"pipeline_id={pipeline_id}"
            )
        return self._agent_tools

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _extract_error_summary(self, logs: str) -> str:
        """从测试日志中提取错误摘要（使用统一的提取方法）"""
        # 使用统一的提取方法
        error_content = extract_pytest_failures(logs, max_chars=5000)

        # 提取失败测试数量
        import re
        failed_tests = re.findall(r'FAILED\s+(\S+)', logs)
        failed_count = len(failed_tests)

        summary = f"失败测试数: {failed_count}\n"
        summary += f"错误日志:\n"
        summary += "-" * 60 + "\n"
        summary += error_content + "\n"
        summary += "-" * 60

        if len(logs) > 5000:
            summary += f"\n(日志共 {len(logs)} 字符，显示关键部分)"

        return summary

    async def _run_test_with_dependency_handling(
        self,
        installed_packages: Dict[str, int],
        max_same_package_installs: int
    ) -> Dict[str, Any]:
        """
        【依赖安装循环】运行测试，自动处理依赖缺失

        逻辑：
        1. 运行测试
        2. 如果报错 ModuleNotFoundError，提取包名
        3. 检查该包是否已连续安装超过限制次数
        4. 安装依赖
        5. 重新运行测试（循环直到没有新的依赖缺失或测试通过）

        Args:
            installed_packages: 已安装依赖及其安装次数
            max_same_package_installs: 同一依赖最多安装次数

        Returns:
            Dict: 最终测试结果
        """
        import re

        MAX_DEPENDENCY_RETRIES = 10  # 全局安全上限，防止极端情况下的死循环
        retry_count = 0

        while retry_count < MAX_DEPENDENCY_RETRIES:
            retry_count += 1
            # 运行测试
            test_result = await self.run_tests_tool()

            # 如果测试通过，直接返回
            if test_result.get("success"):
                return test_result

            # 检查是否是依赖缺失错误
            logs = test_result.get("logs", "")
            module_not_found_match = re.search(
                r"ModuleNotFoundError: No module named ['\"](\w+)['\"]",
                logs
            )

            if not module_not_found_match:
                # 不是依赖缺失错误，返回测试结果
                return test_result

            # 提取缺失的包名
            package_name = module_not_found_match.group(1)
            print(f"\n[RepairerAgent] 📦 检测到依赖缺失: {package_name}")

            # 检查该包是否已连续安装超过限制次数
            install_count = installed_packages.get(package_name, 0)
            if install_count >= max_same_package_installs:
                error_msg = (
                    f"依赖安装失败: 连续 {max_same_package_installs} 次尝试安装 '{package_name}' "
                    f"仍未解决问题。可能是包名错误或网络问题。"
                )
                logger.error(f"[RepairerAgent] {error_msg}")
                print(f"[RepairerAgent] ❌ {error_msg}")
                # 返回包含错误信息的测试结果
                return {
                    "success": False,
                    "error": error_msg,
                    "logs": logs,
                    "dependency_error": True,
                    "failed_package": package_name
                }

            # 安装依赖
            print(f"[RepairerAgent] 🔄 正在安装依赖 ({install_count + 1}/{max_same_package_installs} 次)...")
            install_result = await self.install_dependency_tool(package_name)

            if not install_result.get("success"):
                # 安装失败，记录并继续（可能网络问题，下次重试）
                logger.warning(f"[RepairerAgent] 依赖 {package_name} 安装失败: {install_result.get('message')}")
                print(f"[RepairerAgent] ⚠️ 依赖安装失败，将重试...")

            # 记录安装次数
            installed_packages[package_name] = install_count + 1

            # 安装后立即重新运行测试（继续循环）
            print(f"[RepairerAgent] 🧪 依赖安装完成，重新运行测试...")

        # 安全兜底：达到全局重试上限仍未解决
        logger.error(
            f"[RepairerAgent] 依赖安装循环达到全局上限 {MAX_DEPENDENCY_RETRIES} 次，强制退出"
        )
        return {
            "success": False,
            "error": f"依赖安装重试达到上限 ({MAX_DEPENDENCY_RETRIES} 次)，可能存在无法解决的依赖问题",
            "dependency_error": True
        }

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
        print(f"\n[RepairerAgent] 🧪 运行测试: {test_path}")

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
            
            # 【调试】提取收集到的测试数量
            collected_match = re.search(r'collected\s+(\d+)\s+item', logs)
            collected_count = int(collected_match.group(1)) if collected_match else 0
            
            # 【调试】提取错误类型
            errors_match = re.search(r'(\d+)\s+error', logs, re.IGNORECASE)
            errors_count = int(errors_match.group(1)) if errors_match else 0
            
            # 【调试】提取 passed 数量
            passed_match = re.search(r'(\d+)\s+passed', logs, re.IGNORECASE)
            passed_count = int(passed_match.group(1)) if passed_match else 0

            # 【调试】打印详细统计
            print(f"[RepairerAgent] 📊 测试统计:")
            print(f"  - 退出码: {exec_result.exit_code}")
            print(f"  - 收集到: {collected_count} 个测试")
            print(f"  - 通过: {passed_count} 个")
            print(f"  - 失败: {len(failed_tests)} 个")
            print(f"  - 错误: {errors_count} 个")
            print(f"  - 成功: {success}")

            # 提取错误摘要
            error_summary = ""
            if not success:
                if failed_tests:
                    # 有测试失败
                    error_summary = self._extract_error_summary(logs)
                    print(f"\n[RepairerAgent] ❌ 测试失败摘要:")
                elif errors_count > 0:
                    # 测试收集/导入错误
                    error_summary = self._extract_error_summary(logs)
                    print(f"\n[RepairerAgent] ❌ 测试收集错误（导入失败）:")
                elif collected_count == 0:
                    # 没有收集到任何测试
                    error_summary = "没有收集到任何测试，可能是测试文件路径错误或文件为空"
                    print(f"\n[RepairerAgent] ⚠️ 警告: {error_summary}")
                else:
                    # 其他原因导致失败
                    error_summary = f"测试退出码非0，但未识别到失败原因。日志:\n{logs[:1000]}"
                    print(f"\n[RepairerAgent] ❌ 未知错误:")
                
                print("-" * 60)
                print(error_summary[:2000])
                print("-" * 60)

            logger.info(f"[RepairerAgent] 测试结果: success={success}, collected={collected_count}, passed={passed_count}, failed={len(failed_tests)}, errors={errors_count}")

            return {
                "success": success,
                "exit_code": exec_result.exit_code,
                "logs": logs[:3000],  # 增加日志长度限制
                "failed_tests": failed_tests,
                "collected_count": collected_count,
                "passed_count": passed_count,
                "errors_count": errors_count,
                "error": None if success else f"测试失败: {len(failed_tests)} failed, {errors_count} errors, {passed_count} passed",
                "error_summary": error_summary
            }

        except Exception as e:
            logger.error(f"[RepairerAgent] 运行测试失败: {e}")
            print(f"[RepairerAgent] ❌ 运行测试时发生异常: {e}")
            return {
                "success": False,
                "error": str(e),
                "logs": str(e),
                "failed_tests": [],
                "error_summary": f"运行测试时发生异常: {e}"
            }

    async def install_dependency_tool(self, package_name: str) -> Dict[str, Any]:
        """
        【新增】安装 Python 依赖包工具

        Args:
            package_name: 依赖包名称（如 "python-jose", "passlib", "bcrypt"）

        Returns:
            Dict: 安装结果
        """
        if not self.state:
            return {
                "success": False,
                "message": "状态未初始化"
            }

        pipeline_id = self.state.pipeline_id

        logger.info(f"[RepairerAgent] 安装依赖: {package_name}")
        print(f"[RepairerAgent] 📦 正在安装依赖: {package_name}...")

        try:
            # 在沙箱中安装依赖
            exec_result = await sandbox_manager.exec(
                pipeline_id,
                f"pip install {package_name} --quiet 2>&1",
                timeout=120
            )

            logs = exec_result.stdout + "\n" + exec_result.stderr
            success = exec_result.exit_code == 0

            if success:
                message = f"✅ 依赖 {package_name} 安装成功"
                logger.info(f"[RepairerAgent] {message}")
                print(f"[RepairerAgent] {message}")
            else:
                message = f"❌ 依赖 {package_name} 安装失败: {logs[:500]}"
                logger.error(f"[RepairerAgent] {message}")
                print(f"[RepairerAgent] {message}")

            return {
                "success": success,
                "message": message,
                "logs": logs[:1000]
            }

        except Exception as e:
            message = f"安装依赖时出错: {str(e)}"
            logger.error(f"[RepairerAgent] {message}")
            return {
                "success": False,
                "message": message,
                "logs": str(e)
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
        
        # 构建文件内容部分（带角色标签）
        files_section = []
        for path, content in target_files.items():
            # 为文件打上角色标签
            if "app/" in path:
                role = "【被测业务代码】"
            elif "tests/" in path:
                role = "【测试验证代码】"
            else:
                role = "【辅助文件】"

            numbered_lines = [f"{i+1:04d} | {line}" for i, line in enumerate(content.splitlines())]
            numbered_content = "\n".join(numbered_lines)
            files_section.append(f"""【文件路径】: {path}
【文件角色】: {role}
【代码内容】:
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
        max_rounds: int = 3,
        debugger: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        执行带工具的修复（支持多轮对话和依赖自动安装）

        【新增功能】
        1. 检测 ModuleNotFoundError 错误
        2. 自动调用 install_dependency 安装缺失的依赖
        3. 安装后立即重新运行测试
        4. 如果有新的依赖缺失，继续安装（无次数限制）
        5. 如果连续三次安装相同依赖，抛出错误

        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            fix_order: 修复工单
            target_files: 目标文件内容
            file_service: 文件服务
            max_rounds: 最大修复轮数
            debugger: AgentDebugger 实例（可选，用于保存每轮调试信息）

        Returns:
            Dict: 修复结果
        """
        # 【关键修复】为 RepairerAgent 注入 SandboxFileService，确保工具调用使用沙箱模式
        if file_service:
            self.set_file_service(file_service)

        # 初始化状态
        self.state = RepairerState(
            fix_order=fix_order,
            target_files=target_files,
            file_service=file_service,
            pipeline_id=pipeline_id,
            max_rounds=max_rounds
        )

        all_files_modified = []

        # 【依赖安装跟踪】记录已安装的依赖及其次数
        installed_packages: Dict[str, int] = {}
        MAX_SAME_PACKAGE_INSTALLS = 3  # 同一依赖最多安装次数

        # 【修复3】记录上一轮写入的文件内容哈希，用于检测死循环
        last_written_hashes = {}
        stagnation_count = 0  # 停滞计数器

        for round_num in range(max_rounds):
            logger.info(f"[RepairerAgent] 开始第 {round_num + 1}/{max_rounds} 轮修复")

            # 【关键】每轮循环开始前检查 Pipeline 是否已被终止
            from app.service.pipeline import PipelineService
            if await PipelineService._check_pipeline_terminated(pipeline_id):
                logger.warning(f"[RepairerAgent] Pipeline {pipeline_id} 已终止，退出修复循环")
                return {
                    "success": False,
                    "error": "Pipeline terminated",
                    "output": {
                        "files": all_files_modified,
                        "summary": f"Pipeline 在修复第 {round_num + 1} 轮被终止",
                        "rounds": round_num + 1
                    }
                }

            # 【修复】每轮循环开始前，重新从沙箱读取所有目标文件的最新内容
            if round_num > 0 and file_service:
                refreshed_count = 0
                for file_path in list(target_files.keys()):
                    try:
                        read_res = await file_service.read_file(file_path)
                        if read_res.exists and read_res.content:
                            target_files[file_path] = read_res.content
                            refreshed_count += 1
                    except Exception as e:
                        logger.warning(f"[RepairerAgent] 刷新文件失败 {file_path}: {e}")
                if refreshed_count > 0:
                    logger.info(f"[RepairerAgent] 已刷新 {refreshed_count} 个文件的最新内容")

            # 构建状态
            state = {
                "fix_order": fix_order,
                "target_files": target_files,
                "repairer_state": self.state
            }

            # 【修复3】如果检测到停滞，注入提示信息
            if stagnation_count >= 1:
                print(f"\n[RepairerAgent] 检测到修改停滞，强制切换修复策略...")
                fix_order["fix_hint"] = (
                    "【重要】上一轮修改无效，文件内容未发生变化。\n"
                    "请换一个方向：\n"
                    "1. 如果之前改的是被测代码，这轮尝试修改测试文件\n"
                    "2. 检查是否是 async/await 问题（测试缺 await）\n"
                    "3. 检查断言值是否与 interface_specs 契约一致\n"
                    "4. 尝试修改 mock 配置或 patch 路径"
                )

            # 执行修复（带重试逻辑）
            max_llm_retries = 3  # LLM 空内容重试次数
            llm_retry_count = 0
            result = None

            while llm_retry_count < max_llm_retries:
                # 【关键】每次 LLM 调用前检查 Pipeline 是否已被终止
                if await PipelineService._check_pipeline_terminated(pipeline_id):
                    logger.warning(f"[RepairerAgent] Pipeline {pipeline_id} 已终止，退出 LLM 重试循环")
                    return {
                        "success": False,
                        "error": "Pipeline terminated",
                        "output": {
                            "files": all_files_modified,
                            "summary": f"Pipeline 在 LLM 重试第 {llm_retry_count + 1} 次时被终止",
                            "rounds": round_num + 1
                        }
                    }

                result = await self.execute(
                    pipeline_id=pipeline_id,
                    stage_name=stage_name,
                    initial_state=state
                )

                # 检查是否是 LLM 返回空内容导致的失败
                error_msg = result.get("error", "")
                if "LLM 返回空内容" in error_msg or "无法从工具结果构建输出" in error_msg:
                    llm_retry_count += 1
                    logger.warning(f"[RepairerAgent] LLM 返回空内容，第 {llm_retry_count}/{max_llm_retries} 次重试...")
                    print(f"[RepairerAgent] ⚠️ LLM 返回空内容，进行第 {llm_retry_count} 次重试...")
                    # 短暂等待后重试
                    import asyncio
                    await asyncio.sleep(1)
                    continue
                else:
                    # 不是空内容问题，跳出重试循环
                    break
            
            # 如果重试后仍然失败
            if llm_retry_count >= max_llm_retries and not result.get("success"):
                logger.error(f"[RepairerAgent] LLM 重试 {max_llm_retries} 次后仍然失败")
                return {
                    "success": False,
                    "error": f"LLM 返回空内容，重试 {max_llm_retries} 次后仍然失败",
                    "output": {
                        "files": all_files_modified,
                        "summary": f"LLM 返回空内容，重试 {max_llm_retries} 次后仍然失败",
                        "rounds": round_num + 1
                    }
                }

            # 【新增】保存每轮调试信息
            if debugger:
                debugger.save_agent_io(
                    agent_name="RepairerAgent",
                    stage=f"repair_round_{round_num + 1}",
                    input_data=state,
                    output_data=result,
                    metadata={"round": round_num + 1, "max_rounds": max_rounds, "llm_retries": llm_retry_count},
                    success=result.get("success", False),
                    error=result.get("error"),
                    tool_calls=result.get("tool_results", []),
                    system_prompt=self.system_prompt
                )

            if not result.get("success"):
                logger.error(f"[RepairerAgent] 第 {round_num + 1} 轮修复失败")
                return result

            output = result.get("output", {})
            files_modified = output.get("files", [])
            all_files_modified.extend(files_modified)

            # 写入修复到沙箱，并检测文件内容是否变化
            current_written_hashes = {}
            files_actually_changed = False

            if file_service and files_modified:
                for file_obj in files_modified:
                    file_path = file_obj.get("file_path", "")
                    search_block = file_obj.get("search_block", "")
                    replace_block = file_obj.get("replace_block", "")
                    # 【修复】获取完整内容（用于降级策略）
                    full_content = file_obj.get("content", "")

                    clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")

                    if search_block and replace_block:
                        current_result = await file_service.read_file(clean_path)

                        if current_result.exists and current_result.content:
                            # 计算文件内容哈希
                            import hashlib
                            old_hash = hashlib.md5(current_result.content.encode()).hexdigest()
                            new_content = current_result.content.replace(search_block, replace_block, 1)
                            new_hash = hashlib.md5(new_content.encode()).hexdigest()

                            current_written_hashes[clean_path] = new_hash

                            # 检查文件是否实际发生变化
                            if old_hash != new_hash:
                                files_actually_changed = True
                                write_result = await file_service.write_file(clean_path, new_content)
                                # 【P3: 防御性测试保护】检查写入是否被拦截
                                if not write_result.get("success") and write_result.get("blocked"):
                                    error_msg = f"🚫 修复被拦截: {write_result.get('error')}"
                                    logger.error(f"[RepairerAgent] {error_msg}")
                                    print(f"[RepairerAgent] {error_msg}")
                                    return {
                                        "success": False,
                                        "error": error_msg,
                                        "output": {
                                            "files": all_files_modified,
                                            "summary": f"第 {round_num + 1} 轮修复被拦截：尝试修改 defense 目录文件",
                                            "rounds": round_num + 1,
                                            "blocked": True
                                        }
                                    }
                                print(f"[RepairerAgent] 已修改: {clean_path}")
                            else:
                                print(f"[RepairerAgent] 警告: {clean_path} 内容未变化（search_block 可能不匹配）")
                                # 【修复】降级策略：如果提供了完整内容，直接全量写入
                                if full_content and full_content != current_result.content:
                                    write_result = await file_service.write_file(clean_path, full_content)
                                    # 【P3: 防御性测试保护】检查写入是否被拦截
                                    if not write_result.get("success") and write_result.get("blocked"):
                                        error_msg = f"🚫 修复被拦截: {write_result.get('error')}"
                                        logger.error(f"[RepairerAgent] {error_msg}")
                                        print(f"[RepairerAgent] {error_msg}")
                                        return {
                                            "success": False,
                                            "error": error_msg,
                                            "output": {
                                                "files": all_files_modified,
                                                "summary": f"第 {round_num + 1} 轮修复被拦截：尝试修改 defense 目录文件",
                                                "rounds": round_num + 1,
                                                "blocked": True
                                            }
                                        }
                                    files_actually_changed = True
                                    print(f"[RepairerAgent] 降级写入完整内容: {clean_path}")
                                elif full_content:
                                    print(f"[RepairerAgent] 完整内容与当前内容相同，跳过写入")
                    elif file_obj.get("change_type") == "add" or not search_block:
                        # 【新增】支持新增文件或全量覆盖
                        new_content = full_content or replace_block
                        if new_content:
                            import hashlib
                            current_result = await file_service.read_file(clean_path)
                            if current_result.exists and current_result.content == new_content:
                                print(f"[RepairerAgent] 警告: {clean_path} 内容未变化")
                            else:
                                write_result = await file_service.write_file(clean_path, new_content)
                                # 【P3: 防御性测试保护】检查写入是否被拦截
                                if not write_result.get("success") and write_result.get("blocked"):
                                    error_msg = f"🚫 修复被拦截: {write_result.get('error')}"
                                    logger.error(f"[RepairerAgent] {error_msg}")
                                    print(f"[RepairerAgent] {error_msg}")
                                    return {
                                        "success": False,
                                        "error": error_msg,
                                        "output": {
                                            "files": all_files_modified,
                                            "summary": f"第 {round_num + 1} 轮修复被拦截：尝试修改 defense 目录文件",
                                            "rounds": round_num + 1,
                                            "blocked": True
                                        }
                                    }
                                files_actually_changed = True
                                current_written_hashes[clean_path] = hashlib.md5(new_content.encode()).hexdigest()
                                print(f"[RepairerAgent] 已新建/全量覆盖: {clean_path}")

            # 【修复3】检测是否陷入死循环（文件内容未变化）
            if not files_actually_changed and files_modified:
                stagnation_count += 1
                print(f"[RepairerAgent] 警告: 本轮修改未产生实际变化（停滞计数: {stagnation_count}）")
            else:
                stagnation_count = 0  # 重置停滞计数器

            last_written_hashes = current_written_hashes

            # 检查是否需要运行测试
            need_test = output.get("need_test", True)
            if not need_test:
                logger.info(f"[RepairerAgent] 第 {round_num + 1} 轮修复完成，跳过测试")
                break

            # 【依赖安装循环】运行测试，如果依赖缺失则安装后重试
            test_result = await self._run_test_with_dependency_handling(
                installed_packages, MAX_SAME_PACKAGE_INSTALLS
            )

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
                        "rounds": round_num + 1,
                        "installed_packages": list(installed_packages.keys())
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
                    "error_summary": test_result.get("error_summary", ""),
                    "fix_hint": fix_order.get("fix_hint", "上一轮修复未完全解决问题，请根据新的错误日志继续修复")
                }

        # 达到最大轮数仍未通过
        logger.warning(f"[RepairerAgent] 达到最大轮数 {max_rounds}，测试仍未通过")
        return {
            "success": False,
            "output": {
                "files": all_files_modified,
                "summary": f"经过 {max_rounds} 轮修复，测试仍未通过",
                "rounds": max_rounds,
                "installed_packages": list(installed_packages.keys())
            },
            "error": "达到最大修复轮数",
            "last_test_result": self.state.test_results[-1] if self.state.test_results else None
        }

