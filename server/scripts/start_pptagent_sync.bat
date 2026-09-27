@echo off
chcp 65001 >nul
REM PPTAgent remote workspace mirror (for per-page PPT preview).
REM
REM PPTAgent runs on a remote host, so its output directory cannot be scanned
REM by this machine. This mirrors it over SFTP every 20s so the backend
REM PPT_AGENT_WORKSPACE_DIR can find the per-page preview images.
REM
REM Keep this window open while generating a PPT.

cd /d "%~dp0\.."
D:\apps\anaconda3\python.exe scripts\sync_pptagent_workspace.py --daemon --interval 20
pause
