"""
Agent 协调服务 (AgentCoordinatorService)

统一 E2E 测试和 Pipeline 中的 Agent 调用上下文构建。
确保各 Agent 接收到的参数结构一致。
"""

import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

from app.core.sse_log_buffer import push_log
from app.core.config import settings

logger = logging.getLogger(__name__)


class AgentCoordinatorService:
    """
    统一的 Agent 协调服务

    职责：
    1. 构建 ArchitectAgent 调用上下文
    2. 构建 DesignerAgent 调用上下文
    3. 构建 CoderAgent 调用上下文
    4. 构建 TesterAgent 调用上下文
    5. 统一 injected_files 构建逻辑

    使用场景：
    - E2E 测试脚本
    - Pipeline 各 StageHandler
    - 任何需要调用 Agent 的地方
    """

    def __init__(self):
        pass

    async def build_architect_context(
        self,
        requirement: str,
        file_tree: Optional[Dict[str, Any]] = None,
        element_context: Optional[str] = None,
        pipeline_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        构建 ArchitectAgent 调用上下文

        Args:
            requirement: 需求描述
            file_tree: 文件树（可选）
            element_context: 元素上下文（可选）
            pipeline_id: Pipeline ID

        Returns:
            Dict: ArchitectAgent 输入参数
        """
        context = {
            "requirement": requirement,
            "file_tree": file_tree or {},
            "element_context": element_context,
            "pipeline_id": pipeline_id,
        }

        if pipeline_id:
            await push_log(
                pipeline_id,
                "info",
                f"📋 构建 ArchitectAgent 上下文 (file_tree: {len(file_tree or {})} items)",
                stage="REQUIREMENT"
            )

        return context

    async def build_designer_context(
        self,
        requirement: str,
        arch_output: Dict[str, Any],
        file_tree: Optional[Dict[str, Any]] = None,
        pipeline_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        构建 DesignerAgent 调用上下文

        Args:
            requirement: 需求描述
            arch_output: ArchitectAgent 输出
            file_tree: 文件树（可选）
            pipeline_id: Pipeline ID

        Returns:
            Dict: DesignerAgent 输入参数
        """
        # 提取 injected_files
        injected_files = arch_output.get("injected_files", {})

        context = {
            "requirement": requirement,
            "arch_output": arch_output,
            "file_tree": file_tree or {},
            "injected_files": injected_files,
            "pipeline_id": pipeline_id,
        }

        if pipeline_id:
            await push_log(
                pipeline_id,
                "info",
                f"📋 构建 DesignerAgent 上下文 (injected_files: {len(injected_files)} files)",
                stage="DESIGN"
            )

        return context

    async def build_coder_context(
        self,
        design_output: Dict[str, Any],
        affected_files: List[str],
        injected_files: Optional[Dict[str, str]] = None,
        pipeline_id: Optional[int] = None,
        error_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        构建 CoderAgent 调用上下文

        Args:
            design_output: 设计输出
            affected_files: 受影响的文件列表
            injected_files: 预注入的文件内容
            pipeline_id: Pipeline ID
            error_context: 错误上下文（用于修复模式）

        Returns:
            Dict: CoderAgent 输入参数
        """
        context = {
            "design_output": design_output,
            "pipeline_id": pipeline_id,
            "error_context": error_context,
            "injected_files": injected_files or {},
        }

        if pipeline_id:
            await push_log(
                pipeline_id,
                "info",
                f"📋 构建 CoderAgent 上下文 (affected_files: {len(affected_files)}, "
                f"injected_files: {len(injected_files or {})} files, "
                f"fix_mode: {bool(error_context)})",
                stage="CODING"
            )

        return context

    async def build_tester_context(
        self,
        design_output: Dict[str, Any],
        code_output: Dict[str, Any],
        target_files: Dict[str, Any],
        pipeline_id: Optional[int] = None,
        fix_mode: bool = False,
        fix_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        构建 TesterAgent 调用上下文

        Args:
            design_output: 设计输出
            code_output: 代码输出
            target_files: 目标文件
            pipeline_id: Pipeline ID
            fix_mode: 是否为修复模式
            fix_instruction: 修复指令

        Returns:
            Dict: TesterAgent 输入参数
        """
        context = {
            "design_output": design_output,
            "code_output": code_output,
            "target_files": target_files,
            "pipeline_id": pipeline_id,
        }

        if fix_mode and fix_instruction:
            context["design_output"]["fix_mode"] = True
            context["design_output"]["fix_instruction"] = fix_instruction

        if pipeline_id:
            await push_log(
                pipeline_id,
                "info",
                f"📋 构建 TesterAgent 上下文 (fix_mode: {fix_mode})",
                stage="UNIT_TESTING"
            )

        return context

    def extract_injected_files(
        self,
        arch_output: Dict[str, Any],
        design_output: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """
        统一提取 injected_files

        从 ArchitectAgent 或 DesignerAgent 的输出中提取 injected_files

        Args:
            arch_output: ArchitectAgent 输出
            design_output: DesignerAgent 输出（可选）

        Returns:
            Dict[str, str]: 文件路径 -> 文件内容的字典
        """
        injected_files = {}

        # 从 arch_output 提取
        if arch_output and "injected_files" in arch_output:
            arch_injected = arch_output.get("injected_files", {})
            if isinstance(arch_injected, dict):
                injected_files.update(arch_injected)

        # 从 design_output 提取（优先级更高）
        if design_output and "injected_files" in design_output:
            design_injected = design_output.get("injected_files", {})
            if isinstance(design_injected, dict):
                injected_files.update(design_injected)

        return injected_files

    def build_file_tree(
        self,
        project_path: str,
        max_depth: int = 3,
        ignore_patterns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        构建项目文件树

        Args:
            project_path: 项目路径
            max_depth: 最大深度
            ignore_patterns: 忽略模式列表

        Returns:
            Dict: 文件树结构
        """
        if ignore_patterns is None:
            ignore_patterns = [
                "__pycache__", "*.pyc", ".git", ".venv", "venv",
                "node_modules", ".pytest_cache", ".env"
            ]

        file_tree = {}
        base_path = Path(project_path)

        if not base_path.exists():
            return file_tree

        try:
            for item in base_path.rglob("*"):
                # 检查深度
                relative_path = item.relative_to(base_path)
                depth = len(relative_path.parts)
                if depth > max_depth:
                    continue

                # 检查忽略模式
                path_str = str(relative_path)
                if any(pattern in path_str for pattern in ignore_patterns):
                    continue

                # 添加到文件树
                if item.is_file():
                    file_tree[path_str] = {
                        "type": "file",
                        "size": item.stat().st_size,
                    }
                elif item.is_dir():
                    file_tree[path_str] = {
                        "type": "directory",
                    }

        except Exception as e:
            logger.warning(f"Failed to build file tree: {e}")

        return file_tree

    def merge_contexts(
        self,
        base_context: Dict[str, Any],
        override_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        合并上下文

        用于 E2E 测试中合并手动构建的上下文和自动构建的上下文

        Args:
            base_context: 基础上下文
            override_context: 覆盖上下文

        Returns:
            Dict: 合并后的上下文
        """
        merged = dict(base_context)

        for key, value in override_context.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                # 递归合并字典
                merged[key] = self.merge_contexts(merged[key], value)
            else:
                merged[key] = value

        return merged


# 全局单例实例
agent_coordinator_service = AgentCoordinatorService()
