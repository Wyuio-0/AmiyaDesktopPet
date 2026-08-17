# -*- coding: utf-8 -*-
# 桌面宠物 —— 一键构建脚本
#
# 作用：重新用 PyInstaller 打包 DesktopPet.exe，同步角色资源（阿米娅 / 圣聆初雪
#       等），并刷新桌面「桌面宠物」快捷方式。每次改完功能直接跑这个脚本即可。
#
# 用法：直接双击 build.bat，或在此目录执行  powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- 路径配置（脚本所在目录即项目根目录）------------------------------------
$Root      = $PSScriptRoot
$Spec      = Join-Path $Root 'DesktopPet.spec'
$DistDir   = Join-Path $Root 'dist'
$ExePath   = Join-Path $DistDir 'DesktopPet.exe'
$IconPath  = Join-Path $Root 'app.ico'
$CharSrc   = Join-Path $Root 'characters'
$CharDst   = Join-Path $DistDir 'characters'
$Desktop   = [Environment]::GetFolderPath('Desktop')
$Shortcut  = Join-Path $Desktop '桌面宠物.lnk'

Set-Location $Root
Write-Host '==> 桌面宠物构建开始' -ForegroundColor Cyan

# --- 0. 预检：关键文件是否齐全 ----------------------------------------------
if (-not (Test-Path $Spec))    { throw "缺少打包配置 $Spec。" }
if (-not (Test-Path $CharSrc)) { throw "缺少角色资源目录 $CharSrc。" }
if (-not (Test-Path $IconPath)) {
    Write-Warning "未找到图标 $IconPath，快捷方式将使用 exe 自带图标。"
}

# --- 1. 选择 Python 解释器 --------------------------------------------------
$Py = $null
foreach ($cand in @('python', 'py')) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) { $Py = $cand; break }
}
if (-not $Py) { throw '找不到 Python，请先安装并加入 PATH。' }
Write-Host "    使用解释器: $Py" -ForegroundColor DarkGray

# --- 2. 打包（PyInstaller 读取 DesktopPet.spec）-----------------------------
Write-Host '==> [1/4] 运行 PyInstaller 打包...' -ForegroundColor Yellow
& $Py -m PyInstaller --noconfirm --clean $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败（退出码 $LASTEXITCODE）。" }
if (-not (Test-Path $ExePath)) { throw "打包结束但未找到 $ExePath。" }

# --- 3. 同步角色资源到 dist\characters -------------------------------------
# main.py 在打包运行时优先读取 exe 旁边的 characters\，
# 所以每次构建都用源目录覆盖它，保证角色/配置是最新的。
# **排除敏感文件**：ai_config.json 可能含有 API key；.claude 是本地工具状态。
Write-Host '==> [2/4] 同步角色资源...' -ForegroundColor Yellow
if (Test-Path $CharDst) { Remove-Item $CharDst -Recurse -Force }
Copy-Item $CharSrc $CharDst -Recurse -Force
Get-ChildItem $CharDst -Recurse -Filter 'ai_config.json' -File |
    Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem $CharDst -Recurse -Directory -Filter '.claude' |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
$chars = Get-ChildItem $CharDst -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'config.json') } |
    Select-Object -ExpandProperty Name
Write-Host "    已同步: $CharDst" -ForegroundColor DarkGray
Write-Host ("    角色（{0}个）: {1}" -f $chars.Count, ($chars -join ', ')) -ForegroundColor DarkGray

# --- 4. 刷新桌面快捷方式 ----------------------------------------------------
Write-Host '==> [3/4] 刷新桌面快捷方式...' -ForegroundColor Yellow
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($Shortcut)
$lnk.TargetPath       = $ExePath
$lnk.Arguments        = ''
$lnk.WorkingDirectory = $DistDir
# 图标缺失时回退到 exe 自带图标，避免快捷方式显示空白图标。
$lnk.IconLocation     = if (Test-Path $IconPath) { "$IconPath,0" } else { "$ExePath,0" }
$lnk.Description       = '桌面宠物'
$lnk.Save()
Write-Host "    已更新: $Shortcut" -ForegroundColor DarkGray

Write-Host '==> [4/4] 完成 ✅  桌面宠物已更新，双击桌面快捷方式即可运行。' -ForegroundColor Green
