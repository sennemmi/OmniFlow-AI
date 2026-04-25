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
            
            # 创建 DESIGN 阶段
            design_stage = await WorkflowService.create_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.DESIGN,
                input_data=architect_output,
                session=session
            )
            
            # 推送开始日志
            await push_log(pipeline_id, "info", "开始技术设计...", stage="DESIGN")

            # 调用 DesignerAgent
            agent_result = await designer_agent.design(architect_output)

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
