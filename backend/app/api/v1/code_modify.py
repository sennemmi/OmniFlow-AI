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

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings, process_file_path, get_workspace_path
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

        # 7. 执行搜索替换（带重试机制）
        max_retries = 3
        retry_count = 0
        new_content = None
        
        while retry_count < max_retries and new_content is None:
            if retry_count > 0:
                info(f"第 {retry_count} 次重试：重新调用 QuickCoderAgent...")
                try:
                    # 在重试时添加提示，告诉 AI 之前的搜索块匹配失败
                    retry_instruction = data.user_instruction + f"\n\n【重要提示】之前的代码定位失败，请尝试使用更精确的搜索块。原始文件第 {data.source_context.line} 行附近的内容是：\n{surrounding[:500]}"
                    result = await quick_coder_agent.generate_code(
                        user_instruction=retry_instruction,
                        file_path=file_path,
                        file_content=content,
                        surrounding_code=surrounding,
                        element_context=element_ctx,
                        line=data.source_context.line,
                    )
                    if not result.get("success"):
                        error(f"重试 {retry_count} 代码生成失败: {result.get('error')}")
                        break
                    output = result.get("output", {})
                    files = output.get("files", [])
                except Exception as e:
                    error(f"重试 {retry_count} 调用失败: {e}")
                    break
            
            file_change = files[0]
            change_type = file_change.get("change_type", "modify")
            search_block = file_change.get("search_block", "")
            replace_block = file_change.get("replace_block", "")
            provided_content = file_change.get("content", "")
            
            info(f"尝试搜索替换 (尝试 {retry_count + 1}/{max_retries})", 
                 change_type=change_type, 
                 has_search_block=bool(search_block),
                 has_replace_block=bool(replace_block))
            
            # 如果是 modify 模式且提供了搜索块，使用引擎进行替换
            if change_type == "modify" and search_block and replace_block:
                from app.service.search_replace_engine import search_replace_engine
                new_content = search_replace_engine.apply_search_replace(
                    original=content,
                    search_block=search_block,
                    replace_block=replace_block,
                    fallback_start=file_change.get("fallback_start_line"),
                    fallback_end=file_change.get("fallback_end_line")
                )
                
                if new_content is None:
                    error(f"第 {retry_count + 1} 次搜索替换失败，search_block 匹配失败")
                    retry_count += 1
                else:
                    info(f"搜索替换成功")
                    break
            else:
                # 回退到全量替换
                new_content = provided_content or content
                info(f"使用全量替换模式")
                break
        
        # 如果所有重试都失败，使用原始内容
        if new_content is None:
            error(f"所有 {max_retries} 次重试都失败，使用原始内容")
            new_content = content

        # 8. 应用变更（如果 auto_apply 为 True）
        info(f"检查 auto_apply: {data.auto_apply}")
        if data.auto_apply:
            try:
                executor = CodeExecutorService(str(workspace))
                files_list = files  # 文件列表
                info(f"准备应用变更", changes_count=len(files_list), files=[f.get("file_path") for f in files_list])
                info(f"工作目录: {workspace}")

                # 批量写入文件：先读取获取 read_token，再应用变更
                from app.service.file_safe_io import FileChangeResult
                changes_results = []
                for f in files_list:
                    file_path = f.get("file_path", "")
                    content = f.get("content", "")
                    if file_path and content:
                        read_result = executor.read_file(file_path)
                        change_result = executor.apply_file_change(
                            relative_path=file_path,
                            new_content=content,
                            read_token=read_result.read_token,
                            create_if_missing=False
                        )
                        changes_results.append(change_result)

                # 构造批量变更结果
                success_count = sum(1 for c in changes_results if c.success)
                failed_count = len(changes_results) - success_count
                class SimpleBatchResult:
                    def __init__(self, success, changes, success_count, failed_count):
                        self.success = success
                        self.changes = changes
                        self.success_count = success_count
                        self.failed_count = failed_count
                        self.errors = [c.error for c in changes if not c.success]
                        self.summary = f"成功: {success_count}, 失败: {failed_count}"

                result = SimpleBatchResult(
                    success=failed_count == 0,
                    changes=changes_results,
                    success_count=success_count,
                    failed_count=failed_count
                )
                info(f"变更结果: success={result.success}, summary={result.summary}")

                if not result.success:
                    error(f"变更失败: {result.errors}")
                    for change in result.changes:
                        if not change.success:
                            error(f"  - {change.file_path}: {change.error}")
                else:
                    info("代码变更已应用", files=[f.get("file_path") for f in files_list])
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

        # 9. 生成 diff
        try:
            diff = generate_diff(content, new_content, str(file_path))
            info(f"Diff 生成完成: {len(diff)} 字符")
        except Exception as e:
            error(f"生成 diff 失败: {e}", exc_info=True)
            diff = ""

        # 10. 构建响应（使用字典，不是 Pydantic 模型）
        try:
            # 获取 search_block 和 replace_block 用于前端搜索替换
            file_change = files[0] if files else {}
            response_data = {
                "summary": output.get("summary", ""),
                "files_changed": [f["file_path"] for f in files],
                "new_content": new_content,
                "original_content": content,
                "diff": diff,
                "search_block": file_change.get("search_block", ""),
                "replace_block": file_change.get("replace_block", ""),
                "change_type": file_change.get("change_type", "modify"),
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


# ============================================
# 轻量 MR 创建接口
# ============================================

class LightweightMRRequest(BaseModel):
    """轻量 MR 创建请求"""
    file_path: str = Field(..., description="修改的文件路径")
    instruction: str = Field(..., description="用户的修改指令")
    summary: str = Field(default="", description="变更摘要（由AI生成）")


class BatchMRFileInfo(BaseModel):
    """批量MR中的文件信息"""
    file_path: str = Field(..., description="文件路径")
    summary: str = Field(default="", description="该文件的变更摘要")


class BatchLightweightMRRequest(BaseModel):
    """批量轻量 MR 创建请求"""
    files: List[BatchMRFileInfo] = Field(..., description="修改的文件列表", min_length=1)
    instruction: str = Field(..., description="用户的修改指令")
    summary: str = Field(default="", description="整体变更摘要（由AI生成）")


@router.post(
    "/code/create-mr",
    response_model=ResponseModel,
    summary="创建轻量 MR",
    description="圈选确认后自动创建 MR，包含分支创建、提交、推送和 PR 创建"
)
async def create_lightweight_mr(
    request: Request,
    data: LightweightMRRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    轻量 MR 创建 - 圈选确认后自动触发
    
    【关键改进】使用独立临时工作区，避免本地未提交变更影响
    """
    request_id = getattr(request.state, "request_id", "")
    mr_workspace = None  # 独立 MR 工作区

    try:
        from app.service.git_provider import GitProviderService
        from app.service.platform_provider import GitHubProviderService
        from app.core.config import settings
        import asyncio

        # 【关键改进】创建独立临时工作区，隔离 Git 操作环境
        project_path = Path(settings.TARGET_PROJECT_PATH)
        mr_workspace = Path(tempfile.mkdtemp(prefix=f"omniflow-mr-{request_id[:8]}-"))
        info(f"创建独立 MR 工作区: {mr_workspace}", request_id=request_id)

        # 1. 初始化 Git（工作区为空，无冲突）
        git = GitProviderService(str(mr_workspace))
        remote_url = f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}.git"
        git.init_repo(remote_url=remote_url)
        info(f"Git 仓库已初始化", request_id=request_id)

        # 2. 复制项目文件到工作区（排除 .git 等）
        # 使用 dirs_exist_ok=True 允许目标目录已存在（tempfile.mkdtemp 创建的）
        shutil.copytree(
            project_path,
            mr_workspace,
            ignore=shutil.ignore_patterns(
                '.git', '__pycache__', '*.pyc', '.pytest_cache',
                'node_modules', '.venv', 'venv', '.env'
            ),
            dirs_exist_ok=True
        )
        info(f"项目代码已复制到工作区", request_id=request_id)

        # 3. 处理文件路径
        # file_path 可能是相对路径（如 src/...），需要转换为绝对路径或相对于工作区的路径
        file_path_in_workspace = data.file_path

        # 检查文件是否存在于工作区（尝试多种路径组合）
        possible_paths = [
            mr_workspace / file_path_in_workspace,  # 直接路径
            mr_workspace / "frontend" / file_path_in_workspace,  # frontend/ 前缀
            mr_workspace / "backend" / file_path_in_workspace,   # backend/ 前缀
        ]

        file_found = False
        for test_path in possible_paths:
            if test_path.exists():
                # 计算相对于工作区的路径
                file_path_in_workspace = str(test_path.relative_to(mr_workspace)).replace("\\", "/")
                info(f"文件路径调整: {data.file_path} -> {file_path_in_workspace}", request_id=request_id)
                file_found = True
                break

        if not file_found:
            # 尝试在工作区中搜索文件（修复变量名遮蔽：files -> dir_files）
            file_name = Path(data.file_path).name
            for root, dirs, dir_files in os.walk(mr_workspace):
                for filename in dir_files:
                    if filename == file_name:
                        found_path = Path(root) / filename
                        file_path_in_workspace = str(found_path.relative_to(mr_workspace)).replace("\\", "/")
                        info(f"通过搜索找到文件: {data.file_path} -> {file_path_in_workspace}", request_id=request_id)
                        file_found = True
                        break
                if file_found:
                    break

        if not file_found:
            error(f"文件不存在于工作区: {data.file_path}", request_id=request_id)
            raise FileNotFoundError(f"文件不存在: {data.file_path}")

        # 4. 创建 orphan 分支并设置历史（不覆盖工作区文件）
        branch_name = f"feat/injector-{request_id[:8]}"
        # 创建 orphan 分支（无父提交），然后 reset 到 origin/main 设置历史
        git._run_git_command(["checkout", "--orphan", branch_name])
        git._run_git_command(["reset", "--mixed", "origin/main"])
        info(f"创建分支: {branch_name}", request_id=request_id)

        # 6. 添加变更并提交
        await asyncio.to_thread(git.add_files, [file_path_in_workspace])

        # 提交信息包含用户指令
        commit_msg = f"injector: {data.instruction[:80]}"
        await asyncio.to_thread(git.commit_changes, commit_msg)
        info(f"提交变更: {commit_msg}", request_id=request_id)

        # 3. 推送分支
        await asyncio.to_thread(git.push_branch, branch_name)
        info(f"推送分支: {branch_name}", request_id=request_id)

        # 4. 生成 PR 描述
        pr_description = f"""## 来自圈选修改
{data.summary or data.instruction}

修改文件：`{data.file_path}`
"""

        # 5. 创建 PR
        async with GitHubProviderService() as gh:
            pr_result = await gh.create_pull_request(
                head_branch=branch_name,
                title=f"OmniFlowAI: {data.instruction[:50]}",
                body=pr_description,
                base_branch="main"
            )

        if pr_result.success:
            info(f"PR 创建成功: {pr_result.pr_url}", request_id=request_id)
            return success_response(
                data={
                    "pr_url": pr_result.pr_url,
                    "pr_number": pr_result.pr_number,
                    "branch": branch_name
                },
                request_id=request_id
            )
        else:
            error(f"PR 创建失败: {pr_result.error}", request_id=request_id)
            return error_response(
                error=f"PR创建失败: {pr_result.error}",
                request_id=request_id
            )

    except Exception as e:
        error(f"创建 MR 失败: {e}", exc_info=True, request_id=request_id)
        return error_response(
            error=f"创建 MR 失败: {str(e)}",
            request_id=request_id
        )

    finally:
        # 【关键改进】清理独立 MR 工作区
        if mr_workspace and mr_workspace.exists():
            try:
                shutil.rmtree(mr_workspace, ignore_errors=True)
                info(f"清理 MR 工作区: {mr_workspace}", request_id=request_id)
            except Exception as cleanup_error:
                error(f"清理 MR 工作区失败: {cleanup_error}", request_id=request_id)


@router.post(
    "/code/create-mr-batch",
    response_model=ResponseModel,
    summary="创建批量轻量 MR",
    description="圈选确认后自动创建 MR（支持多文件），包含分支创建、提交、推送和 PR 创建"
)
async def create_batch_lightweight_mr(
    request: Request,
    data: BatchLightweightMRRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    批量轻量 MR 创建 - 圈选确认后自动触发（支持多文件）

    【关键改进】使用独立临时工作区，避免本地未提交变更影响
    """
    request_id = getattr(request.state, "request_id", "")
    mr_workspace = None  # 独立 MR 工作区

    try:
        from app.service.git_provider import GitProviderService
        from app.service.platform_provider import GitHubProviderService
        from app.core.config import settings
        import asyncio

        # 【关键改进】创建独立临时工作区，隔离 Git 操作环境
        project_path = Path(settings.TARGET_PROJECT_PATH)
        mr_workspace = Path(tempfile.mkdtemp(prefix=f"omniflow-mr-batch-{request_id[:8]}-"))
        info(f"创建独立 MR 工作区(批量): {mr_workspace}", request_id=request_id)

        # 1. 初始化 Git（工作区为空，无冲突）
        git = GitProviderService(str(mr_workspace))
        remote_url = f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}.git"
        git.init_repo(remote_url=remote_url)
        info(f"Git 仓库已初始化", request_id=request_id)

        # 2. 复制项目文件到工作区（排除 .git 等）
        shutil.copytree(
            project_path,
            mr_workspace,
            ignore=shutil.ignore_patterns(
                '.git', '__pycache__', '*.pyc', '.pytest_cache',
                'node_modules', '.venv', 'venv', '.env'
            ),
            dirs_exist_ok=True
        )
        info(f"项目代码已复制到工作区", request_id=request_id)

        # 3. 处理多个文件路径
        file_paths_in_workspace: List[str] = []
        file_path_mapping: Dict[str, str] = {}  # 原始路径 -> 工作区路径

        for file_info in data.files:
            original_path = file_info.file_path
            file_path_in_workspace = original_path
            file_found = False

            # 检查文件是否存在于工作区（尝试多种路径组合）
            possible_paths = [
                mr_workspace / file_path_in_workspace,  # 直接路径
                mr_workspace / "frontend" / file_path_in_workspace,  # frontend/ 前缀
                mr_workspace / "backend" / file_path_in_workspace,   # backend/ 前缀
            ]

            for test_path in possible_paths:
                if test_path.exists():
                    # 计算相对于工作区的路径
                    file_path_in_workspace = str(test_path.relative_to(mr_workspace)).replace("\\", "/")
                    info(f"文件路径调整: {original_path} -> {file_path_in_workspace}", request_id=request_id)
                    file_found = True
                    break

            if not file_found:
                # 尝试在工作区中搜索文件（修复变量名遮蔽：files -> dir_files）
                file_name = Path(original_path).name
                for root, dirs, dir_files in os.walk(mr_workspace):
                    for filename in dir_files:
                        if filename == file_name:
                            found_path = Path(root) / filename
                            file_path_in_workspace = str(found_path.relative_to(mr_workspace)).replace("\\", "/")
                            info(f"通过搜索找到文件: {original_path} -> {file_path_in_workspace}", request_id=request_id)
                            file_found = True
                            break
                    if file_found:
                        break

            if not file_found:
                error(f"文件不存在于工作区: {original_path}", request_id=request_id)
                raise FileNotFoundError(f"文件不存在: {original_path}")

            file_paths_in_workspace.append(file_path_in_workspace)
            file_path_mapping[original_path] = file_path_in_workspace

        info(f"共找到 {len(file_paths_in_workspace)} 个文件", request_id=request_id)

        # 4. 创建 orphan 分支并设置历史（不覆盖工作区文件）
        branch_name = f"feat/injector-batch-{request_id[:8]}"
        # 创建 orphan 分支（无父提交），然后 reset 到 origin/main 设置历史
        git._run_git_command(["checkout", "--orphan", branch_name])
        git._run_git_command(["reset", "--mixed", "origin/main"])
        info(f"创建分支: {branch_name}", request_id=request_id)

        # 6. 添加所有变更文件并提交
        await asyncio.to_thread(git.add_files, file_paths_in_workspace)

        # 提交信息包含用户指令
        commit_msg = f"injector(batch): {data.instruction[:80]}"
        await asyncio.to_thread(git.commit_changes, commit_msg)
        info(f"提交变更: {commit_msg}", request_id=request_id)

        # 7. 推送分支
        await asyncio.to_thread(git.push_branch, branch_name)
        info(f"推送分支: {branch_name}", request_id=request_id)

        # 8. 生成 PR 描述（包含所有文件）
        files_list_str = "\n".join([f"- `{f}`" for f in file_path_mapping.keys()])
        pr_description = f"""## 来自圈选修改（批量）
{data.summary or data.instruction}

### 修改文件
{files_list_str}
"""

        # 9. 创建 PR
        async with GitHubProviderService() as gh:
            pr_result = await gh.create_pull_request(
                head_branch=branch_name,
                title=f"OmniFlowAI(batch): {data.instruction[:50]}",
                body=pr_description,
                base_branch="main"
            )

        if pr_result.success:
            info(f"PR 创建成功: {pr_result.pr_url}", request_id=request_id)
            return success_response(
                data={
                    "pr_url": pr_result.pr_url,
                    "pr_number": pr_result.pr_number,
                    "branch": branch_name,
                    "files_count": len(file_paths_in_workspace),
                    "files": list(file_path_mapping.keys())
                },
                request_id=request_id
            )
        else:
            error(f"PR 创建失败: {pr_result.error}", request_id=request_id)
            return error_response(
                error=f"PR创建失败: {pr_result.error}",
                request_id=request_id
            )

    except Exception as e:
        error(f"创建批量 MR 失败: {e}", exc_info=True, request_id=request_id)
        return error_response(
            error=f"创建批量 MR 失败: {str(e)}",
            request_id=request_id
        )

    finally:
        # 【关键改进】清理独立 MR 工作区
        if mr_workspace and mr_workspace.exists():
            try:
                shutil.rmtree(mr_workspace, ignore_errors=True)
                info(f"清理 MR 工作区: {mr_workspace}", request_id=request_id)
            except Exception as cleanup_error:
                error(f"清理 MR 工作区失败: {cleanup_error}", request_id=request_id)
