# 防御性测试（Defense Tests）

防御性测试是 OmniFlowAI 系统的"免疫系统"，用于防止 AI 写出灾难性代码。

## 四层防线

| 层级 | 名称 | 目的 | 关键测试 |
|------|------|------|----------|
| Layer 1 | 代码修改与沙箱防线 | 防止 AI 破坏物理文件 | 文件回滚、路径安全、导入清理、**并发安全** |
| Layer 2 | 测试运行器与决策防线 | 防止"旧测试"被 AI 篡改 | 语法拦截、防御性保护、回归保护、**测试隔离** |
| Layer 3 | 多 Agent 协作与状态机防线 | 防止系统死循环 | Pydantic 校验、重试限制、JSON 剥离、**Token限制** |
| Layer 4 | 工作流与状态持久化防线 | 确保界面显示正确 | 状态流转限制、反馈传递、**事务完整性** |

## 测试文件列表

### Layer 1 - 代码修改与沙箱防线
- `test_layer1_code_sandbox.py` - 基础文件操作安全
- `test_layer1_concurrent_file_safety.py` - **并发文件操作安全**

### Layer 2 - 测试运行器与决策防线
- `test_layer2_test_runner.py` - 测试运行器决策逻辑
- `test_layer2_test_isolation.py` - **测试隔离性**

### Layer 3 - 多 Agent 协作与状态机防线
- `test_layer3_multi_agent.py` - Agent 协作基础
- `test_layer3_token_limit.py` - **Token 消耗限制**

### Layer 4 - 工作流与状态持久化防线
- `test_layer4_workflow_state.py` - 工作流状态管理
- `test_layer4_transaction_integrity.py` - **数据库事务完整性**

## 运行命令

### 方法 1: 使用 Makefile（推荐）

```bash
# 运行所有防御性测试
make test-defense

# 详细模式（显示完整日志）
make test-defense-verbose
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

# 快速检查（只显示失败）
python -m pytest tests/unit/defense --tb=line
```

## 在代码提交前运行

建议在以下时机运行防御性测试：

1. **修改任何服务代码前** - 确保系统保护机制正常
2. **修改 `app/service/` 目录后** - 验证文件操作安全
3. **修改 `app/agents/` 目录后** - 验证 Agent 协作机制
4. **修改 `app/models/` 目录后** - 验证状态机正确性
5. **提交 PR 前** - 作为最终检查

## 测试失败处理

如果防御性测试失败：

1. **不要尝试自动修复** - 防御性测试失败意味着代码破坏了核心保护机制
2. **查看错误信息** - 运行 `make test-defense-verbose` 查看详细日志
3. **人工检查代码** - 重点检查是否修改了 `tests/unit/defense/` 下的测试文件
4. **回滚或重构** - 根据错误信息决定是回滚代码还是重构实现

## 为什么不能修改防御性测试？

防御性测试是系统的"免疫系统"，它们保护：

- **文件系统安全** - 防止 AI 写入错误路径或破坏文件
- **测试完整性** - 防止 AI 为通过测试而篡改测试本身
- **系统稳定性** - 防止无限循环和资源耗尽
- **状态一致性** - 防止 Pipeline 状态错乱

修改这些测试 = 拆除系统的安全护栏。
