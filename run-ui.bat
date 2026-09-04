@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0run-ui.ps1" -Port 8765 -ListenHost 127.0.0.1
