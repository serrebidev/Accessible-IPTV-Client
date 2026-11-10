"""Local recording inventory; media and metadata stay in their recording folder."""
import datetime
import json
import math
import os
from pathlib import Path
import tempfile
import threading

import recording_outcome
from i18n import gettext as _
from programme_reminders import safe_title

_INDEX = ".iptv-recordings.json"
_LOCK = threading.RLock()
_EXTENSIONS = {".mkv", ".mp4", ".ts", ".mts", ".m2ts", ".mp3", ".m4a", ".aac",
               ".flac", ".ogg", ".wav", ".mka", ".opus", ".webm", ".avi", ".mov", ".mpg"}


def _read(directory):
    try:
        with open(Path(directory) / _INDEX, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(directory, rows):
    fd, temporary = tempfile.mkstemp(prefix=".iptv-library-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, Path(directory) / _INDEX)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def remember(rec, returncode):
    path = Path(rec.out_path)
    if not path.is_file() or path.is_symlink():
        return
    stamp = path.stat()
    seconds = getattr(rec, "media_written_seconds", None)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        seconds = None
    entry = {"title": safe_title(rec.title) or path.stem,
             "channel": safe_title(getattr(rec, "metadata", {}).get("channel_name")),
             "duration": seconds, "size": stamp.st_size, "modified_ns": stamp.st_mtime_ns,
             "status": getattr(rec, "outcome", None) or recording_outcome.classify(rec, returncode)}
    with _LOCK:
        rows = _read(path.parent)
        rows.pop(path.name, None)
        rows[path.name] = entry
        _write(path.parent, dict(list(rows.items())[-10000:]))


def scan(directory, active_paths=()):
    root = Path(directory).resolve()
    active = {os.path.normcase(os.path.abspath(p)) for p in active_paths}
    with _LOCK:
        index = _read(root)
    result = []
    if not root.exists():
        return result
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() not in _EXTENSIONS and path.name not in index:
            continue
        if os.path.normcase(str(path)) in active:
            continue
        try:
            stamp = path.stat()
        except OSError:
            continue
        info = index.get(path.name, {})
        if not isinstance(info, dict) or info.get("size") != stamp.st_size or info.get("modified_ns") != stamp.st_mtime_ns:
            info = {}
        duration = info.get("duration")
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            duration = None
        result.append({"path": str(path), "title": safe_title(info.get("title")) or path.stem,
                       "channel": safe_title(info.get("channel")), "duration": duration,
                       "status": info.get("status", "unknown"), "size": stamp.st_size,
                       "modified_ns": stamp.st_mtime_ns,
                       "date": datetime.datetime.fromtimestamp(stamp.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return sorted(result, key=lambda row: (-row["modified_ns"], row["path"]))


def checked_path(directory, row, active_paths=()):
    root = Path(directory).resolve()
    path = Path(row["path"])
    if path.is_symlink() or path.resolve().parent != root or not path.is_file():
        raise ValueError(_("The recording file is no longer available."))
    stamp = path.stat()
    if (stamp.st_size, stamp.st_mtime_ns) != (row["size"], row["modified_ns"]):
        raise ValueError(_("The recording file changed. Refresh the library."))
    if os.path.normcase(str(path.resolve())) in {os.path.normcase(os.path.realpath(p)) for p in active_paths}:
        raise ValueError(_("The recording is still in use."))
    return path


def delete(directory, row, active_paths=()):
    with _LOCK:
        path = checked_path(directory, row, active_paths)
        path.unlink()
        rows = _read(path.parent)
        rows.pop(path.name, None)
        _write(path.parent, rows)


def playback_channel(directory, row, active_paths=()):
    path = checked_path(directory, row, active_paths)
    # Including the file signature prevents a replaced file at the same path
    # from inheriting an unrelated resume position.
    source = "local-recording:{0}:{1}".format(row["size"], row["modified_ns"])
    return {"name": row["title"], "kind": "movie", "url": path.as_uri(),
            "provider-id": source, "local-recording": str(path)}
