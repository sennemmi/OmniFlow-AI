@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo Building OmniFlowAI Sandbox Image
echo ==========================================

set "IMAGE_NAME=omniflowai/sandbox"
set "TAG=latest"

REM determine project root (parent of sandbox directory)
set "PROJECT_ROOT=%~dp0.."

echo Project root: "%PROJECT_ROOT%"
echo Target image: %IMAGE_NAME%:%TAG%

REM switch to project root
pushd "%PROJECT_ROOT%"
if %ERRORLEVEL% neq 0 (
    echo ERROR: Cannot switch to project root "%PROJECT_ROOT%"
    exit /b 1
)

REM ensure Dockerfile exists
if not exist "sandbox\Dockerfile" (
    echo ERROR: sandbox\Dockerfile not found in "%PROJECT_ROOT%"
    popd
    exit /b 1
)

echo Starting Docker build...
echo Command: docker build -f sandbox/Dockerfile -t "%IMAGE_NAME%:%TAG%" .

docker build -f sandbox/Dockerfile -t "%IMAGE_NAME%:%TAG%" .
if %ERRORLEVEL% neq 0 (
    echo.
    echo Build FAILED!
    popd
    exit /b 1
)

echo.
echo ==========================================
echo Build SUCCESSFUL!
echo Image: %IMAGE_NAME%:%TAG%
echo ==========================================
echo.
echo Test the image with:
echo   docker run --rm -it %IMAGE_NAME%:%TAG% python -m pytest --version

popd
exit /b 0