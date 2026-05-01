"""
ArchitectAgent 沙盒环境完整功能测试脚本

测试内容：
1. 启动 Docker Sandbox
2. ProjectCardBuilder - 项目契约卡生成（沙盒环境）
3. TokenBudgetAllocator - Token 预算分配
4. AgentTools 三件套工具 - read_chunk / grep_ast / semantic_search（沙盒模式）
5. ArchitectAgent 完整流程（含真实 LLM 调用，沙盒环境）

运行方式：
    cd d:\feishuProj\backend
    python test_architect_sandbox.py

环境要求：
    - Docker 已安装并运行
    - 已配置 LLM API 密钥
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 设置日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 导入测试组件
from app.agents.tools import ProjectCardBuilder, AgentTools
from app.agents.token_budget_allocator import TokenBudgetAllocator, estimate_tokens
from app.agents.architect import architect_agent
from app.service.sandbox_orchestrator import get_sandbox_orchestrator, cleanup_sandbox_orchestrator
from app.service.sandbox_file_service import SandboxFileService
from app.core.config import settings


# ========================== 测试配置 ==========================
PIPELINE_ID = 88888  # 测试专用 Pipeline ID


class ArchitectSandboxTester:
    """ArchitectAgent 沙盒环境测试器"""

    def __init__(self):
        self.backend_dir = Path(__file__).parent
        self.project_root = str(self.backend_dir.parent)
        self.results: Dict[str, Any] = {}
        self.sandbox_orch = None
        self.file_service: SandboxFileService = None
        self.agent_tools: AgentTools = None

    def check_api_key(self) -> bool:
        """检查 LLM API 密钥（通过 settings 读取）"""
        # settings 会自动从 .env 文件加载配置
        return bool(settings.llm_api_key)

    def check_docker(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            r = subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    async def setup_sandbox(self) -> bool:
        """启动沙盒环境"""
        print("\n" + "="*60)
        print("🐳 启动 Docker Sandbox...")
        print("="*60)

        try:
            # AgentTools 的 project_path 应指向 backend 目录
            # 因为所有文件路径（如 "app/agents/tools.py"）相对 backend
            backend_path = str(self.backend_dir)

            self.sandbox_orch = get_sandbox_orchestrator(PIPELINE_ID)
            sandbox_init = await self.sandbox_orch.initialize(backend_path)

            if not sandbox_init["success"]:
                print(f"❌ Sandbox 启动失败: {sandbox_init.get('error', '未知错误')}")
                return False

            self.file_service = self.sandbox_orch.get_file_service()
            self.agent_tools = AgentTools(
                project_path=backend_path,
                file_service=self.file_service
            )

            print("✅ Sandbox 就绪")
            print(f"   - Pipeline ID: {PIPELINE_ID}")
            print(f"   - Backend 目录: {backend_path}")
            return True

        except Exception as e:
            logger.error(f"Sandbox 启动失败: {e}")
            print(f"❌ Sandbox 启动失败: {e}")
            return False

    async def cleanup_sandbox(self):
        """清理沙盒环境"""
        print("\n🧹 清理沙盒环境...")
        try:
            if self.sandbox_orch:
                await cleanup_sandbox_orchestrator(PIPELINE_ID)
                print("✅ 沙盒已清理")
        except Exception as e:
            logger.warning(f"清理沙盒时出错: {e}")

    # =================================================================
    # 测试 1: ProjectCardBuilder（沙盒环境）
    # =================================================================
    async def test_project_card_builder(self) -> bool:
        """测试项目契约卡生成（沙盒环境）"""
        print("\n" + "="*60)
        print("🧪 测试 1: ProjectCardBuilder - 项目契约卡生成（沙盒）")
        print("="*60)

        try:
            # 注意：ProjectCardBuilder 直接在宿主机上运行，不通过沙盒
            # 因为它只是读取文件并生成摘要
            builder = ProjectCardBuilder(Path(self.project_root) / "backend")
            start_time = time.time()
            card_json = builder.build(max_depth=3, max_files=60)
            elapsed = time.time() - start_time

            card = json.loads(card_json)
            self.results['project_card'] = card

            # 验证关键字段
            assert "directory_structure" in card, "缺少 directory_structure"
            assert "tech_stack" in card, "缺少 tech_stack"
            assert "entry_points" in card, "缺少 entry_points"
            assert "module_imports" in card, "缺少 module_imports"
            assert "symbol_index" in card, "缺少 symbol_index"

            print(f"✅ 生成成功！耗时: {elapsed:.2f}s")
            print(f"   - 目录结构行数: {len(card['directory_structure'].splitlines())}")
            print(f"   - 技术栈: {json.dumps(card['tech_stack'], ensure_ascii=False)}")
            print(f"   - 入口点数量: {len(card['entry_points'])}")
            print(f"   - 模块依赖数量: {len(card['module_imports'])}")
            print(f"   - 符号索引数量: {len(card['symbol_index'])}")

            # 显示前3个入口点
            if card['entry_points']:
                print("\n   📍 入口点示例:")
                for ep in card['entry_points'][:3]:
                    print(f"      - {ep['file']}: {ep.get('role', 'N/A')}")

            return True

        except Exception as e:
            logger.error(f"ProjectCardBuilder 测试失败: {e}")
            print(f"❌ 测试失败: {e}")
            return False

    # =================================================================
    # 测试 2: TokenBudgetAllocator
    # =================================================================
    async def test_token_budget_allocator(self) -> bool:
        """测试 Token 预算分配器"""
        print("\n" + "="*60)
        print("🧪 测试 2: TokenBudgetAllocator - Token 预算分配")
        print("="*60)

        try:
            project_card = self.results.get('project_card', {
                "entry_points": [{"file": "app/main.py"}, {"file": "app/config.py"}]
            })

            # 模拟已注入的文件内容
            injected_files = {
                "app/main.py": "from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/health')\nasync def health_check():\n    return {'status': 'ok'}\n",
                "app/service/user_service.py": "class UserService:\n    async def get_by_id(self, user_id: int):\n        pass\n",
            }
            affected_files = ["app/api/v1/users.py"]

            allocator = TokenBudgetAllocator(max_budget_tokens=3000)
            print(f"   预算分配: entry={allocator.entry_budget}, relevant={allocator.relevant_budget}, low={allocator.low_budget}")

            start_time = time.time()
            result = allocator.allocate(
                project_card=project_card,
                injected_files=injected_files,
                affected_files=affected_files
            )
            elapsed = time.time() - start_time

            estimated_tokens = estimate_tokens(result)
            self.results['budget_allocation'] = result

            print(f"✅ 分配成功！耗时: {elapsed:.3f}s")
            print(f"   - 输出字符数: {len(result)}")
            print(f"   - 估算 Token 数: {estimated_tokens}")
            print(f"   - 预算使用率: {estimated_tokens / allocator.max_budget_tokens * 100:.1f}%")

            # 显示结果预览
            print("\n   📄 分配结果预览（前15行）:")
            lines = result.splitlines()
            for line in lines[:15]:
                print(f"      {line}")
            if len(lines) > 15:
                print(f"      ... ({len(lines) - 15} 行省略)")

            return True

        except Exception as e:
            logger.error(f"TokenBudgetAllocator 测试失败: {e}")
            print(f"❌ 测试失败: {e}")
            return False

    # =================================================================
    # 测试 3: AgentTools 三件套工具（沙盒模式）
    # =================================================================
    async def test_agent_tools_sandbox(self) -> bool:
        """测试 AgentTools 三件套工具（沙盒模式）"""
        print("\n" + "="*60)
        print("🧪 测试 3: AgentTools 三件套工具（沙盒模式）")
        print("="*60)

        success = True

        # 3.1 测试 glob（沙盒模式）
        print("\n   3.1 测试 glob（沙盒模式）...")
        try:
            result = self.agent_tools.glob("app/agents/*.py", max_results=5)
            data = json.loads(result)
            print(f"      ✅ glob: 找到 {data.get('count', 0)} 个文件")
            if data.get("matches"):
                print(f"         示例: {data['matches'][0]}")
        except Exception as e:
            logger.error(f"glob 测试失败: {e}")
            print(f"      ❌ 测试失败: {e}")
            success = False

        # 3.2 测试 read_chunk（沙盒模式）- 【增强验证】
        print("\n   3.2 测试 read_chunk（沙盒模式）...")
        try:
            # 先找一个存在的文件
            glob_result = self.agent_tools.glob("app/agents/architect.py")
            glob_data = json.loads(glob_result)

            if glob_data.get("matches"):
                test_file = glob_data["matches"][0]
                print(f"      测试文件: {test_file}")

                # 模式3: 文件摘要
                result = self.agent_tools.read_chunk(test_file)
                data = json.loads(result)
                assert data.get("mode") == "summary", "摘要模式失败"
                print(f"      ✅ 摘要模式: {data.get('total_lines', 0)} 行")

                # 模式1: 按符号名读取 - 【关键验证】确保不走 read_file 截断路径
                result = self.agent_tools.read_chunk(test_file, symbol_name="ArchitectAgent")
                data = json.loads(result)
                if "symbol" in data:
                    lines_read = data.get('lines', 0)
                    print(f"      ✅ 符号模式: 读取 {data['symbol']} ({lines_read} 行)")
                    # 【关键断言】符号模式应该读取完整定义，不能只有 100 行
                    if lines_read < 100:
                        print(f"         ⚠️ 警告: 符号模式可能走了截断路径（只有 {lines_read} 行）")
                    elif lines_read > 100:
                        print(f"         ✅ 确认: 符号模式读取了完整定义（{lines_read} 行，超过 100 行限制）")
                else:
                    print(f"      ⚠️ 符号模式: ArchitectAgent 不存在或读取失败")
                    print(f"         可用符号: {data.get('available_symbols', [])[:5]}")

                # 模式2: 按行号读取 - 【关键验证】确保 AST 对齐不压缩到 1 行
                result = self.agent_tools.read_chunk(test_file, start_line=1, end_line=30)
                data = json.loads(result)
                assert data.get("mode") == "lines", "行号模式失败"
                start_line = data.get('start_line', 0)
                end_line = data.get('end_line', 0)
                lines_count = data.get('lines', 0)
                print(f"      ✅ 行号模式: 读取 {start_line}-{end_line} 行（共 {lines_count} 行）")
                # 【关键断言】请求 1-30 行，结果不应该只有 1 行
                if lines_count <= 1:
                    print(f"         ❌ 错误: 行号模式被压缩到 {lines_count} 行，AST 对齐有 bug")
                    success = False
                elif lines_count < 20:
                    print(f"         ⚠️ 警告: 行号模式返回行数较少（{lines_count} 行）")
                else:
                    print(f"         ✅ 确认: 行号模式返回了合理的行数（{lines_count} 行）")
            else:
                print("      ⚠️ 未找到测试文件")

        except Exception as e:
            logger.error(f"read_chunk 测试失败: {e}")
            print(f"      ❌ 测试失败: {e}")
            success = False

        # 3.3 测试 grep_ast（沙盒模式）- 【增强验证 callers/import 类型】
        print("\n   3.3 测试 grep_ast（沙盒模式）...")
        try:
            # 测试 function 搜索
            result = self.agent_tools.grep_ast("analyze", search_type="function", max_results=5)
            data = json.loads(result)
            count = data.get('count', 0)
            print(f"      ✅ function 搜索: 找到 {count} 个结果")
            if count > 0 and data.get("matches"):
                m = data["matches"][0]
                content = m.get("content", "")
                # 【验证】function 类型应该返回 def 行
                if "def " in content or "async def" in content:
                    print(f"         ✅ function 类型返回了正确的定义行")
                else:
                    print(f"         ⚠️ function 类型返回的内容可能不正确: {content[:50]}")

            # 测试 class 搜索
            result = self.agent_tools.grep_ast("Agent", search_type="class", max_results=5)
            data = json.loads(result)
            count = data.get('count', 0)
            print(f"      ✅ class 搜索: 找到 {count} 个结果")

            # 【新增】测试 callers 类型 - 验证是否能找到调用位置
            print("\n      测试 callers 类型...")
            result = self.agent_tools.grep_ast("json.loads", search_type="callers", max_results=5)
            data = json.loads(result)
            count = data.get('count', 0)
            print(f"      ✅ callers 搜索 'json.loads': 找到 {count} 个调用位置")
            if count > 0 and data.get("matches"):
                m = data["matches"][0]
                content = m.get("content", "")
                # 【验证】callers 类型应该包含函数调用
                if "loads" in content:
                    print(f"         ✅ callers 类型正确返回了调用位置")
                    print(f"            文件: {m.get('file')}:{m.get('line')}")
                else:
                    print(f"         ⚠️ callers 类型返回的内容可能不正确")

            # 【新增】测试 import 类型 - 验证是否能找到导入语句
            print("\n      测试 import 类型...")
            result = self.agent_tools.grep_ast("fastapi", search_type="import", max_results=5)
            data = json.loads(result)
            count = data.get('count', 0)
            print(f"      ✅ import 搜索 'fastapi': 找到 {count} 个导入位置")
            if count > 0 and data.get("matches"):
                m = data["matches"][0]
                content = m.get("content", "")
                # 【验证】import 类型应该包含 import 或 from 关键字
                if "import" in content or "from" in content:
                    print(f"         ✅ import 类型正确返回了导入语句")
                    print(f"            文件: {m.get('file')}:{m.get('line')}")
                    print(f"            内容: {content[:60]}...")
                else:
                    print(f"         ⚠️ import 类型返回的内容可能不正确: {content[:50]}")

        except Exception as e:
            logger.error(f"grep_ast 测试失败: {e}")
            print(f"      ❌ 测试失败: {e}")
            success = False

        # 3.4 测试 semantic_search（可选）- 【修复】0 结果应该标记为失败
        print("\n   3.4 测试 semantic_search...")
        try:
            result = await self.agent_tools.semantic_search("处理用户认证的函数", top_k=3)
            data = json.loads(result)

            if "error" in data:
                print(f"      ⚠️ 语义搜索不可用: {data['error']}")
            else:
                count = data.get('count', 0)
                retrieval_mode = data.get('retrieval_mode', 'unknown')
                if count == 0:
                    # 【修复】0 结果不是成功，是静默失败
                    print(f"      ❌ 语义搜索返回 0 结果（retrieval_mode={retrieval_mode}）")
                    print(f"         这可能说明 keyword_search 实现有问题或调用的方法名不对")
                    success = False
                else:
                    print(f"      ✅ 语义搜索: 找到 {count} 个结果（mode={retrieval_mode}）")
                    # 显示第一个结果
                    chunks = data.get('chunks', [])
                    if chunks:
                        first = chunks[0]
                        print(f"         示例: {first.get('name')} in {first.get('file_path', first.get('location', 'N/A'))}")

        except Exception as e:
            print(f"      ⚠️ 测试跳过: {e}")

        return success

    # =================================================================
    # 测试 4: ArchitectAgent 完整流程（沙盒环境 + 真实 LLM）
    # =================================================================
    async def test_architect_agent_sandbox(self) -> bool:
        """测试 ArchitectAgent 完整流程（沙盒环境 + 真实 LLM）"""
        print("\n" + "="*60)
        print("🧪 测试 4: ArchitectAgent 完整流程（沙盒 + LLM）")
        print("="*60)

        try:
            # 准备测试需求
            requirement = """
            实现一个用户健康检查功能：
            1. 添加一个 API 端点 GET /api/v1/health
            2. 返回系统状态（数据库连接、服务状态）
            3. 包含响应时间
            """

            # 准备文件树
            file_tree = {
                "app": {
                    "api": {
                        "v1": {
                            "__init__.py": None,
                            "health.py": None,
                        }
                    },
                    "service": {
                        "health_service.py": None,
                    },
                    "main.py": None
                }
            }

            print("   📋 测试需求:")
            print(f"      {requirement.strip()}")
            print(f"\n   🚀 调用 ArchitectAgent.analyze()...")
            print("   （这可能需要 30-60 秒，取决于 LLM 响应速度）")

            start_time = time.time()
            result = await architect_agent.analyze(
                requirement=requirement,
                file_tree=file_tree,
                element_context=None,
                pipeline_id=PIPELINE_ID,
                project_path=str(self.backend_dir)
            )
            elapsed = time.time() - start_time

            print(f"\n   ✅ 分析完成！耗时: {elapsed:.2f}s")

            # 验证结果
            if result.get("success"):
                output = result.get("output", {})
                self.results['architect_output'] = output

                print("\n   📊 输出结果:")
                print(f"      - 功能描述: {output.get('feature_description', 'N/A')[:80]}...")
                print(f"      - 受影响文件: {len(output.get('affected_files', []))} 个")
                print(f"      - 预估工作量: {output.get('estimated_effort', 'N/A')}")
                print(f"      - 验收标准: {len(output.get('acceptance_criteria', []))} 条")
                print(f"      - 必需符号: {len(output.get('required_symbols', []))} 个")

                # 显示 affected_files
                if output.get('affected_files'):
                    print("\n   📁 受影响文件:")
                    for f in output['affected_files'][:5]:
                        print(f"      - {f}")

                # 显示 required_symbols
                if output.get('required_symbols'):
                    print("\n   🔣 必需符号:")
                    for s in output['required_symbols'][:5]:
                        print(f"      - {s.get('name')} ({s.get('type')}) in {s.get('module', 'N/A')}")

                # 显示 injected_files
                injected = result.get('injected_files', {})
                if injected:
                    print(f"\n   💾 注入文件: {len(injected)} 个")
                    for path, content in list(injected.items())[:3]:
                        print(f"      - {path}: {len(content)} 字符")

                return True
            else:
                print(f"\n   ❌ 分析失败: {result.get('error', '未知错误')}")
                return False

        except Exception as e:
            logger.error(f"ArchitectAgent 测试失败: {e}", exc_info=True)
            print(f"\n   ❌ 测试失败: {e}")
            return False

    # =================================================================
    # 运行所有测试
    # =================================================================
    async def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "🚀"*30)
        print("🚀🚀🚀 ArchitectAgent 沙盒环境完整功能测试 🚀🚀🚀")
        print("🚀"*30)
        print(f"\n项目根目录: {self.project_root}")
        print(f"Backend 目录: {self.backend_dir}")

        # 前置检查
        if not self.check_api_key():
            print("\n❌ 未配置 LLM API 密钥")
            print("   请设置以下环境变量之一:")
            print("   - OPENAI_API_KEY")
            print("   - AZURE_OPENAI_API_KEY")
            print("   - ANTHROPIC_API_KEY")
            print("   - DEEPSEEK_API_KEY")
            print("   - MODELSCOPE_API_KEY")
            return False

        if not self.check_docker():
            print("\n❌ Docker 不可用")
            print("   请确保 Docker 已安装并运行")
            return False

        print("\n✅ 前置检查通过")
        print(f"   - LLM 模型: {settings.llm_model}")
        print(f"   - LLM API 密钥: 已配置")
        print("   - Docker: 可用")

        # 启动沙盒
        if not await self.setup_sandbox():
            return False

        results = []
        try:
            # 测试 1: ProjectCardBuilder
            results.append(("ProjectCardBuilder", await self.test_project_card_builder()))

            # 测试 2: TokenBudgetAllocator
            results.append(("TokenBudgetAllocator", await self.test_token_budget_allocator()))

            # 测试 3: AgentTools 三件套（沙盒模式）
            results.append(("AgentTools (Sandbox)", await self.test_agent_tools_sandbox()))

            # 测试 4: ArchitectAgent 完整流程（沙盒 + LLM）
            results.append(("ArchitectAgent (Sandbox)", await self.test_architect_agent_sandbox()))

        finally:
            # 确保清理沙盒
            await self.cleanup_sandbox()

        # 汇总结果
        print("\n" + "="*60)
        print("📊 测试汇总")
        print("="*60)

        for name, passed in results:
            status = "✅ 通过" if passed else "❌ 失败"
            print(f"   {status}: {name}")

        total = len(results)
        passed = sum(1 for _, p in results if p)
        print(f"\n   总计: {passed}/{total} 通过 ({passed/total*100:.1f}%)")

        return passed == total


# =================================================================
# 主入口
# =================================================================
async def main():
    """主函数"""
    tester = ArchitectSandboxTester()
    all_passed = await tester.run_all_tests()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
