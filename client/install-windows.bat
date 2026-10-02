@echo off
setlocal EnableExtensions
title Remote Power - Install

REM Folder this script lives in (strip trailing backslash)
set "DIR=%~dp0"
set "DIR=%DIR:~0,-1%"

REM Find pythonw.exe (Python with no console window)
set "PYW="
for /f "delims=" %%I in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%I"
if not defined PYW (
  echo.
  echo Could not find pythonw.exe on your PATH.
  echo Install Python from https://python.org and tick "Add Python to PATH",
  echo then run this installer again.
  echo.
  pause
  exit /b 1
)

REM Work out python.exe next to pythonw.exe and install 'requests'
for %%I in ("%PYW%") do set "PYDIR=%%~dpI"
echo Installing the 'requests' package...
"%PYDIR%python.exe" -m pip install --quiet requests

REM Need a filled-in config.ini
if not exist "%DIR%\config.ini" (
  echo.
  echo config.ini not found in this folder.
  echo Copy config.example.ini to config.ini and paste your API key first.
  echo.
  pause
  exit /b 1
)

REM Write a tiny launcher into the Startup folder so it runs hidden at login
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS=%STARTUP%\RemotePower.vbs"
> "%VBS%" echo Set sh = CreateObject("WScript.Shell")
>> "%VBS%" echo sh.CurrentDirectory = "%DIR%"
>> "%VBS%" echo cmd = Chr(34) ^& "%PYW%" ^& Chr(34) ^& " listener.py"
>> "%VBS%" echo sh.Run cmd, 0, False

echo.
echo Starting Remote Power now (runs hidden, no window)...
wscript "%VBS%"

echo.
echo ============================================================
echo  Installed. Remote Power now starts automatically and
echo  silently every time you log in - no window will appear.
echo.
echo  Logs:      %DIR%\listener.log
echo  To remove: run uninstall-windows.bat
echo ============================================================
echo.
pause
