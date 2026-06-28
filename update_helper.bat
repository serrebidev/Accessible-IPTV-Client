@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%TEMP%"

REM The app launches this batch file with CREATE_NO_WINDOW. Call PowerShell
REM directly so quoted paths are preserved by cmd's normal argument handling.
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "%SCRIPT_DIR%update_helper.ps1" %*
exit /b 0
