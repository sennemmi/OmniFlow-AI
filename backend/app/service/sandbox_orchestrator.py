"""
Sandbox 编排器
在 Architect 阶段就拉起 Docker Sandbox，管理整个 Pipeline 的 Sandbox 生命周期

职责：
1. 在 Architect 阶段拉起 Docker Sandbox
2. 将项目代码复制到 Sandbox 中
3. 管理 Sandbox 生命周期（启动、停止、重启）
4. 提供 SandboxFileService 实例给各个 Agent 使用

优势：
- 整个流程都在 Sandbox 中运行，无需本地↔Sandbox 文件同步
- 节省本地机器开销
- 环境一致性更好
- 【安全】使用临时目录作为挂载点，避免直接修改宿主机项目目录
"""

import logging
import shutil
import tempfile
from typing import Optional, Dict, Any
from pathlib import Path

from app.service.sandbox_manager import sandbox_manager, SandboxInfo
from app.service.sandbox_file_service import SandboxFileService, get_sandbox_file_service
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class SandboxOrchestrator:
    """
    Sandbox 编排器
    
    在 Architect 阶段就拉起 Sandbox，并管理其生命周期。
    各个 Agent 都通过 SandboxFileService 操作 Sandbox 中的文件。
    
    【安全改进】使用临时目录作为挂载点，避免直接修改宿主机项目目录。
    临时目录在测试开始前清理，测试结束后保留便于调试。
    """
    
    def __init__(self, pipeline_id: int):
        self.pipeline_id = pipeline_id
        self.sandbox_info: Optional[SandboxInfo] = None
        self.file_service: Optional[SandboxFileService] = None
        self._is_initialized = False
        self.temp_dir: Optional[str] = None  # 临时目录路径
    
    async def initialize(
        self,
        project_path: str
    ) -> Dict[str, Any]:
        """
        初始化 Sandbox（在 Architect 阶段调用）
        
        【安全改进】使用临时目录作为挂载点，避免直接修改宿主机项目目录。
        
        Args:
            project_path: 本地项目路径（用于复制到临时目录，然后挂载到 Sandbox）
            
        Returns:
            Dict: 初始化结果
        """
        if self._is_initialized:
            logger.info(f"[Pipeline {self.pipeline_id}] Sandbox 已初始化，跳过")
            return {"success": True, "message": "Sandbox 已初始化"}
        
        try:
            await push_log(
                self.pipeline_id,
                "info",
                "🐳 正在启动 Docker Sandbox（Sandbox 优先架构）...",
                stage="REQUIREMENT"
            )
            
            # 【安全改进】创建临时目录作为挂载点
            self.temp_dir = tempfile.mkdtemp(prefix=f"omniflow-sandbox-{self.pipeline_id}-")
            logger.info(f"[Pipeline {self.pipeline_id}] 创建临时目录: {self.temp_dir}")
            
            # 复制项目代码到临时目录
            await push_log(
                self.pipeline_id,
                "info",
                f"📁 复制项目代码到临时目录...",
                stage="REQUIREMENT"
            )
            
            # 使用 shutil.copytree 复制项目代码
            try:
                shutil.copytree(
                    project_path,
                    self.temp_dir,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(
                        '.git', '__pycache__', '*.pyc', '.pytest_cache',
                        'node_modules', '.venv', 'venv', '.env'
                    )
                )
                logger.info(f"[Pipeline {self.pipeline_id}] 项目代码复制完成")
            except Exception as copy_error:
                logger.error(f"[Pipeline {self.pipeline_id}] 复制项目代码失败: {copy_error}")
                # 清理临时目录
                if self.temp_dir and Path(self.temp_dir).exists():
                    shutil.rmtree(self.temp_dir, ignore_errors=True)
                return {
                    "success": False,
                    "error": f"复制项目代码失败: {copy_error}"
                }
            
            # 1. 启动 Sandbox（使用临时目录作为挂载点）
            self.sandbox_info = await sandbox_manager.start(
                pipeline_id=self.pipeline_id,
                project_path=self.temp_dir  # 【关键】使用临时目录而不是原始项目路径
            )
            
            logger.info(f"[Pipeline {self.pipeline_id}] Sandbox 启动成功", extra={
                "container_id": self.sandbox_info.container_id,
                "port": self.sandbox_info.port,
                "temp_dir": self.temp_dir
            })
            
            await push_log(
                self.pipeline_id,
                "info",
                f"✅ Sandbox 启动成功 (端口: {self.sandbox_info.port})",
                stage="REQUIREMENT"
            )
            await push_log(
                self.pipeline_id,
                "info",
                f"📁 临时目录: {self.temp_dir}",
                stage="REQUIREMENT"
            )
            
            # 2. 创建文件服务
            self.file_service = get_sandbox_file_service(self.pipeline_id)
            
            # 3. 验证 Sandbox 中的文件系统
            verify_result = await self._verify_sandbox_filesystem()
            if not verify_result["success"]:
                logger.error(f"[Pipeline {self.pipeline_id}] Sandbox 文件系统验证失败")
                return verify_result
            
            self._is_initialized = True
            
            return {
                "success": True,
                "sandbox_info": self.sandbox_info,
                "file_service": self.file_service,
                "temp_dir": self.temp_dir,
                "message": "Sandbox 初始化成功"
            }
            
        except Exception as e:
            logger.error(f"[Pipeline {self.pipeline_id}] Sandbox 初始化失败: {e}")
            # 清理临时目录
            if self.temp_dir and Path(self.temp_dir).exists():
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            await push_log(
                self.pipeline_id,
                "error",
                f"❌ Sandbox 初始化失败: {str(e)[:200]}",
                stage="REQUIREMENT"
            )
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _verify_sandbox_filesystem(self) -> Dict[str, Any]:
        """
        验证 Sandbox 中的文件系统
        
        Returns:
            Dict: 验证结果
        """
        try:
            # 检查关键目录是否存在
            check_result = await sandbox_manager.exec(
                self.pipeline_id,
                "ls -la /workspace/backend/",
                timeout=10
            )
            
            if check_result.exit_code != 0:
                return {
                    "success": False,
                    "error": f"无法访问 /workspace/backend/: {check_result.error}"
                }
            
            logger.info(f"[Pipeline {self.pipeline_id}] Sandbox 文件系统验证通过")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"[Pipeline {self.pipeline_id}] 验证 Sandbox 文件系统失败: {e}")
            return {"success": False, "error": str(e)}
    
    def get_file_service(self) -> Optional[SandboxFileService]:
        """
        获取 SandboxFileService 实例
        
        Returns:
            Optional[SandboxFileService]: 文件服务实例，如果未初始化则返回 None
        """
        return self.file_service
    
    async def cleanup(self) -> Dict[str, Any]:
        """
        清理 Sandbox（在 Pipeline 结束时调用）
        
        Returns:
            Dict: 清理结果
        """
        try:
            if not self._is_initialized:
                return {"success": True, "message": "Sandbox 未初始化，无需清理"}
            
            await push_log(
                self.pipeline_id,
                "info",
                "🛑 正在停止 Docker Sandbox...",
                stage="CLEANUP"
            )
            
            await sandbox_manager.stop(self.pipeline_id)
            
            self._is_initialized = False
            self.sandbox_info = None
            self.file_service = None
            
            logger.info(f"[Pipeline {self.pipeline_id}] Sandbox 已停止")
            
            await push_log(
                self.pipeline_id,
                "info",
                "✅ Sandbox 已停止",
                stage="CLEANUP"
            )
            
            return {"success": True, "message": "Sandbox 已停止"}
            
        except Exception as e:
            logger.error(f"[Pipeline {self.pipeline_id}] 停止 Sandbox 失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def restart(self, project_path: str) -> Dict[str, Any]:
        """
        重启 Sandbox
        
        Args:
            project_path: 项目路径
            
        Returns:
            Dict: 重启结果
        """
        await self.cleanup()
        return await self.initialize(project_path)
    
    async def exec_command(self, cmd: str, timeout: int = 60) -> Dict[str, Any]:
        """
        在 Sandbox 中执行命令
        
        Args:
            cmd: 要执行的命令
            timeout: 超时时间（秒）
            
        Returns:
            Dict: 包含 stdout, stderr, exit_code 的结果
        """
        if not self._is_initialized:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Sandbox 未初始化",
                "exit_code": -1
            }
        
        try:
            result = await sandbox_manager.exec(self.pipeline_id, cmd, timeout)
            return {
                "success": result.exit_code == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code
            }
        except Exception as e:
            logger.error(f"[Pipeline {self.pipeline_id}] 执行命令失败: {e}")
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1
            }


# 全局 Sandbox 编排器管理器（按 pipeline_id 存储）
_sandbox_orchestrators: Dict[int, SandboxOrchestrator] = {}


def get_sandbox_orchestrator(pipeline_id: int) -> SandboxOrchestrator:
    """
    获取或创建 SandboxOrchestrator 实例
    
    Args:
        pipeline_id: Pipeline ID
        
    Returns:
        SandboxOrchestrator: 编排器实例
    """
    if pipeline_id not in _sandbox_orchestrators:
        _sandbox_orchestrators[pipeline_id] = SandboxOrchestrator(pipeline_id)
    return _sandbox_orchestrators[pipeline_id]


async def cleanup_sandbox_orchestrator(pipeline_id: int) -> Dict[str, Any]:
    """
    清理并移除指定 Pipeline 的 SandboxOrchestrator
    
    Args:
        pipeline_id: Pipeline ID
        
    Returns:
        Dict: 清理结果
    """
    if pipeline_id in _sandbox_orchestrators:
        orchestrator = _sandbox_orchestrators[pipeline_id]
        result = await orchestrator.cleanup()
        del _sandbox_orchestrators[pipeline_id]
        return result
    return {"success": True, "message": "Orchestrator 不存在"}
