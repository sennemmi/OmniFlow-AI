"""
快速修改功能测试脚本（多文件/多元素版）- 调用真实 LLM

使用方法:
    python test_quick_modify_multi.py

功能:
    1. 测试修改不同文件的多个元素
    2. 支持批量测试多个场景
    3. 自动验证修改结果
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


# ============================================
# 测试用例配置
# ============================================

TEST_CASES = [
    {
        "name": "修改 Hero 组件标题",
        "file": "src/pages/Landing/sections/Hero.tsx",
        "line": 45,
        "instruction": "将'研发'改为'开发'",
        "element": {
            "tag": "h1",
            "id": "hero-title",
            "class_name": "text-5xl font-bold",
            "outer_html": '<h1 class="text-5xl font-bold">研发流程引擎</h1>',
            "text": "研发流程引擎",
            "xpath": "//h1",
            "selector": "h1"
        }
    },
    {
        "name": "修改 Features 组件标题",
        "file": "src/pages/Landing/sections/Features.tsx",
        "line": 30,
        "instruction": "将'核心功能'改为'主要功能'",
        "element": {
            "tag": "h2",
            "id": "",
            "class_name": "text-3xl font-bold",
            "outer_html": '<h2 class="text-3xl font-bold">核心功能</h2>',
            "text": "核心功能",
            "xpath": "//h2",
            "selector": "h2"
        }
    },
    {
        "name": "修改导航栏 Logo 文字",
        "file": "src/components/Layout/Navbar.tsx",
        "line": 25,
        "instruction": "将'OmniFlow'改为'OmniFlowAI'",
        "element": {
            "tag": "span",
            "id": "",
            "class_name": "font-bold text-xl",
            "outer_html": '<span class="font-bold text-xl">OmniFlow</span>',
            "text": "OmniFlow",
            "xpath": "//span[contains(@class, 'font-bold')]",
            "selector": "span.font-bold"
        }
    },
    {
        "name": "修改按钮样式",
        "file": "src/pages/Landing/sections/Hero.tsx",
        "line": 60,
        "instruction": "将按钮背景色改为蓝色",
        "element": {
            "tag": "button",
            "id": "",
            "class_name": "group inline-flex items-center",
            "outer_html": '<button class="group inline-flex items-center gap-2 px-6 py-4">免费开始使用</button>',
            "text": "免费开始使用",
            "xpath": "//button",
            "selector": "button"
        }
    },
]


# ============================================
# 工具函数
# ============================================

def print_separator():
    print("=" * 70)


def print_success(msg):
    print(f"✅ {msg}")


def print_error(msg):
    print(f"❌ {msg}")


def print_info(msg):
    print(f"ℹ️  {msg}")


def print_warning(msg):
    print(f"⚠️  {msg}")


def check_backend():
    """检查后端是否运行"""
    try:
        response = httpx.get(f"{API_BASE_URL}/api/v1/health", timeout=5.0)
        return response.status_code == 200
    except:
        return False


# ============================================
# 核心测试函数
# ============================================

async def test_modify_case(case: dict, client: httpx.AsyncClient) -> bool:
    """测试单个修改用例"""
    print_separator()
    print(f"📝 {case['name']}")
    print(f"📄 文件: {case['file']}:{case['line']}")
    print(f"💬 指令: {case['instruction']}")
    
    payload = {
        "source_context": {
            "file": case["file"],
            "line": case["line"],
            "column": 8
        },
        "element_context": {
            "tag": case["element"]["tag"],
            "id": case["element"]["id"],
            "class_name": case["element"]["class_name"],
            "outer_html": case["element"]["outer_html"],
            "text": case["element"]["text"],
            "xpath": case["element"]["xpath"],
            "selector": case["element"]["selector"]
        },
        "user_instruction": case["instruction"],
        "auto_apply": True
    }
    
    try:
        print("⏳ 发送请求...")
        response = await client.post(
            f"{API_BASE_URL}/api/v1/code/modify",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=120.0
        )
        
        print(f"📡 状态码: {response.status_code}")
        
        # 解析 JSON
        try:
            result = response.json()
        except json.JSONDecodeError as e:
            print_error(f"JSON 解析失败: {e}")
            print(f"原始响应:\n{response.text[:500]}")
            return False
        
        # 显示结果
        if result.get("success"):
            print_success("修改成功!")
            
            data = result.get("data", {})
            
            # 摘要
            summary = data.get("summary", "无")
            print(f"\n📋 摘要: {summary[:100]}...")
            
            # 变更文件
            files = data.get("files_changed", [])
            print(f"📁 变更文件 ({len(files)} 个):")
            for f in files:
                print(f"   - {f}")
            
            # Diff 统计
            diff = data.get("diff", "")
            if diff:
                added = diff.count("\n+")
                removed = diff.count("\n-")
                print(f"\n📊 Diff 统计: +{added} 行, -{removed} 行")
            
            return True
        else:
            print_error(f"修改失败: {result.get('error', '未知错误')}")
            return False
            
    except httpx.TimeoutException:
        print_error("请求超时: LLM 响应时间过长")
        return False
    except Exception as e:
        print_error(f"异常: {e}")
        return False


async def test_all_cases():
    """测试所有用例"""
    print_separator()
    print("🚀 多文件多元素批量测试")
    print_separator()
    print(f"📋 共 {len(TEST_CASES)} 个测试用例\n")
    
    results = []
    
    async with httpx.AsyncClient() as client:
        for i, case in enumerate(TEST_CASES, 1):
            print(f"\n[{i}/{len(TEST_CASES)}] ", end="")
            success = await test_modify_case(case, client)
            results.append({
                "name": case["name"],
                "file": case["file"],
                "success": success
            })
    
    # 汇总报告
    print_separator()
    print("📊 测试结果汇总")
    print_separator()
    
    passed = sum(1 for r in results if r["success"])
    failed = len(results) - passed
    
    print(f"\n总计: {len(results)} 个测试")
    print(f"✅ 通过: {passed}")
    print(f"❌ 失败: {failed}")
    print()
    
    # 详细结果
    for r in results:
        status = "✅" if r["success"] else "❌"
        print(f"{status} {r['name']}")
        print(f"   文件: {r['file']}")
    
    print_separator()
    
    if failed == 0:
        print_success("所有测试通过!")
    else:
        print_warning(f"有 {failed} 个测试失败")
    
    return failed == 0


async def test_custom():
    """自定义测试"""
    print_separator()
    print("🔧 自定义测试")
    print_separator()
    
    # 列出可用文件
    print("\n可用测试文件:")
    for i, case in enumerate(TEST_CASES, 1):
        print(f"{i}. {case['name']} ({case['file']})")
    
    print("\n请输入要测试的编号 (1-{}), 或输入 0 手动指定:".format(len(TEST_CASES)))
    
    try:
        choice = int(input("> ").strip())
        
        if choice == 0:
            # 手动输入
            print("\n请输入文件路径 (相对于 frontend 目录):")
            file_path = input("> ").strip()
            print("请输入行号:")
            line = int(input("> ").strip())
            print("请输入修改指令:")
            instruction = input("> ").strip()
            
            case = {
                "name": "自定义测试",
                "file": file_path,
                "line": line,
                "instruction": instruction,
                "element": {
                    "tag": "div",
                    "id": "",
                    "class_name": "",
                    "outer_html": "<div>自定义元素</div>",
                    "text": "自定义元素",
                    "xpath": "//div",
                    "selector": "div"
                }
            }
        elif 1 <= choice <= len(TEST_CASES):
            case = TEST_CASES[choice - 1]
            print(f"\n已选择: {case['name']}")
            print(f"当前指令: {case['instruction']}")
            print("请输入新的修改指令 (直接回车使用默认):")
            new_instruction = input("> ").strip()
            if new_instruction:
                case = case.copy()
                case["instruction"] = new_instruction
        else:
            print_error("无效选择")
            return
        
        async with httpx.AsyncClient() as client:
            await test_modify_case(case, client)
            
    except ValueError:
        print_error("请输入有效数字")
    except Exception as e:
        print_error(f"错误: {e}")


# ============================================
# 主函数
# ============================================

async def main():
    """主函数"""
    print_separator()
    print("🧪 OmniFlowAI 多文件快速修改测试工具")
    print_separator()
    
    # 检查后端
    print("\n🔍 检查后端服务...")
    if not check_backend():
        print_error("后端服务未启动!")
        print_info("请先运行: python run_server.py")
        return 1
    print_success("后端服务运行中\n")
    
    # 显示菜单
    print("请选择测试模式:")
    print("1. 运行所有测试用例")
    print("2. 自定义测试")
    print("3. 退出")
    print_separator()
    
    choice = input("\n请选择 (1-3): ").strip()
    
    if choice == "1":
        success = await test_all_cases()
        return 0 if success else 1
    elif choice == "2":
        await test_custom()
        return 0
    elif choice == "3":
        print("👋 再见!")
        return 0
    else:
        print_error("无效选择")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n👋 用户取消")
        sys.exit(0)
    except Exception as e:
        print_error(f"程序异常: {e}")
        import traceback
        print(traceback.format_exc())
        sys.exit(1)
