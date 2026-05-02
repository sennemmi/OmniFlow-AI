"""
代码执行服务
业务逻辑层 - 负责将 Agent 生成的代码应用到本地文件系统

【重构说明】
本模块已从单体服务拆分为多个专业模块：
- app/service/file_safe_io.py - 原子文件读写、路径安全、备份、Token
- app/service/code_analysis_service.py - 代码分析、依赖分析
- app/service/auto_heal_service.py - Ruff 自动修复

本模块现在作为门面，组合以上服务，对外暴露统一接口。

原则：
1. 在修改前自动备份原文件（防止 AI 改坏代码）
2. 强制"先读后写"：必须提供 read_token 才能写入
3. 代码写入后自动执行 Ruff 修复（Linter-based Auto-healing）
4. 原子写入 + 路径安全（防止目录穿越攻击）
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.service.file_safe_io import (
    FileSafeIOService,
    FileReadResult,
    FileChangeResult,
    BatchChangeResult,
    file_safe_io
)
from app.service.code_analysis_service import (
    CodeAnalysisService,
    code_analysis
)
from app.service.auto_heal_service import (
    AutoHealService,
    auto_heal
)

logger = logging.getLogger(__name__)


class CodeExecutorError(Exception):
    """代码执行错误"""
    pass


class CodeExecutorService:
    """
    代码执行服务 - 门面模式

    负责：
    1. 安全地将代码写入文件系统
    2. 自动备份原文件
    3. 【核心】强制"先读后写"机制（Read Token）
    4. 冲突检测和验证
    5. 支持批量文件操作
    6. 代码写入后自动执行 Ruff 修复
    7. 原子写入 + 路径安全

    【重构】核心逻辑已拆分到独立模块：
    - FileSafeIOService: 文件安全 IO
    - CodeAnalysisService: 代码分析
    - AutoHealService: 自动修复
    """

    BACKUP_DIR_NAME = ".devflow_backups"
    MAX_BACKUP_AGE_DAYS = 7
    READ_TOKEN_EXPIRY_MINUTES = 30

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化代码执行服务

        Args:
            project_root: 项目根目录，默认使用 settings.TARGET_PROJECT_PATH
        """
        # 初始化项目根目录
        if project_root:
            self.project_root = Path(project_root).resolve()
        else:
            target_path = settings.TARGET_PROJECT_PATH
            if not target_path:
                raise CodeExecutorError(
                    "TARGET_PROJECT_PATH 未配置。\n"
                    "请在 .env 中设置 TARGET_PROJECT_PATH=workspace/your-repo"
                )

            target_path_obj = Path(target_path)
            if not target_path_obj.is_absolute():
                backend_dir = Path(__file__).parent.parent.parent
                project_root_path = backend_dir.parent
                target_path_obj = project_root_path / target_path

            self.project_root = target_path_obj.resolve()
            self.project_root.mkdir(parents=True, exist_ok=True)

        # 备份目录（在目标项目内）
        self.backup_dir = self.project_root / self.BACKUP_DIR_NAME
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # 初始化子服务
        self._file_io = FileSafeIOService(str(self.project_root))
        self._code_analysis = CodeAnalysisService(str(self.project_root))
        self._auto_heal = AutoHealService()

    # =========================================================================
    # 门面方法 - 文件操作（委托给 FileSafeIOService）
    # =========================================================================

    def read_file(self, relative_path: str) -> FileReadResult:
        """读取文件内容并生成 Read Token"""
        return self._file_io.read_file(relative_path)

    def apply_file_change(
        self,
        relative_path: str,
        new_content: str,
        read_token: str,
        create_if_missing: bool = False
    ) -> FileChangeResult:
        """应用文件变更（带 Read Token 验证）"""
        return self._file_io.apply_file_change(
            relative_path=relative_path,
            new_content=new_content,
            read_token=read_token,
            create_if_missing=create_if_missing
        )

    def rollback_change(self, change: FileChangeResult) -> bool:
        """回滚单个文件变更"""
        return self._file_io.rollback_change(change)

    def apply_changes(self, changes: list) -> BatchChangeResult:
        """批量应用文件变更"""
        return self._file_io.apply_changes(changes)

    def rollback_changes(self, changes: list) -> tuple:
        """批量回滚文件变更"""
        return self._file_io.rollback_changes(changes)

    # =========================================================================
    # 门面方法 - 代码分析（委托给 CodeAnalysisService）
    # =========================================================================

    def extract_imports_from_content(self, content: str) -> List[str]:
        """从代码内容中提取 import 语句"""
        return self._code_analysis.extract_imports_from_content(content)

    def find_file_by_module(self, module_path: str) -> Optional[str]:
        """根据模块路径查找文件"""
        return self._code_analysis.find_file_by_module(module_path)

    def analyze_dependencies(self, file_path: str, content: Optional[str] = None) -> Dict[str, Any]:
        """分析文件依赖"""
        return self._code_analysis.analyze_dependencies(file_path, content)

    def get_related_test_files(self, source_file: str) -> List[str]:
        """获取与源文件相关的测试文件"""
        return self._code_analysis.get_related_test_files(source_file)

    def analyze_project_structure(self) -> Dict[str, Any]:
        """分析项目结构"""
        return self._code_analysis.analyze_project_structure()

    # =========================================================================
    # 门面方法 - 自动修复（委托给 AutoHealService）
    # =========================================================================

    def auto_heal_code(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        """调用 Ruff 进行静默修复"""
        target_root = project_root or str(self.project_root)
        return self._auto_heal.auto_heal(target_root)

    def check_code(self, file_path: str) -> Dict[str, Any]:
        """检查代码问题（不修复）"""
        return self._auto_heal.check_code(file_path)

    def format_code(self, file_path: str) -> Dict[str, Any]:
        """格式化代码"""
        return self._auto_heal.format_code(file_path)


# 向后兼容的类导出
FileChange = FileChangeResult

# 单例实例
code_executor = CodeExecutorService()


# 向后兼容的函数导出
def auto_heal_code(project_root: str) -> Dict[str, Any]:
    """调用 Ruff 进行静默修复（向后兼容）"""
    return auto_heal.auto_heal(project_root)
