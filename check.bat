@echo off
rem 跑单元测试 + 导入检查：python scripts/check.py 的双击版
setlocal
cd /d "%~dp0"
python "%~dp0scripts\check.py"
pause
exit /b %errorlevel%
