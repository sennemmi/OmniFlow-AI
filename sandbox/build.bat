@echo off
REM 构建 OmniFlowAI Sandbox 镜像 (Windows)

echo ==========================================
echo Building OmniFlowAI Sandbox Image
echo ==========================================

set IMAGE_NAME=omniflowai/sandbox
set TAG=latest

echo Project root: %~dp0..
echo Building image: %IMAGE_NAME%:%TAG%

REM 构建镜像（从项目根目录）
cd /d "%~dp0.."
docker build -f sandbox/Dockerfile -t "%IMAGE_NAME%:%TAG%" .

if %ERRORLEVEL% neq 0 (
    echo Build failed!
    exit /b 1
)

echo.
echo ==========================================
echo Build completed!
echo Image: %IMAGE_NAME%:%TAG%
echo ==========================================
echo.
echo To test the image:
echo   docker run --rm -it %IMAGE_NAME%:%TAG% python -m pytest --version
