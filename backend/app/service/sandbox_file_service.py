"""
Sandbox 文件服务
提供在 Docker Sandbox 中读写文件的接口

职责：
1. 在 Sandbox 容器中读取文件内容
2. 在 Sandbox 容器中写入文件内容
3. 提供与 CodeExecutorService 类似的接口，但操作的是 Sandbox 中的文件

优势：
- 所有文件操作都在 Sandbox 中完成，无需本地↔Sandbox 同步
- 节省本地机器开销
- 环境一致性更好
"""

import base64
import json
import logging
import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.service.sandbox_manager import sandbox_manager

logger = logging.getLogger(__name__)

# 【改进6】模块级文件锁，防止并发写入同一文件造成内容不一致
_file_locks: Dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()


@dataclass
class SandboxFileResult:
    """Sandbox 文件操作结果"""
    exists: bool
    content: Optional[str] = None
    error: Optional[str] = None
    read_token: Optional[str] = None


class SandboxFileService:
    """
    Sandbox 文件服务
    
    通过 Docker exec 在 Sandbox 容器中执行文件操作，
    提供与本地 CodeExecutorService 类似的接口。
    """
    
    def __init__(self, pipeline_id: int):
        self.pipeline_id = pipeline_id
    
    def _sanitize_path(self, file_path: str) -> str:
        """
        标准化路径：统一为正斜杠，确保路径指向 /workspace/backend/

        处理逻辑：
        - 如果路径以 backend/ 开头（如 backend/tests/ai_generated/test.py），保留 backend/ 前缀
        - 如果路径不以 backend/ 开头（如 app/api/v1/health.py），添加 backend/ 前缀
        - 最终路径格式：backend/xxx/xxx.py，映射到 /workspace/backend/xxx/xxx.py
        """
        clean = file_path.replace("\\", "/").lstrip("/")

        # 如果路径不以 backend/ 开头，添加 backend/ 前缀
        # 因为 sandbox 中 /workspace/backend/ 是代码根目录
        if not clean.startswith("backend/"):
            clean = f"backend/{clean}"

        return clean

    async def read_file(self, file_path: str) -> SandboxFileResult:
        """
        在 Sandbox 中读取文件内容
        
        Args:
            file_path: 文件路径（相对 backend 目录，如 "app/agents/tools.py"）
            
        Returns:
            SandboxFileResult: 文件读取结果
        """
        try:
            clean_path = self._sanitize_path(file_path)
            full_path = f"/workspace/{clean_path}"
            
            # 在 Sandbox 中执行 cat 命令读取文件
            exec_result = await sandbox_manager.exec(
                self.pipeline_id,
                f"cat {full_path}",
                timeout=10
            )
            
            if exec_result.exit_code == 0:
                content = exec_result.stdout
                # 生成 read_token（基于内容哈希）
                import hashlib
                read_token = hashlib.sha256(content.encode()).hexdigest()[:16]
                
                logger.info(f"[SandboxFileService] 读取成功: {file_path} ({len(content)} 字符)")
                return SandboxFileResult(
                    exists=True,
                    content=content,
                    read_token=read_token
                )
            else:
                error_msg = exec_result.stderr or "文件不存在或读取失败"
                logger.warning(f"[SandboxFileService] 读取失败: {file_path} - {error_msg}")
                return SandboxFileResult(
                    exists=False,
                    error=error_msg
                )
                
        except Exception as e:
            logger.error(f"[SandboxFileService] 读取异常: {file_path} - {e}")
            return SandboxFileResult(
                exists=False,
                error=str(e)
            )
    
    async def _get_file_lock(self, file_path: str) -> asyncio.Lock:
        """获取文件级锁，用于并发安全"""
        normalized = self._sanitize_path(file_path)
        async with _locks_lock:
            if normalized not in _file_locks:
                _file_locks[normalized] = asyncio.Lock()
            return _file_locks[normalized]

    async def write_file(self, file_path: str, content: str) -> Dict[str, Any]:
        """
        在 Sandbox 中写入文件内容
        
        Args:
            file_path: 文件路径（相对项目根目录或 backend 目录）
            content: 文件内容
            
        Returns:
            Dict: 写入结果
        """
        import traceback
        
        # 【日志】记录调用栈，追踪是谁调用了 write_file
        stack = traceback.extract_stack()
        caller_info = []
        for frame in stack[-5:-1]:  # 获取最近 4 个调用帧（排除当前函数）
            caller_info.append(f"{frame.filename}:{frame.lineno} in {frame.name}")
        
        logger.info(f"[SandboxFileService] write_file 被调用: {file_path} ({len(content)} 字符)")
        logger.info(f"[SandboxFileService] 调用栈: {' -> '.join(caller_info)}")
        
        # 【改进6】获取文件级锁，防止并发写入
        lock = await self._get_file_lock(file_path)
        async with lock:
            try:
                clean_path = self._sanitize_path(file_path)
                full_path = f"/workspace/{clean_path}"
                
                logger.info(f"[SandboxFileService] 清理后路径: {clean_path}, 完整路径: {full_path}")
                
                # 创建目录
                dir_path = "/".join(full_path.split("/")[:-1])
                logger.info(f"[SandboxFileService] 创建目录: {dir_path}")
                
                mkdir_result = await sandbox_manager.exec(
                    self.pipeline_id,
                    f"mkdir -p {dir_path}",
                    timeout=10
                )
                
                if mkdir_result.exit_code != 0:
                    logger.error(f"[SandboxFileService] 创建目录失败: {dir_path} - {mkdir_result.stderr}")
                    return {"success": False, "error": f"创建目录失败: {mkdir_result.stderr}"}
                
                logger.info(f"[SandboxFileService] 目录创建成功: {dir_path}")
                
                # 【修复】使用分段写入方式，避免 Windows 命令行长度限制
                # 将内容分块，每块通过 echo 追加到文件
                chunk_size = 4000  # 每块约 4000 字符，避免命令行过长
                encoded_content = base64.b64encode(content.encode()).decode()
                
                logger.info(f"[SandboxFileService] 内容长度: {len(encoded_content)} 字符，将分块写入")
                
                # 先清空文件
                clear_result = await sandbox_manager.exec(
                    self.pipeline_id,
                    f"> {full_path}",
                    timeout=10
                )
                
                if clear_result.exit_code != 0:
                    logger.error(f"[SandboxFileService] 清空文件失败: {full_path}")
                    return {"success": False, "error": f"清空文件失败: {clear_result.stderr}"}
                
                # 分块写入
                chunks = [encoded_content[i:i+chunk_size] for i in range(0, len(encoded_content), chunk_size)]
                for i, chunk in enumerate(chunks):
                    write_cmd = f"echo -n '{chunk}' >> {full_path}"
                    exec_result = await sandbox_manager.exec(
                        self.pipeline_id,
                        write_cmd,
                        timeout=10
                    )
                    if exec_result.exit_code != 0:
                        logger.error(f"[SandboxFileService] 写入块 {i+1}/{len(chunks)} 失败: {exec_result.stderr}")
                        return {"success": False, "error": f"写入块 {i+1} 失败: {exec_result.stderr}"}
                
                # 解码 base64 内容
                decode_result = await sandbox_manager.exec(
                    self.pipeline_id,
                    f"base64 -d {full_path} > {full_path}.tmp && mv {full_path}.tmp {full_path}",
                    timeout=10
                )
                
                if decode_result.exit_code != 0:
                    logger.error(f"[SandboxFileService] 解码文件失败: {decode_result.stderr}")
                    return {"success": False, "error": f"解码文件失败: {decode_result.stderr}"}
                
                logger.info(f"[SandboxFileService] 分块写入完成: {len(chunks)} 块")
                logger.info(f"[SandboxFileService] 写入成功: {file_path} ({len(content)} 字符)")
                return {"success": True, "file": file_path}
            except Exception as e:
                logger.error(f"[SandboxFileService] 写入异常: {file_path} - {e}")
                logger.error(f"[SandboxFileService] 异常堆栈: {traceback.format_exc()}")
                return {"success": False, "error": str(e)}
    
    async def file_exists(self, file_path: str) -> bool:
        """
        检查文件是否在 Sandbox 中存在
        
        Args:
            file_path: 文件路径（相对项目根目录或 backend 目录）
            
        Returns:
            bool: 是否存在
        """
        try:
            clean_path = self._sanitize_path(file_path)
            full_path = f"/workspace/{clean_path}"
            
            exec_result = await sandbox_manager.exec(
                self.pipeline_id,
                f"test -f {full_path} && echo 'exists'",
                timeout=5
            )
            
            return exec_result.exit_code == 0 and "exists" in exec_result.stdout
            
        except Exception as e:
            logger.error(f"[SandboxFileService] 检查文件存在异常: {file_path} - {e}")
            return False
    
    async def list_directory(self, dir_path: str) -> Dict[str, Any]:
        """
        列出 Sandbox 中的目录内容
        
        Args:
            dir_path: 目录路径（相对 backend 目录）
            
        Returns:
            Dict: 目录内容列表
        """
        try:
            clean_path = self._sanitize_path(dir_path)
            full_path = f"/workspace/{clean_path}"
            
            exec_result = await sandbox_manager.exec(
                self.pipeline_id,
                f"ls -la {full_path}",
                timeout=5
            )
            
            if exec_result.exit_code == 0:
                return {"success": True, "listing": exec_result.stdout}
            else:
                return {"success": False, "error": exec_result.stderr}
                
        except Exception as e:
            logger.error(f"[SandboxFileService] 列出目录异常: {dir_path} - {e}")
            return {"success": False, "error": str(e)}


# 便捷函数
def get_sandbox_file_service(pipeline_id: int) -> SandboxFileService:
    """
    获取 SandboxFileService 实例
    
    Args:
        pipeline_id: Pipeline ID
        
    Returns:
        SandboxFileService: 服务实例
    """
    return SandboxFileService(pipeline_id)
