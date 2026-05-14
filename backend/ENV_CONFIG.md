# OmniFlowAI 环境变量配置指南

本文档详细说明 OmniFlowAI 后端服务的所有环境变量配置选项，帮助您正确配置开发、测试和生产环境。

---

## 快速开始

1. **复制模板文件**
   ```bash
   cp .env.template .env
   ```

2. **编辑配置文件**
   ```bash
   # 使用您喜欢的编辑器
   vim .env        # Linux/Mac
   notepad .env    # Windows
   ```

3. **填入必要的配置值**（至少配置 AI 模型和目标项目路径）

4. **启动服务**
   ```bash
   python main.py
   ```

---

## 配置分类

### 1. 应用基础配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `ENV` | string | `development` | 运行环境，可选值：`development` \| `production` \| `testing` |
| `DEBUG` | boolean | `true` | 调试模式开关，**生产环境必须设为 `false`** |
| `HOST` | string | `0.0.0.0` | 服务器监听地址，`0.0.0.0` 允许外部访问，`127.0.0.1` 仅本地访问 |
| `PORT` | integer | `8000` | 服务器监听端口 |

**示例配置：**
```ini
ENV=production
DEBUG=false
HOST=0.0.0.0
PORT=8000
```

---

### 2. CORS 跨域配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `CORS_ORIGINS` | json array | `["*"]` | 允许的跨域来源列表 |

**安全提示：**
- 开发环境可设置为 `["*"]` 允许所有来源
- 生产环境应设置为具体域名，如 `["https://yourdomain.com", "https://app.yourdomain.com"]`

**示例配置：**
```ini
# 开发环境
CORS_ORIGINS=["*"]

# 生产环境
CORS_ORIGINS=["https://omniflowai.com", "https://app.omniflowai.com"]
```

---

### 3. 数据库配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `DATABASE_URL` | string | `sqlite+aiosqlite:///./omniflowai.db` | 数据库连接 URL |

**支持的驱动：**
- SQLite (开发/测试): `sqlite+aiosqlite:///./omniflowai.db`
- PostgreSQL (生产): `postgresql+asyncpg://user:password@localhost/dbname`

**示例配置：**
```ini
# SQLite (默认，适合开发和测试)
DATABASE_URL=sqlite+aiosqlite:///./omniflowai.db

# PostgreSQL (生产环境推荐)
DATABASE_URL=postgresql+asyncpg://omniflow:password@localhost:5432/omniflowai
```

---

### 4. AI 模型提供商配置

#### 4.1 主配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `LLM_PROVIDER` | string | `deepseek` | LLM 提供商选择，可选值：`openai` \| `mimo` \| `deepseek` |
| `DEFAULT_MODEL` | string | `deepseek-chat` | 默认使用的模型名称 |

#### 4.2 OpenAI 配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `OPENAI_API_KEY` | string | - | OpenAI API 密钥 |
| `OPENAI_API_BASE` | string | `https://api.openai.com/v1` | API 基础地址 |

**获取 API Key:** https://platform.openai.com/api-keys

#### 4.3 MiMo (小米米墨) 配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `MIMO_API_KEY` | string | - | MiMo API 密钥 |
| `MIMO_API_BASE` | string | `https://api.xiaomimimo.com/v1` | API 基础地址 |
| `MIMO_DEFAULT_MODEL` | string | `mimo-v2.5-pro` | 默认模型 |

**获取 API Key:** https://platform.xiaomimimo.com

#### 4.4 DeepSeek 配置（推荐）

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `DEEPSEEK_API_KEY` | string | - | DeepSeek API 密钥 |
| `DEEPSEEK_API_BASE` | string | `https://api.deepseek.com/v1` | API 基础地址 |
| `DEEPSEEK_DEFAULT_MODEL` | string | `deepseek-chat` | 默认模型 |

**模型选择：**
- `deepseek-chat`: 普通对话模型（推荐，响应快，成本低）
- `deepseek-reasoner`: 推理模型（思考更深入，响应慢，成本高）

**⚠️ 注意：** `deepseek-reasoner` 会返回 `reasoning_content` 字段，需要特殊处理。

**获取 API Key:** https://platform.deepseek.com/api_keys

**示例配置：**
```ini
# 使用 DeepSeek（推荐）
LLM_PROVIDER=deepseek
DEFAULT_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-your-api-key-here

# 使用 OpenAI
LLM_PROVIDER=openai
DEFAULT_MODEL=gpt-4
OPENAI_API_KEY=sk-your-api-key-here

# 使用 MiMo
LLM_PROVIDER=mimo
DEFAULT_MODEL=mimo-v2.5-pro
MIMO_API_KEY=your-api-key-here
```

---

### 5. AI 目标项目配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `TARGET_PROJECT_PATH` | string | - | AI 操作的目标项目绝对路径 |

**重要说明：**
- 必须使用**绝对路径**，不能使用相对路径
- 这是 OmniFlowAI 将要分析、修改和执行代码的项目目录
- 确保 OmniFlowAI 对此目录有读写权限

**示例配置：**
```ini
# Linux/Mac
TARGET_PROJECT_PATH=/home/user/projects/my-project

# Windows
TARGET_PROJECT_PATH=C:/Users/user/projects/my-project
```

---

### 6. GitHub 集成配置（可选）

用于远程交付功能，支持自动创建 Pull Request。

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `GITHUB_TOKEN` | string | - | GitHub Personal Access Token |
| `GITHUB_OWNER` | string | - | 仓库所有者（用户名或组织名） |
| `GITHUB_REPO` | string | - | 仓库名称 |

**Token 权限要求：**
- `repo` - 完全控制私有仓库
- `workflow` - 更新 GitHub Actions 工作流

**获取 Token:** https://github.com/settings/tokens

**示例配置：**
```ini
GITHUB_TOKEN=ghp_your_token_here
GITHUB_OWNER=your-username
GITHUB_REPO=your-repository
```

---

### 7. 代码安全机制配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `READ_TOKEN_SECRET` | string | 自动生成 | 用于验证先读后写机制的密钥 |

**说明：**
- 如果不设置，系统会自动生成一个随机密钥（重启后失效）
- 生产环境建议设置固定值，避免重启后 Token 失效
- 建议长度不少于 32 个字符

**示例配置：**
```ini
READ_TOKEN_SECRET=your-secret-key-at-least-32-characters-long
```

---

### 8. 沙箱测试功能配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `SANDBOX_TEST_ENABLED` | boolean | `true` | 沙箱测试功能开关 |

**说明：**
- `true`: 启用沙箱测试（默认）
- `false`: 禁用沙箱测试

沙箱测试用于安全地执行生成的代码，验证其正确性。

---

### 9. Agent 执行超时配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `AGENT_TIMEOUT` | integer | `300` | Agent 执行总超时时间（秒） |
| `SANDBOX_EXEC_TIMEOUT` | integer | `120` | Sandbox 代码执行超时时间（秒） |
| `LITELLM_TIMEOUT` | integer | `120` | LiteLLM API 调用超时时间（秒） |

**调优建议：**
- 复杂任务可适当增加 `AGENT_TIMEOUT`
- 网络不稳定时可增加 `LITELLM_TIMEOUT`
- 沙箱执行大量测试时可增加 `SANDBOX_EXEC_TIMEOUT`

---

### 10. 模型参数配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `LITELLM_MAX_TOKENS` | integer | `65536` | 模型最大输出 Token 数 |
| `MAX_TOKENS` | integer | `65536` | 最大 Token 数（兼容配置） |
| `LLM_TEMPERATURE` | float | `0.0` | 模型温度参数 (0.0 - 2.0) |
| `LLM_TOP_P` | float | `0.95` | Top-P 采样参数 (0.0 - 1.0) |

**Temperature 设置建议：**

| 场景 | 推荐值 | 说明 |
|------|--------|------|
| 代码生成 | `0.0` | 确定性输出，防止随机性导致错误 |
| 通用问答 | `0.8` | 平衡创造性和准确性 |
| 数学推理 | `1.0` | 最大化创造性思维 |
| 文本创作 | `0.9` | 保持一定创造性 |

---

### 11. Agent 调试配置

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `AGENT_DEBUG_ENABLED` | boolean | `true` | 是否启用 Agent 调试输出 |
| `AGENT_DEBUG_OUTPUT_DIR` | string | `./agent_debug_output` | 调试输出目录 |

**说明：**
- 启用后会输出详细的 Agent 思考过程、工具调用记录等
- 便于排查问题和优化 Agent 行为
- 生产环境可设为 `false` 减少日志量

---

## 环境配置示例

### 开发环境

```ini
ENV=development
DEBUG=true
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=["*"]

LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-dev-key
TARGET_PROJECT_PATH=/home/user/dev-project

AGENT_DEBUG_ENABLED=true
```

### 生产环境

```ini
ENV=production
DEBUG=false
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=["https://yourdomain.com"]

DATABASE_URL=postgresql+asyncpg://user:pass@localhost/omniflowai

LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-prod-key
TARGET_PROJECT_PATH=/var/www/production-project

GITHUB_TOKEN=ghp_your-token
GITHUB_OWNER=your-org
GITHUB_REPO=production-repo

READ_TOKEN_SECRET=your-fixed-secret-key
AGENT_DEBUG_ENABLED=false
```

---

## 安全最佳实践

1. **永远不要提交 `.env` 文件到版本控制**
   - 已添加到 `.gitignore`
   - 使用 `.env.template` 作为示例

2. **保护 API 密钥**
   - 定期轮换 API 密钥
   - 使用环境变量而非硬编码
   - 生产环境使用密钥管理服务

3. **生产环境配置**
   - 设置 `DEBUG=false`
   - 配置具体的 `CORS_ORIGINS`
   - 设置固定的 `READ_TOKEN_SECRET`
   - 禁用 `AGENT_DEBUG_ENABLED`

4. **数据库安全**
   - 生产环境使用 PostgreSQL 而非 SQLite
   - 使用强密码和连接池
   - 定期备份数据库

---

## 故障排查

### 配置未生效

1. 检查 `.env` 文件是否存在
2. 检查变量名是否拼写正确
3. 重启服务以加载新配置

### API 调用失败

1. 检查 API Key 是否正确
2. 检查网络连接
3. 查看 `LITELLM_TIMEOUT` 是否设置过短
4. 检查 API 提供商状态页面

### 数据库连接失败

1. 检查 `DATABASE_URL` 格式
2. 确认数据库服务已启动
3. 检查网络连接和防火墙设置

---

## 相关文档

- [OmniFlowAI 主文档](../README.md)
- [API 文档](http://localhost:8000/docs)（服务启动后访问）
- [部署指南](../deploy.md)
