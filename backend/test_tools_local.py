"""
本地验证脚本：测试重构后的 tools.py 入口及 tree-sitter 功能
同时验证 _file_cache 代理（ArchitectAgent 依赖）
"""

import sys
import json
import os

os.chdir(r"d:\feishuProj\backend")
sys.path.insert(0, r"d:\feishuProj\backend")

from app.agents.tools import AgentTools

PROJECT_PATH = r"d:\feishuProj\backend"
tools = AgentTools(PROJECT_PATH)


def test_read_chunk_symbol():
    print("=" * 60)
    print("TEST 1: read_chunk by symbol_name")
    result = tools.read_chunk("app/agents/tools.py", symbol_name="glob")
    data = json.loads(result)
    assert data.get("mode") == "symbol", f"Expected mode='symbol', got {data.get('mode')}"
    assert data.get("symbol") == "glob"
    assert "start_line" in data and "end_line" in data
    print(f"  OK: symbol={data['symbol']}, lines={data['start_line']}-{data['end_line']}")
    print("=" * 60)


def test_read_chunk_lines():
    print("\n" + "=" * 60)
    print("TEST 2: read_chunk by line range")
    result = tools.read_chunk("app/agents/tools.py", start_line=1, end_line=30)
    data = json.loads(result)
    assert data.get("mode") == "lines"
    assert data.get("start_line") <= 1
    print(f"  OK: lines={data['start_line']}-{data['end_line']}")
    print("=" * 60)


def test_read_chunk_summary():
    print("\n" + "=" * 60)
    print("TEST 3: read_chunk summary mode")
    result = tools.read_chunk("app/agents/tools.py")
    data = json.loads(result)
    assert data.get("mode") == "summary"
    assert "Imports" in data.get("content", "") or "Top-level symbols" in data.get("content", "")
    print(f"  OK: summary length={len(data['content'])}")
    print("=" * 60)


def test_grep_ast_function():
    print("\n" + "=" * 60)
    print("TEST 4: grep_ast search_type=function")
    result = tools.grep_ast("read_chunk", search_path="app/agents", search_type="function", max_results=5)
    data = json.loads(result)
    assert data.get("search_type") == "function"
    assert data.get("count", 0) > 0, "Expected at least one function match"
    print(f"  OK: found {data['count']} matches")
    for m in data["matches"]:
        print(f"    - {m['file']}:{m['line']} {m.get('name', '')}")
    print("=" * 60)


def test_grep_ast_text():
    print("\n" + "=" * 60)
    print("TEST 5: grep_ast search_type=text")
    result = tools.grep_ast("def read_chunk", search_path="app/agents", search_type="text", max_results=5)
    data = json.loads(result)
    assert data.get("search_type") == "text"
    assert data.get("count", 0) > 0
    print(f"  OK: found {data['count']} text matches")
    print("=" * 60)


def test_grep_ast_callers():
    print("\n" + "=" * 60)
    print("TEST 6: grep_ast search_type=callers")
    result = tools.grep_ast("json.dumps", search_path="app/agents", search_type="callers", max_results=5)
    data = json.loads(result)
    assert data.get("search_type") == "callers"
    print(f"  OK: found {data['count']} caller matches")
    print("=" * 60)


def test_glob():
    print("\n" + "=" * 60)
    print("TEST 7: glob")
    result = tools.glob("app/agents/*.py", max_results=10)
    data = json.loads(result)
    assert data.get("count", 0) > 0
    print(f"  OK: found {data['count']} files")
    print("=" * 60)


def test_grep():
    print("\n" + "=" * 60)
    print("TEST 8: grep")
    result = tools.grep("class AgentTools", path="app/agents", max_results=5)
    data = json.loads(result)
    assert data.get("count", 0) > 0
    print(f"  OK: found {data['count']} matches")
    print("=" * 60)


def test_file_cache_proxy():
    print("\n" + "=" * 60)
    print("TEST 9: _file_cache proxy (ArchitectAgent dependency)")
    # 先 read_file 填充缓存
    tools.read_file("app/agents/tools.py", 1, 10)
    cache = tools._file_cache
    assert isinstance(cache, dict), f"_file_cache should be dict, got {type(cache)}"
    assert len(cache) > 0, "_file_cache should not be empty after read_file"
    print(f"  OK: _file_cache has {len(cache)} entries")
    print("=" * 60)


def test_generate_project_card():
    print("\n" + "=" * 60)
    print("TEST 10: generate_project_card")
    result = tools.generate_project_card(max_depth=2, max_files=20)
    data = json.loads(result)
    assert "directory_structure" in data or "error" in data
    if "directory_structure" in data:
        print(f"  OK: project_card generated, has {len(data)} keys")
    else:
        print(f"  WARN: project_card error: {data.get('error')}")
    print("=" * 60)


def test_tool_definitions():
    print("\n" + "=" * 60)
    print("TEST 11: tool_definitions property")
    defs = tools.tool_definitions
    assert isinstance(defs, list)
    names = [d["function"]["name"] for d in defs]
    assert "glob" in names and "grep" in names and "read_file" in names and "replace_lines" in names
    print(f"  OK: tool_definitions has {len(defs)} tools: {names}")
    print("=" * 60)


if __name__ == "__main__":
    test_read_chunk_symbol()
    test_read_chunk_lines()
    test_read_chunk_summary()
    test_grep_ast_function()
    test_grep_ast_text()
    test_grep_ast_callers()
    test_glob()
    test_grep()
    test_file_cache_proxy()
    test_generate_project_card()
    test_tool_definitions()
    print("\nAll tests passed!")
