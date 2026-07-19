@echo off
chcp 65001 >nul 2>nul
setlocal

title Smart Timetable Pro - Local Backend

REM ============================================================
REM  Auto-locate to the folder where this .bat lives
REM  (uses %~dp0 so no hardcoded non-ASCII path is needed)
REM ============================================================
cd /d "%~dp0"

echo ========================================================
echo   Smart Timetable Pro - Local Backend  [Plan A]
echo   Directory: %CD%
echo ========================================================
echo.

REM ---- check app.py exists ----
if not exist "app.py" goto :noapp

REM ============================================================
REM  Locate a Python interpreter (any Python 3 — no third-party deps needed):
REM    1) managed WorkBuddy venv
REM    2) managed WorkBuddy python
REM    3) python  on PATH
REM    4) py      on PATH
REM ============================================================
set "PY_EXE=C:\Users\lenovo\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if exist "%PY_EXE%" goto :run

set "PY_EXE=C:\Users\lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if exist "%PY_EXE%" goto :run

set "PY_EXE="
where python >nul 2>nul
if "%errorlevel%"=="0" set "PY_EXE=python"
if defined PY_EXE goto :run

where py >nul 2>nul
if "%errorlevel%"=="0" set "PY_EXE=py"
if defined PY_EXE goto :run

echo [ERROR] Python was not found.
echo         Please install Python 3, or add it to PATH, then retry.
echo.
pause
exit /b 1

:run
echo Using Python : %PY_EXE%
echo Starting     : python app.py
echo Stop with    : Ctrl+C
echo --------------------------------------------------------
echo.
"%PY_EXE%" app.py
set "RC=%errorlevel%"

echo.
echo ========================================================
echo   Server stopped. Exit code: %RC%
echo   If it failed to start, common causes:
echo     - Port 8000 already in use (close the other process)
echo     - test_data.js missing or malformed
echo   The window stays open so you can review the logs above.
echo ========================================================
pause
exit /b %RC%

:noapp
echo [ERROR] app.py was not found in:
echo         %CD%
echo         Place start_server.bat in the same folder as app.py.
echo.
pause
exit /b 1
