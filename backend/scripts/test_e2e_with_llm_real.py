#!/usr/bin/env python3
"""
端到端集成测试 - 使用真实 LLM 和 Docker Sandbox（真正调用版本）

此脚本真正调用 CoderAgent 和 TesterAgent 的 LLM，
并在 Docker Sandbox 中运行真实的分层测试，
验证从需求到代码到测试的完整流程。

警告: 此脚本会消耗 LLM API Token 并启动 Docker 容器，请谨慎使用！

使用方法:
    # 确保 .env 文件中有 MODELSCOPE_API_KEY
    python scripts/test_e2e_with_llm_real.py
"""

import asyncio
import os
import re
import sys
import tempfile
import time
import shutil
import subprocess
import ast
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.service.layered_test_runner import LayeredTestRunner, LayeredTestResult, LayerResult
from app.service.sandbox_manager import SandboxManager, sandbox_manager
from app.service.agent_coordinator import AgentCoordinatorService
from app.service.code_executor import CodeExecutorService
from app.service.code_indexer import CodeIndexerService
from app.agents.reviewer import ReviewAgent, ReviewDecision
from app.agents.coder import CoderAgent
from app.agents.tester import TesterAgent
from app.agents.architect import ArchitectAgent
from app.agents.designer import DesignerAgent
from app.agents.schemas import CoderOutput, TesterOutput, ArchitectOutput, DesignerOutput


@dataclass
class E2ETestResult:
    """端到端测试结果"""
    scenario_name: str
    success: bool
    code_generated: bool
    tests_generated: bool
    tests_passed: bool
    layered_result: Optional[LayeredTestResult] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class DockerSandboxTester:
    """Docker 沙箱端到端测试器 - 真正调用 LLM 并在容器中运行测试"""

    def __init__(self):
        self.test_results: list = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.backend_dir = Path(__file__).parent.parent
        self.project_root = self.backend_dir.parent
        self.code_indexer: Optional[CodeIndexerService] = None

    def _flexible_search_replace(self, original_text: str, search_block: str, replace_block: str) -> Optional[str]:
        """多级模糊匹配替换算法 (Aider 简化版)"""
        if not search_block:
            return original_text

        # 【第1层】精确匹配
        if search_block in original_text:
            return original_text.replace(search_block, replace_block)

        # 【第2层】换行符归一化 (解决 \r\n vs \n)
        orig_norm = original_text.replace('\r\n', '\n')
        search_norm = search_block.replace('\r\n', '\n')
        replace_norm = replace_block.replace('\r\n', '\n')
        if search_norm in orig_norm:
            return orig_norm.replace(search_norm, replace_norm)

        # 【第3层】行级别的宽松匹配 (忽略每行首尾多余空格，忽略完全空白的行)
        def clean_lines(text: str) -> list:
            return [line.strip() for line in text.splitlines() if line.strip()]

        orig_lines_clean = clean_lines(orig_norm)
        search_lines_clean = clean_lines(search_norm)

        # 在清洗后的原文件中滑动窗口找匹配
        search_len = len(search_lines_clean)
        if search_len > 0:
            for i in range(len(orig_lines_clean) - search_len + 1):
                window = orig_lines_clean[i : i + search_len]
                if window == search_lines_clean:
                    # 在这里，我们确认逻辑上是匹配的
                    # 为了安全替换，我们退回到使用正则进行忽略空白的替换
                    pattern = r'\s*'.join(re.escape(line) for line in search_lines_clean)
                    # 将正则匹配到的原代码块，替换为 AI 提供的新代码块
                    return re.sub(pattern, replace_norm, orig_norm, count=1, flags=re.DOTALL)

        return None  # 彻底找不到

    async def init_code_rag(self):
        """初始化 CodeRAG (代码语义索引)"""
        print("   🔍 初始化 CodeRAG 索引...")
        self.code_indexer = CodeIndexerService(
            project_path=str(self.backend_dir),
            include_tests=True
        )
        # 构建索引
        self.code_indexer.build_index()
        print(f"   ✅ CodeRAG 索引完成，共 {len(self.code_indexer.chunks)} 个代码块")

    async def search_related_code(self, query: str, top_k: int = 10) -> Dict[str, str]:
        """
        使用 CodeRAG 搜索相关代码

        Args:
            query: 查询词（如 "health check api"）
            top_k: 返回前 k 个结果

        Returns:
            Dict[str, str]: 文件路径 -> 文件内容的映射
        """
        if not self.code_indexer:
            await self.init_code_rag()

        print(f"   🔍 CodeRAG 搜索: '{query}'")

        # 1. 搜索签名（广度搜索）
        signatures = await self.code_indexer.search_signatures(query, top_k=top_k)
        print(f"   📋 找到相关签名:\n{signatures[:500]}...")

        # 2. 语义搜索获取完整代码
        search_results = await self.code_indexer.semantic_search(
            query=query,
            top_k=top_k,
            use_vector=True,
            use_keyword=True
        )

        # 3. 提取涉及的文件路径
        related_files = {}
        for chunk in self.code_indexer.chunks:
            # 如果文件路径在搜索结果中被提到
            if chunk.file_path in search_results:
                content = self.code_indexer.get_file_content(chunk.file_path)
                if content:
                    related_files[chunk.file_path] = content

        print(f"   ✅ CodeRAG 找到 {len(related_files)} 个相关文件")
        return related_files

    def load_env_file(self) -> bool:
        """加载 .env 文件中的环境变量"""
        env_path = self.backend_dir / ".env"
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        if key not in os.environ:
                            os.environ[key] = value.strip().strip('"').strip("'")
            return True
        return False

    def check_api_key(self) -> bool:
        """检查 API Key 是否设置"""
        self.load_env_file()

        api_key = (
            os.getenv("MODELSCOPE_API_KEY") or
            os.getenv("OPENAI_API_KEY") or
            os.getenv("LITELLM_API_KEY")
        )

        if not api_key:
            print("❌ 错误: 未设置 API Key")
            print("请在 .env 文件中设置 MODELSCOPE_API_KEY 或 OPENAI_API_KEY")
            return False

        use_modelscope = os.getenv("USE_MODELSCOPE", "false").lower() == "true"
        if use_modelscope:
            print(f"✅ 使用 ModelScope API")
            print(f"   API Base: {os.getenv('MODELSCOPE_API_BASE', 'https://api-inference.modelscope.cn/v1')}")
            print(f"   模型: {os.getenv('DEFAULT_MODEL', 'Qwen/Qwen3.5-122B-A10B')}")
        else:
            print(f"✅ 使用 OpenAI API")

        return True

    def check_docker_available(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def check_docker_image(self, image_name: str = "omniflowai/sandbox:latest") -> bool:
        """检查 Docker 镜像是否存在"""
        try:
            result = subprocess.run(
                ["docker", "images", "-q", image_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            return len(result.stdout.strip()) > 0
        except Exception:
            return False

    def extract_imports_from_content(self, content: str) -> Set[str]:
        """
        使用 AST 分析代码内容，提取所有 import 语句
        
        Returns:
            Set[str]: 导入的模块名集合
        """
        imports = set()
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split('.')[0])
        except SyntaxError:
            pass
        return imports

    def find_file_by_module(self, module_name: str) -> Optional[str]:
        """
        根据模块名查找对应的文件路径
        
        例如: 'app.core.database' -> 'backend/app/core/database.py'
        """
        # 将模块名转换为文件路径
        parts = module_name.split('.')
        
        # 尝试不同的路径组合
        possible_paths = [
            self.backend_dir / Path(*parts) / "__init__.py",
            self.backend_dir / Path(*parts).with_suffix('.py'),
        ]
        
        for path in possible_paths:
            if path.exists():
                rel_path = path.relative_to(self.backend_dir)
                return f"backend/{rel_path}"
        
        return None

    def analyze_dependencies(self, file_content: str, file_path: str) -> List[str]:
        """
        分析文件的依赖关系，返回需要一起发送的相关文件列表
        
        Args:
            file_content: 文件内容
            file_path: 文件路径
            
        Returns:
            List[str]: 相关文件路径列表
        """
        imports = self.extract_imports_from_content(file_content)
        related_files = []
        
        # 项目特定的 import 映射
        project_imports = {
            'app': ['backend/app/main.py', 'backend/app/__init__.py'],
            'main': ['backend/app/main.py'],
            'database': ['backend/app/core/database.py'],
            'config': ['backend/app/core/config.py'],
            'models': ['backend/app/models/__init__.py'],
            'service': ['backend/app/service/__init__.py'],
            'api': ['backend/app/api/__init__.py', 'backend/app/api/v1/__init__.py'],
        }
        
        for imp in imports:
            if imp in project_imports:
                related_files.extend(project_imports[imp])
        
        # 去重并过滤掉自己
        related_files = list(set([f for f in related_files if f != file_path]))
        
        return related_files

    async def get_target_files_with_rag(self, design_output: Dict[str, Any], requirement: str) -> Dict[str, str]:
        """
        使用 CodeRAG (语义检索) 智能获取目标文件
        
        结合:
        1. DesignerAgent 输出的 affected_files
        2. CodeRAG 语义搜索相关代码
        3. AST 分析文件依赖
        
        Args:
            design_output: DesignerAgent 的输出
            requirement: 原始需求描述
            
        Returns:
            Dict[str, str]: 文件路径 -> 文件内容的映射
        """
        target_files = {}
        code_executor = CodeExecutorService(str(self.backend_dir))
        
        # 1. 从 DesignerAgent 输出获取文件
        affected_files = design_output.get("affected_files", [])
        function_changes = design_output.get("function_changes", [])
        
        all_files_to_read = set()
        
        # 添加 affected_files
        for file_path in affected_files:
            all_files_to_read.add(file_path)
        
        # 添加 function_changes 中的文件
        for change in function_changes:
            file_path = change.get("file", "")
            if file_path:
                all_files_to_read.add(file_path)
        
        # 2. 使用 CodeRAG 搜索相关代码
        if not all_files_to_read:
            # 如果没有指定文件，使用 CodeRAG 根据需求搜索
            print(f"   🔍 CodeRAG 根据需求搜索相关代码...")
            rag_files = await self.search_related_code(requirement, top_k=10)
            for file_path, content in rag_files.items():
                # 转换为 backend/ 前缀的路径
                if not file_path.startswith("backend/"):
                    file_path = f"backend/{file_path}"
                all_files_to_read.add(file_path)
                target_files[file_path] = content  # 直接使用 CodeRAG 读取的内容
        
        # 3. 使用 AST 分析依赖关系
        print(f"   🔍 AST 分析文件依赖...")
        for file_path in list(all_files_to_read):
            clean_path = file_path.replace("backend/", "").replace("backend\\", "")
            content = code_executor.get_file_content(clean_path)
            
            if content and file_path not in target_files:
                target_files[file_path] = content
                
                # 分析依赖
                dependencies = self.analyze_dependencies(content, file_path)
                for dep in dependencies:
                    if dep not in target_files:
                        all_files_to_read.add(dep)
        
        # 4. 读取所有收集到的文件
        print(f"   📂 读取 {len(all_files_to_read)} 个文件（含依赖）...")
        for file_path in sorted(all_files_to_read):
            if file_path in target_files:
                continue
                
            clean_path = file_path.replace("backend/", "").replace("backend\\", "")
            content = code_executor.get_file_content(clean_path)
            if content:
                target_files[file_path] = content
                print(f"      ✓ 读取: {file_path}")
            else:
                # 文件不存在，标记为新文件
                target_files[file_path] = "# 新文件"
                print(f"      ✓ 新文件: {file_path}")

        print(f"   📊 共加载 {len(target_files)} 个目标文件")
        return target_files

    def get_target_files_from_design(self, design_output: Dict[str, Any], default_files: List[str] = None) -> Dict[str, str]:
        """
        根据 DesignerAgent 的输出获取目标文件内容（兼容旧版本）
        复用真实流程中的 CodeExecutorService
        使用 AST 分析自动发现依赖文件
        
        Args:
            design_output: DesignerAgent 的输出
            default_files: 如果 design_output 中没有 affected_files，使用默认文件列表
        """
        target_files = {}
        code_executor = CodeExecutorService(str(self.backend_dir))

        # 1. 从 affected_files 获取文件
        affected_files = design_output.get("affected_files", [])
        
        # 如果没有 affected_files 且提供了默认值，使用默认值
        if not affected_files and default_files:
            affected_files = default_files
            print(f"   📂 使用默认文件列表: {default_files}")
        
        # 2. 收集所有需要读取的文件（包括依赖）
        all_files_to_read = set()
        
        for file_path in affected_files:
            all_files_to_read.add(file_path)
            
            # 读取文件内容并分析依赖
            clean_path = file_path.replace("backend/", "").replace("backend\\", "")
            content = code_executor.get_file_content(clean_path)
            
            if content:
                # 使用 AST 分析依赖
                dependencies = self.analyze_dependencies(content, file_path)
                for dep in dependencies:
                    all_files_to_read.add(dep)
        
        # 3. 从 function_changes 获取文件
        function_changes = design_output.get("function_changes", [])
        if function_changes:
            print(f"   📂 从 function_changes 读取文件...")
            for change in function_changes:
                file_path = change.get("file", "")
                if file_path:
                    all_files_to_read.add(file_path)
        
        # 4. 读取所有文件
        print(f"   📂 读取 {len(all_files_to_read)} 个文件（含依赖）...")
        for file_path in sorted(all_files_to_read):
            if file_path in target_files:
                continue
                
            clean_path = file_path.replace("backend/", "").replace("backend\\", "")
            content = code_executor.get_file_content(clean_path)
            if content:
                target_files[file_path] = content
                print(f"      ✓ 读取: {file_path}")
            else:
                # 文件不存在，标记为新文件
                target_files[file_path] = "# 新文件"
                print(f"      ✓ 新文件: {file_path}")

        print(f"   📊 共加载 {len(target_files)} 个目标文件")
        return target_files

    def _build_file_tree(self, max_depth: int = 4) -> Dict[str, Any]:
        """
        构建项目文件树（与后端 ProjectService 保持一致）

        Args:
            max_depth: 最大递归深度

        Returns:
            Dict[str, Any]: 嵌套字典格式的文件树
        """
        # 跳过的目录（与后端保持一致）
        skip_patterns = {'.git', '__pycache__', '.pytest_cache', '.omniflow_index',
                        'node_modules', '.venv', 'venv', '.idea', '.vscode'}
        skip_extensions = {'.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe'}

        def build_node(path: Path, current_depth: int = 0) -> Optional[Dict[str, Any]]:
            """递归构建文件树节点"""
            if not path.exists():
                return None

            # 文件节点
            if not path.is_dir():
                return {
                    "name": path.name,
                    "path": str(path.relative_to(self.backend_dir.parent)),
                    "is_directory": False
                }

            # 目录节点
            node = {
                "name": path.name,
                "path": str(path.relative_to(self.backend_dir.parent)),
                "is_directory": True,
                "children": []
            }

            # 达到最大深度，不再递归
            if current_depth >= max_depth:
                return node

            try:
                for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                    # 跳过隐藏文件和指定模式
                    if item.name.startswith(".") and item.name not in [".env", ".gitignore"]:
                        continue

                    # 跳过指定目录
                    if item.name in skip_patterns:
                        continue

                    # 跳过指定扩展名
                    if item.suffix in skip_extensions:
                        continue

                    child = build_node(item, current_depth + 1)
                    if child:
                        node["children"].append(child)
            except PermissionError:
                pass

            return node

        # 从 backend 目录开始构建
        root_node = build_node(self.backend_dir, current_depth=0)

        if root_node:
            print(f"   📂 构建文件树完成，共 {len(root_node.get('children', []))} 个顶层目录")
            return root_node
        else:
            return {}

    def get_related_test_files(self, affected_files: List[str]) -> Dict[str, str]:
        """
        获取相关的测试文件作为参考
        复用真实流程中的逻辑
        """
        test_files = {}
        code_executor = CodeExecutorService(str(self.backend_dir))

        print(f"   📂 查找相关测试文件...")
        for file_path in affected_files:
            # 提取模块名
            path_parts = file_path.split('/')
            if len(path_parts) < 2:
                continue

            file_name = path_parts[-1]  # calculator.py
            module_name = file_name.replace('.py', '')  # calculator

            # 构建可能的测试文件路径
            possible_test_paths = [
                f"tests/unit/test_{module_name}.py",
                f"tests/unit/test_{module_name}_api.py",
                f"tests/test_{module_name}.py",
            ]

            for test_path in possible_test_paths:
                content = code_executor.get_file_content(test_path)
                if content:
                    full_path = f"backend/{test_path}"
                    test_files[full_path] = content
                    print(f"      ✓ 找到测试文件: {full_path}")
                    break

        print(f"   📊 共找到 {len(test_files)} 个测试文件")
        return test_files

    def prepare_workspace(self, code_files: List[Dict], test_files: List[Dict], target_files: Dict[str, str] = None) -> str:
        """
        准备工作目录，包含生成的代码和项目的测试文件

        【修复 Bug 1】正确顺序：先复制基础文件，再用生成内容覆盖

        返回工作目录路径
        """
        # 创建临时工作目录
        workspace = tempfile.mkdtemp(prefix="omniflow_e2e_")
        print(f"   📁 创建工作目录: {workspace}")

        # 创建 backend 目录结构
        backend_workspace = Path(workspace) / "backend"
        backend_workspace.mkdir(parents=True, exist_ok=True)

        # ========== 第 1 步：复制项目基础文件 ==========
        print(f"   📂 复制项目基础文件...")

        # 复制 pyproject.toml / requirements.txt / main.py（关键！app/main.py 需要它）
        for req_file in ["pyproject.toml", "requirements.txt", "requirements-dev.txt", "main.py"]:
            src = self.backend_dir / req_file
            if src.exists():
                shutil.copy2(src, backend_workspace / req_file)
                print(f"      ✓ {req_file}")

        # 复制 app 目录（原始代码）
        app_src = self.backend_dir / "app"
        app_dst = backend_workspace / "app"
        if app_src.exists():
            shutil.copytree(app_src, app_dst, dirs_exist_ok=True)
            print(f"      ✓ app/ 目录（原始代码）")

        # 复制 tests 目录（原始测试）
        tests_src = self.backend_dir / "tests"
        tests_dst = backend_workspace / "tests"
        if tests_src.exists():
            shutil.copytree(tests_src, tests_dst, dirs_exist_ok=True)
            print(f"      ✓ tests/ 目录（原始测试）")

        # 复制 .env 文件
        env_src = self.backend_dir / ".env"
        if env_src.exists():
            shutil.copy2(env_src, backend_workspace / ".env")
            print(f"      ✓ .env")

        # ========== 第 2 步：写入生成的代码文件（覆盖旧版本）==========
        print(f"   📝 写入生成的代码文件（覆盖旧版本）...")
        for f in code_files:
            file_path = backend_workspace / f['file_path'].replace("backend/", "")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            content = f.get('content')
            change_type = f.get('change_type', 'modify')
            file_path_key = f.get('file_path', '')
            
            # 统一路径格式：将 AI 返回的正斜杠转为系统路径格式进行查找
            file_path_normalized = file_path_key.replace('/', os.sep)
            original = target_files.get(file_path_key, '') or target_files.get(file_path_normalized, '')
            
            if content is None:
                if change_type == 'add':
                    # 新建文件必须有 content
                    raise ValueError(f"文件 {file_path_key} 是新建文件(change_type=add)，必须提供 content 字段")
                elif change_type in ['modify', 'update'] and target_files:
                    # 如果没有 content，尝试使用行号定位替换（数组切片，永不报错）
                    start_line = f.get('start_line')
                    end_line = f.get('end_line')
                    replace_block = f.get('replace_block', '')

                    if start_line and end_line:
                        lines = original.splitlines()
                        # 行号是 1-based 的，转成 0-based 切片
                        # 切片操作：保留前半部分 + 插入新块 + 保留后半部分
                        new_lines = lines[:start_line - 1] + replace_block.splitlines() + lines[end_line:]
                        content = "\n".join(new_lines)
                        print(f"      ✓ {file_path_key} (行号定位替换 {start_line}-{end_line})")
                    elif original:
                        # 兜底：如果没有行号但有原文件内容，保留原文件
                        content = original
                        print(f"      ✓ {file_path_key} (保留原文件内容)")
                    else:
                        raise ValueError(f"文件 {file_path_key} 缺少 start_line 或 end_line，且无法找到原文件内容")
                else:
                    raise ValueError(f"文件 {file_path_key} 无 content 且无法处理(change_type={change_type})")
            
            file_path.write_text(content, encoding='utf-8')
            print(f"      ✓ {f['file_path']}")

        # ========== 第 3 步：写入生成的测试文件（覆盖旧版本）==========
        print(f"   📝 写入生成的测试文件（覆盖旧版本）...")
        for f in test_files:
            file_path = backend_workspace / f['file_path'].replace("backend/", "")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            content = f.get('content', '')
            file_path.write_text(content, encoding='utf-8')
            print(f"      ✓ {f['file_path']}")

        return workspace

    async def _generate_code_and_tests(
        self,
        design_data: Dict[str, Any],
        target_files: Dict[str, str],
        test_files_ref: Dict[str, str],
        feature_description: str,
        attempt: int
    ) -> tuple:
        """
        生成代码和测试

        Returns:
            (code_files, test_files, success)
        """
        print(f"\n📝 Step 3: CoderAgent 生成代码...")
        print(f"   正在调用 LLM，请稍候...")

        coder = CoderAgent()

        # 构建增强的 design_output
        enhanced_design = dict(design_data)
        if test_files_ref:
            enhanced_design["test_files_reference"] = {
                "description": "以下是对应的测试文件内容，供参考（绝对不能修改测试文件）",
                "files": {path: content[:3000] for path, content in test_files_ref.items()}
            }

        # 从所有 target_files 中提取可用的函数和类名
        import re
        available_apis = []
        for file_path, content in target_files.items():
            func_matches = re.findall(r'^(?:async\s+)?def\s+(\w+)\s*\(', content, re.MULTILINE)
            class_matches = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)

            if func_matches or class_matches:
                available_apis.append(f"\n{file_path}:")
                for func in func_matches:
                    available_apis.append(f"  - {func}()")
                for cls in class_matches:
                    available_apis.append(f"  - class {cls}")

        # 添加通用约束
        enhanced_design["coding_constraints"] = {
            "description": "【编码约束】请严格遵守以下规则",
            "rules": [
                "1. 只能使用 target_files 中已定义的函数、类和模块",
                "2. 所有 import 必须基于 target_files 中实际存在的模块路径",
                "3. 禁止假设存在未提供的工具函数或类",
                "4. 保持与现有代码风格一致（命名规范、错误处理等）",
                "5. 如果 target_files 中不存在需要的功能，请实现它而不是假设它存在"
            ],
            "available_apis": available_apis if available_apis else ["请查看 target_files 中的可用 API"]
        }

        # 如果是重试，添加错误上下文
        if attempt > 0:
            enhanced_design["previous_attempt"] = {
                "attempt": attempt,
                "note": "这是第 {} 次尝试，请仔细检查代码并修复之前的问题".format(attempt + 1)
            }

        coder_initial_state = {
            "design_output": enhanced_design,
            "target_files": target_files
        }

        coder_result = await coder.execute(
            pipeline_id=99999,
            stage_name="CODING",
            initial_state=coder_initial_state
        )

        print(f"✅ CoderAgent 执行完成")
        print(f"   成功: {coder_result['success']}")

        if not coder_result['success']:
            return [], [], False

        output = coder_result.get('output', {})
        if isinstance(output, CoderOutput):
            code_files = [{"file_path": f.file_path, "content": f.content} for f in output.files]
        else:
            code_files = output.get('files', [])

        if not code_files:
            print(f"   ❌ CoderAgent 没有生成任何文件")
            return [], [], False

        print(f"   生成 {len(code_files)} 个文件:")
        for f in code_files:
            file_path = f.get('file_path', 'unknown')
            change_type = f.get('change_type', 'modify')
            start_line = f.get('start_line')
            end_line = f.get('end_line')
            if change_type == 'modify' and start_line and end_line:
                # 显示行号定位模式
                replace_preview = f.get('replace_block', '')[:50].replace('\n', ' ')
                print(f"     - {file_path} [{change_type}] 行{start_line}-{end_line}")
                print(f"       replace: {replace_preview}{'...' if len(f.get('replace_block', '')) > 50 else ''}")
            elif change_type == 'add':
                print(f"     - {file_path} [add] (新文件)")
            else:
                print(f"     - {file_path} [{change_type}]")

        self.total_input_tokens += coder_result.get('input_tokens', 0)
        self.total_output_tokens += coder_result.get('output_tokens', 0)

        # 生成测试
        print(f"\n🧪 Step 4: TesterAgent 生成测试...")
        print(f"   正在调用 LLM，请稍候...")

        tester = TesterAgent()

        tester_initial_state = {
            "design_output": design_data,
            "code_output": {
                "files": code_files,
                "summary": f"实现了 {feature_description}"
            }
        }

        tester_result = await tester.execute(
            pipeline_id=99999,
            stage_name="TESTING",
            initial_state=tester_initial_state
        )

        print(f"✅ TesterAgent 执行完成")
        print(f"   成功: {tester_result['success']}")

        if not tester_result['success']:
            return code_files, [], True  # 代码生成成功但测试生成失败

        test_output = tester_result.get('output', {})
        if isinstance(test_output, TesterOutput):
            test_files = [{"file_path": f.file_path, "content": f.content} for f in test_output.test_files]
        else:
            test_files = test_output.get('test_files', [])

        if test_files:
            print(f"   生成 {len(test_files)} 个测试文件:")
            for f in test_files:
                print(f"     - {f['file_path']}")
        else:
            print(f"   未生成测试文件")
            test_files = []

        self.total_input_tokens += tester_result.get('input_tokens', 0)
        self.total_output_tokens += tester_result.get('output_tokens', 0)

        return code_files, test_files, True

    def _prepare_error_context(self, layered_result: LayeredTestResult, code_files: List[Dict]) -> Dict[str, Any]:
        """准备错误上下文供修复使用"""
        error_details = layered_result.error_details or {}
        # 【修复 Bug 2】增加日志截取长度，确保包含完整的错误信息
        logs = error_details.get("logs", "")
        # 优先截取包含 ERROR 或 FAILED 的部分
        if "ERROR" in logs or "FAILED" in logs:
            # 找到第一个 ERROR 或 FAILED 的位置
            error_pos = logs.find("ERROR") if "ERROR" in logs else len(logs)
            failed_pos = logs.find("FAILED") if "FAILED" in logs else len(logs)
            start_pos = min(error_pos, failed_pos)
            # 从错误位置开始截取 3000 字符
            relevant_logs = logs[start_pos:start_pos + 3000]
        else:
            relevant_logs = logs[-3000:]  # 默认截取最后 3000 字符

        return {
            "layer": error_details.get("layer"),
            "message": error_details.get("message"),
            "logs": relevant_logs,
            "failed_tests": error_details.get("failed_tests", []),
            "generated_files": [f["file_path"] for f in code_files]
        }

    async def _apply_fixes(
        self,
        target_files: Dict[str, str],
        code_files: List[Dict],
        error_context: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        应用修复：不污染原始上下文，只把错误记录以特殊文件的形式传给 AI
        """
        print(f"   🔧 收集错误上下文，保持目标文件原样...")

        # ！！！！ 核心修改：绝对不要修改 target_files ！！！！
        # 让 target_files 保持原样，这样 AI 看到的还是未被破坏的代码
        updated_files = dict(target_files)

        # 仅增加一个错误报告给 AI 看
        error_info = f"""# 上次尝试的错误信息

## 失败层级
{error_context.get('layer', 'unknown')}

## 错误描述
{error_context.get('message', '无')}

## 失败的测试
{chr(10).join(error_context.get('failed_tests', [])[:5])}

## 注意
你上次生成的代码测试未通过。
请参考上方原有的目标文件代码（我们已为你恢复到修改前的状态），重新思考并生成正确的修复代码。
"""
        updated_files["ERROR_CONTEXT.md"] = error_info

        return updated_files

    def _display_test_results(self, layered_result: LayeredTestResult):
        """显示测试结果"""
        print(f"\n📊 分层测试结果汇总:")
        print(f"   总层数: {len(layered_result.layers)}")
        print(f"   全部通过: {layered_result.all_passed}")
        if layered_result.failure_cause:
            print(f"   失败原因: {layered_result.failure_cause}")

        if not layered_result.all_passed and layered_result.error_details:
            print(f"\n   📄 详细错误信息:")
            error_details = layered_result.error_details
            print(f"      失败层级: {error_details.get('layer', 'unknown')}")
            print(f"      错误描述: {error_details.get('message', '无')}")

            failed_tests = error_details.get('failed_tests', [])
            if failed_tests:
                print(f"      失败的测试 ({len(failed_tests)} 个):")
                for ft in failed_tests[:5]:
                    print(f"        - {ft}")

    async def run_tests_in_sandbox(
        self,
        workspace_path: str,
        pipeline_id: int = 99999
    ) -> LayeredTestResult:
        """
        在 Docker Sandbox 中运行分层测试

        流程：
        1. 启动 Docker 容器
        2. 在容器中运行 pytest
        3. 解析结果并返回 LayeredTestResult
        """
        print(f"\n   🐳 启动 Docker Sandbox...")

        # 启动沙箱
        try:
            sandbox_info = await sandbox_manager.start(
                pipeline_id=pipeline_id,
                project_path=workspace_path
            )
            print(f"   ✅ Sandbox 已启动")
            print(f"      容器: {sandbox_info.container_id[:12]}")
            print(f"      端口: {sandbox_info.port}")
        except Exception as e:
            print(f"   ❌ 启动 Sandbox 失败: {e}")
            raise

        try:
            # 在容器中运行分层测试
            print(f"\n   🧪 在 Sandbox 中运行分层测试...")

            layers: List[LayerResult] = []

            # Layer 1: 语法检查（在宿主机上做，更快）
            print(f"   \n   📋 Layer 1: 语法检查")
            # 这里我们已经在宿主机上生成了代码，假设语法正确
            # 实际运行时在容器中验证

            # Layer 2-4: 在容器中运行 pytest
            test_commands = [
                ("defense", "tests/unit/defense", "防御性测试"),
                ("regression", "tests/unit", "回归测试"),
                ("new_tests", "tests/ai_generated", "新测试"),
            ]

            for layer_name, test_path, description in test_commands:
                print(f"\n   📋 Layer: {description} ({layer_name})")

                # 检查测试目录是否存在
                check_cmd = f"ls -la /workspace/backend/{test_path} 2>/dev/null | head -5 || echo 'Directory not found'"
                check_result = await sandbox_manager.exec(pipeline_id, check_cmd, timeout=10)

                if "Directory not found" in check_result.stdout or "No such file" in check_result.stderr:
                    print(f"      ⚠️  测试目录不存在，跳过")
                    layers.append(LayerResult(
                        layer=layer_name,
                        passed=True,
                        summary=f"{description}目录不存在，跳过"
                    ))
                    continue

                # 运行 pytest
                pytest_cmd = f"cd /workspace/backend && PYTHONPATH=/workspace/backend python -m pytest {test_path} -v --tb=short -p no:cacheprovider 2>&1"
                print(f"      运行: {pytest_cmd[:80]}...")

                exec_result = await sandbox_manager.exec(pipeline_id, pytest_cmd, timeout=120)

                # 解析结果
                stdout = exec_result.stdout
                stderr = exec_result.stderr
                exit_code = exec_result.exit_code

                # 提取摘要和统计
                import re
                passed_count = 0
                failed_count = 0
                error_count = 0

                # 提取 "X passed"
                passed_match = re.search(r'(\d+) passed', stdout)
                if passed_match:
                    passed_count = int(passed_match.group(1))

                # 提取 "X failed"
                failed_match = re.search(r'(\d+) failed', stdout)
                if failed_match:
                    failed_count = int(failed_match.group(1))

                # 提取 "X error"
                error_match = re.search(r'(\d+) error', stdout)
                if error_match:
                    error_count = int(error_match.group(1))

                # 判断是否通过：exit_code=0 且没有 failed/error
                passed = exit_code == 0 and failed_count == 0 and error_count == 0

                # 生成摘要
                if passed_count > 0:
                    summary = f"{passed_count} 个测试通过"
                elif exit_code == 0:
                    summary = "无测试文件"
                    passed = True
                else:
                    summary = f"测试失败 (exit code: {exit_code})"

                if failed_count > 0:
                    summary += f", {failed_count} 个失败"
                if error_count > 0:
                    summary += f", {error_count} 个错误"

                # 【修复 Bug 2】提取失败的测试（包括 FAILED 和 ERROR）
                failed_tests = []
                # 匹配 FAILED（测试失败）
                if "FAILED" in stdout:
                    for line in stdout.split('\n'):
                        if 'FAILED' in line and '::' in line:
                            test_match = re.search(r'(\S+::\S+)', line)
                            if test_match:
                                failed_tests.append(f"FAILED: {test_match.group(1)}")
                # 匹配 ERROR（collection error，如 ImportError）
                if "ERROR" in stdout:
                    for line in stdout.split('\n'):
                        # 匹配 ERROR collecting tests/xxx.py
                        if line.startswith('ERROR') and 'collecting' in line:
                            error_match = re.search(r'ERROR collecting (\S+)', line)
                            if error_match:
                                failed_tests.append(f"ERROR: {error_match.group(1)}")
                        # 匹配 ERROR tests/xxx.py::test_name
                        elif line.startswith('ERROR') and '::' in line:
                            error_match = re.search(r'(\S+::\S+)', line)
                            if error_match:
                                failed_tests.append(f"ERROR: {error_match.group(1)}")

                # 保存完整日志，只在显示时截断
                full_logs = stdout if stdout else stderr

                layer_result = LayerResult(
                    layer=layer_name,
                    passed=passed,
                    summary=summary,
                    logs=full_logs,  # 保存完整日志
                    failed_tests=failed_tests,
                    error_type="test_failure" if not passed else None
                )
                layers.append(layer_result)

                status = "✅" if passed else "❌"
                print(f"      {status} {summary}")
                if failed_tests:
                    for ft in failed_tests[:3]:  # 只显示前3个
                        print(f"         ❌ {ft}")

                # 临时调试：打印完整测试输出
                if not passed:
                    print(f"\n{'='*40} 完整测试输出 {'='*40}")
                    print(full_logs)
                    print(f"{'='*80}\n")

            # 计算 overall 结果
            all_passed = all(layer.passed for layer in layers)

            # 确定失败原因
            failure_cause = None
            failed_tests = []
            error_details = {}

            for layer in layers:
                if not layer.passed:
                    if layer.layer == "defense":
                        failure_cause = "defense_broken"
                    elif layer.layer == "regression":
                        failure_cause = "regression_broken"
                    elif layer.layer == "new_tests":
                        failure_cause = "code_bug"

                    failed_tests.extend(layer.failed_tests)
                    error_details = {
                        "layer": layer.layer,
                        "message": layer.summary,
                        "logs": layer.logs,
                        "failed_tests": layer.failed_tests
                    }
                    break

            return LayeredTestResult(
                all_passed=all_passed,
                layers=layers,
                failure_cause=failure_cause,
                failed_tests=failed_tests,
                error_details=error_details
            )

        finally:
            # 停止沙箱
            print(f"\n   🛑 停止 Docker Sandbox...")
            await sandbox_manager.stop(pipeline_id)
            print(f"   ✅ Sandbox 已停止")

    async def run_scenario_with_real_llm(self) -> E2ETestResult:
        """
        测试场景: 使用真实 LLM 生成代码和测试，在 Docker Sandbox 中验证

        完整流程: ArchitectAgent → DesignerAgent → CoderAgent → TesterAgent

        需求: 修改已存在的 health check API，添加一个新的状态字段
        """
        print("\n" + "=" * 70)
        print("🧪 测试场景: 使用真实 LLM + Docker Sandbox 完整验证")
        print("=" * 70)
        print("需求: 修改已存在的 health check API，添加数据库连接状态检查")
        print("⚠️  此测试将真正调用 LLM API 并启动 Docker 容器！")
        print()

        start_time = time.time()
        workspace_path = None

        try:
            # ========== Step 1: ArchitectAgent 分析需求 ==========
            print("📋 Step 1: ArchitectAgent 分析需求...")
            print("   正在调用 LLM，请稍候...")

            architect = ArchitectAgent()

            # 动态构建项目文件树（只包含文件结构，不包含代码内容）
            file_tree = self._build_file_tree()

            requirement = "修改 backend/app/api/v1/health.py 文件，在现有的 health check API 中添加数据库连接状态检查。需要检查数据库是否可连接，并在响应中返回 db_status 字段。"

            architect_initial_state = {
                "requirement": requirement,
                "file_tree": file_tree
            }

            architect_result = await architect.execute(
                pipeline_id=99999,
                stage_name="REQUIREMENT",
                initial_state=architect_initial_state
            )

            print(f"✅ ArchitectAgent 执行完成")
            print(f"   成功: {architect_result['success']}")
            print(f"   输入 Tokens: {architect_result.get('input_tokens', 0)}")
            print(f"   输出 Tokens: {architect_result.get('output_tokens', 0)}")
            print(f"   耗时: {architect_result.get('duration_ms', 0)}ms")

            if not architect_result['success']:
                raise Exception(f"ArchitectAgent 失败: {architect_result.get('error')}")

            architect_output = architect_result.get('output', {})
            if isinstance(architect_output, ArchitectOutput):
                feature_description = architect_output.feature_description
                affected_files = architect_output.affected_files
            else:
                feature_description = architect_output.get('feature_description', '计算两数之和')
                affected_files = architect_output.get('affected_files', [])

            print(f"   功能描述: {feature_description}")
            print(f"   受影响文件: {affected_files}")

            self.total_input_tokens += architect_result.get('input_tokens', 0)
            self.total_output_tokens += architect_result.get('output_tokens', 0)

            # ========== Step 2: DesignerAgent 技术设计 ==========
            print("\n🎨 Step 2: DesignerAgent 技术设计...")
            print("   正在调用 LLM，请稍候...")

            designer = DesignerAgent()

            designer_initial_state = {
                "architect_output": architect_output,
                "file_tree": file_tree,
                "related_code_context": {},
                "full_files_context": {}
            }

            designer_result = await designer.execute(
                pipeline_id=99999,
                stage_name="DESIGN",
                initial_state=designer_initial_state
            )

            print(f"✅ DesignerAgent 执行完成")
            print(f"   成功: {designer_result['success']}")
            print(f"   输入 Tokens: {designer_result.get('input_tokens', 0)}")
            print(f"   输出 Tokens: {designer_result.get('output_tokens', 0)}")
            print(f"   耗时: {designer_result.get('duration_ms', 0)}ms")

            if not designer_result['success']:
                raise Exception(f"DesignerAgent 失败: {designer_result.get('error')}")

            designer_output = designer_result.get('output', {})
            if isinstance(designer_output, DesignerOutput):
                design_data = {
                    "architecture": designer_output.technical_design,
                    "api_endpoints": designer_output.api_endpoints,
                    "functions": designer_output.function_changes,
                    "data_models": [],
                    "changes": [designer_output.technical_design]
                }
            else:
                design_data = {
                    "architecture": designer_output.get('technical_design', '简单函数'),
                    "api_endpoints": designer_output.get('api_endpoints', []),
                    "functions": designer_output.get('function_changes', []),
                    "data_models": [],
                    "changes": designer_output.get('affected_files', [])
                }

            print(f"   技术设计: {design_data['architecture'][:100]}...")
            if design_data['api_endpoints']:
                print(f"   API 端点: {len(design_data['api_endpoints'])} 个")

            self.total_input_tokens += designer_result.get('input_tokens', 0)
            self.total_output_tokens += designer_result.get('output_tokens', 0)

            # 获取目标文件内容（使用 CodeRAG 智能检索）
            print("\n📂 获取目标文件内容...")
            # 使用 CodeRAG 根据需求智能搜索相关文件
            target_files = await self.get_target_files_with_rag(design_data, requirement)

            # 获取相关测试文件作为参考
            affected_files = list(target_files.keys())
            test_files_ref = self.get_related_test_files(affected_files)

            # ========== Step 3-7: 代码生成、测试生成、分层测试、ReviewAgent 决策（带 Auto-Fix 循环）==========
            max_retries = 3
            attempt = 0
            layered_result = None
            code_files = []
            test_files = []

            while attempt < max_retries:
                print(f"\n{'='*70}")
                print(f"🔄 Auto-Fix 循环: 第 {attempt + 1}/{max_retries} 次尝试")
                print(f"{'='*70}")

                # 生成代码
                code_files, test_files, success = await self._generate_code_and_tests(
                    design_data, target_files, test_files_ref, feature_description, attempt
                )

                if not success:
                    print(f"   ❌ 代码生成失败，跳过本次尝试")
                    attempt += 1
                    continue

                # 准备工作目录
                print(f"\n🛡️  准备工作目录...")
                workspace_path = self.prepare_workspace(code_files, test_files, target_files)

                # 运行分层测试
                print(f"\n🐳 在 Docker Sandbox 中运行分层测试...")
                layered_result = await self.run_tests_in_sandbox(workspace_path, pipeline_id=99999)

                # ReviewAgent 决策
                print(f"\n🤖 ReviewAgent 决策...")
                decision = ReviewAgent.decide(layered_result, attempt=attempt, max_retries=max_retries)

                print(f"   📋 决策结果:")
                print(f"      action: {decision.action}")
                print(f"      options: {decision.options}")

                if layered_result.all_passed:
                    print(f"\n✅ 所有测试通过！")
                    break

                if decision.action == "auto_fix":
                    print(f"\n🔧 进入 Auto-Fix 模式，分析错误并修复...")
                    # 准备错误上下文供下次代码生成使用
                    error_context = self._prepare_error_context(layered_result, code_files)
                    target_files = await self._apply_fixes(target_files, code_files, error_context)
                    attempt += 1
                elif decision.action == "request_user":
                    # 【修复 Bug 3】在 E2E 测试场景中，如果是 regression 失败，继续尝试修复
                    # 因为可能是生成的代码与旧测试不兼容，需要调整
                    if layered_result.failure_cause == "regression_broken" and attempt < max_retries - 1:
                        print(f"\n🔧 regression 测试失败，尝试调整代码以兼容旧测试...")
                        error_context = self._prepare_error_context(layered_result, code_files)
                        # 添加特殊标记，告诉 CoderAgent 需要兼容旧测试
                        error_context["regression_failure"] = True
                        error_context["note"] = "新代码导致原有测试失败，请检查是否破坏了向后兼容性"
                        target_files = await self._apply_fixes(target_files, code_files, error_context)
                        attempt += 1
                    else:
                        print(f"\n⛔ 需要人工介入，停止 Auto-Fix")
                        break
                else:
                    print(f"\n⚠️  未知决策: {decision.action}")
                    break

            # 显示最终结果
            if layered_result:
                self._display_test_results(layered_result)

            duration = time.time() - start_time

            result = E2ETestResult(
                scenario_name="real_llm_docker_sandbox",
                success=layered_result.all_passed if layered_result else False,
                code_generated=len(code_files) > 0,
                tests_generated=len(test_files) > 0,
                tests_passed=layered_result.all_passed if layered_result else False,
                layered_result=layered_result,
                duration_seconds=duration,
                input_tokens=self.total_input_tokens,
                output_tokens=self.total_output_tokens
            )

            if result.success:
                print(f"\n✅ 场景通过！({duration:.1f}s)")
            else:
                print(f"\n⚠️  场景失败 ({duration:.1f}s)")

            return result

        except Exception as e:
            duration = time.time() - start_time
            print(f"\n❌ 场景异常: {e}")
            import traceback
            traceback.print_exc()

            return E2ETestResult(
                scenario_name="real_llm_docker_sandbox",
                success=False,
                code_generated=False,
                tests_generated=False,
                tests_passed=False,
                error_message=str(e),
                duration_seconds=duration
            )

        finally:
            # 清理工作目录
            if workspace_path and os.path.exists(workspace_path):
                print(f"\n🧹 清理工作目录...")
                shutil.rmtree(workspace_path, ignore_errors=True)
                print(f"   ✅ 已清理: {workspace_path}")

    async def run_all_tests(self) -> bool:
        """运行所有测试场景"""
        print("\n" + "=" * 70)
        print("🚀 端到端集成测试（真实 LLM + Docker Sandbox）")
        print("=" * 70)
        print()
        print("⚠️  警告: 此测试将：")
        print("   1. 真正调用 LLM API，产生费用")
        print("   2. 启动 Docker 容器，需要 Docker 环境")
        print()

        # 检查 API Key
        if not self.check_api_key():
            return False

        # 检查 Docker
        if not self.check_docker_available():
            print("❌ Docker 不可用，请安装 Docker")
            return False
        print("✅ Docker 可用")

        # 检查镜像
        if not self.check_docker_image():
            print("❌ Docker 镜像 'omniflowai/sandbox:latest' 不存在")
            print("请先构建镜像: docker build -t omniflowai/sandbox:latest .")
            return False
        print("✅ Docker 镜像已存在")



        # 运行测试
        result = await self.run_scenario_with_real_llm()
        self.test_results.append(result)

        # 汇总报告
        print("\n" + "=" * 70)
        print("📊 端到端测试结果汇总")
        print("=" * 70)

        passed = sum(1 for r in self.test_results if r.success)
        failed = sum(1 for r in self.test_results if not r.success)

        print(f"✅ 通过: {passed}")
        print(f"❌ 失败: {failed}")
        print(f"📈 通过率: {passed}/{passed + failed} ({passed/(passed+failed)*100:.1f}%)")
        print(f"🔤 总输入 Tokens: {self.total_input_tokens}")
        print(f"🔤 总输出 Tokens: {self.total_output_tokens}")
        print(f"⏱️  总耗时: {sum(r.duration_seconds for r in self.test_results):.1f}s")
        print("=" * 70)

        return failed == 0


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="端到端集成测试（真实 LLM + Docker Sandbox）",
        epilog="""
示例:
  # 运行测试（真实 LLM + Docker）
  python scripts/test_e2e_with_llm_real.py

  # 跳过确认提示（CI/CD 使用）
  python scripts/test_e2e_with_llm_real.py --yes
        """
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过确认提示"
    )

    args = parser.parse_args()

    tester = DockerSandboxTester()

    # 如果指定了 --yes，设置环境变量跳过确认
    if args.yes:
        os.environ["E2E_TEST_SKIP_CONFIRM"] = "1"

    success = asyncio.run(tester.run_all_tests())

    if success:
        print("\n🎉 端到端测试通过！")
        return 0
    else:
        print("\n⚠️  测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
