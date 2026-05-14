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
                # 【环境隔离补丁】清理掉沙箱中历史遗留的 AI 生成测试，防止被污染的测试阻断后续 pytest collection
                ai_generated_dir = Path(self.temp_dir) / "backend" / "tests" / "ai_generated"
                if ai_generated_dir.exists():
                    import glob
                    for f in glob.glob(str(ai_generated_dir / "test_*.py")):
                        Path(f).unlink(missing_ok=True)
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
            
            # 1. 启动 Sandbox（使用绑定挂载，宿主机和容器共享工作区）
            self.sandbox_info = await sandbox_manager.start(
                pipeline_id=self.pipeline_id,
                project_path=self.temp_dir,  # 【关键】使用临时目录作为挂载点
                use_bind_mount=True  # 【架构简化】使用绑定挂载，宿主机和容器共享同一个工作区
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
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                return verify_result

            # 4. 初始化 Git 环境（为 SnapshotService 做准备）
            git_init_result = await self._init_git_environment()
            if not git_init_result["success"]:
                logger.warning(f"[Pipeline {self.pipeline_id}] Git 环境初始化失败: {git_init_result.get('error')}")
                # Git 初始化失败不阻断流程，只是警告

            # 5. 【新增】验证关键文件的语法完整性
            syntax_check_result = await self._verify_file_syntax_integrity()
            if not syntax_check_result["success"]:
                logger.error(f"[Pipeline {self.pipeline_id}] 文件语法完整性验证失败")
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                return syntax_check_result

            # 6. 【新增】预构建代码索引（为 RAG 语义检索做准备）
            await self._build_code_index()

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

    async def _init_git_environment(self) -> Dict[str, Any]:
        """
        在 Sandbox 中初始化 Git 环境

        为 SnapshotService 的 git stash 功能做准备。
        执行: git init -> config -> add -> commit

        Returns:
            Dict: 初始化结果
        """
        try:
            # 【关键修复】先检查是否已经有 Git 仓库且已有提交
            # 避免重复初始化导致超时
            check_result = await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git rev-parse --git-dir && git log --oneline -1",
                timeout=5
            )
            if check_result.exit_code == 0:
                logger.info(f"[Pipeline {self.pipeline_id}] Git 环境已存在且已有提交，跳过初始化")
                await push_log(
                    self.pipeline_id,
                    "info",
                    "✅ Git 环境已就绪",
                    stage="REQUIREMENT"
                )
                return {"success": True}

            await push_log(
                self.pipeline_id,
                "info",
                "🔧 初始化 Git 环境...",
                stage="REQUIREMENT"
            )

            # 【新增】强制清理可能存在的锁文件和旧的 Git 目录，防止上一次失败导致的死锁
            await sandbox_manager.exec(
                self.pipeline_id,
                "rm -rf /workspace/.git/index.lock /workspace/.git/refs/heads/*.lock",
                timeout=5
            )

            # 1. git init (如果 .git 不存在)
            init_result = await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git init",
                timeout=10
            )
            if init_result.exit_code != 0:
                return {
                    "success": False,
                    "error": f"git init 失败: {init_result.stderr}"
                }

            # 2. git config
            config_email_result = await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git config user.email 'omniflow@ai.local'",
                timeout=5
            )
            config_name_result = await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git config user.name 'OmniFlow AI'",
                timeout=5
            )
            if config_email_result.exit_code != 0 or config_name_result.exit_code != 0:
                return {
                    "success": False,
                    "error": f"git config 失败: {config_email_result.stderr or config_name_result.stderr}"
                }

            # 3. 检查是否有文件需要提交
            status_result = await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git status --porcelain | wc -l",
                timeout=10
            )
            if status_result.exit_code == 0:
                file_count = int(status_result.stdout.strip() or 0)
                if file_count == 0:
                    logger.info(f"[Pipeline {self.pipeline_id}] 没有文件需要提交，跳过 git add/commit")
                    await push_log(
                        self.pipeline_id,
                        "info",
                        "✅ Git 环境初始化完成（无文件需提交）",
                        stage="REQUIREMENT"
                    )
                    return {"success": True}
                logger.info(f"[Pipeline {self.pipeline_id}] 需要提交 {file_count} 个文件")

            # 4. git add (超时 120 秒，大项目文件可能很多)
            add_result = await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git add -A",  # 使用 -A 确保包含所有文件
                timeout=120
            )
            if add_result.exit_code != 0:
                return {
                    "success": False,
                    "error": f"git add 失败: {add_result.stderr}"
                }

            # 5. git commit (超时 60 秒，首次提交文件较多)
            commit_result = await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git commit -m 'Initial commit'",
                timeout=60
            )
            if commit_result.exit_code != 0:
                return {
                    "success": False,
                    "error": f"git commit 失败: {commit_result.stderr}"
                }

            logger.info(f"[Pipeline {self.pipeline_id}] Git 环境初始化成功")
            await push_log(
                self.pipeline_id,
                "info",
                "✅ Git 环境初始化成功",
                stage="REQUIREMENT"
            )
            return {"success": True}

        except Exception as e:
            logger.error(f"[Pipeline {self.pipeline_id}] 初始化 Git 环境失败: {e}")
            return {"success": False, "error": str(e)}

    async def _verify_file_syntax_integrity(self) -> Dict[str, Any]:
        """
        验证关键文件的语法完整性

        在 Sandbox 初始化完成后，对关键 Python 文件执行语法检查，
        确保文件复制过程中没有损坏。

        Returns:
            Dict: 验证结果
        """
        try:
            await push_log(
                self.pipeline_id,
                "info",
                "🔍 检查关键文件语法完整性...",
                stage="REQUIREMENT"
            )

            # 定义关键文件列表（这些文件如果损坏会导致系统无法运行）
            critical_files = [
                "app/service/stage_handlers/coding_handler.py",
                "app/service/stage_handlers/base.py",
                "app/service/workflow.py",
                "app/agents/coder.py",
                "app/agents/base.py",
            ]

            import shlex

            failed_files = []

            for file_path in critical_files:
                full_path = f"/workspace/backend/{file_path}"
                check_result = await sandbox_manager.exec(
                    self.pipeline_id,
                    f"python3 -m py_compile {shlex.quote(full_path)} 2>&1",
                    timeout=10
                )

                if check_result.exit_code != 0:
                    error_detail = check_result.stdout or check_result.stderr
                    logger.error(f"[Pipeline {self.pipeline_id}] {file_path} 语法错误: {error_detail}")
                    failed_files.append({
                        "file": file_path,
                        "error": (error_detail or "")[:200]
                    })

            if failed_files:
                error_msg = f"发现 {len(failed_files)} 个关键文件语法错误: " + \
                           ", ".join([f["file"] for f in failed_files])
                logger.error(f"[Pipeline {self.pipeline_id}] {error_msg}")
                await push_log(
                    self.pipeline_id,
                    "error",
                    f"❌ {error_msg}",
                    stage="REQUIREMENT"
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "failed_files": failed_files
                }

            logger.info(f"[Pipeline {self.pipeline_id}] 所有关键文件语法检查通过")
            await push_log(
                self.pipeline_id,
                "info",
                "✅ 关键文件语法检查通过",
                stage="REQUIREMENT"
            )
            return {"success": True}

        except Exception as e:
            logger.error(f"[Pipeline {self.pipeline_id}] 文件语法完整性检查异常: {e}")
            return {"success": False, "error": str(e)}

    async def _build_code_index(self) -> Dict[str, Any]:
        """
        【新增】预构建代码索引（为 RAG 语义检索做准备）

        在 Sandbox 初始化阶段预构建代码索引，避免 ArchitectAgent 首次调用
        semantic_search 时的长时间等待。

        Returns:
            Dict: 构建结果
        """
        try:
            await push_log(
                self.pipeline_id,
                "info",
                "🔍 正在预构建代码索引（为 RAG 语义检索做准备）...",
                stage="REQUIREMENT"
            )

            from app.service.code_indexer import get_indexer
            import time

            start_time = time.time()

            # 获取索引服务（使用宿主机工作区路径）
            indexer = await get_indexer(self.temp_dir, include_tests=False)

            # 检查是否已有有效缓存
            cached_data = indexer._load_index_cache()
            if cached_data and not indexer._is_index_stale(cached_data.get('file_hashes', {})):
                await push_log(
                    self.pipeline_id,
                    "info",
                    "✅ 代码索引已存在且有效，跳过构建",
                    stage="REQUIREMENT"
                )
                return {"success": True, "cached": True}

            # 构建索引
            chunks = indexer.build_index(force_refresh=False)

            elapsed_time = time.time() - start_time

            await push_log(
                self.pipeline_id,
                "info",
                f"✅ 代码索引构建完成: {len(chunks)} 个代码块 ({elapsed_time:.1f}s)",
                stage="REQUIREMENT"
            )

            logger.info(
                f"[Pipeline {self.pipeline_id}] 代码索引构建完成: {len(chunks)} 个代码块 ({elapsed_time:.1f}s)"
            )

            return {
                "success": True,
                "chunks_count": len(chunks),
                "elapsed_time": elapsed_time,
                "cached": False
            }

        except Exception as e:
            logger.error(f"[Pipeline {self.pipeline_id}] 代码索引构建失败: {e}")
            await push_log(
                self.pipeline_id,
                "warning",
                f"⚠️ 代码索引构建失败: {str(e)[:200]}，将使用降级方案",
                stage="REQUIREMENT"
            )
            # 索引构建失败不阻断流程，只是警告
            return {"success": False, "error": str(e)}

    def get_file_service(self) -> Optional[SandboxFileService]:
        """
        获取 SandboxFileService 实例

        Returns:
            Optional[SandboxFileService]: 文件服务实例，如果未初始化则返回 None
        """
        return self.file_service

    def get_workspace_path(self) -> Optional[str]:
        """
        获取 Sandbox 工作区路径（宿主机上的临时目录）

        【绑定挂载架构】返回宿主机上的 temp_dir，与 Sandbox 容器内的 /workspace 是同一个目录
        可以直接用于 Git 操作，无需再从 Sandbox 复制文件

        Returns:
            Optional[str]: 工作区路径，如果未初始化则返回 None
        """
        return self.temp_dir
    
    async def cleanup(self) -> Dict[str, Any]:
        """
        清理 Sandbox（在 Pipeline 结束时调用）

        【安全优化】主动删除 temp_dir，避免磁盘占用

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

            # 【安全优化】主动删除临时工作区目录
            if self.temp_dir and Path(self.temp_dir).exists():
                try:
                    await push_log(
                        self.pipeline_id,
                        "info",
                        f"🧹 清理临时工作区...",
                        stage="CLEANUP"
                    )
                    # 使用线程池执行同步的 shutil.rmtree
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: shutil.rmtree(self.temp_dir, ignore_errors=True)
                    )
                    logger.info(f"[Pipeline {self.pipeline_id}] 临时工作区已清理: {self.temp_dir}")
                    await push_log(
                        self.pipeline_id,
                        "info",
                        f"✅ 临时工作区已清理",
                        stage="CLEANUP"
                    )
                except Exception as cleanup_error:
                    logger.warning(f"[Pipeline {self.pipeline_id}] 清理临时工作区失败: {cleanup_error}")
                    # 清理失败不阻断流程，只是警告

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
