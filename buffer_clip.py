"""Save a finite selection of completed local HLS segments without touching the ingest cursor."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from i18n import gettext as _
from recording_storage import publish_new_file


def select_segments(rows, seconds):
    if not rows or not 0 < seconds <= 24 * 3600:
        raise ValueError(_("No buffered audio or video is available."))
    floor = rows[-1].end - seconds
    return tuple(row for row in rows if row.end > floor)


def _check(canceled):
    if canceled():
        raise InterruptedError(_("Canceled"))


def _open_segment(path):
    if os.name != "nt":
        return open(path, "rb")
    # The ordinary Windows file opener can deny deletion. The live ring must
    # remain able to evict a file even while a slow export is reading it.
    import _winapi
    import msvcrt

    def shared(name, _flags):
        share_read_write_delete = 1 | 2 | 4
        sequential_scan = 0x08000000
        handle = _winapi.CreateFile(
            name, _winapi.GENERIC_READ, share_read_write_delete, 0, _winapi.OPEN_EXISTING, sequential_scan, 0
        )
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            _winapi.CloseHandle(handle)
            raise

    return open(path, "rb", opener=shared)


def _stage(window, rows, directory, canceled):
    manifest = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:%d" % max(1, int(max(r.duration for r in rows) + 1)),
    ]
    for i, row in enumerate(rows):
        _check(canceled)
        name = "%06d.ts" % i
        target = directory / name
        try:
            os.link(window.directory / row.name, target)
        except FileNotFoundError as error:
            raise ValueError(_("The selected buffer segment is no longer available.")) from error
        except OSError:
            try:
                with _open_segment(window.directory / row.name) as source, target.open("xb") as out:
                    while True:
                        _check(canceled)
                        data = source.read(64 * 1024)
                        if not data:
                            break
                        out.write(data)
            except FileNotFoundError as error:
                raise ValueError(_("The selected buffer segment is no longer available.")) from error
        if target.stat().st_size != row.size:
            raise ValueError(_("The selected buffer segment is no longer available."))
        if row.discontinuity:
            manifest.append("#EXT-X-DISCONTINUITY")
        manifest.extend(["#EXTINF:%.6f," % row.duration, name])
    path = directory / "index.m3u8"
    path.write_text("\n".join(manifest + ["#EXT-X-ENDLIST", ""]), encoding="ascii")
    return path


def save(window, rows, destination, ffmpeg, reserve_mib, canceled=lambda: False, on_staged=None):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(_("A file with this name already exists in the selected folder."))
    _check(canceled)
    if not rows:
        raise ValueError(_("No buffered audio or video is available."))
    size = sum(r.size for r in rows)
    # One bounded snapshot plus the remux; keep the recording reserve on both volumes.
    reserve = reserve_mib * 1024**2
    same_device = destination.parent.stat().st_dev == window.directory.stat().st_dev
    if (
        shutil.disk_usage(destination.parent).free < reserve + size * (2 if same_device else 1)
        or shutil.disk_usage(window.directory).free < reserve + size
    ):
        raise OSError(_("There is not enough free space to save the buffered programme."))
    with tempfile.TemporaryDirectory(prefix="iptv-clip-", dir=window.directory.parent) as directory:
        manifest = _stage(window, rows, Path(directory), canceled)
        if on_staged:
            on_staged()
        fd, path = tempfile.mkstemp(dir=destination.parent, prefix=".iptv-clip-", suffix=".part")
        os.close(fd)
        try:
            _check(canceled)
            args = [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-protocol_whitelist",
                "file",
                "-i",
                str(manifest),
                "-map",
                "0",
                "-c",
                "copy",
                "-f",
                "mpegts",
                path,
            ]
            with subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ) as proc:
                try:
                    while proc.poll() is None:
                        _check(canceled)
                        try:
                            proc.wait(timeout=0.2)
                        except subprocess.TimeoutExpired:
                            continue
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
            if proc.returncode or not os.path.getsize(path):
                raise OSError(_("The buffered programme could not be saved."))
            with open(path, "rb+") as handle:
                os.fsync(handle.fileno())
            _check(canceled)
            publish_new_file(path, destination)
        finally:
            Path(path).unlink(missing_ok=True)
