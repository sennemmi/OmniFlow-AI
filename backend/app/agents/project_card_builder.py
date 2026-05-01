"""
项目契约卡生成器

纯 Python / AST 实现，不走 LLM，毫秒级完成。
生成比扁平文件列表信息密度高得多的项目名片。
"""

from __future__ import annotations

import ast
import json
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Set

logger = logging.getLogger(__name__)

# 【改进7】CONVENTIONS.md 路径
_CONVENTIONS_PATH = Path(__file__).parent.parent.parent.parent / "CONVENTIONS.md"

def _load_conventions() -> str:
    """加载项目代码约定文档"""
    try:
        if _CONVENTIONS_PATH.exists():
            content = _CONVENTIONS_PATH.read_text(encoding="utf-8")
            logger.info(f"加载 CONVENTIONS.md: {len(content)} 字符")
            return content
    except Exception as e:
        logger.warning(f"加载 CONVENTIONS.md 失败: {e}")
    return ""


class ProjectCardBuilder:
    # 不进入这些目录
    SKIP_DIRS: Set[str] = {
        '__pycache__', '.git', '.venv', 'venv', 'env',
        'node_modules', 'dist', 'build', '.omniflow_index',
        'tests', 'test', 'migrations',
    }

    # 入口文件关键词 → 重要程度标记
    ENTRY_PATTERNS: Dict[str, str] = {
        'main.py':        '🚀 应用入口',
        'app.py':         '🚀 应用入口',
        'settings.py':    '⚙️  配置中心',
        'config.py':      '⚙️  配置中心',
        'database.py':    '🗄️  数据库',
        'models.py':      '🗄️  数据模型',
        'router.py':      '🔀 路由注册',
        'routes.py':      '🔀 路由注册',
        'middleware.py':  '🔒 中间件',
        'auth.py':        '🔒 认证',
        'dependencies.py':'🔗 依赖注入',
    }

    def __init__(self, project_path: Path):
        self.project_path = project_path

    # 【全局约定】健康组件数据模型 Schema
    HEALTH_COMPONENT_SCHEMA = {
        "ComponentStatus": {
            "description": "组件状态的标准返回结构",
            "fields": {
                "status": {"type": "str", "enum": ["up", "down", "degraded"], "description": "组件状态"},
                "response_time_ms": {"type": "float", "description": "响应时间（毫秒）"},
                "error": {"type": "str", "optional": True, "description": "错误信息（如果有）"},
                "timestamp": {"type": "str", "description": "ISO格式时间戳"}
            }
        },
        "DiskUsage": {
            "description": "磁盘使用状态",
            "fields": {
                "total_gb": {"type": "float", "description": "总容量（GB）"},
                "used_gb": {"type": "float", "description": "已使用容量（GB）"},
                "free_gb": {"type": "float", "description": "剩余容量（GB）"},
                "usage_percent": {"type": "float", "description": "使用百分比（0-100）"}
            }
        },
        "MemoryUsage": {
            "description": "内存使用状态",
            "fields": {
                "total_mb": {"type": "int", "description": "总内存（MB）"},
                "used_mb": {"type": "int", "description": "已使用内存（MB）"},
                "available_mb": {"type": "int", "description": "可用内存（MB）"},
                "usage_percent": {"type": "float", "description": "使用百分比（0-100）"}
            }
        },
        "DatabaseStatus": {
            "description": "数据库状态",
            "fields": {
                "status": {"type": "str", "enum": ["up", "down", "degraded"], "description": "数据库状态"},
                "response_time_ms": {"type": "float", "description": "响应时间（毫秒）"},
                "connection_count": {"type": "int", "optional": True, "description": "当前连接数"},
                "error": {"type": "str", "optional": True, "description": "错误信息"}
            }
        },
        "HealthCheckResponse": {
            "description": "健康检查整体响应",
            "fields": {
                "status": {"type": "str", "enum": ["healthy", "unhealthy", "degraded"], "description": "整体状态"},
                "health_score": {"type": "int", "description": "健康度评分（0-100）"},
                "components": {"type": "dict", "description": "各组件状态详情"},
                "timestamp": {"type": "str", "description": "ISO格式时间戳"}
            }
        }
    }

    def build(self, max_depth: int = 3, max_files: int = 60) -> str:
        """
        生成完整的项目契约卡，返回 JSON 字符串。
        """
        card: Dict[str, Any] = {}
        card["directory_structure"] = self._build_dir_tree(max_depth)
        card["tech_stack"] = self._extract_tech_stack()
        card["entry_points"] = self._find_entry_points()
        card["module_imports"] = self._build_import_graph(max_files)
        card["symbol_index"] = self._build_symbol_index(max_files)
        # 【改进】添加函数签名库，供 Architect/Designer 参考
        card["function_signatures"] = self._build_function_signature_library(max_files)
        card["global_schemas"] = {
            "health_components": self.HEALTH_COMPONENT_SCHEMA,
            "description": "项目级标准数据模型，所有健康检查相关函数必须返回符合这些 Schema 的字典"
        }
        # 【改进7】注入项目约定文档
        conventions = _load_conventions()
        if conventions:
            card["conventions"] = {
                "source": "CONVENTIONS.md",
                "content": conventions,
                "description": "项目代码约定文档，所有 Agent 在生成代码时务必遵守"
            }
        return json.dumps(card, indent=2, ensure_ascii=False)
    
    @staticmethod
    def get_conventions() -> str:
        """获取项目代码约定文档，供 Agent Prompt 注入使用"""
        return _load_conventions()

    def _build_dir_tree(self, max_depth: int) -> str:
        """生成限定深度的目录树字符串"""
        lines: List[str] = []

        def walk(path: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            try:
                entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                return

            entries = [e for e in entries if e.name not in self.SKIP_DIRS and not e.name.startswith('.')]

            for i, entry in enumerate(entries):
                is_last = (i == len(entries) - 1)
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{entry.name}")
                if entry.is_dir():
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    walk(entry, new_prefix, depth + 1)

        walk(self.project_path, "", 0)
        return "\n".join(lines)

    def _extract_tech_stack(self) -> Dict[str, Any]:
        """从 requirements.txt / pyproject.toml / setup.py 提取技术栈。"""
        import sys
        stack: Dict[str, Any] = {"frameworks": [], "databases": [], "others": []}

        FRAMEWORK_KEYWORDS = {
            'fastapi': 'FastAPI', 'flask': 'Flask', 'django': 'Django',
            'starlette': 'Starlette', 'sanic': 'Sanic', 'tornado': 'Tornado',
        }
        DB_KEYWORDS = {
            'sqlalchemy': 'SQLAlchemy', 'sqlmodel': 'SQLModel',
            'pymongo': 'MongoDB', 'motor': 'MongoDB(async)',
            'redis': 'Redis', 'aioredis': 'Redis(async)',
            'psycopg': 'PostgreSQL', 'aiomysql': 'MySQL(async)',
            'chromadb': 'ChromaDB',
        }

        req_files = [
            self.project_path / 'requirements.txt',
            self.project_path / 'requirements-dev.txt',
        ]

        raw_deps: List[str] = []
        for req_file in req_files:
            if req_file.exists():
                for line in req_file.read_text(encoding='utf-8', errors='ignore').splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        pkg = line.split('==')[0].split('>=')[0].split('~=')[0].lower().strip()
                        raw_deps.append(pkg)

        pyproject = self.project_path / 'pyproject.toml'
        if pyproject.exists():
            for line in pyproject.read_text(encoding='utf-8', errors='ignore').splitlines():
                if '=' in line and not line.strip().startswith('#'):
                    pkg = line.split('=')[0].strip().strip('"').lower()
                    raw_deps.append(pkg)

        for dep in raw_deps:
            if dep in FRAMEWORK_KEYWORDS:
                fw = FRAMEWORK_KEYWORDS[dep]
                if fw not in stack["frameworks"]:
                    stack["frameworks"].append(fw)
            elif dep in DB_KEYWORDS:
                db = DB_KEYWORDS[dep]
                if db not in stack["databases"]:
                    stack["databases"].append(db)

        stack["python"] = f"{sys.version_info.major}.{sys.version_info.minor}"
        return stack

    def _find_entry_points(self) -> List[Dict[str, str]]:
        """标记关键入口文件，提示改动风险"""
        entries: List[Dict[str, str]] = []

        for py_file in self.project_path.rglob("*.py"):
            if any(part in self.SKIP_DIRS for part in py_file.parts):
                continue
            if py_file.name.lower() in self.ENTRY_PATTERNS:
                rel = py_file.relative_to(self.project_path).as_posix()
                label = self.ENTRY_PATTERNS[py_file.name.lower()]
                entries.append({
                    "file": rel,
                    "role": label,
                    "warning": "修改此文件可能影响全局行为，请谨慎",
                })

        for py_file in self.project_path.rglob("*.py"):
            if any(part in self.SKIP_DIRS for part in py_file.parts):
                continue
            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                rel = py_file.relative_to(self.project_path).as_posix()
                already = any(e["file"] == rel for e in entries)
                if not already:
                    if 'include_router' in content and rel not in [e["file"] for e in entries]:
                        entries.append({
                            "file": rel,
                            "role": "🔀 路由注册（include_router 发现）",
                            "warning": "增减路由会影响 API 可见性",
                        })
            except Exception:
                pass

        return entries

    def _build_import_graph(self, max_files: int) -> Dict[str, List[str]]:
        """构建模块间 import 依赖图。"""
        graph: Dict[str, List[str]] = {}
        file_count = 0

        for py_file in sorted(self.project_path.rglob("*.py")):
            if file_count >= max_files:
                break
            if any(part in self.SKIP_DIRS for part in py_file.parts):
                continue

            rel = py_file.relative_to(self.project_path).as_posix()
            deps: List[str] = []

            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                tree = ast.parse(content)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    mod = node.module
                    candidate = mod.replace('.', '/') + '.py'
                    candidate_path = self.project_path / candidate
                    if candidate_path.exists():
                        deps.append(candidate)
                    else:
                        init_candidate = mod.replace('.', '/') + '/__init__.py'
                        init_path = self.project_path / init_candidate
                        if init_path.exists():
                            deps.append(init_candidate)

            if deps:
                graph[rel] = list(dict.fromkeys(deps))[:10]
            file_count += 1

        return graph

    def _build_function_signature_library(self, max_files: int = 30) -> Dict[str, List[Dict]]:
        """
        【改进】构建函数签名库，包含函数名、签名和返回结构示例
        
        供 ArchitectAgent 和 DesignerAgent 参考，确保新设计与现有代码一致。
        """
        import re
        library: Dict[str, List[Dict]] = {}
        count = 0
        
        for py_file in sorted(self.project_path.rglob("*.py")):
            if count >= max_files:
                break
            if any(part in self.SKIP_DIRS for part in py_file.parts):
                continue
            
            rel = py_file.relative_to(self.project_path).as_posix()
            
            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            
            functions = []
            # 匹配函数定义
            func_pattern = r"(?P<async>async\s+)?def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)(?:\s*->\s*(?P<ret>[^:]+))?:\s*"
            
            for m in re.finditer(func_pattern, content):
                func_name = m.group("name")
                is_async = bool(m.group("async"))
                params = m.group("params").strip()
                ret_type = m.group("ret").strip() if m.group("ret") else "Any"
                
                # 提取返回字典示例（如果有）
                return_example = None
                func_body = content[m.end():]
                return_match = re.search(r'return\s+(\{[^}]*\})', func_body, re.DOTALL)
                if return_match:
                    return_example = return_match.group(1).replace('\n', ' ').strip()[:200]
                
                functions.append({
                    "name": func_name,
                    "signature": f"{'async ' if is_async else ''}def {func_name}({params}) -> {ret_type}",
                    "return_example": return_example
                })
            
            if functions:
                library[rel] = functions
            count += 1
        
        return library

    def _build_symbol_index(self, max_files: int) -> List[Dict[str, Any]]:
        """构建文件→符号的轻量索引（包含签名）"""
        index: List[Dict[str, Any]] = []
        count = 0

        for py_file in sorted(self.project_path.rglob("*.py")):
            if count >= max_files:
                break
            if any(part in self.SKIP_DIRS for part in py_file.parts):
                continue

            rel = py_file.relative_to(self.project_path).as_posix()
            entry: Dict[str, Any] = {"file": rel, "symbols": []}

            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                tree = ast.parse(content)
            except Exception:
                index.append(entry)
                count += 1
                continue

            MAX_SYMBOLS = 8
            sym_count = 0

            for node in ast.iter_child_nodes(tree):
                if sym_count >= MAX_SYMBOLS:
                    break

                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = self._extract_func_signature(node)
                    entry["symbols"].append({
                        "name": node.name,
                        "type": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                        "signature": sig,
                    })
                    sym_count += 1

                elif isinstance(node, ast.ClassDef):
                    methods = [
                        n.name for n in ast.iter_child_nodes(node)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not n.name.startswith('__')
                    ][:5]
                    entry["symbols"].append({
                        "name": node.name,
                        "type": "class",
                        "public_methods": methods,
                    })
                    sym_count += 1

            index.append(entry)
            count += 1

        return index

    def _extract_func_signature(self, node: ast.FunctionDef) -> str:
        """提取函数签名字符串，如 'async def foo(a: int, b: str) -> dict'"""
        try:
            prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
            args = []
            for arg in node.args.args:
                if arg.arg in ('self', 'cls'):
                    continue
                if arg.annotation:
                    try:
                        ann = ast.unparse(arg.annotation)
                    except AttributeError:
                        ann = "Any"
                    args.append(f"{arg.arg}: {ann}")
                else:
                    args.append(arg.arg)
            ret = ""
            if node.returns:
                try:
                    ret = f" -> {ast.unparse(node.returns)}"
                except AttributeError:
                    ret = ""
            return f"{prefix}{node.name}({', '.join(args)}){ret}"
        except Exception:
            return f"def {node.name}(...)"
