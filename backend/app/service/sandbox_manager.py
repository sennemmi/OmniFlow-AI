"""
SandboxManager - Docker 沙箱管理器

管理 Pipeline 的 Docker 沙箱容器生命周期，包括启动、停止、执行命令等功能。
"""

import asyncio
import socket
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import httpx

from app.core.logging import info, error, set_pipeline_id


@dataclass
class SandboxInfo:
    """沙箱信息"""
    container_id: str
    pipeline_id: int
    port: int
    project_path: str
    started_at: datetime = field(default_factory=datetime.now)


@dataclass
class ExecResult:
    """命令执行结果"""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False


class SandboxManager:
    """Docker 沙箱管理器"""

    def __init__(self):
        self._sandboxes: Dict[int, SandboxInfo] = {}
        self._base_port = 19000
        self._network_name = "omniflow-sandbox"
        self._port_lock = asyncio.Lock()  # 端口分配锁，防止竞态条件
        self._used_ports: set = set()  # 已分配端口集合

    async def _find_available_port(self) -> int:
        """
        查找可用端口（线程安全）
        
        使用锁确保在并发场景下不会分配重复的端口。
        """
        async with self._port_lock:
            port = self._base_port
            while port in self._used_ports or await self._is_port_in_use(port):
                port += 1
            self._used_ports.add(port)
            return port
    
    def _release_port(self, port: int) -> None:
        """释放端口"""
        self._used_ports.discard(port)

    async def _is_port_in_use(self, port: int) -> bool:
        """检查端口是否被占用"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            return result == 0
        except Exception:
            return True

    async def _ensure_network(self) -> bool:
        """确保 Docker 网络存在，不存在则创建"""
        try:
            # 检查网络是否存在
            check_proc = await asyncio.create_subprocess_exec(
                "docker", "network", "inspect", self._network_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await check_proc.wait()

            if check_proc.returncode == 0:
                return True

            # 创建网络
            create_proc = await asyncio.create_subprocess_exec(
                "docker", "network", "create", self._network_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await create_proc.communicate()

            if create_proc.returncode == 0:
                return True
            else:
                error(f"Failed to create network: {stderr.decode()}")
                return False
        except Exception as e:
            error(f"Error ensuring network: {str(e)}")
            return False

    async def _wait_for_container_ready(self, container_name: str, timeout: int = 30) -> bool:
        """等待容器就绪（只检查容器是否存活并运行）"""
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            # 检查容器是否还在运行
            try:
                check_proc = await asyncio.create_subprocess_exec(
                    "docker", "ps", "-q", "-f", f"name={container_name}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await check_proc.communicate()
                if stdout.decode().strip():
                    # 容器正在运行，认为就绪
                    info("Container is running")
                    return True
                else:
                    error(f"Container {container_name} is not running")
                    return False
            except Exception as e:
                error(f"Error checking container status: {e}")
                pass

            await asyncio.sleep(1)

        return False

    async def _force_remove_container(self, container_name: str) -> None:
        """强制删除容器（如果存在）"""
        try:
            # 先尝试停止
            stop_proc = await asyncio.create_subprocess_exec(
                "docker", "stop", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await stop_proc.wait()

            # 再删除
            rm_proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await rm_proc.wait()
        except Exception:
            pass  # 忽略错误，容器可能不存在

    async def start(self, pipeline_id: int, project_path: str) -> SandboxInfo:
        """
        启动沙箱容器

        Args:
            pipeline_id: Pipeline ID
            project_path: 项目路径

        Returns:
            SandboxInfo: 沙箱信息
        """
        set_pipeline_id(pipeline_id)

        try:
            container_name = f"omniflow-sandbox-{pipeline_id}"

            # 检查是否已存在
            if pipeline_id in self._sandboxes:
                info(f"Sandbox already exists for pipeline {pipeline_id}")
                return self._sandboxes[pipeline_id]

            # 强制清理可能存在的残留容器
            await self._force_remove_container(container_name)

            # 确保网络存在
            if not await self._ensure_network():
                raise RuntimeError("Failed to ensure Docker network")

            # 查找可用端口
            port = await self._find_available_port()
            info(f"Using port {port} for sandbox", port=port)

            # 构建 docker run 命令
            # 使用预构建的 omniflowai/sandbox 镜像，依赖已预装
            cmd = [
                "docker", "run", "--rm", "-d",
                "--name", container_name,
                "-v", f"{project_path}:/workspace",
                "-p", f"{port}:8000",
                "--memory", "512m",
                "--cpus", "1",
                "--network", self._network_name,
                "omniflowai/sandbox:latest",  # 使用预构建镜像
            ]

            info("Starting sandbox container", container_name=container_name)

            # 启动容器
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                error(f"Failed to start container: {error_msg}")
                raise RuntimeError(f"Failed to start sandbox: {error_msg}")

            container_id = stdout.decode().strip()
            info(f"Container started", container_id=container_id[:12])

            # 等待容器就绪（检查容器是否运行）
            info("Waiting for container to be ready...")
            if not await self._wait_for_container_ready(container_name, timeout=10):
                # 获取容器日志以便调试
                try:
                    log_proc = await asyncio.create_subprocess_exec(
                        "docker", "logs", container_name,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    log_stdout, log_stderr = await log_proc.communicate()
                    container_logs = log_stdout.decode() if log_stdout else log_stderr.decode() if log_stderr else "No logs"
                    error(f"Container logs:\n{container_logs[:2000]}")
                except Exception as e:
                    error(f"Failed to get container logs: {e}")

                # 启动失败，清理容器
                await self._stop_container(container_name)
                raise RuntimeError("Container failed to become ready within 180 seconds")

            info("Container is ready")

            # 创建沙箱信息
            sandbox_info = SandboxInfo(
                container_id=container_id,
                pipeline_id=pipeline_id,
                port=port,
                project_path=project_path
            )

            self._sandboxes[pipeline_id] = sandbox_info
            return sandbox_info

        finally:
            set_pipeline_id(None)

    async def _stop_container(self, container_name: str) -> bool:
        """停止容器（内部方法）"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception as e:
            error(f"Error stopping container {container_name}: {str(e)}")
            return False

    async def stop(self, pipeline_id: int) -> bool:
        """
        停止沙箱容器

        Args:
            pipeline_id: Pipeline ID

        Returns:
            bool: 是否成功
        """
        set_pipeline_id(pipeline_id)

        try:
            if pipeline_id not in self._sandboxes:
                info(f"No sandbox found for pipeline {pipeline_id}")
                return True

            # 获取沙箱信息并释放端口
            sandbox_info = self._sandboxes[pipeline_id]
            self._release_port(sandbox_info.port)
            
            container_name = f"omniflow-sandbox-{pipeline_id}"
            info(f"Stopping sandbox container", container_name=container_name)

            success = await self._stop_container(container_name)

            if success:
                del self._sandboxes[pipeline_id]
                info("Sandbox stopped successfully")
            else:
                error("Failed to stop sandbox")

            return success

        finally:
            set_pipeline_id(None)

    async def exec(self, pipeline_id: int, cmd: str, timeout: int = 30) -> ExecResult:
        """
        在沙箱中执行命令

        Args:
            pipeline_id: Pipeline ID
            cmd: 要执行的命令
            timeout: 超时时间（秒）

        Returns:
            ExecResult: 执行结果
        """
        set_pipeline_id(pipeline_id)

        try:
            if pipeline_id not in self._sandboxes:
                error(f"No sandbox found for pipeline {pipeline_id}")
                return ExecResult(
                    stderr="Sandbox not found",
                    exit_code=-1
                )

            container_name = f"omniflow-sandbox-{pipeline_id}"
            info(f"Executing command in sandbox", cmd=cmd[:100])

            # 构建 docker exec 命令
            exec_cmd = [
                "docker", "exec",
                container_name,
                "sh", "-c", cmd
            ]

            # 执行命令
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )

                return ExecResult(
                    stdout=stdout.decode() if stdout else "",
                    stderr=stderr.decode() if stderr else "",
                    exit_code=proc.returncode or 0
                )

            except asyncio.TimeoutError:
                # 超时，尝试终止进程
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass

                error(f"Command timed out after {timeout}s")
                return ExecResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout} seconds",
                    exit_code=-1,
                    timed_out=True
                )

        except Exception as e:
            error(f"Error executing command: {str(e)}")
            return ExecResult(
                stderr=str(e),
                exit_code=-1
            )

        finally:
            set_pipeline_id(None)

    def get_info(self, pipeline_id: int) -> Optional[SandboxInfo]:
        """
        获取沙箱信息

        Args:
            pipeline_id: Pipeline ID

        Returns:
            Optional[SandboxInfo]: 沙箱信息，不存在则返回 None
        """
        return self._sandboxes.get(pipeline_id)

    def list_active(self) -> List[SandboxInfo]:
        """
        列出所有活动的沙箱

        Returns:
            List[SandboxInfo]: 沙箱信息列表
        """
        return list(self._sandboxes.values())


# 全局单例
sandbox_manager = SandboxManager()
