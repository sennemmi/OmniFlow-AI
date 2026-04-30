"""
上下文构建服务

负责构建 Agent 所需的代码上下文，包括：
1. 设计阶段的代码上下文（语义检索、完整文件内容）
2. 元素上下文的代码增强（sourceContext 处理）
3. 编码阶段的目标文件获取

【重构】从 AgentCoordinatorService 迁移而来
让 AgentCoordinatorService 退化为纯粹的工作流调度器
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class ContextBuilderService:
    """
    上下文构建服务

    职责：
    1. 获取设计阶段所需的代码上下文（两层上下文注入）
    2. 增强元素上下文（sourceContext 处理）
    3. 获取编码阶段的目标文件
    """

    @classmethod
    async def get_code_context_for_design(
        cls,
        pipeline_id: int,
        architect_output: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        【核心方法】获取设计阶段所需的两层代码上下文

        两层上下文注入：
        1. 语义检索结果（RAG）- 相关代码片段
        2. 完整文件内容 - 用于理解代码风格和架构

        Args:
            pipeline_id: Pipeline ID
            architect_output: ArchitectAgent 的输出

        Returns:
            Dict: 包含以下字段：
                - related_code_context: 语义检索结果（字符串）
                - full_files_context: 完整文件内容映射
                - project_structure_summary: 项目结构摘要
                - success: 是否成功
                - error: 错误信息（如果有）
        """
        try:
            from app.service.code_indexer import get_indexer

            # 获取目标项目路径
            project_path = settings.TARGET_PROJECT_PATH
            if not Path(project_path).is_absolute():
                backend_dir = Path(__file__).parent.parent.parent
                project_path = str(backend_dir.parent / project_path)

            # 获取或创建索引服务（线程安全）
            indexer = await get_indexer(project_path)

            # 提取需求关键词进行检索
            feature_description = architect_output.get("feature_description", "")
            affected_files = architect_output.get("affected_files", [])

            # 构建检索查询
            search_query = feature_description
            if affected_files:
                search_query += " " + " ".join(affected_files)

            await push_log(
                pipeline_id,
                "info",
                f"正在执行语义检索: {search_query[:80]}...",
                stage="DESIGN"
            )

            # 【第一层】执行语义检索，获取相关代码片段
            related_code = await indexer.semantic_search(
                query=search_query,
                top_k=8,
                chunk_types=["function", "class", "method"]
            )

            # 【第二层】获取完整文件内容
            await push_log(
                pipeline_id,
                "info",
                "正在读取完整文件内容...",
                stage="DESIGN"
            )

            # 使用新的核心方法获取两层上下文
            context_result = await indexer.get_related_files_full_content(
                query=search_query,
                top_k=8,
                include_related=True
            )

            # 获取项目结构摘要
            project_structure = indexer.get_project_structure()

            # 统计信息
            full_files_count = len(context_result.get("full_files", {}))
            related_files_count = len(context_result.get("related_files", {}))

            await push_log(
                pipeline_id,
                "info",
                f"代码上下文获取完成: {full_files_count} 个核心文件, {related_files_count} 个相关文件",
                stage="DESIGN"
            )

            # 合并完整文件内容（核心文件 + 相关文件）
            all_full_files = {
                **context_result.get("full_files", {}),
                **context_result.get("related_files", {})
            }

            return {
                "success": True,
                "error": None,
                "related_code_context": related_code,
                "full_files_context": all_full_files,
                "project_structure_summary": project_structure,
                "file_summaries": context_result.get("file_summaries", []),
                "related_chunks": context_result.get("related_chunks", [])
            }

        except Exception as e:
            error_msg = f"获取代码上下文失败: {str(e)}"
            await push_log(pipeline_id, "warning", error_msg[:100], stage="DESIGN")
            return {
                "success": False,
                "error": error_msg,
                "related_code_context": None,
                "full_files_context": None,
                "project_structure_summary": None,
                "file_summaries": [],
                "related_chunks": []
            }

    @classmethod
    async def enrich_element_context_with_code(
        cls,
        pipeline_id: int,
        element_context: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        【增强】根据 sourceContext 读取真实代码上下文并注入到 element_context

        Args:
            pipeline_id: Pipeline ID
            element_context: 页面元素上下文（包含 sourceContext）

        Returns:
            Optional[Dict[str, Any]]: 增强后的 element_context
        """
        if not element_context:
            return element_context

        source_context = element_context.get("sourceContext")
        if not source_context:
            return element_context

        try:
            from app.service.code_modifier import CodeModifierService

            file_path = source_context.get("file") or source_context.get("relativePath")
            line = source_context.get("line", 0)

            if not file_path or line <= 0:
                return element_context

            await push_log(
                pipeline_id,
                "info",
                f"正在读取圈选元素对应的源码上下文: {file_path}:{line}",
                stage="REQUIREMENT"
            )

            # 创建代码修改服务
            modifier = CodeModifierService(workspace_path=settings.TARGET_PROJECT_PATH)

            try:
                # 读取文件上下文
                content, surrounding, start_line, end_line = modifier.read_file_context(
                    file_path, line, context_lines=20
                )

                # 构建 code_context
                code_context = {
                    "file": file_path,
                    "line": line,
                    "column": source_context.get("column", 0),
                    "surrounding_code": surrounding,
                    "full_file_content": content,
                    "context_start_line": start_line,
                    "context_end_line": end_line,
                }

                # 注入到 element_context
                element_context["code_context"] = code_context

                await push_log(
                    pipeline_id,
                    "info",
                    f"成功读取源码上下文: {file_path} (行 {start_line}-{end_line})",
                    stage="REQUIREMENT"
                )

            except FileNotFoundError:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"源文件不存在: {file_path}",
                    stage="REQUIREMENT"
                )
            except Exception as e:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"读取源码上下文失败: {str(e)[:100]}",
                    stage="REQUIREMENT"
                )

        except Exception as e:
            logger.error(f"增强 element_context 失败: {e}")

        return element_context

    @classmethod
    async def get_target_files_for_coding(
        cls,
        pipeline_id: int,
        design_output: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        【增强】获取 CODING 阶段所需的目标文件内容

        优先级：
        1. 如果存在 sourceContext，优先使用该文件
        2. 从 design_output 中提取 affected_files
        3. 从 function_changes 获取文件（兼容旧格式）

        Args:
            pipeline_id: Pipeline ID
            design_output: 设计阶段输出

        Returns:
            Dict[str, str]: 文件路径到内容的映射
        """
        from app.service.code_executor import CodeExecutorService

        target_files = {}

        def normalize_path(p: str) -> str:
            """统一路径格式"""
            p = p.replace("\\", "/")
            if p.startswith("backend/"):
                p = p[len("backend/"):]
            return p

        try:
            # 获取目标项目路径
            target_path = Path(settings.TARGET_PROJECT_PATH)
            if not target_path.is_absolute():
                backend_dir = Path(__file__).parent.parent.parent
                target_path = backend_dir.parent / settings.TARGET_PROJECT_PATH

            code_executor = CodeExecutorService(str(target_path))

            # 1. 优先处理 sourceContext
            source_context = design_output.get("sourceContext")
            if source_context:
                source_file = source_context.get("file") or source_context.get("relativePath")
                source_line = source_context.get("line", 0)

                if source_file:
                    await push_log(
                        pipeline_id,
                        "info",
                        f"使用精确源码定位: {source_file}:{source_line}",
                        stage="CODING"
                    )

                    source_file = normalize_path(source_file)
                    content = code_executor.get_file_content(source_file)

                    # 如果失败且是绝对路径，尝试提取相对路径
                    if not content and Path(source_file).is_absolute():
                        parts = Path(source_file).parts
                        for i, part in enumerate(parts):
                            if part in ["src", "frontend", "components", "pages"]:
                                relative_path = str(Path(*parts[i:]))
                                content = code_executor.get_file_content(relative_path)
                                if content:
                                    source_file = relative_path
                                    break

                    if content:
                        target_files[source_file] = content
                        await push_log(
                            pipeline_id,
                            "info",
                            f"已加载圈选元素对应的源文件: {source_file}",
                            stage="CODING"
                        )

            # 2. 从 affected_files 获取文件
            affected_files = design_output.get("affected_files", [])
            if affected_files:
                await push_log(
                    pipeline_id,
                    "info",
                    f"从 affected_files 读取 {len(affected_files)} 个文件...",
                    stage="CODING"
                )
                for file_path in affected_files:
                    file_path = normalize_path(file_path)
                    if file_path not in target_files:
                        content = code_executor.get_file_content(file_path)
                        if content:
                            target_files[file_path] = content

            # 3. 从 function_changes 获取文件（兼容旧格式）
            function_changes = design_output.get("function_changes", [])
            if function_changes:
                await push_log(
                    pipeline_id,
                    "info",
                    f"从 function_changes 读取文件...",
                    stage="CODING"
                )
                for change in function_changes:
                    file_path = change.get("file", "")
                    if file_path:
                        file_path = normalize_path(file_path)
                        if file_path not in target_files:
                            content = code_executor.get_file_content(file_path)
                            if content:
                                target_files[file_path] = content

            # 补充关键上下文文件
            for change in function_changes:
                file_path = change.get("file", "")
                action = change.get("action", "").lower()
                if action in ("modify", "update"):
                    file_path = normalize_path(file_path)
                    if file_path not in target_files:
                        content = code_executor.get_file_content(file_path)
                        if content:
                            target_files[file_path] = content
                        else:
                            await push_log(
                                pipeline_id,
                                "warning",
                                f"[修改] 目标文件不存在，将创建新文件: {file_path}",
                                stage="CODING"
                            )

            await push_log(
                pipeline_id,
                "info",
                f"成功读取 {len(target_files)} 个目标文件",
                stage="CODING"
            )

        except Exception as e:
            await push_log(
                pipeline_id,
                "warning",
                f"获取目标文件失败: {str(e)[:100]}",
                stage="CODING"
            )

        return target_files


# 单例实例
context_builder = ContextBuilderService()
