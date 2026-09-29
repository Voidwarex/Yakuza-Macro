@echo off
rem Builds dist\AmosSolutions.exe from test.py with Nuitka.
rem Run on Windows from this folder: build.bat
rem
rem The first run asks to download a C compiler (MinGW64); answer yes.
rem After building, approve the new .exe on the license server - see
rem "Building the .exe" in the README.

python -m pip install --upgrade nuitka zstandard ordered-set flask pynput vgamepad || goto :error

rem vgamepad loads ViGEmClient.dll from its own folder. Nuitka never
rem copies DLLs as package data, so name them explicitly below.
set "VGP="
for /f "delims=" %%i in ('python -c "import importlib.util, os; print(os.path.dirname(importlib.util.find_spec('vgamepad').origin))"') do set "VGP=%%i"
if not defined VGP goto :error
if not exist "%VGP%\win\vigem\client\x64\ViGEmClient.dll" (
    echo Can't find ViGEmClient.dll in "%VGP%".
    goto :error
)

python -m nuitka ^
    --onefile ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=branding\amos.ico ^
    --include-package=vgamepad ^
    --include-data-files="%VGP%\win\vigem\client\x64\ViGEmClient.dll=vgamepad\win\vigem\client\x64\ViGEmClient.dll" ^
    --include-data-files="%VGP%\win\vigem\client\x86\ViGEmClient.dll=vgamepad\win\vigem\client\x86\ViGEmClient.dll" ^
    --product-name="Amos Solutions" ^
    --company-name="Amos Solutions" ^
    --file-description="Amos Solutions Auto Builder" ^
    --product-version=1.0.0 ^
    --file-version=1.0.0 ^
    --output-dir=dist ^
    --output-filename=AmosSolutions.exe ^
    --assume-yes-for-downloads ^
    --remove-output ^
    test.py || goto :error

echo.
echo Built dist\AmosSolutions.exe
echo Its SHA-256 (approve this on the license server):
powershell -NoProfile -Command "(Get-FileHash dist\AmosSolutions.exe -Algorithm SHA256).Hash.ToLower()"
goto :eof

:error
echo.
echo Build failed. Scroll up for the first error.
exit /b 1
