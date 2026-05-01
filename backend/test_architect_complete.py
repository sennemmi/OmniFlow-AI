"""
ArchitectAgent 完整功能测试脚本

测试内容：
1. ProjectCardBuilder - 项目契约卡生成
2. TokenBudgetAllocator - Token 预算分配
3. AgentTools 三件套工具 - read_chunk / grep_ast / semantic_search
4. ArchitectAgent 完整流程（含真实 LLM 调用）

运行方式：
    cd d:\feishuProj\backend
    python test_architect_complete.py

环境要求：
    - 已配置 LLM API 密钥（OPENAI_API_KEY 或相应环境变量）
    - 后端依赖已安装
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 设置日志
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 导入测试组件
from app.agents.tools import ProjectCardBuilder, AgentTools
from app.agents.token_budget_allocator import TokenBudgetAllocator, estimate_tokens
from app.agents.architect import architect_agent


class ArchitectTester:
    """ArchitectAgent 完整测试器"""

    def __init__(self, project_path: str = None):
        self.project_path = project_path or str(Path(__file__).parent)
        self.agent_tools = AgentTools(self.project_path)
        self.results: Dict[str, Any] = {}

    # =================================================================
    # 测试 1: ProjectCardBuilder
    # =================================================================
    async def test_project_card_builder(self) -> bool:
        """测试项目契约卡生成"""
        print("\n" + "="*60)
        print("🧪 测试 1: ProjectCardBuilder - 项目契约卡生成")
        print("="*60)

        try:
            builder = ProjectCardBuilder(Path(self.project_path))
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

            # 显示前3个符号索引
            if card['symbol_index']:
                print("\n   🔣 符号索引示例:")
                for idx in card['symbol_index'][:3]:
                    symbols = [s['name'] for s in idx.get('symbols', [])[:3]]
                    print(f"      - {idx['file']}: {symbols}")

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
            # 准备测试数据
            project_card = self.results.get('project_card', {
                "entry_points": [{"file": "app/main.py"}, {"file": "app/config.py"}]
            })

            # 模拟已注入的文件内容
            injected_files = {
                "app/main.py": "from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/health')\nasync def health_check():\n    return {'status': 'ok'}\n",
                "app/service/user_service.py": "class UserService:\n    async def get_by_id(self, user_id: int):\n        pass\n    async def create(self, data: dict):\n        pass\n",
                "app/models/user.py": "from sqlmodel import SQLModel\n\nclass User(SQLModel, table=True):\n    id: int\n    name: str\n",
            }

            affected_files = ["app/api/v1/users.py", "app/service/auth_service.py"]

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
            print("\n   📄 分配结果预览:")
            lines = result.splitlines()
            for line in lines[:20]:
                print(f"      {line}")
            if len(lines) > 20:
                print(f"      ... ({len(lines) - 20} 行省略)")

            return True

        except Exception as e:
            logger.error(f"TokenBudgetAllocator 测试失败: {e}")
            print(f"❌ 测试失败: {e}")
            return False

    # =================================================================
    # 测试 3: AgentTools 三件套工具
    # =================================================================
    async def test_agent_tools(self) -> bool:
        """测试 AgentTools 三件套工具"""
        print("\n" + "="*60)
        print("🧪 测试 3: AgentTools 三件套工具")
        print("="*60)

        success = True

        # 3.1 测试 read_chunk
        print("\n   3.1 测试 read_chunk...")
        try:
            # 先找一个存在的文件
            glob_result = self.agent_tools.glob("app/agents/*.py", max_results=5)
            glob_data = json.loads(glob_result)

            if glob_data.get("matches"):
                test_file = glob_data["matches"][0]
                print(f"      测试文件: {test_file}")

                # 模式3: 文件摘要
                result = self.agent_tools.read_chunk(test_file)
                data = json.loads(result)
                assert data.get("mode") == "summary", "摘要模式失败"
                print(f"      ✅ 摘要模式: {data.get('total_lines', 0)} 行")

                # 模式1: 按符号名读取（尝试读取类定义）
                result = self.agent_tools.read_chunk(test_file, symbol_name="ArchitectAgent")
                data = json.loads(result)
                if "symbol" in data:
                    print(f"      ✅ 符号模式: 读取 {data['symbol']} ({data['lines']} 行)")
                else:
                    print(f"      ⚠️ 符号模式: ArchitectAgent 类不存在于 {test_file}")

                # 模式2: 按行号读取
                result = self.agent_tools.read_chunk(test_file, start_line=1, end_line=30)
                data = json.loads(result)
                assert data.get("mode") == "lines", "行号模式失败"
                print(f"      ✅ 行号模式: 读取 {data['start_line']}-{data['end_line']} 行")
            else:
                print("      ⚠️ 未找到测试文件")

        except Exception as e:
            logger.error(f"read_chunk 测试失败: {e}")
            print(f"      ❌ 测试失败: {e}")
            success = False

        # 3.2 测试 grep_ast
        print("\n   3.2 测试 grep_ast...")
        try:
            # 测试 function 搜索
            result = self.agent_tools.grep_ast("analyze", search_type="function", max_results=5)
            data = json.loads(result)
            print(f"      ✅ function 搜索: 找到 {data.get('count', 0)} 个结果")

            # 测试 class 搜索
            result = self.agent_tools.grep_ast("Agent", search_type="class", max_results=5)
            data = json.loads(result)
            print(f"      ✅ class 搜索: 找到 {data.get('count', 0)} 个结果")

            # 测试 text 搜索
            result = self.agent_tools.grep_ast("async def", search_type="text", max_results=5)
            data = json.loads(result)
            print(f"      ✅ text 搜索: 找到 {data.get('count', 0)} 个结果")

            # 显示第一个结果
            if data.get("matches"):
                match = data["matches"][0]
                print(f"\n      📄 示例结果:")
                print(f"         文件: {match.get('file')}")
                print(f"         行号: {match.get('line')}")
                print(f"         内容: {match.get('content', '')[:60]}...")

        except Exception as e:
            logger.error(f"grep_ast 测试失败: {e}")
            print(f"      ❌ 测试失败: {e}")
            success = False

        # 3.3 测试 semantic_search（可选，需要 code_indexer）
        print("\n   3.3 测试 semantic_search...")
        try:
            result = await self.agent_tools.semantic_search("处理用户认证的函数", top_k=3)
            data = json.loads(result)

            if "error" in data:
                print(f"      ⚠️ 语义搜索不可用: {data['error']}")
            else:
                print(f"      ✅ 语义搜索: 找到 {data.get('count', 0)} 个结果")
                print(f"         检索模式: {data.get('retrieval_mode', 'unknown')}")

                if data.get("chunks"):
                    chunk = data["chunks"][0]
                    print(f"\n      📄 示例结果:")
                    print(f"         文件: {chunk.get('file')}")
                    print(f"         名称: {chunk.get('name')}")
                    print(f"         类型: {chunk.get('type')}")

        except Exception as e:
            logger.error(f"semantic_search 测试失败: {e}")
            print(f"      ⚠️ 测试跳过: {e}")

        return success

    # =================================================================
    # 测试 4: ArchitectAgent 完整流程（含真实 LLM）
    # =================================================================
    async def test_architect_agent_full(self) -> bool:
        """测试 ArchitectAgent 完整流程（含真实 LLM）"""
        print("\n" + "="*60)
        print("🧪 测试 4: ArchitectAgent 完整流程（含真实 LLM）")
        print("="*60)

        try:
            # 检查 LLM 配置
            import os
            llm_configured = any(
                os.getenv(key) for key in [
                    "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY",
                    "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"
                ]
            )

            if not llm_configured:
                print("⚠️ 未配置 LLM API 密钥，跳过 LLM 测试")
                print("   请设置以下环境变量之一:")
                print("   - OPENAI_API_KEY")
                print("   - AZURE_OPENAI_API_KEY")
                print("   - ANTHROPIC_API_KEY")
                print("   - DEEPSEEK_API_KEY")
                return False

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
                            "users.py": None
                        }
                    },
                    "service": {
                        "health_service.py": None,
                        "user_service.py": None
                    },
                    "models": {
                        "__init__.py": None,
                        "user.py": None
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
                pipeline_id=99999,  # 测试 pipeline ID
                project_path=self.project_path
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
            logger.error(f"ArchitectAgent 完整流程测试失败: {e}", exc_info=True)
            print(f"\n   ❌ 测试失败: {e}")
            return False

    # =================================================================
    # 运行所有测试
    # =================================================================
    async def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "🚀"*30)
        print("🚀🚀🚀 ArchitectAgent 完整功能测试 🚀🚀🚀")
        print("🚀"*30)
        print(f"\n项目路径: {self.project_path}")

        results = []

        # 测试 1: ProjectCardBuilder
        results.append(("ProjectCardBuilder", await self.test_project_card_builder()))

        # 测试 2: TokenBudgetAllocator
        results.append(("TokenBudgetAllocator", await self.test_token_budget_allocator()))

        # 测试 3: AgentTools 三件套
        results.append(("AgentTools", await self.test_agent_tools()))

        # 测试 4: ArchitectAgent 完整流程
        results.append(("ArchitectAgent", await self.test_architect_agent_full()))

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
    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description="ArchitectAgent 完整功能测试")
    parser.add_argument("--project-path", "-p", default=None, help="项目路径（默认为后端目录）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 测试")
    args = parser.parse_args()

    # 创建测试器
    tester = ArchitectTester(project_path=args.project_path)

    # 运行测试
    all_passed = await tester.run_all_tests()

    # 返回退出码
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
