@echo off
rem Existing PCs start immediately. A compatible clean PC is offered WSL/Docker setup.
start "" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\Bootstrap-SayScore.ps1"
