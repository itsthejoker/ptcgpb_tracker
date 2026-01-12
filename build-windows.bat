@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Build a distributable ZIP (Windows) using uv + PyInstaller
REM - Produces an onedir bundle under dist\<name>\ and a ZIP archive dist\<name>-<version>-windows.zip
REM - Requires: uv (https://docs.astral.sh/uv/) and PowerShell (for parsing and zipping)

REM Move to the directory of this script
pushd "%~dp0"

REM Check for uvx
where uvx >nul 2>&1
if errorlevel 1 (
  echo Error: 'uv' / 'uvx' is not installed. Install from https://docs.astral.sh/uv/
  popd
  exit /b 1
)

REM Extract name and version from pyproject.toml using PowerShell (simple regex; no external deps)
for /f "usebackq tokens=*" %%A in (`powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t = Get-Content -Raw 'pyproject.toml';" ^
  "$name = [regex]::Match($t,'(?m)^\s*name\s*=\s*\"([^\"]+)\"').Groups[1].Value;" ^
  "$ver  = [regex]::Match($t,'(?m)^\s*version\s*=\s*\"([^\"]+)\"').Groups[1].Value;" ^
  "[Console]::WriteLine(($name, $ver) -join '|')"`) do (
  set "PYPROJECT=%%A"
)

for /f "tokens=1,2 delims=|" %%i in ("%PYPROJECT%") do (
  set "PROJECT_NAME=%%i"
  set "PROJECT_VERSION=%%j"
)

REM Allow overrides via environment
if not defined APP_NAME set "APP_NAME=%PROJECT_NAME%"
if not defined APP_VERSION set "APP_VERSION=%PROJECT_VERSION%"
if not defined APP_NAME set "APP_NAME=ptcgpb-companion"
if not defined APP_VERSION set "APP_VERSION=0.0.0"
if not defined ENTRYPOINT set "ENTRYPOINT=main.py"

echo Building %APP_NAME% v%APP_VERSION% (entry: %ENTRYPOINT%)

REM Clean previous builds
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Common PyInstaller options (Windows)
set "PYI_OPTS=--noconfirm --clean --name %APP_NAME% --windowed"

REM Data assets to include (src;dest within bundle on Windows)
REM Example (uncomment and adjust as needed):
REM   set "PYI_ADD_DATA=resources\card_imgs;resources\card_imgs"
REM For multiple entries, separate by spaces:
REM   set "PYI_ADD_DATA=resources\card_imgs;resources\card_imgs resources\icons;resources\icons"
set "PYI_ADD_DATA="

for %%D in (%PYI_ADD_DATA%) do (
  set "PYI_OPTS=!PYI_OPTS! --add-data \"%%D\""
)

REM If you have an application icon, uncomment and adjust:
REM set "PYI_OPTS=%PYI_OPTS% --icon resources\icons\app.ico"

echo Running PyInstaller via uvx...
uvx --from pyinstaller pyinstaller %PYI_OPTS% "%ENTRYPOINT%"
if errorlevel 1 (
  echo PyInstaller failed.
  popd
  exit /b 1
)

set "DIST_DIR=dist\%APP_NAME%"
if not exist "%DIST_DIR%" (
  echo Error: Expected output directory "%DIST_DIR%" not found. PyInstaller may have failed.
  popd
  exit /b 1
)

set "ZIP_NAME=dist\%APP_NAME%-%APP_VERSION%-windows.zip"
echo Packaging "%DIST_DIR%" -^> "%ZIP_NAME%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "if (Test-Path '%ZIP_NAME%') { Remove-Item -Force '%ZIP_NAME%' } ;" ^
  "Compress-Archive -Path '%DIST_DIR%\*' -DestinationPath '%ZIP_NAME%' -Force"

if errorlevel 1 (
  echo Failed to create ZIP archive.
  popd
  exit /b 1
)

echo.
echo Build complete: %ZIP_NAME%
echo To run: unzip the archive and execute ".\%APP_NAME%\%APP_NAME%.exe"

popd
endlocal
exit /b 0
