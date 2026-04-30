"""
快速修改功能测试脚本（简单版）- 调用真实 LLM

使用方法:
    python test_quick_modify_simple.py

无需额外依赖，只需要 httpx:
    pip install httpx
"""

import asyncio
import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("请先安装 httpx: pip install httpx")
    sys.exit(1)

# API 配置
API_BASE_URL = "http://localhost:8000"
TEST_FILE = "src/pages/Landing/sections/Hero.tsx"  # 相对于 frontend 目录的路径


def print_separator():
    print("=" * 60)


def print_success(msg):
    print(f"✅ {msg}")


def print_error(msg):
    print(f"❌ {msg}")


def print_info(msg):
    print(f"ℹ️  {msg}")


def print_warning(msg):
    print(f"⚠️  {msg}")


async def test_single_modify(instruction: str, line: int = 45):
    """单次修改测试"""
    print_separator()
    print(f"📝 测试指令: {instruction}")
    print(f"📄 目标文件: {TEST_FILE}:{line}")
    
    payload = {
        "source_context": {
            "file": TEST_FILE,
            "line": line,
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
        "user_instruction": instruction,
        "auto_apply": True  # 应用变更到文件系统
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            print("⏳ 发送请求...")
            response = await client.post(
                f"{API_BASE_URL}/api/v1/code/modify",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"📡 状态码: {response.status_code}")
            
            # 尝试解析 JSON
            try:
                result = response.json()
            except json.JSONDecodeError as e:
                print_error(f"JSON 解析失败: {e}")
                print(f"原始响应:\n{response.text[:1000]}")
                return False
            
            # 显示结果
            if result.get("success"):
                print_success("修改成功!")
                
                data = result.get("data", {})
                
                # 摘要
                summary = data.get("summary", "无")
                print(f"\n📋 摘要: {summary}")
                
                # 变更文件
                files = data.get("files_changed", [])
                print(f"\n📁 变更文件 ({len(files)} 个):")
                for f in files:
                    print(f"   - {f}")
                
                # Diff
                diff = data.get("diff", "")
                if diff:
                    print(f"\n📊 Diff ({len(diff)} 字符):")
                    print("-" * 40)
                    # 只显示前 20 行
                    diff_lines = diff.split("\n")[:20]
                    for line in diff_lines:
                        if line.startswith("+"):
                            print(f"\033[92m{line}\033[0m")  # 绿色
                        elif line.startswith("-"):
                            print(f"\033[91m{line}\033[0m")  # 红色
                        else:
                            print(line)
                    if len(diff.split("\n")) > 20:
                        print("... (省略剩余内容)")
                    print("-" * 40)
                
                return True
            else:
                print_error(f"修改失败: {result.get('error', '未知错误')}")
                print(f"Request ID: {result.get('request_id', 'N/A')}")
                return False
                
        except httpx.ConnectError:
            print_error(f"连接失败: 请确保后端服务已启动")
            print_info(f"运行: python run_server.py")
            return False
        except httpx.TimeoutException:
            print_error("请求超时: LLM 响应时间过长")
            return False
        except Exception as e:
            print_error(f"异常: {e}")
            import traceback
            print(traceback.format_exc())
            return False


async def test_batch():
    """批量测试"""
    print_separator()
    print("🧪 批量测试不同指令")
    print_separator()
    
    test_cases = [
        ("将'研发'改为'开发'", 45),
        ("将标题改为蓝色文字", 45),
        ("给按钮添加圆角样式", 50),
    ]
    
    results = []
    
    for i, (instruction, line) in enumerate(test_cases, 1):
        print(f"\n测试 {i}/{len(test_cases)}")
        success = await test_single_modify(instruction, line)
        results.append((instruction, success))
    
    # 汇总
    print_separator()
    print("📊 测试结果汇总:")
    print_separator()
    
    for instruction, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{status}: {instruction[:30]}...")
    
    passed = sum(1 for _, s in results if s)
    print(f"\n总计: {passed}/{len(results)} 通过")


def check_backend():
    """检查后端是否运行"""
    try:
        import httpx
        response = httpx.get(f"{API_BASE_URL}/api/v1/health", timeout=5.0)
        return response.status_code == 200
    except:
        return False


async def interactive_mode():
    """交互模式"""
    print_separator()
    print("🚀 OmniFlowAI 快速修改测试工具")
    print_separator()
    
    # 检查后端
    print("\n🔍 检查后端服务...")
    if not check_backend():
        print_error("后端服务未启动!")
        print_info("请先运行: python run_server.py")
        return
    print_success("后端服务运行中")
    
    while True:
        print_separator()
        print("菜单:")
        print("1. 测试简单文字修改")
        print("2. 测试样式修改")
        print("3. 批量测试")
        print("4. 自定义指令")
        print("5. 退出")
        print_separator()
        
        choice = input("\n请选择 (1-5): ").strip()
        
        if choice == "1":
            await test_single_modify("将'研发'改为'开发'")
        elif choice == "2":
            await test_single_modify("将标题字体加大到 text-5xl 并改为蓝色")
        elif choice == "3":
            await test_batch()
        elif choice == "4":
            instruction = input("请输入修改指令: ").strip()
            if instruction:
                await test_single_modify(instruction)
        elif choice == "5":
            print("👋 再见!")
            break
        else:
            print_warning("无效选择")


async def main():
    """主函数"""
    # 检查命令行参数
    if len(sys.argv) > 1:
        # 直接执行指定指令
        instruction = " ".join(sys.argv[1:])
        print(f"执行指令: {instruction}")
        
        if not check_backend():
            print_error("后端服务未启动!")
            return
        
        await test_single_modify(instruction)
    else:
        # 交互模式
        await interactive_mode()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 用户取消")
    except Exception as e:
        print_error(f"程序异常: {e}")
        import traceback
        print(traceback.format_exc())
