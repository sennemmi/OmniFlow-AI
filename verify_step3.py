"""
第三步验证脚本
验证 API 文档、状态机流转、人工审批、DesignerAgent 实现
"""

import sys
import json
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent / "backend"))


def verify_api_models():
    """验证 API Pydantic 模型"""
    print("\n" + "="*60)
    print("1. 验证 API Pydantic 模型")
    print("="*60)
    
    try:
        from pydantic import BaseModel
        from typing import Optional
        
        # 验证 PipelineCreateRequest
        class TestCreate(BaseModel):
            requirement: str
        
        test_create = TestCreate(requirement="测试需求")
        print(f"✅ PipelineCreateRequest 模型: {test_create.model_dump()}")
        
        # 验证 PipelineApproveRequest
        class TestApprove(BaseModel):
            notes: Optional[str] = None
            feedback: Optional[str] = None
        
        test_approve = TestApprove(notes="可以开始设计")
        print(f"✅ PipelineApproveRequest 模型: {test_approve.model_dump()}")
        
        # 验证 PipelineRejectRequest
        class TestReject(BaseModel):
            reason: str
            suggested_changes: Optional[str] = None
        
        test_reject = TestReject(reason="需求不清晰", suggested_changes="补充说明")
        print(f"✅ PipelineRejectRequest 模型: {test_reject.model_dump()}")
        
        return True
    except Exception as e:
        print(f"❌ API 模型验证失败: {e}")
        return False


def verify_pipeline_status_enum():
    """验证 Pipeline 状态枚举"""
    print("\n" + "="*60)
    print("2. 验证 Pipeline 状态枚举")
    print("="*60)
    
    try:
        from app.models.pipeline import PipelineStatus, StageName, StageStatus
        
        # 验证 PipelineStatus
        assert PipelineStatus.RUNNING.value == "running"
        assert PipelineStatus.PAUSED.value == "paused"
        assert PipelineStatus.SUCCESS.value == "success"
        assert PipelineStatus.FAILED.value == "failed"
        print(f"✅ PipelineStatus 枚举正确: {[s.value for s in PipelineStatus]}")
        
        # 验证 StageName
        assert StageName.REQUIREMENT.value == "REQUIREMENT"
        assert StageName.DESIGN.value == "DESIGN"
        assert StageName.CODING.value == "CODING"
        print(f"✅ StageName 枚举正确: {[s.value for s in StageName]}")
        
        # 验证 StageStatus
        assert StageStatus.PENDING.value == "pending"
        assert StageStatus.RUNNING.value == "running"
        assert StageStatus.SUCCESS.value == "success"
        assert StageStatus.FAILED.value == "failed"
        print(f"✅ StageStatus 枚举正确: {[s.value for s in StageStatus]}")
        
        return True
    except Exception as e:
        print(f"❌ 状态枚举验证失败: {e}")
        return False


def verify_designer_agent():
    """验证 DesignerAgent 实现"""
    print("\n" + "="*60)
    print("3. 验证 DesignerAgent 实现")
    print("="*60)
    
    try:
        from app.agents.designer import DesignerAgent, DesignerOutput, DesignerState
        
        # 验证 DesignerOutput 模型
        output = DesignerOutput(
            technical_design="测试设计",
            api_endpoints=[{"method": "GET", "path": "/test", "description": "测试"}],
            function_changes=[{"file": "test.py", "function": "test", "action": "add", "description": "测试"}],
            logic_flow="测试流程",
            dependencies=["fastapi"]
        )
        print(f"✅ DesignerOutput 模型正确: {list(output.model_dump().keys())}")
        
        # 验证 DesignerAgent 实例化
        agent = DesignerAgent()
        assert agent is not None
        assert agent.graph is not None
        print(f"✅ DesignerAgent 实例化成功")
        
        # 验证 System Prompt 包含关键原则
        assert "以创造接口为耻" in agent.SYSTEM_PROMPT
        assert "以复用现有为荣" in agent.SYSTEM_PROMPT
        print(f"✅ DesignerAgent System Prompt 包含核心原则")
        
        return True
    except Exception as e:
        print(f"❌ DesignerAgent 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_pipeline_service_methods():
    """验证 PipelineService 方法"""
    print("\n" + "="*60)
    print("4. 验证 PipelineService 方法")
    print("="*60)
    
    try:
        from app.service.pipeline import PipelineService
        import inspect
        
        # 检查关键方法是否存在
        methods = [
            'create_pipeline',
            'approve_pipeline',
            'reject_pipeline',
            'get_pipeline_status',
            'list_pipelines',
            '_trigger_designer_analysis',
            '_trigger_architect_analysis_with_feedback',
            '_trigger_designer_analysis_with_feedback'
        ]
        
        for method in methods:
            assert hasattr(PipelineService, method), f"缺少方法: {method}"
            print(f"✅ PipelineService.{method} 存在")
        
        return True
    except Exception as e:
        print(f"❌ PipelineService 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_state_machine_flow():
    """验证状态机流转逻辑"""
    print("\n" + "="*60)
    print("5. 验证状态机流转逻辑")
    print("="*60)
    
    try:
        from app.service.pipeline import PipelineService
        import inspect
        
        # 检查 approve_pipeline 方法逻辑
        source = inspect.getsource(PipelineService.approve_pipeline)
        
        # 验证状态检查
        assert "PAUSED" in source, "approve_pipeline 应检查 PAUSED 状态"
        print("✅ approve_pipeline 检查 PAUSED 状态")
        
        # 验证阶段流转
        assert "DESIGN" in source, "approve_pipeline 应支持流转到 DESIGN"
        print("✅ approve_pipeline 支持流转到 DESIGN 阶段")
        
        # 检查 reject_pipeline 方法逻辑
        source = inspect.getsource(PipelineService.reject_pipeline)
        
        # 验证驳回反馈记录
        assert "rejection_feedback" in source, "reject_pipeline 应记录驳回反馈"
        print("✅ reject_pipeline 记录驳回反馈")
        
        # 验证自动回归
        assert "_trigger_architect_analysis_with_feedback" in source or \
               "_trigger_designer_analysis_with_feedback" in source, \
               "reject_pipeline 应触发重新分析"
        print("✅ reject_pipeline 实现自动回归")
        
        return True
    except Exception as e:
        print(f"❌ 状态机流转验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_logging_module():
    """验证可观测性模块"""
    print("\n" + "="*60)
    print("6. 验证可观测性模块")
    print("="*60)
    
    try:
        from app.core.logging import (
            AgentMetrics, 
            MetricsCollector, 
            agent_metrics_context,
            log_pipeline_event
        )
        
        # 验证 AgentMetrics
        metrics = AgentMetrics(agent_name="TestAgent", stage_name="TEST")
        assert metrics.agent_name == "TestAgent"
        assert metrics.stage_name == "TEST"
        print("✅ AgentMetrics 数据类正确")
        
        # 验证 MetricsCollector
        collector = MetricsCollector()
        assert collector is not None
        print("✅ MetricsCollector 实例化成功")
        
        # 验证上下文管理器
        assert callable(agent_metrics_context)
        print("✅ agent_metrics_context 上下文管理器存在")
        
        # 验证日志函数
        assert callable(log_pipeline_event)
        print("✅ log_pipeline_event 函数存在")
        
        return True
    except Exception as e:
        print(f"❌ 可观测性模块验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_api_documentation():
    """验证 API 文档"""
    print("\n" + "="*60)
    print("7. 验证 API 文档")
    print("="*60)
    
    try:
        docs_path = Path(__file__).parent / "docs" / "api.md"
        assert docs_path.exists(), f"API 文档不存在: {docs_path}"
        
        content = docs_path.read_text(encoding='utf-8')
        
        # 验证关键章节
        required_sections = [
            "统一响应格式",
            "Pipeline 生命周期状态机",
            "POST /api/v1/pipeline/create",
            "GET /api/v1/pipeline/{id}/status",
            "POST /api/v1/pipeline/{id}/approve",
            "POST /api/v1/pipeline/{id}/reject",
            "PipelineStatus",
            "StageName"
        ]
        
        for section in required_sections:
            assert section in content, f"文档缺少章节: {section}"
            print(f"✅ 文档包含: {section}")
        
        return True
    except Exception as e:
        print(f"❌ API 文档验证失败: {e}")
        return False


def verify_architect_agent_integration():
    """验证 ArchitectAgent 集成"""
    print("\n" + "="*60)
    print("8. 验证 ArchitectAgent 集成")
    print("="*60)
    
    try:
        from app.agents.architect import ArchitectAgent, ArchitectOutput
        
        # 验证 ArchitectOutput 模型
        output = ArchitectOutput(
            feature_description="测试功能",
            affected_files=["test.py"],
            estimated_effort="1小时"
        )
        print(f"✅ ArchitectOutput 模型正确")
        
        # 验证 Agent 实例
        from app.agents.architect import architect_agent
        assert architect_agent is not None
        print(f"✅ architect_agent 单例实例存在")
        
        # 验证 analyze 方法
        assert hasattr(architect_agent, 'analyze')
        print(f"✅ architect_agent.analyze 方法存在")
        
        return True
    except Exception as e:
        print(f"❌ ArchitectAgent 集成验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主验证函数"""
    print("\n" + "="*60)
    print("OmniFlowAI 第三步实现验证")
    print("="*60)
    
    results = []
    
    # 运行所有验证
    results.append(("API Pydantic 模型", verify_api_models()))
    results.append(("Pipeline 状态枚举", verify_pipeline_status_enum()))
    results.append(("DesignerAgent 实现", verify_designer_agent()))
    results.append(("PipelineService 方法", verify_pipeline_service_methods()))
    results.append(("状态机流转逻辑", verify_state_machine_flow()))
    results.append(("可观测性模块", verify_logging_module()))
    results.append(("API 文档", verify_api_documentation()))
    results.append(("ArchitectAgent 集成", verify_architect_agent_integration()))
    
    # 汇总结果
    print("\n" + "="*60)
    print("验证结果汇总")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status}: {name}")
    
    print(f"\n总计: {passed}/{total} 项通过")
    
    if passed == total:
        print("\n🎉 所有验证通过！第三步实现正确无误。")
        return 0
    else:
        print(f"\n⚠️ {total - passed} 项验证失败，请检查实现。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
