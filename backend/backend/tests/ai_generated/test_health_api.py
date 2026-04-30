import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from fastapi.testclient import TestClient
from app.main import app
from app.api.v1.health import (
    router,
    _check_database_status,
    _check_disk_status,
    _check_memory_status,
    _calculate_overall_status,
)
from app.core.database import get_db_status
from app.service.system_stats import SystemStatsService

# 测试客户端
current_app = app
client = TestClient(current_app)

# Fixtures
@pytest.fixture
def mock_get_db_status():
    with patch('app.api.v1.health.get_db_status', new_callable=AsyncMock) as mock:
        yield mock

@pytest.fixture
def mock_system_stats_service():
    with patch('app.api.v1.health.SystemStatsService.get_resource_stats') as mock:
        yield mock

# 测试_check_database_status
@pytest.mark.asyncio
async def test_check_database_status_connected(mock_get_db_status):
    """测试数据库连接正常时的状态"""
    mock_get_db_status.return_value = {"connected": True, "latency_ms": 10}
    result = await _check_database_status()
    assert result["status"] == "healthy"
    assert "details" in result

@pytest.mark.asyncio
async def test_check_database_status_disconnected(mock_get_db_status):
    """测试数据库断开时的状态"""
    mock_get_db_status.return_value = {"connected": False, "error": "Connection refused"}
    result = await _check_database_status()
    assert result["status"] == "unhealthy"
    assert "details" in result

# 测试_check_disk_status
def test_check_disk_status_normal(mock_system_stats_service):
    """测试磁盘使用率正常时的状态"""
    mock_system_stats_service.return_value = {
        "disk_percent": 75,
        "disk_used_gb": 75,
        "disk_total_gb": 100
    }
    result = _check_disk_status(mock_system_stats_service.return_value)
    assert result["status"] == "healthy"
    assert result["details"]["percent"] == 75

def test_check_disk_status_warning(mock_system_stats_service):
    """测试磁盘使用率达到警告阈值时的状态"""
    mock_system_stats_service.return_value = {
        "disk_percent": 91,
        "disk_used_gb": 91,
        "disk_total_gb": 100
    }
    result = _check_disk_status(mock_system_stats_service.return_value)
    assert result["status"] == "warning"
    assert result["details"]["percent"] == 91

# 测试_check_memory_status
def test_check_memory_status_normal(mock_system_stats_service):
    """测试内存使用率正常时的状态"""
    mock_system_stats_service.return_value = {
        "memory_percent": 60,
        "memory_used_mb": 6000,
        "memory_total_mb": 10000
    }
    result = _check_memory_status(mock_system_stats_service.return_value)
    assert result["status"] == "healthy"
    assert result["details"]["percent"] == 60

def test_check_memory_status_warning(mock_system_stats_service):
    """测试内存使用率达到警告阈值时的状态"""
    mock_system_stats_service.return_value = {
        "memory_percent": 86,
        "memory_used_mb": 8600,
        "memory_total_mb": 10000
    }
    result = _check_memory_status(mock_system_stats_service.return_value)
    assert result["status"] == "warning"
    assert result["details"]["percent"] == 86

# 测试_calculate_overall_status
def test_calculate_overall_status_all_healthy():
    """测试所有组件正常时的整体状态"""
    components = {
        "database": {"status": "healthy", "details": {}},
        "disk": {"status": "healthy", "details": {}},
        "memory": {"status": "healthy", "details": {}}
    }
    result = _calculate_overall_status(components)
    assert result == "healthy"

def test_calculate_overall_status_with_warning():
    """测试存在警告组件时的整体状态"""
    components = {
        "database": {"status": "healthy", "details": {}},
        "disk": {"status": "warning", "details": {}},
        "memory": {"status": "healthy", "details": {}}
    }
    result = _calculate_overall_status(components)
    assert result == "degraded"

def test_calculate_overall_status_unhealthy():
    """测试存在故障组件时的整体状态"""
    components = {
        "database": {"status": "unhealthy", "details": {}},
        "disk": {"status": "healthy", "details": {}},
        "memory": {"status": "healthy", "details": {}}
    }
    result = _calculate_overall_status(components)
    assert result == "unhealthy"

# 测试健康检查端点
@pytest.mark.asyncio
async def test_health_check_detailed_endpoint_success(mock_get_db_status, mock_system_stats_service):
    """测试详细健康检查端点正常响应"""
    mock_get_db_status.return_value = {"connected": True, "latency_ms": 10}
    mock_system_stats_service.return_value = {
        "disk_percent": 70,
        "disk_used_gb": 70,
        "disk_total_gb": 100,
        "memory_percent": 60,
        "memory_used_mb": 6000,
        "memory_total_mb": 10000
    }
    
    response = client.get("/api/v1/health/detailed")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "healthy"
    assert "components" in data
    assert "database" in data["components"]
    assert "disk" in data["components"]
    assert "memory" in data["components"]

@pytest.mark.asyncio
async def test_health_check_detailed_endpoint_degraded(mock_get_db_status, mock_system_stats_service):
    """测试详细健康检查端点在降级状态下的响应"""
    mock_get_db_status.return_value = {"connected": True, "latency_ms": 10}
    mock_system_stats_service.return_value = {
        "disk_percent": 91,
        "disk_used_gb": 91,
        "disk_total_gb": 100,
        "memory_percent": 60,
        "memory_used_mb": 6000,
        "memory_total_mb": 10000
    }
    
    response = client.get("/api/v1/health/detailed")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "degraded"
    assert data["components"]["disk"]["status"] == "warning"

@pytest.mark.asyncio
async def test_health_check_detailed_endpoint_unhealthy(mock_get_db_status, mock_system_stats_service):
    """测试详细健康检查端点在不健康状态下的响应"""
    mock_get_db_status.return_value = {"connected": False, "error": "Connection failed"}
    mock_system_stats_service.return_value = {
        "disk_percent": 70,
        "disk_used_gb": 70,
        "disk_total_gb": 100,
        "memory_percent": 60,
        "memory_used_mb": 6000,
        "memory_total_mb": 10000
    }
    
    response = client.get("/api/v1/health/detailed")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "unhealthy"
    assert data["components"]["database"]["status"] == "unhealthy"