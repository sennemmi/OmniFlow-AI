"""
文件写入服务
纯 Python 执行文件写入，不调用 LLM

职责：
1. 接收 CoderOutput 的 JSON（包含 search_block/replace_block）
2. 逐文件应用代码变更
3. 返回每个文件的成功/失败状态

【设计原则】
- 不调用 LLM，纯 Python 逻辑
- 使用 CodeExecutorService 读取文件
- 使用 AST 进行语法检查
"""

import ast
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

from app.service.code_executor import CodeExecutorService
from app.service.search_replace_engine import search_replace_engine

logger = logging.getLogger(__name__)


class FileWriterService:
    """
    纯 Python 执行文件写入，不调用 LLM。
    接收 CoderOutput 的 JSON，逐文件应用 search_block/replace_block。
    """

    def __init__(self, project_path: str):
        self.project_path = project_path
        self.code_executor = CodeExecutorService(project_path)

    def apply_changes(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量应用代码变更，返回每个文件的成功/失败状态。

        Args:
            files: 文件变更列表，每个变更包含 file_path, change_type, search_block, replace_block 等

        Returns:
            List[Dict]: 每个文件的执行结果
        """
        results = []
        for file_change in files:
            file_path = file_change.get("file_path", "")
            change_type = file_change.get("change_type", "modify")

            try:
                if change_type == "add":
                    result = self._write_new_file(file_path, file_change.get("content", ""))
                elif change_type == "delete":
                    result = self._delete_file(file_path)
                else:
                    result = self._apply_search_replace(
                        file_path,
                        file_change.get("search_block", ""),
                        file_change.get("replace_block", ""),
                        file_change.get("fallback_start_line"),
                        file_change.get("fallback_end_line")
                    )
                results.append(result)
            except Exception as e:
                logger.error(f"[FileWriterService] 处理文件 {file_path} 时异常: {e}")
                results.append({
                    "file": file_path,
                    "success": False,
                    "error": f"处理异常: {str(e)}"
                })

        return results

    def _write_new_file(self, file_path: str, content: str) -> Dict[str, Any]:
        """
        写入新文件

        Args:
            file_path: 文件路径（相对项目根目录）
            content: 文件内容

        Returns:
            Dict: 执行结果
        """
        try:
            # 清理路径
            clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
            full_path = Path(self.project_path) / clean_path

            # AST 语法检查（仅 Python 文件）
            if file_path.endswith(".py"):
                try:
                    ast.parse(content)
                except SyntaxError as e:
                    return {
                        "file": file_path,
                        "success": False,
                        "error": f"语法错误: {e}"
                    }

            # 创建目录
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            full_path.write_text(content, encoding="utf-8")

            logger.info(f"[FileWriterService] 新增文件成功: {file_path}")
            return {"file": file_path, "success": True}

        except Exception as e:
            logger.error(f"[FileWriterService] 新增文件失败: {file_path}: {e}")
            return {
                "file": file_path,
                "success": False,
                "error": f"写入失败: {str(e)}"
            }

    def _apply_search_replace(
        self,
        file_path: str,
        search_block: str,
        replace_block: str,
        fallback_start_line: Optional[int] = None,
        fallback_end_line: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        应用搜索替换变更（使用四层匹配逻辑）

        Args:
            file_path: 文件路径（相对项目根目录）
            search_block: 要搜索的原始代码块
            replace_block: 替换后的新代码块
            fallback_start_line: 备用起始行号（1-based）
            fallback_end_line: 备用结束行号（1-based，包含）

        Returns:
            Dict: 执行结果
        """
        try:
            # 清理路径
            clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")

            # 读取文件
            read_result = self.code_executor.read_file(clean_path)
            if not read_result.exists:
                return {
                    "file": file_path,
                    "success": False,
                    "error": "文件不存在"
                }

            content = read_result.content

            # 【关键】使用 search_replace_engine 的四层匹配逻辑
            new_content = search_replace_engine.apply_search_replace(
                original=content,
                search_block=search_block,
                replace_block=replace_block,
                fallback_start=fallback_start_line,
                fallback_end=fallback_end_line
            )

            if new_content is None:
                # 【调试】记录详细的匹配失败信息
                logger.error(f"[FileWriterService] search_block 不匹配: {file_path}")
                logger.error(f"[FileWriterService] 文件内容长度: {len(content)} 字符")
                logger.error(f"[FileWriterService] search_block 长度: {len(search_block)} 字符")
                logger.error(f"[FileWriterService] search_block 前100字符: {repr(search_block[:100])}")
                logger.error(f"[FileWriterService] 文件内容前200字符: {repr(content[:200])}")
                
                # 尝试查找相似内容
                if search_block:
                    first_line = search_block.split('\n')[0][:50]
                    if first_line in content:
                        logger.error(f"[FileWriterService] 找到第一行: {repr(first_line)}")
                    else:
                        logger.error(f"[FileWriterService] 第一行也不匹配: {repr(first_line)}")
                
                return {
                    "file": file_path,
                    "success": False,
                    "error": f"search_block 与文件内容不匹配 (文件{len(content)}字符, search_block{len(search_block)}字符)"
                }

            # AST 语法检查（仅 Python 文件）
            if file_path.endswith(".py"):
                try:
                    ast.parse(new_content)
                except SyntaxError as e:
                    return {
                        "file": file_path,
                        "success": False,
                        "error": f"语法错误: {e}"
                    }

            # 写入文件
            full_path = Path(self.project_path) / clean_path
            full_path.write_text(new_content, encoding="utf-8")

            logger.info(f"[FileWriterService] 修改文件成功: {file_path}")
            return {"file": file_path, "success": True}

        except Exception as e:
            logger.error(f"[FileWriterService] 修改文件失败: {file_path}: {e}")
            return {
                "file": file_path,
                "success": False,
                "error": f"修改失败: {str(e)}"
            }

    def _delete_file(self, file_path: str) -> Dict[str, Any]:
        """
        删除文件

        Args:
            file_path: 文件路径（相对项目根目录）

        Returns:
            Dict: 执行结果
        """
        try:
            # 清理路径
            clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
            full_path = Path(self.project_path) / clean_path

            if not full_path.exists():
                return {
                    "file": file_path,
                    "success": True,
                    "message": "文件不存在，无需删除"
                }

            full_path.unlink()
            logger.info(f"[FileWriterService] 删除文件成功: {file_path}")
            return {"file": file_path, "success": True}

        except Exception as e:
            logger.error(f"[FileWriterService] 删除文件失败: {file_path}: {e}")
            return {
                "file": file_path,
                "success": False,
                "error": f"删除失败: {str(e)}"
            }


# 便捷函数
def get_file_writer_service(project_path: str) -> FileWriterService:
    """
    获取 FileWriterService 实例

    Args:
        project_path: 项目路径

    Returns:
        FileWriterService: 文件写入服务实例
    """
    return FileWriterService(project_path)
