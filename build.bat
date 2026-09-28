@echo off
rem Builds dist\AmosSolutions.exe from test.py with Nuitka.
rem Run on Windows from this folder: build.bat
rem
rem The first run asks to download a C compiler (MinGW64); answer yes.
rem After building, approve the new .exe on the license server - see
rem "Building the .exe" in the README.

python -m pip install --upgrade nuitka zstandard ordered-set flask pynput vgamepad || goto :error

python -m nuitka ^
    --onefile ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=branding\amos.ico ^
    --include-package=vgamepad ^
    --include-package-data=vgamepad ^
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
