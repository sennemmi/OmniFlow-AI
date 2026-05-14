"""
系统健康检查端点单元测试
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint_success():
    """
    测试健康检查端点成功场景，验证响应结构和字段
    """
    mock_health_data = {
        "components": {
            "database": {
                "status": "healthy",
                "health_score": 100
            },
            "disk": {
                "status": "healthy",
                "health_score": 100
            },
            "memory": {
                "status": "healthy",
                "health_score": 100
            }
        },
        "overall_health": "healthy"
    }
    
    with patch("app.api.v1.system.HealthService.get_component_health", new_callable=AsyncMock) as mock_health:
        mock_health.return_value = mock_health_data
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/system/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "data" in data
            
            health_data = data["data"]
            assert "status" in health_data
            assert "components" in health_data
            assert "overall_health" in health_data
            
            assert health_data["status"] == "healthy"
            assert health_data["overall_health"] == "healthy"
            assert isinstance(health_data["components"], dict)
            assert "database" in health_data["components"]
            assert "disk" in health_data["components"]
            assert "memory" in health_data["components"]


@pytest.mark.asyncio
async def test_health_endpoint_error():
    """
    测试健康检查端点异常场景，验证错误处理
    """
    with patch("app.api.v1.system.HealthService.get_component_health", new_callable=AsyncMock) as mock_health:
        mock_health.side_effect = Exception("Health service unavailable")
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/system/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "error" in data
            assert "Health check failed" in data["error"]
            assert "Health service unavailable" in data["error"]