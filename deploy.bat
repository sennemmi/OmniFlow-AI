@echo off
setlocal enabledelayedexpansion

chcp 65001 >nul

echo ==========================================
echo OmniFlowAI 一键部署脚本 (Windows)
echo ==========================================
echo.

REM 获取项目根目录
set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

echo 项目根目录: %PROJECT_ROOT%
echo.

REM 检查 Docker 是否安装
docker --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] Docker 未安装或未添加到环境变量
    echo 请先安装 Docker Desktop: https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)
echo [✓] Docker 已安装

REM 检查 Python 是否安装
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] Python 未安装或未添加到环境变量
    echo 请先安装 Python 3.11+: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [✓] Python 已安装

REM 检查 Node.js 是否安装
node --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] Node.js 未安装或未添加到环境变量
    echo 请先安装 Node.js 18+: https://nodejs.org/
    pause
    exit /b 1
)
echo [✓] Node.js 已安装

echo.
echo ==========================================
echo 步骤 1: 构建 Sandbox Docker 镜像
echo ==========================================
echo.

cd /d "%PROJECT_ROOT%"

REM 检查 Dockerfile 是否存在
if not exist "sandbox\Dockerfile" (
    echo [错误] sandbox\Dockerfile 不存在
    pause
    exit /b 1
)

echo 正在构建 Docker 镜像 omniflowai/sandbox:latest...
docker build -f sandbox/Dockerfile -t "omniflowai/sandbox:latest" .

if %ERRORLEVEL% neq 0 (
    echo [错误] Docker 镜像构建失败
    pause
    exit /b 1
)

echo [✓] Docker 镜像构建成功

echo.
echo ==========================================
echo 步骤 2: 启动后端服务
echo ==========================================
echo.

set "BACKEND_DIR=%PROJECT_ROOT%\backend"

if not exist "%BACKEND_DIR%\main.py" (
    echo [错误] 后端 main.py 不存在: %BACKEND_DIR%\main.py
    pause
    exit /b 1
)

cd /d "%BACKEND_DIR%"

REM 检查虚拟环境
if not exist ".venv" (
    echo 创建 Python 虚拟环境...
    python -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
)

REM 激活虚拟环境并安装依赖
echo 安装后端依赖...
call .venv\Scripts\activate.bat

if not exist "requirements.txt" (
    echo [错误] requirements.txt 不存在
    pause
    exit /b 1
)

pip install -q -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [错误] 安装后端依赖失败
    pause
    exit /b 1
)

echo [✓] 后端依赖安装完成

REM 启动后端服务（在新窗口中）
echo 启动后端服务 (端口: 8000)...
start "OmniFlowAI Backend" cmd /k "cd /d %BACKEND_DIR% && call .venv\Scripts\activate.bat && python main.py"

echo [✓] 后端服务已启动

echo.
echo ==========================================
echo 步骤 3: 启动前端服务
echo ==========================================
echo.

set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"

if not exist "%FRONTEND_DIR%\package.json" (
    echo [错误] 前端 package.json 不存在: %FRONTEND_DIR%\package.json
    pause
    exit /b 1
)

cd /d "%FRONTEND_DIR%"

REM 检查 node_modules
if not exist "node_modules" (
    echo 安装前端依赖...
    call npm install
    if %ERRORLEVEL% neq 0 (
        echo [错误] 安装前端依赖失败
        pause
        exit /b 1
    )
) else (
    echo [✓] 前端依赖已安装
)

REM 启动前端服务（在新窗口中）
echo 启动前端服务 (端口: 5173)...
start "OmniFlowAI Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo [✓] 前端服务已启动

echo.
echo ==========================================
echo 部署完成！
echo ==========================================
echo.
echo 服务访问地址:
echo   - 前端: http://localhost:5173
echo   - 后端 API: http://localhost:8000
echo   - API 文档: http://localhost:8000/docs
echo.
echo 按任意键关闭此窗口（服务将继续在后台运行）
pause >nul

endlocal
