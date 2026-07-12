import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

import app_meta  # noqa: E402
import updater  # noqa: E402

DEFAULT_SIGNTOOL = r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"
FFMPEG_NAME = "ffmpeg.exe"
BUNDLED_CONFIG_NAME = "iptvclient.conf"
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
INSTALLER_SCRIPT = os.path.join(REPO_ROOT, "installer", "AccessibleIPTVClient.iss")
CHANGELOG_PATH = os.path.join(REPO_ROOT, "CHANGELOG.md")


def run(cmd, cwd=REPO_ROOT, check=True, capture_output=False):
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def git(*args, capture_output=True):
    result = run(["git", *args], capture_output=capture_output)
    return (result.stdout or "").strip()


def parse_version_tag(tag):
    return updater.parse_version(tag)


def find_last_version_tag():
    tag = ""
    try:
        tag = git("describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        tag = ""
    if tag and parse_version_tag(tag):
        return tag

    try:
        tags = git(
            "for-each-ref",
            "--merged",
            "HEAD",
            "--sort=-creatordate",
            "--format=%(refname:short)",
            "refs/tags",
        ).splitlines()
    except subprocess.CalledProcessError:
        tags = []

    for candidate in tags:
        if parse_version_tag(candidate):
            return candidate
    return None


def get_commits_since(tag):
    range_ref = f"{tag}..HEAD" if tag else "HEAD"
    raw = git(
        "log",
        range_ref,
        "--pretty=format:%s%n%b%x1e",
    )
    commits = []
    for entry in raw.split("\x1e"):
        entry = entry.strip()
        if not entry:
            continue
        lines = entry.splitlines()
        subject = lines[0].strip() if lines else ""
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        commits.append({"subject": subject, "body": body})
    return commits


def classify_commit(commit):
    subject = commit["subject"]
    body = commit["body"]
    text = f"{subject}\n{body}".lower()
    if "breaking change" in text or re.search(r"^[a-z]+\!:", subject.lower()):
        return "Breaking"
    if subject.lower().startswith("feat") or "feature" in text:
        return "Features"
    if subject.lower().startswith("fix") or "fix" in text or "bug" in text:
        return "Fixes"
    return "Other"


def summarize_commits(commits):
    sections = {"Breaking": [], "Features": [], "Fixes": [], "Other": []}
    for commit in commits:
        subject = commit["subject"]
        if not subject or subject.lower().startswith("merge"):
            continue
        sections[classify_commit(commit)].append(subject)
    return sections


def build_release_notes(commits):
    sections = summarize_commits(commits)
    output = []
    for title in ("Breaking", "Features", "Fixes", "Other"):
        items = sections[title]
        if not items:
            continue
        output.append(f"## {title}")
        output.extend([f"- {item}" for item in items])
        output.append("")
    return "\n".join(output).strip() or "## Other\n- No notable changes."


def _changelog_item(text):
    """Turn a conventional-commit subject into a readable changelog bullet."""
    item = (text or "").strip()
    item = re.sub(r"^(?:feat|fix|perf|docs|test|chore|build|ci)(?:\([^)]+\))?!?:\s*", "", item, flags=re.I)
    if not item:
        return ""
    return item[0].upper() + item[1:]


def _changelog_items(release_notes):
    items = []
    for line in (release_notes or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        item = _changelog_item(line)
        if item:
            items.append(item)
    return items or ["No notable changes."]


def _changelog_header():
    return (
        "# Changelog\n\n"
        "Readable release history for Accessible IPTV Client. New entries are "
        "prepended automatically by `build.bat release`. Older entries were "
        "reconstructed from the [Forgejo mirror](https://git.serrebiradio.com/"
        "serrebi/Accessible-IPTV-Client).\n"
    )


def update_changelog(version, release_notes, release_date=None, path=None):
    """Prepend a release entry and refuse to overwrite an existing version."""
    path = path or CHANGELOG_PATH
    release_date = release_date or time.strftime("%Y-%m-%d")
    entry_heading = f"## v{version} - {release_date}"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            existing = handle.read()
    else:
        existing = _changelog_header()

    if entry_heading in existing or re.search(rf"^## v{re.escape(str(version))}\b", existing, re.M):
        raise RuntimeError(f"CHANGELOG.md already contains v{version}.")

    header = _changelog_header()
    if not existing.startswith("# Changelog\n"):
        raise RuntimeError("CHANGELOG.md must begin with '# Changelog'.")
    body = existing[len(header):] if existing.startswith(header) else existing.split("\n", 1)[1].lstrip("\n")
    lines = [entry_heading, ""]
    lines.extend(f"- {item}" for item in _changelog_items(release_notes))
    entry = "\n".join(lines) + "\n\n"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(header + entry + body)


def determine_bump(commits):
    sections = summarize_commits(commits)
    if sections["Breaking"]:
        return "major"
    if sections["Features"]:
        return "minor"
    return "patch"


def bump_version(base, bump):
    major, minor, patch = base
    if bump == "major":
        return major + 1, 0, 0
    if bump == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def format_version(version_tuple):
    return f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"


def update_version_file(new_version):
    path = os.path.join(REPO_ROOT, "app_meta.py")
    with open(path, "r", encoding="utf-8") as handle:
        data = handle.read()
    current = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', data)
    if current and current.group(1) == str(new_version):
        return
    updated = re.sub(
        r'APP_VERSION\s*=\s*"[^\"]+"',
        f'APP_VERSION = "{new_version}"',
        data,
    )
    if data == updated:
        raise RuntimeError("Failed to update APP_VERSION in app_meta.py.")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(updated)


def _remove_tree(path: str) -> None:
    if not os.path.isdir(path):
        return

    if os.name == "nt":
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Remove-Item -LiteralPath $args[0] -Recurse -Force -ErrorAction Stop",
            path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and not os.path.exists(path):
            return

    def _on_error(func, failed_path, _exc_info):
        try:
            os.chmod(failed_path, stat.S_IWRITE)
        except Exception:
            pass
        func(failed_path)

    shutil.rmtree(path, onerror=_on_error)


def clean_build_artifacts():
    for folder in ("build", "dist"):
        path = os.path.join(REPO_ROOT, folder)
        _remove_tree(path)


def _is_elevated_windows_token():
    if os.name != "nt":
        return False
    try:
        import ctypes

        advapi32 = ctypes.CDLL("Advapi32.dll")
        kernel32 = ctypes.CDLL("kernel32.dll")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        token = ctypes.c_void_p()
        TOKEN_QUERY = 8
        process = ctypes.c_void_p(kernel32.GetCurrentProcess())
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return False
        try:
            elevation_type = ctypes.c_int()
            TokenElevationType = 18
            ok = advapi32.GetTokenInformation(
                token,
                TokenElevationType,
                ctypes.byref(elevation_type),
                ctypes.sizeof(elevation_type),
                ctypes.byref(ctypes.c_int()),
            )
            return bool(ok and elevation_type.value == 2)
        finally:
            kernel32.CloseHandle(token)
    except Exception:
        return False


def _run_pyinstaller_limited():
    task_name = f"AccessibleIPTVClientPyInstaller_{os.getpid()}"
    temp_root = os.path.join(REPO_ROOT, ".build-tasks")
    temp_dir = os.path.join(temp_root, f"pyinstaller-{os.getpid()}-{int(time.time())}")
    os.makedirs(temp_dir, exist_ok=False)
    try:
        stdout_path = os.path.join(temp_dir, "pyinstaller.stdout.log")
        stderr_path = os.path.join(temp_dir, "pyinstaller.stderr.log")
        code_path = os.path.join(temp_dir, "pyinstaller.exitcode")
        batch_path = os.path.join(temp_dir, "run_pyinstaller.bat")
        with open(batch_path, "w", encoding="utf-8", newline="\r\n") as handle:
            handle.write("@echo off\n")
            handle.write(f'cd /d "{REPO_ROOT}"\n')
            handle.write("if errorlevel 1 exit /b %errorlevel%\n")
            handle.write(
                f'"{sys.executable}" -m PyInstaller --noconfirm main.spec '
                f'> "{stdout_path}" 2> "{stderr_path}"\n'
            )
            handle.write("set \"RC=%ERRORLEVEL%\"\n")
            handle.write(f'> "{code_path}" echo %RC%\n')
            handle.write("exit /b %RC%\n")

        task_command = f'"{batch_path}"'
        start_time = time.strftime("%H:%M", time.localtime(time.time() + 60))
        run(
            [
                "schtasks",
                "/Create",
                "/TN",
                task_name,
                "/SC",
                "ONCE",
                "/ST",
                start_time,
                "/TR",
                task_command,
                "/RL",
                "LIMITED",
                "/F",
            ],
            capture_output=True,
        )
        try:
            run(["schtasks", "/Run", "/TN", task_name], capture_output=True)
            deadline = time.time() + 1200
            while not os.path.exists(code_path):
                if time.time() > deadline:
                    raise RuntimeError("Timed out waiting for limited PyInstaller task to finish.")
                time.sleep(1)

            stdout = _read_text_file(stdout_path)
            stderr = _read_text_file(stderr_path)
            if stdout:
                sys.stdout.write(stdout)
                sys.stdout.flush()
            if stderr:
                sys.stderr.write(stderr)
                sys.stderr.flush()

            with open(code_path, "r", encoding="utf-8", errors="replace") as handle:
                returncode = int((handle.read() or "1").strip())
            if returncode != 0:
                raise subprocess.CalledProcessError(returncode, [sys.executable, "-m", "PyInstaller", "--noconfirm", "main.spec"])
        finally:
            run(["schtasks", "/Delete", "/TN", task_name, "/F"], check=False, capture_output=True)
    finally:
        _remove_tree(temp_dir)
        try:
            os.rmdir(temp_root)
        except OSError:
            pass


def _read_text_file(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def sync_translations():
    """Keep every translation catalogue in step with the source before building.

    Re-extracts the message template from source, merges new strings into each
    ``locale/<lang>/LC_MESSAGES/*.po`` (preserving existing translations), and
    compiles every catalogue to ``.mo`` so the build always bundles up-to-date
    translations. New source strings that lack a translation fall back to
    English until a translator fills them in.
    """
    import i18n_tools

    print("Syncing translation catalogues...")
    messages = i18n_tools.cmd_extract()
    i18n_tools.cmd_update(messages)
    i18n_tools.cmd_compile()


def run_pyinstaller():
    if _is_elevated_windows_token():
        _run_pyinstaller_limited()
        return
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "main.spec"])


def is_git_lfs_pointer(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


def validate_ffmpeg_binary(path=None):
    path = path or os.path.join(REPO_ROOT, FFMPEG_NAME)
    label = os.path.relpath(path, REPO_ROOT)
    if not os.path.isfile(path):
        raise RuntimeError(f"{label} was not found; the build cannot include FFmpeg.")

    size = os.path.getsize(path)
    if is_git_lfs_pointer(path):
        raise RuntimeError(
            f"{label} is a Git LFS pointer, not a runnable FFmpeg binary. "
            "Run: git lfs pull --include=ffmpeg.exe"
        )
    if size < 1024 * 1024:
        raise RuntimeError(
            f"{label} is unexpectedly small ({size} bytes); refusing to ship a broken FFmpeg binary."
        )

    kwargs = {
        "cwd": REPO_ROOT,
        "check": False,
        "capture_output": True,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run([path, "-version"], **kwargs)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{label} failed to execute as FFmpeg: {detail}")

    first_line = (result.stdout or result.stderr or "").splitlines()
    if not first_line or "ffmpeg version" not in first_line[0].lower():
        raise RuntimeError(f"{label} did not report an FFmpeg version.")


def validate_no_bundled_config(dist_dir=None):
    dist_dir = dist_dir or os.path.join(REPO_ROOT, "dist", "iptvclient")
    if not os.path.isdir(dist_dir):
        return
    matches = []
    for root, _, files in os.walk(dist_dir):
        for filename in files:
            if filename.lower() == BUNDLED_CONFIG_NAME:
                matches.append(os.path.relpath(os.path.join(root, filename), REPO_ROOT))
    if matches:
        raise RuntimeError(
            "Refusing to ship a bundled iptvclient.conf. Remove it from PyInstaller datas: "
            + ", ".join(matches)
        )


def sign_executable(exe_path):
    signtool = os.environ.get("SIGNTOOL_PATH", DEFAULT_SIGNTOOL)
    if not os.path.exists(signtool):
        raise RuntimeError(f"signtool.exe not found at: {signtool}")
    run(
        [
            signtool,
            "sign",
            "/fd",
            "SHA256",
            "/tr",
            "http://timestamp.digicert.com",
            "/td",
            "SHA256",
            "/a",
            exe_path,
        ]
    )


def get_signing_thumbprint(exe_path):
    override = os.environ.get("SIGN_CERT_THUMBPRINT", "").strip()
    if override:
        return override

    powershell = "powershell"
    clean_env = os.environ.copy()
    if os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        candidate = os.path.join(
            system_root,
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )
        if os.path.exists(candidate):
            powershell = candidate
        for key in list(clean_env.keys()):
            upper = key.upper()
            if "PSMODULE" in upper or "POWERSHELL" in upper:
                clean_env.pop(key, None)
        clean_env["PSModulePath"] = os.path.join(
            system_root,
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "Modules",
        )

    literal_path = os.path.abspath(exe_path).replace("'", "''")
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                "$ErrorActionPreference = 'Stop'; "
                f"$sig = Get-AuthenticodeSignature -LiteralPath '{literal_path}'; "
                "if (-not $sig.SignerCertificate) { throw 'No signer certificate found.' }; "
                "$sig.SignerCertificate.Thumbprint"
            ),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=clean_env,
    )
    thumbprint = (result.stdout or "").strip()
    if result.returncode != 0 or not thumbprint:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            "Failed to read signing thumbprint from signed executable."
            + (f" {detail}" if detail else "")
        )
    return thumbprint


def zip_folder(source_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(source_dir):
            for filename in files:
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, source_dir)
                zipf.write(full_path, rel_path)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def find_inno_setup_compiler():
    override = os.environ.get("INNO_SETUP_COMPILER") or os.environ.get("ISCC_PATH")
    if override and os.path.isfile(override):
        return override

    candidates = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("ProgramFiles")
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    for base in (local_appdata, program_files, program_files_x86):
        if not base:
            continue
        for version in ("6", "7"):
            candidates.append(os.path.join(base, "Programs", f"Inno Setup {version}", "ISCC.exe"))
            candidates.append(os.path.join(base, f"Inno Setup {version}", "ISCC.exe"))

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate

    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    if found:
        return found

    if os.name == "nt":
        result = subprocess.run(
            ["where", "ISCC.exe"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        for line in (result.stdout or "").splitlines():
            candidate = line.strip()
            if candidate and os.path.isfile(candidate):
                return candidate
    return None


def build_installer(version, compiler=None):
    compiler = compiler or find_inno_setup_compiler()
    if not compiler:
        raise RuntimeError(
            "Inno Setup compiler ISCC.exe was not found. Install Inno Setup 6/7, "
            "add ISCC.exe to PATH, or set INNO_SETUP_COMPILER."
        )
    dist_dir = os.path.join(REPO_ROOT, "dist", "iptvclient")
    if not os.path.isdir(dist_dir):
        raise RuntimeError("Build output not found at dist\\iptvclient.")
    if not os.path.isfile(INSTALLER_SCRIPT):
        raise RuntimeError("Installer script not found at installer\\AccessibleIPTVClient.iss.")

    assets_dir = os.path.join(REPO_ROOT, "dist", "release")
    ensure_dir(assets_dir)
    installer_filename = app_meta.INSTALLER_ASSET_TEMPLATE.format(
        app=app_meta.APP_NAME,
        version=version,
    )
    installer_path = os.path.join(assets_dir, installer_filename)
    if os.path.exists(installer_path):
        os.remove(installer_path)

    print(f"Building Windows installer with {compiler}...")
    run([
        compiler,
        f"/DMyAppVersion={version}",
        f"/DSourceDir={dist_dir}",
        f"/DOutputDir={assets_dir}",
        INSTALLER_SCRIPT,
    ])
    if not os.path.isfile(installer_path):
        raise RuntimeError(f"Installer output was not created at {installer_path}.")
    if os.path.getsize(installer_path) < 1024 * 1024:
        raise RuntimeError(f"Installer output is unexpectedly small: {installer_path}.")
    return installer_path

def build_assets(version, release_notes, signing_thumbprint=None, installer_path=None):
    dist_dir = os.path.join(REPO_ROOT, "dist", "iptvclient")
    if not os.path.isdir(dist_dir):
        raise RuntimeError("Build output not found at dist\\iptvclient.")

    assets_dir = os.path.join(REPO_ROOT, "dist", "release")
    ensure_dir(assets_dir)

    asset_filename = app_meta.UPDATE_ASSET_TEMPLATE.format(app=app_meta.APP_NAME, version=version)
    asset_path = os.path.join(assets_dir, asset_filename)
    zip_folder(dist_dir, asset_path)

    latest_filename = app_meta.UPDATE_ASSET_LATEST.format(app=app_meta.APP_NAME)
    latest_path = os.path.join(assets_dir, latest_filename)
    shutil.copy2(asset_path, latest_path)

    asset_sha = sha256_file(asset_path)
    download_url = (
        f"https://github.com/{app_meta.GITHUB_OWNER}/{app_meta.GITHUB_REPO}/releases/download/"
        f"v{version}/{asset_filename}"
    )
    installer_filename = None
    installer_download_url = None
    installer_sha = None
    if installer_path:
        installer_filename = os.path.basename(installer_path)
        installer_sha = sha256_file(installer_path)
        installer_download_url = (
            f"https://github.com/{app_meta.GITHUB_OWNER}/{app_meta.GITHUB_REPO}/releases/download/"
            f"v{version}/{installer_filename}"
        )
    summary = updater.summarize_release_notes(release_notes)
    manifest_data = updater.build_manifest(
        version=version,
        asset_filename=asset_filename,
        download_url=download_url,
        sha256=asset_sha,
        release_notes_summary=summary,
        signing_thumbprint=signing_thumbprint,
        installer_asset_filename=installer_filename,
        installer_download_url=installer_download_url,
        installer_sha256=installer_sha,
    )
    manifest_path = os.path.join(assets_dir, app_meta.UPDATE_MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        handle.write(json_dump(manifest_data))

    notes_path = os.path.join(assets_dir, "release_notes.md")
    with open(notes_path, "w", encoding="utf-8") as handle:
        handle.write(release_notes)

    return {
        "asset_path": asset_path,
        "latest_path": latest_path,
        "manifest_path": manifest_path,
        "notes_path": notes_path,
        "installer_path": installer_path,
    }

def json_dump(payload):
    return json.dumps(payload, indent=2)


def git_commit_and_tag(version):
    run(["git", "add", "app_meta.py", "CHANGELOG.md", "locale"])
    run(["git", "commit", "-m", f"chore(release): v{version}"])
    run(["git", "tag", f"v{version}"])


def git_push(version):
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    run(["git", "push", "origin", branch])
    run(["git", "push", "origin", f"v{version}"])


def gh_release_create(version, assets):
    release_assets = [assets["asset_path"], assets["latest_path"]]
    if assets.get("installer_path"):
        release_assets.append(assets["installer_path"])
    release_assets.append(assets["manifest_path"])
    cmd = [
        "gh",
        "release",
        "create",
        f"v{version}",
        *release_assets,
        "--title",
        f"v{version}",
        "--notes-file",
        assets["notes_path"],
        "--latest",
    ]
    run(cmd)
    ensure_release_published_latest(version)
    delete_draft_releases()


def ensure_release_published_latest(version):
    tag = f"v{version}"
    run(["gh", "release", "edit", tag, "--draft=false", "--latest"])


def delete_draft_releases():
    result = run(
        ["gh", "release", "list", "--limit", "100", "--json", "tagName,isDraft"],
        capture_output=True,
    )
    try:
        releases = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse GitHub release list JSON.") from exc

    draft_tags = [
        release.get("tagName")
        for release in releases
        if release.get("isDraft") and release.get("tagName")
    ]
    for tag in draft_tags:
        print(f"Deleting draft release {tag}...")
        run(["gh", "release", "delete", tag, "--yes"])


def print_dry_run(version, tag, bump, assets):
    print("Dry run summary:")
    print(f"- last_tag: {tag or 'none'}")
    print(f"- bump: {bump}")
    print(f"- next_version: {version}")
    print("- build: pyinstaller --noconfirm main.spec")
    print(f"- sign: {app_meta.EXE_NAME}")
    print(f"- zip: {assets['asset_path']}")
    print(f"- installer: {assets['installer_path']}")
    print(f"- manifest: {assets['manifest_path']}")
    print(f"- release: gh release create v{version} ...")


def compute_next_version():
    tag = find_last_version_tag()
    base_version = None
    if tag:
        base_version = parse_version_tag(tag)

    if not base_version:
        base_version = (1, 4, 2)

    commits = get_commits_since(tag)
    bump = determine_bump(commits)
    next_version = bump_version(base_version, bump)
    return tag, format_version(next_version), commits, bump


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["release", "build", "dry-run"])
    args = parser.parse_args()

    if args.mode == "release":
        tag, next_version, commits, bump = compute_next_version()
        release_notes = build_release_notes(commits)
        update_version_file(next_version)
        update_changelog(next_version, release_notes)
        sync_translations()
        validate_ffmpeg_binary()
        clean_build_artifacts()
        run_pyinstaller()
        exe_path = os.path.join(REPO_ROOT, "dist", "iptvclient", app_meta.EXE_NAME)
        validate_ffmpeg_binary(os.path.join(REPO_ROOT, "dist", "iptvclient", "_internal", FFMPEG_NAME))
        validate_no_bundled_config()
        sign_executable(exe_path)
        signing_thumbprint = get_signing_thumbprint(exe_path)
        installer_path = build_installer(next_version)
        sign_executable(installer_path)
        assets = build_assets(next_version, release_notes, signing_thumbprint, installer_path=installer_path)
        git_commit_and_tag(next_version)
        git_push(next_version)
        gh_release_create(next_version, assets)
        return

    if args.mode == "build":
        release_notes = "## Other\n- Local build."
        sync_translations()
        validate_ffmpeg_binary()
        clean_build_artifacts()
        run_pyinstaller()
        exe_path = os.path.join(REPO_ROOT, "dist", "iptvclient", app_meta.EXE_NAME)
        validate_ffmpeg_binary(os.path.join(REPO_ROOT, "dist", "iptvclient", "_internal", FFMPEG_NAME))
        validate_no_bundled_config()
        sign_executable(exe_path)
        signing_thumbprint = get_signing_thumbprint(exe_path)
        installer_path = None
        compiler = find_inno_setup_compiler()
        if compiler:
            installer_path = build_installer(app_meta.APP_VERSION, compiler=compiler)
            sign_executable(installer_path)
        else:
            print("Inno Setup compiler not found; skipping local installer build.")
        build_assets(app_meta.APP_VERSION, release_notes, signing_thumbprint, installer_path=installer_path)
        return

    if args.mode == "dry-run":
        tag, next_version, commits, bump = compute_next_version()
        release_notes = build_release_notes(commits)
        assets = {
            "asset_path": os.path.join(REPO_ROOT, "dist", "release", "asset.zip"),
            "installer_path": os.path.join(REPO_ROOT, "dist", "release", app_meta.INSTALLER_ASSET_TEMPLATE.format(app=app_meta.APP_NAME, version=next_version)),
            "manifest_path": os.path.join(REPO_ROOT, "dist", "release", app_meta.UPDATE_MANIFEST_NAME),
        }
        print_dry_run(next_version, tag, bump, assets)
        print("")
        print(release_notes)


if __name__ == "__main__":
    main()
