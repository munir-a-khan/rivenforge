@echo off
REM ---------------------------------------------------------------------------
REM run-rivenforge.bat - launch the installed rivenforge desktop app.
REM
REM The app bundles its own API sidecar (rivenforge-api.exe) and spawns it
REM automatically, so this just starts the desktop shell. If a sidecar is
REM already listening on the fixed port (e.g. from run-rivenforge-dev.bat),
REM the app reuses it instead of spawning a second one.
REM ---------------------------------------------------------------------------
setlocal

set "APP=%LOCALAPPDATA%\rivenforge\rivenforge.exe"

if exist "%APP%" (
    echo Launching rivenforge...
    start "" "%APP%"
    goto :eof
)

echo Installed app not found at:
echo   %APP%
echo.
echo Install it first from:
echo   frontend\src-tauri\target\release\bundle\nsis\rivenforge_*-setup.exe
echo Or run from source with: run-rivenforge-dev.bat
pause
endlocal
