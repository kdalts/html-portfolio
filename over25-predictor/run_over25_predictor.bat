@echo off
REM Manual/scheduled runner for the Over 2.5 Predictor.
REM Double-click this file to run it on demand, or point Task Scheduler at it.

setlocal
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python over25_predictor.py
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% NEQ 0 (
    echo.
    echo Over 2.5 Predictor exited with code %EXITCODE% -- check over25_predictor.log
    pause
)

endlocal
exit /b %EXITCODE%
