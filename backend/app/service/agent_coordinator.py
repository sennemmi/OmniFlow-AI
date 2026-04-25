"""
Agent 协调服务
负责协调各个 AI Agent 的执行
"""

from typing import Optional, Dict, Any

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.agents.architect import architect_agent
from app.agents.designer import designer_agent
from app.agents.multi_agent_coordinator import multi_agent_coordinator
from app.core.logging import info, error
from app.core.sse_log_buffer import push_log
from app.models.pipeline import PipelineStage, StageName
from app.service.project import ProjectService
from app.service.workflow import WorkflowService


class AgentCoordinatorService:
    """
    Agent 协调服务
    
    职责：
    1. 触发 ArchitectAgent 进行需求分析
    2. 触发 DesignerAgent 进行技术设计
    3. 触发多 Agent 协调器进行代码生成
    4. 处理驳回后的重新执行
    """
    
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
        
        Args:
            pipeline_id: Pipeline ID
            requirement: 需求描述
            element_context: 页面元素上下文
            session: 数据库会话
            
        Returns:
            Dict: 执行结果
        """
        await push_log(pipeline_id, "info", "开始需求分析...", stage="REQUIREMENT")

        try:
            # 获取项目文件树
            from app.service.project import get_current_project_tree
            file_tree_node = get_current_project_tree(max_depth=4)
            file_tree = ProjectService.file_tree_to_dict(file_tree_node) if file_tree_node else {}

            await push_log(pipeline_id, "info", "正在扫描项目结构...", stage="REQUIREMENT")

            # 调用 ArchitectAgent
            result = await architect_agent.analyze(requirement, file_tree, element_context)

            await push_log(pipeline_id, "info", "需求分析完成，等待审批", stage="REQUIREMENT")
            
            # 获取当前阶段
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.REQUIREMENT
            )
            result_query = await session.execute(statement)
            stage = result_query.scalar_one_or_none()
            
            if stage:
                await WorkflowService.complete_stage(
                    stage=stage,
                    output_data=result["output"] if result["success"] else {"error": result["error"]},
                    success=result["success"],
                    session=session
                )
            
            return result

        except Exception as e:
            error_msg = str(e)
            error("Architect analysis failed", pipeline_id=pipeline_id, error=error_msg)
            await push_log(pipeline_id, "error", f"需求分析失败: {error_msg}", stage="REQUIREMENT")
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
            from app.service.project import get_current_project_tree
            file_tree_node = get_current_project_tree(max_depth=4)
            file_tree = ProjectService.file_tree_to_dict(file_tree_node) if file_tree_node else {}
            
            # 构建带反馈的需求
            feedback_requirement = f"""原始需求: {requirement}

审批反馈:
- 驳回原因: {reason}
- 建议修改: {suggested_changes or '无'}

请根据以上反馈重新分析需求。"""
            
            # 调用 ArchitectAgent
            result = await architect_agent.analyze(feedback_requirement, file_tree)
            
            # 获取当前阶段
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.REQUIREMENT
            )
            result_query = await session.execute(statement)
            stage = result_query.scalar_one_or_none()
            
            if stage:
                await WorkflowService.complete_stage(
                    stage=stage,
                    output_data=result["output"] if result["success"] else {"error": result["error"]},
                    success=result["success"],
                    session=session
                )
            
            return result
                
        except Exception as e:
            error("Architect re-analysis failed", pipeline_id=pipeline_id, error=str(e))
            raise
    
    @classmethod
    async def run_designer_analysis(
        cls,
        pipeline_id: int,
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        运行 DesignerAgent 进行技术设计

        新增：在调用 DesignerAgent 之前，先进行代码语义检索，
        将相关代码上下文注入到设计输入中。

        Args:
            pipeline_id: Pipeline ID
            session: 数据库会话

        Returns:
            Dict: 执行结果
        """
        try:
            # 获取 REQUIREMENT 阶段的输出作为输入
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.REQUIREMENT
            )
            result = await session.execute(statement)
            requirement_stage = result.scalar_one_or_none()

            if not requirement_stage or not requirement_stage.output_data:
                raise ValueError("No requirement output found")

            architect_output = requirement_stage.output_data

            # 【新增】代码语义检索 - RAG 流程
            await push_log(pipeline_id, "info", "正在扫描代码库进行语义检索...", stage="DESIGN")

            try:
                from app.service.code_indexer import get_indexer
                from app.core.config import settings

                # 获取目标项目路径
                project_path = settings.TARGET_PROJECT_PATH
                if not Path(project_path).is_absolute():
                    from pathlib import Path as PathLib
                    backend_dir = PathLib(__file__).parent.parent
                    project_path = str(backend_dir.parent / project_path)

                # 获取或创建索引服务
                indexer = get_indexer(project_path)

                # 提取需求关键词进行检索
                feature_description = architect_output.get("feature_description", "")
                affected_files = architect_output.get("affected_files", [])

                # 构建检索查询
                search_query = feature_description
                if affected_files:
                    search_query += " " + " ".join(affected_files)

                # 执行语义检索
                related_code = await indexer.semantic_search(
                    query=search_query,
                    top_k=5,
                    chunk_types=["function", "class", "method"]
                )

                # 获取项目结构摘要
                project_structure = indexer.get_project_structure()

                await push_log(
                    pipeline_id,
                    "info",
                    f"代码检索完成，找到 {len([c for c in indexer.chunks if c.type in ['function', 'class', 'method']])} 个相关代码单元",
                    stage="DESIGN"
                )

                # 将检索结果注入到 architect_output
                architect_output_with_context = {
                    **architect_output,
                    "related_code_context": related_code,
                    "project_structure_summary": project_structure
                }

            except Exception as e:
                # 如果检索失败，继续执行但不注入代码上下文
                await push_log(
                    pipeline_id,
                    "warning",
                    f"代码检索失败，继续执行: {str(e)[:100]}",
                    stage="DESIGN"
                )
                architect_output_with_context = architect_output

            # 创建 DESIGN 阶段
            design_stage = await WorkflowService.create_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.DESIGN,
                input_data=architect_output_with_context,
                session=session
            )

            # 推送开始日志
            await push_log(pipeline_id, "info", "开始技术设计...", stage="DESIGN")

            # 调用 DesignerAgent（传入带代码上下文的输入）
            agent_result = await designer_agent.design(architect_output_with_context)

            await push_log(pipeline_id, "info", "技术设计完成，等待审批", stage="DESIGN")

            # 更新 DESIGN 阶段
            await WorkflowService.complete_stage(
                stage=design_stage,
                output_data=agent_result["output"] if agent_result["success"] else {"error": agent_result["error"]},
                success=agent_result["success"],
                session=session
            )

            return agent_result

        except Exception as e:
            error("Designer analysis failed", pipeline_id=pipeline_id, error=str(e))
            await push_log(pipeline_id, "error", f"技术设计失败: {str(e)}", stage="DESIGN")
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
        """
        try:
            # 获取 REQUIREMENT 阶段的输出
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.REQUIREMENT
            )
            result = await session.execute(statement)
            requirement_stage = result.scalar_one_or_none()
            
            if not requirement_stage or not requirement_stage.output_data:
                raise ValueError("No requirement output found")
            
            architect_output = requirement_stage.output_data
            
            # 添加反馈到输入
            architect_output_with_feedback = {
                **architect_output,
                "rejection_feedback": {
                    "reason": reason,
                    "suggested_changes": suggested_changes
                }
            }
            
            # 调用 DesignerAgent
            result = await designer_agent.design(architect_output_with_feedback)
            
            # 获取 DESIGN 阶段
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.DESIGN
            )
            result_query = await session.execute(statement)
            design_stage = result_query.scalar_one_or_none()
            
            if design_stage:
                await WorkflowService.complete_stage(
                    stage=design_stage,
                    output_data=result["output"] if result["success"] else {"error": result["error"]},
                    success=result["success"],
                    session=session
                )
            
            return result
                
        except Exception as e:
            error("Designer re-analysis failed", pipeline_id=pipeline_id, error=str(e))
            raise
    
    @classmethod
    async def run_multi_agent_coding(
        cls,
        pipeline_id: int,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        运行多 Agent 协调器生成代码

        Args:
            pipeline_id: Pipeline ID
            design_output: 设计阶段输出
            target_files: 目标文件当前内容
            session: 数据库会话（可选，用于避免长时间持有连接）

        Returns:
            Dict: 执行结果
        """
        await push_log(pipeline_id, "info", "开始代码生成...", stage="CODING")
        await push_log(pipeline_id, "info", "启动多 Agent 协作生成代码...", stage="CODING")

        # 调用多 Agent 协调器，传递 pipeline_id 用于日志
        multi_agent_result = await multi_agent_coordinator.execute_parallel(
            design_output,
            target_files,
            pipeline_id=pipeline_id
        )

        return multi_agent_result
