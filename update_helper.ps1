param(
    [Parameter(Mandatory = $true)]
    [int]$ParentPid,
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [string]$StagingDir = "",
    [string]$BackupDir = "",
    [string]$InstallerPath = "",
    [Parameter(Mandatory = $true)]
    [string]$ExeName,
    [string]$RestartArgs = ""
)

Set-Location $env:TEMP
$logPath = Join-Path $env:TEMP "AccessibleIPTVClient_update.log"

function Write-Log {
    param([string]$Message)
    $stamp = (Get-Date).ToString("o")
    Add-Content -Path $logPath -Value "$stamp $Message"
}

Write-Log "Updater started. Waiting for PID $ParentPid."

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
}

$parentProcess = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
if ($parentProcess) {
    Write-Log "Process $ParentPid did not exit within timeout; terminating it."
    Stop-Process -Id $ParentPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 1000
}

# Kill any processes running from the install directory.
Write-Log "Scanning for processes locking $InstallDir..."
try {
    $targetProcessName = [System.IO.Path]::GetFileNameWithoutExtension($ExeName)
    $installPrefix = $InstallDir.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $candidateProcesses = Get-Process -Name $targetProcessName -ErrorAction SilentlyContinue
    $zombies = $candidateProcesses | Where-Object {
        try {
            $_.MainModule.FileName.StartsWith($installPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        } catch {
            $false
        }
    }
    foreach ($proc in $zombies) {
        if ($proc.Id -ne $PID -and $proc.Id -ne $ParentPid) {
            Write-Log "Killing zombie process: $($proc.Name) (PID $($proc.Id))"
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds 500
} catch {
    Write-Log "Warning: Failed to scan/kill zombie processes: $($_.Exception.Message)"
}

if ($InstallerPath) {
    if (-not (Test-Path -LiteralPath $InstallerPath)) {
        Write-Log "Installer missing: $InstallerPath"
        exit 1
    }

    Write-Log "Launching installer update: $InstallerPath"
    $installerArgs = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/DIR=`"$InstallDir`""
    )
    try {
        $proc = Start-Process -FilePath $InstallerPath -ArgumentList $installerArgs -Verb RunAs -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            Write-Log "Installer failed with exit code $($proc.ExitCode)."
            exit $proc.ExitCode
        }
    } catch {
        Write-Log "Failed to launch installer: $($_.Exception.Message)"
        exit 1
    }

    $exePath = Join-Path $InstallDir $ExeName
    if (Test-Path -LiteralPath $exePath) {
        Write-Log "Restarting app after installer update: $exePath"
        if ($RestartArgs) {
            Start-Process -FilePath $exePath -WorkingDirectory $InstallDir -ArgumentList $RestartArgs
        } else {
            Start-Process -FilePath $exePath -WorkingDirectory $InstallDir
        }
        Write-Log "Installer updater completed."
        exit 0
    }

    Write-Log "Executable not found after installer update: $exePath"
    exit 1
}

if (-not (Test-Path -LiteralPath $StagingDir)) {
    Write-Log "Staging directory missing: $StagingDir"
    exit 1
}

$parentDir = Split-Path -Parent $InstallDir
if ($parentDir -and -not (Test-Path -LiteralPath $parentDir)) {
    New-Item -ItemType Directory -Path $parentDir | Out-Null
}

if (Test-Path -LiteralPath $BackupDir) {
    Remove-Item -LiteralPath $BackupDir -Recurse -Force
}

try {
    if (Test-Path -LiteralPath $InstallDir) {
        Move-Item -LiteralPath $InstallDir -Destination $BackupDir -Force
        Write-Log "Moved current install to backup: $BackupDir"
    }
} catch {
    Write-Log "Failed to move install to backup: $($_.Exception.Message)"
    exit 1
}

try {
    Move-Item -LiteralPath $StagingDir -Destination $InstallDir -Force
    Write-Log "Installed update to $InstallDir"

    # Portable zip updates replace the app directory; preserve the local config
    # beside the new executable when the previous portable copy had one.
    $oldConfig = Join-Path $BackupDir "iptvclient.conf"
    $newConfig = Join-Path $InstallDir "iptvclient.conf"
    if ((Test-Path -LiteralPath $oldConfig) -and -not (Test-Path -LiteralPath $newConfig)) {
        try {
            Copy-Item -LiteralPath $oldConfig -Destination $newConfig -Force
            Write-Log "Preserved portable configuration in install directory."
        } catch {
            Write-Log "Failed to preserve portable configuration: $($_.Exception.Message)"
        }
    }

    # Preserve pre-portable AppData configs as a fallback for users updating
    # from builds that still stored portable settings in the roaming profile.
    $roamingDir = Join-Path $env:APPDATA "AccessibleIPTVClient"
    $roamingConfig = Join-Path $roamingDir "iptvclient.conf"
    if ((Test-Path -LiteralPath $roamingConfig) -and -not (Test-Path -LiteralPath $newConfig)) {
        try {
            Copy-Item -LiteralPath $roamingConfig -Destination $newConfig -Force
            Write-Log "Migrated roaming configuration to portable install directory."
        } catch {
            Write-Log "Failed to migrate configuration: $($_.Exception.Message)"
        }
    }
} catch {
    Write-Log "Failed to move staging into place: $($_.Exception.Message)"
    if (Test-Path -LiteralPath $BackupDir -and -not (Test-Path -LiteralPath $InstallDir)) {
        try {
            Move-Item -LiteralPath $BackupDir -Destination $InstallDir -Force
            Write-Log "Rollback completed."
        } catch {
            Write-Log "Rollback failed: $($_.Exception.Message)"
        }
    }
    exit 1
}

$exePath = Join-Path $InstallDir $ExeName
if (Test-Path -LiteralPath $exePath) {
    Write-Log "Restarting app: $exePath"
    if ($RestartArgs) {
        Start-Process -FilePath $exePath -WorkingDirectory $InstallDir -ArgumentList $RestartArgs
    } else {
        Start-Process -FilePath $exePath -WorkingDirectory $InstallDir
    }
} else {
    Write-Log "Executable not found after update: $exePath"
    if (Test-Path -LiteralPath $BackupDir) {
        try {
            Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
            Move-Item -LiteralPath $BackupDir -Destination $InstallDir -Force
            Write-Log "Rolled back to previous version because the new executable was missing."
        } catch {
            Write-Log "Rollback failed: $($_.Exception.Message)"
        }
    }
    exit 1
}

if (Test-Path -LiteralPath $BackupDir) {
    try {
        Write-Log "Removing backup directory: $BackupDir"
        Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction Stop
        Write-Log "Backup directory removed successfully."
    } catch {
        Write-Log "Failed to remove backup directory: $($_.Exception.Message)"
    }
}

Write-Log "Updater completed."
exit 0
