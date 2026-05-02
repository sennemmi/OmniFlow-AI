"""
测试 Agent
基于 LangGraph 状态机实现，继承 BaseAgent 统一调用逻辑

职责：
1. 分析 DesignerAgent 的技术方案
2. 分析 CoderAgent 生成的代码
3. 生成符合项目风格的单元测试代码
"""

import json
import logging
from typing import Dict, List, Optional, Any

from app.agents.base import LangGraphAgent
from app.agents.schemas import TesterOutput

logger = logging.getLogger(__name__)


class TesterAgent(LangGraphAgent[TesterOutput]):
    """
    测试 Agent
    
    根据设计方案和生成的代码编写单元测试
    继承 LangGraphAgent，只需实现业务差异部分
    """
    
    # 【结构化输出】启用 JSON 格式化输出
    USE_JSON_FORMAT = True
    
    def __init__(self):
        super().__init__(agent_name="TesterAgent")
    
    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调测试覆盖和代码风格"""
        return """你是 OmniFlowAI 的测试 Agent，负责根据技术设计方案和生成的代码编写单元测试。

【八荣八耻准则】
以单元测试为荣，以手工验证为耻
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以监控告警为荣，以故障未知为耻

【核心铁律】
以单元测试为荣！

【分层测试策略 - 快速失败原则】
测试按照"发现问题速度"和"修复成本"分层执行：

Layer 1 - 语法检查（毫秒级）：
- 使用 ast.parse 检查新生成代码的语法
- 失败立即返回，不进入后续层

Layer 2 - 防御性测试（秒级，核心保护机制）：
- 位于 backend/tests/unit/defense/ 目录
- 是系统的"免疫系统"，包含 4 层防线：
  * 代码修改与沙箱防线：文件回滚、路径安全、导入清理
  * 测试运行器与决策防线：语法拦截、回归保护
  * 多 Agent 协作与状态机防线：Pydantic 校验、重试限制、JSON 剥离
  * 工作流与状态持久化防线：状态流转、反馈传递
- 【关键】防御性测试失败 = 代码破坏了核心保护机制
- 【关键】防御性测试失败必须人工介入，不能 Auto-Fix

Layer 3 - 新测试（秒级，功能验证）：
- 位于 backend/tests/ai_generated/ 目录（你生成的测试）
- 验证新生成功能是否符合预期
- 失败可进入 Auto-Fix 循环自动修复

Layer 4 - 健康检查（服务启动验证）：
- 验证代码是否能正常启动服务

【重要】你生成的新测试必须：
- 放置于 backend/tests/ai_generated/ 目录
- 通过 Layer 1 语法检查（ast.parse 秒级完成）
- 通过 Layer 2 防御性测试（不能破坏核心保护机制）
- 不能与 backend/tests/unit/defense/ 中的防御性测试冲突
- 不能修改 backend/tests/unit/ 和 backend/tests/integration/ 下的旧测试（受保护层）
- 如果测试失败，系统会告诉你具体的失败测试名称和错误日志

【任务要求】
1. 仔细阅读 DesignerAgent 的技术方案（API 端点、函数变更、逻辑流）
2. 仔细阅读 CoderAgent 生成的代码
3. 生成测试代码时必须遵守：
   - 使用 pytest 框架
   - 保持与主代码相同的缩进风格（空格或Tab数量）
   - 保持与主代码相同的注释风格（井号或三引号）
   - 测试函数名以 test_ 开头
   - 使用 pytest-asyncio 测试异步函数
   - 使用 pytest-mock 进行必要的 mock
   - 覆盖正常路径和异常路径
   - 测试边界条件和错误处理
   - 不要测试与需求无关的代码

【IMPORT 规范 - 绝对遵守】
所有测试文件必须使用如下 import 方式（从 app 包导入）：
  from app.main import app
  from app.core.database import get_session
  from app.models.user import User

绝对不允许使用以下错误的 import 方式：
  from main import app              # ❌ 错误！缺少 app 前缀
  import main                       # ❌ 错误！不能导入 main 模块
  from backend.app.main import app  # ❌ 错误！不需要 backend 前缀

【输出格式 - 极其重要】
你必须直接输出纯 JSON 格式，不要包含任何其他文本、解释或标记。
输出必须是一个有效的 JSON 对象。

正确示例（直接输出 JSON）：
{"test_files": [{"file_path": "backend/tests/ai_generated/test_example.py", "content": "import pytest...", "target_module": "app.api.v1.example", "test_cases_count": 5}], "summary": "生成了 5 个测试用例", "coverage_targets": ["正常登录", "密码错误"], "dependencies_added": ["pytest"]}

错误示例（不要这样输出）：
- 不要添加 ```json 标记
- 不要添加解释文本
- 不要输出工具调用格式如 <|tool_calls_section_begin|>
- 不要输出 "我需要先分析..." 等思考过程
- 只输出纯 JSON

JSON 格式：
{
    "test_files": [
        {
            "file_path": "backend/tests/ai_generated/test_example.py",
            "content": "完整的测试文件内容...",
            "target_module": "app.api.v1.example",
            "test_cases_count": 5
        }
    ],
    "summary": "本次生成了 5 个测试用例...",
    "coverage_targets": ["用户登录接口 - 正常登录", "用户登录接口 - 密码错误"],
    "dependencies_added": ["pytest", "pytest-asyncio", "pytest-mock"]
}

【测试编写原则】
- 每个测试函数只测试一个概念
- 使用 Arrange-Act-Assert 结构
- 使用描述性的测试函数名
- 使用 fixtures 共享测试数据
- 使用 parametrize 测试多组数据
- 【重要】测试异步函数时**不要**使用 @pytest.mark.asyncio 装饰器，因为 pyproject.toml 已配置 asyncio_mode = "auto"
- 测试数据库操作时使用 mock 或测试数据库
-【新增】绝对禁止在测试文件中定义 anyio_backend fixture 或将其作为参数传入测试函数，本项目不需要 anyio。

【Mock 异步函数铁律 - 绝对遵守】
1. 如果你需要 Mock 一个异步函数（特别是会被 asyncio.gather 调用的函数），必须使用 `new_callable=AsyncMock` 或 `return_value` 为协程！否则会导致 `TypeError: unhashable type` 或 `object is not awaitable`。
2. 【关键】如果你在代码中使用了 `AsyncMock`、`MagicMock` 或 `patch`，必须在文件顶部显式导入它们：
   `from unittest.mock import AsyncMock, MagicMock, patch`

【Patch 路径铁律】
必须 patch 目标文件内部实际使用的名字。例如如果 a.py 中写了 `from b import func`，你要测试 a.py，就必须 `patch('a.func')`，绝不能 `patch('b.func')`！否则会报 AttributeError！

【错误消息断言 - 使用模糊匹配】
当测试错误消息时，**绝对禁止**使用精确字符串匹配（如 `assert result["error"] == "Service unavailable"`）。

原因：CoderAgent 可能在错误消息前添加前缀（如 "Health check failed: Service unavailable"），导致测试脆弱。

正确做法（使用模糊匹配）：
- `assert "unavailable" in result["error"]`  # 检查包含关键字
- `assert result["error"].startswith("Service")`  # 检查开头
- `assert any(keyword in result["error"] for keyword in ["unavailable", "service"])`  # 多关键字匹配

如果 interface_specs 中定义了 error_responses，使用其中 message_contains 列表的关键字进行匹配。

【数据库 Mock 示例 - 极其重要】
测试数据库操作时，必须 mock 数据库依赖，不要连接真实数据库。

1. **Mock SQLModel/SQLAlchemy Session**:
```python
from unittest.mock import AsyncMock, patch
import pytest

@pytest.fixture
def mock_db_session():
    # Mock 数据库 session
    mock_session = AsyncMock()
    # 配置 mock 返回值
    mock_session.exec.return_value = AsyncMock()
    mock_session.exec.return_value.first.return_value = None  # 或返回测试数据
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    return mock_session

# 在测试中使用
async def test_create_user(mock_db_session):
    with patch('app.core.database.get_session', return_value=mock_db_session):
        # 调用被测函数
        result = await create_user(user_data)
        # 验证
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
```

2. **Mock 数据库查询结果**:
```python
# 模拟查询返回特定数据
mock_user = User(id=1, name="test", email="test@example.com")
mock_session.exec.return_value.first.return_value = mock_user

# 模拟查询返回 None（记录不存在）
mock_session.exec.return_value.first.return_value = None

# 模拟查询返回列表
mock_session.exec.return_value.all.return_value = [mock_user1, mock_user2]
```

3. **Mock Repository 模式**:
```python
@pytest.fixture
def mock_user_repo():
    with patch('app.repositories.user_repo.UserRepository') as mock_repo:
        mock_instance = AsyncMock()
        mock_repo.return_value = mock_instance
        yield mock_instance

async def test_get_user(mock_user_repo):
    mock_user_repo.get_by_id.return_value = User(id=1, name="test")
    result = await user_service.get_user(1)
    assert result.name == "test"
```

【外部依赖 Mock 示例】
测试涉及外部服务（HTTP、Redis、消息队列等）时，必须 mock 这些依赖。

1. **Mock HTTP 请求 (httpx/aiohttp)**:
```python
from unittest.mock import AsyncMock, patch

async def test_fetch_external_data():
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": "test_value"}
    mock_response.text = '{"data": "test_value"}'
    
    with patch('httpx.AsyncClient.get', return_value=mock_response):
        result = await fetch_external_data("http://api.example.com/data")
        assert result["data"] == "test_value"

# 模拟 HTTP 错误
async def test_fetch_external_data_error():
    mock_response = AsyncMock()
    mock_response.status_code = 503
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Service Unavailable", request=AsyncMock(), response=mock_response
    )
    
    with patch('httpx.AsyncClient.get', return_value=mock_response):
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_external_data("http://api.example.com/data")
```

2. **Mock Redis**:
```python
from unittest.mock import AsyncMock, patch

@pytest.fixture
def mock_redis():
    with patch('app.core.redis.get_redis') as mock_get_redis:
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        yield mock_redis

async def test_cache_user(mock_redis):
    # 模拟缓存命中
    mock_redis.get.return_value = '{"id": 1, "name": "test"}'
    
    result = await get_user_from_cache(1)
    assert result["name"] == "test"
    mock_redis.get.assert_called_once_with("user:1")
    
    # 模拟缓存未命中
    mock_redis.get.return_value = None
    result = await get_user_from_cache(2)
    assert result is None
```

3. **Mock 消息队列 (Celery/RabbitMQ)**:
```python
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_celery_task():
    with patch('app.tasks.send_email_task.delay') as mock_delay:
        mock_task = MagicMock()
        mock_task.id = "task-123"
        mock_delay.return_value = mock_task
        yield mock_delay

async def test_send_email_trigger(mock_celery_task):
    await trigger_email_send("user@example.com", "Hello")
    mock_celery_task.assert_called_once_with("user@example.com", "Hello")
```

4. **Mock 文件系统操作**:
```python
from unittest.mock import patch, mock_open

async def test_file_upload():
    with patch('builtins.open', mock_open(read_data=b'file content')):
        with patch('os.path.exists', return_value=True):
            result = await process_uploaded_file("test.txt")
            assert result["size"] == len(b'file content')
```

【强制：Mock 行为准则】
1. **严禁直接使用 `MagicMock` 模拟异步函数**。必须使用 `from unittest.mock import AsyncMock` 并显式指定 `new_callable=AsyncMock`。
2. **模拟返回值时，结构必须完整**。如果被测函数期望返回一个字典，你的 Mock `return_value` 必须包含该字典所有必需的键，严禁返回空 Mock。
3. **路径对齐：使用 `patch` 时，必须 patch 目标模块 import 进来的那个名字，而不是原始定义的名字。**

【Mock 最佳实践】
1. **只 mock 被测函数的直接依赖**，不要过度 mock
2. **在测试函数级别使用 patch**，不要在模块级别
3. **使用 AsyncMock 测试异步函数**，不要用普通 Mock
4. **验证 mock 被调用的次数和参数**，确保代码逻辑正确
5. **使用 pytest fixtures 复用 mock 配置**
6. **不要 mock 被测函数本身**，只 mock 依赖
7. **【Mock 铁律】Mock 函数时，请务必查看原函数的实现！如果原函数内部自带 try-except 并在失败时返回特定数据结构，你的 Mock 必须返回对应的数据结构，绝不能直接使用 side_effect=Exception 让异常抛出。**

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- 测试文件内容必须是完整的，不是 diff 格式
- 测试代码必须可以直接运行
- 优先使用 pytest 的最佳实践
- 必须使用完整的文件路径（包含 backend/ 前缀，如 backend/tests/ai_generated/test_xxx.py）
- 严禁修改 backend/tests/unit/defense/ 下的防御性测试

"""
    
    def _detect_symbol_type(self, signature: str) -> str:
        """
        根据签名检测符号类型
        
        Args:
            signature: 函数/类签名
            
        Returns:
            str: 符号类型 ("function", "class", "static_method", "class_method", "instance_method")
        """
        if not signature:
            return "function"
        
        sig_lower = signature.lower()
        
        # 检测类定义
        if sig_lower.startswith("class "):
            return "class"
        
        # 检测静态方法（@staticmethod 装饰器）
        if "@staticmethod" in sig_lower:
            return "static_method"
        
        # 检测类方法（@classmethod 装饰器）
        if "@classmethod" in sig_lower:
            return "class_method"
        
        # 检测实例方法（self 或 cls 参数）
        if "(self" in signature or "( cls" in signature or "(cls" in signature:
            return "instance_method"
        
        # 默认视为模块级函数
        return "function"
    
    def _extract_class_name_from_signature(
        self,
        signature: str,
        interface_specs: Optional[List[Dict]] = None
    ) -> str:
        """
        从签名中提取类名

        Args:
            signature: 方法签名
            interface_specs: 接口契约列表，用于查找同模块下的类名

        Returns:
            str: 类名，如果无法提取则返回空字符串
        """
        if not signature:
            return ""

        # 策略1: 从签名中解析类名前缀
        # 例如: "def HealthService.calculate(...)" -> "HealthService"
        sig_clean = signature.strip()
        if "." in sig_clean:
            # 处理 "ClassName.method_name" 格式
            parts = sig_clean.split(".")
            if parts and parts[0]:
                potential_class = parts[0].split()[-1]  # 处理 "def ClassName.method" 情况
                if potential_class and potential_class[0].isupper():
                    return potential_class

        # 策略2: 从 interface_specs 中查找同模块的类
        if interface_specs:
            # 找到当前方法所属的模块
            current_module = ""
            current_symbol = ""

            # 尝试从 signature 中找到方法名
            method_match = re.search(r'def\s+(\w+)', signature)
            if method_match:
                current_symbol = method_match.group(1)

            # 在 interface_specs 中查找同模块的类
            for spec in interface_specs:
                spec_sig = spec.get("signature", "")
                spec_symbol = spec.get("symbol_name", "")
                spec_type = self._detect_symbol_type(spec_sig)

                if spec_type == "class":
                    # 检查这个类是否包含当前方法
                    if current_symbol and self._is_method_of_class(current_symbol, spec_symbol, interface_specs):
                        return spec_symbol

            # 如果没有找到关联，返回同模块的第一个类名
            for spec in interface_specs:
                spec_sig = spec.get("signature", "")
                spec_type = self._detect_symbol_type(spec_sig)
                if spec_type == "class":
                    return spec.get("symbol_name", "")

        return ""

    def _is_method_of_class(
        self,
        method_name: str,
        class_name: str,
        interface_specs: List[Dict]
    ) -> bool:
        """
        判断方法是否属于某个类

        Args:
            method_name: 方法名
            class_name: 类名
            interface_specs: 接口契约列表

        Returns:
            bool: 是否属于该类
        """
        # 查找类的签名
        class_spec = None
        for spec in interface_specs:
            if spec.get("symbol_name") == class_name:
                class_sig = spec.get("signature", "")
                if self._detect_symbol_type(class_sig) == "class":
                    class_spec = spec
                    break

        if not class_spec:
            return False

        # 检查方法名是否是类名的常见变体
        # 例如: HealthService -> get_health, check_health
        class_lower = class_name.lower().replace("service", "").replace("manager", "").replace("controller", "")
        method_lower = method_name.lower()

        # 如果方法名包含类名关键字，可能是该类的方法
        if class_lower and class_lower in method_lower:
            return True

        # 检查是否有其他线索
        return False
    
    def _build_allowed_imports_section(self, design_output: Dict[str, Any]) -> str:
        """
        构建允许导入的符号清单

        基于 interface_specs 生成测试文件允许导入的符号列表
        【改进】添加详细的导入方式说明，包括静态方法/类方法的正确调用方式
        """
        interface_specs = design_output.get("interface_specs", [])
        if not interface_specs:
            return ""

        # 按模块分组，并构建详细的导入说明
        module_imports: Dict[str, List[Dict]] = {}
        for spec in interface_specs:
            module = spec.get("module", "")
            symbol = spec.get("symbol_name", "")
            signature = spec.get("signature", "")
            
            if module and symbol:
                # 转换文件路径为 Python 模块路径
                module_path = module.replace(".py", "").replace("/", ".")
                if module_path not in module_imports:
                    module_imports[module_path] = []
                
                # 判断符号类型（函数、类、静态方法等）
                symbol_type = self._detect_symbol_type(signature)
                
                module_imports[module_path].append({
                    "name": symbol,
                    "signature": signature,
                    "type": symbol_type
                })

        # 构建详细的导入说明
        imports_details = []
        interface_specs = design_output.get("interface_specs", [])

        for module_path, symbols in module_imports.items():
            for sym in symbols:
                name = sym["name"]
                sig = sym["signature"]
                sym_type = sym["type"]

                if sym_type == "class":
                    imports_details.append(
                        f"  - from {module_path} import {name}\n"
                        f"    类型: 类\n"
                        f"    签名: {sig}\n"
                        f"    使用: 实例化后调用方法"
                    )
                elif sym_type == "static_method":
                    # 提取类名（从签名和 interface_specs 中推断）
                    class_name = self._extract_class_name_from_signature(sig, interface_specs) or "ClassName"
                    imports_details.append(
                        f"  - from {module_path} import {class_name}\n"
                        f"    类型: 类（包含静态方法 {name}）\n"
                        f"    签名: {sig}\n"
                        f"    【重要】必须通过 {class_name}.{name}(...) 调用，禁止直接导入 {name}！"
                    )
                elif sym_type == "class_method":
                    class_name = self._extract_class_name_from_signature(sig, interface_specs) or "ClassName"
                    imports_details.append(
                        f"  - from {module_path} import {class_name}\n"
                        f"    类型: 类（包含类方法 {name}）\n"
                        f"    签名: {sig}\n"
                        f"    【重要】必须通过 {class_name}.{name}(...) 调用，禁止直接导入 {name}！"
                    )
                else:
                    imports_details.append(
                        f"  - from {module_path} import {name}\n"
                        f"    类型: 函数\n"
                        f"    签名: {sig}\n"
                        f"    使用: 直接调用 {name}(...)"
                    )

        imports_str = "\n\n".join(imports_details)
        allowed_symbols = [spec.get("symbol_name", "") for spec in interface_specs]

        # ✅ 新增：渲染每个 spec 的 mock_dependencies
        mock_sections = []
        for spec in interface_specs:
            deps = spec.get("mock_dependencies", [])
            if not deps:
                continue
            symbol = spec.get("symbol_name", "?")
            lines = [f"  测试 `{symbol}` 时必须 mock 以下依赖："]
            for dep in deps:
                mock_cls = "AsyncMock" if dep.get("is_async") else "MagicMock"
                rv = dep.get("mock_return_value")
                rv_str = f", return_value={rv}" if rv is not None else ""
                lines.append(
                    f"    patch_target : {dep['patch_target']}\n"
                    f"    mock 类型   : {mock_cls}{rv_str}\n"
                    f"    说明        : {dep.get('description', '')}"
                )
            mock_sections.append("\n".join(lines))

        if mock_sections:
            mock_block = "\n\n".join(mock_sections)
            mock_section = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    【Mock 依赖清单 - 必须全部 mock，否则测试访问真实资源】         ║
╚══════════════════════════════════════════════════════════════════════════════╝

{mock_block}

【Mock 铁律】
1. patch_target 必须完全照抄上述路径，不能自行猜测
2. async 目标用 AsyncMock，同步目标用 MagicMock
3. 不允许访问真实数据库、磁盘、内存、网络
"""
        else:
            mock_section = ""

        return f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    【测试生成规则 - 只能测试契约声明的符号】                      ║
╚══════════════════════════════════════════════════════════════════════════════╝

【允许测试导入的符号 - 绝对禁止违反】
你只能从对应模块导入以下已保证存在的符号，且必须按照指定方式导入和使用：

{imports_str}

允许导入的符号列表：{', '.join(allowed_symbols)}

【导入方式规则 - 极其重要】
1. **模块级函数**：可以直接 `from module import function_name`
2. **类**：可以直接 `from module import ClassName`，然后实例化或调用类方法
3. **静态方法/类方法**：【绝对禁止】直接导入方法名！
   ❌ 错误：`from module import static_method_name`
   ✅ 正确：`from module import ClassName` 然后 `ClassName.static_method_name(...)`
4. **实例方法**：必须先实例化类，然后通过实例调用

【测试生成规则 - 违反会导致测试失败】
1. **你只能测试上述接口契约中列出的函数或类，不得臆造任何未声明的符号**
2. 绝对禁止导入清单外的任何函数或类
3. 静态方法和类方法必须通过类名调用，禁止直接导入方法名
4. 测试端点的行为时，通过 HTTP 响应验证而非直接调用内部函数
5. 如果测试需要调用内部函数，该函数必须在上述清单中
6. 违反此限制会导致 ImportError，测试无法运行

【契约对齐检查清单 - 必须全部勾选才能输出】
在生成测试前，必须逐一检查并确认：
□ 测试的每个函数/类都在契约清单中吗？
□ 导入语句只使用了清单中的符号吗？
□ 静态方法/类方法是通过类名调用的吗？（不是直接导入方法名）
□ 没有导入任何契约外的新函数或类吗？
□ 没有使用任何未声明的辅助函数吗？
□ 测试代码中的每个 import 都能在 interface_specs 中找到对应声明吗？

【硬性规则 - 违反会导致系统崩溃】
1. **绝对禁止**导入 interface_specs 中未声明的任何符号
2. **绝对禁止**直接导入静态方法或类方法（必须通过类名调用）
3. **绝对禁止**在测试代码中调用契约外的函数（即使是"辅助函数"）
4. **绝对禁止**假设任何未声明的函数存在
5. 如果测试需要某个函数，必须在 interface_specs 中声明，由 CoderAgent 实现
6. 违反此规则会导致 ImportError，整个测试流程失败

【关键容错规则 - 防止死循环】
如果 interface_specs 中的某个符号实际上是类中的方法（而非模块级函数）：
1. **不要**尝试直接导入该方法名（会导致 ImportError）
2. **必须**导入包含该方法的类，然后通过类名调用方法
3. **示例**：
   - 契约错误地声明了: `{{"symbol_name": "get_component_health", "module": "app.service.health_service"}}`
   - 但 "get_component_health" 实际上是 HealthService 类的方法
   - ❌ 错误做法: `from app.service.health_service import get_component_health`
   - ✅ 正确做法: `from app.service.health_service import HealthService` 然后 `HealthService.get_component_health(...)`
   - 或者如果无法调用，测试该方法的包装函数或跳过测试

【常见错误示例】
❌ 错误：契约中只有 check_health，但测试导入了 get_component_health
❌ 错误：契约中只有 HealthService，但测试直接导入 calculate_health_score（静态方法）
   ✅ 正确：导入 HealthService，然后通过 HealthService.calculate_health_score(...) 调用
❌ 错误：契约中只有 HealthService，但测试调用了未声明的辅助函数
✅ 正确：只导入和测试 interface_specs 中明确列出的符号，并按正确方式使用

{mock_section}
"""

    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt

        Args:
            state: 包含 design_output, code_output 的状态
        """
        design_output = state.get("design_output", {})
        code_output = state.get("code_output", {})
        design_str = json.dumps(design_output, indent=2, ensure_ascii=False)

        # 【常驻基础设施上下文】注入地基代码
        evergreen_context = state.get("evergreen_context", "")
        evergreen_section = f"""
{evergreen_context}

""" if evergreen_context else ""

        # 【接口契约】生成允许导入的符号清单
        allowed_imports_section = self._build_allowed_imports_section(design_output)

        # 【修复指令】如果有 fix_instruction，在 Prompt 最顶部高亮显示
        fix_instruction = design_output.get("fix_instruction", "")
        fix_section = ""
        if fix_instruction:
            fix_section = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                           【🚨 修复指令 - 必须遵守】                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

{fix_instruction}

╔══════════════════════════════════════════════════════════════════════════════╗
║                           【修复指令结束】                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

"""

        # ── 完整模式：直接生成完整测试 ──────────────────────────────────────────
        code_str = json.dumps(code_output, indent=2, ensure_ascii=False)
        return f"""{fix_section}{evergreen_section}【技术设计方案】
{design_str}

【CoderAgent 生成的代码】
{code_str}
{allowed_imports_section}

请根据技术设计方案和生成的代码，编写完整的单元测试。
注意：
1. 使用 pytest 框架
2. 保持与主代码相同的缩进风格和注释风格
3. 覆盖正常路径、异常路径和边界条件
4. 测试代码必须可以直接运行
5. 直接输出 JSON，不要调用任何工具
6. 【重要】只能导入上述清单中的符号，禁止导入其他未定义的函数或类
7. 【⚠️ 极其重要】禁止直接 mock datetime.datetime.utcnow！datetime.datetime 是 C 扩展类型，不可变。
   正确做法：
   - 使用 freezegun: @freeze_time("2024-01-01")
   - 使用 unittest.mock.patch: with patch('app.module.datetime') as mock_dt:
   - 将被测函数改为接收 datetime 参数（依赖注入）
   错误做法：
   - datetime.datetime.utcnow = Mock()  # 会导致 TypeError!
"""
    
    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出为字典"""
        return self._parse_json_response(response)
    
    def validate_output(self, output: Dict[str, Any]) -> TesterOutput:
        """校验输出为 TesterOutput 模型"""
        return TesterOutput(**output)

    async def generate_tests(
        self,
        design_output: Dict[str, Any],
        code_output: Dict[str, Any],
        target_files: Optional[Dict[str, Any]] = None,
        pipeline_id: Optional[int] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        根据设计方案和生成的代码生成测试

        【改造】TestAgent 现在使用工具按需读取文件，不再依赖预加载的 target_files
        【新增】支持重试机制，当测试文件包含契约外导入时自动重试

        Args:
            design_output: DesignerAgent 的输出内容（包含 interface_specs 契约）
            code_output: CoderAgent 的输出内容
            target_files: 目标文件映射（可选，用于兼容性）
            pipeline_id: Pipeline ID，用于日志记录
            max_retries: 最大重试次数（默认3次）

        Returns:
            Dict: 包含生成结果或错误信息
        """
        from app.core.sse_log_buffer import push_log

        code_files_count = len(code_output.get("files", [])) if isinstance(code_output, dict) else 0

        # 【契约检查】验证 design_output 包含 interface_specs
        interface_specs = design_output.get("interface_specs", [])
        logger.info(f"TesterAgent 开始生成测试", extra={
            "pipeline_id": pipeline_id,
            "code_files_count": code_files_count,
            "interface_specs_count": len(interface_specs)
        })

        if pipeline_id:
            await push_log(pipeline_id, "info", f"TesterAgent 开始生成测试代码...", stage="TESTING")
            if interface_specs:
                await push_log(pipeline_id, "info", f"📋 接收到接口契约: {len(interface_specs)} 个符号", stage="TESTING")
                for spec in interface_specs[:3]:  # 只显示前3个避免日志过长
                    await push_log(pipeline_id, "info", f"   - {spec.get('symbol_name')} in {spec.get('module', '?')}", stage="TESTING")
                if len(interface_specs) > 3:
                    await push_log(pipeline_id, "info", f"   ... 等共 {len(interface_specs)} 个符号", stage="TESTING")

        initial_state = {
            "design_output": design_output,
            "code_output": code_output,
            "target_files": target_files or {}
        }

        result = await self.execute(
            pipeline_id=pipeline_id or 0,
            stage_name="TESTING",
            initial_state=initial_state
        )

        if result.get("success"):
            test_files = result.get("output", {}).get("test_files", [])
            
            # 【新增】后置验证：检查测试文件是否只导入了契约中的符号
            if test_files and interface_specs:
                import_errors = self._validate_test_imports_against_contract(
                    test_files, interface_specs
                )
                if import_errors:
                    error_msg = f"测试文件包含契约外的导入: {import_errors}"
                    logger.error(f"[TesterAgent] {error_msg}")
                    if pipeline_id:
                        await push_log(pipeline_id, "error", error_msg, stage="TESTING")
                    
                    # 【新增】重试逻辑：如果包含契约外导入，进入重试循环
                    logger.info(f"[TesterAgent] 进入重试模式，最多重试 {max_retries} 次")
                    
                    for retry_attempt in range(max_retries):
                        logger.info(f"[TesterAgent] 第 {retry_attempt + 1}/{max_retries} 次重试...")
                        if pipeline_id:
                            await push_log(pipeline_id, "warning", f"测试文件包含契约外导入，第 {retry_attempt + 1}/{max_retries} 次重试...", stage="TESTING")
                        
                        # 构建修复指令
                        fix_instruction = f"""之前的测试生成结果有误: {error_msg}

【关键问题】
测试文件导入了接口契约中未声明的符号。请根据以下规则修复：

1. **只能导入 interface_specs 中声明的符号**
2. **禁止导入契约外的任何符号**
3. **如果被测代码使用了契约外的符号，通过 HTTP 端点测试而非直接调用内部函数**

【允许的导入清单】
{self._build_allowed_imports_section(design_output)}

【修复要求】
- 移除所有契约外的导入
- 只测试契约中声明的函数/类
- 如果无法直接测试某个功能，通过测试其调用方来间接验证
"""
                        
                        # 构建重试用的 design_output
                        retry_design_output = {
                            **design_output,
                            "fix_mode": True,
                            "fix_instruction": fix_instruction,
                            "import_errors": import_errors
                        }
                        
                        retry_state = {
                            "design_output": retry_design_output,
                            "code_output": code_output,
                            "target_files": target_files or {},
                            "_retry_count": retry_attempt + 1
                        }
                        
                        # 执行重试
                        retry_result = await self.execute(
                            pipeline_id=pipeline_id or 0,
                            stage_name="TESTING_RETRY",
                            initial_state=retry_state
                        )
                        
                        if retry_result.get("success"):
                            retry_test_files = retry_result.get("output", {}).get("test_files", [])
                            
                            # 再次验证导入
                            if retry_test_files and interface_specs:
                                retry_import_errors = self._validate_test_imports_against_contract(
                                    retry_test_files, interface_specs
                                )
                                
                                if not retry_import_errors:
                                    # 重试成功，没有导入错误
                                    logger.info(f"[TesterAgent] 第 {retry_attempt + 1} 次重试成功，导入验证通过")
                                    if pipeline_id:
                                        await push_log(pipeline_id, "info", f"✅ 第 {retry_attempt + 1} 次重试成功，导入验证通过", stage="TESTING")
                                    return retry_result
                                else:
                                    # 仍有导入错误，继续重试
                                    error_msg = f"测试文件包含契约外的导入: {retry_import_errors}"
                                    logger.warning(f"[TesterAgent] 第 {retry_attempt + 1} 次重试后仍有导入错误: {retry_import_errors}")
                                    import_errors = retry_import_errors
                            else:
                                # 没有测试文件或没有契约，直接返回成功
                                return retry_result
                        else:
                            # 重试失败
                            logger.error(f"[TesterAgent] 第 {retry_attempt + 1} 次重试失败: {retry_result.get('error')}")
                            if retry_attempt == max_retries - 1:
                                # 最后一次重试失败，返回错误
                                return {
                                    "success": False,
                                    "error": f"重试 {max_retries} 次后仍然失败: {retry_result.get('error')}",
                                    "output": retry_result.get("output"),
                                    "input_tokens": retry_result.get("input_tokens", 0),
                                    "output_tokens": retry_result.get("output_tokens", 0),
                                    "duration_ms": retry_result.get("duration_ms", 0)
                                }
                    
                    # 重试次数用尽，返回最后一次的错误
                    logger.error(f"[TesterAgent] 重试 {max_retries} 次后仍然包含契约外导入")
                    return {
                        "success": False,
                        "error": f"重试 {max_retries} 次后，测试文件仍然包含契约外的导入: {import_errors}",
                        "output": result.get("output"),
                        "input_tokens": result.get("input_tokens", 0),
                        "output_tokens": result.get("output_tokens", 0),
                        "duration_ms": result.get("duration_ms", 0)
                    }
            
            logger.info(f"TesterAgent 测试生成完成", extra={
                "pipeline_id": pipeline_id,
                "test_files_count": len(test_files)
            })
            if pipeline_id:
                await push_log(pipeline_id, "info", f"测试生成完成，共 {len(test_files)} 个测试文件", stage="TESTING")
        else:
            logger.error(f"TesterAgent 测试生成失败", extra={
                "pipeline_id": pipeline_id,
                "error": result.get("error")
            })
            if pipeline_id:
                await push_log(pipeline_id, "error", f"测试生成失败: {result.get('error', '')}", stage="TESTING")

        return result

    # 测试基础设施白名单 - 这些模块/符号不需要在 interface_specs 中声明
    TEST_INFRASTRUCTURE_WHITELIST = {
        # 测试框架
        "pytest",
        "unittest",
        "unittest.mock",
        # FastAPI 测试客户端
        "app.main",
        "app.main.app",
        # 数据库 fixtures（通常定义在 conftest.py）
        "app.core.database",
        "app.core.db",
        "app.db",
        # 常用测试辅助
        "asyncio",
        "typing",
    }

    # 测试基础设施符号白名单
    TEST_SYMBOL_WHITELIST = {
        # FastAPI
        "TestClient",
        "AsyncClient",
        # pytest fixtures 常见名称
        "client",
        "async_client",
        "db_session",
        "mock_db",
        "test_db",
        # 其他常用
        "app",
        "AsyncMock",
        "patch",
        "MagicMock",
        "Mock",
    }

    def _is_test_infrastructure_import(self, module: str, symbol_name: str) -> bool:
        """
        检查是否是测试基础设施导入

        Args:
            module: 模块路径
            symbol_name: 符号名

        Returns:
            bool: 是否是测试基础设施导入
        """
        # 检查模块是否在白名单中
        for whitelist_module in self.TEST_INFRASTRUCTURE_WHITELIST:
            if module == whitelist_module or module.startswith(whitelist_module + "."):
                return True

        # 检查符号是否在白名单中
        if symbol_name in self.TEST_SYMBOL_WHITELIST:
            return True

        return False

    def _validate_test_imports_against_contract(
        self,
        test_files: List[Dict],
        interface_specs: List[Dict]
    ) -> List[str]:
        """
        【新增】验证测试文件的导入是否符合契约

        检查测试文件是否只导入了 interface_specs 中声明的符号。
        【放宽】允许测试文件导入被测模块中的任何符号（用于测试）。
        【放宽】允许测试基础设施导入（pytest、TestClient 等）。

        Args:
            test_files: 测试文件列表
            interface_specs: 接口契约列表

        Returns:
            List[str]: 导入错误列表
        """
        import ast
        errors = []

        # 构建契约中的符号集合
        allowed_symbols = set()
        allowed_modules = set()
        for spec in interface_specs:
            symbol = spec.get("symbol_name", "")
            module = spec.get("module", "")
            if symbol:
                allowed_symbols.add(symbol)
            if module:
                # 标准化模块路径（统一去掉 backend/ 前缀）
                module_path = module.replace("backend/", "").replace(".py", "").replace("/", ".")
                allowed_modules.add(module_path)

        for test_file in test_files:
            content = test_file.get("content", "")
            if not content:
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module
                    if not module or not module.startswith("app."):
                        continue

                    # 【放宽】允许从被测模块导入任何符号
                    # 只要模块路径匹配契约中的模块，就允许导入
                    module_in_contract = any(
                        module == allowed_module or module.startswith(allowed_module + ".")
                        for allowed_module in allowed_modules
                    )

                    if module_in_contract:
                        continue  # 被测模块，允许任何导入

                    # 【放宽】允许测试文件导入 app 包（用于测试 HTTP 端点）
                    if module == "app" or module.startswith("app.main"):
                        continue  # 允许从 app 或 app.main 导入任何符号

                    # 检查导入的符号
                    for alias in node.names:
                        symbol_name = alias.name
                        if symbol_name == "*":
                            continue  # 允许 from module import *

                        # 【放宽】允许测试基础设施导入
                        if self._is_test_infrastructure_import(module, symbol_name):
                            continue

                        if symbol_name not in allowed_symbols:
                            errors.append(
                                f"{test_file.get('file_path', '?')}: "
                                f"导入的符号 '{symbol_name}' 不在接口契约中"
                            )

        return errors


# 单例实例
tester_agent = TesterAgent()

# 向后兼容的别名
test_agent = tester_agent
