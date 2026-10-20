import datetime
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from i18n import gettext as _

LOG = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


class UpdateError(RuntimeError):
    pass


class UpdateCancelled(UpdateError):
    """Raised when the user cancels an in-progress update download."""


# --- Silent subprocess execution -------------------------------------------------
#
# The packaged app is built with console=False, so any console subprocess we spawn
# (powershell.exe, cmd.exe) would otherwise allocate and flash its own console
# window. These helpers mirror the BlindRSS updater: CREATE_NO_WINDOW plus an
# explicitly hidden STARTUPINFO, with stdio detached for fire-and-forget launches.

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
_CREATE_BREAKAWAY_FROM_JOB = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)


def _hidden_startupinfo():
    """A STARTUPINFO that hides the window, or None off Windows."""
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE
    return startupinfo


def _no_show_startupinfo():
    """A STARTUPINFO that says nothing about windows, or None off Windows.

    CREATE_NO_WINDOW already keeps a console off the screen, and SW_HIDE in
    STARTUPINFO is not only about the console: Windows applies it to the first
    top-level window the process shows. The update helper's status window is
    that window, so with _hidden_startupinfo it was created invisible and only
    appeared later, if something forced it to the foreground - which is why
    the update seemed to have no window at all while the app was still
    closing ("the update window disappears at Preparing the update").
    """
    if os.name != "nt":
        return None
    return subprocess.STARTUPINFO()


def run_hidden(cmd, **kwargs):
    """subprocess.run that never flashes a console window on Windows."""
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_NO_WINDOW
        kwargs.setdefault("startupinfo", _hidden_startupinfo())
    return subprocess.run(cmd, **kwargs)


def popen_hidden(cmd, **kwargs):
    """Launch a detached background process with no console window.

    stdio is detached so the helper outlives us cleanly. On Windows we also
    request CREATE_BREAKAWAY_FROM_JOB so the helper survives the parent exiting,
    falling back without it if an enclosing job object refuses.
    """
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    kwargs.setdefault("stdout", subprocess.DEVNULL)
    kwargs.setdefault("stderr", subprocess.DEVNULL)
    kwargs.setdefault("close_fds", True)
    if os.name != "nt":
        kwargs.setdefault("start_new_session", True)
        return subprocess.Popen(cmd, **kwargs)
    kwargs["startupinfo"] = kwargs.get("startupinfo") or _hidden_startupinfo()
    base_flags = kwargs.pop("creationflags", 0) | _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(cmd, creationflags=base_flags | _CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except OSError:
        return subprocess.Popen(cmd, creationflags=base_flags, **kwargs)


# --- starting update_helper.ps1 ---------------------------------------------

UPDATE_LOG_NAME = "AccessibleIPTVClient_update.log"
# PowerShell's own output (parse errors, a refused -File) lands here; the
# helper's step log above cannot record a helper that never ran.
UPDATE_CONSOLE_LOG_NAME = "AccessibleIPTVClient_update_console.log"


def update_log_path() -> str:
    return os.path.join(tempfile.gettempdir(), UPDATE_LOG_NAME)


# update_helper.ps1 writes why an update failed here, so the app can say it
# instead of only pointing at a log (issue #26).
UPDATE_RESULT_NAME = "AccessibleIPTVClient_update_result.json"
INSTALLER_LOG_NAME = "AccessibleIPTVClient_installer.log"
# A GitHub comment holds 65,536 characters; leave room for the user's words.
_UPDATE_LOGS_MAX_CHARS = 60000


def update_result_path(temp_dir: Optional[str] = None) -> str:
    return os.path.join(temp_dir or tempfile.gettempdir(), UPDATE_RESULT_NAME)


def read_update_result(temp_dir: Optional[str] = None) -> Optional[dict]:
    """The failure the helper recorded for the last update, if any."""
    try:
        with open(update_result_path(temp_dir), "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear_update_result(temp_dir: Optional[str] = None) -> None:
    try:
        os.remove(update_result_path(temp_dir))
    except OSError:
        LOG.debug("clear_update_result: nothing to remove", exc_info=True)


def describe_update_failure(result: Optional[dict]) -> str:
    """One or two translated sentences saying why the update did not install."""
    if not result:
        return ""
    kind = str(result.get("kind") or "")
    code = result.get("exit_code")
    if kind == "declined":
        text = _("Windows did not get permission to install the update.")
    elif kind == "launch":
        text = _("The installer could not be started.")
    elif kind == "timeout":
        text = _("The installer was still running after 15 minutes.")
    elif kind == "installer" and code is not None:
        text = _("The installer stopped with exit code {code}.").format(code=code)
    else:
        text = str(result.get("reason") or "").strip()
    detail = str(result.get("installer_error") or "").strip()
    if detail:
        text = (text + "\n" if text else "") + _("Installer message: {message}").format(message=detail)
    return text


def collect_update_logs(temp_dir: Optional[str] = None,
                        max_chars: int = _UPDATE_LOGS_MAX_CHARS) -> str:
    """The update logs as one block of text to paste into a bug report.

    The installer log is by far the longest and its end is what matters, so it
    is the one cut from the front when everything does not fit.
    """
    root = temp_dir or tempfile.gettempdir()
    parts = []
    for name in (UPDATE_LOG_NAME, UPDATE_CONSOLE_LOG_NAME, UPDATE_RESULT_NAME, INSTALLER_LOG_NAME):
        try:
            with open(os.path.join(root, name), "r", encoding="utf-8-sig", errors="replace") as handle:
                text = handle.read().strip()
        except OSError:
            continue
        if text:
            parts.append([name, text])
    if not parts:
        return ""

    def render() -> str:
        return "\n\n".join(f"=== {name} ===\n{text}" for name, text in parts)

    combined = render()
    overflow = len(combined) - max_chars
    if overflow > 0:
        longest = max(parts, key=lambda part: len(part[1]))
        longest[1] = "...\n" + longest[1][overflow + 4:]
        combined = render()
    return combined[-max_chars:]


def windows_powershell_path() -> str:
    """Windows PowerShell 5.1, which every supported Windows has, by full path."""
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR") or r"C:\Windows"
    path = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return path if os.path.exists(path) else "powershell.exe"


def clean_powershell_env() -> dict:
    """Our environment minus PowerShell 7's module paths.

    Windows PowerShell 5.1 inheriting pwsh 7's PSModulePath loads the wrong
    Microsoft.PowerShell.Management and loses Get-Process and friends.
    """
    env = os.environ.copy()
    for key in list(env):
        if "PSMODULE" in key.upper() or "POWERSHELL" in key.upper():
            del env[key]
    return env


def update_helper_command(helper_ps1: str, helper_args: Iterable[str]) -> list:
    """powershell.exe straight onto the helper, with no cmd.exe in between.

    The helper used to go through ``cmd /c update_helper.bat``. When the helper
    path had a space in it (a user profile named "First Last" puts one in
    %TEMP%), cmd stripped the quotes, ran "C:\\Users\\First", and the helper
    never started. Its error went to a detached stderr, so the app simply
    closed and nothing was installed (issue #26).
    """
    return [
        windows_powershell_path(),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden",
        "-File", helper_ps1,
        *[str(arg) for arg in helper_args],
    ]


def launch_update_helper(helper_ps1: str, helper_args: Iterable[str]) -> subprocess.Popen:
    """Start the detached update helper and return its process."""
    cmd = update_helper_command(helper_ps1, helper_args)
    LOG.info("Starting update helper: %s", subprocess.list2cmdline(cmd))
    console_path = os.path.join(tempfile.gettempdir(), UPDATE_CONSOLE_LOG_NAME)
    try:
        console = open(console_path, "wb")
    except OSError:
        LOG.debug("launch_update_helper: cannot open %s", console_path, exc_info=True)
        console = None
    try:
        return popen_hidden(
            cmd,
            # Not _hidden_startupinfo: this process owns the one window the
            # user sees for the whole update (see _no_show_startupinfo).
            startupinfo=_no_show_startupinfo(),
            cwd=os.path.dirname(helper_ps1) or None,
            env=clean_powershell_env(),
            stdout=console if console is not None else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if console is not None else subprocess.DEVNULL,
        )
    finally:
        if console is not None:
            console.close()


def allow_any_foreground_window() -> None:
    """Let the helper we are about to start take focus (ASFW_ANY).

    Only the foreground process may grant this, and a hidden background
    process without it cannot activate its window; its UAC request is also
    shown as a flashing taskbar button instead of the consent prompt.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        allow = ctypes.WinDLL("user32", use_last_error=True).AllowSetForegroundWindow
        allow.argtypes = [wintypes.DWORD]
        allow.restype = wintypes.BOOL
        if not allow(0xFFFFFFFF):
            LOG.debug("AllowSetForegroundWindow refused (error %s)", ctypes.get_last_error())
    except Exception:
        LOG.debug("allow_any_foreground_window failed", exc_info=True)


# --- "an update is being installed" marker ---------------------------------
#
# The Windows installer deletes and rewrites the app's ``_internal`` directory,
# so for the length of the install the executable on disk cannot start: it dies
# with "Failed to load Python DLL ... python314.dll". The app closes before the
# installer runs, so a user who reopens it by hand in that window walks straight
# into that error. The marker lets the next successful start say what happened,
# and it lives in the per-user config directory because the install directory is
# exactly what gets replaced.

UPDATE_PENDING_FILE = "update_pending.json"


# --- the update session: one window, driven by the app ----------------------
#
# update_helper.ps1 owns the only window the user sees from the moment they
# confirm an update until the new version is running. The app is alive for the
# first half of that (it does the downloading) and gone for the second, so the
# two talk through three files in the helper's own folder:
#
#   status.json   what the window should show right now (app -> helper)
#   command.json  what to install, or why there is nothing to install
#   cancel        the user pressed Cancel in the window (helper -> app)
#
# Every write is a rename into place, so the helper can never read half a file.
UPDATE_STATUS_FILE = "status.json"
UPDATE_COMMAND_FILE = "command.json"
UPDATE_CANCEL_FILE = "cancel"


def _write_json_atomically(path: str, payload: dict) -> bool:
    temporary = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temporary, path)
        return True
    except OSError:
        LOG.debug("_write_json_atomically: could not write %s", path, exc_info=True)
        try:
            os.remove(temporary)
        except OSError:
            LOG.debug("_write_json_atomically: no leftover to remove", exc_info=True)
        return False


def write_update_status(session_dir: str, message: str, percent=None,
                        cancellable: bool = False) -> bool:
    """Tell the status window what to say, and whether Cancel applies."""
    if not session_dir:
        return False
    payload = {
        "message": str(message or ""),
        "percent": None if percent is None else int(max(0, min(100, round(float(percent))))),
        "cancellable": bool(cancellable),
    }
    return _write_json_atomically(
        os.path.join(session_dir, UPDATE_STATUS_FILE), payload)


def write_update_command(session_dir: str, action: str, **fields) -> bool:
    """Hand the install over to the helper, or tell it there will be none."""
    if not session_dir:
        return False
    payload = {"action": str(action)}
    payload.update({key: value for key, value in fields.items() if value is not None})
    return _write_json_atomically(
        os.path.join(session_dir, UPDATE_COMMAND_FILE), payload)


def update_cancel_requested(session_dir: str) -> bool:
    """Whether the user pressed Cancel in the status window."""
    if not session_dir:
        return False
    return os.path.exists(os.path.join(session_dir, UPDATE_CANCEL_FILE))


def update_pending_path(directory: str) -> str:
    return os.path.join(directory or "", UPDATE_PENDING_FILE)


def write_update_pending(directory: str, version: str) -> Optional[str]:
    """Record that an update to ``version`` is being installed right now."""
    path = update_pending_path(directory)
    payload = {
        "version": str(version or ""),
        "started": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except OSError:
        LOG.debug("write_update_pending: could not write %s", path, exc_info=True)
        return None
    return path


def read_update_pending(directory: str) -> Optional[dict]:
    path = update_pending_path(directory)
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear_update_pending(directory: str) -> None:
    try:
        os.remove(update_pending_path(directory))
    except OSError:
        LOG.debug("clear_update_pending: nothing to remove", exc_info=True)


# --- leftover update staging directories -----------------------------------
#
# Every update downloads into a fresh mkdtemp("iptvclient_update_") directory.
# A failed or cancelled update deletes it, but a successful one cannot: the
# helper that finishes the install runs from inside it. At ~95 MB each they
# piled up in %TEMP% (25 of them, 2.4 GB, before this sweep existed). The next
# start removes any old enough that no helper or installer can still be using it.

UPDATE_TEMP_PREFIX = "iptvclient_update_"
STALE_UPDATE_DIR_SECONDS = 60 * 60


def sweep_stale_update_dirs(
    temp_dir: Optional[str] = None,
    max_age_seconds: float = STALE_UPDATE_DIR_SECONDS,
    now: Optional[float] = None,
) -> int:
    """Delete leftover update staging directories. Returns how many were removed."""
    root = temp_dir or tempfile.gettempdir()
    cutoff = (time.time() if now is None else now) - max_age_seconds
    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0
    removed = 0
    for entry in entries:
        if not entry.name.startswith(UPDATE_TEMP_PREFIX):
            continue
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.stat(follow_symlinks=False).st_mtime > cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(entry.path, ignore_errors=True)
        if os.path.exists(entry.path):
            LOG.debug("sweep_stale_update_dirs: could not fully remove %s", entry.path)
        else:
            removed += 1
    return removed


@dataclass
class UpdateManifest:
    version: str
    asset_filename: str
    download_url: str
    sha256: str
    published_date: str
    release_notes_summary: Optional[str] = None
    signing_thumbprints: Tuple[str, ...] = ()
    installer_asset_filename: Optional[str] = None
    installer_download_url: Optional[str] = None
    installer_sha256: Optional[str] = None


def parse_version(value: str) -> Optional[Tuple[int, int, int]]:
    if not value:
        return None
    match = _VERSION_RE.match(value.strip())
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return major, minor, patch


def normalize_version_tag(tag: str) -> Optional[str]:
    parsed = parse_version(tag)
    if not parsed:
        return None
    major, minor, patch = parsed
    return f"{major}.{minor}.{patch}"


def is_newer_version(current: str, latest: str) -> bool:
    cur = parse_version(current)
    new = parse_version(latest)
    if not cur or not new:
        return False
    return new > cur


def _build_request(url: str) -> urllib.request.Request:
    headers = {
        "User-Agent": "AccessibleIPTVClient-Updater",
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"token {token}"
    return urllib.request.Request(url, headers=headers)


def _normalize_thumbprint(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace(" ", "").strip().upper()


def _normalize_thumbprints(values: Iterable[str]) -> Tuple[str, ...]:
    normalized = {_normalize_thumbprint(value) for value in values if value}
    normalized.discard("")
    return tuple(sorted(normalized))


def _env_thumbprints() -> Tuple[str, ...]:
    raw = os.environ.get("ACCESSIBLEIPTVCLIENT_TRUSTED_SIGNING_THUMBPRINTS", "")
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


# Certificates this build trusts for the update installer. Add a thumbprint
# here when the signing certificate rotates: the running application was
# signed with the old one, and the next release has to be signed with the old
# one too, so the rotation is delivered by an update that already carries the
# new pin.
TRUSTED_SIGNING_THUMBPRINTS: Tuple[str, ...] = ()


def _running_app_thumbprint() -> str:
    """The certificate the running application was signed with.

    The installed application is what the user already trusts, so its own
    certificate is the pin for the next update. A release signed by anyone
    else is rejected. A source run (not frozen) has no signature and pins
    nothing.
    """
    if not getattr(sys, "frozen", False):
        return ""
    try:
        signature = _authenticode_signature(sys.executable)
    except Exception:
        LOG.debug("_running_app_thumbprint: could not read the signature", exc_info=True)
        return ""
    return _normalize_thumbprint(signature.get("Thumbprint"))


def _trusted_thumbprints() -> Tuple[str, ...]:
    """The thumbprints an update installer may be signed with.

    A pin that travels with the release proves nothing: whoever can publish
    a release can sign it with their own certificate and declare that
    certificate next to the file. Only a pin the client already trusts
    counts - the environment override, the certificate the running
    application was signed with, or the constant in this file.
    """
    pins = list(_env_thumbprints())
    pins.extend(TRUSTED_SIGNING_THUMBPRINTS)
    running = _running_app_thumbprint()
    if running:
        pins.append(running)
    return _normalize_thumbprints(pins)


def _extract_manifest_thumbprints(payload: dict) -> Tuple[str, ...]:
    raw = payload.get("signing_thumbprints") or payload.get("signing_thumbprint")
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if item)
    return ()


def _extract_installer_fields(payload: dict) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    installer = payload.get("installer")
    if not isinstance(installer, dict):
        return None, None, None
    filename = installer.get("asset") or installer.get("asset_name") or installer.get("asset_filename")
    download_url = installer.get("download_url")
    sha256 = installer.get("sha256")
    return (
        str(filename).strip() if filename else None,
        str(download_url).strip() if download_url else None,
        str(sha256).strip() if sha256 else None,
    )


def fetch_latest_release(owner: str, repo: str, *, timeout: float = 20.0) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    req = _build_request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8-sig")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0":
            raise UpdateError(_("GitHub API rate limit exceeded. Please try again later.")) from exc
        raise UpdateError(_("Failed to fetch release info ({code}).").format(code=exc.code)) from exc
    except urllib.error.URLError as exc:
        raise UpdateError(_("Unable to reach GitHub. Please check your connection.")) from exc


def fetch_update_manifest(
    release: dict,
    manifest_name: str,
    *,
    timeout: float = 20.0,
) -> UpdateManifest:
    assets = release.get("assets") or []
    manifest_asset = None
    for asset in assets:
        name = asset.get("name") or ""
        if name.lower() == manifest_name.lower():
            manifest_asset = asset
            break
    if not manifest_asset:
        raise UpdateError(_("Update manifest was not found in the latest release."))

    url = manifest_asset.get("browser_download_url") or ""
    if not url:
        raise UpdateError(_("Update manifest download URL is missing."))

    data = download_json(url, timeout=timeout)
    LOG.debug("fetch_update_manifest: raw data=%s", data)
    
    env_thumbs = list(_env_thumbprints())
    manifest_thumbs = list(_extract_manifest_thumbprints(data))
    LOG.debug("fetch_update_manifest: env_thumbprints=%s, manifest_thumbprints=%s", env_thumbs, manifest_thumbs)

    # The manifest is an unsigned HTTPS asset, so a thumbprint it declares is
    # only as trustworthy as the sha256 next to it: whoever can publish a
    # release can sign it with their own certificate and declare that
    # certificate. The pin therefore has to come from outside the release -
    # the environment override, the certificate the running application was
    # signed with, or the constant in updater.py. The manifest's own value is
    # only a last resort, for a source run with no signature at all, and that
    # case is logged.
    thumbprints = _trusted_thumbprints()
    if not thumbprints:
        thumbprints = _normalize_thumbprints(manifest_thumbs)
        if thumbprints:
            LOG.warning("No out-of-band signing pin is available: falling back to the "
                        "thumbprint the update manifest declares for itself.")
    LOG.debug("fetch_update_manifest: normalized thumbprints=%s", thumbprints)
    
    installer_asset, installer_url, installer_sha = _extract_installer_fields(data)
    try:
        manifest = UpdateManifest(
            version=str(data["version"]),
            asset_filename=str(data["asset_filename"]),
            download_url=str(data["download_url"]),
            sha256=str(data["sha256"]),
            published_date=str(data.get("published_date", "")),
            release_notes_summary=data.get("release_notes_summary"),
            signing_thumbprints=thumbprints,
            installer_asset_filename=installer_asset,
            installer_download_url=installer_url,
            installer_sha256=installer_sha,
        )
        LOG.debug("fetch_update_manifest: created manifest with signing_thumbprints=%s", manifest.signing_thumbprints)
        return manifest
    except KeyError as exc:
        raise UpdateError(_("Update manifest is missing required fields.")) from exc


def download_json(url: str, *, timeout: float = 20.0) -> dict:
    req = _build_request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8-sig")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        raise UpdateError(_("Failed to download manifest ({code}).").format(code=exc.code)) from exc
    except urllib.error.URLError as exc:
        raise UpdateError(_("Unable to download manifest. Please check your connection.")) from exc


def download_file_with_sha256(url: str, dest_path: str, *, progress_cb=None) -> str:
    """Download ``url`` to ``dest_path`` and return its SHA-256 hex digest.

    If ``progress_cb`` is given it is called as ``progress_cb(fraction)`` where
    fraction is 0.0-1.0 (or None when the server sends no Content-Length). If it
    returns False the download is aborted with :class:`UpdateCancelled`.
    """
    req = _build_request(url)
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, "wb") as handle:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            downloaded = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if progress_cb is not None:
                    fraction = (downloaded / total) if total > 0 else None
                    if progress_cb(fraction) is False:
                        raise UpdateCancelled(_("Update cancelled."))
    except UpdateCancelled:
        raise
    except urllib.error.HTTPError as exc:
        raise UpdateError(_("Failed to download update ({code}).").format(code=exc.code)) from exc
    except urllib.error.URLError as exc:
        raise UpdateError(_("Unable to download update. Please check your connection.")) from exc
    except OSError as exc:
        raise UpdateError(_("Unable to download update. Please check your connection.")) from exc
    return digest.hexdigest()


def safe_extract_zip(zip_path: str, dest_dir: str) -> None:
    os.makedirs(dest_dir, exist_ok=True)
    base_path = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            target_path = os.path.abspath(os.path.join(dest_dir, member.filename))
            if not target_path.startswith(base_path + os.sep) and target_path != base_path:
                raise UpdateError(_("Update package contains an unsafe file path."))
        zf.extractall(dest_dir)


def find_executable(root: str, exe_name: str) -> Optional[str]:
    exe_name_lower = exe_name.lower()
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if filename.lower() == exe_name_lower:
                return os.path.join(dirpath, filename)
    return None


# Get-AuthenticodeSignature statuses a pinned certificate may pass with: a
# trusted chain, or a chain ending in a root this machine does not trust.
_PIN_ACCEPTED_STATUSES = frozenset({"valid", "unknownerror", "nottrusted"})


def _authenticode_signature(exe_path: str) -> dict:
    """The Authenticode signature of a file.

    Returns the Status, StatusMessage and SignerCertificate thumbprint.
    """
    # Write the PowerShell script to a temp file to avoid module loading issues
    # when running from a frozen PyInstaller app or PowerShell Core environment
    import tempfile
    abs_path = os.path.abspath(exe_path)
    escaped_path = abs_path.replace("'", "''")
    ps_script = f'''
$ErrorActionPreference = 'SilentlyContinue'
$sig = Get-AuthenticodeSignature -LiteralPath '{escaped_path}'
$thumb = if ($sig.SignerCertificate) {{ $sig.SignerCertificate.Thumbprint }} else {{ "" }}
@{{Status=$sig.Status.ToString(); StatusMessage=$sig.StatusMessage; Thumbprint=$thumb}} | ConvertTo-Json -Compress
'''

    # Create temp script file (UTF-8 with BOM so Windows PowerShell 5.1 reads it
    # correctly even when the path contains non-ASCII characters).
    script_fd, script_path = tempfile.mkstemp(suffix=".ps1")
    try:
        os.write(script_fd, ps_script.encode('utf-8-sig'))
        os.close(script_fd)

        # Windows PowerShell 5.1 straight, never through cmd.exe: cmd mangles a
        # quoted path with a space in it (issue #26), and %TEMP% has one for a
        # user profile named "First Last". The environment is cleaned of pwsh
        # 7's module paths, which break 5.1's own modules.
        cmd = [
            windows_powershell_path(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-File", script_path,
        ]

        try:
            result = run_hidden(cmd, capture_output=True, text=True, errors="replace",
                                timeout=30, env=clean_powershell_env())
        except subprocess.TimeoutExpired as exc:
            raise UpdateError(_("Authenticode verification timed out.")) from exc
        except OSError as exc:
            raise UpdateError(_("Could not run Authenticode verification: {detail}").format(detail=exc)) from exc

        LOG.debug("verify_authenticode: returncode=%s, stdout=%r, stderr=%r",
                  result.returncode, result.stdout[:500] if result.stdout else None,
                  result.stderr[:500] if result.stderr else None)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            LOG.debug("verify_authenticode: ignored exception", exc_info=True)

    if result.returncode != 0:
        raise UpdateError(_("Authenticode verification failed: {detail}").format(
            detail=result.stderr.strip() or result.stdout.strip()))
    try:
        return json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise UpdateError(_("Authenticode verification returned invalid data.")) from exc


def verify_authenticode(exe_path: str, allowed_thumbprints: Iterable[str]) -> None:
    allowed = set(_normalize_thumbprints(allowed_thumbprints))
    LOG.debug("verify_authenticode: exe=%s, allowed_thumbprints=%s", exe_path, allowed)

    # Convert to absolute path and normalize 
    abs_path = os.path.abspath(exe_path)
    data = _authenticode_signature(abs_path)

    status = str(data.get("Status") or "").strip()
    status_msg = str(data.get("StatusMessage") or "").strip()
    thumbprint = _normalize_thumbprint(data.get("Thumbprint"))
    
    LOG.debug("verify_authenticode: status=%s, thumbprint=%s", status, thumbprint)

    # A pinned thumbprint overrides only the CA's trust assessment (self-signed
    # or not-yet-trusted certificates). It never excuses a file whose contents
    # no longer match its signature (HashMismatch) or that is not signed.
    if thumbprint and thumbprint in allowed and status.lower() in _PIN_ACCEPTED_STATUSES:
        LOG.debug("verify_authenticode: PASS - thumbprint %s in allowed set", thumbprint)
        return

    # No pin configured: a fully CA-trusted ("Valid") signature is the best
    # signal available. This is the standard Windows trust model.
    if not allowed and status.lower() == "valid":
        LOG.debug("verify_authenticode: PASS - no pin configured and signature is Valid")
        return

    # Everything else fails. A "Valid" signature from a certificate that is not
    # in the pinned set, or any non-Valid signature with no matching pin, is
    # rejected rather than silently allowed.
    
    # Verification failed - build detailed error message
    detail = _("Authenticode status was {status}.").format(status=status or _("Unknown"))
    if status_msg:
        detail = f"{detail} {status_msg}"
    if thumbprint:
        detail = detail + " " + _("(thumbprint {thumbprint}).").format(thumbprint=thumbprint)
    if allowed:
        detail = detail + " " + _("Expected thumbprints: {thumbprints}.").format(
            thumbprints=", ".join(sorted(allowed)))
    raise UpdateError(detail)


def summarize_release_notes(notes: str, max_lines: int = 6, max_chars: int = 600) -> str:
    if not notes:
        return "No release notes provided."
    lines = [line.strip() for line in notes.splitlines() if line.strip()]
    summary = "\n".join(lines[:max_lines])
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."
    return summary


def build_manifest(
    version: str,
    asset_filename: str,
    download_url: str,
    sha256: str,
    release_notes_summary: Optional[str] = None,
    signing_thumbprint: Optional[str] = None,
    installer_asset_filename: Optional[str] = None,
    installer_download_url: Optional[str] = None,
    installer_sha256: Optional[str] = None,
) -> dict:
    published = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = {
        "version": version,
        "asset_filename": asset_filename,
        "download_url": download_url,
        "sha256": sha256,
        "published_date": published,
        "release_notes_summary": release_notes_summary,
    }
    if signing_thumbprint:
        manifest["signing_thumbprint"] = signing_thumbprint
    if installer_asset_filename and installer_download_url and installer_sha256:
        manifest["installer"] = {
            "asset": installer_asset_filename,
            "download_url": installer_download_url,
            "sha256": installer_sha256,
        }
    return manifest
