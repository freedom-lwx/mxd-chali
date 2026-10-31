@echo off
rem 双击运行界面。游戏是管理员权限时必须让本工具也提权，否则 Windows 会拦掉按键。
setlocal
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo 正在申请管理员权限...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
) else (
    python "%~dp0app.py"
)
if errorlevel 1 pause
exit /b %errorlevel%
