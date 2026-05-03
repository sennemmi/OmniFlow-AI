# OmniFlowAI 项目代码约定

> 本文档是 Agent 生成代码时必须遵守的全局约定。所有 CoderAgent、DesignerAgent 在设计或编写代码时务必以本文档为基准。

---

## 1. API 响应格式

所有 API 端点必须使用统一的响应函数：

```python
from fastapi import Request
from app.core.response import success_response, error_response

# 成功响应 - 必须传入 request_id
return success_response(data={"status": "up"}, request_id=request_id)

# 错误响应 - 使用 error 参数而不是 message/code
return error_response(error="数据库连接失败", request_id=request_id)
```

**重要：所有 API 端点必须引入 `request: Request` 参数以获取 `request_id`：**
```python
from fastapi import Request

@router.get("/health")
async def health_check(request: Request):
    request_id = getattr(request.state, "request_id", "")
    # ... 使用 request_id 调用响应函数
```

禁止手动构建响应字典：
```python
# ❌ 错误
return {"success": True, "data": result}
return JSONResponse(content={"error": "xxx"})
```

## 2. 数据库访问

通过 FastAPI Depends 注入会话，不得使用全局变量或手动实例化：

```python
from fastapi import Depends
from app.core.database import get_session

@router.get("/items")
async def get_items(session: AsyncSession = Depends(get_session)):
    ...
```

## 3. 依赖注入

所有服务依赖必须通过 FastAPI Depends 注入：

```python
# ✅ 正确
@router.get("/health")
async def health_check(service: HealthService = Depends()) -> Any:
    return await service.check()

# ❌ 错误 - 全局变量
health_service = HealthService()

# ❌ 错误 - 手动实例化
@router.get("/health")
async def health_check() -> Any:
    service = HealthService()
```

## 4. 日志规范

统一使用 `structlog`，不使用 `print()`：

```python
import structlog
logger = structlog.get_logger(__name__)

logger.info("用户登录成功", user_id=user.id)
logger.error("数据库查询失败", error=str(e))
```

## 5. 导入路径规范

必须使用完整的 `app.` 前缀导入：

```python
# ✅ 正确
from app.core.database import get_session
from app.models.user import User
from app.service.health import HealthService

# ❌ 错误 - 缺少 app 前缀
from core.database import get_session
from models.user import User
```

## 6. 测试文件规范

- 位置：`tests/ai_generated/` 目录下
- 文件名格式：`test_{功能名}.py`
- 不需要 `@pytest.mark.asyncio` 装饰器（pyproject.toml 已配置 `asyncio_mode = "auto"`）
- 禁止使用 `anyio_backend` fixture
- 直接使用 `async def test_xxx():` 即可

## 7. 数据类型键名约定

项目中所有字典返回的键名必须统一：

### 磁盘使用 (disk_usage / check_disk_usage)
```python
{
    "total_gb": float,
    "used_gb": float,
    "free_gb": float,
    "usage_percent": float   # ⚠️ 不是 used_percent！
}
```

### 内存使用 (memory / check_memory_usage)
```python
{
    "total_mb": int,
    "used_mb": int,
    "available_mb": int,
    "usage_percent": float   # ⚠️ 不是 used_percent！
}
```

### 数据库状态 (database / check_database)
```python
{
    "status": str,             # "up" | "down" | "degraded"
    "response_time_ms": float
}
```

### 健康检查响应 (health)
```python
{
    "status": str,             # "healthy" | "unhealthy" | "degraded"
    "health_score": int,       # 0-100
    "components": dict,        # 各组件状态
    "timestamp": str           # ISO 格式
}
```

## 8. 异常处理

禁止吞掉异常，至少记录日志：

```python
# ✅ 正确
try:
    result = await db.query()
except Exception as e:
    logger.error("查询失败", error=str(e))
    raise

# ❌ 错误 - 空 except
try:
    result = await db.query()
except:
    pass
```

## 9. 模块导出契约

以下核心模块的公共 API 不可删除或重命名：

| 模块 | 受保护的 API |
|------|-------------|
| `app/core/database.py` | `get_session`, `engine`, `async_session_factory` |
| `app/core/response.py` | `success_response`, `error_response`, `ResponseModel` |
| `app/core/config.py` | `settings` |

## 10. 架构分层

```
api/ → service/ → agents/（唯一能调 LLM 的地方）
                ↓
            models/（仅定义表结构）
```

- 分层内聚，只能上层调下层
- 禁止反向调用
