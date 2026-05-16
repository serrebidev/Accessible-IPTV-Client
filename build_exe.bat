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
if defined PYTHON (
    "%PYTHON%" "%SCRIPT%" %MODE%
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.14 -c "import sys" >nul 2>nul
        if not errorlevel 1 (
            py -3.14 "%SCRIPT%" %MODE%
        ) else (
            python "%SCRIPT%" %MODE%
        )
    ) else (
        python "%SCRIPT%" %MODE%
    )
)
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
echo Ensuring the GitHub release is published, latest, and draft-free...
for /f "delims=" %%T in ('git describe --tags --abbrev=0') do set "RELEASE_TAG=%%T"
if "%RELEASE_TAG%"=="" (
    echo Failed to determine release tag from app_meta.py.
    exit /b 1
)
gh release edit "%RELEASE_TAG%" --draft=false --latest
if errorlevel 1 exit /b 1
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $drafts = gh release list --limit 100 --json tagName,isDraft ^| ConvertFrom-Json ^| Where-Object { $_.isDraft }; foreach ($draft in $drafts) { Write-Host ('Deleting draft release ' + $draft.tagName + '...'); gh release delete $draft.tagName --yes }"
if errorlevel 1 exit /b 1
exit /b 0
