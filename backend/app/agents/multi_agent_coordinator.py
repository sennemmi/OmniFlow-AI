"""
多 Agent 协作协调器
实现 CoderAgent 和 TestAgent 的并行执行

基于 LangGraph 的并行状态机实现
"""

import asyncio
from typing import Dict, List, Optional, TypedDict, Any
from concurrent.futures import ThreadPoolExecutor

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from app.agents.coder import coder_agent
from app.agents.tester import test_agent


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
    
    负责协调 CoderAgent 和 TestAgent 的并行执行：
    1. 调用 CoderAgent 生成代码
    2. 调用 TestAgent 生成测试（依赖 CoderAgent 输出）
    3. 合并输出结果
    
    注意：由于 TestAgent 需要 CoderAgent 的输出作为输入，
    所以实际上是顺序执行而非真正的并行
    
    使用 LangGraph 状态机管理协作流程
    """
    
    def __init__(self):
        self.graph = self._build_graph()
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态机"""
        
        workflow = StateGraph(MultiAgentState)
        
        # 添加节点
        workflow.add_node("execute_code_agent", self._execute_code_agent_node)
        workflow.add_node("execute_test_agent", self._execute_test_agent_node)
        workflow.add_node("merge_results", self._merge_results_node)
        
        # 添加边
        workflow.set_entry_point("execute_code_agent")
        workflow.add_edge("execute_code_agent", "execute_test_agent")
        workflow.add_edge("execute_test_agent", "merge_results")
        workflow.add_edge("merge_results", END)
        
        return workflow.compile()
    
    def _execute_code_agent_node(self, state: MultiAgentState) -> MultiAgentState:
        """执行 CoderAgent 节点"""
        
        design_output = state["design_output"]
        target_files = state["target_files"]
        
        # 使用线程池运行异步任务
        future = self.executor.submit(
            self._run_async_task,
            coder_agent.generate_code(design_output, target_files)
        )
        
        try:
            code_result = future.result(timeout=300)  # 5分钟超时
            
            if code_result["success"]:
                return {
                    **state,
                    "code_output": code_result["output"],
                    "code_error": None,
                }
            else:
                return {
                    **state,
                    "code_output": None,
                    "code_error": code_result["error"],
                }
        except Exception as e:
            return {
                **state,
                "code_output": None,
                "code_error": f"CoderAgent execution failed: {str(e)}",
            }
    
    def _execute_test_agent_node(self, state: MultiAgentState) -> MultiAgentState:
        """执行 TestAgent 节点"""
        
        # 如果代码生成失败，跳过测试生成
        if state["code_error"]:
            return {
                **state,
                "test_output": None,
                "test_error": None,
            }
        
        design_output = state["design_output"]
        code_output = state["code_output"]
        target_files = state["target_files"]
        
        # 使用线程池运行异步任务
        future = self.executor.submit(
            self._run_async_task,
            test_agent.generate_tests(design_output, code_output, target_files)
        )
        
        try:
            test_result = future.result(timeout=300)  # 5分钟超时
            
            if test_result["success"]:
                return {
                    **state,
                    "test_output": test_result["output"],
                    "test_error": None,
                }
            else:
                return {
                    **state,
                    "test_output": None,
                    "test_error": test_result["error"],
                }
        except Exception as e:
            return {
                **state,
                "test_output": None,
                "test_error": f"TestAgent execution failed: {str(e)}",
            }
    
    def _run_async_task(self, coro):
        """
        在线程中运行异步任务
        
        每个线程创建独立的事件循环，避免与主循环冲突
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    def _merge_results_node(self, state: MultiAgentState) -> MultiAgentState:
        """合并结果节点：修复元数据丢失问题"""
        
        # 1. 致命错误检查（仅限代码生成）
        if state.get("code_error"):
            return {**state, "error": f"Code generation failed: {state['code_error']}"}
        
        raw_code_output = state.get("code_output")
        raw_test_output = state.get("test_output")
        
        # 防御性转换
        code_output = raw_code_output if isinstance(raw_code_output, dict) else {}
        test_output = raw_test_output if isinstance(raw_test_output, dict) else {}
        
        # 2. 合并文件
        all_files = []
        if code_output.get("files"):
            all_files.extend(code_output["files"])
        
        # 3. 处理测试输出与非致命错误
        test_error = state.get("test_error")
        test_files = test_output.get("test_files") or test_output.get("files") or []  # 兼容不同 key
        
        if test_error:
            # 记录警告但不中断
            current_error = f"Test generation warning: {test_error}"
        else:
            all_files.extend(test_files)
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
                "coder": raw_code_output,
                "tester": raw_test_output
            }
        }
        
        return {
            **state,
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
        target_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        执行 CoderAgent 和 TestAgent
        
        策略：只要有代码输出，就认为执行成功（部分成功）
        测试生成失败不会导致整体失败
        
        Args:
            design_output: DesignerAgent 的输出内容
            target_files: 目标文件路径到内容的映射
            
        Returns:
            Dict: 包含合并后的结果或错误信息
        """
        initial_state: MultiAgentState = {
            "design_output": design_output,
            "target_files": target_files,
            "code_output": None,
            "code_error": None,
            "test_output": None,
            "test_error": None,
            "final_output": None,
            "error": None
        }
        
        # 执行状态机
        result = self.graph.invoke(initial_state)
        
        final_output = result.get("final_output")
        # 只有当完全没有生成文件，或者存在 code_error 时才判定为失败
        is_failed = result.get("code_error") is not None or not final_output or not final_output.get("files")
        
        if is_failed:
            return {
                "success": False,
                "error": result.get("error") or "No output generated",
                "output": final_output
            }
        
        # 成功时也返回 result["error"]，以便调用者看到测试生成的警告
        return {
            "success": True,
            "error": result.get("error"),
            "output": final_output
        }


# 单例实例
multi_agent_coordinator = MultiAgentCoordinator()
