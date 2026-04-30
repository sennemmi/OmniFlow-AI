# OmniFlowAI 项目规范

## 核心模块公共 API 契约

以下模块的公共导出（`__all__` 中列出的或经常被 import 的）**绝对禁止删除或重命名**，只能追加新功能：

### app/core/database.py
```python
# 公共导出（禁止修改）：
- engine
- async_session_factory
- get_session
- init_db
```

### app/core/config.py
```python
# 公共导出（禁止修改）：
- settings
- Settings
```

### app/core/response.py
```python
# 公共导出（禁止修改）：
- ResponseModel
- success_response
- error_response
```

## 修改检查规则

当修改以下文件时，必须遵守：

1. **app/core/database.py**：
   - 禁止删除 `get_session` 函数
   - 禁止修改 `engine` 或 `async_session_factory` 的创建逻辑
   - 可以追加新的数据库工具函数

2. **app/api/v1/health.py**：
   - 保持 `router = APIRouter()` 存在
   - 保持 `@router.get("/")` 装饰器的路由注册

3. **app/main.py**：
   - 保持 `app = FastAPI()` 存在
   - 保持路由注册逻辑

## 搜索替换最佳实践

1. **精确复制**：`search_block` 必须从带行号的文件内容中精确复制（包括所有缩进和空行）
2. **唯一性**：确保 `search_block` 在文件中是唯一的
3. **最小范围**：只修改必要的代码，不要替换整个函数或文件
4. **fallback 行号**：当无法精确匹配时，提供准确的 fallback_start_line 和 fallback_end_line
