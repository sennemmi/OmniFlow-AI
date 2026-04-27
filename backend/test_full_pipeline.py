"""
全链路测试脚本 - 测试 OmniFlowAI 完整 Pipeline

测试流程：
1. ArchitectAgent - 需求分析
2. 两层代码上下文检索
3. DesignerAgent - 技术设计（带代码上下文）
4. CoderAgent - 代码生成
5. TestAgent - 测试生成
6. 打印各阶段的提示词和返回结果

注意：此脚本仅用于测试，不会实际提交代码或创建 PR
"""
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent))

# 设置日志级别
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def print_section(title: str, content: str = "", border: str = "="):
    """打印带边框的章节"""
    width = 80
    print(f"\n{border * width}")
    print(f" {title}")
    print(f"{border * width}")
    if content:
        print(content)


def print_json(data: Dict[str, Any], indent: int = 2):
    """打印格式化的 JSON"""
    print(json.dumps(data, indent=indent, ensure_ascii=False))


def print_prompt(title: str, system_prompt: str, user_prompt: str):
    """打印提示词"""
    print_section(title, border="-")
    print("📝 SYSTEM PROMPT:")
    print("-" * 80)
    print(system_prompt[:1500] if len(system_prompt) > 1500 else system_prompt)
    if len(system_prompt) > 1500:
        print(f"\n... (省略 {len(system_prompt) - 1500} 字符)")
    
    print("\n\n📝 USER PROMPT:")
    print("-" * 80)
    print(user_prompt[:3000] if len(user_prompt) > 3000 else user_prompt)
    if len(user_prompt) > 3000:
        print(f"\n... (省略 {len(user_prompt) - 3000} 字符)")


class MockLLMRecorder:
    """模拟 LLM 调用，记录提示词和返回结果"""
    
    def __init__(self):
        self.calls: list[dict] = []
    
    def record(self, agent_name: str, system_prompt: str, user_prompt: str, response: str, success: bool = True):
        """记录一次 LLM 调用"""
        self.calls.append({
            "agent": agent_name,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": response,
            "success": success
        })
    
    def print_summary(self):
        """打印调用摘要"""
        print_section("📊 LLM 调用摘要")
        for i, call in enumerate(self.calls, 1):
            status = "✅" if call["success"] else "❌"
            print(f"{status} 调用 {i}: {call['agent']}")
            print(f"   用户提示词长度: {len(call['user_prompt'])} 字符")
            print(f"   返回结果长度: {len(call['response'])} 字符")


# 全局记录器
llm_recorder = MockLLMRecorder()


async def step1_architect_agent() -> Dict[str, Any]:
    """
    步骤 1: ArchitectAgent - 需求分析
    """
    print_section("步骤 1: ArchitectAgent - 需求分析")
    
    from app.agents.architect import architect_agent
    from app.service.project import get_current_project_tree, ProjectService
    
    # 模拟用户需求
    requirement = "添加用户认证功能，包括用户登录、注册和 JWT Token 验证"
    element_context = None
    
    print(f"📋 用户需求: {requirement}")
    
    # 获取项目文件树
    file_tree_node = get_current_project_tree(max_depth=4)
    file_tree = ProjectService.file_tree_to_dict(file_tree_node) if file_tree_node else {}
    
    print(f"📁 项目文件树节点数: {len(file_tree)}")
    
    # 调用 ArchitectAgent
    print("\n🤖 调用 ArchitectAgent...")
    
    # 为了记录提示词，我们手动构建并打印
    file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
    user_prompt = f"""【用户需求】
{requirement}

【项目文件树】
```
{file_tree_str}
```

请根据以上信息，输出结构化的技术设计方案（JSON 格式）。
"""
    
    print_prompt("ArchitectAgent 提示词", architect_agent.SYSTEM_PROMPT, user_prompt)
    
    result = await architect_agent.analyze(requirement, file_tree, element_context)
    
    if result["success"]:
        print("\n✅ ArchitectAgent 执行成功!")
        print("\n📋 输出结果:")
        print_json(result["output"])
        
        # 记录调用
        llm_recorder.record(
            "ArchitectAgent",
            architect_agent.SYSTEM_PROMPT,
            user_prompt,
            json.dumps(result["output"], ensure_ascii=False)
        )
    else:
        print(f"\n❌ ArchitectAgent 执行失败: {result['error']}")
    
    return result


async def step2_code_context(architect_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    步骤 2: 两层代码上下文检索
    """
    print_section("步骤 2: 两层代码上下文检索")
    
    from app.service.code_indexer import get_indexer, clear_indexer_cache
    from app.core.config import settings
    
    # 获取项目路径
    project_path = settings.TARGET_PROJECT_PATH
    if not Path(project_path).is_absolute():
        backend_dir = Path(__file__).parent
        project_path = str(backend_dir.parent / project_path)
    
    print(f"📁 项目路径: {project_path}")
    
    # 获取索引服务
    indexer = get_indexer(project_path)
    print("✅ 索引服务初始化成功")
    
    # 构建检索查询
    search_query = architect_output.get("feature_description", "")
    if architect_output.get("affected_files"):
        search_query += " " + " ".join(architect_output["affected_files"])
    
    print(f"\n🔍 检索查询: {search_query[:100]}...")
    
    # 【第一层】语义检索
    print_section("第一层: 语义检索结果 (RAG)", border="-")
    related_code = await indexer.semantic_search(
        query=search_query,
        top_k=5,
        chunk_types=["function", "class", "method"]
    )
    print(related_code[:2000] if len(related_code) > 2000 else related_code)
    if len(related_code) > 2000:
        print(f"\n... (省略 {len(related_code) - 2000} 字符)")
    
    # 【第二层】完整文件内容
    print_section("第二层: 完整文件内容", border="-")
    context_result = await indexer.get_related_files_full_content(
        query=search_query,
        top_k=5,
        include_related=True
    )
    
    print(f"✅ 核心文件数: {len(context_result['full_files'])}")
    print(f"✅ 相关文件数: {len(context_result['related_files'])}")
    print(f"✅ 文件摘要数: {len(context_result['file_summaries'])}")
    
    # 显示文件摘要
    print("\n📄 文件摘要:")
    for summary in context_result['file_summaries']:
        print(f"  - {summary['file_path']} ({summary['total_lines']} 行)")
    
    # 显示完整文件内容（前 30 行）
    print("\n📖 完整文件内容预览:")
    full_files_context = {}
    for file_path, content in list(context_result['full_files'].items())[:3]:
        lines = content.splitlines()
        preview = "\n".join(lines[:30])
        if len(lines) > 30:
            preview += f"\n... ({len(lines) - 30} 行省略)"
        
        print(f"\n--- 文件: {file_path} ---")
        print(preview)
        
        # 保存完整内容用于后续步骤
        full_files_context[file_path] = content
    
    # 合并相关文件
    full_files_context.update(context_result.get('related_files', {}))
    
    # 获取项目结构摘要
    project_structure = indexer.get_project_structure()
    print(f"\n📊 {project_structure}")
    
    return {
        "related_code": related_code,
        "full_files_context": full_files_context,
        "project_structure": project_structure
    }


async def step3_designer_agent(
    architect_output: Dict[str, Any],
    code_context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    步骤 3: DesignerAgent - 技术设计
    """
    print_section("步骤 3: DesignerAgent - 技术设计")
    
    from app.agents.designer import designer_agent
    from app.service.project import get_current_project_tree, ProjectService
    
    related_code = code_context["related_code"]
    full_files_context = code_context["full_files_context"]
    
    # 获取项目文件树
    file_tree_node = get_current_project_tree(max_depth=4)
    file_tree = ProjectService.file_tree_to_dict(file_tree_node) if file_tree_node else {}
    
    # 构建提示词（模拟 DesignerAgent._build_prompt）
    architect_str = json.dumps(architect_output, indent=2, ensure_ascii=False)
    file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
    
    # 构建代码上下文部分
    code_context_section = ""
    
    # 第一层：语义检索结果
    if related_code:
        code_context_section += f"""
【相关代码片段 - 语义检索结果】
以下是通过 RAG 检索到的与需求相关的代码片段：

{related_code}
"""
    
    # 第二层：完整文件内容
    if full_files_context:
        files_content = []
        for file_path, content in full_files_context.items():
            # 限制每个文件的内容长度
            max_content_length = 3000
            truncated_content = content[:max_content_length]
            if len(content) > max_content_length:
                truncated_content += f"\n... (文件剩余 {len(content) - max_content_length} 字符已省略)"
            
            files_content.append(f"""--- 文件: {file_path} ---
```python
{truncated_content}
```""")
        
        full_files_str = "\n\n".join(files_content)
        code_context_section += f"""
【完整文件内容】
以下是相关文件的完整内容（用于理解代码风格和架构）：

{full_files_str}
"""
    
    # 完整的用户提示词
    user_prompt = f"""【ArchitectAgent 输出】
{architect_str}

【项目文件树】
```
{file_tree_str}
```
{code_context_section}

请根据以上信息，输出详细的技术设计方案（JSON 格式）。
注意参考 backend/app/api/ 目录下的现有 API 风格，优先复用现有接口和模式。
"""
    
    print_prompt("DesignerAgent 提示词", designer_agent.SYSTEM_PROMPT, user_prompt)
    
    # 调用 DesignerAgent
    print("\n🤖 调用 DesignerAgent...")
    result = await designer_agent.design(
        architect_output=architect_output,
        related_code_context=related_code,
        full_files_context=full_files_context
    )
    
    if result["success"]:
        print("\n✅ DesignerAgent 执行成功!")
        print("\n📋 技术设计方案:")
        print_json(result["output"])
        
        # 记录调用
        llm_recorder.record(
            "DesignerAgent",
            designer_agent.SYSTEM_PROMPT,
            user_prompt,
            json.dumps(result["output"], ensure_ascii=False)
        )
        
        # 验证输出包含 affected_files
        if "affected_files" in result["output"]:
            print(f"\n✅ affected_files 字段存在: {result['output']['affected_files']}")
        else:
            print("\n⚠️ affected_files 字段不存在")
    else:
        print(f"\n❌ DesignerAgent 执行失败: {result['error']}")
    
    return result


async def step4_coder_agent(
    design_output: Dict[str, Any],
    full_files_context: Dict[str, str]
) -> Dict[str, Any]:
    """
    步骤 4: CoderAgent - 代码生成
    """
    print_section("步骤 4: CoderAgent - 代码生成")
    
    from app.agents.coder import coder_agent
    from app.service.agent_coordinator import AgentCoordinatorService
    from app.service.code_executor import CodeExecutorService
    from app.core.config import settings
    from pathlib import Path
    
    # 使用 AgentCoordinatorService 的逻辑获取目标文件
    target_files = {}
    
    def normalize_path(p: str) -> str:
        """统一路径格式，移除 backend/ 前缀"""
        if p.startswith("backend/") or p.startswith("backend\\"):
            p = p[len("backend/"):]
        return p
    
    # 获取目标项目路径
    target_path = Path(settings.TARGET_PROJECT_PATH)
    if not target_path.is_absolute():
        backend_dir = Path(__file__).parent
        target_path = backend_dir.parent / settings.TARGET_PROJECT_PATH
    
    code_executor = CodeExecutorService(str(target_path))
    
    # 1. 从 affected_files 获取文件
    affected_files = design_output.get("affected_files", [])
    for file_path in affected_files:
        file_path = normalize_path(file_path)
        if file_path not in target_files:
            content = code_executor.get_file_content(file_path)
            if content:
                target_files[file_path] = content
    
    # 2. 从 function_changes 获取文件（兼容旧格式）
    function_changes = design_output.get("function_changes", [])
    for change in function_changes:
        file_path = change.get("file", "")
        if file_path:
            file_path = normalize_path(file_path)
            if file_path not in target_files:
                content = code_executor.get_file_content(file_path)
                if content:
                    target_files[file_path] = content
    
    # === 新增：补充关键上下文文件 ===
    # 如果 affected_files 中包含 modify 类型的文件，无论如何要强制读取它们
    for change in function_changes:
        file_path = change.get("file", "")
        action = change.get("action", "").lower()
        if action in ("modify", "update"):
            file_path = normalize_path(file_path)
            if file_path not in target_files:
                content = code_executor.get_file_content(file_path)
                if content:
                    target_files[file_path] = content
                else:
                    print(f"  ⚠️ [修改] 目标文件不存在，将创建新文件: {file_path}")
    
    # 3. 如果仍然没有找到文件，使用 full_files_context 中的前几个作为 fallback
    if not target_files and full_files_context:
        target_files = dict(list(full_files_context.items())[:3])
        print("  ⚠️ 未从项目中读取到文件，使用语义检索的上下文作为 fallback")
    
    print(f"📁 目标文件数: {len(target_files)}")
    for file_path in target_files.keys():
        print(f"  - {file_path}")
    
    # 构建提示词
    design_str = json.dumps(design_output, indent=2, ensure_ascii=False)
    
    files_content = []
    for file_path, content in target_files.items():
        files_content.append(f"""【文件: {file_path}】
```python
{content}
```""")
    
    files_str = "\n\n".join(files_content)
    
    user_prompt = f"""【技术设计方案】
{design_str}

【目标文件当前内容】
{files_str}

请根据技术设计方案，生成需要修改或新增的代码。
注意保持原有代码的缩进风格、注释风格和架构分层。
输出完整的文件内容（不是 diff 格式）。
"""
    
    print_prompt("CoderAgent 提示词", coder_agent.SYSTEM_PROMPT, user_prompt)
    
    # 调用 CoderAgent
    print("\n🤖 调用 CoderAgent...")
    result = await coder_agent.generate_code(
        design_output=design_output,
        target_files=target_files,
        pipeline_id=999  # 测试用的 pipeline_id
    )
    
    if result["success"]:
        print("\n✅ CoderAgent 执行成功!")
        print(f"\n📋 生成的文件数: {len(result['output'].get('files', []))}")
        
        # 打印生成的文件
        for file_info in result["output"].get("files", [])[:3]:
            print(f"\n📄 文件: {file_info.get('file_path')}")
            print(f"   变更类型: {file_info.get('change_type', 'modify')}")
            print(f"   描述: {file_info.get('description', 'N/A')}")
            content = file_info.get('content', '')
            preview = "\n".join(content.splitlines()[:20])
            print(f"   内容预览:\n{preview}")
            if len(content.splitlines()) > 20:
                print(f"   ... ({len(content.splitlines()) - 20} 行省略)")
        
        # 记录调用
        llm_recorder.record(
            "CoderAgent",
            coder_agent.SYSTEM_PROMPT,
            user_prompt,
            json.dumps(result["output"], ensure_ascii=False)
        )
    else:
        print(f"\n❌ CoderAgent 执行失败: {result['error']}")
    
    return result


async def step5_test_agent(
    design_output: Dict[str, Any],
    code_output: Dict[str, Any],
    full_files_context: Dict[str, str]
) -> Dict[str, Any]:
    """
    步骤 5: TestAgent - 测试生成
    """
    print_section("步骤 5: TestAgent - 测试生成")
    
    try:
        from app.agents.tester import test_agent
    except ImportError:
        print("⚠️ TestAgent 未找到，跳过测试生成步骤")
        return {"success": False, "error": "TestAgent not found"}
    
    # 构建提示词
    design_str = json.dumps(design_output, indent=2, ensure_ascii=False)
    code_str = json.dumps(code_output, indent=2, ensure_ascii=False)
    
    user_prompt = f"""【技术设计方案】
{design_str}

【生成的代码】
{code_str}

请根据以上信息生成测试代码。
"""
    
    print_prompt("TestAgent 提示词", test_agent.SYSTEM_PROMPT if hasattr(test_agent, 'SYSTEM_PROMPT') else "系统提示词未找到", user_prompt)
    
    # 调用 TestAgent
    print("\n🤖 调用 TestAgent...")
    result = await test_agent.generate_tests(
        design_output=design_output,
        code_output=code_output,
        target_files=full_files_context,
        pipeline_id=999
    )
    
    if result["success"]:
        print("\n✅ TestAgent 执行成功!")
        print(f"\n📋 生成的测试文件数: {len(result['output'].get('test_files', []))}")
        
        # 打印生成的测试文件
        for file_info in result["output"].get("test_files", [])[:2]:
            print(f"\n📄 测试文件: {file_info.get('file_path')}")
            content = file_info.get('content', '')
            preview = "\n".join(content.splitlines()[:15])
            print(f"   内容预览:\n{preview}")
            if len(content.splitlines()) > 15:
                print(f"   ... ({len(content.splitlines()) - 15} 行省略)")
        
        # 记录调用
        llm_recorder.record(
            "TestAgent",
            test_agent.SYSTEM_PROMPT if hasattr(test_agent, 'SYSTEM_PROMPT') else "",
            user_prompt,
            json.dumps(result["output"], ensure_ascii=False)
        )
    else:
        print(f"\n❌ TestAgent 执行失败: {result['error']}")
    
    return result


async def step6_verify_generated_logic(
    coder_result: Dict[str, Any],
    test_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    步骤 6: 真实环境运行验证
    
    使用 TestRunnerService 在沙盒环境中运行 pytest，
    验证 AI 生成的代码是否真正可用。
    """
    print_section("步骤 6: 真实环境运行验证")
    
    from app.service.test_runner import TestRunnerService
    import tempfile
    import shutil
    
    # 检查输入
    if not coder_result.get("success") or not coder_result.get("output"):
        print("⚠️ CoderAgent 未成功生成代码，跳过验证")
        return {"success": False, "error": "No code generated"}
    
    if not test_result.get("success") or not test_result.get("output"):
        print("⚠️ TestAgent 未成功生成测试，跳过验证")
        return {"success": False, "error": "No tests generated"}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "backend"
        
        try:
            # 1. 复制当前项目代码到临时目录
            source_backend = Path(__file__).parent
            print(f"📁 复制项目代码到临时目录: {workspace}")
            shutil.copytree(source_backend, workspace)
            
            # 2. 覆盖写入 AI 生成的代码
            generated_files = coder_result["output"].get("files", [])
            print(f"📝 写入 {len(generated_files)} 个生成的代码文件...")
            
            for f in generated_files:
                file_path = f.get("file_path", "")
                content = f.get("content", "")
                
                # 移除 backend/ 前缀（如果有）
                relative_path = file_path.replace("backend/", "").replace("backend\\", "")
                target_path = workspace / relative_path
                
                # 创建父目录
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 写入文件
                target_path.write_text(content, encoding="utf-8")
                print(f"   ✅ 写入: {relative_path}")
            
            # 3. 写入 AI 生成的测试
            test_files = test_result["output"].get("test_files", [])
            print(f"🧪 写入 {len(test_files)} 个生成的测试文件...")
            
            for t in test_files:
                file_path = t.get("file_path", "")
                content = t.get("content", "")
                
                # 移除 backend/ 前缀（如果有）
                relative_path = file_path.replace("backend/", "").replace("backend\\", "")
                test_path = workspace / relative_path
                
                # 创建父目录
                test_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 写入文件
                test_path.write_text(content, encoding="utf-8")
                print(f"   ✅ 写入: {relative_path}")
            
            # 4. 真正运行 pytest！
            print("\n🧪 正在沙盒中执行 pytest...")
            print("⏳ 这可能需要一些时间，请等待...")
            
            run_result = await TestRunnerService.run_tests(str(workspace))
            
            if run_result["success"]:
                print("\n🎊 终极胜利：代码逻辑验证通过！")
                print(f"   测试摘要: {run_result.get('summary', 'N/A')}")
                print(f"   退出码: {run_result.get('exit_code', 'N/A')}")
            else:
                print(f"\n❌ 逻辑验证失败!")
                print(f"   错误类型: {run_result.get('error_type', 'unknown')}")
                print(f"   测试摘要: {run_result.get('summary', 'N/A')}")
                print(f"   具体错误: {run_result.get('error', 'N/A')[:500]}")
                
                # 打印部分日志
                logs = run_result.get('logs', '')
                if logs:
                    print(f"\n📋 测试日志（前 1000 字符）:")
                    print(logs[:1000])
                    if len(logs) > 1000:
                        print(f"\n... ({len(logs) - 1000} 字符省略)")
            
            return run_result
            
        except Exception as e:
            print(f"\n❌ 验证过程出错: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}


async def main():
    """主函数 - 执行全链路测试"""
    
    print_section("🚀 OmniFlowAI 全链路测试", border="=")
    print("\n测试流程:")
    print("  1. ArchitectAgent - 需求分析")
    print("  2. 两层代码上下文检索")
    print("  3. DesignerAgent - 技术设计")
    print("  4. CoderAgent - 代码生成")
    print("  5. TestAgent - 测试生成")
    print("  6. 真实环境运行验证 (TestRunnerService)")
    print("\n⚠️ 注意: 此脚本仅用于测试，不会实际提交代码或创建 PR")
    
    coder_result = None
    test_result = {"success": False, "error": "Not executed"}
    
    try:
        # 步骤 1: ArchitectAgent
        architect_result = await step1_architect_agent()
        if not architect_result["success"]:
            print("\n❌ 全链路测试在步骤 1 失败")
            return
        
        # 步骤 2: 两层代码上下文检索
        code_context = await step2_code_context(architect_result["output"])
        
        # 步骤 3: DesignerAgent
        designer_result = await step3_designer_agent(
            architect_output=architect_result["output"],
            code_context=code_context
        )
        if not designer_result["success"]:
            print("\n❌ 全链路测试在步骤 3 失败")
            return
        
        # 步骤 4: CoderAgent
        coder_result = await step4_coder_agent(
            design_output=designer_result["output"],
            full_files_context=code_context["full_files_context"]
        )
        if not coder_result["success"]:
            print("\n❌ 全链路测试在步骤 4 失败")
            return
        
        # 步骤 5: TestAgent
        test_result = await step5_test_agent(
            design_output=designer_result["output"],
            code_output=coder_result["output"],
            full_files_context=code_context["full_files_context"]
        )
        
        # 步骤 6: 真实环境运行验证
        verify_result = await step6_verify_generated_logic(coder_result, test_result)
        
        # 打印 LLM 调用摘要
        llm_recorder.print_summary()
        
        # 测试完成
        print_section("🎉 全链路测试完成!")
        print("\n总结:")
        print(f"  ✅ ArchitectAgent: 成功")
        print(f"  ✅ 代码上下文检索: 成功")
        print(f"  ✅ DesignerAgent: 成功")
        print(f"  ✅ CoderAgent: 成功")
        print(f"  {'✅' if test_result['success'] else '⚠️'} TestAgent: {'成功' if test_result['success'] else '失败/跳过'}")
        print(f"  {'🎊' if verify_result['success'] else '❌'} 真实环境验证: {'通过' if verify_result['success'] else '失败'}")
        
    except Exception as e:
        print(f"\n❌ 全链路测试出错: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 清理
        from app.service.code_indexer import clear_indexer_cache
        clear_indexer_cache()

    


if __name__ == "__main__":
    asyncio.run(main())
