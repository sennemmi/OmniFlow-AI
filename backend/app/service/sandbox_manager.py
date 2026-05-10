"""
SandboxManager - Docker 沙箱管理器

管理 Pipeline 的 Docker 沙箱容器生命周期，包括启动、停止、执行命令等功能。
提供文件操作、命令执行、Git 操作等高级接口。
"""

import asyncio
import base64
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.core.logging import info, error, warning, set_pipeline_id


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
    """Docker 沙箱管理器（含预热池）"""

    # 预热池配置
    POOL_SIZE = 2
    POOL_PORT_START = 18900  # 预热池专用端口段，与动态分配端口错开

    def __init__(self):
        self._sandboxes: Dict[int, SandboxInfo] = {}
        self._base_port = 19000
        self._network_name = "omniflow-sandbox"
        self._port_lock = asyncio.Lock()
        self._used_ports: set = set()
        # 预热池
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=self.POOL_SIZE)
        self._pool_initialized = False
        self._pool_lock = asyncio.Lock()

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
                    return True
                else:
                    error(f"Container {container_name} is not running")
                    return False
            except Exception as e:
                error(f"Error checking container status: {e}")
                pass

            await asyncio.sleep(1)

        return False

    async def _force_remove_container(self, container_name: str) -> bool:
        """强制删除容器（如果存在），返回是否成功"""
        try:
            # 先检查容器是否存在
            check_proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "-a", "-q", "-f", f"name={container_name}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await check_proc.communicate()
            if not stdout.decode().strip():
                return True  # 容器不存在，视为成功

            # 【新增】检查容器是否正在删除中
            inspect_proc = await asyncio.create_subprocess_exec(
                "docker", "inspect", "--format", "{{.State.Status}}", container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            status_out, _ = await inspect_proc.communicate()
            status = status_out.decode().strip()

            if status == "removing":
                info(f"容器 {container_name} 正在删除中，等待完成...")
                # 等待容器删除完成（最多等待 10 秒）
                for i in range(20):
                    await asyncio.sleep(0.5)
                    check_proc = await asyncio.create_subprocess_exec(
                        "docker", "ps", "-a", "-q", "-f", f"name={container_name}",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await check_proc.communicate()
                    if not stdout.decode().strip():
                        info(f"容器 {container_name} 已删除")
                        return True
                warning(f"等待容器 {container_name} 删除超时")
                return False

            # 【改进】直接使用 docker rm -f 强制删除容器（同时停止和删除，更可靠）
            # 避免先 stop 再 rm 的两步操作，减少端口释放延迟
            rm_proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", "-v", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await rm_proc.communicate()

            if rm_proc.returncode != 0:
                # 【改进】如果删除失败且错误是"already in progress"，等待后重试
                stderr_text = stderr.decode() if stderr else ""
                if "already in progress" in stderr_text.lower():
                    info(f"容器 {container_name} 删除正在进行中，等待...")
                    await asyncio.sleep(2)
                    # 再次检查容器是否还存在
                    check_proc = await asyncio.create_subprocess_exec(
                        "docker", "ps", "-a", "-q", "-f", f"name={container_name}",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await check_proc.communicate()
                    if not stdout.decode().strip():
                        return True  # 容器已删除
                error(f"删除容器 {container_name} 失败: {stderr_text}")
                return False

            return True
        except Exception as e:
            error(f"强制删除容器 {container_name} 异常: {str(e)}")
            return False

    # ==================== 预热池 ====================

    async def init_pool(self, project_path: str) -> None:
        """
        启动时预热 Sandbox 池（在 lifespan.startup 中调用）

        预创建 POOL_SIZE 个容器，项目代码预加载到容器中。
        Pipeline 创建时通过 acquire_from_pool() 直接获取，无需等待 docker run + docker cp。

        【降级方案】如果预热池初始化失败，会记录警告但不会影响系统运行，
        Pipeline 创建时会自动回退到正常启动流程。
        """
        async with self._pool_lock:
            if self._pool_initialized:
                return

        if not await self._ensure_network():
            error("预热池启动失败：Docker 网络不可用，将使用正常启动流程")
            return

        success_count = 0
        for i in range(self.POOL_SIZE):
            try:
                container_name = f"omniflow-prewarm-{i}"
                port = self.POOL_PORT_START + i
                self._used_ports.add(port)

                # 【改进】重试删除，确保容器被清理
                removed = await self._force_remove_container(container_name)
                if not removed:
                    # 如果删除失败，尝试使用带随机后缀的名称
                    import random
                    container_name = f"omniflow-prewarm-{i}-{random.randint(1000, 9999)}"
                    info(f"使用备用容器名称: {container_name}")

                # 【修复】等待端口被操作系统完全释放（避免 TIME_WAIT 状态导致绑定失败）
                # 最多等待 5 秒
                for _ in range(10):
                    if not await self._is_port_in_use(port):
                        break
                    await asyncio.sleep(0.5)
                else:
                    warning(f"端口 {port} 仍然被占用，尝试使用备用端口")
                    port = await self._find_available_port()

                cmd = [
                    "docker", "run", "--rm", "-d",
                    "--name", container_name,
                    "-p", f"{port}:8000",
                    "--memory", "1g",
                    "--cpus", "2",
                    "--network", self._network_name,
                    "omniflowai/sandbox:latest", "sleep", "infinity"
                ]

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode != 0:
                    error(f"预热池容器 {i} 启动失败: {stderr.decode()}")
                    # 【降级】继续尝试创建其他容器
                    continue

                container_id = stdout.decode().strip()

                if not await self._wait_for_container_ready(container_name, timeout=10):
                    await self._stop_container(container_name)
                    continue

                # 预加载项目代码
                if project_path:
                    copy_ok = await self._copy_project_to_container(container_name, project_path)
                    if not copy_ok:
                        error(f"预热池容器 {i} 项目代码复制失败，移除此容器")
                        await self._stop_container(container_name)
                        continue

                info(f"预热池容器就绪", index=i, container_id=container_id[:12], port=port)
                await self._pool.put((container_name, container_id, port))
                success_count += 1

            except Exception as e:
                error(f"预热池容器 {i} 创建失败: {str(e)}")

        # 初始化完成后才在锁内设置标志位（防止其他协程看到未完成的初始化）
        async with self._pool_lock:
            if success_count > 0:
                self._pool_initialized = True
            else:
                self._pool_initialized = False

        # 【降级提示】如果预热池没有完全初始化，给出警告
        if success_count == 0:
            error("预热池初始化完全失败，所有 Pipeline 将使用正常启动流程（启动时间会增加 ~10-30s）")
        elif success_count < self.POOL_SIZE:
            warning(f"预热池部分初始化成功 ({success_count}/{self.POOL_SIZE})，系统仍可运行但性能可能受影响")
        else:
            info(f"预热池初始化完成 ({success_count}/{self.POOL_SIZE})")

    async def acquire_from_pool(self, pipeline_id: int) -> SandboxInfo:
        """
        从预热池获取一个容器分配给 Pipeline

        如果池中有可用容器，直接复用（重命名容器），耗时 <1s。
        如果池为空，回退到正常启动流程。

        Returns:
            SandboxInfo: 沙箱信息
        """
        try:
            pool_name, container_id, port = self._pool.get_nowait()
        except asyncio.QueueEmpty:
            info("预热池为空，回退到正常启动", pipeline_id=pipeline_id)
            return None  # 调用方应回退到 start()

        new_name = f"omniflow-sandbox-{pipeline_id}"

        # 重命名容器（原子操作，近乎零开销）
        try:
            rename_proc = await asyncio.create_subprocess_exec(
                "docker", "rename", pool_name, new_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await rename_proc.communicate()
            if rename_proc.returncode != 0:
                error(f"重命名容器失败: {stderr.decode()}")
                await self._force_remove_container(pool_name)
                return None
        except Exception:
            await self._force_remove_container(pool_name)
            return None

        # 【核心修复】创建临时目录、复制项目并设置路径
        # try/finally 确保任何异常路径下临时目录都被清理
        import tempfile
        import shutil
        from app.core.config import settings

        project_path = str(Path(settings.TARGET_PROJECT_PATH).resolve())
        temp_dir = tempfile.mkdtemp(prefix=f"omniflow-sandbox-{pipeline_id}-")
        copy_ok = False
        try:
            shutil.copytree(
                project_path,
                temp_dir,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    '.git', '__pycache__', '*.pyc', '.pytest_cache',
                    'node_modules', '.venv', 'venv', '.env'
                )
            )
            copy_ok = True
        except Exception as e:
            error(f"预热池复制项目代码到临时目录失败：{str(e)}")
            await self._force_remove_container(new_name)
            return None
        finally:
            if not copy_ok:
                shutil.rmtree(temp_dir, ignore_errors=True)

        sandbox_info = SandboxInfo(
            container_id=container_id,
            pipeline_id=pipeline_id,
            port=port,
            project_path=temp_dir  # 临时目录路径
        )
        self._sandboxes[pipeline_id] = sandbox_info

        info("从预热池分配容器成功",
             pipeline_id=pipeline_id,
             container_id=container_id[:12],
             pool_name=pool_name,
             temp_dir=temp_dir)

        # 异步补充池（后台补充一个新容器）
        asyncio.create_task(self._refill_pool())

        return sandbox_info

    async def _refill_pool(self) -> None:
        """后台补充预热池"""
        from app.core.config import settings
        try:
            index = int(time.time()) % 100
            container_name = f"omniflow-prewarm-{index}"
            port = await self._find_available_port()

            # 【修复】先强制清理可能残留的同名容器
            await self._force_remove_container(container_name)

            cmd = [
                "docker", "run", "--rm", "-d",
                "--name", container_name,
                "-p", f"{port}:8000",
                "--memory", "1g", "--cpus", "2",
                "--network", self._network_name,
                "omniflowai/sandbox:latest", "sleep", "infinity"
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return

            container_id = stdout.decode().strip()
            if not await self._wait_for_container_ready(container_name, timeout=10):
                await self._stop_container(container_name)
                return

            project_path = str(Path(settings.TARGET_PROJECT_PATH).resolve())
            if project_path and Path(project_path).exists():
                await self._copy_project_to_container(container_name, project_path)

            await self._pool.put((container_name, container_id, port))
            info(f"预热池补充完成", container_id=container_id[:12])
        except Exception as e:
            error(f"补充预热池失败: {str(e)}")

    async def cleanup_pool(self) -> None:
        """
        【新增】清理预热池中的所有容器

        在应用关闭时调用，确保所有预热容器被正确停止，释放端口。
        """
        info("开始清理预热池容器...")

        # 清理预热池中的容器
        while not self._pool.empty():
            try:
                pool_name, container_id, port = self._pool.get_nowait()
                await self._force_remove_container(pool_name)
                self._release_port(port)
                info(f"预热池容器已清理", container_name=pool_name)
            except Exception as e:
                error(f"清理预热池容器失败: {str(e)}")

        # 重置预热池状态
        self._pool_initialized = False
        info("预热池清理完成")

    async def start(
        self,
        pipeline_id: int,
        project_path: Optional[str] = None,
        use_bind_mount: bool = False
    ) -> SandboxInfo:
        """
        启动沙箱容器

        Args:
            pipeline_id: Pipeline ID
            project_path: 项目路径（可选，如果不提供则需要在启动后使用 docker cp 复制代码）
            use_bind_mount: 是否使用绑定挂载（默认 False，使用 docker cp 性能更好）

        Returns:
            SandboxInfo: 沙箱信息
        """
        set_pipeline_id(pipeline_id)

        try:
            container_name = f"omniflow-sandbox-{pipeline_id}"

            # 检查是否已存在
            if pipeline_id in self._sandboxes:
                info("Sandbox already exists", pipeline_id=pipeline_id)
                return self._sandboxes[pipeline_id]

            # 强制清理可能存在的残留容器
            await self._force_remove_container(container_name)

            # 确保网络存在
            if not await self._ensure_network():
                raise RuntimeError("Failed to ensure Docker network")

            # 查找可用端口
            port = await self._find_available_port()

            # 构建 docker run 命令
            cmd = [
                "docker", "run", "--rm", "-d",
                "--name", container_name,
                "-p", f"{port}:8000",
                "--memory", "1g",
                "--cpus", "2",
                "--network", self._network_name,
            ]

            # 【性能优化】默认不使用绑定挂载，而是后续使用 docker cp
            # 这样可以避免跨设备 I/O 损耗
            if use_bind_mount and project_path:
                cmd.extend(["-v", f"{project_path}:/workspace"])

            cmd.append("omniflowai/sandbox:latest")
            cmd.append("sleep")
            cmd.append("infinity")

            info("Starting sandbox", container_name=container_name, port=port, use_bind_mount=use_bind_mount)

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

            # 等待容器就绪（检查容器是否运行）
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
                raise RuntimeError("Container failed to become ready within timeout")

            info("Sandbox started", container_id=container_id[:12])

            # 【稳定化】等待 2 秒让容器入口进程完全就绪，减少 docker cp 时容器闪退的竞态窗口
            await asyncio.sleep(2)

            # 【性能优化】如果不使用绑定挂载，使用 docker cp 复制代码到容器
            if not use_bind_mount and project_path:
                info("Copying project to container using docker cp", project_path=project_path)
                copy_success = await self._copy_project_to_container(container_name, project_path)
                if not copy_success:
                    error("Failed to copy project to container")
                    await self._stop_container(container_name)
                    raise RuntimeError("Failed to copy project to container")
                info("Project copied to container successfully")

            # 创建沙箱信息
            sandbox_info = SandboxInfo(
                container_id=container_id,
                pipeline_id=pipeline_id,
                port=port,
                project_path=project_path or ""
            )

            self._sandboxes[pipeline_id] = sandbox_info
            return sandbox_info

        finally:
            set_pipeline_id(None)

    async def _copy_project_to_container(self, container_name: str, project_path: str, max_retries: int = 3) -> bool:
        """
        使用 docker cp 将项目代码复制到容器内

        包含存活检查 + 重试机制，应对容器入口进程在启动后闪退的竞态条件。

        Args:
            container_name: 容器名称
            project_path: 项目路径
            max_retries: 最大重试次数

        Returns:
            bool: 是否成功
        """
        for attempt in range(max_retries):
            # 先确认容器还在运行，避免 No such container 错误
            try:
                check_proc = await asyncio.create_subprocess_exec(
                    "docker", "ps", "-q", "-f", f"name={container_name}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                check_stdout, _ = await check_proc.communicate()
                if not check_stdout.decode().strip():
                    error(
                        f"docker cp 前检查：容器 {container_name} 已不在运行中 (attempt {attempt + 1}/{max_retries})"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    return False
            except Exception as e:
                error(f"检查容器状态时出错: {e}")

            try:
                # 创建 /workspace 目录
                mkdir_proc = await asyncio.create_subprocess_exec(
                    "docker", "exec", container_name, "mkdir", "-p", "/workspace",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE
                )
                await mkdir_proc.communicate()

                # 如果 mkdir 失败(容器已退出)，重试
                if mkdir_proc.returncode != 0:
                    error(
                        f"docker exec mkdir 失败 (容器可能已退出), "
                        f"attempt {attempt + 1}/{max_retries}"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    return False

                # 使用 docker cp 复制项目代码
                copy_proc = await asyncio.create_subprocess_exec(
                    "docker", "cp", f"{project_path}/.", f"{container_name}:/workspace",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await copy_proc.communicate()

                if copy_proc.returncode != 0:
                    error_msg = stderr.decode().strip() if stderr else "Unknown error"
                    if "No such container" in error_msg and attempt < max_retries - 1:
                        error(
                            f"docker cp 容器已退出，重试 {attempt + 1}/{max_retries}: {error_msg}"
                        )
                        await asyncio.sleep(1)
                        continue
                    error(f"docker cp failed: {error_msg}")
                    return False

                info(f"docker cp 成功 (project -> {container_name}:/workspace)")
                return True

            except Exception as e:
                error(f"Error copying project to container (attempt {attempt + 1}): {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return False

        return False

    async def _stop_container(self, container_name: str, timeout: int = 10) -> bool:
        """停止容器（内部方法）

        Args:
            container_name: 容器名称
            timeout: 停止超时时间（秒），默认 10 秒，0 表示立即强制停止
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", "-t", str(timeout), container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception as e:
            error(f"Error stopping container {container_name}: {str(e)}")
            return False

    async def _kill_container(self, container_name: str) -> bool:
        """强制停止容器（使用 docker kill，立即终止）

        Args:
            container_name: 容器名称

        Returns:
            bool: 是否成功
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "kill", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception as e:
            error(f"Error killing container {container_name}: {str(e)}")
            return False

    async def stop(self, pipeline_id: int, fast: bool = False) -> bool:
        """
        停止沙箱容器

        Args:
            pipeline_id: Pipeline ID
            fast: 是否使用快速停止（docker kill，立即终止，不等待优雅关闭）

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

            if fast:
                info(f"Fast stopping sandbox container (docker kill)", container_name=container_name)
                success = await self._kill_container(container_name)
            else:
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
            info("Executing command", cmd=cmd[:50])

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

    # ==================== 高级工具方法 ====================

    @staticmethod
    def _sanitize_sandbox_path(path: str) -> str:
        """防止路径穿越攻击：规范化路径并确保在 /workspace 内"""
        workspace = Path("/workspace")
        resolved = (workspace / path).resolve()
        if not str(resolved).startswith(str(workspace)):
            raise ValueError(f"路径穿越检测：{path} 尝试访问 /workspace 之外")
        return str(resolved)

    async def read_file(self, pipeline_id: int, path: str) -> str:
        """
        读取容器内 /workspace/{path} 的文件内容

        Args:
            pipeline_id: Pipeline ID
            path: 文件路径（相对于 /workspace）

        Returns:
            str: 文件内容

        Raises:
            FileNotFoundError: 文件不存在或读取失败
        """
        safe_path = self._sanitize_sandbox_path(path)
        result = await self.exec(pipeline_id, f"cat {safe_path}")
        if result.exit_code != 0:
            raise FileNotFoundError(result.stderr)
        return result.stdout

    async def write_file(self, pipeline_id: int, path: str, content: str) -> bool:
        """
        将 content 写入容器内 /workspace/{path}

        Args:
            pipeline_id: Pipeline ID
            path: 文件路径（相对于 /workspace）
            content: 文件内容

        Returns:
            bool: 是否写入成功
        """
        safe_path = self._sanitize_sandbox_path(path)
        b64 = base64.b64encode(content.encode()).decode()
        result = await self.exec(
            pipeline_id,
            f"echo {b64} | base64 -d > {safe_path}"
        )
        return result.exit_code == 0

    async def exec_command(self, pipeline_id: int, cmd: str, timeout: int = 30) -> dict:
        """
        在容器内执行命令

        Args:
            pipeline_id: Pipeline ID
            cmd: 要执行的命令
            timeout: 超时时间（秒）

        Returns:
            dict: 包含 stdout, stderr, exit_code, timed_out 的字典
        """
        result = await self.exec(pipeline_id, cmd, timeout)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out
        }

    async def list_directory(self, pipeline_id: int, path: str = ".", depth: int = 2) -> str:
        """
        列出容器内目录内容

        Args:
            pipeline_id: Pipeline ID
            path: 目录路径（相对于 /workspace）
            depth: 遍历深度

        Returns:
            str: 目录列表字符串
        """
        safe_path = self._sanitize_sandbox_path(path)
        result = await self.exec(
            pipeline_id, f"find {safe_path} -maxdepth {depth} -not -path '*/.git/*'"
        )
        return result.stdout

    async def git_diff(self, pipeline_id: int) -> str:
        """
        获取 Git 变更差异

        Args:
            pipeline_id: Pipeline ID

        Returns:
            str: git diff 输出
        """
        result = await self.exec(pipeline_id, "cd /workspace && git diff")
        return result.stdout

    async def git_reset(self, pipeline_id: int) -> bool:
        """
        重置 Git 工作区（丢弃所有变更）

        Args:
            pipeline_id: Pipeline ID

        Returns:
            bool: 是否重置成功
        """
        result = await self.exec(
            pipeline_id, "cd /workspace && git checkout -- . && git clean -fd"
        )
        return result.exit_code == 0


# 全局单例
sandbox_manager = SandboxManager()
