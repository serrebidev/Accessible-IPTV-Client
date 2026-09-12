import json
import re
from pathlib import Path

import i18n

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


def _update_helper_message_catalog():
    raw = (ROOT / "update_helper.ps1").read_bytes()
    # Windows PowerShell 5.1 can interpret a BOM-less script through the ANSI
    # code page. Keeping the embedded JSON ASCII-only makes every language
    # independent of that machine setting.
    assert raw.isascii()
    helper = raw.decode("ascii")
    match = re.search(
        r"\$UpdateMessagesJson = @'\r?\n(.*?)\r?\n'@",
        helper,
        flags=re.DOTALL,
    )
    assert match, "embedded update-helper translations are missing"
    return helper, json.loads(match.group(1))


def test_update_helper_has_unicode_safe_messages_for_every_app_language():
    helper, catalog = _update_helper_message_catalog()
    expected_languages = {"en", *i18n.SHIPPED_CATALOGS}
    message_keys = {"prepare", "install", "start", "error"}

    assert set(catalog) == expected_languages
    for language, messages in catalog.items():
        assert set(messages) == message_keys
        assert all(isinstance(text, str) and text.strip() for text in messages.values())
        if language != "en":
            assert messages != catalog["en"]

    # Decode representatives of every writing system used by the catalogues;
    # these values came from ASCII-only \u escapes in the PowerShell file.
    assert "Może" in catalog["pl"]["install"]
    assert "actualización" in catalog["es"]["prepare"]
    assert "التحديث" in catalog["ar"]["install"]
    assert "обновления" in catalog["ru"]["prepare"]
    assert "अपडेट" in catalog["hi"]["start"]
    assert "正在安装更新" in catalog["zh"]["install"]
    assert "更新をインストール" in catalog["ja"]["install"]
    assert "frissítés" in catalog["hu"]["prepare"]

    assert "$statusWindow = Show-UpdateStatus -Message $updateMessages.prepare" in helper
    assert helper.count("-Message $updateMessages.install") == 2
    assert helper.count("-Message $updateMessages.start") == 2
    assert helper.count("-Message $updateMessages.error") == 6


def test_update_helper_messages_do_not_repeat_the_application_name():
    """The window title is already "Accessible IPTV Client - <message>".

    A message that names the application again makes a screen reader say the
    name twice in one breath, and the title is the only thing NVDA reads when
    the window appears (nothing in it can take focus). The English source used
    to do this in `prepare` and `start`, so all thirteen translations faithfully
    reproduced it.
    """
    _helper, catalog = _update_helper_message_catalog()
    offenders = [
        "{0}/{1}".format(language, key)
        for language, messages in catalog.items()
        for key, text in messages.items()
        if "Accessible IPTV Client" in text
    ]
    assert not offenders, (
        "these messages repeat the app name already in the window title: "
        + ", ".join(offenders)
    )


def test_app_passes_its_resolved_language_to_both_update_paths():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    language_arguments = re.findall(
        r'"-Language",\s+helper_language,',
        main,
    )
    assert len(language_arguments) == 2
    assert main.count("helper_language = i18n.resolved_language()") == 2
    assert main.count('helper_language not in ("en", *i18n.SHIPPED_CATALOGS)') == 2


def test_update_helper_uses_selected_messages_for_every_status():
    helper, _catalog = _update_helper_message_catalog()
    assert "Show-UpdateStatus -Message $updateMessages.prepare" in helper
    assert helper.count("-Message $updateMessages.install") == 2
    assert helper.count("-Message $updateMessages.start") == 2
    assert helper.count("-Message $updateMessages.error") == 6
    assert '-Message "Installing the update.' not in helper
    assert '-Message "Starting the updated' not in helper
    assert '-Message "The update did not finish.' not in helper
