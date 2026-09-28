@echo off
setlocal

rem ============================================================
rem  Judicial AI - Open SSH tunnels to the lab server
rem
rem   127.0.0.1:18061  ->  192.168.68.51:7861   (PPTAgent / DeepPresenter)
rem   127.0.0.1:18003  ->  192.168.68.51:8003   (llama.cpp LLM)
rem
rem  Requires key-based auth (no password prompt).
rem  Two minimized windows will stay open - closing them kills the tunnels.
rem ============================================================

set HOST=lwy@192.168.68.51
set SSHPORT=8081
set OPTS=-o BatchMode=yes -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N

echo.
echo ============================================================
echo  Judicial AI - SSH Tunnels to %HOST%
echo ============================================================
echo.

echo [1/3] 127.0.0.1:18061 -^> :7861  (PPTAgent)
start "PPTAgent-7861" /min ssh %OPTS% -L 127.0.0.1:18061:127.0.0.1:7861 %HOST% -p %SSHPORT%

echo [2/3] 127.0.0.1:18003 -^> :8003  (LLM)
start "LLM-8003" /min ssh %OPTS% -L 127.0.0.1:18003:127.0.0.1:8003 %HOST% -p %SSHPORT%

echo [3/3] Waiting for tunnels to come up...
timeout /t 6 >nul

echo.
echo ------------------------------------------------------------
echo  Verification
echo ------------------------------------------------------------
echo.

echo   PPTAgent  http://127.0.0.1:18061/
curl -s --noproxy "*" -o nul -w "        HTTP %%{http_code}" --max-time 8 http://127.0.0.1:18061/
echo.
echo.

echo   LLM       http://127.0.0.1:18003/v1/models
curl -s --noproxy "*" --max-time 8 http://127.0.0.1:18003/v1/models
echo.
echo.

echo ------------------------------------------------------------
echo  HTTP 200 / a JSON model list = tunnels are UP.
echo  Blank or 000 = SSH failed. Check:
echo    - key auth works:  ssh -p %SSHPORT% %HOST%
echo    - server reachable (ICMP is blocked, ping always fails - ignore it)
echo ------------------------------------------------------------
echo.
echo  Keep the two minimized windows open.
echo  If PPTAgent stays down, the app falls back to LOCAL template
echo  rendering (that is the "ugly template" people complain about).
echo.

pause
endlocal
