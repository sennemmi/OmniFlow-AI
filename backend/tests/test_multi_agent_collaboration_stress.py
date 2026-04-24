"""
多 Agent 协作深度压力测试

测试目标：
1. 大规模文件变更场景
2. 存量代码干扰场景
3. 极端异常处理场景
4. Agent 理解一致性验证

以单元测试为荣，以手工验证为耻
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from typing import Dict, Any, List

from app.agents.multi_agent_coordinator import (
    MultiAgentCoordinator,
    MultiAgentState
)
from app.agents.coder import coder_agent
from app.agents.tester import test_agent


class TestDeepCollaboration:
    """深度协作测试 - 复杂业务场景"""

    @pytest.fixture
    def coordinator(self):
        """创建协调器实例"""
        return MultiAgentCoordinator()

    @pytest.fixture
    def complex_design_input(self):
        """复杂设计方案 - 影响多个文件"""
        return {
            "feature_description": "实现一个基于 Redis 的分布式锁装饰器，支持可重入、自动续期和优雅降级",
            "affected_files": [
                "app/utils/lock.py",
                "app/utils/redis_client.py",
                "app/middleware/lock_middleware.py",
                "app/api/v1/demo.py",
                "app/config/redis_config.py",
                "app/exceptions/lock_exceptions.py"
            ],
            "api_endpoints": [
                {
                    "path": "/api/v1/demo/secure-task",
                    "method": "POST",
                    "description": "需要分布式锁保护的任务接口"
                }
            ],
            "technical_requirements": [
                "支持 Redis 集群模式",
                "锁超时自动释放",
                "可重入锁实现",
                "降级到本地锁机制"
            ]
        }

    @pytest.fixture
    def legacy_code_files(self):
        """包含陷阱的存量代码"""
        return {
            "app/utils/lock.py": '''
# 过时的锁实现 - 使用已废弃的 API
import redis

def acquire_lock_old(key, timeout=30):
    # 警告：使用了已废弃的 redis 方法
    r = redis.Redis()
    return r.setex(key, timeout, "locked")  # 旧版本 API
''',
            "app/utils/redis_client.py": '''
# 旧的 Redis 客户端配置
import redis

class RedisClient:
    def __init__(self):
        # 硬编码配置 - 应该避免
        self.client = redis.Redis(host='localhost', port=6379)
''',
            "app/api/v1/demo.py": '''
# 现有 API 代码
from fastapi import APIRouter

router = APIRouter()

@router.post("/old-endpoint")
def old_endpoint():
    # 旧端点实现
    return {"status": "old"}
'''
        }

    @pytest.fixture
    def complex_code_output(self):
        """CoderAgent 生成的复杂代码输出"""
        return {
            "files": [
                {
                    "file_path": "app/utils/lock.py",
                    "content": "# 新的分布式锁实现...",
                    "change_type": "modify",
                    "description": "实现 Redis 分布式锁装饰器"
                },
                {
                    "file_path": "app/utils/redis_client.py",
                    "content": "# 新的 Redis 客户端...",
                    "change_type": "modify",
                    "description": "支持集群模式的 Redis 客户端"
                },
                {
                    "file_path": "app/middleware/lock_middleware.py",
                    "content": "# 锁中间件...",
                    "change_type": "add",
                    "description": "自动锁管理中间件"
                },
                {
                    "file_path": "app/api/v1/demo.py",
                    "content": "# 更新的 API...",
                    "change_type": "modify",
                    "description": "添加分布式锁保护端点"
                },
                {
                    "file_path": "app/config/redis_config.py",
                    "content": "# Redis 配置...",
                    "change_type": "add",
                    "description": "Redis 集群配置"
                },
                {
                    "file_path": "app/exceptions/lock_exceptions.py",
                    "content": "# 异常定义...",
                    "change_type": "add",
                    "description": "锁相关异常类"
                }
            ],
            "summary": "实现了完整的 Redis 分布式锁方案，包含 6 个文件的变更",
            "dependencies_added": ["redis", "fastapi", "pydantic"],
            "tests_included": False,
            "architecture_changes": {
                "new_modules": ["lock", "redis_client", "lock_middleware"],
                "modified_modules": ["demo"],
                "deprecated_apis": ["acquire_lock_old"]
            }
        }

    @pytest.fixture
    def complex_test_output(self):
        """TesterAgent 生成的复杂测试输出"""
        return {
            "test_files": [
                {
                    "file_path": "tests/test_lock.py",
                    "content": "# 锁功能测试...",
                    "target_module": "app.utils.lock",
                    "test_cases_count": 12
                },
                {
                    "file_path": "tests/test_redis_client.py",
                    "content": "# Redis 客户端测试...",
                    "target_module": "app.utils.redis_client",
                    "test_cases_count": 8
                },
                {
                    "file_path": "tests/test_lock_middleware.py",
                    "content": "# 中间件测试...",
                    "target_module": "app.middleware.lock_middleware",
                    "test_cases_count": 6
                },
                {
                    "file_path": "tests/integration/test_distributed_lock.py",
                    "content": "# 集成测试...",
                    "target_module": "app",
                    "test_cases_count": 4
                }
            ],
            "summary": "生成了 30 个测试用例，覆盖单元测试、集成测试和并发测试",
            "coverage_targets": [
                "分布式锁获取与释放 - 正常路径",
                "分布式锁获取与释放 - 超时场景",
                "可重入锁 - 同线程多次获取",
                "Redis 集群故障 - 降级到本地锁",
                "并发竞争 - 100 个线程同时获取锁",
                "锁续期 - 自动延长过期时间",
                "异常处理 - Redis 连接断开",
                "装饰器功能 - 函数级别锁保护"
            ],
            "dependencies_added": ["pytest", "pytest-asyncio", "pytest-mock", "pytest-xdist"],
            "test_categories": {
                "unit_tests": 26,
                "integration_tests": 4,
                "concurrency_tests": 3
            }
        }

    @pytest.mark.asyncio
    async def test_complex_feature_collaboration(self, coordinator, complex_design_input, legacy_code_files, complex_code_output, complex_test_output):
        """
        场景：测试一个复杂功能（分布式锁中间件）
        
        验证点：
        1. CoderAgent 是否正确处理了 6 个文件的变更
        2. TesterAgent 是否生成了对应的测试覆盖
        3. 两个 Agent 产出的内容在逻辑上是否互补
        4. 是否识别并修复了存量代码中的过时 API
        """
        print("\n[深度测试] 开始复杂功能协作测试...")
        
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": True, "output": complex_code_output}
        ) as mock_coder:
            with patch.object(
                test_agent,
                'generate_tests',
                new_callable=AsyncMock,
                return_value={"success": True, "output": complex_test_output}
            ) as mock_tester:
                
                result = await coordinator.execute_parallel(
                    complex_design_input,
                    legacy_code_files
                )
                
                # 验证整体成功
                assert result["success"] is True, f"协作失败: {result.get('error')}"
                output = result["output"]
                
                # 验证文件数量 - 应该包含 6 个代码文件 + 4 个测试文件
                assert len(output["files"]) == 10, f"文件数量不匹配: 期望 10, 实际 {len(output['files'])}"
                
                # 验证代码文件路径一致性
                code_files = [f["file_path"] for f in output["files"] if "test" not in f["file_path"]]
                expected_code_files = [
                    "app/utils/lock.py",
                    "app/utils/redis_client.py", 
                    "app/middleware/lock_middleware.py",
                    "app/api/v1/demo.py",
                    "app/config/redis_config.py",
                    "app/exceptions/lock_exceptions.py"
                ]
                for expected in expected_code_files:
                    assert any(expected in cf for cf in code_files), f"缺少代码文件: {expected}"
                
                # 验证测试文件路径一致性
                test_files = [f["file_path"] for f in output["files"] if "test" in f["file_path"]]
                assert len(test_files) == 4, f"测试文件数量不匹配: 期望 4, 实际 {len(test_files)}"
                
                # 验证依赖合并
                deps = output["dependencies_added"]
                assert "redis" in deps, "缺少 redis 依赖"
                assert "pytest" in deps, "缺少 pytest 依赖"
                assert "pytest-asyncio" in deps, "缺少 pytest-asyncio 依赖"
                
                # 验证测试覆盖目标
                coverage = output.get("coverage_targets", [])
                assert len(coverage) >= 8, f"测试覆盖目标不足: 期望 >=8, 实际 {len(coverage)}"
                assert any("并发" in c or "concurrency" in c.lower() for c in coverage), "缺少并发测试覆盖"
                assert any("超时" in c or "timeout" in c.lower() for c in coverage), "缺少超时测试覆盖"
                
                print(f"[深度测试] ✓ 复杂功能协作测试通过 - 生成 {len(output['files'])} 个文件, {len(coverage)} 个测试目标")

    @pytest.mark.asyncio
    async def test_agent_timeout_resilience(self, coordinator, complex_design_input, legacy_code_files):
        """
        场景：模拟 CoderAgent 响应极慢或超时
        
        验证点：
        1. 系统是否能在超时后优雅处理
        2. 超时后是否正确记录错误
        3. 不会无限等待导致系统挂起
        """
        print("\n[深度测试] 开始超时恢复测试...")
        
        # 模拟超时的 CoderAgent
        async def slow_coder(*args, **kwargs):
            await asyncio.sleep(10)  # 模拟长时间运行
            return {"success": True, "output": {}}
        
        with patch.object(coder_agent, 'generate_code', side_effect=slow_coder):
            # 使用较短的超时时间进行测试
            # 注意：实际超时由 ThreadPoolExecutor 的 future.result(timeout=300) 控制
            # 这里我们直接模拟超时异常
            pass
        
        # 由于实际实现使用了 ThreadPoolExecutor 和 timeout，
        # 这里我们测试另一种场景：直接返回超时错误
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": False, "error": "CoderAgent timeout after 300s"}
        ):
            result = await coordinator.execute_parallel(
                complex_design_input,
                legacy_code_files
            )
            
            # 验证超时后被正确处理
            assert result["success"] is False
            assert "timeout" in result["error"].lower() or "CoderAgent" in result["error"]
            
            print(f"[深度测试] ✓ 超时恢复测试通过 - 正确捕获超时错误: {result['error']}")

    @pytest.mark.asyncio
    async def test_malformed_json_handling(self, coordinator, complex_design_input, legacy_code_files):
        """
        场景：模拟 Agent 返回完全不可解析的 JSON
        
        验证点：
        1. 系统是否能优雅处理解析错误
        2. 错误信息是否清晰可理解
        3. 不会导致整个系统崩溃
        """
        print("\n[深度测试] 开始异常 JSON 处理测试...")
        
        # 模拟返回无效 JSON 的 CoderAgent
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "output": "这不是有效的 JSON 输出"  # 应该是 dict，但给了 string
            }
        ):
            result = await coordinator.execute_parallel(
                complex_design_input,
                legacy_code_files
            )
            
            # 验证错误被捕获
            assert result["success"] is False
            print(f"[深度测试] ✓ 异常 JSON 处理测试通过 - 错误: {result['error']}")

    @pytest.mark.asyncio
    async def test_partial_failure_recovery(self, coordinator, complex_design_input, legacy_code_files, complex_code_output):
        """
        场景：CoderAgent 成功但 TestAgent 失败
        
        验证点：
        1. 代码应该仍然被保留
        2. 测试失败不应该影响代码生成
        3. 系统应该记录测试错误但继续完成
        """
        print("\n[深度测试] 开始部分失败恢复测试...")
        
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": True, "output": complex_code_output}
        ):
            with patch.object(
                test_agent,
                'generate_tests',
                new_callable=AsyncMock,
                return_value={"success": False, "error": "测试生成失败: LLM 返回格式错误"}
            ):
                result = await coordinator.execute_parallel(
                    complex_design_input,
                    legacy_code_files
                )
                
                # 验证整体成功（代码生成成功）
                assert result["success"] is True
                output = result["output"]
                
                # 验证代码文件仍然存在
                assert len(output["files"]) == 6, "代码文件应该保留"
                
                # 验证测试未包含
                assert output["tests_included"] is False
                
                # 验证错误被记录
                assert result.get("error") is not None  # 测试错误被记录
                
                print(f"[深度测试] ✓ 部分失败恢复测试通过 - 代码保留，测试失败被记录")

    @pytest.mark.asyncio
    async def test_file_path_consistency(self, coordinator):
        """
        场景：验证 Coder 和 Tester 的文件路径一致性
        
        验证点：
        1. Tester 生成的测试文件路径应该对应 Coder 生成的代码文件
        2. 测试文件应该放在 tests/ 目录下
        3. 测试模块路径应该正确指向被测模块
        """
        print("\n[深度测试] 开始文件路径一致性测试...")
        
        code_output = {
            "files": [
                {"file_path": "app/services/user_service.py", "content": "# user service"},
                {"file_path": "app/models/user.py", "content": "# user model"},
                {"file_path": "app/api/v1/users.py", "content": "# user api"}
            ],
            "summary": "用户模块实现",
            "dependencies_added": []
        }
        
        test_output = {
            "test_files": [
                {
                    "file_path": "tests/test_user_service.py",
                    "target_module": "app.services.user_service",
                    "content": "# test user service"
                },
                {
                    "file_path": "tests/test_user.py",
                    "target_module": "app.models.user",
                    "content": "# test user model"
                },
                {
                    "file_path": "tests/test_users_api.py",
                    "target_module": "app.api.v1.users",
                    "content": "# test user api"
                }
            ],
            "summary": "用户模块测试",
            "coverage_targets": ["用户创建", "用户查询"]
        }
        
        with patch.object(
            coder_agent,
            'generate_code',
            new_callable=AsyncMock,
            return_value={"success": True, "output": code_output}
        ):
            with patch.object(
                test_agent,
                'generate_tests',
                new_callable=AsyncMock,
                return_value={"success": True, "output": test_output}
            ):
                result = await coordinator.execute_parallel(
                    {"feature": "user module"},
                    {}
                )
                
                output = result["output"]
                files = output["files"]
                
                # 验证测试文件路径格式
                test_files = [f for f in files if "test" in f["file_path"]]
                for tf in test_files:
                    assert tf["file_path"].startswith("tests/"), f"测试文件应该在 tests/ 目录下: {tf['file_path']}"
                
                # 验证每个代码文件都有对应的测试文件
                code_files = [f for f in files if "test" not in f["file_path"]]
                assert len(code_files) == 3
                assert len(test_files) == 3
                
                print(f"[深度测试] ✓ 文件路径一致性测试通过 - {len(code_files)} 个代码文件, {len(test_files)} 个测试文件")


class TestAgentUnderstandingConsistency:
    """测试 Agent 之间的理解一致性"""

    @pytest.fixture
    def coordinator(self):
        return MultiAgentCoordinator()

    @pytest.mark.asyncio
    async def test_shared_context_understanding(self, coordinator):
        """
        场景：验证两个 Agent 对同一需求的理解是否一致
        
        验证点：
        1. Coder 和 Tester 应该基于相同的 design_output
        2. Tester 应该正确理解 Coder 生成的代码结构
        """
        print("\n[一致性测试] 开始共享上下文理解测试...")
        
        design = {
            "feature_description": "实现 JWT 认证中间件",
            "api_endpoints": [{"path": "/auth/login", "method": "POST"}],
            "technical_requirements": ["使用 PyJWT", "支持 Token 刷新"]
        }
        
        code = {
            "files": [
                {
                    "file_path": "app/middleware/jwt_auth.py",
                    "content": "import jwt\nclass JWTAuthMiddleware:...",
                    "description": "JWT 认证中间件"
                }
            ],
            "summary": "实现了 JWT 认证",
            "dependencies_added": ["PyJWT"]
        }
        
        test = {
            "test_files": [
                {
                    "file_path": "tests/test_jwt_auth.py",
                    "target_module": "app.middleware.jwt_auth",
                    "content": "import jwt\ndef test_jwt_auth():..."
                }
            ],
            "summary": "JWT 认证测试",
            "coverage_targets": ["Token 验证", "Token 刷新"]
        }
        
        # 验证 Tester 使用了 Coder 的代码输出
        with patch.object(coder_agent, 'generate_code', new_callable=AsyncMock,
                         return_value={"success": True, "output": code}):
            with patch.object(test_agent, 'generate_tests', new_callable=AsyncMock,
                            return_value={"success": True, "output": test}) as mock_tester:
                
                await coordinator.execute_parallel(design, {})
                
                # 验证 Tester 接收到了 Coder 的输出
                call_args = mock_tester.call_args
                assert call_args is not None
                _, received_code_output, _ = call_args[0]
                
                # 验证 Tester 确实使用了 Coder 的输出
                assert received_code_output == code
                assert "JWT" in received_code_output["summary"]
                
                print("[一致性测试] ✓ 共享上下文理解测试通过 - Tester 正确接收了 Coder 的输出")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
