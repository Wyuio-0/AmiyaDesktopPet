@echo off
REM 阿米娅桌面宠物 —— 一键构建（双击运行）
REM 调用同目录下的 build.ps1，绕过执行策略限制。
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
echo.
pause
