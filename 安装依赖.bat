@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python 启动器 py，请先安装 Python 3.11+
    pause
    exit /b 1
)

py -3.11 -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python 3.11，请安装后再试
    pause
    exit /b 1
)

echo 正在用 Python 3.11 安装依赖...
py -3.11 -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

echo.
echo 依赖安装完成。可双击「运行.bat」或「启动.vbs」启动。
pause
