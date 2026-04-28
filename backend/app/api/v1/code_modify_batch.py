"""
批量代码修改 API - 一次对话修改多个文件

使用场景：
- 用户选中多个元素（跨文件）
- 输入一个指令，同时修改所有相关文件
- 例如："将所有按钮改为圆角样式"可能涉及多个组件文件

与单文件修改的区别：
- 单文件：/code/modify - 修改一个文件中的一个元素
- 批量：/code/modify-batch - 修改多个文件中的多个元素
"""

from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_workspace_path, process_file_path
from app.core.database import get_session
from app.core.response import ResponseModel, success_response, error_response
from app.core.logging import error, info
from app.utils.code_modify_helper import (
    generate_diff,
    read_file_context,
    build_element_context,
)

router = APIRouter()


# ============================================
# 请求/响应模型
# ============================================

class FileContext(BaseModel):
    """单个文件的上下文"""
    file: str = Field(..., description="源文件路径")
    line: int = Field(..., description="行号", ge=1)
    column: int = Field(default=0, description="列号", ge=0)
    element_tag: str = Field(..., description="元素标签")
    element_id: Optional[str] = Field(default=None, description="元素 ID")
    element_class: Optional[str] = Field(default=None, description="元素 class")
    element_html: str = Field(..., description="元素 outerHTML")
    element_text: Optional[str] = Field(default=None, description="元素文本")


class BatchCodeModifyRequest(BaseModel):
    """批量代码修改请求"""
    files: List[FileContext] = Field(
        ...,
        description="要修改的文件列表",
        min_length=1,
        max_length=10  # 限制最多 10 个文件，避免请求过大
    )
    user_instruction: str = Field(
        ...,
        description="用户修改指令",
        example="将所有按钮改为圆角样式，并统一使用蓝色主题"
    )
    auto_apply: bool = Field(
        default=True,
        description="是否自动应用变更到文件系统"
    )


class FileChangeResult(BaseModel):
    """单个文件的变更结果"""
    file: str = Field(..., description="文件路径")
    success: bool = Field(..., description="是否成功")
    error: Optional[str] = Field(default=None, description="错误信息")
    diff: Optional[str] = Field(default=None, description="代码 diff")


class BatchCodeModifyResponse(BaseModel):
    """批量代码修改响应"""
    summary: str = Field(default="", description="整体变更摘要")
    total_files: int = Field(default=0, description="总文件数")
    success_files: int = Field(default=0, description="成功修改的文件数")
    failed_files: int = Field(default=0, description="失败的文件数")
    results: List[FileChangeResult] = Field(default_factory=list, description="每个文件的变更结果")





# ============================================
# API 端点
# ============================================

@router.post(
    "/code/modify-batch",
    response_model=ResponseModel,
    summary="批量代码修改",
    description="""
    批量修改多个文件，一次对话解决多文件更改。
    
    适用场景：
    - 选中多个元素（跨文件）
    - 统一修改多个文件中的相似元素
    - 批量样式调整
    
    流程：
    1. 为每个文件调用 QuickCoderAgent 生成变更
    2. 并行处理提高效率
    3. 汇总所有变更结果
    4. 可选：自动应用所有变更
    """
)
async def modify_code_batch(
    request: Request,
    data: BatchCodeModifyRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    批量代码修改 - 一次对话修改多个文件
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    info("=" * 60)
    info("批量代码修改开始", request_id=request_id)
    info(f"用户指令: {data.user_instruction[:50]}")
    info(f"涉及文件数: {len(data.files)}")

    try:
        # 导入依赖
        from app.service.code_modifier import CodeModifierService
        from app.agents.quick_coder import quick_coder_agent
        from app.service.code_executor import CodeExecutorService

        # 确定工作目录
        workspace = get_workspace_path("frontend")

        info(f"工作目录: {workspace}")
        
        if not workspace.exists():
            return error_response(
                error=f"工作目录不存在: {workspace}",
                request_id=request_id
            )

        # 准备修改服务
        modifier = CodeModifierService(str(workspace))

        # 存储所有结果
        results: List[FileChangeResult] = []
        changes_to_apply: Dict[str, str] = {}  # 要应用的变更

        # 逐个处理每个文件
        for i, file_ctx in enumerate(data.files, 1):
            info(f"\n处理文件 {i}/{len(data.files)}: {file_ctx.file}")

            file_path = process_file_path(file_ctx.file)

            try:
                # 1. 读取文件
                ctx_result = read_file_context(
                    file_path,
                    file_ctx.line,
                    context_lines=30,
                    workspace=workspace
                )
                content = ctx_result.content
                surrounding = ctx_result.surrounding
                info(f"  文件读取成功: {len(content)} 字符")

                # 2. 构建元素上下文
                element_ctx = build_element_context(
                    tag=file_ctx.element_tag,
                    outer_html=file_ctx.element_html,
                    element_id=file_ctx.element_id,
                    class_name=file_ctx.element_class,
                    text=file_ctx.element_text,
                )
                
                # 3. 调用 QuickCoderAgent
                info(f"  调用 QuickCoderAgent...")
                result = await quick_coder_agent.generate_code(
                    user_instruction=data.user_instruction,
                    file_path=file_path,
                    file_content=content,
                    surrounding_code=surrounding,
                    element_context=element_ctx,
                    line=file_ctx.line,
                )
                
                if not result.get("success"):
                    error_msg = result.get("error", "未知错误")
                    info(f"  ❌ 代码生成失败: {error_msg}")
                    results.append(FileChangeResult(
                        file=file_ctx.file,
                        success=False,
                        error=error_msg
                    ))
                    continue
                
                # 4. 提取变更
                output = result.get("output", {})
                files = output.get("files", [])
                
                if not files:
                    info(f"  ⚠️ 代码生成结果为空")
                    results.append(FileChangeResult(
                        file=file_ctx.file,
                        success=False,
                        error="代码生成结果为空"
                    ))
                    continue
                
                new_content = files[0]["content"]
                diff = generate_diff(content, new_content, file_path)
                
                info(f"  ✅ 代码生成成功")
                
                # 记录变更
                results.append(FileChangeResult(
                    file=file_ctx.file,
                    success=True,
                    diff=diff
                ))
                
                # 保存变更以便批量应用
                changes_to_apply[file_path] = new_content
                
            except FileNotFoundError:
                error_msg = f"文件不存在: {file_ctx.file}"
                info(f"  ❌ {error_msg}")
                results.append(FileChangeResult(
                    file=file_ctx.file,
                    success=False,
                    error=error_msg
                ))
            except Exception as e:
                error_msg = str(e)
                info(f"  ❌ 异常: {error_msg}")
                results.append(FileChangeResult(
                    file=file_ctx.file,
                    success=False,
                    error=error_msg
                ))
        
        # 5. 应用所有变更（如果 auto_apply 为 True）
        if data.auto_apply and changes_to_apply:
            info(f"\n应用 {len(changes_to_apply)} 个文件的变更...")
            try:
                executor = CodeExecutorService(str(workspace))
                executor.apply_changes(changes_to_apply, create_if_missing=False)
                info("✅ 所有变更已应用")
            except Exception as e:
                error(f"应用变更失败: {e}")
                # 标记所有文件为失败
                for result in results:
                    if result.success:
                        result.error = f"应用变更失败: {e}"
        
        # 6. 生成汇总
        total = len(results)
        success_count = sum(1 for r in results if r.success)
        failed_count = total - success_count
        
        summary = f"批量修改完成: {success_count}/{total} 个文件成功"
        if failed_count > 0:
            summary += f", {failed_count} 个失败"
        
        info(f"\n{summary}")
        info("=" * 60)
        
        # 7. 构建响应
        response_data = {
            "summary": summary,
            "total_files": total,
            "success_files": success_count,
            "failed_files": failed_count,
            "results": [r.dict() for r in results]
        }
        
        return success_response(
            data=response_data,
            request_id=request_id
        )

    except Exception as e:
        error(f"批量代码修改失败: {e}", exc_info=True)
        return error_response(
            error=f"批量修改失败: {str(e)}",
            request_id=request_id
        )
