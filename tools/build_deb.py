#!/usr/bin/env python3
"""Build a Debian package (.deb) for Accessible IPTV Client.

The package installs the Python sources to ``/usr/lib/accessible-iptv-client``
and runs them with the system interpreter, so the runtime dependencies
(wxPython, python-vlc, libVLC, ffmpeg) come from apt rather than being bundled.
That keeps the package ``Architecture: all`` and avoids shipping a second copy
of GTK/VLC the way the Windows PyInstaller build has to.

Usage::

    python3 tools/build_deb.py                     # version from app_meta.py
    python3 tools/build_deb.py --version 1.2.3     # explicit version
    python3 tools/build_deb.py --output-dir dist   # where the .deb lands

``dpkg-deb`` is used when available (Linux, WSL). Everywhere else - including
Windows, where the maintainer builds the release - the archive is assembled
directly, since a .deb is just an ``ar`` archive of three members.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import app_meta  # noqa: E402  (needs REPO_ROOT on sys.path)
import i18n_tools  # noqa: E402

PACKAGE = "accessible-iptv-client"
# Timestamp stamped into the archive members. Honouring SOURCE_DATE_EPOCH keeps
# rebuilds reproducible; the wall clock is the fallback because a zeroed mtime
# trips lintian's package-contains-ancient-file check.
BUILD_MTIME = int(os.environ.get("SOURCE_DATE_EPOCH") or time.time())
DEFAULT_MAINTAINER = "serrebidev <serrebidev@users.noreply.github.com>"
INSTALL_LIB_DIR = f"/usr/lib/{PACKAGE}"
HOMEPAGE = f"https://github.com/{app_meta.GITHUB_OWNER}/{app_meta.GITHUB_REPO}"

# Runtime dependencies. python3-vlc already pulls libvlc5; the two vlc-plugin-*
# packages supply the demuxers/outputs libVLC needs for HLS playback without
# dragging in the Qt desktop app, which is only wanted for the external-player
# option and is therefore a Recommends.
DEPENDS = [
    "python3 (>= 3.11)",
    "python3-wxgtk4.0",
    "python3-vlc",
    "vlc-plugin-base",
    "vlc-plugin-video-output",
    "ffmpeg",
]
RECOMMENDS = ["vlc", "python3-psutil"]

# Casting needs newer releases than Debian carries (pychromecast >= 14), and
# pyatv/async-upnp-client are not packaged at all, so they stay out of the
# dependency fields; casting.py degrades gracefully when they are absent.
DESCRIPTION_SHORT = "keyboard-first IPTV player for screen reader users"
DESCRIPTION_LONG = """\
 Accessible IPTV Client is a keyboard-first IPTV player built to work well with
 screen readers (NVDA, JAWS, Narrator, Orca) and to load large playlists and
 XMLTV guides without freezing.
 .
 Features include M3U/M3U+ playlists, Xtream Codes and Stalker Portal sources,
 channel groups with fast channel and EPG search, catch-up/timeshift playback,
 scheduled recordings, and playback either in the built-in libVLC player or an
 external player.
 .
 Casting (Chromecast, DLNA, AirPlay) is optional and needs Python packages that
 Debian does not carry in a new enough version. Install them with pip to enable
 it: pychromecast (>= 14), async-upnp-client (>= 0.38) and pyatv (>= 0.14).
"""

# .desktop entry. No Icon= line: the project ships no icon asset, and inventing
# one here would put unreviewed branding in a release artifact.
DESKTOP_ENTRY = f"""\
[Desktop Entry]
Type=Application
Version=1.0
Name={app_meta.APP_DISPLAY_NAME}
GenericName=IPTV Player
Comment=Keyboard-first IPTV player that works well with screen readers
Exec={PACKAGE}
Terminal=false
Categories=AudioVideo;Video;Player;TV;
Keywords=IPTV;M3U;Xtream;Stalker;EPG;TV;accessible;screenreader;
StartupNotify=true
"""

LAUNCHER = f"""\
#!/bin/sh
# Launcher installed by the {PACKAGE} Debian package.
set -e
exec /usr/bin/python3 "{INSTALL_LIB_DIR}/main.py" "$@"
"""

MAN_PAGE = f""".TH ACCESSIBLE-IPTV-CLIENT 1 "" "{app_meta.APP_VERSION}" "User Commands"
.SH NAME
accessible\\-iptv\\-client \\- keyboard-first IPTV player for screen reader users
.SH SYNOPSIS
.B accessible\\-iptv\\-client
.SH DESCRIPTION
.B {app_meta.APP_DISPLAY_NAME}
plays IPTV sources - M3U/M3U+ playlists, Xtream Codes and Stalker Portal
portals - in a keyboard-driven interface designed to work well with screen
readers. It loads large playlists and XMLTV guides without blocking the UI, and
plays either in the built-in libVLC player or an external player.
.PP
The application takes no command line options; playlists, guides and
preferences are configured in the running program.
.SH KEY BINDINGS
.TP
.B Ctrl+M
Playlist Manager.
.TP
.B Ctrl+E
EPG Manager.
.TP
.B Ctrl+I
Import EPG to the local database.
.TP
.B Enter
Play the selected channel.
.TP
.B Ctrl+Q
Quit.
.SH FILES
.TP
.I ~/iptvclient.conf
Settings, including playlist and EPG source lists.
.TP
.I ~/scheduled_recordings.json
Scheduled recordings.
.TP
.I $TMPDIR/epg.db
The imported XMLTV guide, alongside the playlist cache and EPG debug log.
Because this lives in the temp directory it is cleared when the temp directory
is, usually at reboot; set
.B TMPDIR
to a persistent location to keep an imported guide.
.SH SEE ALSO
.BR vlc (1),
.BR ffmpeg (1)
.SH AUTHOR
serrebidev and contributors. Report bugs at
.UR {HOMEPAGE}/issues
.UE .
"""

COPYRIGHT = f"""\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: {app_meta.APP_DISPLAY_NAME}
Source: {HOMEPAGE}

Files: *
Copyright: 2025 serrebi
License: Expat

License: Expat
 Permission is hereby granted, free of charge, to any person obtaining a copy
 of this software and associated documentation files (the "Software"), to deal
 in the Software without restriction, including without limitation the rights
 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the Software is
 furnished to do so, subject to the following conditions:
 .
 The above copyright notice and this permission notice shall be included in all
 copies or substantial portions of the Software.
 .
 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 SOFTWARE.
"""


def log(message: str) -> None:
    print(f"[build_deb] {message}", flush=True)


def app_source_files() -> list[str]:
    """Top-level Python modules that make up the application."""
    names = sorted(
        name
        for name in os.listdir(REPO_ROOT)
        if name.endswith(".py") and os.path.isfile(os.path.join(REPO_ROOT, name))
    )
    if "main.py" not in names:
        raise RuntimeError("main.py not found in the repository root.")
    return names


def compiled_catalogues() -> list[tuple[str, str]]:
    """``(absolute source, path relative to the locale dir)`` for every .mo file."""
    locale_root = os.path.join(REPO_ROOT, "locale")
    found: list[tuple[str, str]] = []
    for root, _dirs, files in os.walk(locale_root):
        for name in files:
            if name.endswith(".mo"):
                absolute = os.path.join(root, name)
                found.append((absolute, os.path.relpath(absolute, locale_root).replace(os.sep, "/")))
    return sorted(found, key=lambda item: item[1])


class Staged:
    """The package payload, kept in memory so file modes never depend on the host FS.

    Windows cannot express the executable bit, so recording modes explicitly
    here is what lets a .deb built on Windows install correctly on Debian.
    """

    def __init__(self) -> None:
        self.files: list[tuple[str, bytes, int]] = []  # (path without leading /, content, mode)

    def add_bytes(self, path: str, content: bytes, mode: int = 0o644) -> None:
        self.files.append((path.lstrip("/"), content, mode))

    def add_text(self, path: str, text: str, mode: int = 0o644) -> None:
        # Unix line endings regardless of the build host.
        self.add_bytes(path, text.replace("\r\n", "\n").encode("utf-8"), mode)

    def add_file(self, path: str, source: str, mode: int = 0o644) -> None:
        with open(source, "rb") as handle:
            self.add_bytes(path, handle.read(), mode)

    def installed_size_kb(self) -> int:
        total = sum(len(content) for _path, content, _mode in self.files)
        return max(1, (total + 1023) // 1024)

    def md5sums(self) -> str:
        lines = []
        for path, content, _mode in sorted(self.files):
            lines.append(f"{hashlib.md5(content).hexdigest()}  {path}")
        return "\n".join(lines) + "\n"


def build_payload(version: str) -> Staged:
    staged = Staged()

    log("compiling translation catalogues")
    i18n_tools.cmd_compile()

    lib_dir = INSTALL_LIB_DIR.lstrip("/")
    for name in app_source_files():
        staged.add_file(f"{lib_dir}/{name}", os.path.join(REPO_ROOT, name))

    catalogues = compiled_catalogues()
    if not catalogues:
        raise RuntimeError("No compiled .mo catalogues were found under locale/.")
    for absolute, relative in catalogues:
        staged.add_file(f"{lib_dir}/locale/{relative}", absolute)
    log(f"staged {len(app_source_files())} modules and {len(catalogues)} catalogues")

    staged.add_text(f"usr/bin/{PACKAGE}", LAUNCHER, mode=0o755)
    staged.add_text(f"usr/share/applications/{PACKAGE}.desktop", DESKTOP_ENTRY)

    staged.add_bytes(f"usr/share/man/man1/{PACKAGE}.1.gz", gzip_bytes(MAN_PAGE.encode("utf-8")))

    doc_dir = f"usr/share/doc/{PACKAGE}"
    staged.add_text(f"{doc_dir}/copyright", COPYRIGHT)
    changelog = (
        f"{PACKAGE} ({version}) unstable; urgency=medium\n\n"
        f"  * Release {version}; see the upstream CHANGELOG.md.\n\n"
        f" -- {os.environ.get('DEB_MAINTAINER', DEFAULT_MAINTAINER)}  "
        f"{time.strftime('%a, %d %b %Y %H:%M:%S +0000', time.gmtime())}\n"
    )
    staged.add_bytes(f"{doc_dir}/changelog.Debian.gz", gzip_bytes(changelog.encode("utf-8")))
    staged.add_file(f"{doc_dir}/README.md", os.path.join(REPO_ROOT, "README.md"))
    return staged


def gzip_bytes(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=BUILD_MTIME) as handle:
        handle.write(payload)
    return buffer.getvalue()


def control_file(version: str, installed_size_kb: int, maintainer: str) -> str:
    return (
        f"Package: {PACKAGE}\n"
        f"Version: {version}\n"
        "Section: video\n"
        "Priority: optional\n"
        "Architecture: all\n"
        f"Maintainer: {maintainer}\n"
        f"Installed-Size: {installed_size_kb}\n"
        f"Depends: {', '.join(DEPENDS)}\n"
        f"Recommends: {', '.join(RECOMMENDS)}\n"
        f"Homepage: {HOMEPAGE}\n"
        f"Description: {DESCRIPTION_SHORT}\n"
        f"{DESCRIPTION_LONG}"
    )


def _tar_bytes(entries: list[tuple[str, bytes, int]]) -> bytes:
    """A gzipped tar with root-owned entries and directories created explicitly."""
    buffer = io.BytesIO()
    directories: set[str] = set()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:

        def add(name: str, mode: int, content: bytes | None) -> None:
            info = tarfile.TarInfo(name)
            info.mode = mode
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            info.mtime = BUILD_MTIME
            if content is None:
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info.type = tarfile.REGTYPE
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))

        add("./", 0o755, None)
        for path, content, mode in sorted(entries):
            parts = path.split("/")
            for depth in range(1, len(parts)):
                directory = "./" + "/".join(parts[:depth]) + "/"
                if directory not in directories:
                    directories.add(directory)
                    add(directory, 0o755, None)
            add("./" + path, mode, content)
    return buffer.getvalue()


def _ar_archive(members: list[tuple[str, bytes]]) -> bytes:
    """Assemble the ``ar`` container dpkg expects (member order is significant)."""
    out = bytearray(b"!<arch>\n")
    for name, content in members:
        header = (
            f"{name:<16}"          # name
            f"{BUILD_MTIME:<12}"   # mtime
            f"{0:<6}"              # uid
            f"{0:<6}"              # gid
            f"{0o100644:<8o}"      # mode
            f"{len(content):<10}"  # size
            "`\n"                  # magic
        )
        out += header.encode("ascii")
        out += content
        if len(content) % 2:
            out += b"\n"
    return bytes(out)


def build_with_dpkg(staged: Staged, version: str, maintainer: str, output_path: str) -> None:
    stage_dir = os.path.join(REPO_ROOT, "build", "deb", f"{PACKAGE}_{version}_all")
    if os.path.isdir(stage_dir):
        shutil.rmtree(stage_dir)
    for path, content, mode in staged.files:
        target = os.path.join(stage_dir, path.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(content)
        os.chmod(target, mode)

    debian_dir = os.path.join(stage_dir, "DEBIAN")
    os.makedirs(debian_dir, exist_ok=True)
    for name, text, mode in (
        ("control", control_file(version, staged.installed_size_kb(), maintainer), 0o644),
        ("md5sums", staged.md5sums(), 0o644),
    ):
        target = os.path.join(debian_dir, name)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.chmod(target, mode)

    subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", stage_dir, output_path],
        check=True,
    )


def build_without_dpkg(staged: Staged, version: str, maintainer: str, output_path: str) -> None:
    control_entries = [
        ("control", control_file(version, staged.installed_size_kb(), maintainer).encode("utf-8"), 0o644),
        ("md5sums", staged.md5sums().encode("utf-8"), 0o644),
    ]
    members = [
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", _tar_bytes(control_entries)),
        ("data.tar.gz", _tar_bytes(staged.files)),
    ]
    with open(output_path, "wb") as handle:
        handle.write(_ar_archive(members))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Accessible IPTV Client .deb")
    parser.add_argument("--version", default=None, help="upstream version (default: app_meta.APP_VERSION)")
    parser.add_argument("--revision", default="1", help="Debian revision suffix (default: 1)")
    parser.add_argument(
        "--output-dir",
        default=os.path.join(REPO_ROOT, "dist", "release"),
        help="directory to write the .deb into",
    )
    parser.add_argument(
        "--maintainer",
        default=os.environ.get("DEB_MAINTAINER", DEFAULT_MAINTAINER),
        help="Maintainer field value",
    )
    parser.add_argument(
        "--no-dpkg",
        action="store_true",
        help="always assemble the archive directly, even when dpkg-deb is available",
    )
    args = parser.parse_args()

    upstream_version = (args.version or app_meta.APP_VERSION).lstrip("vV")
    version = f"{upstream_version}-{args.revision}" if args.revision else upstream_version

    staged = build_payload(upstream_version)

    os.makedirs(args.output_dir, exist_ok=True)
    output_path = os.path.join(args.output_dir, f"{PACKAGE}_{version}_all.deb")
    if os.path.exists(output_path):
        os.remove(output_path)

    dpkg = None if args.no_dpkg else shutil.which("dpkg-deb")
    if dpkg:
        log("building with dpkg-deb")
        build_with_dpkg(staged, version, args.maintainer, output_path)
    else:
        log("dpkg-deb not found; assembling the archive directly")
        build_without_dpkg(staged, version, args.maintainer, output_path)

    size_kb = os.path.getsize(output_path) // 1024
    log(f"wrote {output_path} ({size_kb} KiB, installed ~{staged.installed_size_kb()} KiB)")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
