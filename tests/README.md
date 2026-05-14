# OmniFlowAI 测试套件

本目录包含 OmniFlow Engine 的完整测试用例，覆盖功能测试、安全防御测试、性能测试和端到端测试。

## 测试架构

```
tests/
├── __init__.py
├── conftest.py                 # Pytest 配置和共享 fixtures
├── pytest.ini                 # Pytest 配置文件
├── README.md                  # 本文件
├── functional/                # 功能测试
│   ├── test_pipeline_workflow.py      # FT-P: Pipeline 引擎与状态机
│   ├── test_agent_orchestration.py    # FT-A: Agent 编排与契约对齐
│   └── test_visual_workspace.py       # FT-V: 可视化工作区与 Injector
├── defense/                   # 安全与防御性测试
│   └── test_defense_system.py         # SEC-L1~L4: 4层免疫系统
├── performance/               # 性能与可靠性测试
│   └── test_performance_resilience.py # PT: 弹性、上下文、预热、并发
└── e2e/                       # 端到端测试
    └── test_full_workflow.py          # E2E: 全链路测试
```

## 测试用例清单

### 1. 功能测试 (Functional Testing)

#### FT-P: Pipeline 引擎与状态机
| 用例编号 | 测试场景 | 预期结果 |
|---------|---------|---------|
| FT-P-01 | 完整链路测试 | 状态机按序流转，数据正确传递 |
| FT-P-02 | 人工审批 (Approve) | 状态从 PAUSED 变为 RUNNING，触发异步任务 |
| FT-P-03 | 人工驳回 (Reject) | 状态回退，Prompt 注入 rejection_feedback |
| FT-P-04 | 任务终止 (Terminate) | 状态变为 FAILED，清理 Sandbox 和日志 |

#### FT-A: Agent 编排与契约对齐
| 用例编号 | 测试场景 | 预期结果 |
|---------|---------|---------|
| FT-A-01 | Architect 探索 | 正确读取项目结构，输出 affected_files |
| FT-A-02 | 契约对齐校验 | 触发 ContractAlignmentError，启动重试 |
| FT-A-03 | 代码生成 (Coder) | 拦截缺失字段，触发针对性重试 |
| FT-A-04 | 独立测试 (Tester) | 拦截契约外 Import，防止幻觉 |

#### FT-V: 可视化工作区与 Injector
| 用例编号 | 测试场景 | 预期结果 |
|---------|---------|---------|
| FT-V-01 | DOM 圈选 | 捕获 outerHTML、XPath、React Fiber 位置 |
| FT-V-02 | AST 搜索替换 | 4级退避匹配（精确→归一→缩进→行号） |
| FT-V-03 | 热更新与撤销 | Vite HMR 生效，取消恢复原始内容 |
| FT-V-04 | 自动 MR 生成 | 切分支、提交、LLM 生成 PR 描述 |

### 2. 安全与防御性测试 (Defense System)

#### SEC-L1: 沙箱隔离与文件安全
| 用例编号 | 测试场景 | 预期结果 |
|---------|---------|---------|
| SEC-L1-01 | 目录穿越攻击 | PathSecurityError 拦截 |
| SEC-L1-02 | 文件回滚 | 100% 完美恢复原始代码 |

#### SEC-L2: 回归保护
| 用例编号 | 测试场景 | 预期结果 |
|---------|---------|---------|
| SEC-L2-01 | 老测试失败 | regression_broken，request_user |

#### SEC-L3: 测试隔离
| 用例编号 | 测试场景 | 预期结果 |
|---------|---------|---------|
| SEC-L3-01 | 全局 Mock | 拦截危险 Mock，保护事件循环 |

#### SEC-L4: 事务完整性
| 用例编号 | 测试场景 | 预期结果 |
|---------|---------|---------|
| SEC-L4-01 | 数据库断开/崩溃 | SQLAlchemy 自动 rollback |

### 3. 性能与可靠性测试 (Performance & Resilience)

| 用例编号 | 测试维度 | 测试场景 | 预期结果/指标 |
|---------|---------|---------|--------------|
| PT-01 | 弹性与重试 | LLM API 返回 502/429 | 指数退避 + Jitter，自动重试 |
| PT-02 | 上下文管控 | 超大项目超 Token 限制 | 按比例截断（核心30%全量） |
| PT-03 | 容器预热 | Pipeline 启动延迟 | 预热池命中 < 1秒 |
| PT-04 | 并发写入 | 多线程同时修改 | 文件锁确保原子写入 |

### 4. 端到端测试 (E2E)

使用 Playwright 测试完整用户流程：

#### 演示环节一：Pipeline 流程
1. 控制台输入需求，展示状态流转
2. Design 阶段点击 Reject，展示打回重做

#### 演示环节二：Injector 流程
1. 打开前端页面，点击悬浮球
2. 圈选 Button 元素
3. 输入"将按钮改为红色并加粗"
4. 验证 HMR 即时生效
5. 展示 Diff 对比和 MR 链接

## 执行测试

### 安装依赖

```bash
# 后端测试依赖
pip install pytest pytest-asyncio pytest-playwright

# 前端测试依赖
cd frontend
npm install -D vitest @playwright/test
```

### 运行测试

```bash
# 1. 极速防御检查 (< 5s)
pytest tests/defense/ -m defense -x

# 2. 功能测试
pytest tests/functional/ -m functional -v

# 3. 性能测试
pytest tests/performance/ -m performance -v

# 4. 端到端测试
pytest tests/e2e/ -m e2e --headed

# 5. 全部测试
pytest tests/ -v --tb=short
```

### 测试标记

- `functional`: 功能测试
- `pipeline`: Pipeline 引擎测试
- `agent`: Agent 编排测试
- `visual`: 可视化工作区测试
- `defense`: 防御性测试
- `security`: 安全测试
- `performance`: 性能测试
- `resilience`: 弹性测试
- `e2e`: 端到端测试
- `slow`: 慢速测试

## 预期测试结果

### 覆盖率指标
- 后端核心层代码覆盖率 > 85%
- AST 搜索替换引擎覆盖率 100%

### 防御拦截率
- 恶意路径注入：10/10 被拦截
- 破坏老测试行为：10/10 流转入人工审批

### 大模型容错率
- E2E 测试中 Pipeline 成功率 > 90%

### 耗时指标
- 需求到 PR 平均耗时（P90）<= 5 分钟
