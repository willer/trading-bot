@echo off
setlocal

set logfile=logs\start-webapp.log
set max_log_size=10485760
set num_logs_to_keep=5

:: Ensure logs directory exists
if not exist logs mkdir logs

:: Function equivalent to rotate_logs
call :rotate_logs

:: Find Python
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set py=python
) else (
    set py=python3
)

:: Set up Flask environment
set FLASK_APP=webapp
set FLASK_ENV=development
set FLASK_DEBUG=1
set PYTHONPATH=.

:loop
echo --------------------------------- >> %logfile%
echo %date% %time% >> %logfile%
echo Starting up >> %logfile%
%py% -m flask run -p 6008 2>&1 >> %logfile%
echo Restarting in 2s >> %logfile%
timeout /t 2 /nobreak >nul
goto loop

:rotate_logs
:: Get file size
if exist %logfile% (
    for %%A in (%logfile%) do set size=%%~zA
    if !size! geq %max_log_size% (
        for /L %%i in (%num_logs_to_keep%,-1,1) do (
            if exist %logfile%.%%i (
                set /a "next=%%i+1"
                rename %logfile%.%%i %logfile%.!next!
            )
        )
        rename %logfile% %logfile%.1
        type nul > %logfile%
    )
)
goto :eof

:: Cleanup on script exit
:cleanup
exit /b 