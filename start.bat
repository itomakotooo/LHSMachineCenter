@echo off
REM One-click launcher for the Slot Console.
REM
REM Double-click this file in Explorer, or run it from cmd:
REM     start.bat              -> default port 8877, auto-open browser
REM     start.bat /install     -> pip install deps first, then launch
REM     start.bat /port 8899   -> custom port
REM     start.bat /noopen      -> don't auto-open the browser
REM
REM The command window stays open after uvicorn exits so you can see
REM any errors (press any key to close).

setlocal enabledelayedexpansion
cd /d "%~dp0"

set PORT=8877
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
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_console.ps1" -Port %PORT% %INSTALL% %OPENBROWSER%

echo.
echo ---- console stopped (exit code %ERRORLEVEL%) ----
pause
endlocal
