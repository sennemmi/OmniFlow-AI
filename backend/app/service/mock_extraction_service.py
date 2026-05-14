"""
Mock 提取服务

从代码中提取 mock 目标，用于测试生成
"""

import ast
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class MockTarget:
    """Mock 目标"""
    def __init__(
        self,
        patch_target: str,
        description: str = "",
        is_async: bool = False,
        is_lazy_import: bool = False,
        mock_return_value: Any = None
    ):
        self.patch_target = patch_target
        self.description = description
        self.is_async = is_async
        self.is_lazy_import = is_lazy_import
        self.mock_return_value = mock_return_value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patch_target": self.patch_target,
            "description": self.description,
            "is_async": self.is_async,
            "is_lazy_import": self.is_lazy_import,
            "mock_return_value": self.mock_return_value
        }


class MockExtractionService:
    """
    Mock 提取服务

    职责：
    1. 从代码中提取需要 mock 的外部依赖
    2. 识别懒加载导入
    3. 生成 patch 目标路径
    """

    def __init__(self):
        self.external_libs = [
            "psutil", "sqlalchemy", "httpx", "aiohttp", "redis", "celery"
        ]
        self.internal_lazy_imports = [
            "app.core.database", "app.core.config", "app.db"
        ]

    def extract_mock_targets(
        self,
        symbol_name: str,
        module_path: str,
        code_files: List[Dict],
        external_libs: Optional[List[str]] = None
    ) -> List[MockTarget]:
        """
        从真实生成的代码里提取 patch 路径，确保与实际 import 方式一致。

        Args:
            symbol_name: 符号名称（用于日志）
            module_path: 模块路径（如 "app/utils/system_monitor.py"）
            code_files: CoderAgent 生成的文件列表
            external_libs: 需要关注的外部库列表

        Returns:
            List[MockTarget]: patch 目标列表
        """
        if external_libs is None:
            external_libs = self.external_libs

        # 找到对应文件
        module_dot = module_path.replace("backend/", "").replace("/", ".").replace(".py", "")
        content = None
        for f in code_files:
            fp = f.get("file_path", "").replace("backend/", "")
            if fp.replace("/", ".").replace(".py", "") == module_dot:
                content = f.get("content", "")
                break

        if not content:
            return []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        patch_targets = []
        seen = set()

        # 遍历所有节点，包括函数体内部
        for node in ast.walk(tree):
            # case 1: import psutil  ->  patch: app.utils.system_monitor.psutil
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in external_libs:
                        local_name = alias.asname or alias.name.split(".")[0]
                        key = f"{module_dot}.{local_name}"
                        if key not in seen:
                            seen.add(key)
                            patch_targets.append(MockTarget(
                                patch_target=key,
                                description=f"import {alias.name}",
                                is_async=False
                            ))

            # case 2: from ... import ... （包括函数体内懒加载）
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                top = mod.split(".")[0]
                is_external = top in external_libs
                is_internal_lazy = any(mod.startswith(p) for p in self.internal_lazy_imports)

                if is_external or is_internal_lazy:
                    for alias in node.names:
                        local_name = alias.asname or alias.name

                        # 判断是否为函数体内懒加载
                        is_lazy = self._is_inside_function(node, tree)

                        # 检测被导入的函数是否是 async
                        is_async_func = False
                        if is_internal_lazy and local_name in ["get_session", "get_async_session", "async_session"]:
                            is_async_func = True

                        if is_lazy and is_internal_lazy:
                            # 懒加载：patch 源模块，不是使用模块
                            patch_target = f"{mod}.{local_name}"
                            key = f"lazy:{patch_target}"
                            if key not in seen:
                                seen.add(key)
                                patch_targets.append(MockTarget(
                                    patch_target=patch_target,
                                    description=f"from {mod} import {alias.name} (函数体内懒加载，patch源模块)",
                                    is_async=is_async_func,
                                    is_lazy_import=True
                                ))
                        else:
                            # 顶层 import：patch 使用模块
                            patch_target = f"{module_dot}.{local_name}"
                            key = patch_target
                            if key not in seen:
                                seen.add(key)
                                patch_targets.append(MockTarget(
                                    patch_target=patch_target,
                                    description=f"from {mod} import {alias.name}",
                                    is_async=False,
                                    is_lazy_import=is_lazy
                                ))

        return patch_targets

    def _is_inside_function(self, target_node: ast.AST, tree: ast.AST) -> bool:
        """判断节点是否在函数体内"""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if child is target_node:
                        return True
        return False

    def extract_mock_targets_from_content(
        self,
        content: str,
        module_path: str,
        external_libs: Optional[List[str]] = None
    ) -> List[MockTarget]:
        """
        直接从代码内容中提取 mock 目标

        Args:
            content: Python 代码内容
            module_path: 模块路径
            external_libs: 外部库列表

        Returns:
            List[MockTarget]: patch 目标列表
        """
        if external_libs is None:
            external_libs = self.external_libs

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        module_dot = module_path.replace("/", ".").replace(".py", "")
        patch_targets = []
        seen = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in external_libs:
                        local_name = alias.asname or alias.name.split(".")[0]
                        key = f"{module_dot}.{local_name}"
                        if key not in seen:
                            seen.add(key)
                            patch_targets.append(MockTarget(
                                patch_target=key,
                                description=f"import {alias.name}"
                            ))

            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                top = mod.split(".")[0]
                if top in external_libs:
                    for alias in node.names:
                        local_name = alias.asname or alias.name
                        patch_target = f"{module_dot}.{local_name}"
                        if patch_target not in seen:
                            seen.add(patch_target)
                            patch_targets.append(MockTarget(
                                patch_target=patch_target,
                                description=f"from {mod} import {alias.name}"
                            ))

        return patch_targets


# 单例实例
mock_extraction_service = MockExtractionService()
