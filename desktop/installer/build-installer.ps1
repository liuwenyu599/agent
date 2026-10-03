#Requires -Version 5.1
<#
  Build the Chinese-named installer for the desktop client.

  Delivery invariant: the packaged app image and final installer must be newer than every
  desktop/src source file. -SkipBuild is allowed only when the existing app image is fresh.
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
$SourceDir    = Join-Path $DesktopDir "src"

function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }

function Get-NewestSourceTime {
    $src = Get-ChildItem $SourceDir -File -Recurse -ErrorAction Stop |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $src) { Fail "no source files found under $SourceDir" }
    return $src.LastWriteTime
}

$newestSourceTime = Get-NewestSourceTime

# --- 1. build the app image -------------------------------------------------
if (-not $SkipBuild) {
    Write-Host "[1/4] gradlew $GradleTask ..." -ForegroundColor Cyan
    $gradlew = Join-Path $DesktopDir "gradlew.bat"
    if (-not (Test-Path $gradlew)) { Fail "gradlew.bat not found at $gradlew" }
    Push-Location $DesktopDir
    try { & $gradlew $GradleTask } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) {
        Fail "gradle failed (exit $LASTEXITCODE). JDK 17 is required."
    }
} else {
    Write-Host "[1/4] SkipBuild requested; freshness will be verified." -ForegroundColor Yellow
}

$exe = Join-Path $AppImageDir $AppExeName
if (-not (Test-Path $exe)) {
    $appRoot = Join-Path $DesktopDir "build\compose\binaries\main\app"
    $found = Get-ChildItem $appRoot -Filter *.exe -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) {
        $AppImageDir = $found.DirectoryName
        $AppExeName  = $found.Name
        $exe         = $found.FullName
        Write-Host "  (auto-detected: $AppImageDir)" -ForegroundColor Yellow
    } else {
        Fail "app image exe not found under $appRoot (did gradlew $GradleTask finish?)"
    }
}

$appExeInfo = Get-Item $exe
if ($appExeInfo.LastWriteTime -lt $newestSourceTime) {
    Fail "app image is stale: $($appExeInfo.LastWriteTime) < newest source $newestSourceTime. Run without -SkipBuild."
}
Write-Host "[2/4] app image fresh: $AppImageDir" -ForegroundColor Cyan

# --- 2. locate ISCC ---------------------------------------------------------
$isccCmd = Get-Command iscc -ErrorAction SilentlyContinue
if ($isccCmd) {
    $iscc = $isccCmd.Source
} else {
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
        Fail "ISCC.exe not found. Install Inno Setup 6/7 first."
    }
}
Write-Host "[3/4] ISCC: $iscc" -ForegroundColor Cyan

# --- 3. compile -------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
& $iscc "/DMySourceDir=$AppImageDir" "/DMyAppExeName=$AppExeName" "/O$OutDir" $IssFile
if ($LASTEXITCODE -ne 0) { Fail "ISCC failed (exit $LASTEXITCODE)" }

$installer = Get-ChildItem $OutDir -Filter *.exe |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $installer) { Fail "installer output not found under $OutDir" }
if ($installer.LastWriteTime -lt $newestSourceTime) {
    Fail "installer is stale: $($installer.LastWriteTime) < newest source $newestSourceTime"
}

Write-Host "[4/4] freshness gate passed" -ForegroundColor Green
Write-Host ""
Write-Host "Output:" -ForegroundColor Green
"{0}  ({1:N1} MB)" -f $installer.FullName, ($installer.Length / 1MB)
