@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python 启动器 py，请先安装 Python 3.11+
    pause
    exit /b 1
)

py -3.11 -c "import open3d" >nul 2>&1
if errorlevel 1 (
    echo 缺少依赖，请先双击「安装依赖.bat」
    pause
    exit /b 1
)

echo 启动 FDM灯箱生成器（源码版 / Python 3.11）
py -3.11 main.py
if errorlevel 1 (
    echo.
    echo [错误] 程序启动失败，请把上面的报错截图发给我
    pause
)
