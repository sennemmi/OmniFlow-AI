#!/bin/bash

# OmniFlowAI 一键部署脚本 (Linux/Mac)
# 功能：构建 Sandbox Docker 镜像，启动前后端服务

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 获取项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

print_header() {
    echo ""
    echo "=========================================="
    echo "$1"
    echo "=========================================="
    echo ""
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[ℹ]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# 检查命令是否存在
check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

# 主程序
main() {
    print_header "OmniFlowAI 一键部署脚本"

    print_info "项目根目录: $PROJECT_ROOT"
    echo ""

    # 检查 Docker
    if ! check_command docker; then
        print_error "Docker 未安装或未添加到环境变量"
        echo "请先安装 Docker:"
        echo "  - Ubuntu: https://docs.docker.com/engine/install/ubuntu/"
        echo "  - Mac: https://docs.docker.com/desktop/install/mac-install/"
        exit 1
    fi
    print_success "Docker 已安装"

    # 检查 Docker 是否运行
    if ! docker info &> /dev/null; then
        print_error "Docker 服务未运行"
        echo "请启动 Docker 服务:"
        echo "  - Linux: sudo systemctl start docker"
        echo "  - Mac: 启动 Docker Desktop"
        exit 1
    fi
    print_success "Docker 服务运行中"

    # 检查 Python
    if ! check_command python3; then
        print_error "Python3 未安装"
        echo "请先安装 Python 3.11+: https://www.python.org/downloads/"
        exit 1
    fi
    print_success "Python3 已安装"

    # 检查 Node.js
    if ! check_command node; then
        print_error "Node.js 未安装"
        echo "请先安装 Node.js 18+: https://nodejs.org/"
        exit 1
    fi
    print_success "Node.js 已安装"

    # 检查 npm
    if ! check_command npm; then
        print_error "npm 未安装"
        exit 1
    fi
    print_success "npm 已安装"

    # 步骤 1: 构建 Sandbox Docker 镜像
    print_header "步骤 1: 构建 Sandbox Docker 镜像"

    cd "$PROJECT_ROOT"

    if [ ! -f "sandbox/Dockerfile" ]; then
        print_error "sandbox/Dockerfile 不存在"
        exit 1
    fi

    print_info "正在构建 Docker 镜像 omniflowai/sandbox:latest..."
    if docker build -f sandbox/Dockerfile -t "omniflowai/sandbox:latest" .; then
        print_success "Docker 镜像构建成功"
    else
        print_error "Docker 镜像构建失败"
        exit 1
    fi

    # 步骤 2: 启动后端服务
    print_header "步骤 2: 启动后端服务"

    BACKEND_DIR="$PROJECT_ROOT/backend"

    if [ ! -f "$BACKEND_DIR/main.py" ]; then
        print_error "后端 main.py 不存在: $BACKEND_DIR/main.py"
        exit 1
    fi

    cd "$BACKEND_DIR"

    # 检查虚拟环境
    if [ ! -d ".venv" ]; then
        print_info "创建 Python 虚拟环境..."
        if ! python3 -m venv .venv; then
            print_error "创建虚拟环境失败"
            exit 1
        fi
        print_success "虚拟环境创建成功"
    fi

    # 激活虚拟环境并安装依赖
    print_info "安装后端依赖..."
    source .venv/bin/activate

    if [ ! -f "requirements.txt" ]; then
        print_error "requirements.txt 不存在"
        exit 1
    fi

    if pip install -q -r requirements.txt; then
        print_success "后端依赖安装完成"
    else
        print_error "安装后端依赖失败"
        exit 1
    fi

    # 启动后端服务（后台运行）
    print_info "启动后端服务 (端口: 8000)..."

    # 检查是否有已存在的后端进程
    if pgrep -f "python main.py" > /dev/null; then
        print_warning "检测到已有后端进程在运行，尝试停止..."
        pkill -f "python main.py" || true
        sleep 2
    fi

    # 在后台启动后端
    nohup python main.py > backend.log 2>&1 &
    BACKEND_PID=$!

    # 等待后端启动
    print_info "等待后端服务启动..."
    for i in {1..30}; do
        if curl -s http://localhost:8000/health &> /dev/null || curl -s http://localhost:8000 &> /dev/null; then
            print_success "后端服务已启动 (PID: $BACKEND_PID)"
            break
        fi
        sleep 1
        if [ $i -eq 30 ]; then
            print_warning "后端服务启动可能较慢，请稍后检查日志: tail -f $BACKEND_DIR/backend.log"
        fi
    done

    # 步骤 3: 启动前端服务
    print_header "步骤 3: 启动前端服务"

    FRONTEND_DIR="$PROJECT_ROOT/frontend"

    if [ ! -f "$FRONTEND_DIR/package.json" ]; then
        print_error "前端 package.json 不存在: $FRONTEND_DIR/package.json"
        exit 1
    fi

    cd "$FRONTEND_DIR"

    # 检查 node_modules
    if [ ! -d "node_modules" ]; then
        print_info "安装前端依赖..."
        if npm install; then
            print_success "前端依赖安装完成"
        else
            print_error "安装前端依赖失败"
            exit 1
        fi
    else
        print_success "前端依赖已安装"
    fi

    # 检查是否有已存在的前端进程
    if pgrep -f "npm run dev" > /dev/null || pgrep -f "vite" > /dev/null; then
        print_warning "检测到已有前端进程在运行，尝试停止..."
        pkill -f "vite" || true
        sleep 2
    fi

    # 启动前端服务（后台运行）
    print_info "启动前端服务 (端口: 5173)..."
    nohup npm run dev > frontend.log 2>&1 &
    FRONTEND_PID=$!

    # 等待前端启动
    print_info "等待前端服务启动..."
    for i in {1..30}; do
        if curl -s http://localhost:5173 &> /dev/null; then
            print_success "前端服务已启动 (PID: $FRONTEND_PID)"
            break
        fi
        sleep 1
        if [ $i -eq 30 ]; then
            print_warning "前端服务启动可能较慢，请稍后检查日志: tail -f $FRONTEND_DIR/frontend.log"
        fi
    done

    # 部署完成
    print_header "部署完成！"

    echo "服务访问地址:"
    echo "  - 前端: http://localhost:5173"
    echo "  - 后端 API: http://localhost:8000"
    echo "  - API 文档: http://localhost:8000/docs"
    echo ""
    echo "进程信息:"
    echo "  - 后端 PID: $BACKEND_PID"
    echo "  - 前端 PID: $FRONTEND_PID"
    echo ""
    echo "日志文件:"
    echo "  - 后端日志: $BACKEND_DIR/backend.log"
    echo "  - 前端日志: $FRONTEND_DIR/frontend.log"
    echo ""
    echo "停止服务命令:"
    echo "  - 停止后端: kill $BACKEND_PID"
    echo "  - 停止前端: kill $FRONTEND_PID"
    echo ""
    print_success "OmniFlowAI 已成功部署！"
}

# 捕获中断信号
cleanup() {
    echo ""
    print_warning "部署脚本被中断"
    exit 1
}
trap cleanup INT TERM

# 执行主程序
main
