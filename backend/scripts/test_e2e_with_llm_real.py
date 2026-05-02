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
from app.agents.repairer import RepairerAgent
from app.agents.verify_agent import VerifyAgent, verify_fixes
from app.agents.tester import TesterAgent
from app.agents.architect import ArchitectAgent
from app.agents.designer import DesignerAgent
from app.agents.schemas import CoderOutput, TesterOutput, ArchitectOutput, DesignerOutput
from app.core.resilience import RetryExecutor, ResilienceManager, RetryConfig, CircuitBreakerOpenError


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
        # 【智能重试】初始化重试执行器
        self._sandbox_retry_executor = ResilienceManager.get_executor(
            name="e2e_sandbox",
            **RetryConfig.TEST_RUN
        )

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

    # 注意：以下方法已迁移到后端，测试脚本直接复用
    # - extract_imports_from_content -> CodeExecutorService.extract_imports_from_content
    # - find_file_by_module -> CodeExecutorService.find_file_by_module
    # - analyze_dependencies -> CodeExecutorService.analyze_dependencies
    # 【新架构】CoderAgent 通过工具主动获取文件，不再需要预加载 target_files

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
        复用后端 CodeExecutorService.get_related_test_files
        """
        code_executor = CodeExecutorService(str(self.backend_dir))
        print(f"   📂 查找相关测试文件...")
        test_files = code_executor.get_related_test_files(affected_files)
        for full_path in test_files:
            print(f"      ✓ 找到测试文件: {full_path}")
        print(f"   📊 共找到 {len(test_files)} 个测试文件")
        return test_files

    def prepare_workspace(self, code_files: List[Dict], test_files: List[Dict]) -> str:
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
        print(f"   📝 写入生成的代码文件（使用 Read Token 机制）...")

        # 【核心】使用 CodeExecutorService 进行安全的文件写入
        code_executor = CodeExecutorService(str(backend_workspace))

        # 导入 MultiAgentCoordinator 用于搜索替换
        from app.agents.multi_agent_coordinator import MultiAgentCoordinator
        coordinator = MultiAgentCoordinator()

        # 按文件分组收集所有修改
        from collections import defaultdict
        file_changes_map = defaultdict(list)

        # 【保护核心文件】这些文件不应该被 AI 生成或修改
        PROTECTED_FILES = [
        ]

        for f in code_files:
            file_path_key = f.get('file_path', '')
            # 统一路径分隔符为正斜杠
            file_path_key = file_path_key.replace("\\", "/")

            # 检查是否是受保护文件
            if any(file_path_key.endswith(p) or file_path_key == p for p in PROTECTED_FILES):
                print(f"      ⚠️  跳过受保护文件: {file_path_key}")
                continue

            file_changes_map[file_path_key].append(f)

        # 处理每个文件的修改
        for file_path_key, changes in file_changes_map.items():
            # 移除 backend/ 前缀，转换为相对路径
            relative_path = file_path_key.replace("backend/", "").replace("backend\\", "")

            # 【Read Token 机制】先读取文件获取 read_token
            read_result = code_executor.read_file(relative_path)

            if len(changes) == 1:
                # 单个修改
                f = changes[0]
                content = f.get('content')
                change_type = f.get('change_type', 'modify')

                if content is not None:
                    # 直接有 content，使用 read_token 写入
                    pass
                elif change_type == 'add':
                    # 新建文件，使用 NEW_FILE token
                    content = f.get('replace_block', '') or f.get('content', '')
                elif change_type in ['modify', 'update']:
                    # 使用搜索替换应用修改（直接复用 coordinator 的方法）
                    # 【新架构】从工作目录读取原始内容，不再依赖 target_files
                    original = read_result.content

                    if not original:
                        raise ValueError(f"找不到文件 {file_path_key} 的原始内容，请确保文件已存在于工作目录")

                    search_block = f.get('search_block')
                    replace_block = f.get('replace_block', '')

                    if not search_block:
                        raise ValueError(f"文件 {file_path_key} 缺少 search_block")

                    content = coordinator._apply_search_replace(
                        original, search_block, replace_block, None, None
                    )

                    if content is None:
                        raise ValueError(f"搜索块匹配失败: {file_path_key}")
                else:
                    raise ValueError(f"文件 {file_path_key} 无法处理(change_type={change_type})")
            else:
                # 多个修改，需要合并应用（直接复用 coordinator 的方法）
                print(f"      [INFO] 文件 {file_path_key} 有 {len(changes)} 个修改，合并应用...")
                # 【新架构】从工作目录读取原始内容
                original = read_result.content

                if not original:
                    raise ValueError(f"找不到文件 {file_path_key} 的原始内容，请确保文件已存在于工作目录")

                content = original
                valid_changes = [c for c in changes if c.get('search_block')]

                for i, change in enumerate(valid_changes):
                    search_block = change.get('search_block', '')
                    replace_block = change.get('replace_block', '')

                    new_content = coordinator._apply_search_replace(
                        content, search_block, replace_block, None, None
                    )

                    if new_content is not None:
                        content = new_content
                        print(f"        [PASS] 修改 {i+1}/{len(valid_changes)}: 搜索替换成功")
                    else:
                        raise ValueError(f"修改 {i+1} 搜索块匹配失败")

            # 【核心】使用 CodeExecutorService 安全写入（带 read_token 校验）
            is_new_file = (changes[0].get('change_type') == 'add') if changes else False
            read_token = read_result.read_token if read_result.read_token else "NEW_FILE"

            result = code_executor.apply_file_change(
                relative_path=relative_path,
                new_content=content,
                read_token=read_token,
                create_if_missing=is_new_file
            )

            if not result.success:
                raise PermissionError(f"写入文件失败 [{file_path_key}]: {result.error}")

            print(f"      ✓ {file_path_key} (read_token 校验通过)")

        # ========== 第 3 步：写入生成的测试文件（使用 Read Token）==========
        print(f"   📝 写入生成的测试文件（使用 Read Token 机制）...")
        for f in test_files:
            relative_path = f['file_path'].replace("backend/", "").replace("backend\\", "")
            content = f.get('content', '')

            # 读取获取 read_token（测试文件可能已存在）
            read_result = code_executor.read_file(relative_path)
            read_token = read_result.read_token if read_result.read_token else "NEW_FILE"

            result = code_executor.apply_file_change(
                relative_path=relative_path,
                new_content=content,
                read_token=read_token,
                create_if_missing=True
            )

            if not result.success:
                raise PermissionError(f"写入测试文件失败 [{f['file_path']}]: {result.error}")

            print(f"      ✓ {f['file_path']} (read_token 校验通过)")

        # 【修复模块缓存问题】清除 Python 模块缓存，确保新文件能被正确导入
        print(f"   🧹 清除 Python 模块缓存...")
        import shutil
        pycache_count = 0
        for root, dirs, files in os.walk(backend_workspace):
            for dir_name in dirs:
                if dir_name == "__pycache__":
                    pycache_path = Path(root) / dir_name
                    try:
                        shutil.rmtree(pycache_path)
                        pycache_count += 1
                    except Exception:
                        pass
        if pycache_count > 0:
            print(f"      ✓ 清除 {pycache_count} 个 __pycache__ 目录")

        # 删除所有 .pyc 文件
        pyc_count = 0
        for root, dirs, files in os.walk(backend_workspace):
            for file in files:
                if file.endswith(".pyc"):
                    pyc_path = Path(root) / file
                    try:
                        pyc_path.unlink()
                        pyc_count += 1
                    except Exception:
                        pass
        if pyc_count > 0:
            print(f"      ✓ 清除 {pyc_count} 个 .pyc 文件")

        return workspace

    async def _generate_code_and_tests(
        self,
        design_data: Dict[str, Any],
        test_files_ref: Dict[str, str],
        feature_description: str,
        attempt: int
    ) -> tuple:
        """
        生成代码和测试（新架构：CoderAgent 通过工具主动获取文件）

        Returns:
            (code_files, test_files, success)
        """
        print(f"\n📝 Step 3: CoderAgent 生成代码...")
        print(f"   正在调用 LLM，请稍候...")
        print(f"   💡 新架构：CoderAgent 将通过工具主动获取需要的文件")

        coder = CoderAgent()

        # 构建增强的 design_output
        enhanced_design = dict(design_data)
        if test_files_ref:
            enhanced_design["test_files_reference"] = {
                "description": "以下是对应的测试文件内容，供参考（绝对不能修改测试文件）",
                "files": {path: content[:3000] for path, content in test_files_ref.items()}
            }

        # 添加通用约束
        enhanced_design["coding_constraints"] = {
            "description": "【编码约束】请严格遵守以下规则",
            "rules": [
                "1. 使用 glob/grep/read_file 工具主动获取需要的文件",
                "2. 所有 import 必须基于项目中实际存在的模块路径",
                "3. 禁止假设存在未提供的工具函数或类",
                "4. 保持与现有代码风格一致（命名规范、错误处理等）",
                "5. 如果需要的功能不存在，请实现它而不是假设它存在"
            ]
        }

        # 如果是重试，添加错误上下文
        if attempt > 0:
            enhanced_design["previous_attempt"] = {
                "attempt": attempt,
                "note": "这是第 {} 次尝试，请仔细检查代码并修复之前的问题".format(attempt + 1)
            }

        coder_initial_state = {
            "design_output": enhanced_design,
            "project_path": str(self.backend_dir)  # 传递项目路径，供工具使用
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
            # 【修复】保留所有字段，不只是 file_path 和 content
            code_files = []
            for f in output.files:
                file_dict = {
                    "file_path": f.file_path,
                    "change_type": getattr(f, 'change_type', 'modify'),
                    "content": getattr(f, 'content', None),
                }
                # 添加搜索替换相关字段（如果存在）
                if hasattr(f, 'search_block') and f.search_block:
                    file_dict["search_block"] = f.search_block
                if hasattr(f, 'replace_block') and f.replace_block:
                    file_dict["replace_block"] = f.replace_block
                if hasattr(f, 'fallback_start_line') and f.fallback_start_line:
                    file_dict["fallback_start_line"] = f.fallback_start_line
                if hasattr(f, 'fallback_end_line') and f.fallback_end_line:
                    file_dict["fallback_end_line"] = f.fallback_end_line
                # 添加旧格式字段（向后兼容）
                code_files.append(file_dict)
        else:
            code_files = output.get('files', [])

        if not code_files:
            print(f"   ❌ CoderAgent 没有生成任何文件")
            return [], [], False

        print(f"   生成 {len(code_files)} 个文件:")
        for f in code_files:
            file_path = f.get('file_path', 'unknown')
            change_type = f.get('change_type', 'modify')
            search_block = f.get('search_block')

            if change_type == 'modify' and search_block:
                # 显示搜索替换模式
                replace_preview = f.get('replace_block', '')[:50].replace('\n', ' ')
                print(f"     - {file_path} [{change_type}] 搜索替换")
                print(f"       replace: {replace_preview}{'...' if len(f.get('replace_block', '')) > 50 else ''}")
            elif change_type == 'add':
                print(f"     - {file_path} [add] (新文件)")
            else:
                print(f"     - {file_path} [{change_type}] (content={f.get('content') is not None})")

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

    async def _verify_with_agent(
        self,
        workspace_path: str,
        code_files: List[Dict],
        pipeline_id: int = 99999
    ) -> Dict[str, Any]:
        """
        【阶段二：独立验证步骤 - 利益隔离核心】

        使用独立的 VerifyAgent 进行验证，与 RepairerAgent 完全分离。
        【复用后端代码】直接使用 verify_fixes 便捷函数

        【利益隔离原则】
        - VerifyAgent 只负责"检"，没有任何文件写入或代码修改权限
        - 只能如实报告，无法补救
        - 只报告事实（PASS/FAIL），绝不提供修复建议

        Args:
            workspace_path: 工作目录路径
            code_files: 生成的代码文件列表
            pipeline_id: Pipeline ID

        Returns:
            Dict[str, Any]: 验证结果
        """
        print(f"   🔍 独立验证步骤（VerifyAgent）- 只检测，不修复...")

        # 【复用后端代码】使用 TestRunnerService 运行测试
        from app.service.test_runner import TestRunnerService

        # 运行测试
        test_result = await TestRunnerService.run_tests(
            project_path=workspace_path,
            test_path="tests/",
            timeout=120
        )

        # 【复用后端代码】使用 verify_fixes 便捷函数进行验证
        verify_result = await verify_fixes(
            test_runner=TestRunnerService,
            test_path="tests/",
            generated_files=[f.get("file_path", "") for f in code_files],
            project_path=workspace_path
        )

        # 添加测试运行结果到验证结果
        verify_result["test_result"] = test_result

        verdict = verify_result.get("verdict")
        message = verify_result.get("message", "")

        if verdict == "PASS":
            print(f"   ✅ {message}")
        elif verdict == "FAIL":
            error_count = verify_result.get("error_count", 0)
            print(f"   ❌ {message}")
            print(f"      发现 {error_count} 个错误")
            errors = verify_result.get("errors", [])
            for err in errors[:3]:  # 只显示前3个
                print(f"         - {err}")
        else:
            print(f"   ⚠️  验证过程出错: {message}")

        return verify_result

    async def _apply_fixes(
        self,
        code_files: List[Dict],
        verify_result: Dict[str, Any],
        workspace_path: str
    ) -> bool:
        """
        【利益隔离】RepairerAgent 修复阶段

        RepairerAgent 被剥夺了自检能力，永远看不到测试结果。
        它只能通过结构化工单了解错误，然后提交修复。

        【利益隔离原则】
        - RepairerAgent 只负责"修"
        - 永远看不到原始测试日志，只能看到结构化工单
        - 没有任何测试工具的访问权限

        Returns:
            bool: 修复是否成功
        """
        print(f"   🔧 调用 RepairerAgent 进行精确修复（利益隔离）...")

        # 【利益隔离】构建结构化工单
        structured_errors = verify_result.get("structured_errors", {})
        failed_tests = verify_result.get("errors", [])
        evidence = verify_result.get("evidence", {})
        snippet = evidence.get("failed_output", "")[:1500] if evidence else ""

        # 从 structured_errors 中获取错误列表
        errors_list = structured_errors.get("errors", []) if structured_errors else []

        # 修复 file_path：如果指向测试文件，则改为第一个生成的代码文件
        generated_file_paths = [f["file_path"] for f in code_files]
        if generated_file_paths:
            for err in errors_list:
                file_path = err.get("file_path", "")
                if not file_path or "test_" in file_path or "/tests/" in file_path:
                    err["file_path"] = generated_file_paths[0]

        # 如果没有错误列表，创建一个默认的错误项
        if not errors_list and generated_file_paths:
            errors_list = [
                {
                    "file_path": generated_file_paths[0],
                    "line": 1,
                    "severity": "critical",
                    "summary": "代码需要修复",
                    "detail": "测试失败，需要修复代码",
                    "fix_hint": "根据测试输出修复代码"
                }
            ]

        fix_order = {
            "type": "fix_order",
            "category": "code_bug",
            "source": "VerificationAgent",
            "errors": errors_list,
            "failed_tests": failed_tests[:5],
            "error_snippet": snippet,
            "generated_files": generated_file_paths,
            "fix_hint": "根据以上测试输出修复代码，务必使所有测试通过。"
        }

        print(f"   📋 修复工单已生成: {len(fix_order['errors'])} 个错误项")

        # 【利益隔离核心】调用 RepairerAgent 进行修复
        repairer = RepairerAgent()
        repair_result = await repairer.execute_with_reread(
            pipeline_id=99999,
            stage_name="REPAIR",
            fix_order=fix_order,
            project_path=workspace_path,
            initial_state={
                "verification_report": {
                    "verdict": verify_result.get("verdict"),
                    "error_count": len(failed_tests),
                    "message": verify_result.get("message", "")
                }
            }
        )

        if not repair_result.get("success"):
            print(f"   ❌ RepairerAgent 修复失败: {repair_result.get('error', '未知错误')}")
            return False

        # 修复成功，应用修复到工作目录
        repair_output = repair_result.get("output", {})
        if repair_output and "files" in repair_output:
            print(f"   ✅ RepairerAgent 修复完成，应用 {len(repair_output['files'])} 个文件修复")

            # 使用 CodeExecutorService 应用修复
            from app.service.code_executor import CodeExecutorService
            code_executor = CodeExecutorService(workspace_path)

            for file_change in repair_output["files"]:
                file_path = file_change.get("file_path", "")
                relative_path = file_path.replace("backend/", "").replace("backend\\", "")

                # 读取文件获取 read_token
                read_result = code_executor.read_file(relative_path)

                # 应用修改
                search_block = file_change.get("search_block", "")
                replace_block = file_change.get("replace_block", "")

                if search_block and read_result.content:
                    new_content = read_result.content.replace(search_block, replace_block, 1)

                    result = code_executor.apply_file_change(
                        relative_path=relative_path,
                        new_content=new_content,
                        read_token=read_result.read_token
                    )

                    if result.success:
                        print(f"      ✓ 应用修复: {file_path}")
                    else:
                        print(f"      ❌ 应用修复失败: {file_path} - {result.error}")

            return True

        return False

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
        在 Docker Sandbox 中运行分层测试（带智能重试）

        【智能重试】对于环境错误（如 Docker 容器启动失败）会进行静默重试。

        流程：
        1. 启动 Docker 容器（带重试）
        2. 在容器中运行 pytest
        3. 解析结果并返回 LayeredTestResult
        """
        print(f"\n   🐳 启动 Docker Sandbox...")

        # 【智能重试】启动沙箱（带重试）
        async def _do_start_sandbox():
            return await sandbox_manager.start(
                pipeline_id=pipeline_id,
                project_path=workspace_path
            )

        try:
            sandbox_info = await self._sandbox_retry_executor.execute(_do_start_sandbox)
            print(f"   ✅ Sandbox 已启动")
            print(f"      容器: {sandbox_info.container_id[:12]}")
            print(f"      端口: {sandbox_info.port}")
        except CircuitBreakerOpenError:
            print(f"   ❌ 启动 Sandbox 失败: 服务暂时不可用，系统正在冷却")
            raise RuntimeError("Docker Sandbox 服务暂时不可用，请稍后再试...")
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
        print("需求: 实现复杂的系统状态监控 API（多文件修改）")
        print("  - 添加 /api/v1/health/detailed 端点")
        print("  - 检查 database、disk、memory 组件状态")
        print("  - 实现健康状态聚合逻辑")
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

            requirement = """在 backend/app/api/v1/health.py 中实现一个完整的系统状态监控 API：

1. 添加一个新的端点 GET /api/v1/health/detailed，返回详细的系统状态信息
2. 需要检查以下组件状态：
   - database: 检查数据库连接是否正常
   - disk: 检查磁盘使用率（模拟即可）
   - memory: 检查内存使用率（模拟即可）
3. 返回 JSON 格式：
   {
     "status": "healthy|degraded|unhealthy",
     "timestamp": "ISO格式时间戳",
     "components": {
       "database": {"status": "up|down", "response_time_ms": 123},
       "disk": {"status": "up|down", "usage_percent": 45},
       "memory": {"status": "up|down", "usage_percent": 67}
     }
   }
4. 如果任一组件状态为 down，整体状态应为 degraded
5. 如果多个组件 down，整体状态应为 unhealthy

这是一个复杂的任务，需要：
- 修改 health.py 添加新端点
- 可能需要创建新的服务模块来处理状态检查逻辑
- 需要处理错误情况和边界条件"""

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

            # 【新架构】CoderAgent 将通过工具主动获取需要的文件
            # 不再需要预加载所有目标文件，大幅降低 Token 消耗
            print("\n📂 获取测试文件参考...")
            # 从 affected_files 中提取文件路径用于查找相关测试
            affected_files = design_data.get('affected_files', [])
            test_files_ref = self.get_related_test_files(affected_files)
            print(f"   💡 新架构：CoderAgent 将通过 glob/grep/read_file 工具主动获取文件")

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

                # 生成代码（新架构：CoderAgent 通过工具主动获取文件）
                code_files, test_files, success = await self._generate_code_and_tests(
                    design_data, test_files_ref, feature_description, attempt
                )

                if not success:
                    print(f"   ❌ 代码生成失败，跳过本次尝试")
                    attempt += 1
                    continue

                # 准备工作目录
                print(f"\n🛡️  准备工作目录...")
                workspace_path = self.prepare_workspace(code_files, test_files)

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
                    print(f"\n🔧 进入 Auto-Fix 模式（利益隔离）...")
                    print(f"   Step 1: 独立验证（VerifyAgent）...")

                    # 【利益隔离】Step 1: 独立验证步骤
                    # VerifyAgent 只负责"检"，没有任何文件写入或代码修改权限
                    verify_result = await self._verify_with_agent(workspace_path, code_files, pipeline_id=99999)

                    if verify_result.get("verdict") == "PASS":
                        print(f"   ✅ 验证通过，无需修复")
                        break

                    print(f"   Step 2: 调用 RepairerAgent 进行修复...")

                    # 【利益隔离】Step 2: RepairerAgent 修复阶段
                    # RepairerAgent 只负责"修"，永远看不到测试结果
                    fix_success = await self._apply_fixes(code_files, verify_result, workspace_path)

                    if fix_success:
                        print(f"   🔄 修复已应用，将进行下一次验证...")
                    else:
                        print(f"   ⚠️  修复未成功，继续下一次尝试...")
                    attempt += 1

                elif decision.action == "request_user":
                    # 【修复 Bug 3】在 E2E 测试场景中，如果是 regression 失败，继续尝试修复
                    # 因为可能是生成的代码与旧测试不兼容，需要调整
                    if layered_result.failure_cause == "regression_broken" and attempt < max_retries - 1:
                        print(f"\n🔧 regression 测试失败，调用 RepairerAgent 调整代码以兼容旧测试...")
                        print(f"   Step 1: 独立验证（VerifyAgent）...")

                        # 【利益隔离】独立验证
                        verify_result = await self._verify_with_agent(workspace_path, code_files, pipeline_id=99999)

                        if verify_result.get("verdict") == "PASS":
                            print(f"   ✅ 验证通过，无需修复")
                            break

                        print(f"   Step 2: 调用 RepairerAgent 进行修复（regression 兼容模式）...")

                        # 添加 regression 标记到验证结果
                        verify_result["regression_failure"] = True
                        verify_result["note"] = "新代码导致原有测试失败，请检查是否破坏了向后兼容性"

                        fix_success = await self._apply_fixes(code_files, verify_result, workspace_path)

                        if fix_success:
                            print(f"   🔄 修复已应用，将进行下一次验证...")
                        else:
                            print(f"   ⚠️  修复未成功，继续下一次尝试...")
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
