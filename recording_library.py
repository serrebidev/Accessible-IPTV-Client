"""Local recording inventory; media and metadata stay in their recording folder."""
import datetime
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import threading
import uuid

import recording_outcome
from i18n import gettext as _
from programme_reminders import safe_title

_INDEX = ".iptv-recordings.json"
_LOCK = threading.RLock()
LOG = logging.getLogger(__name__)
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
        rows = _read(path.parent)
        original = dict(rows)
        rows.pop(path.name, None)
        _write(path.parent, rows)
        try:
            path.unlink()
        except OSError:
            _write(path.parent, original)
            raise


def rename_title(directory, row, title, active_paths=()):
    """Rename the displayed title without invalidating playback identities."""
    title = str(title).strip()
    if not title or len(title) > 240 or any(ord(char) < 32 for char in title):
        raise ValueError(_("Enter a recording title of 1 to 240 characters."))
    with _LOCK:
        path = checked_path(directory, row, active_paths)
        rows = _read(path.parent)
        rows[path.name] = {key: row[key] for key in ("channel", "duration", "status", "size", "modified_ns")}
        rows[path.name]["title"] = title
        _write(path.parent, rows)


def _trash_root(directory, *, create=False):
    root = Path(directory).resolve()
    trash = root / ".iptv-recording-trash"
    if trash.is_symlink() or trash.resolve() != trash or (trash.exists() and not trash.is_dir()):
        raise ValueError(_("The recording trash folder is not available."))
    if create:
        trash.mkdir(exist_ok=True)
    return trash


def trash(directory, row, active_paths=()):
    """Journal metadata before the atomic, same-volume move. Never erase media."""
    with _LOCK:
        path = checked_path(directory, row, active_paths)
        target = _trash_root(directory, create=True) / uuid.uuid4().hex
        target.mkdir()
        entry = {key: row[key] for key in ("title", "channel", "duration", "status", "size", "modified_ns")}
        try:
            _write(target, {"file": path.name, "entry": entry})
            os.replace(path, target / path.name)
        except Exception:
            # If the move failed the source still exists. Only remove our
            # metadata; never recursively delete a directory containing media.
            (target / _INDEX).unlink(missing_ok=True)
            target.rmdir()
            raise
        # The old index row is harmless: scan requires a matching real file.
        # Do not report a successful media move as failed because of cleanup.


def scan_trash(directory):
    root = _trash_root(directory)
    if not root.exists():
        return []
    rows = []
    for folder in root.iterdir():
        if folder.is_symlink() or folder.resolve() != folder or not folder.is_dir() or not all(c in "0123456789abcdef" for c in folder.name) or len(folder.name) != 32:
            continue
        manifest = _read(folder)
        name, info = manifest.get("file"), manifest.get("entry")
        if not isinstance(name, str) or Path(name).name != name or name in (".", "..") or not isinstance(info, dict):
            continue
        path = folder / name
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            continue
        stamp = path.stat()
        if (info.get("size"), info.get("modified_ns")) != (stamp.st_size, stamp.st_mtime_ns):
            continue
        rows.append(dict(info, path=str(path), trash_id=folder.name, original_name=name,
                         date=datetime.datetime.fromtimestamp(stamp.st_mtime).strftime("%Y-%m-%d %H:%M")))
    return sorted(rows, key=lambda row: (-row["modified_ns"], row["path"]))


def _checked_trash(directory, row):
    root = _trash_root(directory)
    identity = str(row.get("trash_id", ""))
    if len(identity) != 32 or not all(c in "0123456789abcdef" for c in identity):
        raise ValueError(_("The recording file is no longer available."))
    folder = root / identity
    if folder.is_symlink():
        raise ValueError(_("The recording file is no longer available."))
    current = next((item for item in scan_trash(directory) if item["trash_id"] == identity), None)
    if current is None or current != row:
        raise ValueError(_("The recording file changed. Refresh the library."))
    return folder, Path(current["path"])


def restore(directory, row):
    """Restore without replacing another file, even if it appears concurrently."""
    with _LOCK:
        folder, path = _checked_trash(directory, row)
        destination = Path(directory).resolve() / path.name
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(_("A file with this name already exists in the recording folder."))
        index = _read(destination.parent)
        index[destination.name] = {key: row[key] for key in ("title", "channel", "duration", "status", "size", "modified_ns")}
        _write(destination.parent, index)
        # Hard-link creation is exclusive; fall back to an exclusive copy on
        # filesystems without links. All large work runs in the dialog worker.
        try:
            os.link(path, destination)
        except FileExistsError:
            raise
        except OSError:
            import shutil
            with open(destination, "xb") as target:
                try:
                    with open(path, "rb") as source:
                        shutil.copyfileobj(source, target)
                    target.flush()
                    os.fsync(target.fileno())
                    os.utime(destination, ns=(path.stat().st_atime_ns, row["modified_ns"]))
                except Exception:
                    target.close()
                    destination.unlink(missing_ok=True)
                    raise
        try:
            path.unlink()
        except OSError:
            destination.unlink()
            raise
        _cleanup_trash_folder(folder)


def _cleanup_trash_folder(folder):
    # The media action has completed. Leftover metadata is safe to ignore.
    try:
        (folder / _INDEX).unlink(missing_ok=True)
        folder.rmdir()
    except OSError:
        LOG.debug("Recording trash metadata cleanup failed", exc_info=True)


def delete_trashed(directory, row):
    with _LOCK:
        folder, path = _checked_trash(directory, row)
        path.unlink()
        _cleanup_trash_folder(folder)


def folders(config):
    import options
    values = [options.get_recordings_dir(config)]
    additional = config.get("recording_library_folders")
    if isinstance(additional, list):
        values.extend(path for path in additional if isinstance(path, str) and "\x00" not in path)
    result = []
    seen = set()
    for path in values:
        if not path.strip():
            continue
        absolute = os.path.abspath(path)
        key = os.path.normcase(os.path.realpath(absolute))
        if key not in seen:
            result.append(absolute)
            seen.add(key)
    return result[:20]


def playback_channel(directory, row, active_paths=()):
    path = checked_path(directory, row, active_paths)
    # Including the file signature prevents a replaced file at the same path
    # from inheriting an unrelated resume position.
    source = "local-recording:{0}:{1}".format(row["size"], row["modified_ns"])
    return {"name": row["title"], "kind": "movie", "url": path.as_uri(),
            "provider-id": source, "local-recording": str(path)}
