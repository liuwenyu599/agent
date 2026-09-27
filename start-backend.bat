@echo off
rem ============================================================
rem  Judicial AI - Start backend server
rem  Double-click this file. It runs start-backend.ps1
rem  (bypassing the execution policy for this one file only).
rem ============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-backend.ps1"
