"""
代码分析服务

提供代码分析（AST提取、依赖分析、相关测试文件查找）
"""

import ast
import logging
from pathlib import Path
from typing import List, Optional, Set, Dict, Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class CodeAnalysisService:
    """
    代码分析服务

    职责：
    1. AST 提取
    2. 依赖分析
    3. 相关测试文件查找
    """

    def __init__(self, project_root: Optional[str] = None):
        """初始化代码分析服务"""
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

    def extract_imports_from_content(self, content: str) -> List[str]:
        """
        从代码内容中提取 import 语句

        Args:
            content: Python 代码内容

        Returns:
            List[str]: import 列表
        """
        imports = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        imports.append(f"{module}.{alias.name}")
        except SyntaxError:
            logger.warning("解析代码提取 import 失败：语法错误")
        except Exception as e:
            logger.error(f"提取 import 失败: {e}")

        return imports

    def find_file_by_module(self, module_path: str) -> Optional[str]:
        """
        根据模块路径查找文件

        Args:
            module_path: 模块路径（如 app.models.user）

        Returns:
            Optional[str]: 文件相对路径
        """
        # 将模块路径转换为文件路径
        parts = module_path.split(".")

        # 尝试多种可能的路径
        possible_paths = [
            f"backend/{'/'.join(parts)}.py",
            f"backend/{'/'.join(parts)}/__init__.py",
            f"{'/'.join(parts)}.py",
            f"{'/'.join(parts)}/__init__.py",
        ]

        for path in possible_paths:
            abs_path = self.project_root / path
            if abs_path.exists():
                return path

        return None

    def analyze_dependencies(self, file_path: str, content: Optional[str] = None) -> Dict[str, Any]:
        """
        分析文件依赖

        Args:
            file_path: 文件路径
            content: 文件内容（可选，不提供则读取文件）

        Returns:
            Dict: 依赖分析结果
        """
        if content is None:
            abs_path = self.project_root / file_path
            if not abs_path.exists():
                return {"error": "文件不存在"}
            try:
                content = abs_path.read_text(encoding='utf-8')
            except Exception as e:
                return {"error": str(e)}

        imports = self.extract_imports_from_content(content)

        # 分类依赖
        stdlib_imports = []
        third_party_imports = []
        local_imports = []

        stdlib_modules = {
            'os', 'sys', 'json', 're', 'datetime', 'time', 'pathlib',
            'typing', 'collections', 'itertools', 'functools', 'hashlib',
            'hmac', 'secrets', 'tempfile', 'shutil', 'logging', 'asyncio'
        }

        for imp in imports:
            base_module = imp.split('.')[0]
            if base_module in stdlib_modules:
                stdlib_imports.append(imp)
            elif base_module in ['app', 'backend']:
                local_imports.append(imp)
            else:
                third_party_imports.append(imp)

        return {
            "file_path": file_path,
            "total_imports": len(imports),
            "stdlib_imports": stdlib_imports,
            "third_party_imports": third_party_imports,
            "local_imports": local_imports,
            "all_imports": imports
        }

    def get_related_test_files(self, source_file: str) -> List[str]:
        """
        获取与源文件相关的测试文件

        Args:
            source_file: 源文件路径

        Returns:
            List[str]: 相关测试文件路径列表
        """
        related_tests = []

        # 解析源文件名
        path = Path(source_file)
        file_name = path.stem  # 不带扩展名的文件名

        # 可能的测试文件命名模式
        test_patterns = [
            f"tests/unit/test_{file_name}.py",
            f"tests/unit/test_{file_name}_api.py",
            f"tests/test_{file_name}.py",
            f"backend/tests/unit/test_{file_name}.py",
            f"backend/tests/unit/test_{file_name}_api.py",
            f"backend/tests/test_{file_name}.py",
        ]

        for pattern in test_patterns:
            abs_path = self.project_root / pattern
            if abs_path.exists():
                related_tests.append(pattern)

        # 如果文件在 app/ 目录下，也检查对应的 tests/ 目录
        if "app/" in source_file:
            # 提取模块路径
            parts = source_file.replace("backend/", "").replace(".py", "").split("/")
            if len(parts) >= 2:
                module_name = parts[-1]
                for pattern in [
                    f"tests/unit/test_{module_name}.py",
                    f"backend/tests/unit/test_{module_name}.py",
                ]:
                    abs_path = self.project_root / pattern
                    if abs_path.exists() and pattern not in related_tests:
                        related_tests.append(pattern)

        return related_tests

    def analyze_project_structure(self) -> Dict[str, Any]:
        """
        分析项目结构

        Returns:
            Dict: 项目结构信息
        """
        structure = {
            "total_files": 0,
            "python_files": 0,
            "test_files": 0,
            "api_files": [],
            "service_files": [],
            "model_files": [],
            "other_files": []
        }

        try:
            for py_file in self.project_root.rglob("*.py"):
                rel_path = str(py_file.relative_to(self.project_root))
                structure["total_files"] += 1
                structure["python_files"] += 1

                if "test_" in rel_path or "_test.py" in rel_path:
                    structure["test_files"] += 1
                elif "/api/" in rel_path or "api_" in rel_path:
                    structure["api_files"].append(rel_path)
                elif "/service/" in rel_path:
                    structure["service_files"].append(rel_path)
                elif "/models/" in rel_path or "/model/" in rel_path:
                    structure["model_files"].append(rel_path)
                else:
                    structure["other_files"].append(rel_path)

        except Exception as e:
            logger.error(f"分析项目结构失败: {e}")

        return structure

    def find_import_cycles(self, file_path: str, visited: Optional[Set[str]] = None) -> List[List[str]]:
        """
        查找循环导入（简化版）

        Args:
            file_path: 起始文件路径
            visited: 已访问文件集合

        Returns:
            List[List[str]]: 发现的循环导入链
        """
        if visited is None:
            visited = set()

        cycles = []

        if file_path in visited:
            return [[file_path]]  # 发现循环

        visited.add(file_path)

        abs_path = self.project_root / file_path
        if not abs_path.exists():
            return cycles

        try:
            content = abs_path.read_text(encoding='utf-8')
            imports = self.extract_imports_from_content(content)

            for imp in imports:
                if imp.startswith('app.') or imp.startswith('backend.'):
                    dep_file = self.find_file_by_module(imp)
                    if dep_file and dep_file != file_path:
                        sub_cycles = self.find_import_cycles(dep_file, visited.copy())
                        for cycle in sub_cycles:
                            if file_path in cycle:
                                cycles.append([file_path] + cycle)
                            else:
                                cycles.append(cycle)

        except Exception as e:
            logger.error(f"查找循环导入失败: {e}")

        return cycles


# 单例实例
code_analysis = CodeAnalysisService()
