@echo off
title SayScore PDF - 준비 상태 확인
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Test-SayScoreRequirements.ps1"
echo.
pause
