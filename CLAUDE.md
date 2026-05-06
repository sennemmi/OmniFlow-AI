# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Commands

```bash
# Backend
cd backend && python run_server.py                                    # Start backend (port 8000)
cd backend && python -m pytest tests -m unit -v                       # Unit tests (<10s)
cd backend && python -m pytest tests -m "unit or integration" -v      # Unit + integration (<60s)
cd backend && python -m pytest tests/unit/defense -v                  # Defense tests ("immune system")
cd backend && python -m pytest $(FILE) -v -s                          # Single test file

# Frontend
cd frontend && npm run dev               # Vite dev server (port 5173, proxies /api → 8000)
cd frontend && npm run test              # Vitest unit tests
cd frontend && npm run build             # Production build
cd frontend && npm run lint              # ESLint

# Root-level Makefile shortcuts
make test-be-unit    # Backend unit tests
make test-be-ci      # Backend unit + integration
make test-fe-unit    # Frontend unit tests
make test-smoke      # Fast smoke test
make test-e2e        # Playwright E2E (requires backend + frontend running)
make test-all        # test-be-ci + test-fe-unit
```

## Architecture Overview

OmniFlowAI is an AI-driven full-cycle R&D engine that orchestrates `requirement → design → coding → testing → review → delivery` as an automated Pipeline. It follows a **"Pipeline as skeleton, Agents as muscles, Human as reviewer"** architecture.

### Layer Stack (strict top-down dependency: `api/ → service/ → agents/`, no reverse calls)

```
frontend/src/            React 19 SPA (Vite + Tailwind + Zustand + React Flow + Monaco)
  ├── pages/             Landing, Console, PipelineDetail, Workspace, Analytics
  ├── components/        Pipeline visual nodes, approval drawer, SSE thought log
  ├── injector/          Standalone IIFE browser injection script (element selection + HMR preview)
  ├── hooks/             usePipelineFlow (React Flow graph builder), usePipelineNotification
  └── stores/            Zustand stores (pipelineStore, uiStore)

backend/app/
  ├── api/v1/            FastAPI routes (pipeline, system, workspace, code_modify)
  ├── service/           Business orchestration layer
  │   ├── pipeline.py    PipelineService — stage scheduling, approval flow, background tasks
  │   ├── workflow.py    WorkflowService — state persistence, stage transitions
  │   ├── stage_handlers/  Strategy pattern: RequirementHandler, DesignHandler, CodingHandler,
  │   │                     TestingHandler, CodeReviewHandler, DeliveryHandler
  │   ├── agent_coordinator_service.py  Builds unified context for each Agent
  │   ├── sandbox_orchestrator.py       Docker sandbox lifecycle (temp dir mount, file sync)
  │   ├── sandbox_file_service.py       Safe file I/O in sandbox (base64 transport, per-file locks)
  │   ├── layered_test_runner.py        5-layer fail-fast test strategy
  │   └── repair_service.py            Auto-fix loop orchestration (max 3 rounds)
  └── agents/            AI Agent implementations (only layer that calls LLM)
      ├── base.py        LangGraphAgent — 3-node state graph (process → validate → retry/end)
      ├── tool_agent.py  ToolUsingAgent — ReAct loop with tool-calling, token budget control
      ├── architect.py   Requirement analysis (read-only tools)
      ├── designer.py    Contract generation via Instructor structured output
      ├── coder.py       Code generation (search_block/replace_block)
      ├── tester.py      Test generation from contracts
      ├── code_reviewer.py  7-dimension code review
      ├── repairer_with_tools.py  Multi-round auto-repair with stall detection
      ├── reviewer.py    Pure-Python routing decisions (no LLM)
      ├── llm_providers.py  Strategy pattern: ModelScope / OpenAI / MiMo
      └── tools*.py      Agent tools: glob, grep_ast, read_chunk, code_apply, semantic_search

sandbox/                 Docker image: omniflowai/sandbox (python:3.11 + git + deps)
```

### Pipeline Lifecycle

Six stages in fixed order: `REQUIREMENT → DESIGN → CODING ∥ UNIT_TESTING → CODE_REVIEW → DELIVERY`

- **CODING and UNIT_TESTING run concurrently** via `asyncio.gather` — both consume the same `InterfaceSpec` contract
- **Three Human-in-the-Loop checkpoints**: REQUIREMENT, DESIGN, CODE_REVIEW. Each pauses Pipeline (status=PAUSED) and waits for Approve/Reject. Reject carries feedback back to the Agent for redo.
- **CODE_REVIEW** uses a 4-way approval matrix: approve/reject coding and testing independently
- **Auto-repair loop**: LayeredTestRunner detects failures → ReviewAgent routes (code_bug → auto-fix, defense_broken → force human) → RepairerAgentWithTools fixes in sandbox (max 3 rounds)

### Data Flow Between Stages

Each stage's `output_data` (Pydantic model) is persisted to `PipelineStage.output_data` (JSON column in SQLite). Downstream stages read it via `previous_output` through `StageContext`. Key contract: **DesignerAgent → InterfaceSpec list → shared by CoderAgent + TesterAgent** — this contract ensures code and tests are independently generated yet mutually compatible.

### Key Conventions (from CONVENTIONS.md)

- **API responses**: Always use `success_response(data, request_id)` / `error_response(error, request_id)`. Never manually build response dicts. Always include `request: Request` parameter in routes.
- **Imports**: Always use full `app.` prefix (`from app.core.database import get_session`), never relative.
- **Database**: Inject sessions via `Depends(get_session)`. Never use global variables or manual instantiation.
- **Logging**: Use `structlog`, never `print()`.
- **Protected modules**: `app/core/database.py` (get_session, engine, async_session_factory), `app/core/response.py` (success_response, error_response, ResponseModel), `app/core/config.py` (settings) — these APIs must not be removed or renamed.

### LLM Provider Configuration

Set via `backend/.env`: `LLM_PROVIDER=modelscope|openai|mimo` with corresponding `*_API_KEY`/`*_API_BASE` variables. Switch at runtime without code changes. ToolUsingAgent uses `litellm.acompletion` directly (needs `tools` parameter); standard agents use `LLMProvider.chat_completion()` through the strategy pattern factory.

### Sandbox Architecture

Docker containers provide isolated execution. On init: project code is copied to a temp dir (`shutil.copytree`, excludes `.git`/`node_modules`/`.venv`), then bind-mounted into the container. This prevents AI-generated code from damaging host files. Containers are resource-limited (1GB RAM, 2 CPUs). Each pipeline gets its own container, cleaned up on success/failure/terminate.

### Frontend Injector

The browser injection script (`frontend/src/injector/`) is a standalone IIFE built by a custom Vite plugin (`omniFlowOverlayPlugin`). It provides: floating icon → element selection (React Fiber source location) → AI code modification via `POST /api/v1/code/modify` → search/replace on frontend → write back triggering Vite HMR → preview banner (confirm/cancel/ESC) → auto MR creation. Uses native `fetch`, not React.
