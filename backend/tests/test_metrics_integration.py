"""
独立测试脚本：验证真实 LLM 调用的指标采集

运行方式：
    cd backend
    python -m tests.test_metrics_integration
"""
import asyncio
import sys
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.architect import architect_agent
from app.agents.designer import designer_agent
from app.agents.coder import coder_agent
from app.core.config import settings


async def test_architect_agent_metrics():
    """测试 ArchitectAgent 的指标采集"""
    print("\n" + "="*60)
    print("测试 ArchitectAgent 指标采集")
    print("="*60)

    result = await architect_agent.analyze(
        requirement="创建一个简单的用户登录功能",
        file_tree={"backend/app": ["main.py"]},
        element_context=None,
        pipeline_id=9999
    )

    print(f"\n返回结果键: {result.keys()}")
    print(f"success: {result.get('success')}")
    print(f"input_tokens: {result.get('input_tokens')}")
    print(f"output_tokens: {result.get('output_tokens')}")
    print(f"duration_ms: {result.get('duration_ms')}")
    print(f"retry_count: {result.get('retry_count')}")

    # 验证
    assert result.get('duration_ms', 0) > 0, "Duration must be > 0"
    print("\n✅ ArchitectAgent 指标测试通过")
    return result


async def test_designer_agent_metrics():
    """测试 DesignerAgent 的指标采集"""
    print("\n" + "="*60)
    print("测试 DesignerAgent 指标采集")
    print("="*60)

    architect_output = {
        "feature_description": "创建一个简单的用户登录功能",
        "affected_files": ["backend/app/auth.py"],
        "api_endpoints": [{"path": "/api/login", "method": "POST"}]
    }

    result = await designer_agent.design(
        architect_output=architect_output,
        file_tree={"backend/app": ["main.py"]},
        related_code_context=None,
        full_files_context=None,
        pipeline_id=9999
    )

    print(f"\n返回结果键: {result.keys()}")
    print(f"success: {result.get('success')}")
    print(f"input_tokens: {result.get('input_tokens')}")
    print(f"output_tokens: {result.get('output_tokens')}")
    print(f"duration_ms: {result.get('duration_ms')}")
    print(f"retry_count: {result.get('retry_count')}")

    # 验证
    assert result.get('duration_ms', 0) > 0, "Duration must be > 0"
    print("\n✅ DesignerAgent 指标测试通过")
    return result


async def test_coder_agent_metrics():
    """测试 CoderAgent 的指标采集"""
    print("\n" + "="*60)
    print("测试 CoderAgent 指标采集")
    print("="*60)

    design_output = {
        "feature_description": "创建一个简单的用户登录功能",
        "affected_files": ["backend/app/auth.py"],
        "api_endpoints": [{"path": "/api/login", "method": "POST"}],
        "technical_design": "使用 FastAPI 创建登录接口"
    }

    target_files = {}

    result = await coder_agent.generate_code(
        design_output=design_output,
        target_files=target_files,
        pipeline_id=9999
    )

    print(f"\n返回结果键: {result.keys()}")
    print(f"success: {result.get('success')}")
    print(f"input_tokens: {result.get('input_tokens')}")
    print(f"output_tokens: {result.get('output_tokens')}")
    print(f"duration_ms: {result.get('duration_ms')}")
    print(f"retry_count: {result.get('retry_count')}")

    # 验证
    assert result.get('duration_ms', 0) > 0, "Duration must be > 0"
    print("\n✅ CoderAgent 指标测试通过")
    return result


async def main():
    """主函数"""
    print("\n" + "="*60)
    print("LLM 指标采集集成测试")
    print("="*60)
    print(f"\n当前配置:")
    print(f"  USE_MODELSCOPE: {settings.USE_MODELSCOPE}")
    print(f"  llm_model: {settings.llm_model}")
    print(f"  llm_api_base: {settings.llm_api_base}")

    try:
        # 测试 ArchitectAgent
        await test_architect_agent_metrics()

        # 测试 DesignerAgent
        await test_designer_agent_metrics()

        # 测试 CoderAgent
        await test_coder_agent_metrics()

        print("\n" + "="*60)
        print("所有测试通过！")
        print("="*60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
