"""
代码执行服务
业务逻辑层 - 负责将 Agent 生成的代码应用到本地文件系统

原则：
1. 在修改前自动备份原文件（防止 AI 改坏代码）
2. 简单的冲突检测：如果目标文件不存在，主动报错
3. 代码写入后自动执行 Ruff 修复（Linter-based Auto-healing）

重构说明：
- 所有路径操作基于 settings.TARGET_PROJECT_PATH
- 实现平台代码与 AI 操作目标代码的解耦
"""

import hashlib
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from datetime import datetime

from app.core.config import settings
from app.core.timezone import now_str

logger = logging.getLogger(__name__)


@dataclass
class FileChange:
    """文件变更记录"""
    file_path: str
    original_content: Optional[str]
    new_content: str
    backup_path: Optional[str] = None
    success: bool = False
    error: Optional[str] = None


@dataclass
class ExecutionResult:
    """代码执行结果"""
    success: bool
    changes: List[FileChange]
    summary: Dict[str, int]  # 统计信息
    errors: List[str]


class CodeExecutorError(Exception):
    """代码执行错误"""
    pass


def auto_heal_code(project_root: str) -> Dict[str, Any]:
    """
    调用 Ruff 进行静默修复 - Linter-based Auto-healing

    修复内容：
    - 未使用的 import
    - 代码格式化
    - 简单的语法问题

    Args:
        project_root: 项目根目录路径

    Returns:
        Dict: 修复结果统计
    """
    result = {
        "success": True,
        "check_fixed": 0,
        "format_fixed": 0,
        "errors": []
    }

    try:
        # 修复未使用的 import、简单语法问题等
        check_result = subprocess.run(
            ["ruff", "check", "--fix", project_root],
            capture_output=True,
            text=True,
            timeout=60
        )
        result["check_fixed"] = len([line for line in check_result.stdout.split("\n") if line.strip()])
        if check_result.returncode != 0 and check_result.stderr:
            result["errors"].append(f"ruff check error: {check_result.stderr[:200]}")

        # 代码格式化
        format_result = subprocess.run(
            ["ruff", "format", project_root],
            capture_output=True,
            text=True,
            timeout=60
        )
        result["format_fixed"] = len([line for line in format_result.stdout.split("\n") if line.strip()])
        if format_result.returncode != 0 and format_result.stderr:
            result["errors"].append(f"ruff format error: {format_result.stderr[:200]}")

        logger.info(f"Ruff auto-heal completed: {result}")

    except FileNotFoundError:
        # Ruff 未安装，静默处理
        logger.debug("Ruff not found, skipping auto-heal")
        result["success"] = False
        result["errors"].append("ruff not installed")
    except subprocess.TimeoutExpired:
        logger.warning("Ruff auto-heal timeout")
        result["success"] = False
        result["errors"].append("timeout")
    except Exception as e:
        # 静默处理，不影响主流程
        logger.warning(f"Ruff auto-heal failed: {e}")
        result["success"] = False
        result["errors"].append(str(e))

    return result


class CodeExecutorService:
    """
    代码执行服务

    负责：
    1. 安全地将代码写入文件系统
    2. 自动备份原文件
    3. 冲突检测和验证
    4. 支持批量文件操作
    5. 代码写入后自动执行 Ruff 修复

    安全原则：
    - 修改前必须备份
    - 文件不存在时报错（不自动创建目录）
    - 提供回滚能力
    - 代码写入后自动格式化

    重要：所有操作基于 settings.TARGET_PROJECT_PATH
    实现平台代码与 AI 操作目标代码的解耦
    """

    BACKUP_DIR_NAME = ".devflow_backups"
    MAX_BACKUP_AGE_DAYS = 7

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化代码执行服务
        
        Args:
            project_root: 项目根目录，默认使用 settings.TARGET_PROJECT_PATH
        """
        if project_root:
            self.project_root = Path(project_root).resolve()
        else:
            # 从配置获取目标项目路径
            target_path = settings.TARGET_PROJECT_PATH
            
            if not target_path:
                raise CodeExecutorError(
                    "TARGET_PROJECT_PATH 未配置。\n"
                    "请在 .env 中设置 TARGET_PROJECT_PATH=workspace/your-repo"
                )
            
            # 解析路径
            target_path_obj = Path(target_path)
            if not target_path_obj.is_absolute():
                # 基于 backend 父目录解析
                backend_dir = Path(__file__).parent.parent.parent
                project_root_path = backend_dir.parent
                target_path_obj = project_root_path / target_path
            
            self.project_root = target_path_obj.resolve()

            # 自动创建目录（如果不存在）
            self.project_root.mkdir(parents=True, exist_ok=True)
        
        # 备份目录（在目标项目内）
        self.backup_dir = self.project_root / self.BACKUP_DIR_NAME
        self.backup_dir.mkdir(exist_ok=True)
    
    def _get_backup_path(self, file_path: Path) -> Path:
        """
        生成备份文件路径
        
        Args:
            file_path: 原文件路径
            
        Returns:
            Path: 备份文件路径
        """
        # 使用相对路径 + 时间戳 + hash 生成备份文件名
        rel_path = file_path.relative_to(self.project_root)
        timestamp = now_str("%Y%m%d_%H%M%S")
        path_hash = hashlib.md5(str(rel_path).encode()).hexdigest()[:8]
        
        backup_name = f"{rel_path.name}.{timestamp}.{path_hash}.bak"
        backup_subdir = self.backup_dir / rel_path.parent.relative_to(".")
        backup_subdir.mkdir(parents=True, exist_ok=True)
        
        return backup_subdir / backup_name
    
    def _backup_file(self, file_path: Path) -> Optional[Path]:
        """
        备份文件
        
        Args:
            file_path: 要备份的文件
            
        Returns:
            Optional[Path]: 备份文件路径，文件不存在返回 None
        """
        if not file_path.exists():
            return None
        
        backup_path = self._get_backup_path(file_path)
        shutil.copy2(file_path, backup_path)
        
        return backup_path
    
    def _verify_file_exists(self, file_path: Path) -> bool:
        """
        验证文件是否存在
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否存在
        """
        return file_path.exists()
    
    def apply_file_change(
        self,
        relative_path: str,
        new_content: str,
        create_if_missing: bool = False
    ) -> FileChange:
        """
        应用单个文件变更
        
        Args:
            relative_path: 相对于项目根目录的文件路径
            new_content: 新文件内容
            create_if_missing: 文件不存在时是否创建
            
        Returns:
            FileChange: 变更记录
            
        Raises:
            CodeExecutorError: 文件不存在且 create_if_missing=False
        """
        target_path = self.project_root / relative_path
        
        # 冲突检测：检查文件是否存在
        if not self._verify_file_exists(target_path):
            if not create_if_missing:
                return FileChange(
                    file_path=relative_path,
                    original_content=None,
                    new_content=new_content,
                    success=False,
                    error=f"文件不存在: {relative_path}"
                )
            # 创建父目录
            target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 读取原内容
        original_content = None
        if target_path.exists():
            try:
                original_content = target_path.read_text(encoding='utf-8')
            except Exception as e:
                return FileChange(
                    file_path=relative_path,
                    original_content=None,
                    new_content=new_content,
                    success=False,
                    error=f"读取原文件失败: {e}"
                )
        
        # 备份原文件
        backup_path = None
        if original_content is not None:
            try:
                backup_path = self._backup_file(target_path)
            except Exception as e:
                return FileChange(
                    file_path=relative_path,
                    original_content=original_content,
                    new_content=new_content,
                    success=False,
                    error=f"备份文件失败: {e}"
                )
        
        # 写入新内容
        try:
            target_path.write_text(new_content, encoding='utf-8')
            
            return FileChange(
                file_path=relative_path,
                original_content=original_content,
                new_content=new_content,
                backup_path=str(backup_path) if backup_path else None,
                success=True,
                error=None
            )
        except Exception as e:
            return FileChange(
                file_path=relative_path,
                original_content=original_content,
                new_content=new_content,
                backup_path=str(backup_path) if backup_path else None,
                success=False,
                error=f"写入文件失败: {e}"
            )
    
    def apply_changes(
        self,
        changes: Dict[str, str],
        create_if_missing: bool = False,
        auto_heal: bool = True
    ) -> ExecutionResult:
        """
        批量应用文件变更

        Args:
            changes: {文件路径: 新内容} 字典
            create_if_missing: 文件不存在时是否创建
            auto_heal: 是否自动执行 Ruff 修复（默认开启）

        Returns:
            ExecutionResult: 执行结果
        """
        file_changes = []
        errors = []

        for relative_path, new_content in changes.items():
            change = self.apply_file_change(
                relative_path,
                new_content,
                create_if_missing=create_if_missing
            )
            file_changes.append(change)

            if not change.success:
                errors.append(f"{relative_path}: {change.error}")

        # 统计
        summary = {
            "total": len(file_changes),
            "success": sum(1 for c in file_changes if c.success),
            "failed": sum(1 for c in file_changes if not c.success),
            "created": sum(1 for c in file_changes if c.original_content is None and c.success),
            "modified": sum(1 for c in file_changes if c.original_content is not None and c.success)
        }

        success = summary["failed"] == 0

        # 【Ruff Auto-healing】代码写入后自动修复
        if success and auto_heal and changes:
            heal_result = auto_heal_code(str(self.project_root))
            if heal_result["success"]:
                total_fixed = heal_result.get("check_fixed", 0) + heal_result.get("format_fixed", 0)
                if total_fixed > 0:
                    logger.info(f"Ruff auto-healed {total_fixed} issues")
                    summary["ruff_fixed"] = total_fixed
            else:
                # 静默处理，不影响主流程
                logger.debug(f"Ruff auto-heal skipped: {heal_result.get('errors', [])}")

        return ExecutionResult(
            success=success,
            changes=file_changes,
            summary=summary,
            errors=errors
        )
    
    def rollback_change(self, change: FileChange) -> bool:
        """
        回滚单个文件变更
        
        Args:
            change: 变更记录
            
        Returns:
            bool: 是否成功
        """
        if not change.backup_path:
            return False
        
        try:
            backup_path = Path(change.backup_path)
            target_path = self.project_root / change.file_path
            
            if backup_path.exists():
                shutil.copy2(backup_path, target_path)
                return True
            
            return False
        except Exception as e:
            print(f"回滚失败 {change.file_path}: {e}")
            return False
    
    def rollback_changes(self, changes: List[FileChange]) -> Tuple[int, int]:
        """
        批量回滚变更
        
        Args:
            changes: 变更记录列表
            
        Returns:
            Tuple[int, int]: (成功数, 失败数)
        """
        success_count = 0
        failed_count = 0
        
        for change in changes:
            if self.rollback_change(change):
                success_count += 1
            else:
                failed_count += 1
        
        return success_count, failed_count
    
    def get_file_content(self, relative_path: str) -> Optional[str]:
        """
        获取文件内容
        
        Args:
            relative_path: 相对于项目根目录的文件路径
            
        Returns:
            Optional[str]: 文件内容，不存在返回 None
        """
        target_path = self.project_root / relative_path
        
        if not target_path.exists():
            return None
        
        try:
            return target_path.read_text(encoding='utf-8')
        except Exception:
            return None
    
    def list_backups(self, max_age_days: Optional[int] = None) -> List[Path]:
        """
        列出备份文件
        
        Args:
            max_age_days: 最大年龄（天），默认使用 MAX_BACKUP_AGE_DAYS
            
        Returns:
            List[Path]: 备份文件列表
        """
        if max_age_days is None:
            max_age_days = self.MAX_BACKUP_AGE_DAYS
        
        backups = []
        cutoff_time = datetime.now().timestamp() - (max_age_days * 24 * 3600)
        
        if self.backup_dir.exists():
            for backup_file in self.backup_dir.rglob("*.bak"):
                if backup_file.stat().st_mtime > cutoff_time:
                    backups.append(backup_file)
        
        return sorted(backups, key=lambda p: p.stat().st_mtime, reverse=True)
    
    def cleanup_old_backups(self, max_age_days: Optional[int] = None) -> int:
        """
        清理旧备份
        
        Args:
            max_age_days: 最大年龄（天）
            
        Returns:
            int: 删除的文件数
        """
        if max_age_days is None:
            max_age_days = self.MAX_BACKUP_AGE_DAYS
        
        cutoff_time = datetime.now().timestamp() - (max_age_days * 24 * 3600)
        deleted_count = 0
        
        if self.backup_dir.exists():
            for backup_file in list(self.backup_dir.rglob("*.bak")):
                try:
                    if backup_file.stat().st_mtime < cutoff_time:
                        backup_file.unlink()
                        deleted_count += 1
                except Exception as e:
                    print(f"删除备份失败 {backup_file}: {e}")
        
        return deleted_count
    
    def verify_changes(self, changes: List[FileChange]) -> bool:
        """
        验证变更是否正确应用
        
        Args:
            changes: 变更记录列表
            
        Returns:
            bool: 是否全部验证通过
        """
        for change in changes:
            if not change.success:
                continue
            
            current_content = self.get_file_content(change.file_path)
            if current_content != change.new_content:
                return False
        
        return True


# 便捷函数
def get_code_executor(project_root: Optional[str] = None) -> CodeExecutorService:
    """
    获取代码执行服务实例
    
    Args:
        project_root: 项目根目录
        
    Returns:
        CodeExecutorService: 代码执行服务实例
    """
    return CodeExecutorService(project_root)
