"""
文件安全 IO 服务

提供原子文件读写、路径安全、备份、Token 生成与验证
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class FileReadResult:
    """文件读取结果，包含 Read Token"""
    file_path: str
    content: Optional[str]
    content_hash: Optional[str]
    read_token: Optional[str]
    exists: bool
    error: Optional[str] = None


@dataclass
class FileChangeResult:
    """文件变更结果"""
    success: bool
    file_path: str
    error: Optional[str] = None
    backup_path: Optional[str] = None


class PathSecurityError(Exception):
    """路径安全错误（目录穿越）"""
    pass


class ReadTokenError(Exception):
    """Read Token 验证错误"""
    pass


class FileSafeIOService:
    """
    文件安全 IO 服务

    职责：
    1. 原子文件读写
    2. 路径安全检查（防止目录穿越）
    3. 文件备份
    4. Read Token 生成与验证
    """

    BACKUP_DIR_NAME = ".devflow_backups"
    MAX_BACKUP_AGE_DAYS = 7
    READ_TOKEN_EXPIRY_MINUTES = 30

    def __init__(self, project_root: Optional[str] = None):
        """初始化文件安全 IO 服务"""
        if project_root:
            self.project_root = Path(project_root).resolve()
        else:
            target_path = settings.TARGET_PROJECT_PATH
            if not target_path:
                raise ValueError("TARGET_PROJECT_PATH 未配置")

            target_path_obj = Path(target_path)
            if not target_path_obj.is_absolute():
                backend_dir = Path(__file__).parent.parent.parent
                project_root_path = backend_dir.parent
                target_path_obj = project_root_path / target_path

            self.project_root = target_path_obj.resolve()
            self.project_root.mkdir(parents=True, exist_ok=True)

        # 备份目录
        self.backup_dir = self.project_root / self.BACKUP_DIR_NAME
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Read Token Secret
        self._read_token_secret = self._get_read_token_secret()
        self._token_cache: Dict[str, Dict[str, Any]] = {}

    def _get_read_token_secret(self) -> str:
        """获取 Read Token 密钥"""
        if settings.READ_TOKEN_SECRET:
            return settings.READ_TOKEN_SECRET
        return secrets.token_hex(32)

    def _compute_content_hash(self, content: str) -> str:
        """计算内容哈希（SHA-256）"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _generate_read_token(self, file_path: str, content_hash: str) -> str:
        """生成 Read Token"""
        expiry = datetime.utcnow() + timedelta(minutes=self.READ_TOKEN_EXPIRY_MINUTES)
        payload = {
            "path": file_path,
            "hash": content_hash,
            "exp": expiry.isoformat(),
            "iat": datetime.utcnow().isoformat()
        }

        payload_json = json.dumps(payload, sort_keys=True)
        signature = hmac.new(
            self._read_token_secret.encode('utf-8'),
            payload_json.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        token = f"{payload_json}.{signature}"
        token_encoded = secrets.token_urlsafe(32)

        self._token_cache[token_encoded] = {
            "payload": payload,
            "signature": signature,
            "used": False
        }

        return token_encoded

    def _verify_read_token(self, token: str, file_path: str, current_content: str) -> bool:
        """验证 Read Token"""
        if not token:
            return False

        # 特殊 Token：NEW_FILE 表示新建文件
        if token == "NEW_FILE":
            return True

        # 检查缓存
        cached = self._token_cache.get(token)
        if not cached:
            logger.warning(f"Read Token 未找到或已过期: {token[:20]}...")
            return False

        # 检查是否已使用
        if cached.get("used"):
            logger.warning(f"Read Token 已被使用: {token[:20]}...")
            return False

        # 验证 payload
        payload = cached["payload"]

        # 检查路径匹配
        if payload["path"] != file_path:
            logger.warning(f"Read Token 路径不匹配: {payload['path']} != {file_path}")
            return False

        # 检查过期时间
        try:
            exp = datetime.fromisoformat(payload["exp"])
            if datetime.utcnow() > exp:
                logger.warning(f"Read Token 已过期")
                return False
        except Exception as e:
            logger.error(f"Read Token 过期时间解析失败: {e}")
            return False

        # 验证内容哈希（检测文件是否被修改）
        current_hash = self._compute_content_hash(current_content)
        if payload["hash"] != current_hash:
            logger.warning(f"Read Token 内容哈希不匹配，文件可能已被修改")
            return False

        # 标记为已使用
        cached["used"] = True
        return True

    def _validate_path(self, relative_path: str) -> Path:
        """
        验证路径安全，防止目录穿越攻击

        Args:
            relative_path: 相对路径

        Returns:
            Path: 绝对路径

        Raises:
            PathSecurityError: 路径不安全
        """
        # 规范化路径
        relative_path = relative_path.replace("\\", "/").lstrip("/")

        # 解析为绝对路径
        abs_path = (self.project_root / relative_path).resolve()

        # 安全检查：确保路径在项目根目录内
        try:
            abs_path.relative_to(self.project_root.resolve())
        except ValueError:
            raise PathSecurityError(
                f"路径安全检查失败: {relative_path} 尝试访问项目根目录之外的区域"
            )

        # 检查是否包含 .. 或 ~
        if ".." in relative_path or "~" in relative_path:
            raise PathSecurityError(f"路径包含非法字符: {relative_path}")

        return abs_path

    def read_file(self, relative_path: str) -> FileReadResult:
        """
        读取文件内容并生成 Read Token

        Args:
            relative_path: 相对项目根目录的路径

        Returns:
            FileReadResult: 读取结果
        """
        try:
            abs_path = self._validate_path(relative_path)

            if not abs_path.exists():
                return FileReadResult(
                    file_path=relative_path,
                    content=None,
                    content_hash=None,
                    read_token="NEW_FILE",
                    exists=False,
                    error=None
                )

            content = abs_path.read_text(encoding='utf-8')
            content_hash = self._compute_content_hash(content)
            read_token = self._generate_read_token(relative_path, content_hash)

            logger.info(f"文件读取成功: {relative_path}, 生成 read_token")

            return FileReadResult(
                file_path=relative_path,
                content=content,
                content_hash=content_hash,
                read_token=read_token,
                exists=True,
                error=None
            )

        except PathSecurityError as e:
            logger.error(f"路径安全错误: {e}")
            return FileReadResult(
                file_path=relative_path,
                content=None,
                content_hash=None,
                read_token=None,
                exists=False,
                error=str(e)
            )
        except Exception as e:
            logger.error(f"读取文件失败: {relative_path}, error: {e}")
            return FileReadResult(
                file_path=relative_path,
                content=None,
                content_hash=None,
                read_token=None,
                exists=False,
                error=str(e)
            )

    def _backup_file(self, abs_path: Path) -> Optional[str]:
        """备份文件"""
        try:
            if not abs_path.exists():
                return None

            # 生成备份文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{abs_path.name}.{timestamp}.bak"
            backup_path = self.backup_dir / backup_name

            # 复制文件
            shutil.copy2(abs_path, backup_path)

            # 清理旧备份
            self._cleanup_old_backups()

            logger.info(f"文件已备份: {abs_path} -> {backup_path}")
            return str(backup_path)

        except Exception as e:
            logger.error(f"备份文件失败: {e}")
            return None

    def _cleanup_old_backups(self):
        """清理超过7天的备份文件"""
        try:
            cutoff = datetime.now() - timedelta(days=self.MAX_BACKUP_AGE_DAYS)
            for backup_file in self.backup_dir.glob("*.bak"):
                try:
                    mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
                    if mtime < cutoff:
                        backup_file.unlink()
                        logger.debug(f"删除旧备份: {backup_file}")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"清理旧备份失败: {e}")

    def _atomic_write(self, abs_path: Path, content: str) -> bool:
        """原子写入文件"""
        try:
            # 确保父目录存在
            abs_path.parent.mkdir(parents=True, exist_ok=True)

            # 创建临时文件
            fd, temp_path = tempfile.mkstemp(
                dir=abs_path.parent,
                prefix=f".{abs_path.name}.tmp_"
            )

            try:
                # 写入临时文件
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(content)

                # 原子重命名
                os.replace(temp_path, abs_path)

                logger.info(f"文件原子写入成功: {abs_path}")
                return True

            except Exception:
                # 清理临时文件
                try:
                    os.unlink(temp_path)
                except:
                    pass
                raise

        except Exception as e:
            logger.error(f"原子写入失败: {abs_path}, error: {e}")
            return False

    def apply_file_change(
        self,
        relative_path: str,
        new_content: str,
        read_token: str,
        create_if_missing: bool = False
    ) -> FileChangeResult:
        """
        应用文件变更（带 Read Token 验证）

        Args:
            relative_path: 相对路径
            new_content: 新内容
            read_token: Read Token
            create_if_missing: 如果文件不存在是否创建

        Returns:
            FileChangeResult: 变更结果
        """
        try:
            abs_path = self._validate_path(relative_path)

            # 检查文件是否存在
            file_exists = abs_path.exists()

            if not file_exists and not create_if_missing:
                return FileChangeResult(
                    success=False,
                    file_path=relative_path,
                    error=f"文件不存在: {relative_path}"
                )

            # 读取当前内容用于验证
            current_content = ""
            if file_exists:
                current_content = abs_path.read_text(encoding='utf-8')

            # 验证 Read Token
            if not self._verify_read_token(read_token, relative_path, current_content):
                return FileChangeResult(
                    success=False,
                    file_path=relative_path,
                    error="Read Token 验证失败：token 无效、已过期或文件已被修改"
                )

            # 备份原文件
            backup_path = None
            if file_exists:
                backup_path = self._backup_file(abs_path)

            # 原子写入
            if not self._atomic_write(abs_path, new_content):
                return FileChangeResult(
                    success=False,
                    file_path=relative_path,
                    error="文件写入失败"
                )

            logger.info(f"文件变更成功: {relative_path}")
            return FileChangeResult(
                success=True,
                file_path=relative_path,
                backup_path=backup_path
            )

        except PathSecurityError as e:
            return FileChangeResult(
                success=False,
                file_path=relative_path,
                error=str(e)
            )
        except Exception as e:
            logger.error(f"应用文件变更失败: {relative_path}, error: {e}")
            return FileChangeResult(
                success=False,
                file_path=relative_path,
                error=str(e)
            )

    def rollback_change(self, change: FileChangeResult) -> bool:
        """
        回滚单个文件变更

        Args:
            change: 文件变更结果（包含 backup_path）

        Returns:
            bool: 回滚是否成功
        """
        if not change.backup_path:
            logger.warning(f"无法回滚 {change.file_path}: 没有备份路径")
            return False

        try:
            backup_path = Path(change.backup_path)
            target_path = self.project_root / change.file_path

            if not backup_path.exists():
                logger.error(f"备份文件不存在: {backup_path}")
                return False

            # 从备份恢复
            import shutil
            shutil.copy2(backup_path, target_path)

            logger.info(f"文件回滚成功: {change.file_path} <- {backup_path}")
            return True

        except Exception as e:
            logger.error(f"回滚失败: {change.file_path}, error: {e}")
            return False

    def apply_changes(self, changes: list) -> 'BatchChangeResult':
        """
        批量应用文件变更

        Args:
            changes: 变更列表，每个元素包含 file_path, new_content, read_token

        Returns:
            BatchChangeResult: 批量变更结果
        """
        results = []
        success_count = 0
        failed_count = 0

        for change_data in changes:
            file_path = change_data.get("file_path")
            new_content = change_data.get("new_content")
            read_token = change_data.get("read_token")

            result = self.apply_file_change(
                relative_path=file_path,
                new_content=new_content,
                read_token=read_token
            )

            results.append(result)

            if result.success:
                success_count += 1
            else:
                failed_count += 1

        return BatchChangeResult(
            success=failed_count == 0,
            changes=results,
            success_count=success_count,
            failed_count=failed_count
        )

    def rollback_changes(self, changes: list) -> tuple:
        """
        批量回滚文件变更

        Args:
            changes: 变更结果列表

        Returns:
            tuple: (成功数量, 失败数量)
        """
        success_count = 0
        failed_count = 0

        for change in changes:
            if self.rollback_change(change):
                success_count += 1
            else:
                failed_count += 1

        return success_count, failed_count


# 批量变更结果类
class BatchChangeResult:
    """批量文件变更结果"""

    def __init__(self, success: bool, changes: list, success_count: int, failed_count: int):
        self.success = success
        self.changes = changes
        self.success_count = success_count
        self.failed_count = failed_count


# 单例实例
file_safe_io = FileSafeIOService()
