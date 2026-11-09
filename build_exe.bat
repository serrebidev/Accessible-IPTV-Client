@echo off
setlocal EnableDelayedExpansion

set "MODE=%~1"
if "%MODE%"=="" set "MODE=build"

if /I "%MODE%"=="build" goto :run
if /I "%MODE%"=="release" goto :run
if /I "%MODE%"=="dry-run" goto :run

echo Usage: build_exe.bat [build^|release^|dry-run]
exit /b 1

:run
set "SCRIPT=%~dp0tools\release.py"

if not exist "%SCRIPT%" (
    echo Release script not found: %SCRIPT%
    exit /b 1
)

rem Prefer Python 3.14 via the Windows py launcher; allow PYTHON env override.
rem Resolved once: the release state check below reuses the same interpreter.
if defined PYTHON (
    set "PYCMD="%PYTHON%""
) else (
    rem `call` below is load-bearing: `py` on this host is a py.cmd batch
    rem shim, and a bare `py` line ends this script silently with exit 0.
    where py >nul 2>nul
    if not errorlevel 1 (
        call py -3.14 -c "import sys" >nul 2>nul
        if not errorlevel 1 (
            set "PYCMD=py -3.14"
        ) else (
            set "PYCMD=python"
        )
    ) else (
        set "PYCMD=python"
    )
)
call %PYCMD% "%SCRIPT%" %MODE%
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

if /I "%MODE%"=="release" (
    call :ensure_release_state
    if errorlevel 1 exit /b 1
)

if /I "%MODE%"=="build" (
    echo.
    echo Build successful!
    echo Executable can be found in: dist\iptvclient\IPTVClient.exe
)

exit /b 0

:ensure_release_state
echo Ensuring the Forgejo release is published and draft-free...
for /f "delims=" %%T in ('git describe --tags --abbrev^=0') do set "RELEASE_TAG=%%T"
if "%RELEASE_TAG%"=="" (
    echo Failed to determine release tag from git.
    exit /b 1
)
call %PYCMD% -c "import sys;sys.path.insert(0,r'%~dp0tools');import release;release.ensure_release_state('%RELEASE_TAG%')"
if errorlevel 1 exit /b 1
exit /b 0
