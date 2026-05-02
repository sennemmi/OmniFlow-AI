# OmniFlowAI Backend Makefile
# 分层运行测试命令

.PHONY: test-defense test-unit test-ci test-all test-file test-defense-verbose test-defense-docker test-layer-order test-layer-order-docker test-e2e

# 【防御性测试】跑核心保护机制测试（最先跑，< 5s）
# 这些测试是系统的"免疫系统"，必须全部通过
test-defense:
	python -m pytest tests/unit/defense -v --tb=short

# 【防御性测试 - 详细模式】显示完整日志，用于调试
test-defense-verbose:
	python -m pytest tests/unit/defense -v --tb=long -s

# 【防御性测试 - Docker 沙箱】在 Docker 容器中运行测试
# 使用已构建的 omniflowai/sandbox 镜像
# 用法: make test-defense-docker [IMAGE=your-image-name]
test-defense-docker:
	python scripts/test_defense_in_docker.py $(if $(IMAGE),--image=$(IMAGE))

# 【分层顺序验证】验证分层测试执行顺序是否符合快速失败原则
test-layer-order:
	python scripts/test_layer_order.py

# 【分层顺序验证 - Docker】在 Docker sandbox 中运行分层顺序验证
test-layer-order-docker:
	python scripts/test_layer_order.py --docker

# 【端到端测试 - 使用真实 LLM（模拟版本）】
# ⚠️  警告: 此测试会消耗 LLM API Token！
# 自动读取 .env 文件中的配置 (MODELSCOPE_API_KEY 或 OPENAI_API_KEY)
# 用法: make test-e2e [MODEL=Qwen/Qwen3.5-122B-A10B]
test-e2e:
	python scripts/test_e2e_with_llm.py $(if $(MODEL),--model=$(MODEL))

# 【端到端测试 - 真正调用 LLM】
# ⚠️  警告: 此测试会真正调用 CoderAgent 和 TesterAgent 的 LLM！
# 用法: make test-e2e-real
test-e2e-real:
	python scripts/test_e2e_with_llm_real.py

# 只跑单元测试（< 10s，本地开发时用）
test-unit:
	python -m pytest tests -m unit -v

# 跑单元 + 集成（< 60s，提 PR 前用）
test-ci:
	python -m pytest tests -m "unit or integration" -v --tb=short

# 跑全量包括 E2E（慢，只在 main 分支合并后用）
test-all:
	python -m pytest tests -v

# 快速检查某个文件（用法: make test-file FILE=tests/unit/test_pipeline_service.py）
test-file:
	python -m pytest $(FILE) -v -s
