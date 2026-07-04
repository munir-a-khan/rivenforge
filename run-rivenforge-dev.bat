@echo off
REM ---------------------------------------------------------------------------
REM run-rivenforge-dev.bat - run the API sidecar from SOURCE, then launch the
REM installed desktop app against it.
REM
REM Why this exists: the Tauri shell reuses an already-listening sidecar on the
REM fixed port (47321) instead of spawning its bundled one. So starting the
REM source sidecar FIRST means the installed app runs against your latest
REM Python code with NO rebuild - ideal for iterating on core/ and api/.
REM
REM Usage:  run-rivenforge-dev.bat            (sidecar + installed app)
REM         run-rivenforge-dev.bat --api-only (sidecar only, for curl/tests)
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "PORT=47321"
set "HOST=127.0.0.1"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found on PATH. Install Python 3.11+ and retry.
    pause
    goto :eof
)

echo Starting rivenforge-api (source) on %HOST%:%PORT% ...
start "rivenforge-api (dev)" cmd /k python api_sidecar.py --host %HOST% --port %PORT% --log-level info

if /i "%~1"=="--api-only" (
    echo API sidecar launched in its own window. Leave it running for tests:
    echo   Invoke-RestMethod http://%HOST%:%PORT%/capture/status
    goto :eof
)

echo Waiting for the API to come up...
powershell -NoProfile -Command "for ($i=0; $i -lt 40; $i++) { try { Invoke-RestMethod http://%HOST%:%PORT%/health -TimeoutSec 1 | Out-Null; exit 0 } catch { Start-Sleep -Milliseconds 250 } }; exit 1"
if errorlevel 1 (
    echo API did not respond in time. Check the sidecar window for errors.
    pause
    goto :eof
)

set "APP=%LOCALAPPDATA%\rivenforge\rivenforge.exe"
if exist "%APP%" (
    echo API is up. Launching installed app (it will reuse this sidecar)...
    start "" "%APP%"
) else (
    echo API is up at http://%HOST%:%PORT% . Installed app not found - use the
    echo API directly, or build/install the app first. See PACKAGING.md.
)

endlocal
