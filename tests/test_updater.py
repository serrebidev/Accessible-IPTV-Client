import hashlib
import json
import os

import pytest

import updater


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


def test_fetch_latest_release_uses_supplied_timeout(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, timeout))
        return _Response({"tag_name": "v1.2.3"})

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)

    release = updater.fetch_latest_release("owner", "repo", timeout=4.5)

    assert release["tag_name"] == "v1.2.3"
    assert calls == [
        ("https://api.github.com/repos/owner/repo/releases/latest", 4.5)
    ]


def test_fetch_update_manifest_uses_supplied_timeout(monkeypatch):
    calls = []
    release = {
        "assets": [
            {
                "name": "manifest.json",
                "browser_download_url": "https://example.test/manifest.json",
            }
        ]
    }
    manifest_payload = {
        "version": "1.2.3",
        "asset_filename": "IPTVClient.zip",
        "download_url": "https://example.test/IPTVClient.zip",
        "sha256": "abc123",
    }

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, timeout))
        return _Response(manifest_payload)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)

    manifest = updater.fetch_update_manifest(
        release,
        "manifest.json",
        timeout=6.0,
    )

    assert manifest.version == "1.2.3"
    assert manifest.asset_filename == "IPTVClient.zip"
    assert calls == [("https://example.test/manifest.json", 6.0)]


def test_download_json_accepts_utf8_bom(monkeypatch):
    class BomResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"\xef\xbb\xbf{\"ok\": true}"

    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda req, timeout: BomResponse(),
    )

    assert updater.download_json("https://example.test/manifest.json") == {"ok": True}


class _DownloadResponse:
    """Minimal urlopen() stand-in that yields the payload in small chunks."""

    def __init__(self, data: bytes, chunk_size: int = 4, content_length: bool = True):
        self._data = data
        self._pos = 0
        self._chunk = chunk_size
        self.headers = {"Content-Length": str(len(data))} if content_length else {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        if self._pos >= len(self._data):
            return b""
        end = min(self._pos + self._chunk, len(self._data))
        chunk = self._data[self._pos:end]
        self._pos = end
        return chunk


def test_download_reports_progress_and_hashes(monkeypatch, tmp_path):
    payload = b"accessible-iptv-client update payload, streamed in small chunks"
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda req, timeout: _DownloadResponse(payload),
    )
    fractions = []

    def progress(fraction):
        fractions.append(fraction)
        return True

    dest = tmp_path / "update.zip"
    digest = updater.download_file_with_sha256(
        "https://example.test/update.zip", str(dest), progress_cb=progress
    )

    assert digest == hashlib.sha256(payload).hexdigest()
    assert dest.read_bytes() == payload
    assert fractions and fractions[-1] == 1.0
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert fractions == sorted(fractions)  # monotonic non-decreasing


def test_download_without_content_length_reports_none(monkeypatch, tmp_path):
    payload = b"no content-length header on this response"
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda req, timeout: _DownloadResponse(payload, content_length=False),
    )
    seen = []
    dest = tmp_path / "update.zip"
    updater.download_file_with_sha256(
        "https://example.test/update.zip", str(dest),
        progress_cb=lambda fraction: (seen.append(fraction), True)[1],
    )
    assert seen and all(f is None for f in seen)


def test_download_cancel_raises_update_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda req, timeout: _DownloadResponse(b"x" * 64, chunk_size=4),
    )
    dest = tmp_path / "update.zip"
    with pytest.raises(updater.UpdateCancelled):
        updater.download_file_with_sha256(
            "https://example.test/update.zip", str(dest),
            progress_cb=lambda fraction: False,
        )


def test_run_hidden_hides_console_on_windows(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return "result"

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    result = updater.run_hidden(["whoami"], capture_output=True)

    assert result == "result"
    assert captured["cmd"] == ["whoami"]
    if os.name == "nt":
        assert captured["kwargs"]["creationflags"] & updater._CREATE_NO_WINDOW
        assert captured["kwargs"]["startupinfo"] is not None
    else:
        assert "creationflags" not in captured["kwargs"]


def test_popen_hidden_detaches_stdio(monkeypatch):
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    updater.popen_hidden(["cmd", "/c", "echo", "hi"])

    assert captured["stdin"] == updater.subprocess.DEVNULL
    assert captured["stdout"] == updater.subprocess.DEVNULL
    assert captured["stderr"] == updater.subprocess.DEVNULL
    assert captured["close_fds"] is True


@pytest.mark.skipif(os.name != "nt", reason="window-hiding flags are Windows-only")
def test_popen_hidden_falls_back_without_breakaway(monkeypatch):
    attempts = []

    class _FakeProc:
        pass

    def fake_popen(cmd, **kwargs):
        flags = kwargs.get("creationflags", 0)
        attempts.append(flags)
        if flags & updater._CREATE_BREAKAWAY_FROM_JOB:
            raise OSError("breakaway from job not permitted")
        return _FakeProc()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    proc = updater.popen_hidden(["cmd", "/c", "echo", "hi"])

    assert isinstance(proc, _FakeProc)
    assert len(attempts) == 2
    assert attempts[0] & updater._CREATE_BREAKAWAY_FROM_JOB
    assert not (attempts[1] & updater._CREATE_BREAKAWAY_FROM_JOB)
    assert attempts[1] & updater._CREATE_NO_WINDOW
    assert attempts[1] & updater._CREATE_NEW_PROCESS_GROUP


def test_fetch_update_manifest_reads_installer_metadata(monkeypatch):
    release = {
        "assets": [
            {
                "name": "manifest.json",
                "browser_download_url": "https://example.test/manifest.json",
            }
        ]
    }
    manifest_payload = {
        "version": "1.2.3",
        "asset_filename": "AccessibleIPTVClient-v1.2.3.zip",
        "download_url": "https://example.test/AccessibleIPTVClient-v1.2.3.zip",
        "sha256": "a" * 64,
        "installer": {
            "asset": "AccessibleIPTVClient-Setup-v1.2.3.exe",
            "download_url": "https://example.test/AccessibleIPTVClient-Setup-v1.2.3.exe",
            "sha256": "b" * 64,
        },
    }

    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda req, timeout: _Response(manifest_payload),
    )

    manifest = updater.fetch_update_manifest(release, "manifest.json")

    assert manifest.installer_asset_filename == "AccessibleIPTVClient-Setup-v1.2.3.exe"
    assert manifest.installer_download_url == "https://example.test/AccessibleIPTVClient-Setup-v1.2.3.exe"


def test_the_manifest_cannot_pin_its_own_certificate(monkeypatch):
    """A release that declares its own signing certificate proves nothing.

    Whoever can publish a release can sign it with their own certificate and
    declare that certificate next to the file, so the pin has to come from
    outside the release. The environment override is such a pin, and it wins.
    """
    release = {
        "assets": [
            {
                "name": "manifest.json",
                "browser_download_url": "https://example.test/manifest.json",
            }
        ]
    }
    manifest_payload = {
        "version": "1.2.3",
        "asset_filename": "AccessibleIPTVClient-v1.2.3.zip",
        "download_url": "https://example.test/AccessibleIPTVClient-v1.2.3.zip",
        "sha256": "a" * 64,
        "signing_thumbprints": ["ATTACKER0000000000000000000000000000000000"],
    }
    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda req, timeout: _Response(manifest_payload),
    )
    monkeypatch.setenv("ACCESSIBLEIPTVCLIENT_TRUSTED_SIGNING_THUMBPRINTS",
                       "TRUSTED0000000000000000000000000000000000")

    manifest = updater.fetch_update_manifest(release, "manifest.json")

    assert manifest.signing_thumbprints == ("TRUSTED0000000000000000000000000000000000",)


def test_a_manifest_without_an_out_of_band_pin_is_only_a_last_resort(monkeypatch):
    """With no pin of its own the client falls back to the manifest's value.

    That is the source-run case (the application is not signed), so it is
    logged rather than silently accepted.
    """
    release = {
        "assets": [
            {
                "name": "manifest.json",
                "browser_download_url": "https://example.test/manifest.json",
            }
        ]
    }
    manifest_payload = {
        "version": "1.2.3",
        "asset_filename": "AccessibleIPTVClient-v1.2.3.zip",
        "download_url": "https://example.test/AccessibleIPTVClient-v1.2.3.zip",
        "sha256": "a" * 64,
        "signing_thumbprints": ["DECLARED000000000000000000000000000000000"],
    }
    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda req, timeout: _Response(manifest_payload),
    )
    monkeypatch.delenv("ACCESSIBLEIPTVCLIENT_TRUSTED_SIGNING_THUMBPRINTS", raising=False)
    monkeypatch.setattr(updater, "_running_app_thumbprint", lambda: "")

    manifest = updater.fetch_update_manifest(release, "manifest.json")

    assert manifest.signing_thumbprints == ("DECLARED000000000000000000000000000000000",)


def test_build_manifest_includes_optional_installer_metadata():
    manifest = updater.build_manifest(
        version="1.2.3",
        asset_filename="AccessibleIPTVClient-v1.2.3.zip",
        download_url="https://example.test/AccessibleIPTVClient-v1.2.3.zip",
        sha256="a" * 64,
        installer_asset_filename="AccessibleIPTVClient-Setup-v1.2.3.exe",
        installer_download_url="https://example.test/AccessibleIPTVClient-Setup-v1.2.3.exe",
        installer_sha256="b" * 64,
    )

    assert manifest["installer"] == {
        "asset": "AccessibleIPTVClient-Setup-v1.2.3.exe",
        "download_url": "https://example.test/AccessibleIPTVClient-Setup-v1.2.3.exe",
        "sha256": "b" * 64,
    }


# --------------------------------------------------------------------------- #
# "an update is being installed" marker
#
# The Windows installer deletes and rewrites the app's _internal directory, so
# an app opened by hand during the install dies with "Failed to load Python DLL
# ... python314.dll". The marker is how the next successful start reports what
# happened to the update that was running when we exited.
# --------------------------------------------------------------------------- #
def test_update_pending_marker_round_trip(tmp_path):
    directory = str(tmp_path / "config")
    assert updater.read_update_pending(directory) is None

    path = updater.write_update_pending(directory, "1.121.0")
    assert path and os.path.exists(path)

    pending = updater.read_update_pending(directory)
    assert pending["version"] == "1.121.0"
    assert pending["started"].endswith("Z")

    updater.clear_update_pending(directory)
    assert updater.read_update_pending(directory) is None


def test_update_pending_marker_survives_garbage(tmp_path):
    directory = str(tmp_path)
    with open(updater.update_pending_path(directory), "w", encoding="utf-8") as handle:
        handle.write("not json at all")
    assert updater.read_update_pending(directory) is None
    # Clearing something unreadable must not raise either.
    updater.clear_update_pending(directory)
    updater.clear_update_pending(directory)


# --------------------------------------------------------------------------- #
# Leftover update staging directories
#
# A successful update cannot delete its own mkdtemp directory (the helper runs
# from inside it), so the next start sweeps the old ones out of %TEMP%.
# --------------------------------------------------------------------------- #
def test_sweep_stale_update_dirs_removes_only_old_update_dirs(tmp_path):
    now = 1_000_000.0
    old = tmp_path / (updater.UPDATE_TEMP_PREFIX + "old")
    (old / "helper").mkdir(parents=True)
    (old / "helper" / "update_helper.ps1").write_text("x", encoding="utf-8")
    fresh = tmp_path / (updater.UPDATE_TEMP_PREFIX + "fresh")
    fresh.mkdir()
    unrelated = tmp_path / "iptv_remux_keep"
    unrelated.mkdir()
    stray_file = tmp_path / (updater.UPDATE_TEMP_PREFIX + "file")
    stray_file.write_text("x", encoding="utf-8")
    for path in (old, unrelated, stray_file):
        os.utime(path, (now - 7200, now - 7200))
    os.utime(fresh, (now - 60, now - 60))

    removed = updater.sweep_stale_update_dirs(str(tmp_path), max_age_seconds=3600, now=now)

    assert removed == 1
    assert not old.exists()
    # A helper may still be running from a recent one; never touch it.
    assert fresh.exists()
    assert unrelated.exists()
    assert stray_file.exists()


def test_sweep_stale_update_dirs_tolerates_missing_temp_dir(tmp_path):
    assert updater.sweep_stale_update_dirs(str(tmp_path / "missing")) == 0


def test_update_helper_command_runs_powershell_without_cmd(tmp_path):
    """Issue #26: `cmd /c "<path with space>" ...` never ran the helper."""
    helper = tmp_path / "has space" / "update_helper.ps1"
    cmd = updater.update_helper_command(str(helper), ["-InstallDir", r"C:\Program Files\X"])

    assert os.path.basename(cmd[0]).lower() == "powershell.exe"
    assert "cmd" not in [part.lower() for part in cmd]
    assert cmd[cmd.index("-File") + 1] == str(helper)
    assert cmd[-2:] == ["-InstallDir", r"C:\Program Files\X"]
    assert "-NoProfile" in cmd and "Bypass" in cmd


def test_clean_powershell_env_drops_module_paths(monkeypatch):
    monkeypatch.setenv("PSModulePath", r"C:\pwsh7\Modules")
    monkeypatch.setenv("KEEP_ME", "1")
    env = updater.clean_powershell_env()
    assert not any("PSMODULE" in key.upper() for key in env)
    assert env["KEEP_ME"] == "1"


def test_launch_update_helper_captures_powershell_output(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return "proc"

    monkeypatch.setattr(updater, "popen_hidden", fake_popen)
    helper = tmp_path / "helper" / "update_helper.ps1"
    assert updater.launch_update_helper(str(helper), ["-ExeName", "IPTVClient.exe"]) == "proc"

    assert captured["cwd"] == str(helper.parent)
    assert captured["stderr"] == updater.subprocess.STDOUT
    assert captured["stdout"].closed  # our copy is closed; the child has its own
    assert (tmp_path / updater.UPDATE_CONSOLE_LOG_NAME).exists()
    assert updater.update_log_path() == str(tmp_path / updater.UPDATE_LOG_NAME)


@pytest.mark.skipif(os.name != "nt", reason="foreground rights are Windows-only")
def test_allow_any_foreground_window_does_not_raise():
    updater.allow_any_foreground_window()


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_actually_starts_from_a_path_with_a_space(tmp_path):
    """End to end: the staged helper runs and writes its ready file."""
    import shutil
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    helper_dir = tmp_path / "user name" / "helper"
    helper_dir.mkdir(parents=True)
    helper = helper_dir / "update_helper.ps1"
    shutil.copy2(os.path.join(root, "update_helper.ps1"), helper)
    ready = helper_dir / "update_window_ready"
    missing = tmp_path / "missing"
    proc = subprocess.Popen(updater.update_helper_command(str(helper), [
        "-ParentPid", "999999",
        "-InstallDir", str(tmp_path / "no such install"),
        "-StagingDir", str(missing),
        "-BackupDir", str(tmp_path / "backup"),
        "-ExeName", "IPTVClient.exe",
        "-ReadyFile", str(ready),
        "-SelfTest",
    ]), env=updater.clean_powershell_env(), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output, _unused = proc.communicate(timeout=60)
    assert proc.returncode == 0, output
    assert ready.exists(), output



def test_update_result_round_trip(tmp_path):
    assert updater.read_update_result(str(tmp_path)) is None
    (tmp_path / updater.UPDATE_RESULT_NAME).write_text(
        '\ufeff{"status": "failed", "kind": "installer", "exit_code": 5}', encoding="utf-8")
    assert updater.read_update_result(str(tmp_path))["exit_code"] == 5
    updater.clear_update_result(str(tmp_path))
    updater.clear_update_result(str(tmp_path))
    assert updater.read_update_result(str(tmp_path)) is None


def test_update_result_survives_garbage(tmp_path):
    (tmp_path / updater.UPDATE_RESULT_NAME).write_text("not json", encoding="utf-8")
    assert updater.read_update_result(str(tmp_path)) is None


def test_describe_update_failure_names_the_cause():
    """Issue #26: "did not finish" alone gave nobody anything to act on."""
    assert updater.describe_update_failure(None) == ""
    assert "permission" in updater.describe_update_failure({"kind": "declined"})
    assert "could not be started" in updater.describe_update_failure({"kind": "launch"})
    assert "15 minutes" in updater.describe_update_failure({"kind": "timeout"})
    text = updater.describe_update_failure({
        "kind": "installer", "exit_code": 5,
        "installer_error": "DeleteFile failed; code 5. Access is denied.",
    })
    assert "exit code 5" in text
    assert "DeleteFile failed; code 5. Access is denied." in text
    # Portable-update failures carry only the helper's own English reason.
    assert updater.describe_update_failure(
        {"kind": "other", "reason": "Could not put the update in place."}
    ) == "Could not put the update in place."


def test_collect_update_logs_joins_every_log_and_trims_the_installer_log(tmp_path):
    assert updater.collect_update_logs(str(tmp_path)) == ""
    (tmp_path / updater.UPDATE_LOG_NAME).write_text("helper started\nUpdate failed", encoding="utf-8")
    (tmp_path / updater.UPDATE_RESULT_NAME).write_text('{"kind": "installer"}', encoding="utf-8")
    (tmp_path / updater.INSTALLER_LOG_NAME).write_text(
        "early line\n" + "x" * 5000 + "\nRolling back changes.", encoding="utf-8")

    logs = updater.collect_update_logs(str(tmp_path), max_chars=2000)
    assert len(logs) <= 2000
    assert "=== AccessibleIPTVClient_update.log ===\nhelper started\nUpdate failed" in logs
    assert '"kind": "installer"' in logs
    # The end of the installer log is where the failure is; its start goes.
    assert logs.endswith("Rolling back changes.")
    assert "early line" not in logs


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_extracts_the_installer_error(tmp_path):
    """The answer Inno gave itself in silent mode is what the user is told."""
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "update_helper.ps1"), encoding="ascii") as handle:
        helper = handle.read()
    function = helper[helper.index("function Get-InstallerError"):helper.index("function Write-UpdateResult")]
    log = tmp_path / "installer.log"
    log.write_text(
        "2026-09-18 08:31:49.945   DeleteFile: The existing file appears to be in use (5). Retrying.\n"
        "2026-09-18 08:31:50.959   Defaulting to Abort for suppressed message box (Abort/Retry/Ignore):\n"
        "                          C:\\Program Files\\AccessibleIPTVClient\\_internal\\python314.dll\n"
        "                          \n"
        "                          An error occurred while trying to replace the existing file:\n"
        "                          DeleteFile failed; code 5.\n"
        "2026-09-18 08:31:50.959   User canceled the installation process.\n",
        encoding="utf-8")
    script = tmp_path / "t.ps1"
    script.write_text(function + "\nGet-InstallerError -Path '" + str(log) + "'\n", encoding="utf-8-sig")
    out = subprocess.run(
        [updater.windows_powershell_path(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True, text=True, timeout=60, env=updater.clean_powershell_env())
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == (
        "Defaulting to Abort for suppressed message box (Abort/Retry/Ignore): "
        "C:\\Program Files\\AccessibleIPTVClient\\_internal\\python314.dll "
        "An error occurred while trying to replace the existing file: DeleteFile failed; code 5.")



def _run_helper_function(tmp_path, name, body):
    """Run one function from update_helper.ps1 with ``body`` appended."""
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "update_helper.ps1"), encoding="ascii") as handle:
        helper = handle.read()
    start = helper.index("function %s {" % name)
    end = helper.index("\n}\n", start) + 3
    script = tmp_path / "t.ps1"
    script.write_text(
        "function Write-Log { param([string]$Message) $script:logs += $Message }\n"
        "$script:logs = @()\n"
        + helper[start:end] + "\n" + body + "\n'FRAGMENT-OK'\n",
        encoding="utf-8-sig")
    out = subprocess.run(
        [updater.windows_powershell_path(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True, text=True, timeout=60, env=updater.clean_powershell_env())
    assert out.returncode == 0, out.stderr + out.stdout
    assert "FRAGMENT-OK" in out.stdout, out.stderr + out.stdout
    return out.stdout


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_the_rollback_puts_the_previous_version_back_over_a_partial_install(tmp_path):
    """A failed move can leave a half-written install directory behind.

    The backup is only restored when the install directory is gone, so the
    rollback has to remove the partial tree first - otherwise the app is left
    uninstalled and the working version sits in the .bak folder.
    """
    install = tmp_path / "app"
    backup = tmp_path / "app.bak"
    install.mkdir()
    (install / "half-written.dll").write_text("x", encoding="utf-8")
    backup.mkdir()
    (backup / "IPTVClient.exe").write_text("old", encoding="utf-8")

    out = _run_helper_function(
        tmp_path,
        "Restore-InstallBackup",
        "$ok = Restore-InstallBackup -BackupDir '%s' -InstallDir '%s'\n"
        "if (-not $ok) { throw 'rollback reported failure' }\n"
        "if (-not (Test-Path -LiteralPath (Join-Path '%s' 'IPTVClient.exe'))) "
        "{ throw 'the previous version was not restored' }\n"
        "if (Test-Path -LiteralPath (Join-Path '%s' 'half-written.dll')) "
        "{ throw 'the partial install was left behind' }"
        % (str(backup).replace("'", "''"), str(install).replace("'", "''"),
           str(install).replace("'", "''"), str(install).replace("'", "''")))

    assert "FRAGMENT-OK" in out


def _run_helper_fragment(tmp_path, body):
    """Run update_helper.ps1's status/focus functions with ``body`` appended."""
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "update_helper.ps1"), encoding="ascii") as handle:
        helper = handle.read()
    update_status = helper[helper.index("# The one window of the whole update"):helper.index("# --- Status window focus")]
    focus_block = helper[helper.index("# --- Status window focus"):helper.index("# Every failure ends here")]
    # The update's last word is said by this window too, so its function comes
    # along: the restarted app taking focus must not silence it.
    success_block = helper[helper.index("# The update worked."):helper.index("function Complete-FailedUpdate")]
    script = tmp_path / "t.ps1"
    script.write_text(
        "function Write-Log { param([string]$Message) $script:logs += $Message }\n"
        "$script:logs = @()\n"
        + update_status + "\n" + focus_block + "\n" + success_block + "\n"
        + body + "\n'FRAGMENT-OK'\n",
        encoding="utf-8-sig")
    out = subprocess.run(
        [updater.windows_powershell_path(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True, text=True, timeout=60, env=updater.clean_powershell_env())
    assert out.returncode == 0, out.stderr + out.stdout
    assert "FRAGMENT-OK" in out.stdout, out.stderr + out.stdout


# A fake foreground: focusing sets it, the test moves it, and each handle's
# owner is looked up in $kinds, so no real window ever takes focus.
_FAKE_FOCUS = (
    "$script:fg = [IntPtr]0\n"
    "$script:kinds = @{}\n"
    "function Get-ForegroundHandle { return $script:fg }\n"
    "function Invoke-ForceForeground { param([IntPtr]$Handle) $script:fg = $Handle; return $true }\n"
    "function Get-ForegroundOwnerKind { param([IntPtr]$Handle)\n"
    "    if ($Handle -eq $script:StatusWindowHandle) { return 'self' }\n"
    "    return $script:kinds[[int64]$Handle] }\n"
    "$script:activations = 0\n"
    "$label = New-Object PSObject -Property @{ Text = '' }\n"
    "$win = New-Object PSObject -Property @{ Text = ''; Handle = [IntPtr]7; IsDisposed = $false }\n"
    "$win | Add-Member ScriptMethod Refresh { }\n"
    "$win | Add-Member ScriptMethod Activate { $script:activations += 1 }\n"
    # The window and its label are held directly, not looked up by name:
    # $form.Controls["StatusLabel"] came back null on a user's machine and
    # froze the window on one message for the rest of the update (issue #31).
    "$script:StatusWindow = $win\n"
    "$script:StatusLabel = $label\n"
    "$script:StatusMessage = ''\n"
    "function Show-StatusWindowForReal { param([IntPtr]$Handle) }\n"
    "$script:kinds[[int64]100] = 'update'\n"
    "$script:kinds[[int64]200] = 'neutral'\n"
    "$script:kinds[[int64]300] = 'other'\n"
)


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_status_window_focus_rules(tmp_path):
    """Issue #30: re-focus once per stage, never steal it back after the user leaves."""
    _run_helper_fragment(tmp_path, _FAKE_FOCUS + (
        # A stage change sets the text and takes focus once.
        "Update-StatusMessage -Window $win -Message 'Installing the update.'\n"
        "if ($label.Text -ne 'Installing the update.') { throw 'label not set' }\n"
        "if (-not $win.Text.Contains('Installing the update.')) { throw 'title not set' }\n"
        "if ($script:activations -ne 1) { throw \"expected one focus grab, got $script:activations\" }\n"
        "if (-not $script:StatusFocusWatch) { throw 'focus watch not enabled' }\n"
        # Our own window holding the foreground is not 'leaving'.
        "Watch-StatusWindowFocus\n"
        "if ($script:UserLeftStatusWindow) { throw 'own foreground counted as leaving' }\n"
        # The user switches to another window: that latches, once.
        "$script:fg = [IntPtr]300\n"
        "Watch-StatusWindowFocus\n"
        "if (-not $script:UserLeftStatusWindow) { throw 'switching away was not noticed' }\n"
        # Later stages still update the text but never take focus back.
        "Update-StatusMessage -Window $win -Message 'Starting the updated application...'\n"
        "if (-not $label.Text.StartsWith('Starting')) { throw 'stage text not updated after user left' }\n"
        "if ($script:activations -ne 1) { throw 'focus was taken back after the user left' }\n"
    ))


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_repeats_neither_a_message_nor_its_focus_grab(tmp_path):
    """One grab per step: a repeated message must not re-read the window."""
    _run_helper_fragment(tmp_path, _FAKE_FOCUS + (
        "Update-StatusMessage -Window $win -Message 'Installing the update.'\n"
        "Update-StatusMessage -Window $win -Message 'Installing the update.'\n"
        "if ($script:activations -ne 1) { throw \"expected one grab, got $script:activations\" }\n"
    ))


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_announces_that_the_update_worked(tmp_path):
    """The restarted app taking focus must not silence the last message.

    The confirmation lives in this window now - the new version shows no box
    of its own - and the app that has just been started takes the foreground,
    which otherwise latches as "the user switched away".
    """
    _run_helper_fragment(tmp_path, _FAKE_FOCUS + (
        "Update-StatusMessage -Window $win -Message 'Starting the updated application...'\n"
        "$script:fg = [IntPtr]300\n"
        "Watch-StatusWindowFocus\n"
        "if (-not $script:UserLeftStatusWindow) { throw 'the app taking focus went unnoticed' }\n"
        "$before = $script:activations\n"
        "$updateMessages = [PSCustomObject]@{ complete = 'Update complete. Version {version} is starting.'; close = 'Close' }\n"
        "function Wait-Pumped { param([int]$Milliseconds, $Window) $script:waited = $Milliseconds }\n"
        "function Grant-ForegroundToNextProcess { $script:granted = $true }\n"
        "function Close-StatusWindow { param($Window) $script:closed = $true }\n"
        "function Set-StatusProgress { param($Percent) }\n"
        "function Set-StatusButton { param([string]$Action = '', [string]$Text = '') "
        "if ($Action) { throw \"a finished update offered a $Action button\" } }\n"
        "Complete-SuccessfulUpdate -Window $win -Restarted $true -Version '9.9.9'\n"
        "if (-not $script:granted) { throw 'the restarted app was not given the foreground' }\n"
        "if ($script:waited -gt 6000) { throw \"the window lingered $script:waited ms\" }\n"
        "if (-not $win.Text.Contains('v9.9.9')) { throw \"no version in: $($win.Text)\" }\n"
        "if ($script:activations -le $before) { throw 'the confirmation was never focused' }\n"
        "if (-not $script:closed) { throw 'the window was not closed afterwards' }\n"
    ))


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_takes_focus_back_from_the_silent_installer(tmp_path):
    """The installer's hidden window taking the foreground is not the user leaving.

    It used to latch as "the user left", so the status window was never
    brought back and NVDA stayed silent for the rest of the install.
    """
    _run_helper_fragment(tmp_path, _FAKE_FOCUS + (
        "Update-StatusMessage -Window $win -Message 'Installing the update.'\n"
        # The installer's hidden window steals the foreground: taken back.
        "$script:fg = [IntPtr]100\n"
        "Watch-StatusWindowFocus\n"
        "if ($script:UserLeftStatusWindow) { throw 'installer window counted as the user leaving' }\n"
        "if ($script:fg -ne $win.Handle) { throw 'focus not taken back from the installer' }\n"
        "if ($script:activations -ne 2) { throw \"expected a second grab, got $script:activations\" }\n"
        # The UAC prompt or the bare desktop: neither leaving nor grabbed.
        "$script:fg = [IntPtr]200\n"
        "Watch-StatusWindowFocus\n"
        "if ($script:UserLeftStatusWindow) { throw 'desktop counted as the user leaving' }\n"
        "if ($script:activations -ne 2) { throw 'focus grabbed from a neutral window' }\n"
        "$script:fg = [IntPtr]0\n"
        "Watch-StatusWindowFocus\n"
        "if ($script:UserLeftStatusWindow) { throw 'the secure desktop counted as leaving' }\n"
    ))


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_takes_focus_back_from_a_parked_shell_window(tmp_path):
    """Windows 11 parked the foreground on Explorer's ForegroundStaging window.

    Seen in a real installer update: it latched as "the user left" and NVDA
    stayed silent. A brief stop there (Alt+Tab) is left alone; one that stays
    is taken back.
    """
    _run_helper_fragment(tmp_path, _FAKE_FOCUS + (
        "$script:kinds[[int64]400] = 'transient'\n"
        "$script:TransientGraceMs = 300\n"
        "Update-StatusMessage -Window $win -Message 'Installing the update.'\n"
        "$script:fg = [IntPtr]400\n"
        "Watch-StatusWindowFocus\n"
        "if ($script:UserLeftStatusWindow) { throw 'shell window counted as the user leaving' }\n"
        "if ($script:activations -ne 1) { throw 'grabbed before the grace ended' }\n"
        "Start-Sleep -Milliseconds 400\n"
        "Watch-StatusWindowFocus\n"
        "if ($script:fg -ne $win.Handle) { throw 'focus not taken back from the parked shell window' }\n"
        # Passing through it on the way to another app: the user left, no grab.
        "$script:fg = [IntPtr]400\n"
        "Watch-StatusWindowFocus\n"
        "$script:fg = [IntPtr]300\n"
        "Watch-StatusWindowFocus\n"
        "Start-Sleep -Milliseconds 400\n"
        "Watch-StatusWindowFocus\n"
        "if (-not $script:UserLeftStatusWindow) { throw 'Alt+Tab to another app not noticed' }\n"
        "if ($script:activations -ne 2) { throw \"expected two grabs, got $script:activations\" }\n"
    ))


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_focus_is_not_watched_until_it_really_had_focus(tmp_path):
    """A failed first grab must not turn the next foreground into 'the user left'."""
    _run_helper_fragment(tmp_path, _FAKE_FOCUS + (
        "function Invoke-ForceForeground { param([IntPtr]$Handle) return $false }\n"
        "$script:fg = [IntPtr]300\n"
        "Focus-StatusWindow -Window $win -Stage 'application closed'\n"
        "if ($script:StatusFocusWatch) { throw 'watching without ever holding focus' }\n"
        "Watch-StatusWindowFocus\n"
        "if ($script:UserLeftStatusWindow) { throw 'latched without ever holding focus' }\n"
    ))


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_only_announces_a_uac_prompt_that_will_appear(tmp_path):
    """No "Windows will ask for permission" when UAC is off or elevates silently."""
    cases = [
        # (EnableLUA, ConsentPromptBehaviorAdmin, ConsentPromptBehaviorUser, elevation type, admin, expected)
        (1, 5, 3, 3, True, True),     # default UAC, administrator: prompt
        (1, 0, 3, 3, True, False),    # administrator, "elevate without prompting"
        (0, 5, 3, 1, True, False),    # UAC switched off
        (0, 5, 3, 1, False, True),    # UAC off, standard user: Run As dialog
        (1, 5, 3, 2, True, False),    # already elevated
        (1, 5, 3, 1, True, False),    # built-in Administrator, full token
        (1, 5, 3, 1, False, True),    # standard user: credentials prompt
        (1, 5, 0, 1, False, False),   # standard user, "deny without prompting"
        (None, None, None, 3, True, True),  # nothing readable: assume a prompt
    ]
    lines = []
    for lua, admin_b, user_b, kind, is_admin, expected in cases:
        props = []
        for name, value in (("EnableLUA", lua), ("ConsentPromptBehaviorAdmin", admin_b),
                            ("ConsentPromptBehaviorUser", user_b)):
            if value is not None:
                props.append(f"{name} = {value}")
        policy = "New-Object PSObject -Property @{ " + "; ".join(props) + " }" if props else "New-Object PSObject"
        lines.append(
            f"$r = Test-ElevationPromptExpected -Policy ({policy}) -ElevationType {kind} "
            f"-IsAdmin ${str(is_admin).lower()}\n"
            f"if ($r -ne ${str(expected).lower()}) {{ throw 'case {lua},{admin_b},{user_b},{kind},{is_admin}: got ' + $r }}\n")
    # And it runs against this machine's real policy without failing.
    lines.append("$null = Test-ElevationPromptExpected\n")
    _run_helper_fragment(tmp_path, "".join(lines))


class _SignatureResult:
    def __init__(self, status, thumbprint):
        self.returncode = 0
        self.stdout = json.dumps({"Status": status, "StatusMessage": "", "Thumbprint": thumbprint})
        self.stderr = ""


def _fake_signature(monkeypatch, status, thumbprint, commands=None):
    def run(cmd, **_kwargs):
        if commands is not None:
            commands.append(cmd)
        return _SignatureResult(status, thumbprint)

    monkeypatch.setattr(updater, "run_hidden", run)


def test_pinned_certificate_does_not_excuse_a_tampered_file(monkeypatch, tmp_path):
    _fake_signature(monkeypatch, "HashMismatch", "AB CD")
    with pytest.raises(updater.UpdateError):
        updater.verify_authenticode(str(tmp_path / "app.exe"), ["ABCD"])


def test_pinned_certificate_does_not_pass_an_unsigned_file(monkeypatch, tmp_path):
    _fake_signature(monkeypatch, "NotSigned", "ABCD")
    with pytest.raises(updater.UpdateError):
        updater.verify_authenticode(str(tmp_path / "app.exe"), ["ABCD"])


def test_pinned_self_signed_certificate_still_passes(monkeypatch, tmp_path):
    _fake_signature(monkeypatch, "UnknownError", "ABCD")
    updater.verify_authenticode(str(tmp_path / "app.exe"), ["ABCD"])


def test_authenticode_check_runs_powershell_without_cmd(monkeypatch, tmp_path):
    """Same trap as issue #26: cmd /c mangles a quoted path with a space."""
    commands = []
    _fake_signature(monkeypatch, "Valid", "ABCD", commands)
    updater.verify_authenticode(str(tmp_path / "has space" / "app.exe"), ["ABCD"])
    assert os.path.basename(commands[0][0]).lower() == "powershell.exe"
    assert "cmd" not in [part.lower() for part in commands[0]]


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_says_so_when_the_app_could_not_be_restarted(tmp_path):
    """An update nobody can see running is not a completed update.

    The install worked, but every restart attempt failed, so the window must
    say that rather than "Update complete", and it must not tell the app the
    update finished - nothing is running to read it anyway.
    """
    _run_helper_fragment(tmp_path, _FAKE_FOCUS + (
        "$updateMessages = [PSCustomObject]@{ complete = 'Update complete.'; "
        "restart = 'The update is installed, but the application could not be started.'; "
        "close = 'Close' }\n"
        "$script:wrote = 'nothing'\n"
        "function Write-UpdateSuccess { param([string]$Version) $script:wrote = $Version }\n"
        "function Wait-ForDismissal { param($Window, [int]$Milliseconds, [string]$ButtonText) }\n"
        "function Close-StatusWindow { param($Window) $script:closed = $true }\n"
        "function Set-StatusProgress { param($Percent) }\n"
        "Complete-SuccessfulUpdate -Window $win -Restarted $false -Version '9.9.9'\n"
        "if ($script:wrote -ne 'nothing') { throw 'a failed restart was recorded as success' }\n"
        "if (-not $label.Text.StartsWith('The update is installed')) "
        "{ throw \"wrong message: $($label.Text)\" }\n"
        "if (-not $script:closed) { throw 'the window was left behind' }\n"
    ))


@pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")
def test_update_helper_takes_the_window_back_when_the_update_needs_it(tmp_path):
    """The app is usable during the download now, so the latch has to reopen.

    Going back to the app while it downloads latches "the user switched
    away" - which is right for the download, and wrong from the moment the
    install starts: it used to leave NVDA with nothing for the whole install.
    """
    _run_helper_fragment(tmp_path, _FAKE_FOCUS + (
        "Update-StatusMessage -Window $win -Message 'Downloading the update...'\n"
        "$script:fg = [IntPtr]300\n"
        "Watch-StatusWindowFocus\n"
        "if (-not $script:UserLeftStatusWindow) { throw 'going back to the app went unnoticed' }\n"
        "$before = $script:activations\n"
        "Reset-StatusFocusLatch -Stage 'the install is starting'\n"
        "Update-StatusMessage -Window $win -Message 'Installing the update.'\n"
        "if ($script:UserLeftStatusWindow) { throw 'the latch was not reopened' }\n"
        "if ($script:activations -le $before) { throw 'the install was never announced' }\n"
    ))
