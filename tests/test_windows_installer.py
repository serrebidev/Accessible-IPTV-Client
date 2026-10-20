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
    assert "$psi.FileName = $InstallerPath" in helper
    assert '$psi.Verb = "runas"' in helper
    assert helper.index("if ($InstallerPath)") < helper.index("Portable zip updates replace the app directory")
    assert 'Join-Path $env:APPDATA "AccessibleIPTVClient"' in helper
    assert '$newConfig = Join-Path $InstallDir "iptvclient.conf"' in helper
    assert "Preserved portable configuration in install directory." in helper
    assert "Migrated roaming configuration to portable install directory." in helper
    assert "Migrated configuration from backup to roaming profile." not in helper


def test_update_helper_stops_only_bundled_ffmpeg_before_replacing_the_app():
    """A detached recording finalizer must not keep the update's ffmpeg.exe locked."""
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    assert '$targetProcessNames = @($targetProcessName, "ffmpeg")' in helper
    assert "Get-Process -Name $targetProcessNames" in helper
    assert "StartsWith($installPrefix" in helper
    assert "never terminate an unrelated FFmpeg" in helper


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
    # Both update paths go through it, and so does a failed update, which
    # brings the old app back to report it; nothing fires and forgets.
    assert helper.count("Start-AppAfterUpdate -ExePath") == 3
    assert "Start-Process -FilePath $exePath -WorkingDirectory $InstallDir" not in helper


def test_update_helper_clears_the_backup_before_restarting():
    """The recursive delete used to run while the new app was loading its DLLs."""
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    removal = helper.index("Removing backup directory")
    restart = helper.index('Write-Log "Restarting app: $exePath"')
    assert removal < restart


def test_update_helper_rollback_condition_is_valid_powershell():
    """`Test-Path -LiteralPath $x -and ...` binds -and as a positional argument.

    The rollback lives in Restore-InstallBackup now, and it must not use that
    form anywhere.
    """
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    assert "function Restore-InstallBackup {" in helper
    assert "Test-Path -LiteralPath $BackupDir -and" not in helper
    assert "Test-Path -LiteralPath $InstallDir -and" not in helper


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
    # "complete" is the update's last word, said in the same window rather
    # than in a box from the restarted app; "cancel"/"close" label the one
    # button that window ever shows.
    message_keys = {"prepare", "consent", "install", "start", "error",
                    "complete", "restart", "cancel", "close"}

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
    assert "Schließen" == catalog["de"]["close"]
    assert "versión" in catalog["es"]["complete"]

    assert "$statusWindow = Show-UpdateStatus -Message $firstMessage" in helper
    assert helper.count("-Message $updateMessages.install") == 2
    assert helper.count("-Message $updateMessages.start") == 2
    assert helper.count("-Message $updateMessages.error") == 1
    assert "$updateMessages.complete" in helper


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
        r'"-Language",\s+self\._update_helper_language\(\),',
        main,
    )
    # Installed and portable updates each launch the helper after downloading.
    assert len(language_arguments) == 2
    assert main.count("def _update_helper_language") == 1
    assert main.count('language in ("en", *i18n.SHIPPED_CATALOGS)') == 1
    assert main.count("updater.launch_update_helper(") == 2


def test_update_helper_uses_selected_messages_for_every_status():
    helper, _catalog = _update_helper_message_catalog()
    assert "Show-UpdateStatus -Message $firstMessage" in helper
    assert "-Message $updateMessages.prepare" in helper
    assert helper.count("-Message $updateMessages.install") == 2
    assert helper.count("-Message $updateMessages.start") == 2
    assert helper.count("-Message $updateMessages.error") == 1
    assert "-Message $updateMessages.consent" in helper
    assert '-Message "Installing the update.' not in helper
    assert '-Message "Starting the updated' not in helper
    assert '-Message "The update did not finish.' not in helper


def test_update_helper_elevation_prompt_is_owned_by_the_status_window():
    """Issue #26: a hidden helper's RunAs became a flashing taskbar button.

    The UAC request needs an owner window, or Windows does not put the consent
    prompt in front of the user, and the installer waits unseen for ever.
    """
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    assert "$psi.ErrorDialogParentHandle = $statusWindow.Handle" in helper
    assert "Start-Process -FilePath $InstallerPath" not in helper
    # A declined prompt (ERROR_CANCELLED) is reported, not left in silence.
    assert "NativeErrorCode -eq 1223" in helper
    # The wait for the installer is capped, and it leaves its own log.
    assert "-TimeoutSeconds 900" in helper
    assert "/LOG=" in helper


def test_update_helper_logs_before_anything_can_fail():
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    started = helper.index('Write-Log "Update helper started')
    assert started < helper.index("$UpdateMessagesJson = @'")
    assert started < helper.index("Show-UpdateStatus -Message")
    assert helper.index("function Write-Log") < started
    assert "trap {" in helper


def test_update_helper_failures_bring_the_app_back_or_say_so():
    """Every failure restarts the old app (which reports it) or shows a box."""
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    body = helper[helper.index("function Complete-FailedUpdate"):]
    body = body[:body.index("\nfunction ")]
    assert "Start-AppAfterUpdate -ExePath $oldExe" in body
    assert "MessageBox]::Show(" in body
    assert "$logPath" in body
    # The old ten-second error flash in an unfocusable window is gone.
    assert "Wait-Pumped -Milliseconds 10000" not in helper


def test_batch_launcher_is_gone():
    """cmd /c split a helper path with a space in it; nothing may use it."""
    assert not (ROOT / "update_helper.bat").exists()
    assert "update_helper.bat" not in (ROOT / "main.spec").read_text(encoding="utf-8")
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "update_helper.bat" not in main
    assert '"cmd",\n            "/d"' not in main



def test_inno_installer_restores_the_old_runtime_when_an_update_fails():
    """Issue #26: [InstallDelete] is never rolled back.

    An update that stopped on a file in use rolled back to an install with its
    whole _internal directory gone, and the app then died at start with "No
    module named '_socket'". The old runtime is moved aside instead and put
    back unless the install finished.
    """
    script = (ROOT / "installer" / "AccessibleIPTVClient.iss").read_text(encoding="utf-8")

    assert "\n[InstallDelete]" not in script
    assert 'Name: "{app}\\_internal"' not in script
    assert "procedure CurStepChanged(CurStep: TSetupStep);" in script
    assert "RenameFile(InternalDir(), InternalBackupDir)" in script
    assert "procedure DeinitializeSetup();" in script
    assert "RenameFile(InternalBackupDir, InternalDir())" in script
    assert "InstallFinished := True;" in script


def test_update_helper_records_why_an_update_failed():
    helper = (ROOT / "update_helper.ps1").read_text(encoding="utf-8")

    assert 'Join-Path $env:TEMP "AccessibleIPTVClient_update_result.json"' in helper
    assert "Write-UpdateResult -Kind $Kind" in helper
    assert '-Kind "declined"' in helper
    assert '-Kind "installer" -ExitCode $installerExit -InstallerLog $installerLog' in helper
    # Tests run -SelfTest; it must not touch a real result in the user's %TEMP%.
    assert helper.index("if ($SelfTest)") < helper.index("Remove-Item -LiteralPath $resultPath")


def test_update_helper_records_success_before_it_restarts_the_app():
    """The app reports the update milliseconds after it shows its window.

    Writing the result after the restart lost that race, and the new version
    then opened its own "successfully updated" box on top of the update's own
    window - the box this window exists to replace.
    """
    helper, _catalog = _update_helper_message_catalog()
    assert helper.count("Write-UpdateSuccess -Version $newVersion") == 2
    for start in ("Restarting app after installer update", "Restarting app: $exePath"):
        restart = helper.index(start)
        success = helper.rindex("Write-UpdateSuccess -Version $newVersion", 0, restart)
        between = helper[success:restart]
        assert "Start-AppAfterUpdate" not in between, start


def test_update_helper_reopens_the_focus_latch_when_the_update_needs_the_window():
    """Every moment the update becomes the user's task again resets it."""
    helper, _catalog = _update_helper_message_catalog()
    stages = re.findall(r'Reset-StatusFocusLatch -Stage "([^"]+)"', helper)
    assert "the install is starting" in stages
    assert "the update failed" in stages
    assert "the update was stopped" in stages
    assert "the update is complete" in stages


def test_a_finished_update_takes_its_window_away():
    """The update is over: nothing to read, nothing to dismiss, no window."""
    helper, _catalog = _update_helper_message_catalog()
    success = helper[helper.index("function Complete-SuccessfulUpdate"):
                     helper.index("function Complete-FailedUpdate")]
    # The restart-failed branch still waits to be dismissed; the success one
    # must not, and must hand the foreground to the app it has just started.
    finished = success[success.index("Reset-StatusFocusLatch -Stage \"the update is complete\""):]
    assert "Wait-ForDismissal" not in finished
    assert "Grant-ForegroundToNextProcess" in finished
    assert "Close-StatusWindow" in finished
    assert "$script:CompleteLingerMs" in finished
