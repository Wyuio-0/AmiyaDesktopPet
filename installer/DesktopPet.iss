; Amiya Desktop Pet — Inno Setup 安装包脚本
; CI 用 jrsoftware-org/iscc-action 构建：iscc installer/DesktopPet.iss /DAppVersion=<tag>
; 本地构建：安装 Inno Setup 6 后执行
;   iscc installer/DesktopPet.iss

#define MyAppName "Amiya Desktop Pet"
#ifndef MyAppVersion
  #define MyAppVersion "1.2.1"
#endif

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Wyuio-0
AppPublisherURL=https://github.com/Wyuio-0/AmiyaDesktopPet
DefaultDirName={localappdata}\Programs\AmiyaDesktopPet
DefaultGroupName={#MyAppName}
; 用户级安装，免管理员权限（UAC 弹窗）
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=DesktopPet-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
SetupIconFile=..\app.ico
UninstallDisplayIcon={app}\DesktopPet.exe
WizardStyle=modern

[Files]
; onedir 分发（exe + _internal 必须保持同目录结构）
; Excludes 双保险：ai_config.json（含 key）、.claude（本地工具状态）
Source: "..\dist\DesktopPet\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs; \
    Excludes: "ai_config.json,.claude"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\DesktopPet.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\DesktopPet.exe"

[Run]
Filename: "{app}\DesktopPet.exe"; Description: "立即运行 {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent
