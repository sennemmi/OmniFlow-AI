# OmniFlowAI Sandbox 专用镜像
# 预装所有依赖，实现秒级启动

FROM python:3.11

WORKDIR /workspace

# 使用国内镜像源加速（清华）
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list && \
    sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list

# 安装系统依赖（最小化）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

# 复制精简 requirements（不含 torch 等重型依赖）
COPY sandbox/requirements-sandbox.txt /tmp/requirements.txt

# 使用清华镜像安装依赖
RUN pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# 验证核心依赖安装
RUN python -m pytest --version && \
    python -c "import fastapi, sqlmodel, langgraph, litellm; print('Core dependencies OK')"

# 创建数据库目录
RUN mkdir -p /workspace/backend/data

# 工作目录（main.py 在 backend/ 根目录）
WORKDIR /workspace/backend

# 默认命令：启动后端服务
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --reload"]
