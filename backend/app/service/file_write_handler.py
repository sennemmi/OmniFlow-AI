"""
文件写入处理器

提供文件写入、回滚、read_token 强制校验的包装逻辑
"""

import asyncio
import logging
from typing import Dict, List, Any
from contextlib import asynccontextmanager

from app.service.code_executor import CodeExecutorService
from app.core.code_validator import code_validator
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)

# 【并发安全】Pipeline 级别的文件写入锁
_pipeline_file_locks: Dict[int, asyncio.Lock] = {}


def _get_pipeline_lock(pipeline_id: int) -> asyncio.Lock:
    """获取指定 Pipeline 的文件写入锁"""
    if pipeline_id not in _pipeline_file_locks:
        _pipeline_file_locks[pipeline_id] = asyncio.Lock()
    return _pipeline_file_locks[pipeline_id]


@asynccontextmanager
async def _pipeline_file_lock(pipeline_id: int):
    """Pipeline 文件写入锁的上下文管理器"""
    lock = _get_pipeline_lock(pipeline_id)
    async with lock:
        yield


class FileWriteHandler:
    """文件写入处理器 - 处理文件写入和回滚"""

    @staticmethod
    async def write_files_to_project(
        all_files: List[Dict[str, Any]],
        pipeline_id: int
    ) -> None:
        """
        写入文件到宿主机项目目录

        【核心】强制 Read Token 校验：每个文件变更必须携带有效的 read_token
        【并发安全】使用 Pipeline 级别的锁确保同一个 Pipeline 的文件写入是原子的
        """
        logger.info(f"[Pipeline {pipeline_id}] 开始写入 {len(all_files)} 个文件到项目目录")

        async with _pipeline_file_lock(pipeline_id):
            # 使用 CodeExecutorService 进行安全的文件写入
            code_executor = CodeExecutorService()

            # 记录已写入的文件变更，用于失败时回滚
            written_changes: List[Dict[str, Any]] = []

            try:
                for i, file_change in enumerate(all_files, 1):
                    file_path = file_change["file_path"]
                    content = file_change["content"]
                    change_type = file_change.get("change_type", "modify")
                    content_lines = len(content.splitlines())

                    logger.info(f"[Pipeline {pipeline_id}] [{i}/{len(all_files)}] 写入文件: {file_path} ({content_lines} 行)")

                    # 【写入前 AST 语法检查】
                    if file_path.endswith(".py"):
                        syntax_error = code_validator.pre_flight_check(content)
                        if syntax_error:
                            raise ValueError(f"[{file_path}] 语法错误: {syntax_error}")

                    # 【Read Token 强制校验】
                    read_token = file_change.get("read_token")
                    if not read_token:
                        raise PermissionError(
                            f"文件 {file_path} 缺少 read_token。"
                            f"必须先通过 read_file 读取文件才能写入。"
                        )

                    # 移除 backend/ 前缀，转换为相对路径
                    relative_path = file_path.replace("backend/", "").replace("backend\\", "")

                    # 使用 CodeExecutorService 进行安全的文件写入
                    # 它会自动验证 read_token 并执行原子写入
                    is_new_file = (change_type == "add")
                    result = code_executor.apply_file_change(
                        relative_path=relative_path,
                        new_content=content,
                        read_token=read_token,
                        create_if_missing=is_new_file
                    )

                    if not result.success:
                        # 如果是 token 失效，提供更友好的错误信息
                        if "read_token" in result.error.lower() or "token" in result.error.lower():
                            raise PermissionError(
                                f"文件 {file_path} 的 read_token 无效: {result.error}\n"
                                f"文件可能已被修改，请重新读取后再试。"
                            )
                        raise RuntimeError(f"写入文件失败 [{file_path}]: {result.error}")

                    written_changes.append(file_change)
                    logger.debug(f"[Pipeline {pipeline_id}] 文件已写入磁盘: {file_path}")

                    # 【确定性后置钩子】写入后验证代码关键约束
                    logger.debug(f"[Pipeline {pipeline_id}] 执行后置钩子检查: {file_path}")
                    hook_error = code_validator.post_write_hook(file_path, content)
                    if hook_error:
                        logger.error(f"[Pipeline {pipeline_id}] 后置钩子检查失败: {file_path} - {hook_error}")
                        # 如果检查失败，抛出错误（外层会处理回滚）
                        raise RuntimeError(f"确定性检查失败 [{file_path}]: {hook_error}")

                    logger.info(f"[Pipeline {pipeline_id}] 文件写入成功: {file_path}")
                    await push_log(
                        pipeline_id, "info",
                        f"文件已写入: {file_path}",
                        stage="CODING"
                    )

                logger.info(f"[Pipeline {pipeline_id}] 所有 {len(all_files)} 个文件写入成功")

            except Exception as e:
                # 【回滚】如果任何文件写入或检查失败，使用 CodeExecutorService 回滚
                logger.error(f"[Pipeline {pipeline_id}] 文件写入失败，回滚 {len(written_changes)} 个文件: {str(e)}", extra={
                    "pipeline_id": pipeline_id,
                    "error": str(e),
                    "written_files": [c.get("file_path") for c in written_changes]
                })

                # 使用 CodeExecutorService 回滚已写入的文件
                for change in written_changes:
                    file_path = change.get("file_path", "")
                    relative_path = file_path.replace("backend/", "").replace("backend\\", "")
                    original_content = change.get("original_content")

                    if original_content:
                        # 重新读取获取新 token，然后恢复原始内容
                        read_result = code_executor.read_file(relative_path)
                        if read_result.read_token:
                            restore_result = code_executor.apply_file_change(
                                relative_path=relative_path,
                                new_content=original_content,
                                read_token=read_result.read_token,
                                create_if_missing=False
                            )
                            if restore_result.success:
                                logger.info(f"[Pipeline {pipeline_id}] 回滚恢复: {file_path}")
                            else:
                                logger.error(f"[Pipeline {pipeline_id}] 回滚失败: {file_path} - {restore_result.error}")

                # 重新抛出原始错误
                raise

    @staticmethod
    async def rollback_files(
        written_changes: List[Dict[str, Any]],
        pipeline_id: int
    ) -> None:
        """
        回滚已写入的文件

        Args:
            written_changes: 已写入的文件变更列表
            pipeline_id: Pipeline ID
        """
        if not written_changes:
            return

        logger.info(f"[Pipeline {pipeline_id}] 回滚 {len(written_changes)} 个文件")
        code_executor = CodeExecutorService()

        for change in written_changes:
            file_path = change.get("file_path", "")
            relative_path = file_path.replace("backend/", "").replace("backend\\", "")
            original_content = change.get("original_content")

            if original_content:
                read_result = code_executor.read_file(relative_path)
                if read_result.read_token:
                    restore_result = code_executor.apply_file_change(
                        relative_path=relative_path,
                        new_content=original_content,
                        read_token=read_result.read_token,
                        create_if_missing=False
                    )
                    if restore_result.success:
                        logger.info(f"[Pipeline {pipeline_id}] 回滚恢复: {file_path}")
                    else:
                        logger.error(f"[Pipeline {pipeline_id}] 回滚失败: {file_path} - {restore_result.error}")


# 单例实例
file_write_handler = FileWriteHandler()
