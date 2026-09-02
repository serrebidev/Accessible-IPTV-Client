"""Stream recording engine for Accessible IPTV Client.

GUI-free. Drives ffmpeg subprocesses that capture a resolved stream URL to disk.
Three families of output are supported (see ``RECORDING_FORMATS``):

* provider quality (stream copy) in MKV or MP4,
* x264 re-encode (H.264 + AAC) in MKV or MP4,
* audio only (WAV / FLAC / MP3 V0 / AAC / Opus).

The active format is a persistent setting chosen elsewhere; this module just turns a
format key + URL + per-channel HTTP headers into a running ffmpeg process and tracks it.
"""

import logging
import os
import re
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional

LOG = logging.getLogger(__name__)

# preset key -> (English display label, file extension, kind)
# ``kind`` is "video" or "audio" (audio presets drop the video stream).
RECORDING_FORMATS: "Dict[str, tuple]" = {
    "provider_mkv": ("Provider quality (copy, MKV)", "mkv", "video"),
    "provider_mp4": ("Provider quality (copy, MP4)", "mp4", "video"),
    "x264_mkv": ("x264 re-encode (MKV)", "mkv", "video"),
    "x264_mp4": ("x264 re-encode (MP4)", "mp4", "video"),
    "audio_mp3_v0": ("Audio only (MP3 V0)", "mp3", "audio"),
    "audio_flac": ("Audio only (FLAC)", "flac", "audio"),
    "audio_wav": ("Audio only (WAV)", "wav", "audio"),
    "audio_aac_m4a": ("Audio only (AAC, M4A)", "m4a", "audio"),
    "audio_opus": ("Audio only (Opus)", "opus", "audio"),
}

DEFAULT_RECORDING_FORMAT = "provider_mkv"

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
# On shutdown we ask ffmpeg to stop, wait briefly, then leave it alone. It is a separate
# process and finishes the container on its own; blocking the GUI thread for the full
# finalize timeout would look like a hang, and killing it would corrupt the recording.
DETACH_WAIT_SECONDS = 5.0

# ffmpeg's stderr for each recording is kept next to the recordings themselves, so a
# capture that went wrong can still be diagnosed afterwards.
RECORDING_LOG_DIRNAME = "logs"
LOG_URL_PLACEHOLDER = "<stream url>"
STDERR_TAIL_LINES = 12
_LOG_TAIL_WINDOW_BYTES = 262144
# ``-loglevel level+info`` prefixes every line with its severity.
_PROBLEM_LINE_RE = re.compile(r"^\[(?:panic|fatal|error|warning)\]", re.IGNORECASE)


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


def recording_log_path(out_dir: str, out_path: str) -> str:
    """Where the full ffmpeg stderr for ``out_path`` is written."""
    base = os.path.splitext(os.path.basename(out_path))[0]
    return os.path.join(out_dir, RECORDING_LOG_DIRNAME, base + ".log")


def redact_log(path: str, url: str) -> None:
    """Replace the stream URL wherever ffmpeg echoed it into ``path``.

    ffmpeg prints its input URL in the stream dump, and for Xtream Codes and Stalker
    providers that URL carries the account's username and password. These logs exist
    to be sent to somebody for diagnosis, so the credentials must not travel with them.
    """
    if not path or not url:
        return
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        needle = url.encode("utf-8", errors="replace")
        if needle not in data:
            return
        with open(path, "wb") as handle:
            handle.write(data.replace(needle, LOG_URL_PLACEHOLDER.encode("utf-8")))
    except OSError:
        LOG.debug("redact_log: ignored exception", exc_info=True)


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
    lines = [line.strip() for line in data.decode("utf-8", errors="replace").splitlines()]
    return [line for line in lines if _PROBLEM_LINE_RE.match(line)][-limit:]


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
) -> List[str]:
    """Construct the full ffmpeg argument list for one recording."""
    if fmt not in RECORDING_FORMATS:
        fmt = DEFAULT_RECORDING_FORMAT

    cmd: List[str] = [ffmpeg_path, "-hide_banner", "-loglevel", "level+info", "-nostats", "-y"]
    # Reconnect/robustness for long-running HTTP(S) live captures.
    cmd += [
        "-rw_timeout", "15000000",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
    ]
    # Per-channel auth headers must precede -i to apply to the input.
    cmd += _header_input_args(headers)
    cmd += ["-i", url]

    if duration and duration > 0:
        cmd += ["-t", str(float(duration))]

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
    elif fmt in ("x264_mp4", "x264_mkv"):
        cmd += [
            "-map", "0:v?", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
        ]
    elif fmt == "audio_wav":
        cmd += ["-vn", "-c:a", "pcm_s16le"]
    elif fmt == "audio_flac":
        cmd += ["-vn", "-c:a", "flac"]
    elif fmt == "audio_mp3_v0":
        cmd += ["-vn", "-c:a", "libmp3lame", "-q:a", "0"]
    elif fmt == "audio_aac_m4a":
        cmd += ["-vn", "-c:a", "aac", "-b:a", "256k"]
    elif fmt == "audio_opus":
        cmd += ["-vn", "-c:a", "libopus", "-b:a", "160k"]
    else:  # pragma: no cover - defensive, normalized upstream
        cmd += ["-map", "0", "-c", "copy"]

    if format_uses_faststart(fmt):
        cmd += ["-movflags", "+faststart"]

    cmd.append(out_path)
    return cmd


class Recording:
    """A single in-progress (or finished) recording."""

    def __init__(self, rec_id: int, key: str, url: str, title: str, fmt: str, out_path: str,
                 process: "subprocess.Popen", metadata: Optional[Dict[str, object]] = None,
                 log_path: str = "", command: Optional[List[str]] = None):
        self.id = rec_id
        self.key = key  # stable channel identity (resolved URL can change per resolve)
        self.url = url
        self.title = title
        self.fmt = fmt
        self.out_path = out_path
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


class RecordingManager:
    """Tracks and controls ffmpeg recording subprocesses."""

    def __init__(self):
        self._lock = threading.Lock()
        self._recordings: "Dict[int, Recording]" = {}
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
    ) -> Recording:
        if not url:
            raise ValueError("No stream URL to record.")
        if fmt not in RECORDING_FORMATS:
            fmt = DEFAULT_RECORDING_FORMAT

        os.makedirs(out_dir, exist_ok=True)
        out_path = self._unique_output_path(out_dir, display_name, format_extension(fmt))
        cmd = build_ffmpeg_command(get_ffmpeg_path(), url, out_path, fmt, headers, duration=duration)
        LOG.info("Starting recording: %s -> %s (%s)", display_name, out_path, fmt)

        # ffmpeg writes its diagnostics straight into the log file rather than into a
        # pipe we drain. That keeps the complete stderr for every recording, and it
        # means the log survives -- and ffmpeg keeps running -- when the app exits
        # while a capture is still finalizing.
        log_path = recording_log_path(out_dir, out_path)
        log_handle = self._open_log(log_path, cmd, url)
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log_handle if log_handle else subprocess.PIPE,
                creationflags=creation_flags,
            )
        except Exception:
            if log_handle:
                log_handle.close()
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
                            metadata, log_path=log_path, command=cmd)
            self._recordings[rec_id] = rec

        if not log_path:
            threading.Thread(target=self._drain_stderr, args=(rec,), daemon=True).start()
        threading.Thread(target=self._watch, args=(rec, on_finish), daemon=True).start()
        return rec

    def stop(self, rec_id: int, *, wait: bool = False, detach: bool = False) -> None:
        with self._lock:
            rec = self._recordings.get(rec_id)
        if rec:
            self._graceful_stop(rec, wait=wait, detach=detach)

    def stop_key(self, key: str, *, wait: bool = False, detach: bool = False) -> int:
        stopped = 0
        for rec in self.list_active():
            if rec.key == key:
                self._graceful_stop(rec, wait=wait, detach=detach)
                stopped += 1
        return stopped

    def stop_all(self, *, wait: bool = False, detach: bool = False) -> int:
        """Stop every active recording.

        ``detach`` is for application shutdown: ffmpeg is asked to stop and then left
        to finish writing its container by itself, however long that takes.
        """
        active = self.list_active()
        for rec in active:
            self._graceful_stop(rec, wait=wait, detach=detach)
        return len(active)

    # -- internals ---------------------------------------------------------
    def _unique_output_path(self, out_dir: str, display_name: str, ext: str) -> str:
        base = sanitize_filename(display_name)
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        candidate = os.path.join(out_dir, f"{base} - {stamp}.{ext}")
        counter = 2
        while os.path.exists(candidate):
            candidate = os.path.join(out_dir, f"{base} - {stamp} ({counter}).{ext}")
            counter += 1
        return candidate

    def _open_log(self, log_path: str, cmd: List[str], url: str):
        """Open the per-recording ffmpeg log, or return None if we cannot write one."""
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            handle = open(log_path, "wb")
        except Exception:
            LOG.debug("RecordingManager._open_log: ignored exception", exc_info=True)
            return None
        try:
            # The URL can carry provider credentials, so record the command with it
            # masked; the log lives beside the recordings and may well be shared.
            safe = []
            for index, part in enumerate(cmd):
                if part == url:
                    safe.append(LOG_URL_PLACEHOLDER)
                elif index and cmd[index - 1] == "-headers":
                    safe.append("<headers>")
                else:
                    safe.append(part)
            header = "# %s\n# ffmpeg %s\n\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), subprocess.list2cmdline(safe[1:]))
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
                if line and _PROBLEM_LINE_RE.match(line):
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
        rc = proc.returncode if proc else -1
        if rec.log_path:
            redact_log(rec.log_path, rec.url)
            rec.stderr_tail = read_log_problems(rec.log_path)
        with self._lock:
            self._recordings.pop(rec.id, None)
        LOG.info("Recording finished: %s (rc=%s, log=%s)", rec.out_path, rc, rec.log_path or "-")
        if on_finish:
            try:
                on_finish(rec, rc if rc is not None else -1)
            except Exception:
                LOG.exception("Recording on_finish callback failed")

    def _graceful_stop(self, rec: Recording, *, wait: bool = False, detach: bool = False) -> None:
        proc = rec.process
        rec.stopped_by_user = True
        if not proc or proc.poll() is not None:
            return
        if rec.stopping:
            if wait:
                try:
                    proc.wait(timeout=DETACH_WAIT_SECONDS if detach
                              else finalize_timeout_seconds(rec.fmt, rec.out_path))
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
                # Shutdown. Give ffmpeg a moment for the common short recording, then
                # leave it to finish on its own: it is a separate process and does not
                # need us alive. Killing it here is exactly what strands a long MP4
                # with no moov atom.
                rec.detached = True
                try:
                    proc.wait(timeout=DETACH_WAIT_SECONDS)
                    rec.detached = False
                except Exception:
                    LOG.info("Leaving ffmpeg to finish writing %s after shutdown", rec.out_path)
                return

            # Finalizing is disk-bound and scales with the size of the capture, so the
            # budget is derived from the file rather than fixed. Terminating early here
            # is what produced unplayable MP4s: ffmpeg had rewritten the mdat header but
            # had not yet written the moov atom, so nothing could open the result.
            timeout = finalize_timeout_seconds(rec.fmt, rec.out_path)
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
