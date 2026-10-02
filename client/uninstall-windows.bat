@echo off
setlocal EnableExtensions
title Remote Power - Uninstall

set "VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RemotePower.vbs"
if exist "%VBS%" (
    del "%VBS%"
    echo Removed auto-start.
) else (
    echo Auto-start was not installed.
)

echo.
echo Stopping any running listener...
taskkill /f /im pythonw.exe >nul 2>&1

echo.
echo Done. Remote Power will no longer start at login.
pause
