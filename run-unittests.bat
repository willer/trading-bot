@echo off
REM Script to run all unit tests on Windows

echo === Running all unit tests ===
echo.

echo Running webapp tests...
python -m unittest test_webapp.py
if %ERRORLEVEL% NEQ 0 (
    set WEBAPP_FAILED=1
) else (
    set WEBAPP_FAILED=0
)

echo.

echo Running broker tests...
python -m unittest test_broker.py
if %ERRORLEVEL% NEQ 0 (
    set BROKER_FAILED=1
) else (
    set BROKER_FAILED=0
)

echo.
echo === Test run complete ===

if %WEBAPP_FAILED% EQU 0 if %BROKER_FAILED% EQU 0 (
    echo All tests passed successfully!
    exit /b 0
) else (
    echo Some tests failed. See logs above for details.
    exit /b 1
)