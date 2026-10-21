"""Stream recording engine for Accessible IPTV Client.

GUI-free. Drives ffmpeg subprocesses that capture a resolved stream URL to disk.
Three families of output are supported (see ``RECORDING_FORMATS``):

* provider quality (stream copy) in MKV, MP4 or MKA (MKA is audio-only),
* x264 re-encode (H.264 + AAC) in MKV or MP4,
* audio only (WAV / FLAC / MP3 V0 / AAC / Opus).

The active format is a persistent setting chosen elsewhere; this module just turns a
format key + URL + per-channel HTTP headers into a running ffmpeg process and tracks it.
"""

import datetime
import logging
import os
import re
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional

LOG = logging.getLogger(__name__)

# preset key -> (English display label, file extension, kind)
# ``kind`` is "video" or "audio" (audio presets drop the video stream).
RECORDING_FORMATS: "Dict[str, tuple]" = {
    "provider_mkv": ("Provider quality (copy, MKV)", "mkv", "video"),
    "provider_mp4": ("Provider quality (copy, MP4)", "mp4", "video"),
    "x264_mkv": ("x264 re-encode (MKV)", "mkv", "video"),
    "x264_mp4": ("x264 re-encode (MP4)", "mp4", "video"),
    "provider_mka": ("Provider quality (stream copy, MKA)", "mka", "audio"),
    "audio_mp3_v0": ("Audio only (MP3 V0)", "mp3", "audio"),
    "audio_flac": ("Audio only (FLAC)", "flac", "audio"),
    "audio_wav": ("Audio only (WAV)", "wav", "audio"),
    "audio_aac_m4a": ("Audio only (AAC, M4A)", "m4a", "audio"),
    "audio_opus": ("Audio only (Opus)", "opus", "audio"),
}

DEFAULT_RECORDING_FORMAT = "provider_mkv"

# ffmpeg infers the output muxer from the filename extension. Download-style
# captures write to a ``.part`` sibling while running, so the muxer has to be
# forced explicitly (mapping: recording extension -> ffmpeg muxer name).
FORMAT_MUXERS = {
    "mkv": "matroska",
    "mka": "matroska",
    "mp4": "mp4",
    "m4a": "ipod",
    "mp3": "mp3",
    "flac": "flac",
    "wav": "wav",
    "opus": "oga",
}

# Formats whose muxer rewrites the whole output file when it closes. ``+faststart``
# moves the MP4 moov atom in front of the media data, which means ffmpeg reads back
# and rewrites every byte it just captured.
FASTSTART_FORMATS = frozenset({"provider_mp4", "x264_mp4"})

# How long ffmpeg may take to close its container after being asked to stop.
#
# This is not a formality. A provider-quality MP4 finalizes by writing the moov atom
# and then rewriting the entire file to move it to the front, so the cost scales with
# the recording: seconds on an internal SSD, many minutes on the external USB or
# network drives recordings usually live on. Killing ffmpeg partway through leaves a
# file that is ``ftyp`` followed by one enormous ``mdat`` and no moov atom at all --
# "moov atom not found", unplayable, with every byte of a multi-hour capture stranded
# inside it. So we wait for as long as the container can plausibly need, and escalate
# only once ffmpeg is genuinely wedged.
FINALIZE_GRACE_SECONDS = 30.0
FINALIZE_REWRITE_BYTES_PER_SECOND = 8 * 1024 * 1024  # pessimistic: USB 2.0 / SMB share
FINALIZE_TIMEOUT_CAP_SECONDS = 3600.0
TERMINATE_GRACE_SECONDS = 15.0
# On shutdown we ask FFmpeg to stop and give it the same clean-finalize window
# every other stop gets, derived from the size of the capture.  If it is still
# alive after that, it must be terminated: an orphan can keep a provider's only
# stream slot occupied and makes a restarted scheduled recording fail until
# Task Manager is used to kill it.  The constant is the floor for that window.
DETACH_WAIT_SECONDS = 5.0

# ffmpeg's stderr for each recording is kept next to the recordings themselves, so a
# capture that went wrong can still be diagnosed afterwards. URLs, credentials and
# headers are deliberately left in the log: it exists to be read, and stripping the
# stream URL makes 403/timeout diagnoses impossible.
RECORDING_LOG_DIRNAME = "logs"
STDERR_TAIL_LINES = 12
_LOG_TAIL_WINDOW_BYTES = 262144
# ``-loglevel level+datetime+info`` writes lines such as
#   2026-09-19 20:20:07.514 [h264 @ 00000244d66ec580] [error] mmco: unref short failure
# The date is missing when ffmpeg is too old for the ``datetime`` flag, and the
# ``[component @ address]`` prefixes (there can be several) are missing on
# ffmpeg's own messages, so both are optional.
_LOG_LINE_RE = re.compile(
    r"^(?:(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?) )?"
    r"((?:\[[^\]]*\] )*)"
    r"\[(panic|fatal|error|warning|info|verbose|debug|trace)\] ?(.*)$",
    re.IGNORECASE)
_PROBLEM_LEVELS = frozenset({"panic", "fatal", "error", "warning"})
_LOG_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
# Without ``-loglevel repeat`` ffmpeg may fold identical lines into this one.
_REPEATED_RE = re.compile(r"Last message repeated (\d+) times?")
# The first line ffmpeg writes once the output is open: from here on the
# recording is really being written.
_OUTPUT_OPENED_RE = re.compile(r"^Output #\d+")
# How many kinds of problem the summary lists per phase before it stops.
_SUMMARY_MAX_KINDS = 20
# Up to this many occurrences are listed one by one; beyond it only the first
# and last are named.
_SUMMARY_MAX_TIMES = 5
_SUMMARY_MARKER = "# ===== Recording summary ====="
# How many times one kind of problem is placed in time by
# recording_problem_times(); beyond it only the first ones are listed.
_PROBLEM_TIMES_LIMIT = 12

# Stats lines written when a recording runs with ``show_stats``: the dialog
# tails the log for the newest ``time=HH:MM:SS.xx`` to report real progress.
_FFMPEG_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def format_uses_faststart(fmt: str) -> bool:
    return fmt in FASTSTART_FORMATS


def finalize_timeout_seconds(fmt: str, out_path: str) -> float:
    """Seconds to allow ffmpeg to finish writing ``out_path`` after a stop request."""
    timeout = FINALIZE_GRACE_SECONDS
    if format_uses_faststart(fmt):
        try:
            size = os.path.getsize(out_path)
        except OSError:
            size = 0
        timeout += float(size) / FINALIZE_REWRITE_BYTES_PER_SECOND
    return min(timeout, FINALIZE_TIMEOUT_CAP_SECONDS)


def written_size(rec: "Recording") -> int:
    """Bytes ffmpeg has written so far for ``rec`` (0 when unknown)."""
    try:
        return os.path.getsize(rec.written_path)
    except OSError:
        return 0


def parse_ffmpeg_progress(log_path: str) -> Optional[float]:
    """Media seconds ffmpeg has written so far, from the newest ``time=`` line.

    Only recordings started with ``show_stats`` have those lines; anything else
    (or an unreadable log) returns None and the caller falls back to an
    indeterminate display.
    """
    if not log_path:
        return None
    try:
        with open(log_path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _LOG_TAIL_WINDOW_BYTES))
            data = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    last = None
    for match in _FFMPEG_TIME_RE.finditer(data):
        last = match
    if last is None:
        return None
    hours, minutes, seconds = last.groups()
    try:
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None


def format_duration(seconds: Optional[float]) -> str:
    """h:mm:ss / m:ss for a duration, or a placeholder when it is unknown."""
    if not seconds or seconds <= 0:
        return "--:--"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_size(num_bytes: Optional[float]) -> str:
    """Human-readable byte size, or a placeholder when it is unknown."""
    if not num_bytes or num_bytes <= 0:
        return "--"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return "--"


def parse_log_line(line: str) -> Optional[Dict[str, object]]:
    """Split one ffmpeg log line into its time, level, component and message.

    Returns None for lines without a level (the header, stats, ``[q] command
    received``). ``when`` is None when ffmpeg did not time-stamp the line, and
    ``component`` is the first ``[name @ address]`` prefix's name, if any.
    """
    match = _LOG_LINE_RE.match(line.strip())
    if not match:
        return None
    stamp, prefixes, level, message = match.groups()
    when = None
    if stamp:
        try:
            when = datetime.datetime.strptime(
                stamp if "." in stamp else stamp + ".0", _LOG_DATETIME_FORMAT)
        except ValueError:
            when = None
    component = ""
    if prefixes:
        first = prefixes.split("] ", 1)[0].lstrip("[")
        component = first.split(" @ ", 1)[0].strip()
    return {"when": when, "level": level.lower(), "component": component,
            "message": message.strip()}


def strip_log_timestamp(line: str) -> str:
    """A log line minus ffmpeg's date prefix, for dialogs that quote it."""
    line = line.strip()
    match = _LOG_LINE_RE.match(line)
    if match and match.group(1):
        return line[len(match.group(1)):].lstrip()
    return line


def _is_problem_line(line: str) -> bool:
    parsed = parse_log_line(line)
    return bool(parsed) and parsed["level"] in _PROBLEM_LEVELS


def _read_log_lines(path: str) -> List[str]:
    """Every line of a recording log. ffmpeg ends stats lines with a bare CR."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


_LOG_DATETIME_SUPPORT: Dict[str, bool] = {}


def ffmpeg_supports_log_datetime(ffmpeg_path: str) -> bool:
    """Whether this ffmpeg accepts ``-loglevel level+datetime+info``.

    The flag arrived in ffmpeg 7; an older system ffmpeg (Linux) refuses to
    start at all when given it, so ask once and remember the answer. A check
    that could not run at all is not remembered.
    """
    if not ffmpeg_path:
        return False
    cached = _LOG_DATETIME_SUPPORT.get(ffmpeg_path)
    if cached is not None:
        return cached
    creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-loglevel", "level+datetime+info", "-version"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=15, creationflags=creation_flags)
        supported = result.returncode == 0
    except Exception:
        LOG.debug("ffmpeg_supports_log_datetime: check failed", exc_info=True)
        return False
    _LOG_DATETIME_SUPPORT[ffmpeg_path] = supported
    return supported


def recording_log_path(out_dir: str, out_path: str) -> str:
    """Where the full ffmpeg stderr for ``out_path`` is written."""
    base = os.path.splitext(os.path.basename(out_path))[0]
    return os.path.join(out_dir, RECORDING_LOG_DIRNAME, base + ".log")


def read_log_problems(path: str, limit: int = STDERR_TAIL_LINES) -> List[str]:
    """The last few warning/error lines of a recording log, for the finish dialog."""
    if not path:
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > _LOG_TAIL_WINDOW_BYTES:
                handle.seek(size - _LOG_TAIL_WINDOW_BYTES)
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    return [strip_log_timestamp(line) for line in lines if _is_problem_line(line)][-limit:]


def count_log_problems(path: str) -> Dict[str, int]:
    """Count warning/error/fatal lines in a recording log, over the whole file.

    A capture that struggled can log hundreds of reconnect warnings spread
    across a long run, and the tail window the finish dialog reads shows only
    the last dozen. This scans every line so the total is easy to find: it is
    what the app logs and reports when the recording ends, and it can be
    compared across the log files in ``<recordings>/logs``. Lines that are
    neither warnings nor errors do not count. A decoder's own messages
    (``[h264 @ ...] [error] ...``) count like ffmpeg's.
    """
    counts = {"warnings": 0, "errors": 0, "fatals": 0}
    if not path:
        return counts
    summary = summarize_log(path)
    for phase in summary["phases"].values():
        for kind in phase:
            counts[_COUNT_KEYS[kind["level"]]] += kind["count"]
    return counts


_COUNT_KEYS = {"warning": "warnings", "error": "errors", "fatal": "fatals", "panic": "fatals"}


def summarize_log(path: str) -> Dict[str, object]:
    """Group a recording log's problems by kind, split at the start of writing.

    ``phases["opening"]`` holds what ffmpeg reported before the output file was
    opened (joining the stream part-way and reading its start to identify it),
    ``phases["recording"]`` everything after. Each kind is a dict with
    ``level``, ``component``, ``message`` (the first occurrence), ``count`` and
    ``offsets``: seconds since the output opened, one per occurrence, empty
    when ffmpeg did not time-stamp its lines. ``output_opened`` says whether
    the recording got as far as writing at all.
    """
    phases: Dict[str, List[Dict[str, object]]] = {"opening": [], "recording": []}
    index: Dict[tuple, Dict[str, object]] = {}
    opened_at: Optional[datetime.datetime] = None
    output_opened = False
    timestamps = False
    last_kind: Optional[Dict[str, object]] = None
    for line in _read_log_lines(path) if path else []:
        repeated = _REPEATED_RE.search(line)
        if repeated:
            if last_kind is not None:
                extra = int(repeated.group(1))
                last_kind["count"] += extra
                if last_kind["offsets"]:
                    last_kind["offsets"].extend([last_kind["offsets"][-1]] * extra)
            continue
        parsed = parse_log_line(line)
        if parsed is None:
            continue
        if parsed["when"] is not None:
            timestamps = True
        message = str(parsed["message"])
        if not output_opened and parsed["level"] == "info" and _OUTPUT_OPENED_RE.match(message):
            output_opened = True
            opened_at = parsed["when"]
            continue
        if parsed["level"] not in _PROBLEM_LEVELS:
            last_kind = None
            continue
        phase = "recording" if output_opened else "opening"
        level = "fatal" if parsed["level"] == "panic" else str(parsed["level"])
        # Numbers vary between otherwise identical messages (timestamps, sizes).
        key = (phase, level, parsed["component"], re.sub(r"\d+", "#", message))
        kind = index.get(key)
        if kind is None:
            kind = {"level": level, "component": parsed["component"], "message": message,
                    "count": 0, "offsets": []}
            index[key] = kind
            phases[phase].append(kind)
        kind["count"] += 1
        if phase == "recording" and opened_at is not None and parsed["when"] is not None:
            kind["offsets"].append(max(0.0, (parsed["when"] - opened_at).total_seconds()))
        last_kind = kind
    return {"phases": phases, "output_opened": output_opened,
            "timestamps": timestamps and opened_at is not None}


def _clock(seconds: float) -> str:
    """h:mm:ss, always with hours, so times in a list line up."""
    total = int(round(max(0.0, seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _problem_totals(kinds: List[Dict[str, object]]) -> str:
    totals = {"warning": 0, "error": 0, "fatal": 0}
    for kind in kinds:
        totals[str(kind["level"])] += int(kind["count"])
    return "{w}, {e}, {f}".format(
        w=_plural(totals["warning"], "warning"), e=_plural(totals["error"], "error"),
        f=_plural(totals["fatal"], "fatal error"))


def _describe_kind(kind: Dict[str, object]) -> str:
    count = int(kind["count"])
    source = " from {c}".format(c=kind["component"]) if kind["component"] else ""
    text = "{times}: {level}{source}: {message}".format(
        times="once" if count == 1 else f"{count} times",
        level=kind["level"], source=source, message=kind["message"])
    # A burst within one second is one time, not the same time repeated.
    clocks: List[str] = []
    for value in kind["offsets"]:
        if _clock(value) not in clocks:
            clocks.append(_clock(value))
    if clocks:
        if len(clocks) <= _SUMMARY_MAX_TIMES:
            text += ". At " + ", ".join(clocks) + "."
        else:
            text += ". First at {a}, last at {b}.".format(a=clocks[0], b=clocks[-1])
    return text


def format_recording_summary(
    *,
    out_path: str,
    started_at: float,
    ended_at: float,
    planned_seconds: Optional[float],
    written_seconds: Optional[float],
    file_size: Optional[int],
    ending: str,
    summary: Dict[str, object],
) -> List[str]:
    """The lines appended to a recording log once ffmpeg has exited.

    Everything a reader wants first: how long the file should be, how long it
    is, and which problems were logged, grouped by kind and placed in time, so
    nobody has to count repeated decoder lines by hand.
    """
    stamp = "%Y-%m-%d %H:%M:%S"
    lines = [
        _SUMMARY_MARKER,
        "# File: {path}".format(path=out_path),
        "# Started: {t}".format(t=time.strftime(stamp, time.localtime(started_at))),
        "# Ended: {t} (ran for {d})".format(
            t=time.strftime(stamp, time.localtime(ended_at)),
            d=_clock(ended_at - started_at)),
        "# How it ended: {e}".format(e=ending),
    ]
    if planned_seconds and planned_seconds > 0:
        lines.append("# Planned length: {d}".format(d=_clock(planned_seconds)))
    else:
        lines.append("# Planned length: none, recorded until stopped")
    if written_seconds and written_seconds > 0:
        recorded = "# Recorded length: {d}".format(d=_clock(written_seconds))
        if planned_seconds and planned_seconds > 0:
            gap = planned_seconds - written_seconds
            recorded += " ({p:.1f}% of planned".format(p=100.0 * written_seconds / planned_seconds)
            if abs(gap) >= 1:
                recorded += ", {diff} {how}".format(
                    diff=_clock(abs(gap)), how="short" if gap > 0 else "over")
            recorded += ")"
        lines.append(recorded)
    else:
        lines.append("# Recorded length: unknown (ffmpeg did not report it)")
    lines.append("# File size: {s}".format(
        s=format_size(file_size) if file_size else "no file was written"))

    phases = summary["phases"]
    opening, recording = phases["opening"], phases["recording"]
    lines.append("# Problems while opening the stream: {t}".format(
        t=_problem_totals(opening) if opening else "none"))
    if summary["output_opened"]:
        lines.append("# Problems during the recording: {t}".format(
            t=_problem_totals(recording) if recording else "none"))
    else:
        lines.append("# The recording never started writing: ffmpeg did not open the output file.")
    for title, kinds in (("While opening the stream", opening),
                         ("During the recording", recording)):
        if not kinds:
            continue
        lines.append("#")
        lines.append("# {title}:".format(title=title))
        ordered = sorted(kinds, key=lambda k: (-int(k["count"]), str(k["message"])))
        for kind in ordered[:_SUMMARY_MAX_KINDS]:
            lines.append("#   " + _describe_kind(kind))
        if len(ordered) > _SUMMARY_MAX_KINDS:
            lines.append("#   ...and {n} other kinds; see above.".format(
                n=len(ordered) - _SUMMARY_MAX_KINDS))
    if opening and summary["output_opened"]:
        lines.append("#")
        lines.append("# Problems while opening the stream happen before anything is written:")
        lines.append("# ffmpeg joins a live stream part-way through and reads its start to")
        lines.append("# identify it. They are usually harmless.")
    if recording:
        lines.append("#")
        if summary["timestamps"]:
            lines.append("# Times are clock time since the recording started writing.")
        else:
            lines.append("# No times: this ffmpeg cannot time-stamp its log.")
    lines.append("# ===== End of summary =====")
    return lines


def _read_log_and_opened_at(log_path: str):
    """A log's text and the wall clock at its ``Output #`` line."""
    try:
        with open(log_path, "rb") as handle:
            data = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return "", None
    for line in data.splitlines():
        parsed = parse_log_line(line)
        if parsed and parsed["level"] == "info" and _OUTPUT_OPENED_RE.match(
                str(parsed["message"])):
            if parsed["when"] is not None:
                return data, parsed["when"]
            break
    return data, None


def media_at_offset(log_path: str, when_seconds: float,
                    *, window_seconds: float = 30.0) -> Optional[str]:
    """A media timestamp for ``when_seconds`` into the recording, or "".

    The newest ``time=`` stats line logged before ``when_seconds``, as
    h:mm:ss - the position a player counts the file from. Lines come with
    wall-clock stamps only when the recording runs with ``show_stats``. Older
    logs without them get an empty string, so callers fall back to wall time.
    """
    if not log_path or when_seconds < 0:
        return ""
    data, opened_at = _read_log_and_opened_at(log_path)
    return media_at_offset_from(data, opened_at, when_seconds,
                                window_seconds=window_seconds)


def media_at_offset_from(data: str, opened_at: Optional[datetime.datetime],
                         when_seconds: float, *,
                         window_seconds: float = 30.0) -> Optional[str]:
    """``media_at_offset`` over an already-read log (or None for no stamps)."""
    if opened_at is None:
        return ""
    best = ""
    for line in data.splitlines():
        parsed = parse_log_line(line)
        if parsed is None or parsed["when"] is None:
            continue
        offset = max(0.0, (parsed["when"] - opened_at).total_seconds())
        if offset > when_seconds + window_seconds:
            break
        match = _FFMPEG_TIME_RE.search(str(parsed["message"]))
        if match and offset <= when_seconds:
            hours, minutes, seconds = match.groups()
            best = _clock(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
    return best


def recording_problem_times(
    log_path: str, *, max_times: int = _PROBLEM_TIMES_LIMIT
) -> List[Dict[str, object]]:
    """When problems were logged, in seconds into the recording.

    For a listener's verification: a problem kind is one ffmpeg message with
    its numbers folded out (the summary's grouping), so a decoder complaining
    through a minute of bad signal reads as one entry whose times cover it.
    Each kind carries ``clock_times`` (h:mm:ss offsets from the moment ffmpeg
    opened the output file, which is where a player's own clock starts from)
    and ``media_times`` (the newest ``time=`` before each occurrence, which is
    where a player counts the file from). Only warnings, errors and fatals are
    listed, and only up to ``max_times`` of each kind. Returns [] when the log
    holds nothing a listener would care about, and [] when ffmpeg could not
    time-stamp its lines: without the timestamps nothing can be placed.
    """
    if not log_path:
        return []
    try:
        summary = summarize_log(log_path)
    except Exception:
        LOG.debug("recording_problem_times: could not read %s", log_path,
                  exc_info=True)
        return []
    if not summary.get("timestamps"):
        return []
    data, opened_at = _read_log_and_opened_at(log_path)
    if opened_at is None:
        return []
    results: List[Dict[str, object]] = []
    for kind in summary["phases"].get("recording") or []:
        clocks = kind.get("offsets") or []
        if not clocks:
            continue
        placed = clocks[:max_times]
        stamps = [_clock(value) for value in placed]
        media = [media_at_offset_from(data, opened_at, value)
                 for value in placed]
        jump_times = list(dict.fromkeys(
            media_time or clock_time
            for media_time, clock_time in zip(media, stamps)
        ))
        results.append({
            "message": str(kind["message"]),
            "level": str(kind["level"]),
            "count": int(kind["count"]),
            "clock_times": stamps,
            "media_times": [stamp for stamp in media if stamp],
            "jump_times": jump_times,
        })
    results.sort(key=lambda kind: (not kind["clock_times"], kind["clock_times"]))
    return results


def get_ffmpeg_path():
    """Resolve ffmpeg lazily so importing recorder stays cheap at startup."""
    from stream_proxy import get_ffmpeg_path as _get_ffmpeg_path

    return _get_ffmpeg_path()


def format_extension(fmt: str) -> str:
    entry = RECORDING_FORMATS.get(fmt) or RECORDING_FORMATS[DEFAULT_RECORDING_FORMAT]
    return entry[1]


def sanitize_filename(name: Optional[str]) -> str:
    """Turn an arbitrary channel/show title into a safe base filename."""
    text = (name or "").strip()
    if not text:
        text = "Recording"
    # Drop characters illegal on Windows/POSIX filesystems and control chars.
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = "Recording"
    return text[:120]


def _header_input_args(headers: Optional[Dict[str, object]]) -> List[str]:
    """Build ffmpeg *input* options (placed before ``-i``) from channel headers.

    ``headers`` is the dict produced by ``http_headers.channel_http_headers``. We emit
    the dedicated ``-user_agent`` / ``-referer`` options (most reliable) and fold every
    other header into a single ``-headers`` CRLF-joined blob.
    """
    from stream_proxy import normalize_request_headers

    normalized = normalize_request_headers(headers, add_default_user_agent=True)
    args: List[str] = []
    extra_lines: List[str] = []
    for name, value in normalized.items():
        if not value:
            continue
        if name.lower() == "user-agent":
            args += ["-user_agent", str(value)]
        elif name.lower() == "referer":
            args += ["-referer", str(value)]
        else:
            extra_lines.append(f"{name}: {value}")
    if extra_lines:
        args += ["-headers", "".join(line + "\r\n" for line in extra_lines)]
    return args


def _is_http_url(url: str) -> bool:
    return str(url or "").lower().startswith(("http://", "https://"))


def _close_stdin(proc: "subprocess.Popen") -> None:
    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        LOG.debug("RecordingManager._close_stdin: ignored exception", exc_info=True)


def build_ffmpeg_command(
    ffmpeg_path: str,
    url: str,
    out_path: str,
    fmt: str,
    headers: Optional[Dict[str, object]] = None,
    *,
    duration: Optional[float] = None,
    show_stats: bool = False,
    force_format: Optional[str] = None,
    audio_track: Optional[int] = None,
    audio_track_count: int = 0,
    copy_to_stdout: bool = False,
    log_datetime: bool = False,
) -> List[str]:
    """Construct the full ffmpeg argument list for one recording.

    ``audio_track`` is the input audio stream to keep (its ``0:a:N`` position)
    and ``audio_track_count`` how many the input has; None leaves the choice
    to ffmpeg, as before. ``copy_to_stdout`` adds a second output: an untouched
    MPEG-TS copy of the input on stdout, for the built-in player to watch.
    ``log_datetime`` time-stamps every log line (see
    ``ffmpeg_supports_log_datetime``), which is what places each problem in
    time in the log's closing summary.
    """
    if fmt not in RECORDING_FORMATS:
        fmt = DEFAULT_RECORDING_FORMAT

    loglevel = "level+datetime+info" if log_datetime else "level+info"
    cmd: List[str] = [ffmpeg_path, "-hide_banner", "-loglevel", loglevel, "-y"]
    if show_stats:
        # Write periodic stats lines into the log so a progress dialog can tail
        # them for the captured time. One line per second keeps logs small.
        cmd += ["-stats_period", "1"]
    else:
        cmd += ["-nostats"]
    # ``-rw_timeout`` is a generic protocol option; the rest are HTTP-only, and
    # ffmpeg refuses to open any other input (rtmp://, rtsp://, udp://) when
    # given them ("Option reconnect not found"), so those channels never
    # recorded at all.
    cmd += ["-rw_timeout", "15000000"]
    if _is_http_url(url):
        # Reconnect/robustness for long-running HTTP(S) live captures.
        cmd += [
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
        ]
        # Per-channel auth headers must precede -i to apply to the input.
        cmd += _header_input_args(headers)
    elif str(url).lower().startswith("rtsp://"):
        # Same transport the built-in player asks for.
        cmd += ["-rtsp_transport", "tcp"]
    cmd += ["-i", url]

    if duration and duration > 0:
        cmd += ["-t", str(float(duration))]

    # An audio-only file holds one track, and left to itself ffmpeg keeps the
    # one with the most channels - not the one the user listens to, and not
    # the audio description. Name it.
    pick_audio = ["-map", f"0:a:{int(audio_track)}"] if audio_track is not None else []

    if fmt == "provider_mp4":
        # Only video and audio: MP4 cannot carry the DVB teletext/subtitle and data
        # streams that IPTV transport streams routinely include, so "-map 0" with
        # "-c:s copy" made ffmpeg fail at header write ("Could not find tag for codec
        # ... not currently supported in container") and leave a 0-byte recording.
        # MKV keeps everything; that is what provider_mkv is for.
        cmd += ["-map", "0:v?", "-map", "0:a?", "-dn", "-sn",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    elif fmt == "provider_mkv":
        cmd += ["-map", "0", "-c", "copy"]
    elif fmt == "provider_mka":
        # Original-quality radio: copy every audio stream verbatim into a
        # Matroska Audio container. Video, subtitle and data tracks are left
        # behind (``-vn -sn -dn`` as well as the audio-only map), and nothing
        # is re-encoded: a source that cannot be copied fails here instead of
        # silently becoming a transcode.
        cmd += ["-map", "0:a?", "-vn", "-sn", "-dn", "-c:a", "copy"]
    elif fmt in ("x264_mp4", "x264_mkv"):
        cmd += [
            "-map", "0:v?", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
        ]
    elif fmt == "audio_wav":
        cmd += pick_audio + ["-vn", "-c:a", "pcm_s16le"]
    elif fmt == "audio_flac":
        cmd += pick_audio + ["-vn", "-c:a", "flac"]
    elif fmt == "audio_mp3_v0":
        cmd += pick_audio + ["-vn", "-c:a", "libmp3lame", "-q:a", "0"]
    elif fmt == "audio_aac_m4a":
        cmd += pick_audio + ["-vn", "-c:a", "aac", "-b:a", "256k"]
    elif fmt == "audio_opus":
        cmd += pick_audio + ["-vn", "-c:a", "libopus", "-b:a", "160k"]
    else:  # pragma: no cover - defensive, normalized upstream
        cmd += ["-map", "0", "-c", "copy"]

    if audio_track is not None and RECORDING_FORMATS[fmt][2] == "video":
        # Video formats keep every audio track; the chosen one becomes the
        # default, so a player opening the file starts on it.
        for index in range(max(int(audio_track_count), int(audio_track) + 1)):
            cmd += [f"-disposition:a:{index}", "+default" if index == audio_track else "-default"]

    if format_uses_faststart(fmt):
        cmd += ["-movflags", "+faststart"]

    if force_format:
        # The output name may not have a recognizable extension (``.part``),
        # so tell ffmpeg which muxer to use.
        cmd += ["-f", force_format]
    cmd.append(out_path)
    if copy_to_stdout:
        # A second output from the SAME input: the stream as it arrives, for
        # the built-in player (see recording_relay). Watching while recording
        # then uses one provider connection instead of two. Output options
        # apply per output, so an audio-only file still leaves the player
        # its picture.
        cmd += ["-map", "0:v?", "-map", "0:a?", "-c", "copy", "-f", "mpegts", "pipe:1"]
    return cmd


# Dispositions ffmpeg prints after an input stream, e.g. "(visual impaired)".
_DISPOSITIONS = {
    "default", "dub", "original", "comment", "lyrics", "karaoke", "forced",
    "hearing impaired", "visual impaired", "clean effects", "attached pic",
    "timed thumbnails", "non diegetic", "captions", "descriptions", "metadata",
    "dependent", "still image", "multilayer",
}
_STREAM_LINE_RE = re.compile(r"^\s*Stream #\d+:\d+(?:\[[^\]]*\])?(?:\(([^)]*)\))?: (\w+): (.*)$")
_STREAM_META_RE = re.compile(r"^\s+(title|comment)\s*:\s*(.*)$")
_AUDIO_DESCRIPTION_DISPOSITIONS = {"visual impaired", "descriptions"}


def parse_audio_streams(report: str) -> List[Dict[str, object]]:
    """The audio streams in ffmpeg's ``-i`` report, in ``0:a:N`` order.

    Each is ``{"language", "title", "dispositions"}``. DVB marks an audio
    description track "visual impaired" (ffmpeg adds "descriptions"), which is
    what finds it when its name says nothing; HLS renditions carry their name
    as a "comment".
    """
    streams: List[Dict[str, object]] = []
    current: Optional[Dict[str, object]] = None
    for line in (report or "").splitlines():
        match = _STREAM_LINE_RE.match(line)
        if match:
            current = None
            if match.group(2) != "Audio":
                continue
            flags = set(re.findall(r"\(([a-z][a-z ]*)\)", match.group(3)))
            current = {"language": (match.group(1) or "").strip(), "title": "",
                       "dispositions": flags & _DISPOSITIONS}
            streams.append(current)
            continue
        if current is not None and not current["title"]:
            meta = _STREAM_META_RE.match(line)
            if meta:
                current["title"] = meta.group(2).strip()
    return streams


def audio_stream_label(position: int, stream: Dict[str, object]) -> str:
    """A name for one probed stream, in the words the player's rules match."""
    parts = [f"Track {position + 1}"]
    if stream.get("language"):
        parts.append(f"[{stream['language']}]")
    if stream.get("title"):
        parts.append(str(stream["title"]))
    if set(stream.get("dispositions") or ()) & _AUDIO_DESCRIPTION_DISPOSITIONS:
        parts.append("audio description")
    return " - ".join(parts)


def probe_stream_report(url: str, headers: Optional[Dict[str, object]] = None,
                        *, timeout: float = 20.0,
                        on_popen: Optional[Callable[[Any], None]] = None) -> str:
    """Ask a stream to describe itself; "" when it cannot answer in time.

    A plain ``ffmpeg -i`` with no output: it opens the input, reports what it
    found on stderr and exits. A network round trip, so never on the UI
    thread. The raw report is returned so callers can parse audio tracks,
    media types, or anything else from the same single probe. The optional
    ``on_popen`` hook receives the live Popen so a caller can terminate a
    probe early -- a recording starting on a one-stream provider preempts the
    background media-type probe instead of racing it for the slot.
    """
    cmd = [get_ffmpeg_path(), "-hide_banner", "-nostdin",
           "-rw_timeout", "10000000", "-analyzeduration", "3000000"]
    if _is_http_url(url):
        # HTTP-only options: any other input (a file, udp://) rejects them
        # outright ("Option user_agent not found") and lists nothing.
        cmd += _header_input_args(headers)
    cmd += ["-i", url]
    creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                                creationflags=creation_flags)
    except OSError as exc:
        LOG.info("Stream probe failed for %s: %s", url, exc)
        return ""
    if on_popen is not None:
        try:
            on_popen(proc)
        except Exception:
            LOG.debug("probe_stream_report: on_popen hook failed", exc_info=True)
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, stderr = proc.communicate()
        LOG.info("Stream probe timed out for %s", url)
        return ""
    except OSError as exc:
        LOG.info("Stream probe failed for %s: %s", url, exc)
        return ""
    return (stderr or b"").decode("utf-8", errors="replace")


def probe_audio_streams(url: str, headers: Optional[Dict[str, object]] = None,
                        *, timeout: float = 20.0) -> List[Dict[str, object]]:
    """Ask a stream which audio tracks it carries; [] when it cannot say in time.

    A plain ``ffmpeg -i`` with no output: it opens the input, reports what it
    found and exits. A network round trip, so never on the UI thread.
    """
    return parse_audio_streams(probe_stream_report(url, headers, timeout=timeout))


def probe_media_type(url: str, headers: Optional[Dict[str, object]] = None,
                     *, timeout: float = 20.0,
                     on_popen: Optional[Callable[[Any], None]] = None) -> str:
    """``"audio"``/``"video"``/``"unknown"`` for what the stream carries.

    Shares one ``ffmpeg -i`` probe with the audio-track listing; an attached
    picture or cover-art track never counts as video. Never on the UI thread.
    ``on_popen`` is passed through to :func:`probe_stream_report` so the
    probe can be preempted.
    """
    from media_type import classify_probe_report
    return classify_probe_report(
        probe_stream_report(url, headers, timeout=timeout, on_popen=on_popen))


class Recording:
    """A single in-progress (or finished) recording."""

    def __init__(self, rec_id: int, key: str, url: str, title: str, fmt: str, out_path: str,
                 process: "subprocess.Popen", metadata: Optional[Dict[str, object]] = None,
                 log_path: str = "", command: Optional[List[str]] = None,
                 partial_path: str = "", connection_key: str = ""):
        self.id = rec_id
        self.key = key  # stable channel identity (resolved URL can change per resolve)
        # Some providers permit exactly one media session per account.  This
        # separate key is intentionally provider-scoped, unlike ``key`` above.
        self.connection_key = connection_key
        self.url = url
        self.title = title
        self.fmt = fmt
        self.out_path = out_path
        # For download-style captures (``keep_partial=False``) ffmpeg actually
        # writes to this sibling ``.part`` path and the file is renamed to
        # ``out_path`` only when it completes cleanly.
        self.partial_path = partial_path
        self.process = process
        self.started_at = time.time()
        self.stderr_tail: List[str] = []
        self.stopped_by_user = False
        self.stopping = False
        self.metadata = metadata or {}
        self.log_path = log_path
        self.command = list(command or [])
        # Set when ffmpeg had to be killed before it finished writing the container,
        # which is the one case where the output file is expected to be unplayable.
        self.finalize_timed_out = False
        self.detached = False
        # The local relay the built-in player watches this recording through,
        # when it was started with ``share_with_player``.
        self.relay: Any = None
        # Filled in when ffmpeg exits: how many warnings/errors/fatals the
        # whole recording log holds, so a capture that struggled is easy to
        # spot without reading the log yourself.
        self.problem_counts: Optional[Dict[str, int]] = None
        # Filled in when ffmpeg exits: how much media the newest ``time=``
        # stats line reported. A truncated transfer (the provider closes the
        # connection mid-file) still exits 0, so this is what tells a
        # short-but-"clean" download apart from a complete one.
        self.media_written_seconds: Optional[float] = None
        # How long the capture was meant to run, when that is known: the
        # requested duration, or a scheduled job's stop time. Only for the
        # log's closing summary.
        self.planned_seconds: Optional[float] = None

    @property
    def written_path(self) -> str:
        """The path ffmpeg is actually writing to (the .part file if any)."""
        return self.partial_path or self.out_path


def _planned_seconds(duration: Optional[float], metadata: Dict[str, object],
                     started_at: float) -> Optional[float]:
    """How long a capture is meant to run: its duration, or until its stop time."""
    if duration and duration > 0:
        return float(duration)
    try:
        stop_ts = float(metadata.get("planned_stop_ts") or 0)
    except (TypeError, ValueError):
        return None
    if stop_ts > started_at:
        return stop_ts - started_at
    return None


class RecordingManager:
    """Tracks and controls ffmpeg recording subprocesses."""

    def __init__(self):
        self._lock = threading.Lock()
        self._recordings: "Dict[int, Recording]" = {}
        self._reserved_connection_keys = set()
        # Output paths chosen for recordings that are still starting.
        self._reserved_paths = set()
        self._next_id = 1

    # -- queries -----------------------------------------------------------
    def list_active(self) -> List[Recording]:
        with self._lock:
            return [r for r in self._recordings.values() if r.process and r.process.poll() is None]

    def has_active(self) -> bool:
        return bool(self.list_active())

    def is_recording(self, key: str) -> bool:
        if not key:
            return False
        return any(r.key == key for r in self.list_active())

    def has_active_connection(self, connection_key: str) -> bool:
        """Whether a provider-scoped exclusive recording is already running."""
        return bool(connection_key and any(
            r.connection_key == connection_key for r in self.list_active()))

    # -- lifecycle ---------------------------------------------------------
    def start(
        self,
        url: str,
        display_name: str,
        fmt: str,
        headers: Optional[Dict[str, object]],
        out_dir: str,
        *,
        key: Optional[str] = None,
        metadata: Optional[Dict[str, object]] = None,
        on_finish: Optional[Callable[[Recording, int], None]] = None,
        duration: Optional[float] = None,
        show_stats: bool = True,
        keep_partial: bool = True,
        file_time: Optional[datetime.datetime] = None,
        audio_track: Optional[int] = None,
        audio_track_count: int = 0,
        share_with_player: bool = False,
        connection_key: str = "",
    ) -> Recording:
        if not url:
            raise ValueError("No stream URL to record.")
        if fmt not in RECORDING_FORMATS:
            fmt = DEFAULT_RECORDING_FORMAT

        # Check before creating files or opening ffmpeg.  A scheduled and a
        # manual recording use different recording keys, so ``is_recording``
        # alone cannot prevent two connections to a one-stream provider.
        if self.has_active_connection(connection_key):
            raise RuntimeError("A recording is already using this provider's only stream.")

        os.makedirs(out_dir, exist_ok=True)
        with self._lock:
            out_path = self._unique_output_path(out_dir, display_name, format_extension(fmt),
                                                when=file_time)
            # Held until the recording is registered: ffmpeg only creates its
            # file once the input opens, which can be seconds away.
            self._reserved_paths.add(out_path)
        try:
            return self._start_reserved(
                url, display_name, fmt, headers, out_dir, out_path,
                key=key, metadata=metadata, on_finish=on_finish, duration=duration,
                show_stats=show_stats, keep_partial=keep_partial, audio_track=audio_track,
                audio_track_count=audio_track_count, share_with_player=share_with_player,
                connection_key=connection_key)
        finally:
            with self._lock:
                self._reserved_paths.discard(out_path)

    def _start_reserved(self, url, display_name, fmt, headers, out_dir, out_path, *, key,
                        metadata, on_finish, duration, show_stats, keep_partial,
                        audio_track, audio_track_count, share_with_player,
                        connection_key) -> Recording:
        # ffmpeg cannot resume a partial file, so for download-style captures the
        # output goes to a ``.part`` sibling and is renamed into place only when
        # the download completes; a canceled or failed run leaves nothing behind.
        # Live captures keep their name from the start (stopping one intentionally
        # keeps what was captured so far).
        partial_path = "" if keep_partial else out_path + ".part"
        force_format = FORMAT_MUXERS.get(format_extension(fmt)) if partial_path else None
        ffmpeg_path = get_ffmpeg_path()
        cmd = build_ffmpeg_command(ffmpeg_path, url, partial_path or out_path, fmt, headers,
                                   duration=duration, show_stats=show_stats,
                                   force_format=force_format, audio_track=audio_track,
                                   audio_track_count=audio_track_count,
                                   copy_to_stdout=share_with_player,
                                   log_datetime=ffmpeg_supports_log_datetime(ffmpeg_path))
        LOG.info("Starting recording: %s -> %s (%s)", display_name, out_path, fmt)
        if fmt == "provider_mka":
            # Say it plainly in the log: the MKA preset preserves the source
            # audio via stream copy and never transcodes.
            LOG.info("MKA recording: audio stream(s) copied verbatim, no re-encode")
        if audio_track is not None:
            LOG.info("Recording audio track %d of %d", audio_track + 1, audio_track_count)

        # ffmpeg writes its diagnostics straight into the log file rather than into a
        # pipe we drain. That keeps the complete stderr for every recording, and it
        # means the log survives even when ffmpeg has to be terminated on exit.
        log_path = recording_log_path(out_dir, out_path)
        log_handle = self._open_log(log_path, cmd, url)
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        with self._lock:
            if connection_key and (connection_key in self._reserved_connection_keys or any(
                    r.connection_key == connection_key and r.process and r.process.poll() is None
                    for r in self._recordings.values())):
                if log_handle:
                    log_handle.close()
                raise RuntimeError("A recording is already using this provider's only stream.")
            if connection_key:
                self._reserved_connection_keys.add(connection_key)
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE if share_with_player else subprocess.DEVNULL,
                stderr=log_handle if log_handle else subprocess.PIPE,
                creationflags=creation_flags,
            )
        except Exception:
            if log_handle:
                log_handle.close()
            with self._lock:
                self._reserved_connection_keys.discard(connection_key)
            raise
        if log_handle:
            # The child owns the descriptor now; ours would only pin the file open.
            log_handle.close()
        else:
            log_path = ""

        with self._lock:
            rec_id = self._next_id
            self._next_id += 1
            rec = Recording(rec_id, key or url, url, display_name, fmt, out_path, process,
                            metadata, log_path=log_path, command=cmd, partial_path=partial_path,
                            connection_key=connection_key)
            rec.planned_seconds = _planned_seconds(duration, rec.metadata, rec.started_at)
            self._recordings[rec_id] = rec
            self._reserved_connection_keys.discard(connection_key)
        if share_with_player:
            from recording_relay import RecordingRelay
            try:
                rec.relay = RecordingRelay(process.stdout)
            except Exception:
                # Nothing would read ffmpeg's stdout copy, so the pipe would fill
                # and stall the recording itself. Give up on it cleanly instead.
                LOG.exception("Could not start the player relay for %s", out_path)
                self._abandon_start(rec)
                raise

        if not log_path:
            threading.Thread(target=self._drain_stderr, args=(rec,), daemon=True).start()
        threading.Thread(target=self._watch, args=(rec, on_finish), daemon=True).start()
        return rec

    def stop(self, rec_id: int, *, wait: bool = False, detach: bool = False) -> bool:
        """Stop one recording. False when the id is not (or no longer) active.

        The caller has to be able to tell "stopped" from "there was nothing
        to stop": the scheduled-recording path falls back to stopping by key
        when the id no longer resolves.
        """
        with self._lock:
            rec = self._recordings.get(rec_id)
        if not rec:
            return False
        self._graceful_stop(rec, wait=wait, detach=detach)
        return True

    def stop_key(self, key: str, *, wait: bool = False, detach: bool = False) -> int:
        stopped = 0
        for rec in self.list_active():
            if rec.key == key:
                self._graceful_stop(rec, wait=wait, detach=detach)
                stopped += 1
        return stopped

    def stop_all(self, *, wait: bool = False, detach: bool = False) -> int:
        """Stop every active recording.

        ``detach`` is for application shutdown: FFmpeg gets a short clean-finalize
        window, then is forcibly stopped if it remains alive.
        """
        active = self.list_active()
        for rec in active:
            self._graceful_stop(rec, wait=wait, detach=detach)
        return len(active)

    # -- internals ---------------------------------------------------------
    def _unique_output_path(self, out_dir: str, display_name: str, ext: str,
                            when: Optional[datetime.datetime] = None) -> str:
        base = sanitize_filename(display_name)
        # A download of something that already aired is named for when it
        # aired, to the minute as the EPG lists it; a live capture for the
        # moment it started.
        stamp = when.strftime("%Y-%m-%d %H-%M") if when else time.strftime("%Y-%m-%d %H-%M-%S")
        # Callers hold ``self._lock``. A download writes to ``<name>.part`` and
        # ffmpeg creates nothing until its input opens, so the finished name
        # alone does not show that a path is in use.
        in_use = set(self._reserved_paths)
        for rec in self._recordings.values():
            in_use.add(os.path.normcase(rec.out_path))
        in_use = {os.path.normcase(path) for path in in_use}

        def taken(path: str) -> bool:
            return (os.path.normcase(path) in in_use or os.path.exists(path)
                    or os.path.exists(path + ".part"))

        candidate = os.path.join(out_dir, f"{base} - {stamp}.{ext}")
        counter = 2
        while taken(candidate):
            candidate = os.path.join(out_dir, f"{base} - {stamp} ({counter}).{ext}")
            counter += 1
        return candidate

    def _abandon_start(self, rec: Recording) -> None:
        """Undo a start that failed after ffmpeg was already launched."""
        proc = rec.process
        try:
            proc.kill()
            proc.wait(timeout=TERMINATE_GRACE_SECONDS)
        except Exception:
            LOG.debug("RecordingManager._abandon_start: ignored exception", exc_info=True)
        _close_stdin(proc)
        with self._lock:
            self._recordings.pop(rec.id, None)
        if rec.partial_path:
            try:
                os.remove(rec.partial_path)
            except OSError:
                LOG.debug("RecordingManager._abandon_start: ignored exception", exc_info=True)

    def _open_log(self, log_path: str, cmd: List[str], url: str):
        """Open the per-recording ffmpeg log, or return None if we cannot write one."""
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            handle = open(log_path, "wb")
        except Exception:
            LOG.debug("RecordingManager._open_log: ignored exception", exc_info=True)
            return None
        try:
            # Keep the exact command line, URLs, headers and all: the log exists
            # for troubleshooting, and masking the input URL hides the details a
            # 403 or a timeout diagnosis needs.
            header = "# %s\n# ffmpeg %s\n\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), subprocess.list2cmdline(cmd[1:]))
            handle.write(header.encode("utf-8", errors="replace"))
            handle.flush()
        except Exception:
            LOG.debug("RecordingManager._open_log: ignored exception", exc_info=True)
        return handle

    def _drain_stderr(self, rec: Recording) -> None:
        proc = rec.process
        if not proc or not proc.stderr:
            return
        try:
            for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").strip()
                if line and _is_problem_line(line):
                    rec.stderr_tail.append(line)
                    rec.stderr_tail = rec.stderr_tail[-STDERR_TAIL_LINES:]
        except Exception:
            LOG.debug("RecordingManager._drain_stderr: ignored exception", exc_info=True)

    def _watch(self, rec: Recording, on_finish: Optional[Callable[[Recording, int], None]]) -> None:
        proc = rec.process
        if proc:
            try:
                proc.wait()
            except Exception:
                LOG.debug("RecordingManager._watch: ignored exception", exc_info=True)
            _close_stdin(proc)
        if rec.relay is not None:
            rec.relay.close()
        rc = proc.returncode if proc else -1
        if rec.log_path:
            # Deliberately not rewritten: the log keeps the stream URL and
            # credentials so a failed capture can be diagnosed from it.
            rec.stderr_tail = read_log_problems(rec.log_path)
            rec.problem_counts = count_log_problems(rec.log_path)
            if any(rec.problem_counts.values()):
                LOG.info(
                    "Recording log problem summary for %s: %d warnings, "
                    "%d errors, %d fatal errors (full detail in %s)",
                    rec.out_path, rec.problem_counts["warnings"],
                    rec.problem_counts["errors"], rec.problem_counts["fatals"],
                    rec.log_path)
        # How much media ffmpeg had actually written when it exited, from the
        # newest ``time=`` stats line (None when the log carries none).
        rec.media_written_seconds = parse_ffmpeg_progress(rec.log_path) if rec.log_path else None
        self._settle_partial_output(rec, rc)
        if rec.log_path:
            self._append_log_summary(rec, rc)
        with self._lock:
            self._recordings.pop(rec.id, None)
        LOG.info("Recording finished: %s (rc=%s, log=%s)", rec.out_path, rc, rec.log_path or "-")
        if on_finish:
            try:
                on_finish(rec, rc if rc is not None else -1)
            except Exception:
                LOG.exception("Recording on_finish callback failed")

    @staticmethod
    def _append_log_summary(rec: Recording, rc: Optional[int]) -> None:
        """Close the recording's log with a readable summary of how it went."""
        try:
            path = rec.out_path if os.path.exists(rec.out_path) else rec.written_path
            try:
                size: Optional[int] = os.path.getsize(path)
            except OSError:
                size = None
            if rec.finalize_timed_out or rec.detached:
                ending = ("ffmpeg had to be stopped before it finished writing the file "
                          "(exit code {rc}); the file may be incomplete.").format(rc=rc)
            elif rec.stopped_by_user:
                ending = "stopped on request (exit code {rc}).".format(rc=rc)
            elif rc == 0:
                ending = "finished normally."
            else:
                ending = "ffmpeg failed (exit code {rc}).".format(rc=rc)
            lines = format_recording_summary(
                out_path=path if size is not None else rec.out_path,
                started_at=rec.started_at,
                ended_at=time.time(),
                planned_seconds=rec.planned_seconds,
                written_seconds=rec.media_written_seconds,
                file_size=size,
                ending=ending,
                summary=summarize_log(rec.log_path),
            )
            with open(rec.log_path, "ab") as handle:
                handle.write(("\n" + "\n".join(lines) + "\n").encode("utf-8", errors="replace"))
        except Exception:
            LOG.debug("RecordingManager._append_log_summary: ignored exception", exc_info=True)

    def _settle_partial_output(self, rec: Recording, rc: int) -> None:
        """Rename a download's ``.part`` output into place, or discard it.

        Used when ``keep_partial=False``: only a clean, finished capture is
        worth a file in the recordings folder. ffmpeg cannot resume a partial
        file, so anything else (canceled, failed, or finalized under duress)
        would be unplayable junk and is deleted instead.
        """
        if not rec.partial_path:
            return
        keep = rc == 0 and not rec.stopped_by_user and not rec.finalize_timed_out
        if keep:
            try:
                os.replace(rec.partial_path, rec.out_path)
                return
            except OSError:
                LOG.exception("Could not finalize download output %s", rec.out_path)
        try:
            os.remove(rec.partial_path)
        except OSError:
            LOG.debug("RecordingManager._settle_partial_output: ignored exception", exc_info=True)

    @staticmethod
    def _stop_for_exit(rec: Recording, proc: "subprocess.Popen") -> None:
        """Shutdown: a clean-finalize window, then terminate, then kill.

        Never orphan ffmpeg: it can keep the provider stream open after the
        application is gone, so the scheduler re-arms the job at next launch and
        starts a second competing capture.

        The window is the same size-derived finalization budget every other
        stop gets, not a flat few seconds: a faststart MP4 rewrites the whole
        file when it finalizes, and killing it mid-rewrite leaves the capture
        unplayable with every byte of it stranded inside.
        """
        budget = max(DETACH_WAIT_SECONDS, finalize_timeout_seconds(rec.fmt, rec.written_path))
        try:
            proc.wait(timeout=budget)
            return
        except Exception:
            LOG.warning("ffmpeg did not stop %s within %.0fs during shutdown; "
                        "terminating it.", rec.out_path, budget)
        rec.detached = True
        try:
            proc.terminate()
            proc.wait(timeout=TERMINATE_GRACE_SECONDS)
            return
        except Exception:
            LOG.warning("ffmpeg did not terminate %s; killing it.", rec.out_path)
        try:
            proc.kill()
            proc.wait(timeout=TERMINATE_GRACE_SECONDS)
        except Exception:
            LOG.exception("Could not kill ffmpeg during shutdown: %s", rec.out_path)

    def _graceful_stop(self, rec: Recording, *, wait: bool = False, detach: bool = False) -> None:
        proc = rec.process
        if not proc or proc.poll() is not None:
            # ffmpeg is already gone: the capture finished on its own. Saying
            # the user stopped it would make a finished download look
            # discarded, and the finished file was deleted for that reason.
            return
        rec.stopped_by_user = True
        if rec.stopping:
            if detach:
                # Exit while an earlier stop is still finalizing (a big MP4 can
                # take minutes). Its own thread dies with the app, so without
                # this ffmpeg outlived us and held the provider's stream slot.
                self._stop_for_exit(rec, proc)
            elif wait:
                try:
                    proc.wait(timeout=finalize_timeout_seconds(rec.fmt, rec.out_path))
                except Exception:
                    LOG.debug("RecordingManager._graceful_stop: ignored exception", exc_info=True)
            return
        rec.stopping = True

        def _finalize():
            # Ask ffmpeg to quit cleanly so the container is finalized (MP4 moov atom,
            # MKV cues).
            try:
                if proc.stdin:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
                    proc.stdin.close()
            except Exception:
                LOG.debug("RecordingManager._graceful_stop._finalize: ignored exception", exc_info=True)

            if detach:
                self._stop_for_exit(rec, proc)
                return

            # Finalizing is disk-bound and scales with the size of the capture, so the
            # budget is derived from the file rather than fixed. Terminating early here
            # is what produced unplayable MP4s: ffmpeg had rewritten the mdat header but
            # had not yet written the moov atom, so nothing could open the result.
            timeout = finalize_timeout_seconds(rec.fmt, rec.written_path)
            try:
                proc.wait(timeout=timeout)
                return
            except Exception:
                LOG.warning("ffmpeg has not finalized %s after %.0fs; terminating it. "
                            "The file may be incomplete.", rec.out_path, timeout)
            rec.finalize_timed_out = True
            try:
                proc.terminate()
                proc.wait(timeout=TERMINATE_GRACE_SECONDS)
                return
            except Exception:
                LOG.debug("RecordingManager._graceful_stop._finalize: ignored exception", exc_info=True)
            try:
                proc.kill()
            except Exception:
                LOG.debug("RecordingManager._graceful_stop._finalize: ignored exception", exc_info=True)

        if wait:
            _finalize()
        else:
            threading.Thread(target=_finalize, daemon=True).start()
