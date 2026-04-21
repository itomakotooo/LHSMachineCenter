@echo off
REM One-click launcher for the Virtual Machine Console.
REM
REM The virtual console runs a second FastAPI instance on port 8878
REM (real console is 8877) with fully isolated data:
REM   - rawdata : slot_designer/rawdata/
REM   - reports : slot_designer/reports/
REM   - state   : slot_designer/state/
REM   - machines: slot_designer/configs/machines_virtual.json
REM Both consoles can run simultaneously — open two browser tabs and
REM do side-by-side real-vs-virtual comparisons.
REM
REM Double-click this file in Explorer, or run it from cmd:
REM     start_virtual.bat              -> default port 8878, auto-open browser
REM     start_virtual.bat /install     -> pip install deps first, then launch
REM     start_virtual.bat /port 8879   -> custom port
REM     start_virtual.bat /noopen      -> don't auto-open the browser
REM
REM The command window stays open after uvicorn exits so you can see
REM any errors (press any key to close).

setlocal enabledelayedexpansion
cd /d "%~dp0"

set PORT=8878
set INSTALL=
set OPENBROWSER=-OpenBrowser

:parse_args
if "%~1"=="" goto run
if /I "%~1"=="/install"  (set INSTALL=-Install & shift & goto parse_args)
if /I "%~1"=="/port"     (set PORT=%~2          & shift & shift & goto parse_args)
if /I "%~1"=="/noopen"   (set OPENBROWSER=      & shift & goto parse_args)
echo WARN: unknown argument "%~1" (ignored).
shift
goto parse_args

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0slot_designer\scripts\start_virtual_console.ps1" -Port %PORT% %INSTALL% %OPENBROWSER%

echo.
echo ---- virtual console stopped (exit code %ERRORLEVEL%) ----
pause
endlocal
