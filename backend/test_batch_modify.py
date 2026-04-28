"""
批量代码修改功能测试脚本 - 测试 /api/v1/code/modify-batch

使用方法:
    python test_batch_modify.py

功能:
    1. 测试批量修改多个文件
    2. 测试跨文件元素修改
    3. 验证批量修改结果汇总
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
# 测试用例
# ============================================

# 测试用例 1: 同一文件多个元素
TEST_CASE_SINGLE_FILE = {
    "name": "同一文件多个元素",
    "description": "修改 Hero.tsx 中的标题和副标题",
    "files": [
        {
            "file": "src/pages/Landing/sections/Hero.tsx",
            "line": 45,
            "column": 8,
            "element_tag": "h1",
            "element_id": "hero-title",
            "element_class": "text-5xl font-bold",
            "element_html": '<h1 class="text-5xl font-bold">研发流程引擎</h1>',
            "element_text": "研发流程引擎"
        },
        {
            "file": "src/pages/Landing/sections/Hero.tsx",
            "line": 55,
            "column": 8,
            "element_tag": "p",
            "element_id": "",
            "element_class": "text-xl text-white/60",
            "element_html": '<p class="text-xl text-white/60">新一代企业级 AI 研发平台</p>',
            "element_text": "新一代企业级 AI 研发平台"
        }
    ],
    "instruction": "将所有的'研发'改为'开发'"
}

# 测试用例 2: 跨文件修改
TEST_CASE_MULTI_FILE = {
    "name": "跨文件修改",
    "description": "修改 Hero.tsx 和 Features.tsx 的标题",
    "files": [
        {
            "file": "src/pages/Landing/sections/Hero.tsx",
            "line": 45,
            "column": 8,
            "element_tag": "h1",
            "element_id": "",
            "element_class": "text-5xl font-bold",
            "element_html": '<h1 class="text-5xl font-bold">研发流程引擎</h1>',
            "element_text": "研发流程引擎"
        },
        {
            "file": "src/pages/Landing/sections/Features.tsx",
            "line": 30,
            "column": 8,
            "element_tag": "h2",
            "element_id": "",
            "element_class": "text-3xl font-bold",
            "element_html": '<h2 class="text-3xl font-bold">核心功能</h2>',
            "element_text": "核心功能"
        }
    ],
    "instruction": "将'研发'改为'开发'，将'核心功能'改为'主要功能'"
}

# 测试用例 3: 样式批量修改
TEST_CASE_STYLE_BATCH = {
    "name": "批量样式修改",
    "description": "统一修改多个按钮的样式",
    "files": [
        {
            "file": "src/pages/Landing/sections/Hero.tsx",
            "line": 60,
            "column": 8,
            "element_tag": "button",
            "element_id": "",
            "element_class": "px-6 py-4 bg-blue-500",
            "element_html": '<button class="px-6 py-4 bg-blue-500">开始使用</button>',
            "element_text": "开始使用"
        },
        {
            "file": "src/components/Layout/Navbar.tsx",
            "line": 25,
            "column": 8,
            "element_tag": "button",
            "element_id": "",
            "element_class": "px-4 py-2 bg-green-500",
            "element_html": '<button class="px-4 py-2 bg-green-500">登录</button>',
            "element_text": "登录"
        }
    ],
    "instruction": "将所有按钮改为圆角（rounded-lg）并使用蓝色主题（bg-blue-600）"
}


# ============================================
# 核心测试函数
# ============================================

async def test_batch_modify(test_case: dict, client: httpx.AsyncClient) -> bool:
    """测试批量修改"""
    print_separator()
    print(f"📝 {test_case['name']}")
    print(f"💬 {test_case['description']}")
    print(f"📋 涉及 {len(test_case['files'])} 个元素:")
    for i, f in enumerate(test_case['files'], 1):
        print(f"   {i}. {f['file']}:{f['line']} <{f['element_tag']}>{f['element_text'][:20]}</{f['element_tag']}>")
    print(f"💡 指令: {test_case['instruction']}")
    
    payload = {
        "files": test_case["files"],
        "user_instruction": test_case["instruction"],
        "auto_apply": True  # 自动应用变更到文件系统
    }
    
    try:
        print("\n⏳ 发送批量修改请求...")
        response = await client.post(
            f"{API_BASE_URL}/api/v1/code/modify-batch",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=180.0  # 批量修改可能需要更长时间
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
            data = result.get("data", {})
            
            print_success("批量修改完成!")
            print(f"\n📊 结果汇总:")
            print(f"   总文件数: {data.get('total_files', 0)}")
            print(f"   ✅ 成功: {data.get('success_files', 0)}")
            print(f"   ❌ 失败: {data.get('failed_files', 0)}")
            print(f"\n📋 摘要: {data.get('summary', '无')}")
            
            # 详细结果
            results = data.get("results", [])
            print(f"\n📁 详细结果:")
            for r in results:
                status = "✅" if r["success"] else "❌"
                print(f"   {status} {r['file']}")
                if not r["success"] and r.get("error"):
                    print(f"      错误: {r['error']}")
                elif r.get("diff"):
                    # 统计 diff 行数
                    added = r["diff"].count("\n+")
                    removed = r["diff"].count("\n-")
                    print(f"      变更: +{added} -{removed}")
            
            # 变更已自动应用
            print_success(f"变更已自动应用到文件系统!")
            
            return data.get("failed_files", 0) == 0
        else:
            print_error(f"批量修改失败: {result.get('error', '未知错误')}")
            return False
            
    except httpx.TimeoutException:
        print_error("请求超时: LLM 响应时间过长")
        return False
    except Exception as e:
        print_error(f"异常: {e}")
        import traceback
        print(traceback.format_exc())
        return False


async def test_all_cases():
    """测试所有用例"""
    test_cases = [
        TEST_CASE_SINGLE_FILE,
        TEST_CASE_MULTI_FILE,
        TEST_CASE_STYLE_BATCH,
    ]
    
    print_separator()
    print("🚀 批量代码修改功能测试")
    print_separator()
    print(f"📋 共 {len(test_cases)} 个测试用例\n")
    
    results = []
    
    async with httpx.AsyncClient() as client:
        for i, case in enumerate(test_cases, 1):
            print(f"\n[{i}/{len(test_cases)}] ")
            success = await test_batch_modify(case, client)
            results.append({
                "name": case["name"],
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
    
    for r in results:
        status = "✅ 通过" if r["success"] else "❌ 失败"
        print(f"{status}: {r['name']}")
    
    print_separator()
    
    if failed == 0:
        print_success("所有测试通过!")
    else:
        print_warning(f"有 {failed} 个测试失败")
    
    return failed == 0


async def test_custom():
    """自定义测试"""
    print_separator()
    print("🔧 自定义批量修改测试")
    print_separator()
    
    print("\n请输入要修改的文件数量 (1-5):")
    try:
        count = int(input("> ").strip())
        if count < 1 or count > 5:
            print_error("数量必须在 1-5 之间")
            return
    except ValueError:
        print_error("请输入有效数字")
        return
    
    files = []
    for i in range(count):
        print(f"\n--- 元素 {i+1}/{count} ---")
        print("文件路径 (相对于 frontend 目录):")
        file_path = input("> ").strip()
        print("行号:")
        line = int(input("> ").strip())
        print("元素标签 (如: h1, button, div):")
        tag = input("> ").strip()
        print("元素文本内容:")
        text = input("> ").strip()
        
        files.append({
            "file": file_path,
            "line": line,
            "column": 8,
            "element_tag": tag,
            "element_id": "",
            "element_class": "",
            "element_html": f"<{tag}>{text}</{tag}>",
            "element_text": text
        })
    
    print("\n修改指令:")
    instruction = input("> ").strip()
    
    test_case = {
        "name": "自定义测试",
        "description": f"修改 {count} 个元素",
        "files": files,
        "instruction": instruction
    }
    
    async with httpx.AsyncClient() as client:
        await test_batch_modify(test_case, client)


async def main():
    """主函数"""
    print_separator()
    print("🧪 OmniFlowAI 批量代码修改测试工具")
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
    print("1. 运行所有预设测试用例")
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
