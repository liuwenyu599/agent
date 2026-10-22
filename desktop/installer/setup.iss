; ===========================================================================
;  云法智办 · 桌面客户端 安装脚本 (Inno Setup 6)
; ---------------------------------------------------------------------------
;  为什么要自己写 .iss，而不是直接用 jpackage 生成的安装包：
;    jpackage / Compose Desktop 里 packageName 会同时决定
;      - exe 文件名
;      - 安装目录名
;      - 快捷方式名
;    三者无法拆开，而且非 ASCII 的 packageName 在部分 Windows 上会炸。
;    所以分工是：
;      - build.gradle.kts: packageName = "YunFaZhiBan"（纯 ASCII，只管 exe 名）
;      - 本脚本:           产品名 / 桌面快捷方式 / 开始菜单 = 中文「云法智办」
;
;  本脚本打包的是 Compose 生成的 app image 目录（自带 JRE，拷走即用）：
;    desktop\build\compose\binaries\main\app\YunFaZhiBan\
;      ├─ YunFaZhiBan.exe
;      └─ runtime\ (自带 JRE)
;
;  用法：
;    iscc setup.iss
;    iscc /DMySourceDir="D:\path\to\app\YunFaZhiBan" setup.iss
;    或双击同目录的 build-installer.ps1（推荐，会自动先跑 gradle）
;
;  ⚠ 本文件必须保存为 UTF-8「带 BOM」，否则中文会变乱码。
; ===========================================================================

#define MyAppName      "云法智办"
#define MyAppVersion   "1.1.4"   ; ⚠ 必须与 desktop/build.gradle.kts 的 packageVersion 保持一致

; 可由命令行覆盖：iscc /DMyAppExeName="Other.exe"
#ifndef MyAppExeName
  #define MyAppExeName "YunFaZhiBan.exe"
#endif

; 命名统一为「云法智办」：产品名 / 发布者 / 开始菜单组 / 快捷方式名 全部一致
#define MyAppPublisher "云法智办"
#define MyAppMenuGroup "云法智办"

#ifndef MySourceDir
  #define MySourceDir "..\build\compose\binaries\main\app\YunFaZhiBan"
#endif

[Setup]
; 注意：AppId 一旦发布就不要再改，否则会被当成另一个软件（旧版本残留）
AppId={{4C45073E-DC1F-4261-A8AD-BB3F20C1926C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppComments=云法智办 · 智慧办公平台桌面客户端
AppCopyright=Copyright (C) 2026 {#MyAppPublisher}

; 逐用户安装，装到 %LOCALAPPDATA%，不需要管理员权限
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppMenuGroup}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline

; Compose 桌面端是 x64
; 只声明 ArchitecturesAllowed 即可：Inno Setup 6.3+ 起在 ArchitecturesAllowed 仅含
; 64 位架构时会自动以 64 位模式安装，ArchitecturesInstallIn64BitMode 已废弃，
; Inno Setup 7 更是直接移除（写了会报 Unrecognized directive）。
ArchitecturesAllowed=x64

WizardStyle=modern
WizardResizable=no
; Unicode 指令自 Inno Setup 6 起恒为 yes（已无 ANSI 版），7 已移除该指令
Compression=lzma2/max
SolidCompression=yes
AllowNoIcons=yes
SetupIconFile=..\app_logo.ico
OutputDir=..\build\installer
OutputBaseFilename=云法智办-安装程序-{#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoTextVersion={#MyAppVersion}

; 想让安装向导界面也显示中文，把下面两行的注释去掉（需要 Inno Setup 6 完整版
; 自带 Languages\ChineseSimplified.isl；若文件不存在编译会报找不到）。
; [Languages]
; Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; app image 整个目录照搬（YunFaZhiBan.exe + app\ + runtime\）
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 桌面快捷方式：显示名是中文「云法智办」，指向的依然是英文的 YunFaZhiBan.exe
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
