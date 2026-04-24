"""
Pipeline API 路由
路由层 - 只负责路由定义和参数解析
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Path
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_session
from app.core.response import ResponseModel, success_response, error_response
from app.service.pipeline import PipelineService

router = APIRouter()


class PipelineCreateRequest(BaseModel):
    """Pipeline 创建请求模型"""
    requirement: str = Field(
        ...,
        description="开发需求描述",
        example="创建一个用户登录页面，包含用户名和密码输入框"
    )


class PipelineCreateResponse(BaseModel):
    """Pipeline 创建响应数据"""
    pipeline_id: int = Field(..., description="Pipeline 唯一标识符")
    status: str = Field(..., description="Pipeline 状态: running, paused, success, failed")
    current_stage: Optional[str] = Field(None, description="当前执行阶段: REQUIREMENT, DESIGN, CODING")
    created_at: str = Field(..., description="创建时间 (ISO 8601 格式)")


class PipelineStageInfo(BaseModel):
    """Pipeline 阶段信息"""
    id: int = Field(..., description="阶段 ID")
    name: str = Field(..., description="阶段名称")
    status: str = Field(..., description="阶段状态")
    input_data: Optional[dict] = Field(None, description="阶段输入数据")
    output_data: Optional[dict] = Field(None, description="阶段输出数据")
    created_at: Optional[str] = Field(None, description="创建时间")
    completed_at: Optional[str] = Field(None, description="完成时间")


class PipelineDeliveryInfo(BaseModel):
    """Pipeline 交付物信息（仅成功状态返回）"""
    git_branch: Optional[str] = Field(None, description="Git 分支名")
    commit_hash: Optional[str] = Field(None, description="Git 提交哈希")
    pr_url: Optional[str] = Field(None, description="Pull Request URL")
    pr_created: bool = Field(False, description="是否已创建 PR")
    summary: str = Field("", description="代码变更摘要")
    files_changed: dict = Field({}, description="变更文件统计")
    diff_summary: Optional[str] = Field(None, description="代码 diff 摘要")


class PipelineStatusResponse(BaseModel):
    """Pipeline 状态响应数据"""
    id: int = Field(..., description="Pipeline ID")
    description: str = Field(..., description="需求描述")
    status: str = Field(..., description="Pipeline 状态")
    current_stage: Optional[str] = Field(None, description="当前阶段")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")
    stages: list[PipelineStageInfo] = Field([], description="所有阶段信息")
    delivery: Optional[PipelineDeliveryInfo] = Field(None, description="交付物信息（仅成功状态）")


class PipelineListItem(BaseModel):
    """Pipeline 列表项"""
    id: int = Field(..., description="Pipeline ID")
    description: str = Field(..., description="需求描述（前100字符）")
    status: str = Field(..., description="Pipeline 状态")
    current_stage: Optional[str] = Field(None, description="当前阶段")
    created_at: str = Field(..., description="创建时间")


class PipelineListResponse(BaseModel):
    """Pipeline 列表响应数据"""
    total: int = Field(..., description="总数")
    pipelines: list[PipelineListItem] = Field([], description="Pipeline 列表")


class PipelineApproveRequest(BaseModel):
    """Pipeline 审批请求模型"""
    notes: Optional[str] = Field(
        None,
        description="审批备注",
        example="设计合理，可以进入开发阶段"
    )
    feedback: Optional[str] = Field(
        None,
        description="反馈建议",
        example="建议增加错误处理逻辑"
    )


class PipelineApproveResponse(BaseModel):
    """Pipeline 审批响应数据"""
    pipeline_id: int = Field(..., description="Pipeline ID")
    action: str = Field(..., description="操作类型: approved")
    previous_stage: Optional[str] = Field(None, description="前一阶段")
    next_stage: Optional[str] = Field(None, description="下一阶段")
    notes: Optional[str] = Field(None, description="审批备注")


class PipelineRejectRequest(BaseModel):
    """Pipeline 驳回请求模型"""
    reason: str = Field(
        ...,
        description="驳回原因",
        example="需求描述不够清晰，需要补充"
    )
    suggested_changes: Optional[str] = Field(
        None,
        description="建议修改内容",
        example="请补充用户交互流程说明"
    )


class PipelineRejectResponse(BaseModel):
    """Pipeline 驳回响应数据"""
    pipeline_id: int = Field(..., description="Pipeline ID")
    action: str = Field(..., description="操作类型: rejected")
    current_stage: Optional[str] = Field(None, description="当前阶段")
    reason: str = Field(..., description="驳回原因")
    retry_count: int = Field(0, description="当前阶段重试次数")


@router.post(
    "/pipeline/create",
    response_model=ResponseModel,
    summary="创建新的 Pipeline",
    description="""
    提交开发需求，系统自动创建 Pipeline 并开始执行。
    
    Pipeline 执行流程：
    1. **REQUIREMENT**: 需求分析阶段
    2. **DESIGN**: 架构设计阶段（需要人工审批）
    3. **CODING**: 代码开发阶段（需要人工审批）
    
    创建成功后返回 Pipeline ID，可用于后续状态查询和操作。
    """,
    response_description="创建成功，返回 Pipeline 基本信息"
)
async def create_pipeline(
    request: Request,
    data: PipelineCreateRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    创建新的 Pipeline
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        pipeline = await PipelineService.create_pipeline(
            requirement=data.requirement,
            session=session
        )
        
        response_data = PipelineCreateResponse(
            pipeline_id=pipeline.id,
            status=pipeline.status.value,
            current_stage=pipeline.current_stage.value if pipeline.current_stage else None,
            created_at=pipeline.created_at.isoformat()
        )
        
        return success_response(
            data=response_data.model_dump(),
            request_id=request_id
        )
    except Exception as e:
        return error_response(
            error=f"Failed to create pipeline: {str(e)}",
            request_id=request_id
        )


@router.get(
    "/pipeline/{pipeline_id}/status",
    response_model=ResponseModel,
    summary="获取 Pipeline 状态",
    description="""
    查询指定 Pipeline 的详细状态和阶段信息。
    
    根据 Pipeline 状态返回不同信息：
    - **running/paused**: 返回当前执行阶段和进度
    - **success**: 额外返回交付物信息（Git 分支、PR 链接等）
    - **failed**: 返回错误信息
    """,
    response_description="Pipeline 详细状态信息"
)
async def get_pipeline_status(
    request: Request,
    pipeline_id: int = Path(..., description="Pipeline ID", ge=1),
    session: AsyncSession = Depends(get_session)
):
    """
    获取 Pipeline 状态
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
        
        # 构建阶段数据
        stages_data = []
        if pipeline.stages:
            for stage in pipeline.stages:
                stage_data = PipelineStageInfo(
                    id=stage.id,
                    name=stage.name.value,
                    status=stage.status.value,
                    input_data=stage.input_data,
                    output_data=stage.output_data,
                    created_at=stage.created_at.isoformat() if stage.created_at else None,
                    completed_at=stage.completed_at.isoformat() if stage.completed_at else None
                )
                stages_data.append(stage_data.model_dump())
        
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
            coding_stage = None
            for stage in pipeline.stages:
                if stage.name.value == "CODING":
                    coding_stage = stage
                    break
            
            if coding_stage and coding_stage.output_data:
                output_data = coding_stage.output_data
                
                delivery_info = PipelineDeliveryInfo(
                    git_branch=output_data.get("git_branch"),
                    commit_hash=output_data.get("commit_hash"),
                    pr_url=output_data.get("pr_url"),
                    pr_created=output_data.get("pr_created", False),
                    summary=output_data.get("coder_output", {}).get("summary", ""),
                    files_changed=output_data.get("execution_summary", {})
                )
                
                # 尝试获取 Git diff 摘要
                try:
                    from app.service.git_provider import GitProviderService
                    git_service = GitProviderService()
                    
                    branch_name = output_data.get("git_branch")
                    if branch_name:
                        try:
                            git_service.checkout_branch(branch_name)
                            diff_summary = git_service.get_diff(cached=True)
                            delivery_info.diff_summary = diff_summary[:2000] if diff_summary else None
                        except Exception:
                            pass
                except Exception:
                    pass
                
                response_data["delivery"] = delivery_info.model_dump()
        
        return success_response(
            data=response_data,
            request_id=request_id
        )
    except Exception as e:
        return error_response(
            error=f"Failed to get pipeline status: {str(e)}",
            request_id=request_id
        )


@router.get(
    "/pipelines",
    response_model=ResponseModel,
    summary="列出所有 Pipeline",
    description="分页获取 Pipeline 列表，支持按创建时间排序。",
    response_description="Pipeline 列表及总数"
)
async def list_pipelines(
    request: Request,
    skip: int = Query(0, description="跳过数量（分页偏移量）", ge=0),
    limit: int = Query(100, description="返回数量限制", ge=1, le=1000),
    session: AsyncSession = Depends(get_session)
):
    """
    列出所有 Pipeline
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        pipelines = await PipelineService.list_pipelines(
            session=session,
            skip=skip,
            limit=limit
        )
        
        pipeline_items = [
            PipelineListItem(
                id=p.id,
                description=p.description[:100] + "..." if len(p.description) > 100 else p.description,
                status=p.status.value,
                current_stage=p.current_stage.value if p.current_stage else None,
                created_at=p.created_at.isoformat() if p.created_at else None
            ).model_dump()
            for p in pipelines
        ]
        
        response_data = PipelineListResponse(
            total=len(pipeline_items),
            pipelines=pipeline_items
        )
        
        return success_response(
            data=response_data.model_dump(),
            request_id=request_id
        )
    except Exception as e:
        return error_response(
            error=f"Failed to list pipelines: {str(e)}",
            request_id=request_id
        )


@router.post(
    "/pipeline/{pipeline_id}/approve",
    response_model=ResponseModel,
    summary="审批 Pipeline",
    description="""
    审批当前阶段的 Pipeline，允许进入下一阶段。
    
    审批流程：
    - **DESIGN 阶段**: 审批后进入 CODING 阶段
    - **CODING 阶段**: 审批后完成 Pipeline
    
    需要提供审批备注和反馈建议。
    """,
    response_description="审批结果及下一阶段信息"
)
async def approve_pipeline(
    request: Request,
    pipeline_id: int = Path(..., description="Pipeline ID", ge=1),
    data: PipelineApproveRequest = None,
    session: AsyncSession = Depends(get_session)
):
    """
    审批 Pipeline，允许进入下一阶段
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        result = await PipelineService.approve_pipeline(
            pipeline_id=pipeline_id,
            notes=data.notes if data else None,
            feedback=data.feedback if data else None,
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


@router.post(
    "/pipeline/{pipeline_id}/reject",
    response_model=ResponseModel,
    summary="驳回 Pipeline",
    description="""
    驳回当前阶段的 Pipeline，退回当前阶段重新执行。
    
    驳回后：
    - 当前阶段状态重置为 pending
    - 记录驳回原因和建议修改内容
    - 增加重试计数
    
    需要提供详细的驳回原因。
    """,
    response_description="驳回结果及重试信息"
)
async def reject_pipeline(
    request: Request,
    pipeline_id: int = Path(..., description="Pipeline ID", ge=1),
    data: PipelineRejectRequest = None,
    session: AsyncSession = Depends(get_session)
):
    """
    驳回 Pipeline，退回当前阶段重新执行
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        result = await PipelineService.reject_pipeline(
            pipeline_id=pipeline_id,
            reason=data.reason if data else "No reason provided",
            suggested_changes=data.suggested_changes if data else None,
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
