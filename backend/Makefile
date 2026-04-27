# OmniFlowAI Backend Makefile
# 分层运行测试命令

.PHONY: test-unit test-ci test-all test-file

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
