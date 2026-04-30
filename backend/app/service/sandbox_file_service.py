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
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.service.sandbox_manager import sandbox_manager

logger = logging.getLogger(__name__)


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
    
    async def read_file(self, file_path: str) -> SandboxFileResult:
        """
        在 Sandbox 中读取文件内容
        
        Args:
            file_path: 文件路径（相对项目根目录）
            
        Returns:
            SandboxFileResult: 文件读取结果
        """
        try:
            # 清理路径
            # 【修复】backend 目录被挂载到 /workspace，所以路径应该是 /workspace/...
            clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
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
    
    async def write_file(self, file_path: str, content: str) -> Dict[str, Any]:
        """
        在 Sandbox 中写入文件内容
        
        Args:
            file_path: 文件路径（相对项目根目录）
            content: 文件内容
            
        Returns:
            Dict: 写入结果
        """
        try:
            # 清理路径
            # 【修复】backend 目录被挂载到 /workspace，所以路径应该是 /workspace/...
            clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
            full_path = f"/workspace/{clean_path}"
            
            # 创建目录
            dir_path = "/".join(full_path.split("/")[:-1])
            mkdir_result = await sandbox_manager.exec(
                self.pipeline_id,
                f"mkdir -p {dir_path}",
                timeout=10
            )
            
            if mkdir_result.exit_code != 0:
                logger.error(f"[SandboxFileService] 创建目录失败: {dir_path}")
                return {"success": False, "error": f"创建目录失败: {mkdir_result.stderr}"}
            
            # 使用 base64 编码内容，避免特殊字符问题
            encoded_content = base64.b64encode(content.encode()).decode()
            
            # 在 Sandbox 中写入文件
            write_cmd = f"echo '{encoded_content}' | base64 -d > {full_path}"
            exec_result = await sandbox_manager.exec(
                self.pipeline_id,
                write_cmd,
                timeout=10
            )
            
            if exec_result.exit_code == 0:
                logger.info(f"[SandboxFileService] 写入成功: {file_path} ({len(content)} 字符)")
                return {"success": True, "file": file_path}
            else:
                error_msg = exec_result.stderr or "写入失败"
                logger.error(f"[SandboxFileService] 写入失败: {file_path} - {error_msg}")
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            logger.error(f"[SandboxFileService] 写入异常: {file_path} - {e}")
            return {"success": False, "error": str(e)}
    
    async def file_exists(self, file_path: str) -> bool:
        """
        检查文件是否在 Sandbox 中存在
        
        Args:
            file_path: 文件路径（相对项目根目录）
            
        Returns:
            bool: 是否存在
        """
        try:
            # 【修复】backend 目录被挂载到 /workspace，所以路径应该是 /workspace/...
            clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
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
            dir_path: 目录路径（相对项目根目录）
            
        Returns:
            Dict: 目录内容列表
        """
        try:
            # 【修复】backend 目录被挂载到 /workspace，所以路径应该是 /workspace/...
            clean_path = dir_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
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
