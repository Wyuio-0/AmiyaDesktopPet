@echo off
REM Amiya Desktop Pet - one-click build (double-click to run)
REM Calls build.ps1 in the same directory, bypassing execution policy.
REM (Keep this file ASCII-only: cmd parses batch files in the active
REM  code page, so non-ASCII comments can garble and break parsing.)
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
echo.
pause
