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


def get_ffmpeg_path():
    """Resolve ffmpeg lazily so importing recorder stays cheap at startup."""
    from stream_proxy import get_ffmpeg_path as _get_ffmpeg_path

    return _get_ffmpeg_path()


def format_label(fmt: str) -> str:
    """English display label for a format key (callers translate at display time)."""
    entry = RECORDING_FORMATS.get(fmt) or RECORDING_FORMATS[DEFAULT_RECORDING_FORMAT]
    return entry[0]


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

    cmd: List[str] = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y"]
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
        cmd += ["-map", "0", "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart"]
    elif fmt == "provider_mkv":
        cmd += ["-map", "0", "-c", "copy"]
    elif fmt in ("x264_mp4", "x264_mkv"):
        cmd += [
            "-map", "0:v?", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
        ]
        if fmt == "x264_mp4":
            cmd += ["-movflags", "+faststart"]
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

    cmd.append(out_path)
    return cmd


class Recording:
    """A single in-progress (or finished) recording."""

    def __init__(self, rec_id: int, key: str, url: str, title: str, fmt: str, out_path: str,
                 process: "subprocess.Popen", metadata: Optional[Dict[str, object]] = None):
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

        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )

        with self._lock:
            rec_id = self._next_id
            self._next_id += 1
            rec = Recording(rec_id, key or url, url, display_name, fmt, out_path, process, metadata)
            self._recordings[rec_id] = rec

        threading.Thread(target=self._drain_stderr, args=(rec,), daemon=True).start()
        threading.Thread(target=self._watch, args=(rec, on_finish), daemon=True).start()
        return rec

    def stop(self, rec_id: int, *, wait: bool = False) -> None:
        with self._lock:
            rec = self._recordings.get(rec_id)
        if rec:
            self._graceful_stop(rec, wait=wait)

    def stop_key(self, key: str, *, wait: bool = False) -> int:
        stopped = 0
        for rec in self.list_active():
            if rec.key == key:
                self._graceful_stop(rec, wait=wait)
                stopped += 1
        return stopped

    def stop_all(self, *, wait: bool = False) -> int:
        active = self.list_active()
        for rec in active:
            self._graceful_stop(rec, wait=wait)
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

    def _drain_stderr(self, rec: Recording) -> None:
        proc = rec.process
        if not proc or not proc.stderr:
            return
        try:
            for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    rec.stderr_tail.append(line)
                    rec.stderr_tail = rec.stderr_tail[-12:]
        except Exception:
            pass

    def _watch(self, rec: Recording, on_finish: Optional[Callable[[Recording, int], None]]) -> None:
        try:
            rec.process.wait()
        except Exception:
            pass
        rc = rec.process.returncode if rec.process else -1
        with self._lock:
            self._recordings.pop(rec.id, None)
        LOG.info("Recording finished: %s (rc=%s)", rec.out_path, rc)
        if on_finish:
            try:
                on_finish(rec, rc if rc is not None else -1)
            except Exception:
                LOG.exception("Recording on_finish callback failed")

    def _graceful_stop(self, rec: Recording, *, wait: bool = False) -> None:
        proc = rec.process
        rec.stopped_by_user = True
        if not proc or proc.poll() is not None:
            return
        if rec.stopping:
            if wait:
                try:
                    proc.wait(timeout=8)
                except Exception:
                    pass
            return
        rec.stopping = True

        def _finalize():
            # Ask ffmpeg to quit cleanly so the container is finalized (MP4 moov atom,
            # MKV cues). Fall back to terminate/kill if it ignores us.
            try:
                if proc.stdin:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(timeout=8)
                return
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=5)
                return
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass

        if wait:
            _finalize()
        else:
            threading.Thread(target=_finalize, daemon=True).start()
