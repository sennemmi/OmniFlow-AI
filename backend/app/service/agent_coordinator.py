"""
Agent 协调服务
负责协调各个 AI Agent 的执行

【重构】上下文构建逻辑已迁移到 ContextBuilderService
本模块现在专注于工作流调度，退化为纯粹的协调器

【优化】使用 Repository 模式消除重复的数据库查询代码
"""

from pathlib import Path
from typing import Optional, Dict, Any, List

from sqlmodel.ext.asyncio.session import AsyncSession

from app.agents.architect import architect_agent
from app.agents.designer import designer_agent
from app.agents.multi_agent_coordinator import multi_agent_coordinator
from app.core.logging import info, error
import logging

logger = logging.getLogger(__name__)
from app.core.sse_log_buffer import push_log
from app.models.pipeline import PipelineStage, StageName
from app.service.project import ProjectService
from app.service.workflow import WorkflowService
from app.service.context_builder import context_builder
from app.repositories import PipelineStageRepository


class AgentCoordinatorService:
    """
    Agent 协调服务
    
    职责：
    1. 触发 ArchitectAgent 进行需求分析
    2. 触发 DesignerAgent 进行技术设计（带两层代码上下文注入）
    3. 触发多 Agent 协调器进行代码生成
    4. 处理驳回后的重新执行
    
    【优化】使用 Repository 统一数据访问，消除重复查询
    """
    
    # ==================== 通用工具方法 ====================
    
    @staticmethod
    def _extract_metrics(agent_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 Agent 执行结果中提取可观测性指标

        Args:
            agent_result: Agent 执行结果

        Returns:
            Dict[str, Any]: 指标字典
        """
        metrics = PipelineStageRepository.extract_metrics(agent_result)
        # ★ DEBUG: 打印提取的指标
        from app.core.logging import logger
        logger.info(f"[DEBUG] _extract_metrics from agent_result: {metrics}")
        return metrics
    
    @staticmethod
    async def _get_project_file_tree(max_depth: int = 4) -> Dict[str, Any]:
        """
        获取项目文件树
        
        Args:
            max_depth: 最大深度
            
        Returns:
            Dict[str, Any]: 文件树字典
        """
        from app.service.project import get_current_project_tree
        file_tree_node = get_current_project_tree(max_depth=max_depth)
        return ProjectService.file_tree_to_dict(file_tree_node) if file_tree_node else {}
    
    @staticmethod
    async def _complete_stage_with_metrics(
        pipeline_id: int,
        stage_name: StageName,
        agent_result: Dict[str, Any],
        session: AsyncSession
    ) -> None:
        """
        完成阶段并保存指标（通用方法）
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            agent_result: Agent 执行结果
            session: 数据库会话
        """
        stage = await PipelineStageRepository.get_by_pipeline_and_name(
            pipeline_id, stage_name, session
        )
        
        if stage:
            metrics = AgentCoordinatorService._extract_metrics(agent_result)
            # ★ DEBUG: 打印即将保存的指标
            logger.info(f"[DEBUG] _complete_stage_with_metrics for {stage_name}: metrics={metrics}")
            await WorkflowService.complete_stage(
                stage=stage,
                output_data=agent_result["output"] if agent_result["success"] else {"error": agent_result["error"]},
                success=agent_result["success"],
                session=session,
                metrics=metrics
            )
    
    # ==================== ArchitectAgent 相关 ====================
    
    @classmethod
    async def _enrich_element_context_with_code(
        cls,
        pipeline_id: int,
        element_context: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        【重构】委托给 ContextBuilderService 处理
        
        Args:
            pipeline_id: Pipeline ID
            element_context: 页面元素上下文（包含 sourceContext）
            
        Returns:
            Optional[Dict[str, Any]]: 增强后的 element_context
        """
        return await context_builder.enrich_element_context_with_code(
            pipeline_id=pipeline_id,
            element_context=element_context
        )
    
    @classmethod
    async def run_architect_analysis(
        cls,
        pipeline_id: int,
        requirement: str,
        element_context: Optional[Dict[str, Any]],
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        运行 ArchitectAgent 分析

        【改造】ArchitectAgent 现在使用工具自主探索项目代码
        - 不再预注入 code_context
        - ArchitectAgent 使用 glob/grep/read_file 工具按需读取
        - 简化 Prompt，降低 Token 消耗

        Args:
            pipeline_id: Pipeline ID
            requirement: 需求描述
            element_context: 页面元素上下文（可选）
            session: 数据库会话

        Returns:
            Dict: 执行结果
        """
        from app.core.config import settings

        await push_log(pipeline_id, "info", "开始需求分析...", stage="REQUIREMENT")

        try:
            # 【改造】不再预注入 code_context
            # ArchitectAgent 会使用工具自主探索项目

            # 获取项目文件树
            file_tree = await cls._get_project_file_tree()
            await push_log(pipeline_id, "info", "正在扫描项目结构...", stage="REQUIREMENT")

            # 获取项目路径
            project_path = settings.TARGET_PROJECT_PATH
            if not Path(project_path).is_absolute():
                backend_dir = Path(__file__).parent.parent
                project_path = str(backend_dir.parent / project_path)

            await push_log(
                pipeline_id,
                "info",
                "ArchitectAgent 将使用工具自主探索项目代码...",
                stage="REQUIREMENT"
            )

            # 【改造】调用 ArchitectAgent，传入 project_path 用于工具执行
            result = await architect_agent.analyze(
                requirement=requirement,
                file_tree=file_tree,
                element_context=element_context,
                pipeline_id=pipeline_id,
                project_path=project_path
            )

            # 记录工具调用情况
            tool_calls = result.get("tool_calls", 0)
            await push_log(
                pipeline_id,
                "info",
                f"需求分析完成（使用了 {tool_calls} 次工具调用），等待审批",
                stage="REQUIREMENT"
            )

            # 完成阶段并保存指标
            await cls._complete_stage_with_metrics(
                pipeline_id, StageName.REQUIREMENT, result, session
            )

            return result

        except Exception as e:
            error_msg = str(e)
            error("Architect analysis failed", pipeline_id=pipeline_id, error=error_msg, exc_info=True)
            await push_log(pipeline_id, "error", f"需求分析失败: {error_msg[:500]}", stage="REQUIREMENT")
            raise

    @classmethod
    async def run_architect_with_feedback(
        cls,
        pipeline_id: int,
        requirement: str,
        reason: str,
        suggested_changes: Optional[str],
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        携带驳回反馈重新运行 ArchitectAgent
        """
        try:
            # 获取项目文件树
            file_tree = await cls._get_project_file_tree()
            
            # 构建带反馈的需求
            feedback_requirement = f"""原始需求: {requirement}

审批反馈:
- 驳回原因: {reason}
- 建议修改: {suggested_changes or '无'}

请根据以上反馈重新分析需求。"""
            
            # 调用 ArchitectAgent
            result = await architect_agent.analyze(feedback_requirement, file_tree, None, pipeline_id)
            
            # 完成阶段并保存指标
            await cls._complete_stage_with_metrics(
                pipeline_id, StageName.REQUIREMENT, result, session
            )

            return result

        except Exception as e:
            error_msg = str(e)
            error("Architect re-analysis failed", pipeline_id=pipeline_id, error=error_msg, exc_info=True)
            await push_log(pipeline_id, "error", f"需求重新分析失败: {error_msg[:500]}", stage="REQUIREMENT")
            raise
    
    # ==================== DesignerAgent 相关 ====================
    
    @classmethod
    async def _get_code_context_for_design(
        cls,
        pipeline_id: int,
        architect_output: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        【重构】委托给 ContextBuilderService 处理
        
        Args:
            pipeline_id: Pipeline ID
            architect_output: ArchitectAgent 的输出
            
        Returns:
            Dict: 代码上下文
        """
        return await context_builder.get_code_context_for_design(
            pipeline_id=pipeline_id,
            architect_output=architect_output
        )
    
    @classmethod
    async def run_designer_analysis(
        cls,
        pipeline_id: int,
        session: AsyncSession,
        design_stage_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        运行 DesignerAgent 进行技术设计

        【增强】在调用 DesignerAgent 之前，先进行两层代码上下文注入
        
        Args:
            pipeline_id: Pipeline ID
            session: 数据库会话
            design_stage_id: DESIGN 阶段 ID（由 Handler 传入，避免重复创建）

        Returns:
            Dict: 执行结果
        """
        try:
            # 获取 REQUIREMENT 阶段的输出作为输入
            requirement_stage = await PipelineStageRepository.get_by_pipeline_and_name(
                pipeline_id, StageName.REQUIREMENT, session
            )

            if not requirement_stage or not requirement_stage.output_data:
                raise ValueError("No requirement output found")

            architect_output = requirement_stage.output_data

            # 从 REQUIREMENT 阶段的 input_data 中提取 sourceContext
            source_context = None
            if requirement_stage.input_data:
                element_context = requirement_stage.input_data.get("element_context", {})
                source_context = element_context.get("sourceContext")
                if source_context:
                    await push_log(
                        pipeline_id,
                        "info",
                        f"检测到精确源码定位: {source_context.get('relativePath') or source_context.get('file')}:{source_context.get('line')}",
                        stage="DESIGN"
                    )

            # 【核心】获取两层代码上下文
            await push_log(pipeline_id, "info", "正在扫描代码库进行语义检索...", stage="DESIGN")

            code_context = await cls._get_code_context_for_design(
                pipeline_id=pipeline_id,
                architect_output=architect_output
            )

            # 构建带代码上下文的输入
            if code_context["success"]:
                architect_output_with_context = {
                    **architect_output,
                    "related_code_context": code_context["related_code_context"],
                    "project_structure_summary": code_context["project_structure_summary"]
                }
                full_files_context = code_context["full_files_context"]
            else:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"代码检索失败: {code_context.get('error', '未知错误')[:100]}",
                    stage="DESIGN"
                )
                architect_output_with_context = architect_output
                full_files_context = None

            # 获取项目文件树
            file_tree = await cls._get_project_file_tree()

            # 【修复】如果提供了 design_stage_id，则更新现有阶段，否则创建新阶段
            if design_stage_id:
                # 使用 Handler 已创建的阶段
                from sqlmodel import select
                from app.models.pipeline import PipelineStage
                statement = select(PipelineStage).where(PipelineStage.id == design_stage_id)
                result = await session.execute(statement)
                design_stage = result.scalar_one_or_none()
                if not design_stage:
                    raise ValueError(f"Design stage {design_stage_id} not found")
                
                # 更新输入数据
                design_stage.input_data = {
                    **architect_output_with_context,
                    "full_files_context_keys": list(full_files_context.keys()) if full_files_context else [],
                    "file_summaries": code_context.get("file_summaries", [])
                }
            else:
                # 创建 DESIGN 阶段（兼容旧调用）
                design_stage = await WorkflowService.create_stage(
                    pipeline_id=pipeline_id,
                    stage_name=StageName.DESIGN,
                    input_data={
                        **architect_output_with_context,
                        "full_files_context_keys": list(full_files_context.keys()) if full_files_context else [],
                        "file_summaries": code_context.get("file_summaries", [])
                    },
                    session=session
                )

            # 推送开始日志
            await push_log(pipeline_id, "info", "开始技术设计...", stage="DESIGN")

            # 调用 DesignerAgent
            agent_result = await designer_agent.design(
                architect_output=architect_output_with_context,
                file_tree=file_tree,
                related_code_context=code_context.get("related_code_context"),
                full_files_context=full_files_context,
                pipeline_id=pipeline_id
            )

            await push_log(pipeline_id, "info", "技术设计完成，等待审批", stage="DESIGN")

            # 将 sourceContext 添加到输出中
            output_data = agent_result["output"] if agent_result["success"] else {"error": agent_result["error"]}
            if source_context and agent_result["success"]:
                output_data["sourceContext"] = source_context
                await push_log(
                    pipeline_id,
                    "info",
                    "已将源码定位信息传递到代码生成阶段",
                    stage="DESIGN"
                )

            # 更新 DESIGN 阶段
            metrics = cls._extract_metrics(agent_result)
            await WorkflowService.complete_stage(
                stage=design_stage,
                output_data=output_data,
                success=agent_result["success"],
                session=session,
                metrics=metrics
            )

            return agent_result

        except Exception as e:
            error_msg = str(e)
            error("Designer analysis failed", pipeline_id=pipeline_id, error=error_msg, exc_info=True)
            await push_log(pipeline_id, "error", f"技术设计失败: {error_msg[:500]}", stage="DESIGN")
            raise
    
    @classmethod
    async def run_designer_with_feedback(
        cls,
        pipeline_id: int,
        reason: str,
        suggested_changes: Optional[str],
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        携带驳回反馈重新运行 DesignerAgent
        
        【增强】重新获取代码上下文，确保 Designer 有最新的代码库信息
        """
        try:
            # 获取 REQUIREMENT 阶段的输出
            requirement_stage = await PipelineStageRepository.get_by_pipeline_and_name(
                pipeline_id, StageName.REQUIREMENT, session
            )
            
            if not requirement_stage or not requirement_stage.output_data:
                raise ValueError("No requirement output found")
            
            architect_output = requirement_stage.output_data
            
            # 【增强】重新获取代码上下文
            code_context = await cls._get_code_context_for_design(
                pipeline_id=pipeline_id,
                architect_output=architect_output
            )
            
            # 添加反馈到输入
            architect_output_with_feedback = {
                **architect_output,
                "rejection_feedback": {
                    "reason": reason,
                    "suggested_changes": suggested_changes
                },
                "related_code_context": code_context.get("related_code_context") if code_context["success"] else None,
                "project_structure_summary": code_context.get("project_structure_summary") if code_context["success"] else None
            }
            
            full_files_context = code_context.get("full_files_context") if code_context["success"] else None
            
            # 获取项目文件树
            file_tree = await cls._get_project_file_tree()
            
            # 调用 DesignerAgent
            result = await designer_agent.design(
                architect_output=architect_output_with_feedback,
                file_tree=file_tree,
                related_code_context=code_context.get("related_code_context"),
                full_files_context=full_files_context
            )
            
            # 完成阶段并保存指标
            await cls._complete_stage_with_metrics(
                pipeline_id, StageName.DESIGN, result, session
            )

            return result
                
        except Exception as e:
            error_msg = str(e)
            error("Designer re-analysis failed", pipeline_id=pipeline_id, error=error_msg, exc_info=True)
            await push_log(pipeline_id, "error", f"技术重新设计失败: {error_msg[:500]}", stage="DESIGN")
            raise
    
    # ==================== 代码生成相关 ====================
    
    @classmethod
    async def run_multi_agent_coding(
        cls,
        pipeline_id: int,
        design_output: Dict[str, Any],
        affected_files: List[str],
        session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        运行多 Agent 协调器生成代码

        【改造】使用 affected_files 替代 target_files
        CoderAgent 现在使用工具按需读取文件

        Args:
            pipeline_id: Pipeline ID
            design_output: 设计阶段输出
            affected_files: 受影响文件列表
            session: 数据库会话（可选，用于避免长时间持有连接）

        Returns:
            Dict: 执行结果
        """
        await push_log(pipeline_id, "info", "开始代码生成...", stage="CODING")
        await push_log(pipeline_id, "info", "启动多 Agent 协作生成代码...", stage="CODING")

        # 【改造】调用多 Agent 协调器，传入 affected_files 而非 target_files
        multi_agent_result = await multi_agent_coordinator.execute_parallel(
            design_output,
            affected_files,
            pipeline_id=pipeline_id
        )

        return multi_agent_result
    
    @classmethod
    async def get_target_files_for_coding(
        cls,
        pipeline_id: int,
        design_output: Dict[str, Any],
        session: AsyncSession
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
            session: 数据库会话

        Returns:
            Dict[str, str]: 文件路径到内容的映射
        """
        from app.service.code_executor import CodeExecutorService
        from app.core.config import settings

        target_files = {}

        def normalize_path(p: str) -> str:
            """统一路径格式：
            1. 统一使用正斜杠
            2. 移除 backend/ 前缀
            """
            # 统一使用正斜杠
            p = p.replace("\\", "/")
            # 移除 backend/ 前缀
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

            # === 新增：补充关键上下文文件 ===
            # 如果 affected_files 中包含 modify 类型的文件，无论如何要强制读取它们
            function_changes = design_output.get("function_changes", [])
            for change in function_changes:
                file_path = change.get("file", "")
                action = change.get("action", "").lower()
                if action in ("modify", "update"):
                    file_path = normalize_path(file_path)
                    if file_path not in target_files:
                        content = code_executor.get_file_content(file_path)
                        if content:
                            target_files[file_path] = content
                        # 如果文件确实不存在（允许新建 but marked as modify），则记录警告
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
                f"读取目标文件失败: {str(e)[:100]}",
                stage="CODING"
            )

        return target_files
