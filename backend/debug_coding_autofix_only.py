"""
debug_coding_autofix_only.py
仅测试 CODING 阶段的「生成→测试→修复」循环，不涉及完整流水线。
保存每次 CoderAgent 的完整输入输出到文件，方便检查 Prompt 和 AI 响应。
"""
import asyncio
import json
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.agents.multi_agent_coordinator import MultiAgentCoordinator
from app.agents.coder import coder_agent
from app.core.config import settings

# 替换 CoderAgent 的 generate_code 方法，添加日志记录
original_generate_code = coder_agent.generate_code
call_counter = 0

async def logged_generate_code(design_output, target_files, pipeline_id=None, error_context=None):
    global call_counter
    call_counter += 1
    input_dump = {
        "call": call_counter,
        "design_output": design_output,
        "target_files_keys": list(target_files.keys()),
        "error_context": error_context
    }
    print(f"\n{'='*60}")
    print(f"CoderAgent 第 {call_counter} 次调用")
    if error_context:
        print(f"传入的错误上下文（前500字符）: {error_context[:500]}")
    else:
        print("无错误上下文（首次生成）")
    
    # 保存输入到文件
    filename = f"debug_coder_input_{call_counter}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(input_dump, f, indent=2, ensure_ascii=False)
    print(f"完整输入已保存: {filename}")

    result = await original_generate_code(design_output, target_files, pipeline_id, error_context)

    # 保存输出
    out_filename = f"debug_coder_output_{call_counter}.json"
    with open(out_filename, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"完整输出已保存: {out_filename}")

    if result.get("success"):
        files = result.get("output", {}).get("files", [])
        print(f"生成文件: {[f['file_path'] for f in files]}")
    else:
        print(f"CoderAgent 执行失败: {result.get('error')}")
    return result

# 替换方法
coder_agent.generate_code = logged_generate_code

async def run():
    # 1. 准备设计输出（模拟 DESIGN 阶段的结果）
    design_output = {
        "technical_design": "在 app/api/v1/system.py 中新增一个清理缓存的接口 POST /api/v1/system/cleanup",
        "api_endpoints": [{"method": "POST", "path": "/api/v1/system/cleanup", "description": "清理系统缓存"}],
        "function_changes": [
            {
                "file": "app/api/v1/system.py",
                "function": "cleanup_cache",
                "action": "add",
                "description": "新增清理缓存端点"
            }
        ],
        "affected_files": ["app/api/v1/system.py"]
    }

    # 2. 确定目标项目路径
    target = settings.TARGET_PROJECT_PATH
    if not target:
        print("错误: TARGET_PROJECT_PATH 未设置，请检查 .env")
        return
    src_project = Path(target)
    if not src_project.is_absolute():
        src_project = Path.cwd().parent / target
    src_project = src_project.resolve()
    if not src_project.exists():
        print(f"错误: 目标项目目录不存在: {src_project}")
        return

    # 3. 创建临时工作区（复制整个 backend 目录）
    tmpdir = tempfile.mkdtemp(prefix="debug_coding_")
    dest_backend = Path(tmpdir) / "backend"
    shutil.copytree(src_project / "backend", dest_backend)
    print(f"工作区: {dest_backend}")

    # 4. 读取需要修改的文件（目前只修改 system.py）
    target_files = {}
    for f in design_output["affected_files"]:
        full_path = dest_backend / f
        if full_path.exists():
            target_files[f] = full_path.read_text(encoding="utf-8")
        else:
            print(f"警告: 目标文件不存在 {f}，将以新建模式处理")

    print(f"目标文件数量: {len(target_files)}")

    # 5. 执行 auto-fix 循环
    coordinator = MultiAgentCoordinator()
    result = await coordinator.execute_with_auto_fix(
        design_output=design_output,
        target_files=target_files,
        pipeline_id=999,
        workspace_path=str(dest_backend)
    )

    print("\n" + "="*60)
    print("最终结果")
    print(f"成功: {result['success']}")
    print(f"尝试次数: {result['attempt']}")
    if not result['success']:
        print(f"错误: {result.get('error')}")
        if result.get("last_error_logs"):
            print(f"最后错误日志（前800字符）: {result['last_error_logs'][:800]}")

    # 保留工作区以便手动检查
    keep_dir = Path("./debug_workspace")
    if keep_dir.exists():
        shutil.rmtree(keep_dir)
    shutil.move(tmpdir, str(keep_dir))
    print(f"\n完整工作区已保留在: {keep_dir}")
    print("可以手动查看生成的代码和测试文件。")

if __name__ == "__main__":
    # 恢复原方法（避免影响其他测试）
    try:
        asyncio.run(run())
    finally:
        coder_agent.generate_code = original_generate_code