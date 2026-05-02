"""
上下文构建服务

负责构建 Agent 所需的代码上下文，包括：
1. 设计阶段的代码上下文（语义检索、完整文件内容）
2. 元素上下文的代码增强（sourceContext 处理）
3. 编码阶段的目标文件获取
4. 【新增】常驻基础设施上下文（Evergreen Context）
5. 【新增】动态依赖追踪（Recursive Dependency Discovery）

【重构】从 AgentCoordinatorService 迁移而来
让 AgentCoordinatorService 退化为纯粹的工作流调度器
"""

import ast
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)

# 常驻基础设施文件列表 - 这些文件的内容会被自动注入到所有 Agent 的上下文中
EVERGREEN_FILES = [
    "app/core/response.py",
    "app/core/database.py",
    "app/core/config.py",
]


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
        【简化版】获取设计阶段所需的代码上下文（禁用 RAG）

        【注意】当前版本已禁用语义检索（RAG），与测试脚本保持一致。
        只返回空上下文，让 DesignerAgent 基于 Architect 输出直接设计。

        Args:
            pipeline_id: Pipeline ID
            architect_output: ArchitectAgent 的输出

        Returns:
            Dict: 空上下文，与 test_e2e_with_contract_v2.py 保持一致
        """
        await push_log(
            pipeline_id,
            "info",
            "代码上下文获取已禁用（与测试脚本保持一致）",
            stage="DESIGN"
        )

        # 返回空上下文，与测试脚本一致
        return {
            "success": True,
            "error": None,
            "related_code_context": "",  # 空字符串，与测试脚本一致
            "full_files_context": {},     # 空字典，与测试脚本一致
            "project_structure_summary": {},
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

    @classmethod
    def extract_local_imports(cls, file_path: Path, project_root: Path) -> List[str]:
        """
        【动态依赖追踪】解析 Python 文件，提取本地项目 import

        使用 AST 分析文件内容，找出所有从 app. 导入的模块，
        并转换为文件路径。

        Args:
            file_path: 要分析的文件路径
            project_root: 项目根目录

        Returns:
            List[str]: 导入的本地文件路径列表（相对路径）
        """
        imports = []

        try:
            content = file_path.read_text(encoding='utf-8')
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError) as e:
            logger.warning(f"解析文件失败 {file_path}: {e}")
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                # 只处理本地项目模块（以 app. 开头）
                if module.startswith("app."):
                    # 将模块路径转换为文件路径
                    # app.core.response -> app/core/response.py
                    module_parts = module.split(".")
                    possible_paths = [
                        "/".join(module_parts) + ".py",  # app/core/response.py
                        "/".join(module_parts[:-1]) + "/__init__.py" if len(module_parts) > 1 else "",  # app/core/__init__.py
                    ]

                    for rel_path in possible_paths:
                        if not rel_path:
                            continue
                        full_path = project_root / "backend" / rel_path
                        if not full_path.exists():
                            full_path = project_root / rel_path

                        if full_path.exists() and rel_path not in imports:
                            imports.append(rel_path)
                            break

        return imports

    @classmethod
    def get_auto_context(
        cls,
        target_file_paths: List[str],
        project_root: Path,
        max_depth: int = 2
    ) -> Dict[str, str]:
        """
        【递归依赖发现】自动获取目标文件及其依赖的上下文

        逻辑：
        1. 确定受影响文件（如 app/api/v1/health.py）
        2. 解析 Import 树：利用 ast 扫描文件
        3. 发现本地依赖：识别出它导入了 app.core.response 等
        4. 自动包含：将依赖文件内容读入上下文

        Args:
            target_file_paths: 目标文件路径列表（相对路径，如 app/api/v1/health.py）
            project_root: 项目根目录
            max_depth: 递归深度，避免无限递归

        Returns:
            Dict[str, str]: 文件路径到内容的映射
        """
        context_files = set(target_file_paths)
        discovered_files = set(target_file_paths)

        for depth in range(max_depth):
            new_files = set()

            for rel_path in list(discovered_files):
                # 构建完整路径
                full_path = project_root / "backend" / rel_path
                if not full_path.exists():
                    full_path = project_root / rel_path

                if not full_path.exists():
                    continue

                # 提取该文件依赖的所有本地模块
                imports = cls.extract_local_imports(full_path, project_root)

                # 过滤：只包含 core/ 或 models/ 下的公共定义，避免上下文爆炸
                infra_imports = [
                    imp for imp in imports
                    if "core" in imp or "models" in imp
                ]

                for imp in infra_imports:
                    if imp not in context_files:
                        new_files.add(imp)
                        context_files.add(imp)

            if not new_files:
                break

            discovered_files = new_files
            logger.info(f"递归深度 {depth + 1}: 发现 {len(new_files)} 个新依赖")

        # 读取所有文件内容
        result = {}
        for rel_path in context_files:
            full_path = project_root / "backend" / rel_path
            if not full_path.exists():
                full_path = project_root / rel_path

            if full_path.exists():
                try:
                    content = full_path.read_text(encoding='utf-8')
                    # 限制内容长度
                    max_chars = 5000
                    if len(content) > max_chars:
                        content = content[:max_chars] + f"\n... (文件剩余 {len(content) - max_chars} 字符已省略)"
                    result[rel_path] = content
                except Exception as e:
                    logger.warning(f"读取文件失败 {rel_path}: {e}")

        return result

    @classmethod
    def get_evergreen_context(cls, project_path: Path) -> str:
        """
        获取项目中永远需要让 AI 看到的'地基'代码

        读取 EVERGREEN_FILES 中定义的核心基础设施文件，构建常驻上下文。
        这些文件定义了项目的核心契约（响应格式、数据库连接、配置等），
        所有 Agent 在生成代码时都必须遵守这些契约。

        Args:
            project_path: 项目根目录路径

        Returns:
            str: 格式化的常驻上下文字符串，包含所有地基文件的内容
        """
        context_parts = ["【核心基础设施定义 - 禁止修改，仅供参考其签名和用法】\n"]

        for rel_path in EVERGREEN_FILES:
            full_path = project_path / "backend" / rel_path
            if not full_path.exists():
                # 尝试不带 backend 前缀的路径
                full_path = project_path / rel_path

            if full_path.exists():
                try:
                    content = full_path.read_text(encoding='utf-8')
                    # 限制内容长度，避免 token 爆炸
                    max_chars = 3000
                    if len(content) > max_chars:
                        content = content[:max_chars] + f"\n... (文件剩余 {len(content) - max_chars} 字符已省略)"

                    context_parts.append(f"=== 文件: {rel_path} ===")
                    context_parts.append("```python")
                    context_parts.append(content)
                    context_parts.append("```\n")
                except Exception as e:
                    logger.warning(f"读取 evergreen 文件失败 {rel_path}: {e}")
                    context_parts.append(f"=== 文件: {rel_path} ===")
                    context_parts.append(f"[读取失败: {e}]\n")
            else:
                context_parts.append(f"=== 文件: {rel_path} ===")
                context_parts.append("[文件不存在]\n")

        return "\n".join(context_parts)

    @classmethod
    async def build_agent_context(
        cls,
        pipeline_id: int,
        base_context: Dict[str, Any],
        include_evergreen: bool = True
    ) -> Dict[str, Any]:
        """
        构建完整的 Agent 上下文，包含常驻基础设施上下文

        Args:
            pipeline_id: Pipeline ID
            base_context: 基础上下文（如 design_output, code_output 等）
            include_evergreen: 是否包含常驻上下文

        Returns:
            Dict: 增强后的上下文
        """
        if not include_evergreen:
            return base_context

        # 获取项目路径
        project_path = Path(settings.TARGET_PROJECT_PATH)
        if not project_path.is_absolute():
            backend_dir = Path(__file__).parent.parent.parent
            project_path = backend_dir.parent / settings.TARGET_PROJECT_PATH

        # 获取常驻上下文
        evergreen_context = cls.get_evergreen_context(project_path)

        # 合并到基础上下文
        enhanced_context = {
            **base_context,
            "evergreen_context": evergreen_context,
        }

        await push_log(
            pipeline_id,
            "info",
            f"已注入常驻基础设施上下文 ({len(EVERGREEN_FILES)} 个文件)",
            stage="CONTEXT"
        )

        return enhanced_context


# 单例实例
context_builder = ContextBuilderService()
