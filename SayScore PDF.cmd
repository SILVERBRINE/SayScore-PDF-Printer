@echo off
rem Existing PCs start immediately. A compatible clean PC is offered the WSL 2 Windows feature.
start "" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\Bootstrap-SayScore.ps1"
