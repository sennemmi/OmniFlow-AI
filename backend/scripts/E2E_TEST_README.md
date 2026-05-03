# E2E 端到端测试文档

## 概述

本文档介绍 OmniFlow-AI 的端到端（E2E）测试系统，该系统基于**三阶段重构架构**实现，支持多种代码生成模式和自动化质量检查。

## 三阶段重构架构

### 第一阶段：建立防线（短期）

目标：在不改变核心架构的前提下，通过工具化手段为现有流程增加一层安全网和修复能力。

#### 1.1 Linting-修复自动化 Hook
- **功能**：代码生成后自动运行 `ruff` 检查，捕获语法和格式错误
- **自动修复**：发现问题时自动运行 `ruff check --fix` 进行修复
- **配置项**：
  ```bash
  set LINTING_ENABLED=true     # 启用/禁用
  set LINTING_MAX_RETRIES=3    # 最大修复重试次数
  ```

#### 1.2 code_apply 工具
- **功能**：精确的 search/replace 执行器
- **特点**：
  - 只做精确匹配，不做模糊匹配
  - 失败时返回结构化错误信息（而非 None）
  - 四级诊断：换行符差异、缩进差异、模糊匹配、完全找不到
- **位置**：`app/agents/tools_code_apply.py`

---

### 第二阶段：双轨实验（中期）

目标：在不影响现有流程稳定性的前提下，以 A/B 测试的方式引入可回退的指令式生成流程。

#### 2.1 Architect/Editor 分离模式
- **Architect（架构师）**：负责理解需求、规划修改、读取代码
  - 只读工具：`read_file`, `grep_ast`, `glob`, `grep`
  - 输出：`edit_plan` 编辑指令清单
  
- **Editor（编辑者）**：接收精确指令，执行工具调用
  - 编辑工具：`code_apply`, `func_replace`, `insert_after`, `delete_lines`
  - 职责：不做推理，只做机械编辑

- **编排器**：`app/agents/architect_editor_orchestrator.py`
  - Phase 1: Architect 分析并生成 edit_plan
  - Phase 2: Editor 逐条执行 edit_plan
  - 失败时自动原子撤销（回退到上一个成功的 checkpoint）

#### 2.2 智能回退逻辑
```python
CODE_GEN_MODE = os.environ.get("CODE_GEN_MODE", "auto")
```

| 模式 | 说明 |
|------|------|
| `auto` | **默认**。优先使用 Architect/Editor 模式，失败时自动回退到传统模式 |
| `tool_based` | 强制使用 Architect/Editor 分离模式 |
| `legacy` | 强制使用传统 CoderAgent 直接生成完整代码 |

#### 2.3 检查点 (Snapshotting) 机制
- 每次代码修改前自动 `git stash` 保存当前状态
- 修改失败时可一键回滚
- 确保实验安全性

---

### 第三阶段：全面重构（长期）

目标：彻底改变代码交互的核心范式，从"打包式生成"转变为"流式交互与微提交"。

#### 3.1 交互式编辑器工具集
完整工具列表（`app/agents/tools.py`）：

| 工具名 | 功能 | 使用场景 |
|--------|------|----------|
| `read_file` | 读取文件指定行范围 | 获取代码上下文 |
| `grep` | 文本搜索 | 查找代码片段 |
| `glob` | 文件查找 | 发现项目文件 |
| `code_apply` | 精确 search/replace | 修改代码块 |
| `func_replace` | 替换整个函数 | 函数级修改 |
| `insert_after` | 在指定行后插入 | 添加新代码 |
| `delete_lines` | 删除指定行范围 | 移除代码 |
| `install_dependency` | 安装 Python 包 | 修复依赖缺失 |

#### 3.2 微提交 (Micro-commits)
- 每次成功的工具调用视为一个原子操作
- 自动执行 `git commit`，形成小型提交
- 提交信息格式：`micro: {tool_name} on {file_path}`
- 增强可回溯性，支持"后悔药"和试验性编程

#### 3.3 架构师/编辑者分离模式
- **优势**：
  - 降低对单一模型的能力要求
  - Architect 专注推理规划，Editor 专注精确执行
  - 提升整体可靠性

---

## 使用方法

### 基本用法

```bash
# 进入后端目录
cd backend

# 默认模式运行（自动选择最优模式）
python scripts/test_e2e_with_contract_v2.py
```

### 环境变量配置

#### 代码生成模式
```bash
# Windows
set CODE_GEN_MODE=auto          # 默认：自动选择
set CODE_GEN_MODE=tool_based    # 强制 Architect/Editor 模式
set CODE_GEN_MODE=legacy        # 强制传统模式

# Linux/Mac
export CODE_GEN_MODE=auto
```

#### Linting 配置
```bash
# Windows
set LINTING_ENABLED=true        # 启用 Linting 检查（默认）
set LINTING_ENABLED=false       # 禁用
set LINTING_MAX_RETRIES=3       # 最大修复重试次数

# Linux/Mac
export LINTING_ENABLED=true
export LINTING_MAX_RETRIES=3
```

#### 调试配置
```bash
# Windows
set AGENT_DEBUG_ENABLED=true    # 启用 Agent 调试输出
set AGENT_DEBUG_OUTPUT_DIR=./agent_debug_output

# Linux/Mac
export AGENT_DEBUG_ENABLED=true
export AGENT_DEBUG_OUTPUT_DIR=./agent_debug_output
```

### 使用 pytest 运行

```bash
# 安装依赖
pip install pytest pytest-asyncio

# 运行测试
pytest scripts/test_e2e_with_contract_v2.py -v

# 指定模式运行
set CODE_GEN_MODE=tool_based
pytest scripts/test_e2e_with_contract_v2.py -v
```

---

## 测试流程

```
Step 1: ArchitectAgent 分析需求
    ↓
Step 2: DesignerAgent 技术设计（生成 interface_specs 契约）
    ↓
Step 3: 代码生成（根据 CODE_GEN_MODE 选择模式）
    ├─ auto: 尝试 Architect/Editor → 失败则回退到 CoderAgent
    ├─ tool_based: 强制 Architect/Editor
    └─ legacy: 强制 CoderAgent
    ↓
Step 3.5: Linting 检查和自动修复（如果启用）
    ↓
Step 4: TesterAgent 生成测试
    ↓
Step 5: 语法验证
    ↓
Step 6: 契约检查
    ↓
Step 7: 测试导入和语法验证
    ↓
Step 8: 运行测试
    ├─ 8.1: 预测试
    ├─ 8.2: 分层测试
    └─ Auto-Fix 循环（如果失败）
```

---

## 输出解读

### 成功示例
```
======================================================================
📊 测试执行摘要
======================================================================
成功: ✅ 是
代码生成: ✅
测试生成: ✅
测试通过: ✅
代码生成模式: tool_based
Linting 检查: ✅ 通过
总耗时: 45.2s
======================================================================
```

### 失败示例
```
======================================================================
📊 测试执行摘要
======================================================================
成功: ❌ 否
代码生成: ✅
测试生成: ✅
测试通过: ❌
代码生成模式: legacy
Linting 检查: ⚠️ 有警告
总耗时: 120.5s
错误: 达到最大修复轮数
======================================================================
```

---

## 调试输出

启用调试后，Agent 的输入输出将保存到 `agent_debug_output/<session_id>/` 目录：

```
agent_debug_output/
└── 20260503_173112/
    ├── 001_ArchitectAgent_analyze.json
    ├── 002_DesignerAgent_design.json
    ├── 003_CoderAgent_generate_code.json
    ├── 004_TesterAgent_generate_tests.json
    ├── 005_RepairerAgent_repair_round_1.json
    ├── 006_RepairerAgent_repair_round_2.json
    └── summary.json
```

每个 JSON 文件包含：
- `input`: Agent 的输入数据
- `output`: Agent 的输出结果
- `system_prompt`: 使用的系统提示词
- `tool_calls`: 工具调用记录
- `metadata`: 元数据（token 使用量等）

---

## 故障排查

### 1. Docker 启动失败
```
❌ Sandbox 启动失败
```
**解决**：
```bash
# 检查 Docker 状态
docker ps

# 手动清理残留容器
docker rm -f $(docker ps -aq --filter name=omniflow-sandbox)
```

### 2. Architect/Editor 模式失败
```
⚠️ Architect/Editor 模式失败: 错误信息
📝 使用传统 CoderAgent 模式生成代码...
```
**说明**：这是正常的自动回退行为，测试会继续使用传统模式执行。

### 3. Linting 检查警告
```
⚠️ Linting 检查后仍有 X 个文件有问题
```
**说明**：Linting 警告不会阻止测试继续执行，但建议检查代码风格。

### 4. 测试修复循环
```
🔧 启动 Auto-Fix（智能错误路由）...
🔄 第 1/3 次修复
🎯 检测到错误类型: syntax
```
**说明**：系统会自动尝试修复测试失败，最多 3 次重试。

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `scripts/test_e2e_with_contract_v2.py` | E2E 测试主脚本 |
| `app/agents/architect_editor_orchestrator.py` | Architect/Editor 编排器 |
| `app/agents/coder_architect.py` | Architect Agent |
| `app/agents/coder_editor.py` | Editor Agent |
| `app/agents/tools.py` | Agent 工具集 |
| `app/agents/tools_code_apply.py` | code_apply 工具实现 |
| `app/core/experiment.py` | 代码生成模式配置 |
| `app/service/e2e_test_service.py` | E2E 测试服务 |

---

## 架构对比

### 传统模式 (legacy)
```
User Request → CoderAgent → 完整代码 JSON → 写入文件 → 测试
```
- **优点**：简单直接，一次生成完整代码
- **缺点**：容易生成不匹配的文件，search_block 匹配失败率高

### 工具模式 (tool_based)
```
User Request → Architect → edit_plan → Editor → 工具调用 → 微提交 → 测试
```
- **优点**：
  - 精确编辑，失败时可原子撤销
  - 每次修改都有 git 记录
  - 更适合复杂修改场景
- **缺点**：
  - 流程更复杂
  - 需要更多 LLM 调用

### 自动模式 (auto) - 推荐
```
User Request → 尝试工具模式 ──成功──→ 测试
                    │
                    └──失败──→ 回退到传统模式 → 测试
```
- **优点**：兼顾可靠性和成功率
- **适用场景**：生产环境默认使用

---

## 未来规划

1. **完全移除 legacy 模式**：待 tool_based 模式稳定后
2. **增强 Linting 规则**：集成更多代码质量检查
3. **智能模式选择**：根据需求复杂度自动选择最佳模式
4. **并行测试执行**：支持多个 E2E 测试并行运行

---

## 贡献指南

如需修改 E2E 测试系统：

1. **新增工具**：在 `app/agents/tools.py` 中添加工具定义和执行逻辑
2. **修改编排逻辑**：编辑 `app/agents/architect_editor_orchestrator.py`
3. **调整测试流程**：修改 `scripts/test_e2e_with_contract_v2.py`
4. **更新文档**：同步更新本文档

---

## 许可证

本项目采用与 OmniFlow-AI 相同的许可证。
