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


def cleanup_pipeline_file_locks(pipeline_id: int) -> None:
    """
    清理指定 Pipeline 的所有文件锁
    在 Pipeline 终止时调用，防止内存泄漏
    """
    global _file_locks
    prefix = f"pipeline_{pipeline_id}:"
    keys_to_remove = [k for k in list(_file_locks.keys()) if k.startswith(prefix)]
    for key in keys_to_remove:
        del _file_locks[key]
    if keys_to_remove:
        logger.info(f"[SandboxFileService] 清理 {len(keys_to_remove)} 个文件锁 for pipeline {pipeline_id}")


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
        - 移除可能的 /workspace/ 或 /workspace/backend/ 前缀（绝对路径转相对路径）
        - 循环去除重复的 backend/ 前缀（如 backend/backend/app/... → backend/app/...）
        - 如果路径不以 backend/ 开头（如 app/api/v1/health.py），添加 backend/ 前缀
        - 最终路径格式：backend/xxx/xxx.py，映射到 /workspace/backend/xxx/xxx.py
        """
        clean = file_path.replace("\\", "/").lstrip("/")

        # 【修复】处理沙箱内的绝对路径，移除 /workspace/backend/ 或 /workspace/ 前缀
        if clean.startswith("workspace/backend/"):
            clean = clean[len("workspace/backend/"):]
        elif clean.startswith("workspace/"):
            clean = clean[len("workspace/"):]

        # 【修复】循环去除重复的 backend/ 前缀
        while clean.startswith("backend/backend/"):
            clean = clean[8:]  # 去除第一个 "backend/"

        # 如果路径不以 backend/ 开头，添加 backend/ 前缀
        # 因为 sandbox 中 /workspace/backend/ 是代码根目录
        if not clean.startswith("backend/"):
            clean = f"backend/{clean}"

        return clean

    def _is_defense_path(self, file_path: str) -> bool:
        """
        【P3: 防御性测试保护】检查路径是否是 defense 目录下的文件

        Args:
            file_path: 标准化后的文件路径

        Returns:
            bool: 是否是 defense 目录下的文件
        """
        # 检查路径中是否包含 defense 目录
        # 匹配 patterns: backend/tests/defense/, backend/defense/, tests/defense/ 等
        defense_patterns = [
            "/defense/",
            "/defense_test/",
            "defense/",
        ]
        file_path_lower = file_path.lower()
        for pattern in defense_patterns:
            if pattern in file_path_lower:
                return True
        return False

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
        """获取文件级锁，用于并发安全（带 pipeline_id 前缀）"""
        normalized = self._sanitize_path(file_path)
        # 【修复】使用带 pipeline_id 前缀的锁键，便于后续清理
        lock_key = f"pipeline_{self.pipeline_id}:{normalized}"
        async with _locks_lock:
            if lock_key not in _file_locks:
                _file_locks[lock_key] = asyncio.Lock()
            return _file_locks[lock_key]

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

        # 【P3: 防御性测试保护】在写入前拦截对 defense 目录的修改
        clean_path = self._sanitize_path(file_path)
        if self._is_defense_path(clean_path):
            error_msg = f"🚫 拦截违规操作：禁止修改 defense 目录下的文件 [{clean_path}]"
            logger.error(f"[SandboxFileService] {error_msg}")
            logger.error(f"[SandboxFileService] 调用栈: {' -> '.join(caller_info)}")
            return {"success": False, "error": error_msg, "blocked": True}

        # 【改进6】获取文件级锁，防止并发写入
        lock = await self._get_file_lock(file_path)
        async with lock:
            try:
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

                # 【改进】使用更安全的写入方式：通过管道传输 cat > file <<'EOF'
                # 避免 shell 转义问题
                write_result = await self._write_file_safe(full_path, content)

                if not write_result["success"]:
                    return write_result

                # 【新增】写入后立即检查 Python 语法（如果是 Python 文件）
                if file_path.endswith('.py'):
                    syntax_check = await self._verify_python_syntax(full_path)
                    if not syntax_check["success"]:
                        logger.error(f"[SandboxFileService] 文件语法错误: {syntax_check['error']}")
                        return {"success": False, "error": f"文件语法错误: {syntax_check['error']}"}

                logger.info(f"[SandboxFileService] 写入成功: {file_path} ({len(content)} 字符)")
                return {"success": True, "file": file_path}
            except Exception as e:
                logger.error(f"[SandboxFileService] 写入异常: {file_path} - {e}")
                logger.error(f"[SandboxFileService] 异常堆栈: {traceback.format_exc()}")
                return {"success": False, "error": str(e)}

    async def _write_file_safe(self, full_path: str, content: str) -> Dict[str, Any]:
        """
        使用 python3 在沙箱内解码写入，避免 shell 转义和命令行长度限制。

        将内容通过标准输入传给 python3 脚本，由脚本完成 base64 解码和写入。
        """
        try:
            import shlex

            encoded = base64.b64encode(content.encode()).decode()
            safe_path = shlex.quote(full_path)

            # 通过 heredoc 将 base64 内容安全地传给 python3
            # 使用 python3 而非管道避免 shell 转义导致的 base64 损坏
            cmd = (
                f"python3 -c \""
                f"import base64, sys; "
                f"data = base64.b64decode(sys.argv[1]); "
                f"open({safe_path}, 'wb').write(data)"
                f"\" {shlex.quote(encoded)}"
            )

            exec_result = await sandbox_manager.exec(
                self.pipeline_id,
                cmd,
                timeout=30
            )

            if exec_result.exit_code != 0:
                error_msg = exec_result.stderr.strip() if exec_result.stderr else "未知错误"
                logger.error(f"[SandboxFileService] python3 写入失败: {error_msg}")
                return {"success": False, "error": f"文件写入失败: {error_msg}"}

            return {"success": True}
        except Exception as e:
            logger.error(f"[SandboxFileService] 安全写入异常: {e}")
            return {"success": False, "error": str(e)}

    async def _verify_python_syntax(self, full_path: str) -> Dict[str, Any]:
        """
        【新增】验证 Python 文件语法

        写入后立即检查，发现 SyntaxError 时返回错误
        """
        try:
            check_result = await sandbox_manager.exec(
                self.pipeline_id,
                f"python -m py_compile {full_path} 2>&1",
                timeout=10
            )

            if check_result.exit_code != 0:
                error_msg = check_result.stderr.strip() if check_result.stderr else "未知语法错误"
                logger.error(f"[SandboxFileService] Python 语法错误: {error_msg}")
                return {"success": False, "error": error_msg}

            return {"success": True}
        except Exception as e:
            logger.error(f"[SandboxFileService] 语法检查异常: {e}")
            # 语法检查失败不阻断写入，只是记录日志
            return {"success": True, "warning": f"语法检查异常: {e}"}
    
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
