"""
系统指标端点单元测试
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_metrics_endpoint_success():
    """
    测试系统指标端点成功场景，验证响应结构和字段
    """
    mock_resource_stats = {
        "cpu_percent": 45.5,
        "memory_percent": 62.3,
        "memory_used_mb": 4096,
        "memory_total_mb": 8192,
        "disk_percent": 75.0,
        "disk_used_gb": 150.5,
        "disk_total_gb": 200.0,
        "uptime_seconds": 3600
    }
    
    with patch("app.api.v1.system.SystemStatsService.get_resource_stats", new_callable=AsyncMock) as mock_stats:
        mock_stats.return_value = mock_resource_stats
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/system/metrics")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "data" in data
            
            metrics_data = data["data"]
            assert "cpu_usage" in metrics_data
            assert "memory_usage" in metrics_data
            assert "disk_usage" in metrics_data
            assert "uptime_seconds" in metrics_data
            
            assert metrics_data["cpu_usage"] == 45.5
            assert metrics_data["memory_usage"] == 62.3
            assert metrics_data["disk_usage"] == 75.0
            assert metrics_data["uptime_seconds"] == 3600


@pytest.mark.asyncio
async def test_metrics_endpoint_error():
    """
    测试系统指标端点异常场景，验证错误处理
    """
    with patch("app.api.v1.system.SystemStatsService.get_resource_stats", new_callable=AsyncMock) as mock_stats:
        mock_stats.side_effect = Exception("Metrics collection failed")
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/system/metrics")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "error" in data
            assert "Metrics collection failed" in data["error"]
            assert "Metrics collection failed" in data["error"]