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

function Start-AppAfterUpdate {
    param(
        [string]$ExePath,
        [string]$WorkDir,
        [string]$Arguments = ""
    )

    # A silent restart failure is the worst outcome there is for a screen-reader
    # user: the update succeeded, the app is simply gone, and nothing on screen
    # says why. So every attempt is verified - a process that dies within a few
    # seconds counts as a failure, not a success - and the last resort hands the
    # launch to Explorer, which starts the app from the shell instead of from
    # this helper's own process tree.
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $app = $null
        try {
            $startArgs = @{
                FilePath         = $ExePath
                WorkingDirectory = $WorkDir
                PassThru         = $true
            }
            if ($Arguments) { $startArgs['ArgumentList'] = $Arguments }
            $app = Start-Process @startArgs
        } catch {
            Write-Log "Restart attempt $attempt could not launch the app: $($_.Exception.Message)"
        }
        if ($app) {
            # Long enough to get past DLL loading, where a broken install dies.
            for ($tick = 0; $tick -lt 20 -and -not $app.HasExited; $tick++) {
                Start-Sleep -Milliseconds 250
            }
            if (-not $app.HasExited) {
                Write-Log "App restarted (PID $($app.Id))."
                return $true
            }
            Write-Log "Restart attempt $attempt exited immediately with code $($app.ExitCode)."
        }
        Start-Sleep -Seconds 2
    }

    try {
        Write-Log "Falling back to Explorer to start the app."
        Start-Process -FilePath "explorer.exe" -ArgumentList "`"$ExePath`""
        return $true
    } catch {
        Write-Log "Explorer fallback failed: $($_.Exception.Message)"
    }
    Write-Log "Could not restart the app after the update."
    return $false
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
        $restarted = Start-AppAfterUpdate -ExePath $exePath -WorkDir $InstallDir -Arguments $RestartArgs
        Write-Log "Installer updater completed."
        if ($restarted) { exit 0 }
        exit 2
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
    if ((Test-Path -LiteralPath $BackupDir) -and -not (Test-Path -LiteralPath $InstallDir)) {
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
if (-not (Test-Path -LiteralPath $exePath)) {
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

# Clear the backup before restarting, not after. A recursive delete of a
# directory tree right beside the install is heavy disk work, and it used to run
# while the freshly started app was still loading its own DLLs out of that same
# install directory.
if (Test-Path -LiteralPath $BackupDir) {
    try {
        Write-Log "Removing backup directory: $BackupDir"
        Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction Stop
        Write-Log "Backup directory removed successfully."
    } catch {
        Write-Log "Failed to remove backup directory: $($_.Exception.Message)"
    }
}

Write-Log "Restarting app: $exePath"
$restarted = Start-AppAfterUpdate -ExePath $exePath -WorkDir $InstallDir -Arguments $RestartArgs

Write-Log "Updater completed."
if ($restarted) { exit 0 }
exit 2
