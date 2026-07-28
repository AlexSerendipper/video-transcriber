@echo off
setlocal
cd /d "%~dp0"
title Local Video Transcriber
echo Starting Local Video Transcriber...
echo.
echo Keep this window open while using the app.
echo Close this window or press Ctrl+C to stop the local server.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" %*
echo.
echo Server stopped. You can close this window.
pause
