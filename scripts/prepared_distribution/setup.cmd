@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set "setup_result=%errorlevel%"
if not "%setup_result%"=="0" echo Setup failed. Read the message above before trying again.
pause
exit /b %setup_result%
