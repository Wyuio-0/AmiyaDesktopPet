@echo off
REM 语音克隆一键训练入口（双击运行）
REM 把本文件与 train_clone.py 一起放在 D:\Dev\voiceclone 下。
REM 首次使用：确认下面 CONFIG 里的路径（音频目录 + 文本映射 JSON）。
chcp 65001 >nul
cd /d "%~dp0"
setlocal

set NAME=
set AUDIO_DIR=
set TEXTS=
set EPOCHS=20

REM ================== 修改这里 ==================
REM 角色 key（自定义，如 amiya2）
set NAME=mychar
REM 音频目录（放 .wav 训练文件）
set AUDIO_DIR=D:\voice
REM 文本映射 JSON：{文件名不含扩展名: 文本}
set TEXTS=D:\voice\texts.json
REM ==============================================

if not exist "%~dp0train_clone.py" (
    echo 错误：当前目录缺少 train_clone.py，请与本 bat 一起放在 voiceclone 目录。
    pause
    exit /b 1
)

echo.
echo 语音克隆训练开始：角色=%NAME%  音频=%AUDIO_DIR%  文本=%TEXTS%  轮数=%EPOCHS%
echo 预处理(1a/1b/1c) + S2 单进程训练，耗时约 10 分钟~1 小时，请勿关闭窗口。
echo.
".venv\Scripts\python.exe" "%~dp0train_clone.py" --name "%NAME%" --audio-dir "%AUDIO_DIR%" --texts "%TEXTS%" --epochs %EPOCHS%
echo.
if %ERRORLEVEL% NEQ 0 (
    echo 训练出错（退出码 %ERRORLEVEL%），请检查上方日志。
) else (
    echo 训练完成！检查点目录：%NAME%_model\logs_s2_v2
    echo 下一步：改 serve.py 该角色的 tuned_s2_dir 指向该目录。
)
echo.
pause
