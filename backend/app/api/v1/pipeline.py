"""
Pipeline API 路由
路由层 - 只负责路由定义和参数解析
"""

import asyncio
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Path, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_session, async_session_factory
from app.core.response import ResponseModel, success_response, error_response
from app.core.sse_log_buffer import get_or_create_buffer, remove_buffer
from app.service.pipeline import PipelineService

router = APIRouter()


class PipelineCreateRequest(BaseModel):
    """Pipeline 创建请求模型"""
    requirement: str = Field(
        ...,
        description="开发需求描述",
        example="创建一个用户登录页面，包含用户名和密码输入框"
    )
    elementContext: Optional[dict] = Field(
        default=None,
        description="页面元素上下文（HTML、XPath、数据源等）",
        example={"html": "<div>...</div>", "xpath": "//div[@id='app']", "data_source": "api/v1/users"}
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
    current_stage_index: int = Field(0, description="当前阶段索引（0=REQUIREMENT, 1=DESIGN, 2=CODING）")
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


async def run_architect_task(pipeline_id: int, requirement: str, element_context: Optional[Dict[str, Any]]) -> None:
    """后台任务：使用独立 session，确保事务完整性"""
    async with async_session_factory() as session:
        try:
            await PipelineService.run_architect_task(
                pipeline_id=pipeline_id,
                requirement=requirement,
                element_context=element_context,
                session=session
            )
            # 显式提交（不依赖上下文管理器的隐式行为）
            await session.commit()
        except Exception as e:
            await session.rollback()
            # 记录结构化日志，而不是 print
            from app.core.logging import op_logger
            op_logger.log_pipeline_status_change(
                pipeline_id=pipeline_id,
                old_status='running',
                new_status='failed',
                stage='REQUIREMENT',
                error=str(e)
            )
            # 更新 pipeline 状态为 failed，让前端感知
            try:
                async with async_session_factory() as err_session:
                    await PipelineService.mark_pipeline_failed(
                        pipeline_id=pipeline_id,
                        error=str(e),
                        session=err_session
                    )
                    await err_session.commit()
            except Exception:
                pass


async def run_coding_task(pipeline_id: int) -> None:
    """后台任务：触发 CODING 阶段，使用独立 session"""
    async with async_session_factory() as session:
        try:
            from app.core.logging import op_logger
            from app.core.sse_log_buffer import push_log

            await push_log(pipeline_id, "info", "后台任务启动：开始执行代码生成...", stage="CODING")

            result = await PipelineService.trigger_coding_phase(
                pipeline_id=pipeline_id,
                session=session
            )

            if result["success"]:
                await session.commit()
                await push_log(pipeline_id, "info", "代码生成任务已完成，等待人工审查", stage="CODE_REVIEW")
            else:
                await session.rollback()
                op_logger.log_pipeline_status_change(
                    pipeline_id=pipeline_id,
                    old_status='running',
                    new_status='failed',
                    stage='CODING',
                    error=result.get("message", "Unknown error")
                )
                # 更新 pipeline 状态为 failed
                try:
                    async with async_session_factory() as err_session:
                        await PipelineService.mark_pipeline_failed(
                            pipeline_id=pipeline_id,
                            error=result.get("message", "Coding phase failed"),
                            session=err_session
                        )
                        await err_session.commit()
                except Exception:
                    pass
        except Exception as e:
            await session.rollback()
            from app.core.logging import op_logger
            from app.core.sse_log_buffer import push_log

            op_logger.log_pipeline_status_change(
                pipeline_id=pipeline_id,
                old_status='running',
                new_status='failed',
                stage='CODING',
                error=str(e)
            )
            await push_log(pipeline_id, "error", f"代码生成任务失败: {str(e)}", stage="CODING")
            # 更新 pipeline 状态为 failed
            try:
                async with async_session_factory() as err_session:
                    await PipelineService.mark_pipeline_failed(
                        pipeline_id=pipeline_id,
                        error=str(e),
                        session=err_session
                    )
                    await err_session.commit()
            except Exception:
                pass


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
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """
    创建新的 Pipeline
    
    使用 BackgroundTasks 异步执行 ArchitectAgent 分析
    立即返回 Pipeline ID，后台运行分析任务
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        # 1. 创建 Pipeline 记录
        pipeline = await PipelineService.create_pipeline_record(
            requirement=data.requirement,
            element_context=data.elementContext,
            session=session
        )
        
        # 2. 添加后台任务运行 ArchitectAgent
        background_tasks.add_task(
            run_architect_task,
            pipeline_id=pipeline.id,
            requirement=data.requirement,
            element_context=data.elementContext
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


def _extract_coding_summary(output_data: dict) -> dict:
    """
    提取 CODING 阶段的摘要信息，排除大字段

    避免在状态接口中传输完整的代码内容，减少带宽和内存占用
    """
    if not output_data:
        return output_data

    summary = {
        "tests_included": output_data.get("tests_included", False),
        "files_count": 0,
        "file_names": [],
        "summary": "",
    }

    # 提取 multi_agent_output 中的摘要
    multi_agent_output = output_data.get("multi_agent_output", {})
    if multi_agent_output:
        files = multi_agent_output.get("files", [])
        summary["files_count"] = len(files)
        summary["file_names"] = [f.get("file_path", "") for f in files[:10]]  # 最多10个文件名
        summary["summary"] = multi_agent_output.get("summary", "")[:500]  # 限制摘要长度

        # 如果有测试覆盖信息，也包含进来
        if "coverage_targets" in multi_agent_output:
            summary["coverage_targets_count"] = len(multi_agent_output["coverage_targets"])

    # 如果有错误信息，保留
    if "error" in output_data:
        summary["error"] = output_data["error"]

    return summary


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

    注意：CODING 阶段的 output_data 只包含摘要信息，完整代码请使用 /pipeline/{id}/diff 接口
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
        
        # 构建阶段数据（优化：排除大字段，避免传输过多数据）
        stages_data = []
        if pipeline.stages:
            for stage in pipeline.stages:
                # 优化：对于 CODING 阶段，只返回摘要信息，不返回完整代码内容
                input_data = stage.input_data
                output_data = stage.output_data

                if stage.name.value == "CODING" and output_data:
                    # 只保留关键元数据，排除大字段
                    output_data = cls._extract_coding_summary(output_data)

                stage_data = PipelineStageInfo(
                    id=stage.id,
                    name=stage.name.value,
                    status=stage.status.value,
                    input_data=input_data,
                    output_data=output_data,
                    created_at=stage.created_at.isoformat() if stage.created_at else None,
                    completed_at=stage.completed_at.isoformat() if stage.completed_at else None
                )
                stages_data.append(stage_data.model_dump())
        
        # 计算当前阶段索引（用于前端进度显示）
        stage_order = ["REQUIREMENT", "DESIGN", "CODING"]
        current_stage_index = 0
        if pipeline.current_stage:
            try:
                current_stage_index = stage_order.index(pipeline.current_stage.value)
            except ValueError:
                current_stage_index = 0
        
        # 构建基础响应数据
        response_data = {
            "id": pipeline.id,
            "description": pipeline.description,
            "status": pipeline.status.value,
            "current_stage": pipeline.current_stage.value if pipeline.current_stage else None,
            "current_stage_index": current_stage_index,
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
    - **DESIGN 阶段**: 审批后异步进入 CODING 阶段
    - **CODE_REVIEW 阶段**: 审批后异步进入 DELIVERY 阶段

    对于 DESIGN 阶段的审批，会立即返回成功响应，后台异步执行代码生成任务。
    前端应通过 SSE 日志流监控任务进度。
    """,
    response_description="审批结果及下一阶段信息"
)
async def approve_pipeline(
    request: Request,
    pipeline_id: int = Path(..., description="Pipeline ID", ge=1),
    data: PipelineApproveRequest = None,
    background_tasks: BackgroundTasks = None,
    session: AsyncSession = Depends(get_session)
):
    """
    审批 Pipeline，允许进入下一阶段

    DESIGN 阶段审批会立即返回，后台异步执行代码生成
    """
    request_id = getattr(request.state, "request_id", "unknown")

    try:
        result = await PipelineService.approve_pipeline(
            pipeline_id=pipeline_id,
            notes=data.notes if data else None,
            feedback=data.feedback if data else None,
            session=session,
            background_tasks=background_tasks
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


@router.get(
    "/pipeline/{pipeline_id}/logs",
    summary="SSE 实时日志流",
    description="""
    实时推送 Pipeline 的 Agent 日志流。

    使用 Server-Sent Events (SSE) 协议，前端通过 EventSource 连接。

    消息格式：
    - 普通日志: `data: {"ts": "09:05:40", "level": "info", "msg": "...", "stage": "REQUIREMENT"}`
    - 心跳: `: heartbeat`（每 15 秒）
    - 完成: `event: done\ndata: {}`

    客户端断开时自动清理资源。
    """,
    response_description="SSE 事件流"
)
async def stream_pipeline_logs(
    request: Request,
    pipeline_id: int = Path(..., description="Pipeline ID", ge=1),
    session: AsyncSession = Depends(get_session)
):
    """
    SSE 实时日志流端点
    """
    async def event_generator():
        buf = get_or_create_buffer(pipeline_id)
        heartbeat_count = 0

        while True:
            # 检查客户端是否断开
            if await request.is_disconnected():
                break

            try:
                # 等待日志消息，超时 15 秒
                msg = await asyncio.wait_for(buf.get(), timeout=15.0)
                yield f"data: {msg}\n\n"
            except asyncio.TimeoutError:
                # 发送心跳保持连接
                yield ": heartbeat\n\n"
                heartbeat_count += 1

                # 每 2 个心跳（30 秒）检查一次 pipeline 状态
                if heartbeat_count % 2 == 0:
                    try:
                        pipeline = await PipelineService.get_pipeline_status(pipeline_id, session)
                        if pipeline and pipeline.status.value in ("success", "failed"):
                            # Pipeline 已完成，发送 done 事件
                            yield 'event: done\ndata: {}\n\n'
                            break
                    except Exception:
                        pass  # 忽略查询错误，继续循环

        # 清理 buffer
        remove_buffer(pipeline_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Nginx 反代需要
            "Connection": "keep-alive",
        }
    )
