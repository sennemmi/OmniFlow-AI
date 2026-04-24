# OmniFlowAI API 文档

> **版本**: v0.1.0  
> **文档原则**: 以跳过验证为耻，文档必须准确反映现有的 Pydantic 模型

---

## 目录

1. [统一响应格式](#统一响应格式)
2. [Pipeline 生命周期状态机](#pipeline-生命周期状态机)
3. [API 端点](#api-端点)
   - [创建 Pipeline](#post-apiv1pipelinecreate)
   - [查询 Pipeline 状态](#get-apiv1pipelineidstatus)
   - [列出所有 Pipelines](#get-apiv1pipelines)
   - [审批 Pipeline](#post-apiv1pipelineidapprove)
   - [驳回 Pipeline](#post-apiv1pipelineidreject)

---

## 统一响应格式

所有 API 统一返回以下格式：

```json
{
  "success": true | false,
  "data": <any> | null,
  "error": <string> | null,
  "request_id": <uuid-string>
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 请求是否成功 |
| `data` | any | 响应数据，失败时为 null |
| `error` | string | 错误信息，成功时为 null |
| `request_id` | string | 请求唯一标识（UUID） |

### 响应示例

**成功响应**:
```json
{
  "success": true,
  "data": {
    "pipeline_id": 1,
    "status": "running",
    "current_stage": "REQUIREMENT",
    "created_at": "2024-01-15T10:30:00"
  },
  "error": null,
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**错误响应**:
```json
{
  "success": false,
  "data": null,
  "error": "Pipeline 123 not found",
  "request_id": "550e8400-e29b-41d4-a716-446655440001"
}
```

---

## Pipeline 生命周期状态机

```
┌─────────────┐
│   CREATED   │  (Pipeline 创建完成)
└──────┬──────┘
       │
       ▼
┌─────────────┐     ArchitectAgent 分析
│ REQUIREMENT │ ──────────────────────────►
│  (running)  │
└──────┬──────┘
       │
       │ 分析完成
       ▼
┌─────────────┐
│   PAUSED    │  (等待人工审批)
└──────┬──────┘
       │
       ├──────────────┐
       │              │
       ▼              ▼
  ┌─────────┐   ┌──────────┐
  │ APPROVE │   │  REJECT  │
  └────┬────┘   └────┬─────┘
       │             │
       ▼             ▼
┌─────────────┐  ┌─────────────┐
│    DESIGN   │  │ REQUIREMENT │ (重新分析)
│  (running)  │  │  (re-run)   │
└──────┬──────┘  └─────────────┘
       │
       │ DesignAgent 设计完成
       ▼
┌─────────────┐
│   PAUSED    │  (等待人工审批)
└──────┬──────┘
       │
       ├──────────────┐
       │              │
       ▼              ▼
  ┌─────────┐   ┌──────────┐
  │ APPROVE │   │  REJECT  │
  └────┬────┘   └────┬─────┘
       │             │
       ▼             ▼
┌─────────────┐  ┌─────────────┐
│    CODING   │  │    DESIGN   │ (重新设计)
│  (running)  │  │  (re-run)   │
└──────┬──────┘  └─────────────┘
       │
       │ CodingAgent 编码完成
       ▼
┌─────────────┐
│   SUCCESS   │  (Pipeline 完成)
└─────────────┘
```

### 状态说明

| 状态 | 说明 |
|------|------|
| `running` | Pipeline/Stage 正在执行 |
| `paused` | 等待人工审批 |
| `success` | 执行成功完成 |
| `failed` | 执行失败 |

### 阶段说明

| 阶段 | Agent | 职责 |
|------|-------|------|
| `REQUIREMENT` | ArchitectAgent | 分析需求，输出功能描述和受影响文件 |
| `DESIGN` | DesignerAgent | 技术设计，输出具体实现方案 |
| `CODING` | CoderAgent | 代码实现 |

---

## API 端点

### POST /api/v1/pipeline/create

创建新的 Pipeline，触发 ArchitectAgent 分析需求。

#### 请求

**Content-Type**: `application/json`

**请求体**:
```json
{
  "requirement": "string (required) - 用户需求描述"
}
```

**Pydantic 模型**: `PipelineCreateRequest`

```python
class PipelineCreateRequest(BaseModel):
    requirement: str
```

#### 响应

**成功 (200)**:
```json
{
  "success": true,
  "data": {
    "pipeline_id": 1,
    "status": "running",
    "current_stage": "REQUIREMENT",
    "created_at": "2024-01-15T10:30:00"
  },
  "error": null,
  "request_id": "uuid"
}
```

**失败 (500)**:
```json
{
  "success": false,
  "data": null,
  "error": "Failed to create pipeline: ...",
  "request_id": "uuid"
}
```

---

### GET /api/v1/pipeline/{id}/status

查询指定 Pipeline 的详细状态，包括所有阶段信息。

#### 请求

**路径参数**:
- `id` (integer, required) - Pipeline ID

#### 响应

**成功 (200)**:
```json
{
  "success": true,
  "data": {
    "id": 1,
    "description": "实现用户登录功能",
    "status": "paused",
    "current_stage": "REQUIREMENT",
    "created_at": "2024-01-15T10:30:00",
    "updated_at": "2024-01-15T10:31:00",
    "stages": [
      {
        "id": 1,
        "name": "REQUIREMENT",
        "status": "success",
        "input_data": {
          "requirement": "实现用户登录功能"
        },
        "output_data": {
          "feature_description": "基于需求的功能实现...",
          "affected_files": [
            "backend/app/api/v1/auth.py",
            "backend/app/service/auth.py"
          ],
          "estimated_effort": "4小时",
          "technical_design": "..."
        },
        "created_at": "2024-01-15T10:30:00",
        "completed_at": "2024-01-15T10:31:00"
      }
    ]
  },
  "error": null,
  "request_id": "uuid"
}
```

**未找到 (200)**:
```json
{
  "success": false,
  "data": null,
  "error": "Pipeline 123 not found",
  "request_id": "uuid"
}
```

---

### GET /api/v1/pipelines

列出所有 Pipeline（不包含详细阶段信息）。

#### 请求

**查询参数**:
- `skip` (integer, optional) - 跳过数量，默认 0
- `limit` (integer, optional) - 返回数量限制，默认 100

#### 响应

**成功 (200)**:
```json
{
  "success": true,
  "data": {
    "total": 2,
    "pipelines": [
      {
        "id": 1,
        "description": "实现用户登录功能",
        "status": "paused",
        "current_stage": "REQUIREMENT",
        "created_at": "2024-01-15T10:30:00"
      },
      {
        "id": 2,
        "description": "添加数据导出功能...",
        "status": "running",
        "current_stage": "DESIGN",
        "created_at": "2024-01-15T09:00:00"
      }
    ]
  },
  "error": null,
  "request_id": "uuid"
}
```

---

### POST /api/v1/pipeline/{id}/approve

审批 Pipeline，允许进入下一阶段。

#### 请求

**路径参数**:
- `id` (integer, required) - Pipeline ID

**Content-Type**: `application/json`

**请求体**:
```json
{
  "notes": "string (optional) - 审批备注",
  "feedback": "string (optional) - 反馈建议"
}
```

**Pydantic 模型**: `PipelineApproveRequest`

```python
class PipelineApproveRequest(BaseModel):
    notes: Optional[str] = None
    feedback: Optional[str] = None
```

#### 响应

**成功 (200)**:
```json
{
  "success": true,
  "data": {
    "pipeline_id": 1,
    "previous_stage": "REQUIREMENT",
    "next_stage": "DESIGN",
    "status": "running",
    "message": "Pipeline approved, proceeding to DESIGN stage"
  },
  "error": null,
  "request_id": "uuid"
}
```

**状态错误 (200)**:
```json
{
  "success": false,
  "data": null,
  "error": "Pipeline is not in PAUSED state, cannot approve",
  "request_id": "uuid"
}
```

---

### POST /api/v1/pipeline/{id}/reject

驳回 Pipeline，退回当前阶段重新执行。

#### 请求

**路径参数**:
- `id` (integer, required) - Pipeline ID

**Content-Type**: `application/json`

**请求体**:
```json
{
  "reason": "string (required) - 驳回原因",
  "suggested_changes": "string (optional) - 建议修改"
}
```

**Pydantic 模型**: `PipelineRejectRequest`

```python
class PipelineRejectRequest(BaseModel):
    reason: str
    suggested_changes: Optional[str] = None
```

#### 响应

**成功 (200)**:
```json
{
  "success": true,
  "data": {
    "pipeline_id": 1,
    "current_stage": "REQUIREMENT",
    "status": "running",
    "message": "Pipeline rejected, re-running REQUIREMENT stage with feedback",
    "feedback": {
      "reason": "需求不清晰",
      "suggested_changes": "请补充用户角色权限说明"
    }
  },
  "error": null,
  "request_id": "uuid"
}
```

**状态错误 (200)**:
```json
{
  "success": false,
  "data": null,
  "error": "Pipeline is not in PAUSED state, cannot reject",
  "request_id": "uuid"
}
```

---

## 数据模型

### PipelineStatus (枚举)

```python
class PipelineStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"
```

### StageName (枚举)

```python
class StageName(str, Enum):
    REQUIREMENT = "REQUIREMENT"
    DESIGN = "DESIGN"
    CODING = "CODING"
```

### StageStatus (枚举)

```python
class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
```

### Pipeline (数据库模型)

```python
class Pipeline(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    description: str                    # 原始需求描述
    status: PipelineStatus              # Pipeline 整体状态
    current_stage: Optional[StageName]  # 当前执行阶段
    created_at: datetime
    updated_at: datetime
```

### PipelineStage (数据库模型)

```python
class PipelineStage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pipeline_id: int                    # 关联 Pipeline ID
    name: StageName                     # 阶段名称
    status: StageStatus                 # 阶段状态
    input_data: Optional[Dict[str, Any]]   # 输入数据 (JSON)
    output_data: Optional[Dict[str, Any]]  # 输出数据 (JSON)
    created_at: datetime
    completed_at: Optional[datetime]
```

---

## 错误码

| HTTP 状态码 | 说明 |
|-------------|------|
| 200 | 请求成功（业务错误在响应体的 `error` 字段中） |
| 422 | 请求参数验证失败（Pydantic Validation Error） |
| 500 | 服务器内部错误 |

---

## 设计原则

1. **以跳过验证为耻**: 所有 API 请求体都使用 Pydantic 模型严格验证
2. **以接口抽象为荣**: 统一响应格式，所有端点遵循相同的响应结构
3. **以认真查询为荣**: Pipeline 状态查询返回完整的阶段历史和 Agent 输出
4. **以详实文档为荣**: API 文档与代码实现保持同步

---

*文档版本: 2024-01-15*  
*维护者: OmniFlowAI Team*
