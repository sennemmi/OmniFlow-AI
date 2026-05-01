"""
Sandbox 模式验证脚本：测试 AgentTools 在 sandbox 环境下的功能

运行方式：
    python test_tools_sandbox.py

要求：
    1. Docker Desktop 已启动
    2. sandbox 镜像已构建
    3. 项目代码已挂载到 sandbox
"""

import sys
import os
import json
import asyncio

os.chdir(r"d:\feishuProj\backend")
sys.path.insert(0, r"d:\feishuProj\backend")

from app.service.sandbox_orchestrator import get_sandbox_orchestrator
from app.agents.tools import AgentTools

PROJECT_PATH = r"d:\feishuProj\backend"
PIPELINE_ID = 99999  # 测试用 pipeline_id


async def setup_sandbox():
    """初始化 sandbox 环境"""
    print("=" * 60)
    print("SETUP: 初始化 Sandbox 环境")
    orchestrator = get_sandbox_orchestrator(PIPELINE_ID)
    result = await orchestrator.initialize(PROJECT_PATH)
    if not result.get("success"):
        raise RuntimeError(f"Sandbox 初始化失败: {result.get('error')}")

    print(f"  Pipeline ID: {PIPELINE_ID}")

    file_service = orchestrator.get_file_service()
    if not file_service:
        raise RuntimeError("file_service 未初始化")

    print("  等待 sandbox 就绪...")
    await asyncio.sleep(3)

    # 验证文件系统可访问
    test_read = await file_service.read_file("app/agents/tools.py")
    if not test_read.exists:
        raise RuntimeError(f"无法读取 sandbox 中的文件: {test_read.error}")
    print(f"  Sandbox 文件系统正常 (app/agents/tools.py: {len(test_read.content)} chars)")
    print("=" * 60)
    return orchestrator, file_service


async def test_read_chunk_symbol_sandbox(tools):
    print("\n" + "=" * 60)
    print("TEST 1: read_chunk by symbol_name (sandbox)")
    result = tools.read_chunk("app/agents/tools.py", symbol_name="glob")
    data = json.loads(result)
    assert data.get("mode") == "symbol", f"Expected mode='symbol', got {data.get('mode')}"
    assert data.get("symbol") == "glob"
    print(f"  OK: symbol={data['symbol']}, lines={data['start_line']}-{data['end_line']}")
    print("=" * 60)


async def test_read_chunk_lines_sandbox(tools):
    print("\n" + "=" * 60)
    print("TEST 2: read_chunk by line range (sandbox)")
    result = tools.read_chunk("app/agents/tools.py", start_line=1, end_line=30)
    data = json.loads(result)
    assert data.get("mode") == "lines"
    print(f"  OK: lines={data['start_line']}-{data['end_line']}")
    print("=" * 60)


async def test_read_chunk_summary_sandbox(tools):
    print("\n" + "=" * 60)
    print("TEST 3: read_chunk summary mode (sandbox)")
    result = tools.read_chunk("app/agents/tools.py")
    data = json.loads(result)
    assert data.get("mode") == "summary"
    print(f"  OK: summary length={len(data['content'])}")
    print("=" * 60)


async def test_grep_ast_function_sandbox(tools):
    print("\n" + "=" * 60)
    print("TEST 4: grep_ast search_type=function (sandbox)")
    result = tools.grep_ast("read_chunk", search_path="app/agents", search_type="function", max_results=5)
    data = json.loads(result)
    assert data.get("search_type") == "function"
    print(f"  OK: found {data['count']} matches")
    for m in data["matches"]:
        print(f"    - {m['file']}:{m['line']} {m.get('name', '')}")
    print("=" * 60)


async def test_grep_ast_text_sandbox(tools):
    print("\n" + "=" * 60)
    print("TEST 5: grep_ast search_type=text (sandbox)")
    result = tools.grep_ast("def read_chunk", search_path="app/agents", search_type="text", max_results=5)
    data = json.loads(result)
    assert data.get("search_type") == "text"
    print(f"  OK: found {data['count']} text matches")
    print("=" * 60)


async def test_glob_sandbox(tools):
    print("\n" + "=" * 60)
    print("TEST 6: glob (sandbox)")
    result = tools.glob("app/agents/*.py", max_results=10)
    data = json.loads(result)
    assert data.get("count", 0) > 0
    print(f"  OK: found {data['count']} files")
    print("=" * 60)


async def test_grep_sandbox(tools):
    print("\n" + "=" * 60)
    print("TEST 7: grep (sandbox)")
    result = tools.grep("class AgentTools", path="app/agents", max_results=5)
    data = json.loads(result)
    assert data.get("count", 0) > 0
    print(f"  OK: found {data['count']} matches")
    print("=" * 60)


async def test_file_cache_proxy_sandbox(tools):
    print("\n" + "=" * 60)
    print("TEST 8: _file_cache proxy (sandbox)")
    tools.read_file("app/agents/tools.py", 1, 10)
    cache = tools._file_cache
    assert isinstance(cache, dict)
    assert len(cache) > 0
    print(f"  OK: _file_cache has {len(cache)} entries")
    print("=" * 60)


async def test_generate_project_card_sandbox(tools):
    print("\n" + "=" * 60)
    print("TEST 9: generate_project_card (sandbox)")
    result = tools.generate_project_card(max_depth=2, max_files=20)
    data = json.loads(result)
    assert "directory_structure" in data or "error" in data
    if "directory_structure" in data:
        print(f"  OK: project_card generated")
    else:
        print(f"  WARN: {data.get('error')}")
    print("=" * 60)


async def run_all_tests():
    orchestrator, file_service = await setup_sandbox()
    tools = AgentTools(PROJECT_PATH, file_service=file_service)

    try:
        await test_read_chunk_symbol_sandbox(tools)
        await test_read_chunk_lines_sandbox(tools)
        await test_read_chunk_summary_sandbox(tools)
        await test_grep_ast_function_sandbox(tools)
        await test_grep_ast_text_sandbox(tools)
        await test_glob_sandbox(tools)
        await test_grep_sandbox(tools)
        await test_file_cache_proxy_sandbox(tools)
        await test_generate_project_card_sandbox(tools)
        print("\n" + "=" * 60)
        print("All sandbox tests passed!")
        print("=" * 60)
    finally:
        print("\nCLEANUP: 销毁 sandbox...")
        await orchestrator.cleanup()
        print("  Sandbox 已销毁")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
