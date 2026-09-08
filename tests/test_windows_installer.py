from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_inno_installer_uses_program_files_and_installed_marker():
    script = (ROOT / "installer" / "AccessibleIPTVClient.iss").read_text(encoding="utf-8")

    assert "DefaultDirName={autopf}\\{#MyAppName}" in script
    assert "PrivilegesRequired=admin" in script
    assert "ArchitecturesAllowed=x64compatible" in script
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in script
    assert 'Source: "windows-installed.marker"; DestDir: "{app}"; DestName: ".windows-installed"' in script
    assert "{localappdata}\\Programs" not in script.lower()
    assert "PrivilegesRequired=lowest" not in script


def test_inno_installer_excludes_mutable_runtime_files():
    script = (ROOT / "installer" / "AccessibleIPTVClient.iss").read_text(encoding="utf-8")

    for excluded in (
        "iptvclient.conf",
        "epg.db",
        "epg.db-wal",
        "epg.db-shm",
        "scheduled_recordings.json",
        "iptv_cache\\*",
    ):
        assert excluded in script


def test_release_tool_builds_signs_and_uploads_installer_asset():
    release_py = (ROOT / "tools" / "release.py").read_text(encoding="utf-8")

    assert "INNO_SETUP_COMPILER" in release_py
    assert "ISCC.exe" in release_py
    assert "def build_installer" in release_py
    assert "installer_path = build_installer(next_version)" in release_py
    assert "sign_executable(installer_path)" in release_py
    assert "installer_asset_filename" in release_py
    assert 'release_assets.append(assets["installer_path"])' in release_py


def test_update_helper_supports_elevated_installer_mode_and_portable_config():
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    assert "$InstallerPath" in helper
    assert "Start-Process -FilePath $InstallerPath" in helper
    assert "-Verb RunAs" in helper
    assert helper.index("if ($InstallerPath)") < helper.index("Portable zip updates replace the app directory")
    assert 'Join-Path $env:APPDATA "AccessibleIPTVClient"' in helper
    assert '$newConfig = Join-Path $InstallDir "iptvclient.conf"' in helper
    assert "Preserved portable configuration in install directory." in helper
    assert "Migrated roaming configuration to portable install directory." in helper
    assert "Migrated configuration from backup to roaming profile." not in helper


def test_update_helper_verifies_the_restart_and_retries():
    """A restart that silently fails leaves a blind user with no app and no clue.

    The helper used to fire Start-Process and exit without ever looking at the
    result, so "Restarting app" in the log meant nothing more than "the call did
    not throw". Every attempt is now checked, retried, and finally handed to
    Explorer, which starts the app outside this helper's process tree.
    """
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    assert "function Start-AppAfterUpdate" in helper
    assert "PassThru         = $true" in helper
    assert "$app.HasExited" in helper
    assert "explorer.exe" in helper
    assert "Could not restart the app after the update." in helper
    # Both update paths go through it; neither fires and forgets any more.
    assert helper.count("Start-AppAfterUpdate -ExePath") == 2
    assert "Start-Process -FilePath $exePath -WorkingDirectory $InstallDir" not in helper


def test_update_helper_clears_the_backup_before_restarting():
    """The recursive delete used to run while the new app was loading its DLLs."""
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    removal = helper.index("Removing backup directory")
    restart = helper.index('Write-Log "Restarting app: $exePath"')
    assert removal < restart


def test_update_helper_rollback_condition_is_valid_powershell():
    """`Test-Path -LiteralPath $x -and ...` binds -and as a positional argument."""
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    assert "(Test-Path -LiteralPath $BackupDir) -and -not" in helper
    assert "Test-Path -LiteralPath $BackupDir -and" not in helper
