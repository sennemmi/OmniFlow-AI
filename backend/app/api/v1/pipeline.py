"""
Pipeline API 路由
路由层 - 只负责路由定义和参数解析
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_session
from app.core.response import ResponseModel, success_response, error_response
from app.service.pipeline import PipelineService

router = APIRouter()


class PipelineCreateRequest(BaseModel):
    """Pipeline 创建请求模型"""
    requirement: str


class PipelineApproveRequest(BaseModel):
    """Pipeline 审批请求模型"""
    notes: Optional[str] = None
    feedback: Optional[str] = None


class PipelineRejectRequest(BaseModel):
    """Pipeline 驳回请求模型"""
    reason: str
    suggested_changes: Optional[str] = None


@router.post("/pipeline/create", response_model=ResponseModel)
async def create_pipeline(
    request: Request,
    data: PipelineCreateRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    创建新的 Pipeline
    
    Args:
        data: 包含 requirement 的请求体
        
    Returns:
        ResponseModel: 创建的 Pipeline 信息
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        pipeline = await PipelineService.create_pipeline(
            requirement=data.requirement,
            session=session
        )
        
        return success_response(
            data={
                "pipeline_id": pipeline.id,
                "status": pipeline.status.value,
                "current_stage": pipeline.current_stage.value if pipeline.current_stage else None,
                "created_at": pipeline.created_at.isoformat()
            },
            request_id=request_id
        )
    except Exception as e:
        return error_response(
            error=f"Failed to create pipeline: {str(e)}",
            request_id=request_id
        )


@router.get("/pipeline/{pipeline_id}/status", response_model=ResponseModel)
async def get_pipeline_status(
    request: Request,
    pipeline_id: int,
    session: AsyncSession = Depends(get_session)
):
    """
    获取 Pipeline 状态
    
    Args:
        pipeline_id: Pipeline ID
        
    Returns:
        ResponseModel: Pipeline 状态和阶段信息
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        pipeline = await PipelineService.get_pipeline_status(
            pipeline_id=pipeline_id,
            session=session
        )
        
        if not pipeline:
            return error_response(
                error=f"Pipeline {pipeline_id} not found",
                request_id=request_id
            )
        
        # 构建响应数据
        stages_data = []
        if pipeline.stages:
            for stage in pipeline.stages:
                stage_data = {
                    "id": stage.id,
                    "name": stage.name.value,
                    "status": stage.status.value,
                    "input_data": stage.input_data,
                    "output_data": stage.output_data,
                    "created_at": stage.created_at.isoformat() if stage.created_at else None,
                    "completed_at": stage.completed_at.isoformat() if stage.completed_at else None
                }
                stages_data.append(stage_data)
        
        # 构建基础响应数据
        response_data = {
            "id": pipeline.id,
            "description": pipeline.description,
            "status": pipeline.status.value,
            "current_stage": pipeline.current_stage.value if pipeline.current_stage else None,
            "created_at": pipeline.created_at.isoformat() if pipeline.created_at else None,
            "updated_at": pipeline.updated_at.isoformat() if pipeline.updated_at else None,
            "stages": stages_data
        }
        
        # 如果 Pipeline 已完成 (SUCCESS)，添加交付物摘要
        if pipeline.status.value == "success":
            # 从 CODING 阶段获取 Git 信息
            coding_stage = None
            for stage in pipeline.stages:
                if stage.name.value == "CODING":
                    coding_stage = stage
                    break
            
            if coding_stage and coding_stage.output_data:
                output_data = coding_stage.output_data
                
                # 添加 Git 分支和提交信息
                response_data["delivery"] = {
                    "git_branch": output_data.get("git_branch"),
                    "commit_hash": output_data.get("commit_hash"),
                    "summary": output_data.get("coder_output", {}).get("summary", ""),
                    "files_changed": output_data.get("execution_summary", {})
                }
                
                # 尝试获取 Git diff 摘要
                try:
                    from app.service.git_provider import GitProviderService
                    git_service = GitProviderService()
                    
                    # 切换到对应分支获取 diff
                    branch_name = output_data.get("git_branch")
                    if branch_name:
                        try:
                            git_service.checkout_branch(branch_name)
                            diff_summary = git_service.get_diff(cached=True)
                            response_data["delivery"]["diff_summary"] = diff_summary[:2000] if diff_summary else None
                        except Exception:
                            response_data["delivery"]["diff_summary"] = None
                except Exception:
                    pass
        
        return success_response(
            data=response_data,
            request_id=request_id
        )
    except Exception as e:
        return error_response(
            error=f"Failed to get pipeline status: {str(e)}",
            request_id=request_id
        )


@router.get("/pipelines", response_model=ResponseModel)
async def list_pipelines(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_session)
):
    """
    列出所有 Pipeline
    
    Args:
        skip: 跳过数量
        limit: 返回数量限制
        
    Returns:
        ResponseModel: Pipeline 列表
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        pipelines = await PipelineService.list_pipelines(
            session=session,
            skip=skip,
            limit=limit
        )
        
        data = [
            {
                "id": p.id,
                "description": p.description[:100] + "..." if len(p.description) > 100 else p.description,
                "status": p.status.value,
                "current_stage": p.current_stage.value if p.current_stage else None,
                "created_at": p.created_at.isoformat() if p.created_at else None
            }
            for p in pipelines
        ]
        
        return success_response(
            data={
                "total": len(data),
                "pipelines": data
            },
            request_id=request_id
        )
    except Exception as e:
        return error_response(
            error=f"Failed to list pipelines: {str(e)}",
            request_id=request_id
        )


@router.post("/pipeline/{pipeline_id}/approve", response_model=ResponseModel)
async def approve_pipeline(
    request: Request,
    pipeline_id: int,
    data: PipelineApproveRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    审批 Pipeline，允许进入下一阶段
    
    Args:
        pipeline_id: Pipeline ID
        data: 审批信息（notes, feedback）
        
    Returns:
        ResponseModel: 审批结果
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        result = await PipelineService.approve_pipeline(
            pipeline_id=pipeline_id,
            notes=data.notes,
            feedback=data.feedback,
            session=session
        )
        
        if not result["success"]:
            return error_response(
                error=result["error"],
                request_id=request_id
            )
        
        return success_response(
            data=result["data"],
            request_id=request_id
        )
    except Exception as e:
        return error_response(
            error=f"Failed to approve pipeline: {str(e)}",
            request_id=request_id
        )


@router.post("/pipeline/{pipeline_id}/reject", response_model=ResponseModel)
async def reject_pipeline(
    request: Request,
    pipeline_id: int,
    data: PipelineRejectRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    驳回 Pipeline，退回当前阶段重新执行
    
    Args:
        pipeline_id: Pipeline ID
        data: 驳回信息（reason, suggested_changes）
        
    Returns:
        ResponseModel: 驳回结果
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        result = await PipelineService.reject_pipeline(
            pipeline_id=pipeline_id,
            reason=data.reason,
            suggested_changes=data.suggested_changes,
            session=session
        )
        
        if not result["success"]:
            return error_response(
                error=result["error"],
                request_id=request_id
            )
        
        return success_response(
            data=result["data"],
            request_id=request_id
        )
    except Exception as e:
        return error_response(
            error=f"Failed to reject pipeline: {str(e)}",
            request_id=request_id
        )
