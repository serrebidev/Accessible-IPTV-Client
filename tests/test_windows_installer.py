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


def test_update_helper_supports_elevated_installer_mode_and_roaming_config():
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    assert "$InstallerPath" in helper
    assert "Start-Process -FilePath $InstallerPath" in helper
    assert "-Verb RunAs" in helper
    assert 'Join-Path $env:APPDATA "AccessibleIPTVClient"' in helper
    assert 'Join-Path $InstallDir "iptvclient.conf"' not in helper