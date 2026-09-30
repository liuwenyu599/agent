#Requires -Version 5.1
<#
  Build the Chinese-named installer for the desktop client.

  Steps:
    1. gradlew createDistributable
         -> app image at desktop\build\compose\binaries\main\app\YunFaZhiBan\
            (YunFaZhiBan.exe + runtime\ 自带 JRE，拷走即用)
    2. ISCC setup.iss
         -> 云法智办-安装程序-<ver>.exe  (中文名 + 中文桌面快捷方式)

  Requires: JDK 17 (build.gradle.kts uses jvmToolchain(17)), Inno Setup 6 (ISCC.exe).
  Note: build.gradle.kts 已不再声明 targetFormats，所以 jpackage 原生的 exe/msi 不再产出
        （也就不需要 WiX、不需要 jpackage 那套 Inno Setup）——安装包由本脚本的 setup.iss 独家负责。
        若哪天要恢复原生包，把 build.gradle.kts 里 targetFormats(...) 与文件头 import 加回来。

  NOTE: this file must stay UTF-8 **with BOM**, otherwise PowerShell 5.1 reads it as
        ANSI and the Chinese text below turns into mojibake.
#>
param(
    [switch]$SkipBuild,
    [string]$GradleTask = "createDistributable",
    [string]$AppExeName = "YunFaZhiBan.exe"
)

$ErrorActionPreference = "Stop"

$InstallerDir = $PSScriptRoot
$DesktopDir   = Split-Path -Parent $InstallerDir
$AppImageDir  = Join-Path $DesktopDir "build\compose\binaries\main\app\YunFaZhiBan"
$IssFile      = Join-Path $InstallerDir "setup.iss"
$OutDir       = Join-Path $DesktopDir "build\installer"

function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }

# --- 1. build the app image -------------------------------------------------
if (-not $SkipBuild) {
    Write-Host "[1/3] gradlew $GradleTask ..." -ForegroundColor Cyan
    $gradlew = Join-Path $DesktopDir "gradlew.bat"
    if (-not (Test-Path $gradlew)) { Fail "gradlew.bat not found at $gradlew" }
    Push-Location $DesktopDir
    try { & $gradlew $GradleTask } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) {
        Fail "gradle failed (exit $LASTEXITCODE). Most likely cause: JDK 17 missing (build.gradle.kts uses jvmToolchain(17))."
    }
}

$exe = Join-Path $AppImageDir $AppExeName
if (-not (Test-Path $exe)) {
    # 兜底：app image 目录名跟 packageName 强绑定，改名后这里自动找
    $appRoot = Join-Path $DesktopDir "build\compose\binaries\main\app"
    $found = Get-ChildItem $appRoot -Filter *.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        $AppImageDir = $found.DirectoryName
        $AppExeName  = $found.Name
        $exe         = $found.FullName
        Write-Host "  (auto-detected: $AppImageDir)" -ForegroundColor Yellow
    } else {
        Fail "app image exe not found under $appRoot (did gradlew $GradleTask finish?)"
    }
}
Write-Host "[2/3] app image OK: $AppImageDir" -ForegroundColor Cyan

# --- 2. locate ISCC ---------------------------------------------------------
$isccCmd = Get-Command iscc -ErrorAction SilentlyContinue
if ($isccCmd) {
    $iscc = $isccCmd.Source
} else {
    # 任意版本 / 任意位数：Inno Setup 6 是 32 位（装在 Program Files (x86)），
    # Inno Setup 7 有 64 位版（装在 Program Files）。两者都能编译同一份 setup.iss。
    $roots = @("C:\Program Files", "C:\Program Files (x86)", "$env:LOCALAPPDATA\Programs")
    $iscc = $null
    foreach ($r in $roots) {
        $hit = Get-ChildItem -Path $r -Filter "Inno Setup*" -Directory -ErrorAction SilentlyContinue |
               ForEach-Object { Join-Path $_.FullName "ISCC.exe" } |
               Where-Object { Test-Path $_ } |
               Sort-Object -Descending |
               Select-Object -First 1
        if ($hit) { $iscc = $hit; break }
    }
    if (-not $iscc) {
        Fail "ISCC.exe not found. Install Inno Setup: winget install --id JRSoftware.InnoSetup.7 --exact  (or JRSoftware.InnoSetup for v6)"
    }
}
Write-Host "[3/3] ISCC: $iscc" -ForegroundColor Cyan

# --- 3. compile -------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
& $iscc "/DMySourceDir=$AppImageDir" "/DMyAppExeName=$AppExeName" "/O$OutDir" $IssFile
if ($LASTEXITCODE -ne 0) { Fail "ISCC failed (exit $LASTEXITCODE)" }

Write-Host ""
Write-Host "Output:" -ForegroundColor Green
Get-ChildItem $OutDir -Filter *.exe |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 |
    ForEach-Object { "{0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB) }
