import asyncio
import sys
import os
from pathlib import Path
import tempfile
import shutil

# 强制加载环境变量
from dotenv import load_dotenv
backend_dir = Path(__file__).parent / "backend"
env_path = backend_dir / ".env"
if not env_path.exists():
    env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(backend_dir))

from app.agents.multi_agent_coordinator import multi_agent_coordinator
from app.core.config import settings

async def test_coding_loop():
    print(f"🚀 启动独立 Coder & Tester 调试模式 (使用模型: {settings.llm_model})...")
    
    mock_design = {
        "technical_design": "新增系统清理接口",
        "api_endpoints": [{"method": "POST", "path": "/api/v1/system/cleanup", "description": "触发清理"}],
        "function_changes": [
            {"file": "app/api/v1/system.py", "function": "cleanup", "action": "add", "description": "添加清理接口"}
        ]
    }

    target_files = {}
    system_py_path = backend_dir / "app/api/v1/system.py"
    if system_py_path.exists():
        target_files["app/api/v1/system.py"] = system_py_path.read_text(encoding='utf-8')

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_path = Path(tmpdir) / "workspace"
        
        print(f"📂 正在克隆当前代码到沙盒: {workspace_path}")
        shutil.copytree(backend_dir, workspace_path / "backend")
        
        print("🤖 呼叫 MultiAgentCoordinator 进行编码和测试...")
        result = await multi_agent_coordinator.execute_with_auto_fix(
            design_output=mock_design,
            target_files=target_files,
            pipeline_id=999, 
            workspace_path=str(workspace_path)
        )

        print("\n" + "="*50)
        print("🎯 执行结束！最终结果：")
        print(f"Success: {result.get('success')}")
        print(f"尝试次数: {result.get('attempt')}")
        
        if not result.get("success"):
            print("\n❌ 失败原因:", result.get("error"))
            print("\n📜 最后的测试日志:\n", result.get("last_error_logs"))
            
        print("\n💻 AI 实际输出的代码：")
        output = result.get("output")
        if output and "files" in output:
            for f in output["files"]:
                print(f"\n>>> 文件: {f['file_path']} <<<")
                print(f['content'])
                
                # 把生成的代码写到当前目录，方便你用编辑器查看！
                dump_file = Path(__file__).parent / f"debug_output_{f['file_path'].replace('/', '_')}"
                dump_file.write_text(f['content'], encoding='utf-8')
                print(f"✅ 已将此代码保存到本地: {dump_file.name}")
        else:
            print("没有拿到代码输出。")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(test_coding_loop())