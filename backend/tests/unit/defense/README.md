# 防御性测试（Defense Tests）

防御性测试是 OmniFlowAI 系统的"免疫系统"，用于防止 AI 写出灾难性代码。

## 四层防线

| 层级 | 名称 | 目的 | 关键测试 |
|------|------|------|----------|
| Layer 1 | 代码修改与沙箱防线 | 防止 AI 破坏物理文件 | 文件回滚、路径安全、导入清理、**并发安全** |
| Layer 2 | 测试运行器与决策防线 | 防止"旧测试"被 AI 篡改 | 语法拦截、防御性保护、回归保护、**测试隔离** |
| Layer 3 | 多 Agent 协作与状态机防线 | 防止系统死循环 | Pydantic 校验、重试限制、JSON 剥离、**Token限制**、**代码-测试契约** |
| Layer 4 | 工作流与状态持久化防线 | 确保界面显示正确 | 状态流转限制、反馈传递、**事务完整性** |

---

## 三阶段重构与防御性测试

### 第一阶段：建立防线（短期）

#### 1.1 Linting-修复自动化 Hook 测试
**目标**：验证代码生成后的自动 Lint 检查和修复机制

**测试要点**：
- `test_linting_hook_execution` - Linting Hook 正确执行
- `test_linting_error_detection` - 准确检测代码风格错误
- `test_linting_auto_fix` - 自动修复功能正常工作
- `test_linting_path_handling` - 正确处理沙箱路径（backend/xxx）
- `test_linting_e902_filtering` - 过滤文件不存在错误（E902）

**相关代码**：
- `scripts/test_e2e_with_contract_v2.py` - `_run_linting_check()` 方法
- `app/service/code_validation_service.py` - 代码验证服务

#### 1.2 code_apply 工具测试
**目标**：验证精确的 search/replace 执行器

**测试要点**：
- `test_code_apply_exact_match` - 精确匹配成功替换
- `test_code_apply_non_unique_detection` - 检测非唯一 search_block
- `test_code_apply_newline_mismatch` - 识别换行符差异（\r\n vs \n）
- `test_code_apply_indentation_mismatch` - 识别缩进差异
- `test_code_apply_fuzzy_mismatch` - 模糊匹配诊断
- `test_code_apply_structured_error` - 返回结构化错误信息

**相关代码**：
- `app/agents/tools_code_apply.py` - CodeApplyTool 类

---

### 第二阶段：双轨实验（中期）

#### 2.1 Architect/Editor 分离模式测试
**目标**：验证架构师规划 + 编辑者执行的分离流程

**测试要点**：
- `test_architect_read_only_tools` - Architect 只能使用只读工具
- `test_architect_edit_plan_generation` - 正确生成 edit_plan
- `test_editor_tool_execution` - Editor 正确执行编辑工具
- `test_editor_no_reasoning` - Editor 不做额外推理
- `test_orchestrator_phase_transition` - Phase 1 → Phase 2 正确流转
- `test_orchestrator_failure_rollback` - 失败时原子撤销

**相关代码**：
- `app/agents/architect_editor_orchestrator.py` - 编排器
- `app/agents/coder_architect.py` - Architect Agent
- `app/agents/coder_editor.py` - Editor Agent

#### 2.2 智能回退逻辑测试
**目标**：验证工具模式失败时自动回退到传统模式

**测试要点**：
- `test_auto_mode_tool_based_first` - auto 模式优先尝试工具模式
- `test_auto_mode_fallback_to_legacy` - 失败时回退到传统模式
- `test_legacy_mode_no_fallback` - legacy 模式不回退
- `test_tool_based_mode_no_fallback` - tool_based 模式失败时直接报错
- `test_code_gen_mode_env_var` - CODE_GEN_MODE 环境变量生效

**相关代码**：
- `app/core/experiment.py` - CodeGenMode 枚举
- `scripts/test_e2e_with_contract_v2.py` - 模式选择逻辑

#### 2.3 检查点 (Snapshotting) 机制测试
**目标**：验证每次修改前自动保存状态

**测试要点**：
- `test_checkpoint_before_edit` - 编辑前自动创建检查点
- `test_atomic_rollback_on_failure` - 失败时原子撤销
- `test_commit_history_tracking` - 提交历史正确记录
- `test_rollback_to_specific_checkpoint` - 回退到指定检查点
- `test_checkpoint_cleanup` - 检查点清理机制

**相关代码**：
- `app/service/snapshot_service.py` - 快照服务
- `app/agents/architect_editor_orchestrator.py` - 检查点调用

---

### 第三阶段：全面重构（长期）

#### 3.1 交互式编辑器工具集测试
**目标**：验证完整的工具集功能

**测试要点**：
- `test_tool_read_file` - read_file 工具正确读取文件
- `test_tool_grep` - grep 工具正确搜索内容
- `test_tool_glob` - glob 工具正确查找文件
- `test_tool_replace_lines` - replace_lines 工具正确替换
- `test_tool_func_replace` - func_replace 工具替换整个函数
- `test_tool_insert_after` - insert_after 工具正确插入
- `test_tool_delete_lines` - delete_lines 工具正确删除
- `test_tool_install_dependency` - install_dependency 安装依赖

**相关代码**：
- `app/agents/tools.py` - AgentTools 类
- `app/agents/agent_tools_core.py` - 核心工具实现
- `app/agents/agent_tools_advanced.py` - 高级工具实现

#### 3.2 微提交 (Micro-commits) 测试
**目标**：验证每次成功工具调用后自动 git commit

**测试要点**：
- `test_micro_commit_after_tool_success` - 工具成功后自动提交
- `test_micro_commit_message_format` - 提交信息格式正确
- `test_micro_commit_no_commit_on_failure` - 失败时不提交
- `test_micro_commit_history` - 微提交历史可追溯
- `test_micro_commit_rollback` - 支持微提交级别回滚

**相关代码**：
- `app/agents/tools.py` - `_micro_commit()` 方法

#### 3.3 架构师/编辑者分离优势测试
**目标**：验证分离模式降低模型能力要求

**测试要点**：
- `test_architect_focus_on_planning` - Architect 专注规划
- `test_editor_focus_on_execution` - Editor 专注执行
- `test_separation_reduces_complexity` - 分离降低单模型复杂度
- `test_reliability_improvement` - 整体可靠性提升
- `test_error_isolation` - 错误隔离性

---

## 测试文件列表

### Layer 1 - 代码修改与沙箱防线
- `test_layer1_code_sandbox.py` - 基础文件操作安全
- `test_layer1_concurrent_file_safety.py` - **并发文件操作安全**

**新增测试（第一阶段）**：
- `test_layer1_linting_hook.py` - Linting-修复自动化 Hook
- `test_layer1_code_apply_tool.py` - code_apply 工具安全

### Layer 2 - 测试运行器与决策防线
- `test_layer2_test_runner.py` - 测试运行器决策逻辑
- `test_layer2_test_isolation.py` - **测试隔离性**

### Layer 3 - 多 Agent 协作与状态机防线
- `test_layer3_multi_agent.py` - Agent 协作基础
- `test_layer3_token_limit.py` - **Token 消耗限制**
- `test_layer3_contract_enforcement.py` - **代码-测试契约强制**

**新增测试（第二阶段）**：
- `test_layer3_architect_editor_separation.py` - Architect/Editor 分离
- `test_layer3_smart_fallback.py` - 智能回退逻辑
- `test_layer3_checkpoint_mechanism.py` - 检查点机制

### Layer 4 - 工作流与状态持久化防线
- `test_layer4_workflow_state.py` - 工作流状态管理
- `test_layer4_transaction_integrity.py` - **数据库事务完整性**

**新增测试（第三阶段）**：
- `test_layer4_micro_commits.py` - 微提交机制
- `test_layer4_interactive_editor.py` - 交互式编辑器工具集

---

## 运行命令

### 方法 1: 使用 Makefile（推荐）

```bash
# 运行所有防御性测试
make test-defense

# 详细模式（显示完整日志）
make test-defense-verbose

# 按阶段运行（三阶段重构）
make test-defense-phase1  # 第一阶段：建立防线
make test-defense-phase2  # 第二阶段：双轨实验
make test-defense-phase3  # 第三阶段：全面重构
```

### 方法 2: 使用 Python 脚本

```bash
# 运行所有防御性测试
python scripts/run_defense_tests.py

# 详细模式
python scripts/run_defense_tests.py --verbose

# 只运行特定层
python scripts/run_defense_tests.py --layer=1  # Layer 1
python scripts/run_defense_tests.py --layer=2  # Layer 2
python scripts/run_defense_tests.py --layer=3  # Layer 3
python scripts/run_defense_tests.py --layer=4  # Layer 4

# 按阶段运行（三阶段重构）
python scripts/run_defense_tests.py --phase=1  # 第一阶段
python scripts/run_defense_tests.py --phase=2  # 第二阶段
python scripts/run_defense_tests.py --phase=3  # 第三阶段
```

### 方法 3: 直接使用 pytest

```bash
# 运行所有防御性测试
cd backend
python -m pytest tests/unit/defense -v

# 按标记运行
python -m pytest tests/unit/defense -m defense -v
python -m pytest tests/unit/defense -m layer1 -v
python -m pytest tests/unit/defense -m layer2 -v
python -m pytest tests/unit/defense -m layer3 -v
python -m pytest tests/unit/defense -m layer4 -v

# 按阶段标记运行
python -m pytest tests/unit/defense -m phase1 -v
python -m pytest tests/unit/defense -m phase2 -v
python -m pytest tests/unit/defense -m phase3 -v

# 快速检查（只显示失败）
python -m pytest tests/unit/defense --tb=line
```

---

## 三阶段重构测试检查清单

### 第一阶段检查清单
- [ ] Linting Hook 正确执行
- [ ] 自动修复功能正常
- [ ] code_apply 工具精确匹配
- [ ] 四级诊断信息准确
- [ ] 路径处理正确（backend/xxx）

### 第二阶段检查清单
- [ ] Architect 只读工具限制
- [ ] Editor 正确执行编辑
- [ ] 编排器 Phase 流转正确
- [ ] 失败时原子撤销
- [ ] 智能回退逻辑生效
- [ ] 检查点创建和回滚

### 第三阶段检查清单
- [ ] 所有工具功能正常
- [ ] 微提交自动执行
- [ ] 提交信息格式正确
- [ ] 工具调用可追溯
- [ ] 分离模式可靠性提升

---

## 在代码提交前运行

建议在以下时机运行防御性测试：

1. **修改任何服务代码前** - 确保系统保护机制正常
2. **修改 `app/service/` 目录后** - 验证文件操作安全
3. **修改 `app/agents/` 目录后** - 验证 Agent 协作机制
4. **修改 `app/models/` 目录后** - 验证状态机正确性
5. **修改 E2E 测试脚本后** - 验证三阶段重构功能
6. **提交 PR 前** - 作为最终检查

### 三阶段重构特定检查点

**第一阶段修改后检查**：
```bash
python -m pytest tests/unit/defense -m "phase1 or linting or code_apply" -v
```

**第二阶段修改后检查**：
```bash
python -m pytest tests/unit/defense -m "phase2 or architect_editor or checkpoint" -v
```

**第三阶段修改后检查**：
```bash
python -m pytest tests/unit/defense -m "phase3 or micro_commit or tool" -v
```

---

## 测试失败处理

如果防御性测试失败：

1. **不要尝试自动修复** - 防御性测试失败意味着代码破坏了核心保护机制
2. **查看错误信息** - 运行 `make test-defense-verbose` 查看详细日志
3. **人工检查代码** - 重点检查是否修改了 `tests/unit/defense/` 下的测试文件
4. **回滚或重构** - 根据错误信息决定是回滚代码还是重构实现

### 三阶段重构特定问题排查

**Linting 检查失败**：
```bash
# 检查路径处理
python -m pytest tests/unit/defense/test_layer1_linting_hook.py -v
```

**Architect/Editor 分离失败**：
```bash
# 检查分离模式
python -m pytest tests/unit/defense/test_layer3_architect_editor_separation.py -v
```

**微提交失败**：
```bash
# 检查微提交机制
python -m pytest tests/unit/defense/test_layer4_micro_commits.py -v
```

---

## 为什么不能修改防御性测试？

防御性测试是系统的"免疫系统"，它们保护：

- **文件系统安全** - 防止 AI 写入错误路径或破坏文件
- **测试完整性** - 防止 AI 为通过测试而篡改测试本身
- **系统稳定性** - 防止无限循环和资源耗尽
- **状态一致性** - 防止 Pipeline 状态错乱
- **代码质量** - 防止生成不符合规范的代码（三阶段重构新增）
- **可回溯性** - 防止无法追踪代码修改历史（三阶段重构新增）

修改这些测试 = 拆除系统的安全护栏。

---

## 相关文档

- [E2E 测试文档](../../scripts/E2E_TEST_README.md) - E2E 测试三阶段重构说明
- [架构设计文档](../../docs/architecture.md) - 系统架构设计
- [Agent 工具文档](../../docs/agent_tools.md) - Agent 工具使用说明

---

## 贡献指南

添加新的防御性测试：

1. **确定测试层级** - 根据保护目标选择 Layer 1-4
2. **确定测试阶段** - 根据三阶段重构选择 Phase 1-3
3. **编写测试文件** - 遵循现有测试文件命名规范
4. **添加标记** - 使用 pytest 标记便于筛选运行
5. **更新本文档** - 同步更新测试列表和检查清单

### 测试标记规范

```python
import pytest

@pytest.mark.defense  # 所有防御性测试
@pytest.mark.layer1   # Layer 1 测试
@pytest.mark.layer2   # Layer 2 测试
@pytest.mark.layer3   # Layer 3 测试
@pytest.mark.layer4   # Layer 4 测试

# 三阶段重构标记
@pytest.mark.phase1   # 第一阶段：建立防线
@pytest.mark.phase2   # 第二阶段：双轨实验
@pytest.mark.phase3   # 第三阶段：全面重构

# 功能标记
@pytest.mark.linting           # Linting Hook
@pytest.mark.code_apply        # code_apply 工具
@pytest.mark.architect_editor  # Architect/Editor 分离
@pytest.mark.checkpoint        # 检查点机制
@pytest.mark.micro_commit      # 微提交
@pytest.mark.tool              # 工具集
```
