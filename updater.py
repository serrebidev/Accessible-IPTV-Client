import datetime
import hashlib
import json
import logging
import os
import re
import subprocess
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
    
    thumbprints = _normalize_thumbprints(env_thumbs + manifest_thumbs)
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
    except urllib.error.HTTPError as exc:
        raise UpdateError(_("Failed to download update ({code}).").format(code=exc.code)) from exc
    except urllib.error.URLError as exc:
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
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if filename.lower() == exe_name_lower:
                return os.path.join(dirpath, filename)
    return None


def verify_authenticode(exe_path: str, allowed_thumbprints: Iterable[str]) -> None:
    allowed = set(_normalize_thumbprints(allowed_thumbprints))
    LOG.debug("verify_authenticode: exe=%s, allowed_thumbprints=%s", exe_path, allowed)
    
    # Convert to absolute path and normalize 
    abs_path = os.path.abspath(exe_path)
    
    # Write the PowerShell script to a temp file to avoid module loading issues
    # when running from a frozen PyInstaller app or PowerShell Core environment
    import tempfile
    ps_script = f'''
$ErrorActionPreference = 'SilentlyContinue'
$sig = Get-AuthenticodeSignature -LiteralPath "{abs_path}"
$thumb = if ($sig.SignerCertificate) {{ $sig.SignerCertificate.Thumbprint }} else {{ "" }}
@{{Status=$sig.Status.ToString(); StatusMessage=$sig.StatusMessage; Thumbprint=$thumb}} | ConvertTo-Json -Compress
'''
    
    # Create temp script file
    script_fd, script_path = tempfile.mkstemp(suffix=".ps1")
    try:
        os.write(script_fd, ps_script.encode('utf-8'))
        os.close(script_fd)
        
        # Use cmd.exe to launch Windows PowerShell with a clean environment
        # This bypasses Python environment variables that can cause module loading issues
        # (e.g., PSMODULEPATH conflicts between pwsh 7 and Windows PowerShell 5.1)
        windows_ps = os.path.join(os.environ.get("SYSTEMROOT", "C:\\Windows"),
                                   "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if not os.path.exists(windows_ps):
            windows_ps = "powershell.exe"  # Fall back to PATH
        
        cmd = [
            "cmd", "/c", windows_ps,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-File", script_path,
        ]
        
        # Clean environment - remove PS-related vars that cause module conflicts
        clean_env = os.environ.copy()
        for k in list(clean_env.keys()):
            if 'PSMODULE' in k.upper() or 'POWERSHELL' in k.upper():
                del clean_env[k]
        
        result = run_hidden(cmd, capture_output=True, text=True, timeout=30, env=clean_env)
        
        LOG.debug("verify_authenticode: returncode=%s, stdout=%r, stderr=%r", 
                  result.returncode, result.stdout[:500] if result.stdout else None, 
                  result.stderr[:500] if result.stderr else None)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
    
    if result.returncode != 0:
        raise UpdateError(_("Authenticode verification failed: {detail}").format(
            detail=result.stderr.strip() or result.stdout.strip()))
    try:
        data = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise UpdateError(_("Authenticode verification returned invalid data.")) from exc

    status = str(data.get("Status") or "").strip()
    status_msg = str(data.get("StatusMessage") or "").strip()
    thumbprint = _normalize_thumbprint(data.get("Thumbprint"))
    
    LOG.debug("verify_authenticode: status=%s, thumbprint=%s", status, thumbprint)

    # Case 1: Signature is fully valid (trusted CA)
    if status.lower() == "valid":
        LOG.debug("verify_authenticode: PASS - status is Valid")
        return
    
    # Case 2: Self-signed or untrusted CA, but thumbprint matches allowed list
    # This handles UnknownError, NotTrusted, etc. when we have a pinned thumbprint
    if thumbprint and thumbprint in allowed:
        LOG.debug("verify_authenticode: PASS - thumbprint %s in allowed set", thumbprint)
        return
    
    # Case 3: No allowed thumbprints configured, but we have a signature - warn but allow
    # This provides backwards compatibility for releases without pinned thumbprints
    if thumbprint and not allowed:
        LOG.warning("verify_authenticode: No allowed thumbprints configured, allowing signed exe with thumbprint %s", thumbprint)
        return
    
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
