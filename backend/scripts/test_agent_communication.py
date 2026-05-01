#!/usr/bin/env python3
"""
轻量级 Agent 通信验证脚本

测试 ArchitectAgent 和 DesignerAgent 的输入输出，验证：
1. ArchitectAgent 是否正确输出 acceptance_criteria 和 required_symbols
2. DesignerAgent 是否能正确接收 ArchitectAgent 的输出
3. DesignerAgent 的 design 方法是否正常工作
4. 验收标准与接口契约是否正确对齐

使用方法:
    cd backend
    python scripts/test_agent_communication.py
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Any

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.architect import architect_agent
from app.agents.designer import designer_agent
from app.core.config import settings


# 测试用的简单需求
TEST_REQUIREMENT = "实现一个用户登录功能，要求支持邮箱和密码验证，返回 JWT token。"

# 模拟的项目文件树
TEST_FILE_TREE = {
    "app": {
        "api": {
            "v1": {
                "auth.py": None,
                "users.py": None
            }
        },
        "service": {
            "auth_service.py": None,
            "user_service.py": None
        },
        "models": {
            "user.py": None
        }
    }
}


async def test_architect_agent() -> Dict[str, Any]:
    """
    测试 ArchitectAgent
    
    验证输出是否包含：
    - feature_description
    - acceptance_criteria（关键）
    - required_symbols（关键）
    - affected_files
    """
    print("=" * 80)
    print("🔍 测试 1: ArchitectAgent 输出验证")
    print("=" * 80)
    print(f"\n输入需求: {TEST_REQUIREMENT}\n")
    
    try:
        result = await architect_agent.analyze(
            requirement=TEST_REQUIREMENT,
            file_tree=TEST_FILE_TREE,
            pipeline_id=99999,
            project_path="/workspace/backend"
        )
        
        if not result.get("success"):
            print(f"❌ ArchitectAgent 执行失败: {result.get('error')}")
            return None
        
        output = result.get("output", {})
        
        print("✅ ArchitectAgent 执行成功\n")
        print("输出内容:")
        print(f"  - feature_description: {output.get('feature_description', 'N/A')}")
        print(f"  - estimated_effort: {output.get('estimated_effort', 'N/A')}")
        
        # 验证关键字段
        acceptance_criteria = output.get("acceptance_criteria", [])
        required_symbols = output.get("required_symbols", [])
        affected_files = output.get("affected_files", [])
        
        print(f"\n  - acceptance_criteria ({len(acceptance_criteria)} 条):")
        for i, criteria in enumerate(acceptance_criteria, 1):
            print(f"    {i}. {criteria}")
        
        print(f"\n  - required_symbols ({len(required_symbols)} 个):")
        for sym in required_symbols:
            print(f"    - {sym.get('name')} ({sym.get('type')}) in {sym.get('module')}")
        
        print(f"\n  - affected_files ({len(affected_files)} 个):")
        for f in affected_files:
            print(f"    - {f}")
        
        # 关键验证
        if not acceptance_criteria:
            print("\n⚠️ 警告: acceptance_criteria 为空，这将导致 DesignerAgent 无法执行契约对齐！")
        
        if not required_symbols:
            print("\n⚠️ 警告: required_symbols 为空，DesignerAgent 将没有符号对齐的约束！")
        
        return output
        
    except Exception as e:
        print(f"❌ ArchitectAgent 异常: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_designer_agent(architect_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    测试 DesignerAgent

    验证：
    - 是否正确接收 architect_output
    - 是否输出 interface_specs
    - 是否输出 contract_alignment（关键）
    - contract_alignment 是否与 acceptance_criteria 对齐
    """
    print("\n" + "=" * 80)
    print("🔍 测试 2: DesignerAgent 输出验证（Instructor 模式）")
    print("=" * 80)

    try:
        result = await designer_agent.design(
            architect_output=architect_output,
            file_tree=TEST_FILE_TREE,
            pipeline_id=99999,
            max_retries=2
        )
        
        print(f"\n执行结果:")
        print(f"  - success: {result.get('success')}")
        print(f"  - error: {result.get('error')}")
        
        if not result.get("success"):
            print(f"\n❌ DesignerAgent 执行失败")
            return None
        
        output = result.get("output", {})
        
        print("\n✅ DesignerAgent 执行成功\n")
        print(f"  - technical_design: {output.get('technical_design', 'N/A')[:100]}...")
        
        # 验证 interface_specs
        interface_specs = output.get("interface_specs", [])
        print(f"\n  - interface_specs ({len(interface_specs)} 个):")
        for spec in interface_specs:
            print(f"    - {spec.get('symbol_name')} in {spec.get('module')}")
            print(f"      signature: {spec.get('signature')}")
        
        # 验证 contract_alignment（关键）
        contract_alignment = output.get("contract_alignment", [])
        print(f"\n  - contract_alignment ({len(contract_alignment)} 个):")
        for item in contract_alignment:
            print(f"    - 标准: {item.get('acceptance_criteria', 'N/A')[:50]}...")
            print(f"      接口: {item.get('interface_specs', [])}")
            print(f"      理由: {item.get('mapping_reason', 'N/A')[:50]}...")
        
        # 对齐验证
        acceptance_criteria = architect_output.get("acceptance_criteria", [])
        print(f"\n📊 对齐验证:")
        print(f"  - Architect 验收标准数: {len(acceptance_criteria)}")
        print(f"  - Designer 契约映射数: {len(contract_alignment)}")
        
        if len(contract_alignment) == len(acceptance_criteria):
            print("  ✅ 数量对齐")
        else:
            print(f"  ❌ 数量不对齐 (期望 {len(acceptance_criteria)}, 实际 {len(contract_alignment)})")
        
        # 验证每条验收标准都有映射
        covered_criteria = {item.get('acceptance_criteria', '').strip() for item in contract_alignment}
        missing = [c for c in acceptance_criteria if c.strip() not in covered_criteria]
        
        if not missing:
            print("  ✅ 所有验收标准都有映射")
        else:
            print(f"  ❌ 缺失映射的验收标准: {missing}")
        
        return output
        
    except Exception as e:
        print(f"\n❌ DesignerAgent 异常: {e}")
        import traceback
        traceback.print_exc()
        return None





async def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("🚀 OmniFlowAI Agent 通信验证脚本")
    print("=" * 80)
    print(f"\n测试模型: {settings.llm_model}")
    print(f"测试需求: {TEST_REQUIREMENT}\n")
    
    # 测试 1: ArchitectAgent
    architect_output = await test_architect_agent()
    
    if not architect_output:
        print("\n❌ ArchitectAgent 测试失败，无法继续")
        return
    
    # 测试 2: DesignerAgent
    designer_output = await test_designer_agent(architect_output)

    if not designer_output:
        print("\n⚠️ DesignerAgent 测试失败")

    # 总结
    print("\n" + "=" * 80)
    print("📋 测试总结")
    print("=" * 80)
    
    if architect_output:
        print("✅ ArchitectAgent: 通过")
        has_criteria = bool(architect_output.get("acceptance_criteria"))
        has_symbols = bool(architect_output.get("required_symbols"))
        print(f"   - 包含 acceptance_criteria: {'是' if has_criteria else '否'}")
        print(f"   - 包含 required_symbols: {'是' if has_symbols else '否'}")
    else:
        print("❌ ArchitectAgent: 失败")
    
    if designer_output:
        print("✅ DesignerAgent: 通过")
        has_alignment = bool(designer_output.get("contract_alignment"))
        print(f"   - 包含 contract_alignment: {'是' if has_alignment else '否'}")
    else:
        print("❌ DesignerAgent: 失败")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
