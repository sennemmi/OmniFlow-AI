"""
快速修改功能测试脚本 - 调用真实 LLM

使用方法:
    python test_quick_modify.py

功能:
    1. 测试轻量级代码修改 API (/api/v1/code/modify)
    2. 调用真实 LLM 生成代码变更
    3. 自动应用变更到文件系统
    4. 显示变更前后的 diff

环境要求:
    - 后端服务已启动 (python run_server.py)
    - LLM API Key 已配置
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()

# API 配置
API_BASE_URL = "http://localhost:8000"
TEST_FILE = "src/pages/Landing/sections/Hero.tsx"


async def test_quick_modify():
    """测试快速修改功能"""
    console.print(Panel.fit("🚀 快速修改功能测试", style="bold blue"))
    
    # 准备测试数据
    payload = {
        "source_context": {
            "file": TEST_FILE,
            "line": 45,
            "column": 8
        },
        "element_context": {
            "tag": "h1",
            "id": "hero-title",
            "class_name": "text-4xl font-bold",
            "outer_html": '<h1 class="text-4xl font-bold">研发流程引擎</h1>',
            "text": "研发流程引擎",
            "xpath": "//h1[@id='hero-title']",
            "selector": "#hero-title"
        },
        "user_instruction": '将"研发"改为"开发"',
        "auto_apply": False  # 先不应用，查看结果
    }
    
    console.print(f"\n📄 测试文件: {TEST_FILE}")
    console.print(f"📝 修改指令: {payload['user_instruction']}")
    console.print(f"🎯 目标元素: {payload['element_context']['outer_html'][:50]}...")
    
    # 发送请求
    async with httpx.AsyncClient(timeout=120.0) as client:
        console.print("\n⏳ 调用 API...")
        
        try:
            response = await client.post(
                f"{API_BASE_URL}/api/v1/code/modify",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            console.print(f"📡 响应状态: {response.status_code}")
            
            # 解析响应
            try:
                result = response.json()
            except json.JSONDecodeError as e:
                console.print(f"[red]❌ JSON 解析失败: {e}[/red]")
                console.print(f"原始响应: {response.text[:500]}")
                return
            
            # 显示结果
            if result.get("success"):
                console.print("\n[green]✅ 修改成功![/green]")
                
                data = result.get("data", {})
                
                # 显示摘要
                summary = data.get("summary", "无摘要")
                console.print(f"\n📋 摘要: {summary}")
                
                # 显示变更的文件
                files_changed = data.get("files_changed", [])
                console.print(f"\n📁 变更文件数: {len(files_changed)}")
                for f in files_changed:
                    console.print(f"   - {f}")
                
                # 显示 diff
                diff = data.get("diff", "")
                if diff:
                    console.print("\n📊 代码 Diff:")
                    console.print(Syntax(diff, "diff", theme="monokai", line_numbers=True))
                
                # 显示新内容（前 50 行）
                new_content = data.get("new_content", "")
                if new_content:
                    lines = new_content.split("\n")[:50]
                    preview = "\n".join(lines)
                    console.print("\n📝 新文件内容预览（前 50 行）:")
                    console.print(Syntax(preview, "typescript", theme="monokai", line_numbers=True))
                
                # 询问是否应用变更
                console.print("\n" + "=" * 50)
                console.print("是否应用此变更到文件系统?")
                console.print("输入 'y' 应用, 其他键跳过:")
                
                # 由于异步环境，这里使用简单的输入
                user_input = input("> ").strip().lower()
                
                if user_input == 'y':
                    console.print("\n⏳ 应用变更...")
                    payload["auto_apply"] = True
                    
                    apply_response = await client.post(
                        f"{API_BASE_URL}/api/v1/code/modify",
                        json=payload,
                        headers={"Content-Type": "application/json"}
                    )
                    
                    apply_result = apply_response.json()
                    if apply_result.get("success"):
                        console.print("[green]✅ 变更已应用到文件系统![/green]")
                    else:
                        console.print(f"[red]❌ 应用失败: {apply_result.get('error')}[/red]")
                else:
                    console.print("[yellow]⚠️ 已跳过应用变更[/yellow]")
                    
            else:
                console.print(f"\n[red]❌ 修改失败[/red]")
                console.print(f"错误信息: {result.get('error', '未知错误')}")
                console.print(f"Request ID: {result.get('request_id', 'N/A')}")
                
        except httpx.ConnectError:
            console.print(f"[red]❌ 连接失败: 请确保后端服务已启动[/red]")
            console.print(f"   运行: python run_server.py")
        except httpx.TimeoutException:
            console.print(f"[red]❌ 请求超时: LLM 响应时间过长[/red]")
        except Exception as e:
            console.print(f"[red]❌ 异常: {e}[/red]")
            import traceback
            console.print(traceback.format_exc())


async def test_with_different_instructions():
    """测试多个不同的修改指令"""
    console.print(Panel.fit("🧪 批量测试不同指令", style="bold green"))
    
    test_cases = [
        {
            "name": "修改文字",
            "instruction": '将"研发"改为"开发"',
            "line": 45
        },
        {
            "name": "修改样式",
            "instruction": '将标题字体改为 text-5xl 并添加 text-blue-600 颜色',
            "line": 45
        },
        {
            "name": "添加属性",
            "instruction": '给按钮添加 disabled 属性',
            "line": 50
        }
    ]
    
    results = []
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, test_case in enumerate(test_cases, 1):
            console.print(f"\n{'=' * 50}")
            console.print(f"测试 {i}/{len(test_cases)}: {test_case['name']}")
            console.print(f"指令: {test_case['instruction']}")
            
            payload = {
                "source_context": {
                    "file": TEST_FILE,
                    "line": test_case["line"],
                    "column": 8
                },
                "element_context": {
                    "tag": "h1",
                    "id": "hero-title",
                    "class_name": "text-4xl font-bold",
                    "outer_html": '<h1 class="text-4xl font-bold">研发流程引擎</h1>',
                    "text": "研发流程引擎",
                    "xpath": "//h1[@id='hero-title']",
                    "selector": "#hero-title"
                },
                "user_instruction": test_case["instruction"],
                "auto_apply": False
            }
            
            try:
                response = await client.post(
                    f"{API_BASE_URL}/api/v1/code/modify",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                
                result = response.json()
                success = result.get("success", False)
                
                results.append({
                    "name": test_case["name"],
                    "success": success,
                    "error": result.get("error", "") if not success else ""
                })
                
                if success:
                    console.print(f"[green]✅ 成功[/green]")
                else:
                    console.print(f"[red]❌ 失败: {result.get('error', '未知错误')[:100]}[/red]")
                    
            except Exception as e:
                console.print(f"[red]❌ 异常: {e}[/red]")
                results.append({
                    "name": test_case["name"],
                    "success": False,
                    "error": str(e)
                })
    
    # 显示汇总
    console.print(f"\n{'=' * 50}")
    console.print("📊 测试结果汇总:")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("测试名称")
    table.add_column("结果")
    table.add_column("错误信息")
    
    for r in results:
        status = "[green]✅ 通过[/green]" if r["success"] else "[red]❌ 失败[/red]"
        table.add_row(r["name"], status, r["error"][:50])
    
    console.print(table)


def check_backend_running():
    """检查后端服务是否运行"""
    import httpx
    try:
        response = httpx.get(f"{API_BASE_URL}/api/v1/health", timeout=5.0)
        return response.status_code == 200
    except:
        return False


async def main():
    """主函数"""
    # 检查后端服务
    console.print("🔍 检查后端服务...")
    if not check_backend_running():
        console.print(f"[red]❌ 后端服务未启动![/red]")
        console.print(f"   请先运行: python run_server.py")
        return
    
    console.print("[green]✅ 后端服务运行中[/green]\n")
    
    # 显示菜单
    console.print(Panel.fit("测试菜单", style="bold cyan"))
    console.print("1. 单次测试 - 修改文字")
    console.print("2. 批量测试 - 多个不同指令")
    console.print("3. 退出")
    console.print()
    
    choice = input("请选择 (1-3): ").strip()
    
    if choice == "1":
        await test_quick_modify()
    elif choice == "2":
        await test_with_different_instructions()
    elif choice == "3":
        console.print("👋 再见!")
    else:
        console.print("[red]无效选择[/red]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n\n👋 用户取消")
    except Exception as e:
        console.print(f"\n[red]❌ 程序异常: {e}[/red]")
        import traceback
        console.print(traceback.format_exc())
