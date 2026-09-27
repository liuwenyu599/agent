# ============================================================
#  Judicial AI - Start backend server (Windows / PowerShell)
#  Called by start-backend.bat
#
#  Runs in SUPERVISOR mode: keeps the backend alive.
#  Every 10s it probes http://127.0.0.1:8000/docs and restarts
#  uvicorn if it has died. Close this window to stop supervising.
# ============================================================

$ErrorActionPreference = "Continue"

$PROJECT_DIR = "D:\Projects\judicial_app"
$SERVER_DIR  = Join-Path $PROJECT_DIR "server"
$PYTHON_EXE  = "D:\apps\anaconda3\python.exe"
$LOG_DIR     = Join-Path $PROJECT_DIR "logs"
$PORT        = 8000
$HEALTH      = "http://127.0.0.1:$PORT/docs"
$PROBE_EVERY = 10

# NOTE: do NOT assign $env:PATH here (uppercase).
# In Windows PowerShell 5.1 that creates a duplicate "PATH" key alongside
# "Path", and Start-Process then dies with:
#   "An item with the same key has already been added."
# Processes launched from Explorer already inherit the user PATH, so we only
# verify the two preview tools are reachable and warn if they are not.

if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null }

function Write-Line($s) { Write-Output $s }
function Stamp { Get-Date -Format "HH:mm:ss" }

function Pause-Exit($code) {
    try { Read-Host "Press Enter to exit" | Out-Null } catch { }
    exit $code
}

# Invoke-WebRequest honours the system proxy, which makes 127.0.0.1 probes
# fail on machines with a proxy configured. Use WebClient with Proxy=$null.
function Test-BackendUp {
    param([string]$Url)
    try {
        $wc = New-Object System.Net.WebClient
        $wc.Proxy = $null
        $wc.Headers.Add("User-Agent", "judicial-startup-probe")
        $null = $wc.DownloadString($Url)
        $wc.Dispose()
        return $true
    } catch {
        return $false
    }
}

function Start-Backend {
    param([string]$Tag)

    $out = Join-Path $LOG_DIR "backend_$Tag.out.log"
    $err = Join-Path $LOG_DIR "backend_$Tag.err.log"
    $args = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$PORT")

    # attempt 1: Start-Process with redirected logs
    try {
        Start-Process -FilePath $PYTHON_EXE -ArgumentList $args `
            -WorkingDirectory $SERVER_DIR -WindowStyle Minimized `
            -RedirectStandardOutput $out -RedirectStandardError $err
        return $true
    } catch {
        Write-Line "  [warn] Start-Process failed: $($_.Exception.Message)"
    }

    # attempt 2: raw .NET Process via cmd.exe (bypasses PS env-dictionary quirks)
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "cmd.exe"
        $psi.Arguments = "/c $PYTHON_EXE $($args -join ' ') > $out 2>&1"
        $psi.WorkingDirectory = $SERVER_DIR
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $p = [System.Diagnostics.Process]::Start($psi)
        if ($p -and $p.Id -gt 0) { return $true }
    } catch {
        Write-Line "  [warn] .NET fallback failed: $($_.Exception.Message)"
    }
    return $false
}

Write-Line ""
Write-Line "============================================================"
Write-Line " Judicial AI Backend Supervisor"
Write-Line "============================================================"
Write-Line ""

# ------------------------------------------------------------
# 0. What address will the desktop client use?
# ------------------------------------------------------------
$cfgPath = Join-Path $env:APPDATA "JudicialAIDesktop\server.json"
Write-Line "[config] Desktop client server address:"
if (Test-Path $cfgPath) {
    try {
        $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Line "         $cfgPath"
        Write-Line "         baseUrl = $($cfg.baseUrl)"
        if ($cfg.baseUrl -notmatch "127\.0\.0\.1|localhost") {
            Write-Line ""
            Write-Line "         [WARN] not a loopback address. For a backend on THIS"
            Write-Line "         machine it must be http://127.0.0.1:$PORT - a LAN IP"
            Write-Line "         breaks every time Wi-Fi hands out a new address."
        }
    } catch {
        Write-Line "         (could not parse $cfgPath)"
    }
} else {
    Write-Line "         (not found: $cfgPath)"
}
Write-Line ""

# ------------------------------------------------------------
# 1. Preconditions
# ------------------------------------------------------------
if (-not (Test-Path $PYTHON_EXE)) {
    Write-Line "[ERROR] Python not found: $PYTHON_EXE"
    Write-Line ""
    Pause-Exit 1
}
if (-not (Test-Path $SERVER_DIR)) {
    Write-Line "[ERROR] Server dir not found: $SERVER_DIR"
    Write-Line ""
    Pause-Exit 1
}

Write-Line "[env]    Python : $PYTHON_EXE"
Write-Line "[env]    Server : $SERVER_DIR"
foreach ($tool in @("soffice", "pdftoppm")) {
    $cmd = Get-Command $tool -ErrorAction SilentlyContinue
    if ($cmd) {
        Write-Line "[env]    $tool : $($cmd.Source)"
    } else {
        Write-Line "[env]    $tool : NOT FOUND -> PPT preview degrades to placeholder cards"
    }
}
Write-Line ""
Write-Line "Supervising every $PROBE_EVERY s. Keep this window open."
Write-Line "------------------------------------------------------------"

# ------------------------------------------------------------
# 2. Supervisor loop
# ------------------------------------------------------------
$consecutiveFails = 0

while ($true) {
    if (Test-BackendUp $HEALTH) {
        $consecutiveFails = 0
        Write-Host "." -NoNewline
        Start-Sleep -Seconds $PROBE_EVERY
        continue
    }

    Write-Line ""
    Write-Line "$(Stamp) backend not responding -> starting uvicorn"

    $ok = Start-Backend -Tag (Get-Date -Format "HHmmss")
    if (-not $ok) {
        $consecutiveFails++
        Write-Line "$(Stamp) launch failed ($consecutiveFails/3)"
        if ($consecutiveFails -ge 3) {
            Write-Line ""
            Write-Line "[ERROR] Could not start the backend after 3 attempts."
            Write-Line "        Is port $PORT taken by something else?"
            Write-Line "        Start it manually to see the real error:"
            Write-Line "          cd $SERVER_DIR"
            Write-Line "          $PYTHON_EXE -m uvicorn app.main:app --host 0.0.0.0 --port $PORT"
            Write-Line ""
            Pause-Exit 1
        }
        Start-Sleep -Seconds 5
        continue
    }

    $ready = $false
    for ($i = 1; $i -le 30; $i++) {
        Start-Sleep -Seconds 2
        if (Test-BackendUp $HEALTH) { $ready = $true; break }
        Write-Host "." -NoNewline
    }

    if ($ready) {
        $consecutiveFails = 0
        Write-Line ""
        Write-Line "$(Stamp) backend is UP   http://127.0.0.1:$PORT/docs"
    } else {
        $consecutiveFails++
        Write-Line ""
        Write-Line "$(Stamp) started but never became ready ($consecutiveFails/3)"
        Write-Line "        check $LOG_DIR\backend_*.err.log"
        if ($consecutiveFails -ge 3) {
            Write-Line ""
            Write-Line "[ERROR] Backend keeps failing to become ready."
            Write-Line ""
            Pause-Exit 1
        }
    }
}
