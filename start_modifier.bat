@echo off
chcp 65001 >nul
cd /d "%~dp0"

py -3.11 modifier.py
if errorlevel 1 (
  echo.
  echo [错误] 启动失败。若提示缺少依赖，请先双击「安装依赖.bat」。
  pause
)
