@echo off
set "PROJECT_ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%run.ps1" %*
