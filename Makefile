# OmniFlowAI Makefile
# 一键启动和管理命令

.PHONY: help install backend test lint format clean

# 默认目标
help:
	@echo "OmniFlowAI 项目管理命令"
	@echo ""
	@echo "可用命令:"
	@echo "  make install    - 安装后端依赖"
	@echo "  make backend    - 启动后端开发服务器"
	@echo "  make test       - 运行测试"
	@echo "  make lint       - 代码检查"
	@echo "  make format     - 代码格式化"
	@echo "  make clean      - 清理缓存文件"

# 安装依赖
install:
	@echo "📦 安装后端依赖..."
	cd backend && pip install -r requirements.txt

# 启动后端
backend:
	@echo "🚀 启动后端服务..."
	cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 运行测试
test:
	@echo "🧪 运行测试..."
	cd backend && pytest -v

# 代码检查
lint:
	@echo "🔍 代码检查..."
	cd backend && ruff check .

# 代码格式化
format:
	@echo "✨ 代码格式化..."
	cd backend && ruff format .

# 清理缓存
clean:
	@echo "🧹 清理缓存文件..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
