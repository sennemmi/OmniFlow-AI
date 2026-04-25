"""
多 Agent 协作协调器
实现 CoderAgent 和 TestAgent 的协作执行

重构说明：
- 移除 ThreadPoolExecutor，使用纯异步执行
- CoderAgent 和 TestAgent 顺序执行（TestAgent 依赖 CoderAgent 输出）
- 保留结果合并逻辑
"""

import asyncio
import logging
from typing import Dict, List, Optional, TypedDict, Any

from pydantic import BaseModel, Field

from app.agents.coder import coder_agent
from app.agents.tester import test_agent

logger = logging.getLogger(__name__)


class MultiAgentState(TypedDict):
    """多 Agent 协作状态"""
    design_output: Dict[str, Any]
    target_files: Dict[str, str]
    
    # CoderAgent 输出
    code_output: Optional[Dict[str, Any]]
    code_error: Optional[str]
    
    # TestAgent 输出
    test_output: Optional[Dict[str, Any]]
    test_error: Optional[str]
    
    # 最终结果
    final_output: Optional[Dict[str, Any]]
    error: Optional[str]


class CodeAndTestOutput(BaseModel):
    """代码和测试输出组合"""
    code_files: List[Dict[str, Any]] = Field(description="代码文件列表")
    test_files: List[Dict[str, Any]] = Field(description="测试文件列表")
    code_summary: str = Field(description="代码生成摘要")
    test_summary: str = Field(description="测试生成摘要")
    dependencies_added: List[str] = Field(default_factory=list, description="新增依赖")
    tests_included: bool = Field(default=True, description="是否包含测试")


class MultiAgentCoordinator:
    """
    多 Agent 协作协调器
    
    负责协调 CoderAgent 和 TestAgent 的执行：
    1. 调用 CoderAgent 生成代码
    2. 调用 TestAgent 生成测试（依赖 CoderAgent 输出）
    3. 合并输出结果
    
    注意：TestAgent 需要 CoderAgent 的输出作为输入，所以是顺序执行
    """
    
    async def _execute_code_agent(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        执行 CoderAgent

        Args:
            design_output: DesignerAgent 的输出
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 包含 code_output 或 code_error
        """
        logger.info(f"MultiAgentCoordinator: 开始执行 CoderAgent", extra={
            "pipeline_id": pipeline_id,
            "files_count": len(target_files)
        })

        try:
            code_result = await coder_agent.generate_code(design_output, target_files, pipeline_id)

            if code_result["success"]:
                logger.info(f"MultiAgentCoordinator: CoderAgent 执行成功", extra={
                    "pipeline_id": pipeline_id
                })
                return {
                    "code_output": code_result["output"],
                    "code_error": None,
                }
            else:
                logger.error(f"MultiAgentCoordinator: CoderAgent 执行失败", extra={
                    "pipeline_id": pipeline_id,
                    "error": code_result["error"]
                })
                return {
                    "code_output": None,
                    "code_error": code_result["error"],
                }
        except Exception as e:
            logger.error(f"MultiAgentCoordinator: CoderAgent 执行异常", extra={
                "pipeline_id": pipeline_id,
                "error": str(e)
            })
            return {
                "code_output": None,
                "code_error": f"CoderAgent execution failed: {str(e)}",
            }
    
    async def _execute_test_agent(
        self,
        design_output: Dict[str, Any],
        code_output: Optional[Dict[str, Any]],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        执行 TestAgent

        Args:
            design_output: DesignerAgent 的输出
            code_output: CoderAgent 的输出
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 包含 test_output 或 test_error
        """
        # 如果代码生成失败，跳过测试生成
        if not code_output:
            logger.info(f"MultiAgentCoordinator: 跳过测试生成（代码生成失败）", extra={
                "pipeline_id": pipeline_id
            })
            return {
                "test_output": None,
                "test_error": None,
            }

        logger.info(f"MultiAgentCoordinator: 开始执行 TestAgent", extra={
            "pipeline_id": pipeline_id
        })

        try:
            test_result = await test_agent.generate_tests(design_output, code_output, target_files, pipeline_id)

            if test_result["success"]:
                logger.info(f"MultiAgentCoordinator: TestAgent 执行成功", extra={
                    "pipeline_id": pipeline_id
                })
                return {
                    "test_output": test_result["output"],
                    "test_error": None,
                }
            else:
                logger.warning(f"MultiAgentCoordinator: TestAgent 执行失败", extra={
                    "pipeline_id": pipeline_id,
                    "error": test_result["error"]
                })
                return {
                    "test_output": None,
                    "test_error": test_result["error"],
                }
        except Exception as e:
            logger.error(f"MultiAgentCoordinator: TestAgent 执行异常", extra={
                "pipeline_id": pipeline_id,
                "error": str(e)
            })
            return {
                "test_output": None,
                "test_error": f"TestAgent execution failed: {str(e)}",
            }
    
    def _merge_results(
        self,
        code_output: Optional[Dict[str, Any]],
        test_output: Optional[Dict[str, Any]],
        target_files: Dict[str, str],
        code_error: Optional[str] = None,
        test_error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        合并结果：修复元数据丢失问题，注入 original_content
        
        Args:
            code_output: CoderAgent 输出
            test_output: TestAgent 输出
            target_files: 原始文件内容映射
            code_error: 代码生成错误
            test_error: 测试生成错误
            
        Returns:
            Dict: 合并后的 final_output
        """
        # 1. 致命错误检查（仅限代码生成）
        if code_error:
            return {
                "final_output": None,
                "error": f"Code generation failed: {code_error}"
            }

        # 防御性转换
        code_output = code_output if isinstance(code_output, dict) else {}
        test_output = test_output if isinstance(test_output, dict) else {}

        # 2. 合并文件并注入 original_content
        all_files = []
        if code_output.get("files"):
            for f in code_output["files"]:
                # 核心修复：把 target_files 里的原始内容注入每个文件对象
                enriched = dict(f)  # 浅拷贝，不改原对象
                file_path = enriched.get("file_path", "")
                if "original_content" not in enriched:
                    enriched["original_content"] = target_files.get(file_path)  # None 表示新建文件
                all_files.append(enriched)

        # 3. 处理测试输出与非致命错误
        test_files = test_output.get("test_files") or test_output.get("files") or []  # 兼容不同 key

        if test_error:
            # 记录警告但不中断
            current_error = f"Test generation warning: {test_error}"
        else:
            # 测试文件同样注入 original_content（通常是 None，代表新建）
            for f in test_files:
                enriched = dict(f)
                file_path = enriched.get("file_path", "")
                if "original_content" not in enriched:
                    enriched["original_content"] = target_files.get(file_path)
                all_files.append(enriched)
            current_error = None

        # 4. 构建最终输出（确保 coverage_targets 等字段被提取）
        final_output = {
            "files": all_files,
            "summary": self._build_summary(code_output, test_output),
            "dependencies_added": list(set(
                code_output.get("dependencies_added", []) +
                test_output.get("dependencies_added", [])
            )),
            "tests_included": len(test_files) > 0,
            "code_summary": code_output.get("summary", ""),
            "test_summary": test_output.get("summary", "Skipped or failed"),
            # 关键修复：从 test_output 中准确获取 coverage_targets
            "coverage_targets": test_output.get("coverage_targets", []),
            "agent_outputs": {
                "coder": code_output,
                "tester": test_output
            }
        }

        return {
            "final_output": final_output,
            "error": current_error  # 保留非致命错误信息
        }
    
    def _build_summary(self, code_output: Optional[Dict], test_output: Optional[Dict]) -> str:
        """构建合并后的摘要"""
        
        parts = []
        
        if code_output and "summary" in code_output:
            parts.append(f"代码生成: {code_output['summary']}")
        
        if test_output and "summary" in test_output:
            parts.append(f"测试生成: {test_output['summary']}")
        
        if test_output and "coverage_targets" in test_output:
            coverage = test_output["coverage_targets"]
            if coverage:
                parts.append(f"测试覆盖: {len(coverage)} 个测试目标")
        
        return "\n".join(parts) if parts else "代码和测试生成完成"
    
    async def execute_parallel(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        执行 CoderAgent 和 TestAgent

        策略：
        1. 先执行 CoderAgent 生成代码
        2. 再执行 TestAgent 生成测试（依赖 CoderAgent 输出）
        3. 合并结果

        只要有代码输出，就认为执行成功（部分成功）
        测试生成失败不会导致整体失败

        Args:
            design_output: DesignerAgent 的输出内容
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 包含合并后的结果或错误信息
        """
        logger.info(f"MultiAgentCoordinator: 开始执行多 Agent 协作", extra={
            "pipeline_id": pipeline_id,
            "target_files_count": len(target_files)
        })

        # 1. 执行 CoderAgent
        code_result = await self._execute_code_agent(design_output, target_files, pipeline_id)

        # 2. 执行 TestAgent（依赖 CoderAgent 输出）
        test_result = await self._execute_test_agent(
            design_output,
            code_result.get("code_output"),
            target_files,
            pipeline_id
        )

        # 3. 合并结果
        merge_result = self._merge_results(
            code_result.get("code_output"),
            test_result.get("test_output"),
            target_files,
            code_result.get("code_error"),
            test_result.get("test_error")
        )

        final_output = merge_result.get("final_output")
        # 只有当完全没有生成文件，或者存在 code_error 时才判定为失败
        is_failed = code_result.get("code_error") is not None or not final_output or not final_output.get("files")

        if is_failed:
            logger.error(f"MultiAgentCoordinator: 多 Agent 执行失败", extra={
                "pipeline_id": pipeline_id,
                "error": merge_result.get("error")
            })
            return {
                "success": False,
                "error": merge_result.get("error") or "No output generated",
                "output": final_output
            }

        logger.info(f"MultiAgentCoordinator: 多 Agent 执行成功", extra={
            "pipeline_id": pipeline_id,
            "files_count": len(final_output.get("files", []))
        })

        # 成功时也返回 error，以便调用者看到测试生成的警告
        return {
            "success": True,
            "error": merge_result.get("error"),
            "output": final_output
        }


# 单例实例
multi_agent_coordinator = MultiAgentCoordinator()
