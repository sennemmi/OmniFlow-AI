#!/bin/bash
# 构建 OmniFlowAI Sandbox 镜像

set -e

echo "=========================================="
echo "Building OmniFlowAI Sandbox Image"
echo "=========================================="

# 镜像名称和标签
IMAGE_NAME="omniflowai/sandbox"
TAG="latest"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Project root: $PROJECT_ROOT"
echo "Building image: $IMAGE_NAME:$TAG"

# 构建镜像（从项目根目录，以便复制 requirements.txt）
cd "$PROJECT_ROOT"
docker build -f sandbox/Dockerfile -t "$IMAGE_NAME:$TAG" .

echo ""
echo "=========================================="
echo "Build completed!"
echo "Image: $IMAGE_NAME:$TAG"
echo "=========================================="
echo ""
echo "To test the image:"
echo "  docker run --rm -it $IMAGE_NAME:$TAG python -m pytest --version"
