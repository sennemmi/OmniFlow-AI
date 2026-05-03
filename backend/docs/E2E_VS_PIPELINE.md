# E2E 测试 vs 真实 Pipeline 流程对比

## 流程对比表

| 阶段 | E2E 测试 (`test_e2e_with_contract_v2.py`) | 真实 Pipeline (`PipelineService`) | 一致性 |
|------|------------------------------------------|----------------------------------|--------|
| **Step 0** | 启动 Docker Sandbox | 启动 Docker Sandbox | ✅ 一致 |
| **Step 1** | ArchitectAgent 分析需求 | RequirementHandler 处理需求 | ✅ 一致 |
| **Step 2** | DesignerAgent 技术设计 | DesignHandler 技术设计 | ✅ 一致 |
| **Step 3** | 代码生成 (CoderAgent 传统模式) | CodingHandler 代码生成 (传统模式) | ✅ 一致 |
| **Step 3.5** | Linting 检查和自动修复 | ✅ Linting 检查和自动修复 | ✅ 一致 |
| **Step 4** | TesterAgent 生成测试 | TestingHandler 生成测试 | ✅ 一致 |
| **Step 5** | 语法验证 | TestingHandler 内执行 | ✅ 一致 |
| **Step 6** | 契约检查 | TestingHandler 内执行 | ✅ 一致 |
| **Step 7** | 测试导入验证 | TestingHandler 内执行 | ✅ 一致 |
| **Step 8** | 预测试 + 分层测试 + RepairerAgentWithTools 修复 | ✅ 预测试 + 分层测试 + RepairerAgentWithTools 修复 | ✅ 一致 |

---

## 详细功能对比

### 1. 代码生成阶段 (Step 3)

#### E2E 测试
```python
# E2E 测试中的代码生成（仅传统模式）
coder_result = await coder_agent.generate_code(...)
```

#### 真实 Pipeline (CodingHandler)
```python
# CodingHandler 中的代码生成
final_result = await self._generate_code_with_auto_fix(...)
```

**状态**: ✅ 一致（均使用传统模式）

**注意**: Architect/Editor 分离模式已从 E2E 和 Pipeline 中移除

---

### 2. Linting 检查 (Step 3.5)

#### E2E 测试
```python
# E2E 测试中的 Linting 检查
linting_passed, code_files = await self._run_linting_check(code_files, file_service)
```

#### 真实 Pipeline
```python
# CodingHandler 中的 Linting 检查
linting_passed, fixed_files = await self._run_linting_check(
    code_files=all_files,
    file_service=file_service
)
```

**状态**: ✅ 已同步

**文件位置**: `app/service/stage_handlers/coding_handler.py`

---

### 3. 测试执行和修复 (Step 8)

#### E2E 测试
```python
# E2E 测试中的测试执行
# 1. 预测试
preliminary_result = await self.e2e_service.run_preliminary_test(...)

# 2. 分层测试
layered_result = await self.e2e_service.run_layered_tests(...)

# 3. 如果测试失败，启动 RepairerAgentWithTools 修复
if not layered_result.all_passed:
    repairer = RepairerAgentWithTools()
    repair_result = await repairer.execute_with_tools(...)
```

#### 真实 Pipeline (TestingHandler)
```python
# TestingHandler 中的测试执行
# 1. 预测试
preliminary_result = await self._run_preliminary_test(...)

# 2. 分层测试
layered_result = await self._run_layered_tests(...)

# 3. RepairerAgentWithTools 修复
repairer = RepairerAgentWithTools()
repair_result = await repairer.execute_with_tools(...)
```

**状态**: ✅ 已同步

**文件位置**: `app/service/stage_handlers/testing_handler.py`

---

### 4. 文件选择策略

#### E2E 测试
```python
# E2E 测试中的文件选择
essential_paths = extract_critical_files(logs, generated_file_paths)
# ❌ 不再强制注入核心契约文件
# 💡 提示 RepairerAgent 使用工具探索 import 依赖
```

#### 真实 Pipeline
```python
# TestingHandler 中的文件选择
essential_paths = extract_critical_files(
    logs=test_logs,
    all_generated_paths=generated_file_paths
)
# ❌ 不再强制注入核心契约文件
# 💡 提示 RepairerAgent 使用 read_file/grep/glob 等工具探索 import 依赖
```

**状态**: ✅ 已同步

---

### 5. AgentDebugger 调试工具

#### E2E 测试
```python
# E2E 测试中的调试工具
self.debugger = AgentDebugger(
    enabled=debug_enabled,
    output_dir=AGENT_DEBUG_OUTPUT_DIR
)
```

#### 真实 Pipeline
```python
# Pipeline 中的调试工具 (base.py)
class StageHandler(ABC):
    def __init__(self):
        self.debugger = AgentDebugger(
            enabled=settings.AGENT_DEBUG_ENABLED,
            output_dir=settings.AGENT_DEBUG_OUTPUT_DIR
        )
```

**状态**: ✅ 已同步

---

## 已移除的功能

### ❌ Architect/Editor 分离模式

**状态**: 已从 E2E 和 Pipeline 中完全移除

**原因**: 
- 模式过于不成熟
- JSON 解析失败率高
- LLM 返回空内容问题
- 维护成本高

**当前实现**:
- E2E 测试：仅保留传统 CoderAgent 模式
- Pipeline：仅保留传统模式

---

## 同步完成的修改

### ✅ CodingHandler
- [x] Linting 检查 (`_run_linting_check`)
- [x] 使用 AgentDebugger 保存调试信息

### ✅ TestingHandler
- [x] RepairerAgentWithTools
- [x] extract_critical_files 精简文件
- [x] 移除强制注入核心契约文件
- [x] 预测试 (Preliminary Test)
- [x] 分层测试 (LayeredTestRunner)
- [x] E2ETestService 集成

### ✅ Base Handler
- [x] AgentDebugger 集成

### ✅ Config
- [x] AgentDebugger 配置 (`AGENT_DEBUG_ENABLED`, `AGENT_DEBUG_OUTPUT_DIR`)

---

## 架构对比

### E2E 测试架构
```
test_e2e_with_contract_v2.py
├── ArchitectAgent (需求分析)
├── DesignerAgent (技术设计)
├── CoderAgent (代码生成)
│   └── Linting 检查
├── TesterAgent (测试生成)
└── RepairerAgentWithTools (自动修复)
    ├── 预测试
    ├── 分层测试
    └── 工具调用 (read_file/grep/glob)
```

### Pipeline 架构
```
PipelineService
├── RequirementHandler
│   └── ArchitectAgent
├── DesignHandler
│   └── DesignerAgent
├── CodingHandler
│   ├── CoderAgent
│   └── Linting 检查 ✅
└── TestingHandler
    ├── TesterAgent
    ├── 预测试 ✅
    ├── 分层测试 ✅
    └── RepairerAgentWithTools ✅
```

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `scripts/test_e2e_with_contract_v2.py` | E2E 测试脚本 |
| `app/service/pipeline.py` | Pipeline 服务 |
| `app/service/stage_handlers/coding_handler.py` | 代码生成处理器 (含 Linting) |
| `app/service/stage_handlers/testing_handler.py` | 测试处理器 (含预测试、分层测试、RepairerAgentWithTools) |
| `app/service/stage_handlers/base.py` | 基础处理器 (含 AgentDebugger) |
| `app/service/e2e_test_service.py` | 统一测试服务 |
| `app/service/layered_test_runner.py` | 分层测试运行器 |
| `app/utils/repair_utils.py` | 文件选择工具 |
