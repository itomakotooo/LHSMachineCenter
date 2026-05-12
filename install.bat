@echo off
REM Slot Console - one-click env setup (Windows)
REM
REM Usage: double-click this file, or run install.bat in cmd/PowerShell.
REM After it finishes, double-click start.bat to launch the console.
REM
REM Steps:
REM   1. Check Python >= 3.10
REM   2. Upgrade pip
REM   3. pip install -r src\web_console\requirements.txt
REM      (Tsinghua mirror first for speed in CN networks, PyPI fallback)
REM   4. Verify fastapi / uvicorn import

chcp 65001 >nul 2>nul

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ================================================
echo  Slot Console - one-click env setup
echo  Repo: %CD%
echo ================================================
echo.

REM ---- 1) repo root sanity ----
if not exist "src\web_console\requirements.txt" (
    echo [FAIL] Not in LHSMachineCenter repo root.
    echo        Put install.bat next to start.bat at the repo root.
    echo.
    pause
    exit /b 1
)

REM ---- 2) python on PATH? ----
where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] python not found in PATH.
    echo.
    echo Install Python 3.10-3.13 from:
    echo     https://www.python.org/downloads/
    echo IMPORTANT: tick "Add Python to PATH" during install.
    echo Reopen cmd after installing, then run install.bat again.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PYVER=%%V"
if not defined PYVER (
    echo [FAIL] python --version produced no output. Python install may be broken.
    pause
    exit /b 1
)
echo Python: %PYVER%

REM ---- 3) python >= 3.10 ? ----
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set "PYMAJOR=%%a"
    set "PYMINOR=%%b"
)
set "BADVER="
if %PYMAJOR% LSS 3 set "BADVER=1"
if %PYMAJOR% EQU 3 if %PYMINOR% LSS 10 set "BADVER=1"
if defined BADVER (
    echo.
    echo [FAIL] Need Python ^>= 3.10, got %PYVER%.
    echo        Upgrade: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM ---- 4) pip install: Tsinghua mirror primary, PyPI fallback ----
set "TSINGHUA=https://pypi.tuna.tsinghua.edu.cn/simple"

echo.
echo === Upgrading pip (Tsinghua mirror) ===
python -m pip install --upgrade pip -i %TSINGHUA%

echo.
echo === pip install deps (Tsinghua mirror, prebuilt wheels preferred) ===
python -m pip install --prefer-binary -r src\web_console\requirements.txt -i %TSINGHUA%
if not errorlevel 1 goto :pip_ok

echo.
echo Tsinghua mirror failed. Retrying with default PyPI...
python -m pip install --prefer-binary -r src\web_console\requirements.txt
if not errorlevel 1 goto :pip_ok

echo.
echo [FAIL] pip install failed on both Tsinghua mirror and default PyPI.
echo.
echo Common causes:
echo   * Network: VPN / proxy / firewall blocking pip
echo   * Python %PYVER% too new for some prebuilt wheels.
echo     If you are on Python 3.14+, downgrade to 3.12 or 3.13.
echo   * Company mirror needed. Manual retry:
echo         python -m pip install -r src\web_console\requirements.txt -i ^<your-mirror^>
echo.
pause
exit /b 1

:pip_ok
echo (pip install OK)

REM ---- 5) verify ----
echo.
echo === Verifying fastapi / uvicorn ===
python -c "import fastapi, uvicorn; print('OK - fastapi + uvicorn ready')"
if errorlevel 1 (
    echo.
    echo [FAIL] fastapi or uvicorn installed but import broken.
    echo        See python error above. Contact dev.
    pause
    exit /b 1
)

echo.
echo ================================================
echo  Install complete.
echo  Next: double-click start.bat to launch console.
echo ================================================
echo.
pause
endlocal
