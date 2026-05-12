@echo off
REM 中文输出靠 chcp 65001 (UTF-8); 否则默认 cp936 (GBK) 会把 UTF-8 字节
REM 错认成命令,整个脚本会炸。>nul 是 silent。
chcp 65001 >nul

REM Slot Console - 一键装环境 (Windows)
REM
REM 用法:
REM   双击本文件;或者在 cmd / PowerShell 里跑 install.bat 都行。
REM   装完后双击 start.bat 启动 console。
REM
REM 干什么:
REM   1. 检查 Python ^>= 3.10
REM   2. pip install -r src\web_console\requirements.txt
REM   3. 验证 fastapi / uvicorn 能 import

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ================================================
echo  Slot Console - 一键装环境
echo  仓库目录: %CD%
echo ================================================
echo.

REM ---- 1) 在仓库根目录? ----
if not exist "src\web_console\requirements.txt" (
    echo [FAIL] 当前目录不像 LHSMachineCenter 仓库根。
    echo        请把 install.bat 放在 start.bat 旁边 ^(repo 根目录^)。
    echo.
    pause
    exit /b 1
)

REM ---- 2) Python 在 PATH 吗? ----
where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] 找不到 python 命令。
    echo.
    echo 请先装 Python 3.10 或更新版本:
    echo     https://www.python.org/downloads/
    echo 安装时务必勾选 "Add Python to PATH"。
    echo 装完后重开一个 cmd 窗口再双击本脚本。
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PYVER=%%V"
if not defined PYVER (
    echo [FAIL] python --version 跑不出结果,Python 安装可能坏了。
    pause
    exit /b 1
)
echo Python: %PYVER%

REM ---- 3) Python ^>= 3.10? ----
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set "PYMAJOR=%%a"
    set "PYMINOR=%%b"
)
set "BADVER="
if %PYMAJOR% LSS 3 set "BADVER=1"
if %PYMAJOR% EQU 3 if %PYMINOR% LSS 10 set "BADVER=1"
if defined BADVER (
    echo.
    echo [FAIL] 需要 Python ^>= 3.10,当前是 %PYVER%。
    echo        请升级:https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM ---- 4) 装依赖 ----
echo.
echo === pip install (装依赖) ===
python -m pip install -r src\web_console\requirements.txt
if errorlevel 1 (
    echo.
    echo [FAIL] pip install 失败。看上面错误信息。
    echo        如果是网络问题,可以用公司内部 pip 镜像:
    echo            python -m pip install -r src\web_console\requirements.txt -i ^<镜像 URL^>
    echo.
    pause
    exit /b 1
)

REM ---- 5) 验证 ----
echo.
echo === 验证 ===
python -c "import fastapi, uvicorn; print('OK - fastapi + uvicorn ready')"
if errorlevel 1 (
    echo.
    echo [FAIL] fastapi / uvicorn 装完但 import 不行。看上面 python 输出。
    echo.
    pause
    exit /b 1
)

echo.
echo ================================================
echo  装完了。
echo  下一步:双击根目录的 start.bat 启动 console。
echo ================================================
echo.
pause
endlocal
