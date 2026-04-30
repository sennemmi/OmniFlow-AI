"""
文件写入 Agent
纯 Python 实现，不走 LLM

职责：
1. 接收 CoderOutput 的 JSON（包含 search_block/replace_block）
2. 执行实际的文件写入操作
3. 验证写入结果

【设计原则】
- 不调用 LLM，纯 Python 逻辑
- 使用 search_replace_engine 进行补丁应用
- 使用 code_validator 进行语法和结构验证
"""

import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

from app.service.code_executor import CodeExecutorService
from app.service.search_replace_engine import search_replace_engine
from app.core.code_validator import code_validator
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class FileWriterAgent:
    """
    文件写入 Agent

    纯 Python 实现，负责将 CoderAgent 生成的代码变更写入文件系统
    """

    def __init__(self, project_path: str = "/workspace/backend"):
        self.project_path = project_path
        self.code_executor = CodeExecutorService(project_path)

    async def write_files(
        self,
        files: List[Dict[str, Any]],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        将代码变更写入文件

        Args:
            files: 文件变更列表，每个变更包含 file_path, change_type, search_block, replace_block 等
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 写入结果，包含成功/失败状态和详细信息
        """
        logger.info(f"[FileWriterAgent] 开始写入 {len(files)} 个文件", extra={
            "pipeline_id": pipeline_id,
            "files_count": len(files)
        })

        if pipeline_id:
            await push_log(pipeline_id, "info", f"FileWriterAgent 开始写入 {len(files)} 个文件...", stage="CODING")

        written_files = []
        failed_files = []

        for file_change in files:
            file_path = file_change.get("file_path", "")
            change_type = file_change.get("change_type", "modify")

            try:
                result = await self._write_single_file(
                    file_change=file_change,
                    pipeline_id=pipeline_id
                )

                if result.get("success"):
                    written_files.append({
                        "file_path": file_path,
                        "change_type": change_type,
                        "message": result.get("message", "写入成功")
                    })
                else:
                    failed_files.append({
                        "file_path": file_path,
                        "change_type": change_type,
                        "error": result.get("error", "未知错误")
                    })

            except Exception as e:
                logger.error(f"[FileWriterAgent] 写入文件 {file_path} 失败: {e}")
                failed_files.append({
                    "file_path": file_path,
                    "change_type": change_type,
                    "error": str(e)
                })

        # 构建返回结果
        success = len(failed_files) == 0

        result = {
            "success": success,
            "written_files": written_files,
            "failed_files": failed_files,
            "total_count": len(files),
            "success_count": len(written_files),
            "failed_count": len(failed_files)
        }

        if pipeline_id:
            if success:
                await push_log(pipeline_id, "info", f"文件写入完成：{len(written_files)} 个成功", stage="CODING")
            else:
                await push_log(pipeline_id, "warning", f"文件写入完成：{len(written_files)} 个成功，{len(failed_files)} 个失败", stage="CODING")

        return result

    async def _write_single_file(
        self,
        file_change: Dict[str, Any],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        写入单个文件

        Args:
            file_change: 单个文件变更
            pipeline_id: Pipeline ID

        Returns:
            Dict: 写入结果
        """
        file_path = file_change.get("file_path", "")
        change_type = file_change.get("change_type", "modify")

        # 清理路径
        clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
        full_path = Path(self.project_path) / clean_path

        logger.info(f"[FileWriterAgent] 处理文件: {file_path} (type={change_type})")

        # 处理新增文件
        if change_type == "add":
            return await self._handle_add_file(
                file_path=file_path,
                clean_path=clean_path,
                full_path=full_path,
                content=file_change.get("content", ""),
                pipeline_id=pipeline_id
            )

        # 处理修改文件
        if change_type in ["modify", "update"]:
            return await self._handle_modify_file(
                file_path=file_path,
                clean_path=clean_path,
                full_path=full_path,
                file_change=file_change,
                pipeline_id=pipeline_id
            )

        # 处理删除文件
        if change_type == "delete":
            return await self._handle_delete_file(
                file_path=file_path,
                full_path=full_path,
                pipeline_id=pipeline_id
            )

        return {
            "success": False,
            "error": f"未知的变更类型: {change_type}"
        }

    async def _handle_add_file(
        self,
        file_path: str,
        clean_path: str,
        full_path: Path,
        content: str,
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """处理新增文件"""
        try:
            # 验证语法
            if file_path.endswith(".py"):
                syntax_error = code_validator.pre_flight_check(content)
                if syntax_error:
                    return {
                        "success": False,
                        "error": f"语法错误: {syntax_error}"
                    }

            # 创建目录
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            full_path.write_text(content, encoding="utf-8")

            logger.info(f"[FileWriterAgent] 新增文件成功: {file_path}")

            if pipeline_id:
                await push_log(pipeline_id, "info", f"✨ 新增文件: {file_path}", stage="CODING")

            return {
                "success": True,
                "message": f"新增文件成功: {file_path}"
            }

        except Exception as e:
            logger.error(f"[FileWriterAgent] 新增文件失败: {file_path}: {e}")
            return {
                "success": False,
                "error": f"新增文件失败: {str(e)}"
            }

    async def _handle_modify_file(
        self,
        file_path: str,
        clean_path: str,
        full_path: Path,
        file_change: Dict[str, Any],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """处理修改文件"""
        try:
            # 读取原始文件内容
            read_result = self.code_executor.read_file(clean_path)

            if not read_result.exists:
                return {
                    "success": False,
                    "error": f"文件不存在: {file_path}"
                }

            original_content = read_result.content
            search_block = file_change.get("search_block", "")
            replace_block = file_change.get("replace_block", "")
            fallback_start = file_change.get("fallback_start_line")
            fallback_end = file_change.get("fallback_end_line")

            # 使用 search_replace_engine 应用变更
            new_content = search_replace_engine.apply_search_replace(
                original=original_content,
                search_block=search_block,
                replace_block=replace_block,
                fallback_start=fallback_start,
                fallback_end=fallback_end
            )

            if new_content is None:
                return {
                    "success": False,
                    "error": "搜索替换失败：search_block 与文件内容不匹配"
                }

            # 验证语法
            if file_path.endswith(".py"):
                syntax_error = code_validator.pre_flight_check(new_content)
                if syntax_error:
                    return {
                        "success": False,
                        "error": f"语法错误: {syntax_error}"
                    }

                structure_error = code_validator.validate_code_structure(new_content, file_path)
                if structure_error:
                    return {
                        "success": False,
                        "error": f"结构错误: {structure_error}"
                    }

            # 写入文件
            full_path.write_text(new_content, encoding="utf-8")

            # 计算变更行数
            old_lines = search_block.count("\n") + 1 if search_block else 0
            new_lines = replace_block.count("\n") + 1 if replace_block else 0

            logger.info(f"[FileWriterAgent] 修改文件成功: {file_path} ({old_lines} -> {new_lines} 行)")

            if pipeline_id:
                await push_log(pipeline_id, "info", f"✏️ 修改文件: {file_path}", stage="CODING")

            return {
                "success": True,
                "message": f"修改文件成功: {file_path} ({old_lines} -> {new_lines} 行)"
            }

        except Exception as e:
            logger.error(f"[FileWriterAgent] 修改文件失败: {file_path}: {e}")
            return {
                "success": False,
                "error": f"修改文件失败: {str(e)}"
            }

    async def _handle_delete_file(
        self,
        file_path: str,
        full_path: Path,
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """处理删除文件"""
        try:
            if not full_path.exists():
                return {
                    "success": True,
                    "message": f"文件不存在，无需删除: {file_path}"
                }

            full_path.unlink()

            logger.info(f"[FileWriterAgent] 删除文件成功: {file_path}")

            if pipeline_id:
                await push_log(pipeline_id, "info", f"🗑️ 删除文件: {file_path}", stage="CODING")

            return {
                "success": True,
                "message": f"删除文件成功: {file_path}"
            }

        except Exception as e:
            logger.error(f"[FileWriterAgent] 删除文件失败: {file_path}: {e}")
            return {
                "success": False,
                "error": f"删除文件失败: {str(e)}"
            }


# 便捷函数
def get_file_writer(project_path: str = "/workspace/backend") -> FileWriterAgent:
    """
    获取 FileWriterAgent 实例

    Args:
        project_path: 项目路径

    Returns:
        FileWriterAgent: 文件写入 Agent 实例
    """
    return FileWriterAgent(project_path)
