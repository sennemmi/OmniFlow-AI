# app/agents/architect_editor_orchestrator.py

"""
Architect → Editor 编排器
实现架构师和编辑者的协作流程
"""

import json
import logging
from typing import Dict, Any, List, Optional

from app.agents.coder_architect import ArchitectCoderAgent
from app.agents.coder_editor import EditorCoderAgent
from app.service.snapshot_service import get_snapshot_service
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class ArchitectEditorOrchestrator:
    """
    Architect/Editor 分离编排器

    Phase 1: Architect 分析需求并生成 edit_plan
    Phase 2: Editor 逐条执行 edit_plan
    """

    def __init__(self, pipeline_id: int):
        self.pipeline_id = pipeline_id
        self.snapshot = get_snapshot_service(pipeline_id)
        self.architect = ArchitectCoderAgent()
        self.editor = EditorCoderAgent()

    async def execute(
        self,
        design_output: Dict[str, Any],
        project_path: str,
        file_service=None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        执行 Architect → Editor 流程

        Args:
            design_output: 技术方案输出
            project_path: 项目路径
            file_service: SandboxFileService 实例
            max_retries: 最大重试次数

        Returns:
            Dict: 执行结果
        """
        try:
            await push_log(
                self.pipeline_id,
                "info",
                "🏗️ 启动 Architect → Editor 分离流程",
                stage="CODING"
            )

            # 设置 file_service
            if file_service:
                self.architect.set_file_service(file_service)
                self.editor.set_file_service(file_service)

            # ========== Phase 1: Architect 分析 ==========
            await push_log(
                self.pipeline_id,
                "info",
                "📐 Phase 1: Architect 分析需求并生成编辑计划...",
                stage="CODING"
            )

            architect_result = await self.architect.execute(
                pipeline_id=self.pipeline_id,
                stage_name="ARCHITECT_PLAN",
                initial_state={
                    "design_output": design_output,
                    "project_path": project_path
                }
            )

            if not architect_result.get("success"):
                logger.error(f"[ArchitectEditor] Architect 阶段失败")
                await push_log(
                    self.pipeline_id,
                    "error",
                    "❌ Architect 分析失败",
                    stage="CODING"
                )
                return {
                    "success": False,
                    "error": "Architect 分析失败",
                    "phase": "architect",
                    "details": architect_result
                }

            # 提取 edit_plan
            output = architect_result.get("output", {})
            edit_plan = output.get("files", [])  # Architect 输出在 files 字段

            if not edit_plan:
                logger.error(f"[ArchitectEditor] Architect 没有生成 edit_plan")
                await push_log(
                    self.pipeline_id,
                    "error",
                    "❌ Architect 没有生成编辑计划",
                    stage="CODING"
                )
                return {
                    "success": False,
                    "error": "Architect 没有生成 edit_plan",
                    "phase": "architect"
                }

            await push_log(
                self.pipeline_id,
                "info",
                f"📋 Architect 生成了 {len(edit_plan)} 个编辑指令",
                stage="CODING"
            )

            # 打印 edit_plan 摘要
            for i, action in enumerate(edit_plan[:5]):
                await push_log(
                    self.pipeline_id,
                    "info",
                    f"  {i+1}. {action.get('action', 'unknown')} - {action.get('file_path', 'unknown')}",
                    stage="CODING"
                )

            # ========== Phase 2: Editor 执行 ==========
            await push_log(
                self.pipeline_id,
                "info",
                "🔨 Phase 2: Editor 执行编辑计划...",
                stage="CODING"
            )

            # 保存编辑前快照
            await self.snapshot.checkpoint("before_editor")

            # 逐条执行 edit_plan
            execution_results = []
            success_count = 0
            failure_count = 0

            for i, action in enumerate(edit_plan):
                # 保存当前步骤前的快照
                checkpoint_name = f"before_edit_{i}"
                await self.snapshot.checkpoint(checkpoint_name)

                await push_log(
                    self.pipeline_id,
                    "info",
                    f"🔧 执行编辑指令 {i+1}/{len(edit_plan)}: {action.get('action', 'unknown')}",
                    stage="CODING"
                )

                # 执行单条指令
                editor_result = await self.editor.execute(
                    pipeline_id=self.pipeline_id,
                    stage_name="EDITOR_EXECUTE",
                    initial_state={
                        "current_action": action,
                        "project_path": project_path
                    }
                )

                if editor_result.get("success"):
                    success_count += 1
                    execution_results.append({
                        "index": i,
                        "action": action,
                        "success": True,
                        "output": editor_result.get("output", {})
                    })
                    await push_log(
                        self.pipeline_id,
                        "success",
                        f"✅ 指令 {i+1} 执行成功",
                        stage="CODING"
                    )
                else:
                    failure_count += 1
                    execution_results.append({
                        "index": i,
                        "action": action,
                        "success": False,
                        "error": editor_result.get("error", "未知错误"),
                        "details": editor_result
                    })
                    await push_log(
                        self.pipeline_id,
                        "warning",
                        f"⚠️ 指令 {i+1} 执行失败: {editor_result.get('error', '未知错误')}",
                        stage="CODING"
                    )

                    # 【原子撤销】回退到上一个成功的 commit
                    await push_log(
                        self.pipeline_id,
                        "info",
                        f"🔄 执行原子撤销，回退到指令 {i} 的状态...",
                        stage="CODING"
                    )

                    # 获取当前 commit 历史
                    commit_history = await self.snapshot.get_commit_history(5)
                    logger.info(f"[ArchitectEditor] 当前 commit 历史: {commit_history}")

                    # 原子撤销：回退 1 步（撤销失败的修改）
                    atomic_rollback_success = await self.snapshot.atomic_rollback(steps=1)

                    if atomic_rollback_success:
                        await push_log(
                            self.pipeline_id,
                            "info",
                            f"✅ 已原子撤销到上一个 commit",
                            stage="CODING"
                        )

                        # 将失败原因反馈给 Architect
                        failure_feedback = {
                            "failed_action": action,
                            "error": editor_result.get("error", "未知错误"),
                            "index": i,
                            "suggestion": f"指令 {i+1} 执行失败，请调整编辑策略"
                        }

                        # 如果失败次数未达上限，让 Architect 重新规划
                        if failure_count < max_retries:
                            await push_log(
                                self.pipeline_id,
                                "info",
                                f"🔄 请求 Architect 重新规划剩余指令...",
                                stage="CODING"
                            )

                            # 获取已成功的操作数
                            remaining_plan = edit_plan[i+1:]

                            # 让 Architect 基于失败反馈重新规划
                            replan_result = await self._replan_with_feedback(
                                design_output=design_output,
                                project_path=project_path,
                                completed_actions=execution_results[:i],
                                failed_action=action,
                                remaining_plan=remaining_plan
                            )

                            if replan_result.get("success"):
                                # 使用新的 edit_plan 继续
                                new_plan = replan_result.get("new_plan", [])
                                if new_plan:
                                    await push_log(
                                        self.pipeline_id,
                                        "info",
                                        f"📋 Architect 生成了新的 {len(new_plan)} 个指令",
                                        stage="CODING"
                                    )
                                    # 更新 edit_plan，继续执行
                                    edit_plan = edit_plan[:i] + new_plan
                                    break  # 跳出当前循环，重新开始执行
                        else:
                            # 失败次数达到上限
                            await push_log(
                                self.pipeline_id,
                                "error",
                                f"❌ 连续失败 {failure_count} 次，达到上限",
                                stage="CODING"
                            )

                            return {
                                "success": False,
                                "error": f"Editor 执行失败次数过多 ({failure_count})",
                                "phase": "editor",
                                "execution_results": execution_results,
                                "success_count": success_count,
                                "failure_count": failure_count,
                                "rolled_back": True,
                                "failure_feedback": failure_feedback
                            }
                    else:
                        await push_log(
                            self.pipeline_id,
                            "warning",
                            "⚠️ 原子撤销失败",
                            stage="CODING"
                        )

            # ========== 总结 ==========
            all_success = failure_count == 0

            await push_log(
                self.pipeline_id,
                "success" if all_success else "warning",
                f"{'✅' if all_success else '⚠️'} Editor 执行完成: "
                f"成功 {success_count} 个, 失败 {failure_count} 个",
                stage="CODING"
            )

            # 【兼容性】构建与旧格式兼容的 files 列表
            # E2E 测试脚本使用 extract_code_files 期望 {"files": [...]} 格式
            compatible_files = []
            for exec_result in execution_results:
                if exec_result.get("success"):
                    action = exec_result.get("action", {})
                    compatible_files.append({
                        "file_path": action.get("file_path", ""),
                        "change_type": "modify",
                        "description": action.get("description", ""),
                        # 添加旧格式可能需要的字段
                        "search_block": action.get("search_block", ""),
                        "replace_block": action.get("replace_block", ""),
                        "content": action.get("content", "")
                    })

            return {
                "success": all_success,
                "phase": "complete",
                "edit_plan": edit_plan,
                "execution_results": execution_results,
                "success_count": success_count,
                "failure_count": failure_count,
                "summary": f"成功 {success_count} 个, 失败 {failure_count} 个",
                # 【兼容性】添加与旧格式兼容的 output 字段
                "output": {
                    "files": compatible_files,
                    "summary": f"Architect -> Editor 完成: 成功 {success_count} 个, 失败 {failure_count} 个"
                },
                "files": compatible_files  # 顶层也添加，便于直接访问
            }

        except Exception as e:
            logger.error(f"[ArchitectEditor] 编排异常: {e}")
            await push_log(
                self.pipeline_id,
                "error",
                f"❌ Architect → Editor 流程异常: {str(e)}",
                stage="CODING"
            )
            return {
                "success": False,
                "error": str(e),
                "phase": "unknown"
            }

    async def execute_single_action(
        self,
        action: Dict[str, Any],
        project_path: str,
        file_service=None
    ) -> Dict[str, Any]:
        """
        执行单条编辑指令

        Args:
            action: 单条编辑指令
            project_path: 项目路径
            file_service: SandboxFileService 实例

        Returns:
            Dict: 执行结果
        """
        try:
            # 设置 file_service
            if file_service:
                self.editor.set_file_service(file_service)

            # 执行单条指令
            editor_result = await self.editor.execute(
                pipeline_id=self.pipeline_id,
                stage_name="EDITOR_EXECUTE_SINGLE",
                initial_state={
                    "current_action": action,
                    "project_path": project_path
                }
            )

            return editor_result

        except Exception as e:
            logger.error(f"[ArchitectEditor] 单条指令执行异常: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _replan_with_feedback(
        self,
        design_output: Dict[str, Any],
        project_path: str,
        completed_actions: List[Dict],
        failed_action: Dict[str, Any],
        remaining_plan: List[Dict]
    ) -> Dict[str, Any]:
        """
        基于失败反馈让 Architect 重新规划

        Args:
            design_output: 原始技术方案
            project_path: 项目路径
            completed_actions: 已成功执行的操作
            failed_action: 失败的操作
            remaining_plan: 剩余未执行的操作

        Returns:
            Dict: 新的规划结果
        """
        try:
            await push_log(
                self.pipeline_id,
                "info",
                "🔄 Architect 正在基于失败反馈重新规划...",
                stage="CODING"
            )

            # 构建反馈上下文
            feedback_context = {
                "original_design": design_output,
                "completed_actions": completed_actions,
                "failed_action": failed_action,
                "remaining_plan": remaining_plan,
                "feedback": f"指令执行失败: {failed_action.get('error', '未知错误')}"
            }

            # 让 Architect 重新规划
            replan_result = await self.architect.execute(
                pipeline_id=self.pipeline_id,
                stage_name="ARCHITECT_REPLAN",
                initial_state={
                    "design_output": design_output,
                    "feedback_context": feedback_context,
                    "project_path": project_path,
                    "is_replan": True
                }
            )

            if not replan_result.get("success"):
                return {
                    "success": False,
                    "error": "Architect 重新规划失败"
                }

            # 提取新的 edit_plan
            output = replan_result.get("output", {})
            new_plan = output.get("files", [])

            return {
                "success": True,
                "new_plan": new_plan,
                "replan_summary": output.get("summary", "")
            }

        except Exception as e:
            logger.error(f"[ArchitectEditor] 重新规划异常: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# 便捷函数
async def execute_architect_editor_flow(
    design_output: Dict[str, Any],
    pipeline_id: int,
    project_path: str,
    file_service=None
) -> Dict[str, Any]:
    """
    便捷函数: 执行 Architect → Editor 流程

    Args:
        design_output: 技术方案输出
        pipeline_id: Pipeline ID
        project_path: 项目路径
        file_service: SandboxFileService 实例

    Returns:
        Dict: 执行结果
    """
    orchestrator = ArchitectEditorOrchestrator(pipeline_id)
    return await orchestrator.execute(
        design_output=design_output,
        project_path=project_path,
        file_service=file_service
    )
