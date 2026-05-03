# E2E 测试 vs Pipeline 功能对比

## 功能对比表

| 功能 | E2E 测试 | Pipeline | 状态 |
|------|---------|----------|------|
| **核心流程** | | | |
| ArchitectAgent | ✅ | ✅ | 一致 |
| DesignerAgent | ✅ | ✅ | 一致 |
| CoderAgent | ✅ | ✅ (MultiAgentCoordinator) | 一致 |
| TesterAgent | ✅ | ✅ (MultiAgentCoordinator) | 一致 |
| **代码生成增强** | | | |
| Linting 检查 | ✅ | ✅ **已同步** | 一致 |
| Auto-Fix 循环 | ✅ | ✅ | 一致 |
| **测试执行** | | | |
| 分层测试 (LayeredTest) | ✅ | ✅ **已同步** | 一致 |
| E2ETestService | ✅ | ✅ **已同步** | 一致 |
| 预测试 (Preliminary) | ✅ | ✅ **已同步** | 一致 |
| **修复机制** | | | |
| RepairerAgentWithTools | ✅ | ✅ **已同步** | 一致 |
| extract_critical_files | ✅ | ✅ **已同步** | 一致 |
| 文件选择策略 | ✅ Traceback关联 | ✅ Traceback关联 | 一致 |
| **调试工具** | | | |
| AgentDebugger | ✅ | ✅ **已同步** | 一致 |
| 调试输出保存 | ✅ | ✅ **已同步** | 一致 |
| **验证流程** | | | |
| 语法验证 | ✅ | ✅ | 一致 |
| 契约检查 | ✅ | ✅ | 一致 |
| 测试导入验证 | ✅ | ✅ | 一致 |
| **其他** | | | |
| 代码库索引 | ❌ | ✅ | Pipeline特有 |
| 多Agent协作 | ❌ | ✅ | Pipeline特有 |

---

## 同步完成的功能

### ✅ 1. 分层测试 (Layered Test Runner)

**状态**: 已同步到 Pipeline

**Pipeline 中的实现**:
```python
# TestingHandler._run_layered_tests()
from app.service.layered_test_runner import LayeredTestRunner

layered_result = await LayeredTestRunner.run(
    workspace_path=workspace_dir,
    new_files=all_files,
    sandbox_port=None,
    timeout=120,
    file_service=file_service
)
```

**文件位置**: `app/service/stage_handlers/testing_handler.py` (line 97-169)

---

### ✅ 2. E2ETestService

**状态**: 已同步到 Pipeline

**Pipeline 中的实现**:
```python
# TestingHandler 中导入并使用
from app.service.e2e_test_service import e2e_test_service

# 用于预测试
result = await e2e_test_service.run_preliminary_test(...)
```

**文件位置**: `app/service/stage_handlers/testing_handler.py`

---

### ✅ 3. 预测试 (Preliminary Test)

**状态**: 已同步到 Pipeline

**Pipeline 中的实现**:
```python
# TestingHandler._run_preliminary_test()
async def _run_preliminary_test(self, pipeline_id, test_files, code_files, ...):
    result = await e2e_test_service.run_preliminary_test(
        pipeline_id=pipeline_id,
        test_files=test_files,
        file_service=file_service
    )
    return result
```

**文件位置**: `app/service/stage_handlers/testing_handler.py` (line 175-260)

**集成点**: 在 `_generate_tests_with_retry` 中，写入测试文件后、完整测试前调用

---

### ✅ 4. AgentDebugger

**状态**: 已同步到 Pipeline

**Pipeline 中的实现**:
```python
# base.py 中初始化
from app.core.agent_debugger import AgentDebugger
from app.core.config import settings

class StageHandler(ABC):
    def __init__(self):
        self.debugger = AgentDebugger(
            enabled=settings.AGENT_DEBUG_ENABLED,
            output_dir=settings.AGENT_DEBUG_OUTPUT_DIR
        )
```

**配置位置**: `app/core/config.py`
```python
AGENT_DEBUG_ENABLED: bool = True
AGENT_DEBUG_OUTPUT_DIR: str = "./agent_debug_output"
```

---

### ✅ 5. RepairerAgentWithTools

**状态**: 已同步到 Pipeline

**Pipeline 中的实现**:
```python
# TestingHandler._run_auto_fix_with_repairer()
from app.agents.repairer_with_tools import RepairerAgentWithTools

repairer = RepairerAgentWithTools()
repair_result = await repairer.execute_with_tools(
    pipeline_id=pipeline_id,
    stage_name="UNIT_TESTING_REPAIR",
    fix_order=fix_order,
    target_files=target_files,
    max_rounds=3
)
```

**文件位置**: `app/service/stage_handlers/testing_handler.py` (line 321-539)

---

### ✅ 6. 文件选择策略 (Traceback 关联)

**状态**: 已同步到 Pipeline

**Pipeline 中的实现**:
```python
# 使用 extract_critical_files 精简文件列表
from app.utils.repair_utils import extract_critical_files

essential_paths = extract_critical_files(
    logs=test_logs,
    all_generated_paths=generated_file_paths
)
```

**特点**:
- ❌ 不再强制注入所有核心契约文件
- 💡 提示 RepairerAgent 使用 read_file/grep/glob 等工具探索 import 依赖

---

### ✅ 7. Linting 检查

**状态**: 已同步到 Pipeline

**Pipeline 中的实现**:
```python
# CodingHandler._run_linting_check()
async def _run_linting_check(self, code_files, file_service):
    # 使用 ruff 检查代码
    # 自动修复问题
    # 返回修复后的代码文件
```

**文件位置**: `app/service/stage_handlers/coding_handler.py`

---

## Pipeline 特有的功能（E2E 测试不需要）

### 1. 代码库索引 (CodeIndexer)
- 语义检索、向量数据库
- E2E 测试使用工具探索代替

### 2. 多 Agent 协作 (MultiAgentCoordinator)
- CoderAgent 和 TestAgent 协作
- E2E 测试使用串行执行

---

## 已移除的功能

### ❌ Architect/Editor 分离模式

**状态**: 已从 E2E 和 Pipeline 中移除

**原因**: 模式过于不成熟，稳定性差

**当前状态**:
- E2E 测试：仅保留传统模式
- Pipeline：仅保留传统模式

---

## 同步历史记录

| 日期 | 同步内容 | 状态 |
|------|---------|------|
| 2026-05-03 | Linting 检查同步到 CodingHandler | ✅ 完成 |
| 2026-05-03 | RepairerAgentWithTools 同步到 TestingHandler | ✅ 完成 |
| 2026-05-03 | 文件选择策略同步 (Traceback 关联) | ✅ 完成 |
| 2026-05-03 | AgentDebugger 同步到 base handler | ✅ 完成 |
| 2026-05-03 | E2ETestService 集成到 TestingHandler | ✅ 完成 |
| 2026-05-03 | LayeredTestRunner 同步到 TestingHandler | ✅ 完成 |
| 2026-05-03 | 预测试 (Preliminary Test) 同步到 TestingHandler | ✅ 完成 |
| 2026-05-03 | Architect/Editor 模式从 E2E 移除 | ✅ 完成 |

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `scripts/test_e2e_with_contract_v2.py` | E2E 测试脚本 |
| `app/service/stage_handlers/coding_handler.py` | 代码生成处理器 (含 Linting) |
| `app/service/stage_handlers/testing_handler.py` | 测试处理器 (含预测试、分层测试、RepairerAgentWithTools) |
| `app/service/stage_handlers/base.py` | 基础处理器 (含 AgentDebugger) |
| `app/service/e2e_test_service.py` | 统一测试服务 |
| `app/service/layered_test_runner.py` | 分层测试运行器 |
| `app/core/config.py` | 配置 (含 AgentDebugger 配置) |
| `app/utils/repair_utils.py` | 文件选择工具 |
