"""
轻量级代码修改 API - 直接修改，不走 Pipeline

职责：
- 接收前端传来的元素上下文和修改指令
- 读取源码文件上下文
- 调用 QuickCoderAgent 生成代码变更
- 应用变更到文件系统
- 返回变更详情

错误排查清单：
1. 文件路径处理（Windows 反斜杠、src/ 前缀）
2. JSON 序列化（避免 Pydantic 模型直接返回）
3. 异常捕获（所有可能出错的地方都有 try-except）
4. 日志记录（每个步骤都有日志）
"""

from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.response import ResponseModel, success_response, error_response
from app.core.logging import error, info
from app.utils.code_modify_helper import (
    generate_diff,
    read_file_context,
    validate_file_path,
    read_file_content,
    write_file_content,
    build_element_context,
)

router = APIRouter()


# ============================================
# 请求/响应模型
# ============================================

class CodeModifySourceContext(BaseModel):
    """源码位置上下文"""
    file: str = Field(..., description="源文件路径")
    line: int = Field(..., description="行号", ge=1)
    column: int = Field(default=0, description="列号", ge=0)


class CodeModifyElementContext(BaseModel):
    """元素上下文"""
    tag: str = Field(..., description="元素标签")
    id: Optional[str] = Field(default=None, description="元素 ID")
    class_name: Optional[str] = Field(default=None, description="元素 class")
    outer_html: str = Field(..., description="元素 outerHTML")
    text: Optional[str] = Field(default=None, description="元素文本")
    xpath: Optional[str] = Field(default=None, description="元素 XPath")
    selector: Optional[str] = Field(default=None, description="CSS 选择器")


class CodeModifyRequest(BaseModel):
    """轻量级代码修改请求"""
    source_context: CodeModifySourceContext = Field(..., description="源码位置上下文")
    element_context: CodeModifyElementContext = Field(..., description="页面元素上下文")
    user_instruction: str = Field(..., description="用户修改指令")
    auto_apply: bool = Field(default=True, description="是否自动应用变更")





# ============================================
# API 端点
# ============================================

@router.post(
    "/code/modify",
    response_model=ResponseModel,
    summary="轻量级代码修改",
    description="直接修改代码，不走完整 Pipeline。适用于单个元素的快速修改。"
)
async def modify_code_directly(
    request: Request,
    data: CodeModifyRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    轻量级代码修改 - 直接修改，不走 Pipeline
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    info("=" * 50)
    info("轻量代码修改开始", request_id=request_id)
    info(f"用户指令: {data.user_instruction[:50]}")
    info(f"目标文件: {data.source_context.file}")
    info(f"目标行号: {data.source_context.line}")

    try:
        # 1. 导入依赖（延迟导入避免循环依赖）
        try:
            from app.service.code_modifier import CodeModifierService
            from app.agents.quick_coder import quick_coder_agent
            from app.service.code_executor import CodeExecutorService
        except ImportError as e:
            error(f"导入失败: {e}")
            return error_response(
                error=f"服务初始化失败: {e}",
                request_id=request_id
            )

        # 2. 确定工作目录
        try:
            workspace = get_workspace_path("frontend")

            info(f"工作目录: {workspace}")
            info(f"工作目录存在: {workspace.exists()}")

            if not workspace.exists():
                return error_response(
                    error=f"工作目录不存在: {workspace}",
                    request_id=request_id
                )
        except Exception as e:
            error(f"确定工作目录失败: {e}")
            return error_response(
                error=f"确定工作目录失败: {e}",
                request_id=request_id
            )

        # 3. 处理文件路径
        try:
            file_path = process_file_path(data.source_context.file)
            info(f"处理后的文件路径: {file_path}")
        except Exception as e:
            error(f"处理文件路径失败: {e}")
            return error_response(
                error=f"处理文件路径失败: {e}",
                request_id=request_id
            )

        # 4. 读取文件上下文
        content = ""
        surrounding = ""
        start_line = 0
        end_line = 0
        
        try:
            modifier = CodeModifierService(str(workspace))
            content, surrounding, start_line, end_line = modifier.read_file_context(
                file_path,
                data.source_context.line,
                context_lines=30
            )
            info(f"文件读取成功: {file_path}")
            info(f"文件大小: {len(content)} 字符")
            info(f"上下文行数: {start_line}-{end_line}")
        except FileNotFoundError:
            # 尝试使用原始路径
            info(f"使用处理后路径未找到，尝试原始路径: {data.source_context.file}")
            try:
                content, surrounding, start_line, end_line = modifier.read_file_context(
                    data.source_context.file,
                    data.source_context.line,
                    context_lines=30
                )
                file_path = data.source_context.file
                info(f"使用原始路径成功")
            except FileNotFoundError:
                error(f"文件不存在: {data.source_context.file}")
                return error_response(
                    error=f"文件不存在: {data.source_context.file}",
                    request_id=request_id
                )
        except Exception as e:
            error(f"读取文件失败: {e}")
            return error_response(
                error=f"读取文件失败: {e}",
                request_id=request_id
            )

        # 5. 调用 QuickCoderAgent 生成代码变更
        try:
            element_ctx = build_element_context(
                tag=data.element_context.tag,
                outer_html=data.element_context.outer_html,
                element_id=data.element_context.id,
                class_name=data.element_context.class_name,
                text=data.element_context.text,
                xpath=data.element_context.xpath,
                selector=data.element_context.selector,
            )
            
            info("调用 QuickCoderAgent...")
            result = await quick_coder_agent.generate_code(
                user_instruction=data.user_instruction,
                file_path=file_path,
                file_content=content,
                surrounding_code=surrounding,
                element_context=element_ctx,
                line=data.source_context.line,
            )
            info(f"QuickCoderAgent 返回: success={result.get('success')}")
        except Exception as e:
            error(f"调用 QuickCoderAgent 失败: {e}")
            return error_response(
                error=f"代码生成失败: {e}",
                request_id=request_id
            )

        # 6. 检查生成结果
        if not result.get("success"):
            error_msg = result.get("error", "未知错误")
            error(f"代码生成失败: {error_msg}")
            return error_response(
                error=f"代码生成失败: {error_msg}",
                request_id=request_id
            )

        output = result.get("output", {})
        files = output.get("files", [])
        
        if not files:
            error("代码生成结果为空")
            return error_response(
                error="代码生成结果为空",
                request_id=request_id
            )
        
        info(f"生成文件数: {len(files)}")

        # 7. 应用变更（如果 auto_apply 为 True）
        info(f"检查 auto_apply: {data.auto_apply}")
        if data.auto_apply:
            try:
                executor = CodeExecutorService(str(workspace))
                changes = {f["file_path"]: f["content"] for f in files}
                info(f"准备应用变更", changes_count=len(changes), files=list(changes.keys()))
                info(f"工作目录: {workspace}")
                
                result = executor.apply_changes(changes, create_if_missing=False)
                info(f"变更结果: success={result.success}, summary={result.summary}")
                
                if not result.success:
                    error(f"变更失败: {result.errors}")
                    for change in result.changes:
                        if not change.success:
                            error(f"  - {change.file_path}: {change.error}")
                else:
                    info("代码变更已应用", files=list(changes.keys()))
            except Exception as e:
                error(f"应用变更失败: {e}")
                import traceback
                error(traceback.format_exc())
                return error_response(
                    error=f"应用变更失败: {e}",
                    request_id=request_id
                )
        else:
            info("跳过应用变更（auto_apply=False）")

        # 8. 生成 diff
        try:
            new_content = files[0]["content"] if files else ""
            diff = generate_diff(content, new_content, file_path)
            info(f"Diff 生成完成: {len(diff)} 字符")
        except Exception as e:
            error(f"生成 diff 失败: {e}")
            diff = ""

        # 9. 构建响应（使用字典，不是 Pydantic 模型）
        try:
            response_data = {
                "summary": output.get("summary", ""),
                "files_changed": [f["file_path"] for f in files],
                "new_content": new_content,
                "original_content": content,
                "diff": diff,
            }
            info(f"响应数据构建完成: {len(response_data)} 个字段")
        except Exception as e:
            error(f"构建响应数据失败: {e}")
            return error_response(
                error=f"构建响应失败: {e}",
                request_id=request_id
            )

        info("轻量代码修改完成")
        info("=" * 50)

        return success_response(
            data=response_data,
            request_id=request_id
        )

    except Exception as e:
        error(f"轻量代码修改失败: {e}", exc_info=True)
        return error_response(
            error=f"修改失败: {str(e)}",
            request_id=request_id
        )


@router.get(
    "/code/file-content",
    response_model=ResponseModel,
    summary="获取文件内容",
    description="读取指定文件的完整内容，用于前端预览缓存"
)
async def get_file_content(
    request: Request,
    path: str,
    session: AsyncSession = Depends(get_session)
):
    """
    获取文件内容 - 用于前端预览缓存
    """
    request_id = getattr(request.state, "request_id", "unknown")

    try:
        # 读取文件内容
        success, content, error_msg = read_file_content(path)

        if not success:
            return error_response(
                error=error_msg,
                request_id=request_id
            )

        file_path = process_file_path(path)

        return success_response(
            data={
                "path": file_path,
                "content": content,
                "size": len(content),
            },
            request_id=request_id
        )

    except Exception as e:
        error(f"读取文件内容失败: {e}", exc_info=True)
        return error_response(
            error=f"读取文件失败: {str(e)}",
            request_id=request_id
        )


class FileContentUpdateRequest(BaseModel):
    """文件内容更新请求"""
    path: str = Field(..., description="文件路径")
    content: str = Field(..., description="文件内容")


@router.put(
    "/code/file-content",
    response_model=ResponseModel,
    summary="更新文件内容",
    description="直接写入文件内容，用于预览模式"
)
async def update_file_content(
    request: Request,
    data: FileContentUpdateRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    更新文件内容 - 用于预览模式直接写入文件
    """
    request_id = getattr(request.state, "request_id", "unknown")

    try:
        # 写入文件内容
        success, error_msg = write_file_content(data.path, data.content)

        if not success:
            return error_response(
                error=error_msg,
                request_id=request_id
            )

        file_path = process_file_path(data.path)

        return success_response(
            data={
                "path": file_path,
                "size": len(data.content),
            },
            request_id=request_id
        )

    except Exception as e:
        error(f"写入文件内容失败: {e}", exc_info=True)
        return error_response(
            error=f"写入文件失败: {str(e)}",
            request_id=request_id
        )
