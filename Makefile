# OmniFlowAI 项目 Makefile
# 统一前后端测试命令

.PHONY: test-be test-be-unit test-be-ci test-be-file test-fe test-fe-unit test-e2e test-all test-db test-agents

# ==================== 后端测试 ====================

# 后端单元测试（< 10s）
test-be-unit:
	cd backend && python -m pytest tests -m unit -v

# 后端单元 + 集成测试（< 60s）
test-be-ci:
	cd backend && python -m pytest tests -m "unit or integration" -v --tb=short

# 后端全量测试
test-be:
	cd backend && python -m pytest tests -v

# 后端测试单个文件（用法: make test-be-file FILE=tests/unit/test_pipeline_service.py）
test-be-file:
	cd backend && python -m pytest $(FILE) -v -s

# 数据库持久层测试
test-db:
	cd backend && python -m pytest tests/unit/test_models_persistence.py -v

# Agent 智力测试（使用录制好的响应）
test-agents:
	cd backend && python -m pytest tests/unit/test_agent_schema.py -v

# Agent 自我诊断测试
test-agents-healing:
	cd backend && python -m pytest tests/integration/test_agent_self_healing.py -v

# Agent 压力测试（真实调用 LLM）
test-llm-heavy:
	cd backend && python -m pytest tests/integration/test_llm_costs.py --vcr-record=all -v

# ==================== 前端测试 ====================

# 前端单元测试（< 30s）
test-fe-unit:
	cd frontend && npm run test

# 前端测试（带覆盖率）
test-fe:
	cd frontend && npm run test -- --coverage

# ==================== E2E 测试 ====================

# E2E 测试（需启动前后端）
test-e2e:
	npx playwright test

# E2E 测试（带 UI）
test-e2e-ui:
	npx playwright test --ui

# ==================== 全量测试 ====================

# 运行所有测试（后端 + 前端）
test-all: test-be-ci test-fe-unit
	@echo "所有测试通过！"

# CI 完整流程（GitHub Actions 使用）
test-ci: test-be-ci test-fe-unit

# 快速冒烟测试（最常用）
test-smoke:
	cd backend && python -m pytest tests/unit -m unit -x -q
