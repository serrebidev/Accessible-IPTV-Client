"""On-demand chapter descriptions and timed text from local Matroska recordings."""

import ctypes
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time

from i18n import gettext as _
import subtitle_cues


def chapters(player):
    import vlc

    # python-vlc's high-level generator does not release this native array.
    pointer = ctypes.POINTER(vlc.ChapterDescription)()
    count = vlc.libvlc_media_player_get_full_chapter_descriptions(player, -1, ctypes.byref(pointer))
    if count <= 0 or not pointer:
        return []
    array = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(vlc.ChapterDescription)))
    try:
        return [
            (
                i,
                max(0, array[i].contents.time_offset),
                (array[i].contents.name or b"").decode("utf-8", errors="replace").strip(),
            )
            for i in range(count)
            if array[i]
        ]
    finally:
        vlc.libvlc_chapter_descriptions_release(array, count)


# Match the stream declarations in FFmpeg's input summary. Selection/extraction
# both use that same absolute stream index, independent of libVLC's ES IDs.
_STREAM = re.compile(r"^\s*Stream #0:(\d+)(?:\[[^]]*])?(?:\(([^)]*)\))?:\s*(\w+):\s*([\w]+)")
_TEXT = {"subrip", "srt", "ass", "ssa", "webvtt", "text", "mov_text"}


def _read_process(args, canceled, *, listing):
    limit = 1024 * 1024 if listing else subtitle_cues.MAX_FILE_BYTES
    output = bytearray()
    with subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if listing else subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as proc:

        def collect():
            while chunk := proc.stdout.read(65536):
                output.extend(chunk)
                if len(output) > limit:
                    proc.kill()
                    return

        reader = threading.Thread(target=collect, daemon=True, name="SubtitleOutput")
        reader.start()
        deadline = time.monotonic() + (20 if listing else 180)
        try:
            while proc.poll() is None:
                if canceled():
                    return b""
                if time.monotonic() >= deadline:
                    raise ValueError(_("Reading the embedded subtitles timed out."))
                try:
                    proc.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    continue  # Check for cancellation during this bounded foreground request.
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            reader.join()
        if len(output) > limit:
            raise ValueError(_("The subtitle data is too large to read."))
        if not listing and proc.returncode:
            raise ValueError(_("Could not read this subtitle track."))
    return bytes(output)


def _input(path):
    from recorder import get_ffmpeg_path

    file = Path(path)
    if file.suffix.casefold() not in (".mkv", ".mka") or not file.is_file():
        raise ValueError(_("Open a local Matroska recording to read its embedded subtitles."))
    return [
        get_ffmpeg_path(),
        "-nostdin",
        "-hide_banner",
        "-protocol_whitelist",
        "file",
        "-f",
        "matroska",
        "-i",
        str(file.absolute()),
    ]


def _signature(path):
    info = Path(path).stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def subtitle_tracks(path, canceled, recording_id=""):
    if canceled():
        return []
    args = _input(path)
    signature = _signature(path)
    if recording_id.startswith("local-recording:") and recording_id != "local-recording:{}:{}".format(*signature[2:]):
        raise ValueError(_("The recording file changed. Refresh the library."))
    listing = _read_process(args, canceled, listing=True).decode("utf-8", errors="replace")
    if canceled():
        return []
    if _signature(path) != signature:
        raise ValueError(_("The recording file changed. Refresh the library."))
    if "Input #0," not in listing:
        raise ValueError(_("Could not read the recording's track information."))
    tracks = {}
    current = None
    for line in listing.splitlines():
        if match := _STREAM.match(line):
            idx, language, kind, codec = match.groups()
            current = None
            if kind == "Subtitle":
                current = tracks[int(idx)] = dict(
                    index=int(idx),
                    language=language or "",
                    codec=codec,
                    title="",
                    readable=codec in _TEXT,
                    signature=signature,
                )
        elif current is not None and (tag := re.match(r"^\s+title\s*:\s*(.*)", line, re.I)):
            current["title"] = " ".join(tag[1].split())[:240]
    return list(tracks.values())


def embedded_cues(path, track, canceled):
    if canceled():
        return []
    if not track["readable"] or type(track["index"]) is not int or track["index"] < 0:
        raise ValueError(_("This subtitle track cannot be read aloud."))
    if _signature(path) != track["signature"]:
        raise ValueError(_("The recording file changed. Refresh the library."))
    ass = track["codec"] in {"ass", "ssa"}
    fmt = "ass" if ass else "srt"
    args = _input(path) + [
        "-loglevel",
        "error",
        "-map",
        "0:" + str(track["index"]),
        "-c:s",
        "copy" if ass else "srt",
        "-f",
        fmt,
        "pipe:1",
    ]
    data = _read_process(args, canceled, listing=False)
    if canceled():
        return []
    if _signature(path) != track["signature"]:
        raise ValueError(_("The recording file changed. Refresh the library."))
    return subtitle_cues.parse(data.decode("utf-8-sig", errors="replace"), fmt)


def transcript(cues):
    from media_navigation import clock_text

    def timestamp(milliseconds):
        return f"{clock_text(milliseconds)}.{milliseconds % 1000:03}"

    return "".join(f"{timestamp(cue.start)} – {timestamp(cue.end)}\n{cue.text}\n\n"
                   for cue in cues).encode("utf-8-sig")


def save_excerpt(path, identity, destination, first, last, canceled):
    """Encode an exact local range to a temporary MKV and publish it on success."""
    from recorder import get_ffmpeg_path
    from recording_storage import publish_new_file

    if canceled():
        return
    source = Path(path)
    target = Path(destination)
    if target.suffix.casefold() != ".mkv" or not 0 <= first < last <= 7 * 24 * 3600 * 1000:
        raise ValueError(_("Choose a valid recording range and an MKV filename."))
    if not source.is_file():
        raise ValueError(_("The recording file is no longer available."))
    signature = _signature(source)
    if identity != "local-recording:{}:{}".format(*signature[2:]):
        raise ValueError(_("The recording file changed. Refresh the library."))
    if target.exists() or target.is_symlink():
        raise ValueError(_("Choose a new filename for the excerpt."))

    with tempfile.TemporaryDirectory(prefix=".iptv-excerpt-", dir=target.parent) as staging:
        temporary = Path(staging) / "excerpt.mkv"
        # Low-priority, bounded encoder threads leave room for existing recordings.
        args = [get_ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error",
                "-protocol_whitelist", "file", "-threads", "1", "-ss", f"{first / 1000:.3f}",
                "-i", str(source.absolute()), "-t", f"{(last - first) / 1000:.3f}",
                "-map", "0:V:0?", "-map", "0:a?", "-map_chapters", "-1", "-map_metadata", "-1",
                "-c:v", "libx264", "-preset", "veryfast", "-threads:v", "1", "-c:a", "aac",
                "-filter_threads", "1", str(temporary.absolute())]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        if os.name == "posix":
            import shutil
            if nice := shutil.which("nice"):
                args = [nice, "-n", "10", *args]
        with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, creationflags=flags) as proc:
            deadline = time.monotonic() + 7200
            try:
                while proc.poll() is None:
                    if canceled():
                        return
                    if time.monotonic() >= deadline:
                        raise ValueError(_("Saving the recording excerpt timed out."))
                    try:
                        proc.wait(timeout=0.25)
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
            if proc.returncode or not temporary.is_file() or not temporary.stat().st_size:
                raise ValueError(_("Could not save the recording excerpt."))
        if canceled():
            return
        if _signature(source) != signature:
            raise ValueError(_("The recording file changed. Refresh the library."))
        with temporary.open("rb+") as output:
            os.fsync(output.fileno())
        if not canceled():
            publish_new_file(temporary, target)
