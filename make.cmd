@echo off
REM Windows shim so `make <task>` works without GNU Make installed.
REM cmd.exe resolves `make` to this file when run from the repository root.
REM The real task list lives in tools/tasks.py - this only finds Python.
setlocal

REM Prefer the py launcher; it is what a stock python.org install provides.
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py -3 -m tools.tasks %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python -m tools.tasks %*
    exit /b %ERRORLEVEL%
)

echo Python 3.11 or newer is required but was not found on PATH.
echo Install it from https://www.python.org/downloads/ and tick
echo "Add python.exe to PATH" in the installer.
exit /b 1
