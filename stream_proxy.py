
import http.server
import socketserver
import threading
import urllib.request
import urllib.parse
import socket
import logging
import json
import base64
import subprocess
import tempfile
import shutil
import os
import time
import hashlib
import collections

import sys

LOG = logging.getLogger(__name__)

_DEFAULT_UPSTREAM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
_REAL_HLS_PLAYLIST_WAIT_SECONDS = 8
_HLS_PLAYLIST_EXTENDED_WAIT_SECONDS = 4
_HLS_UPSTREAM_READ_TIMEOUT_SECONDS = 30
_HLS_UPSTREAM_MAX_STARTUP_ATTEMPTS = 3
_HLS_UPSTREAM_STARTUP_RETRY_DELAY_SECONDS = 1.0
_HLS_SEGMENT_SECONDS = 2
_HLS_PLAYLIST_SEGMENT_COUNT = 8
_HLS_RETAINED_SEGMENT_COUNT = 180
_HLS_SEGMENT_CLEANUP_INTERVAL_SECONDS = 15
_HLS_MIN_READY_SEGMENTS = 3
_HLS_MIN_READY_DURATION_SECONDS = 5.0
_HLS_MIN_STABLE_START_SEGMENT_BYTES = 128 * 1024
_HLS_STARTUP_SEGMENTS_TO_DROP = 3

_HEADER_NAME_MAP = {
    "user-agent": "User-Agent",
    "ua": "User-Agent",
    "http-user-agent": "User-Agent",
    "referer": "Referer",
    "referrer": "Referer",
    "http-referrer": "Referer",
    "http-referer": "Referer",
    "origin": "Origin",
    "http-origin": "Origin",
    "cookie": "Cookie",
    "http-cookie": "Cookie",
    "authorization": "Authorization",
    "auth": "Authorization",
    "http-authorization": "Authorization",
    "accept": "Accept",
    "http-accept": "Accept",
    "range": "Range",
    "http-range": "Range",
    "host": "Host",
    "http-host": "Host",
    "x-forwarded-for": "X-Forwarded-For",
    "xff": "X-Forwarded-For",
}


def _normalize_header_name(name):
    mapped = _HEADER_NAME_MAP.get(str(name).strip().lower())
    if mapped:
        return mapped
    return "-".join(part.capitalize() for part in str(name).strip().split("-") if part)


def _header_value_to_str(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        for item in value:
            text = _header_value_to_str(item)
            if text:
                return text
        return ""
    return str(value).strip()


def _set_header(headers, name, value, *, overwrite=True):
    value_text = _header_value_to_str(value)
    if not name or not value_text:
        return
    lower_name = name.lower()
    existing = {key.lower() for key in headers}
    if overwrite or lower_name not in existing:
        headers[name] = value_text


def _iter_extra_headers(value):
    if not value:
        return
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]

    for header in values:
        text = str(header).strip()
        if ":" not in text:
            continue
        name, val = text.split(":", 1)
        name = _normalize_header_name(name)
        val = val.strip()
        if name and val:
            yield name, val


def normalize_request_headers(headers=None, *, add_default_user_agent=True):
    """Convert channel metadata headers into urllib-safe string headers."""
    normalized = {}
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).strip().lower() == "_extra":
                continue
            name = _normalize_header_name(key)
            if not name:
                continue
            _set_header(normalized, name, value)

        for name, value in _iter_extra_headers(headers.get("_extra")) or ():
            _set_header(normalized, name, value, overwrite=False)

    if add_default_user_agent and not any(k.lower() == "user-agent" for k in normalized):
        normalized["User-Agent"] = _DEFAULT_UPSTREAM_USER_AGENT
    return normalized


def _segment_number_from_name(filename):
    if not filename.startswith("seg_") or not filename.endswith(".ts"):
        return None
    try:
        return int(filename[4:-3])
    except ValueError:
        return None


def _segment_number_from_uri(uri):
    return _segment_number_from_name(os.path.basename(urllib.parse.urlparse(uri).path))


def _segment_file_size(segment_dir, uri):
    if not segment_dir:
        return None
    filename = os.path.basename(urllib.parse.urlparse(uri).path)
    path = os.path.join(segment_dir, filename)
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def filter_unstable_hls_start(lines, segment_dir, min_segment_bytes=_HLS_MIN_STABLE_START_SEGMENT_BYTES):
    """Drop tiny FFmpeg startup segments that can have incomplete audio metadata."""
    if not segment_dir:
        return list(lines)

    filtered = []
    pending_segment_tags = []
    media_sequence_index = None
    original_media_sequence = None
    current_sequence = None
    stable_sequence = None
    dropping = True
    saw_segment = False

    for raw_line in lines:
        line = str(raw_line).strip()
        if not line:
            continue

        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            media_sequence_index = len(filtered)
            filtered.append(line)
            try:
                original_media_sequence = int(line.split(":", 1)[1])
                current_sequence = original_media_sequence
            except ValueError:
                original_media_sequence = None
                current_sequence = None
            continue

        if line.startswith("#EXTINF:"):
            pending_segment_tags.append(line)
            continue

        if line.startswith("#"):
            if pending_segment_tags:
                pending_segment_tags.append(line)
            else:
                filtered.append(line)
            continue

        size = _segment_file_size(segment_dir, line)
        saw_segment = True
        sequence_offset = (
            current_sequence - original_media_sequence
            if current_sequence is not None and original_media_sequence is not None
            else None
        )
        segment_number = _segment_number_from_uri(line)
        in_startup_window = (
            segment_number is not None
            and segment_number <= _HLS_STARTUP_SEGMENTS_TO_DROP
        ) or (
            segment_number is None
            and original_media_sequence == 1
            and sequence_offset is not None
            and sequence_offset < _HLS_STARTUP_SEGMENTS_TO_DROP
        )
        below_stable_size = size is not None and size < min_segment_bytes
        if dropping and (in_startup_window or below_stable_size):
            pending_segment_tags.clear()
            if current_sequence is not None:
                current_sequence += 1
            continue

        if dropping:
            dropping = False
            stable_sequence = current_sequence or _segment_number_from_uri(line)
        filtered.extend(pending_segment_tags)
        filtered.append(line)
        pending_segment_tags.clear()
        if current_sequence is not None:
            current_sequence += 1

    if dropping:
        if saw_segment:
            if media_sequence_index is not None and current_sequence is not None:
                filtered[media_sequence_index] = f"#EXT-X-MEDIA-SEQUENCE:{current_sequence}"
            return filtered
        return list(lines)

    if stable_sequence is not None:
        if media_sequence_index is not None:
            filtered[media_sequence_index] = f"#EXT-X-MEDIA-SEQUENCE:{stable_sequence}"
        elif original_media_sequence is not None:
            filtered.insert(1, f"#EXT-X-MEDIA-SEQUENCE:{stable_sequence}")

    return filtered


def rewrite_hls_playlist(lines, base_url, segment_dir=None, drop_unstable_start=False):
    """Rewrite FFmpeg HLS segment paths without changing playlist semantics."""
    if drop_unstable_start:
        lines = filter_unstable_hls_start(lines, segment_dir)

    rewritten = []
    saw_header = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            if not saw_header:
                rewritten.append("#EXTM3U")
                saw_header = True
            continue
        if line.startswith("#"):
            rewritten.append(line)
            continue
        rewritten.append(urllib.parse.urljoin(base_url, line))

    if not saw_header:
        rewritten.insert(0, "#EXTM3U")
    return "\n".join(rewritten) + "\n"


def hls_playlist_stats(lines):
    media_sequence = None
    first_segment = None
    segment_count = 0
    duration = 0.0
    has_endlist = False
    pending_duration = None

    for raw_line in lines:
        line = str(raw_line).strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(line.split(":", 1)[1])
            except ValueError:
                media_sequence = None
            continue
        if line.startswith("#EXTINF:"):
            try:
                pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
            except ValueError:
                pending_duration = None
            continue
        if line == "#EXT-X-ENDLIST":
            has_endlist = True
            continue
        if line.startswith("#"):
            continue

        if first_segment is None:
            first_segment = line
        segment_count += 1
        if pending_duration is not None:
            duration += pending_duration
        pending_duration = None

    return {
        "media_sequence": media_sequence,
        "first_segment": first_segment,
        "segment_count": segment_count,
        "duration": duration,
        "has_endlist": has_endlist,
    }


def hls_playlist_is_ready(lines, segment_dir=None, require_stable_start=False):
    if require_stable_start:
        lines = filter_unstable_hls_start(lines, segment_dir)
    stats = hls_playlist_stats(lines)
    if stats["has_endlist"] and stats["segment_count"] > 0:
        return True, stats
    ready = (
        stats["segment_count"] >= _HLS_MIN_READY_SEGMENTS
        and stats["duration"] >= _HLS_MIN_READY_DURATION_SECONDS
    )
    return ready, stats


def is_fresh_transcode_profile(profile):
    return str(profile or "").startswith("chromecast")


def get_ffmpeg_path():
    """Resolve ffmpeg path, prioritizing bundled executable in frozen mode."""
    # PyInstaller onefile
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundled = os.path.join(sys._MEIPASS, 'ffmpeg.exe')
        if os.path.exists(bundled):
            return bundled
            
    # PyInstaller onedir (PyInstaller 6+ puts it in _internal)
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
        internal = os.path.join(base_dir, '_internal', 'ffmpeg.exe')
        if os.path.exists(internal):
            return internal
        # Old layout or user-placed
        adjacent = os.path.join(base_dir, 'ffmpeg.exe')
        if os.path.exists(adjacent):
            return adjacent
    
    # Fallback to PATH or local file
    if os.path.exists("ffmpeg.exe"):
        return os.path.abspath("ffmpeg.exe")
        
    return "ffmpeg"

class HLSConverter:
    def __init__(self, source_url, headers=None, transcode_profile: str = "auto"):
        self.source_url = source_url
        self.headers = normalize_request_headers(headers)
        self.profile = transcode_profile
        self.user_agent = self.headers.get("User-Agent") or _DEFAULT_UPSTREAM_USER_AGENT
        self.temp_dir = tempfile.mkdtemp(prefix="iptv_remux_")
        self.process = None
        self.playlist_path = os.path.join(self.temp_dir, "stream.m3u8")
        self.last_access = time.time()
        self._bytes_pumped = 0
        self._startup_error = None
        self._ffmpeg_stderr_tail = []
        self._state_lock = threading.Lock()
        self.start()

    def _uses_h264_transcode(self):
        return self.profile in {"chromecast_h264", "h264", "transcode"}

    def _build_ffmpeg_command(self):
        cmd = [
            get_ffmpeg_path(), "-hide_banner", "-loglevel", "error",
            "-analyzeduration", "5000000", "-probesize", "5000000",
            "-fflags", "nobuffer+genpts+igndts",
            "-flags", "low_delay",
            "-i", "pipe:0",
            "-map", "0:v?", "-map", "0:a?",
        ]

        if self._uses_h264_transcode():
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-tune", "zerolatency",
                "-pix_fmt", "yuv420p",
                "-profile:v", "high",
                "-level", "4.1",
                "-crf", "23",
                "-maxrate", "6000k",
                "-bufsize", "12000k",
                "-force_key_frames", f"expr:gte(t,n_forced*{_HLS_SEGMENT_SECONDS})",
            ])
            hls_flags = None
        else:
            cmd.extend(["-c:v", "copy"])
            hls_flags = "split_by_time"

        cmd.extend([
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "320k", "-ac", "2", "-ar", "44100"
        ])

        cmd.extend([
            "-f", "hls", "-hls_time", str(_HLS_SEGMENT_SECONDS),
            "-hls_list_size", str(_HLS_PLAYLIST_SEGMENT_COUNT),
        ])
        if hls_flags:
            cmd.extend(["-hls_flags", hls_flags])
        cmd.extend([
            "-hls_segment_type", "mpegts", "-flush_packets", "1",
            "-start_number", "1", "-hls_segment_filename", os.path.join(self.temp_dir, "seg_%d.ts"),
            "-mpegts_flags", "pat_pmt_at_beginning",
            self.playlist_path
        ])
        return cmd

    def start(self):
        # Video HLS engine (piped)
        cmd = self._build_ffmpeg_command()
        LOG.info(f"Starting HLS engine for Video ({self.profile})")
        
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creation_flags
            )

            def _drain_stderr():
                if not self.process or not self.process.stderr:
                    return
                try:
                    for raw_line in self.process.stderr:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if line:
                            with self._state_lock:
                                self._ffmpeg_stderr_tail.append(line)
                                self._ffmpeg_stderr_tail = self._ffmpeg_stderr_tail[-8:]
                except Exception:
                    pass

            threading.Thread(target=_drain_stderr, daemon=True).start()

            def _pump():
                last_error = None
                got_any_data = False
                startup_attempts = 0
                try:
                    while self.process and self.process.poll() is None:
                        if self.process and self.process.poll() is not None:
                            break
                        try:
                            req = urllib.request.Request(self.source_url, headers=self.headers)
                            with urllib.request.urlopen(
                                req,
                                timeout=_HLS_UPSTREAM_READ_TIMEOUT_SECONDS
                            ) as resp:
                                response_had_data = False
                                while self.process and self.process.poll() is None:
                                    chunk = resp.read(32768)
                                    if not chunk:
                                        break
                                    response_had_data = True
                                    got_any_data = True
                                    with self._state_lock:
                                        self._bytes_pumped += len(chunk)
                                    try:
                                        self.process.stdin.write(chunk)
                                        self.process.stdin.flush()
                                    except Exception:
                                        return
                            if not got_any_data:
                                startup_attempts += 1
                                if startup_attempts >= _HLS_UPSTREAM_MAX_STARTUP_ATTEMPTS:
                                    break
                                LOG.info(
                                    "HLS upstream did not provide data on startup attempt %s/%s; retrying",
                                    startup_attempts,
                                    _HLS_UPSTREAM_MAX_STARTUP_ATTEMPTS
                                )
                                time.sleep(_HLS_UPSTREAM_STARTUP_RETRY_DELAY_SECONDS)
                                continue
                            if response_had_data and self.process and self.process.poll() is None:
                                LOG.info("HLS upstream response ended; reopening live stream")
                                time.sleep(_HLS_UPSTREAM_STARTUP_RETRY_DELAY_SECONDS)
                                continue
                            break
                        except Exception as e:
                            last_error = e
                            if got_any_data:
                                LOG.info("HLS upstream read ended; reopening live stream: %s", e)
                                time.sleep(_HLS_UPSTREAM_STARTUP_RETRY_DELAY_SECONDS)
                                continue

                            startup_attempts += 1
                            if startup_attempts >= _HLS_UPSTREAM_MAX_STARTUP_ATTEMPTS:
                                break
                            LOG.info(
                                "HLS upstream did not provide data on startup attempt %s/%s; retrying",
                                startup_attempts,
                                _HLS_UPSTREAM_MAX_STARTUP_ATTEMPTS
                            )
                            time.sleep(_HLS_UPSTREAM_STARTUP_RETRY_DELAY_SECONDS)

                    if not got_any_data and not last_error:
                        with self._state_lock:
                            self._startup_error = "HLS upstream closed before media data was received"
                        LOG.info("HLS upstream closed before media data was received")
                    elif last_error and not got_any_data:
                        with self._state_lock:
                            self._startup_error = str(last_error)
                        LOG.info("HLS upstream startup failed before media data was received: %s", last_error)
                    elif last_error:
                        LOG.info("HLS upstream ended after media data was received: %s", last_error)
                finally:
                    if self.process and self.process.stdin:
                        try: self.process.stdin.close()
                        except: pass
            threading.Thread(target=_pump, daemon=True).start()
            threading.Thread(target=self._cleanup_old_segments, daemon=True).start()
        except Exception as e:
            with self._state_lock:
                self._startup_error = str(e)
            LOG.info("FFmpeg HLS start failed: %s", e)

    def _segment_number(self, filename):
        if not filename.startswith("seg_") or not filename.endswith(".ts"):
            return None
        try:
            return int(filename[4:-3])
        except ValueError:
            return None

    def _cleanup_old_segments_once(self):
        if not os.path.isdir(self.temp_dir):
            return
        segments = []
        try:
            with os.scandir(self.temp_dir) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    number = self._segment_number(entry.name)
                    if number is not None:
                        segments.append((number, entry.path))
        except OSError:
            return

        if len(segments) <= _HLS_RETAINED_SEGMENT_COUNT:
            return
        segments.sort()
        stale = segments[:-_HLS_RETAINED_SEGMENT_COUNT]
        for _number, path in stale:
            try:
                os.remove(path)
            except OSError:
                pass

    def _cleanup_old_segments(self):
        while self.is_alive():
            time.sleep(_HLS_SEGMENT_CLEANUP_INTERVAL_SECONDS)
            self._cleanup_old_segments_once()

    def stop(self):
        if self.process:
            try: self.process.terminate()
            except: pass
            self.process = None
        if os.path.exists(self.temp_dir):
            try: shutil.rmtree(self.temp_dir)
            except: pass

    def is_alive(self): return self.process and self.process.poll() is None
    def touch(self): self.last_access = time.time()
    def has_upstream_data(self):
        with self._state_lock:
            return self._bytes_pumped > 0
    def startup_error(self):
        with self._state_lock:
            return self._startup_error

    def wait_for_playlist(self, timeout=10, extended_timeout=None):
        """Wait for the FFmpeg HLS playlist to become ready.

        Some upstreams (signed redirects, slow CDNs) take longer than the
        base timeout to finish their TLS handshake and emit segments. As
        long as upstream bytes are *still arriving* we extend the deadline
        up to ``extended_timeout`` instead of giving up. This avoids the
        Chromecast-idles-to-ERROR failure mode that happens when the proxy
        returns 503 mid-handshake on a fresh-session profile.
        """
        if extended_timeout is None:
            extended_timeout = max(timeout, _HLS_PLAYLIST_EXTENDED_WAIT_SECONDS)
        start = time.time()
        last_bytes = 0
        last_progress = start
        while True:
            elapsed = time.time() - start
            with self._state_lock:
                pumped = self._bytes_pumped
            if pumped > last_bytes:
                last_bytes = pumped
                last_progress = time.time()

            if os.path.exists(self.playlist_path) and os.path.getsize(self.playlist_path) > 100:
                try:
                    with open(self.playlist_path, "r", encoding="utf-8") as f:
                        ready, _stats = hls_playlist_is_ready(
                            f.readlines(),
                            segment_dir=self.temp_dir,
                            require_stable_start=is_fresh_transcode_profile(self.profile),
                        )
                    if ready:
                        return True
                except OSError:
                    pass
            if not self.is_alive():
                with self._state_lock:
                    if not self._startup_error:
                        self._startup_error = "FFmpeg exited before producing an HLS playlist"
                return False

            if elapsed >= timeout:
                stalled = (time.time() - last_progress) > 3.0
                if elapsed >= extended_timeout or stalled or last_bytes == 0:
                    return False
            time.sleep(0.2)

    def can_serve_bootstrap(self):
        return self.is_alive() and self.has_upstream_data()


class StreamBuffer:
    def __init__(self, max_size=16 * 1024 * 1024, initial_fill=128 * 1024):
        self.max_size = max_size
        self.initial_fill = initial_fill
        self.buffer = collections.deque()
        self.current_size = 0
        self.lock = threading.Lock()
        self.not_empty = threading.Condition(self.lock)
        self.not_full = threading.Condition(self.lock)
        self.closed = False
        self.error = None
        self.has_filled = False

    def write(self, chunk):
        with self.lock:
            while self.current_size + len(chunk) > self.max_size:
                if self.closed: return
                self.not_full.wait()
            self.buffer.append(chunk)
            self.current_size += len(chunk)
            
            if not self.has_filled:
                if self.current_size >= self.initial_fill:
                    self.has_filled = True
                    self.not_empty.notify_all()
            else:
                self.not_empty.notify()

    def read(self):
        with self.lock:
            while not self.buffer or (not self.has_filled and not self.closed):
                if self.closed:
                    if self.buffer: break
                    if self.error: raise self.error
                    return None
                
                # Check fill again in case it changed while we waited
                if not self.has_filled and self.current_size >= self.initial_fill:
                    self.has_filled = True
                    break
                    
                self.not_empty.wait()
            
            chunk = self.buffer.popleft()
            self.current_size -= len(chunk)
            self.not_full.notify()
            return chunk

    def close(self, error=None):
        with self.lock:
            self.closed = True
            self.error = error
            self.not_empty.notify_all()
            self.not_full.notify_all()

    def is_closed(self):
        with self.lock:
            return self.closed

class StreamProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # BaseHTTPRequestHandler.log_message writes to sys.stderr, which is None
        # in PyInstaller --noconsole / windowed builds. Touching it raises
        # AttributeError on the FIRST line of every response (send_response →
        # log_request → log_message), the handler dies, and the receiver sees an
        # empty reply. Route through our own LOG instead so the bundled exe can
        # actually serve responses.
        try:
            LOG.debug("proxy %s - %s", self.address_string(), format % args)
        except Exception:
            pass

    def log_error(self, format, *args):
        try:
            LOG.info("proxy %s - %s", self.address_string(), format % args)
        except Exception:
            pass

    def _send_no_cache_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # 1. --- Route: /audio or /stream (High-Speed Buffered Proxy) ---
        if parsed.path in ('/audio', '/stream', '/proxy'):
            query = urllib.parse.parse_qs(parsed.query)
            target_url = query.get('url', [None])[0]
            if not target_url: return self.send_error(400)
            mode = (query.get('mode', [None])[0] or '').strip().lower()
            
            headers_json = query.get('headers', [None])[0]
            req_headers = {}
            if headers_json:
                try: req_headers = json.loads(base64.b64decode(headers_json).decode())
                except: pass
            req_headers = normalize_request_headers(req_headers)
            
            # --- RADIO Path ---
            target_lower = target_url.lower()
            force_audio = mode == "audio"
            if force_audio or "radio" in target_lower or "streamon.fm" in target_lower or parsed.path == '/audio':
                self.send_response(200)
                self.send_header('Content-Type', 'audio/mpeg')
                self.send_header('Icy-MetaData', '1')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()

                # Determine if we need transcoding — only skip for plain MP3 streams
                is_mp3 = target_lower.endswith(".mp3")
                needs_transcode = not is_mp3

                # Shared buffer for decoupling download from client write
                # 128KB fill ≈ 3s at 320kbps output, absorbs FFmpeg startup latency
                stream_buffer = StreamBuffer(max_size=16 * 1024 * 1024, initial_fill=128 * 1024)

                def _upstream_worker():
                    proc = None
                    try:
                        if needs_transcode:
                            cmd = [
                                get_ffmpeg_path(), "-hide_banner", "-loglevel", "error",
                                "-probesize", "32k", "-analyzeduration", "500000",
                                "-i", "pipe:0", "-vn",
                                "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100",
                                "-f", "mp3", "pipe:1"
                            ]
                            creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                            proc = subprocess.Popen(
                                cmd,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                creationflags=creation_flags
                            )
                            
                            # Feed ffmpeg in a sub-thread so we can read stdout in this thread
                            def _feeder():
                                try:
                                    req = urllib.request.Request(target_url, headers=req_headers)
                                    with urllib.request.urlopen(req, timeout=15) as resp:
                                        while proc and proc.poll() is None and not stream_buffer.is_closed():
                                            # Use smaller chunks (8KB) for smoother flow
                                            chunk = resp.read(8192)
                                            if not chunk: break
                                            try:
                                                proc.stdin.write(chunk)
                                                proc.stdin.flush()
                                            except: break
                                except Exception: pass
                                finally:
                                    if proc and proc.stdin:
                                        try: proc.stdin.close()
                                        except: pass

                            threading.Thread(target=_feeder, daemon=True).start()

                            # Read ffmpeg stdout -> buffer
                            while not stream_buffer.is_closed():
                                chunk = proc.stdout.read(8192)
                                if not chunk: break
                                stream_buffer.write(chunk)
                            
                            if proc.poll() is None:
                                proc.terminate()
                            try:
                                proc.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait()
                        else:
                            # Direct download -> buffer
                            req = urllib.request.Request(target_url, headers=req_headers)
                            with urllib.request.urlopen(req, timeout=15) as resp:
                                while not stream_buffer.is_closed():
                                    chunk = resp.read(8192)
                                    if not chunk: break
                                    stream_buffer.write(chunk)
                        
                        stream_buffer.close()
                    except Exception as e:
                        if stream_buffer.is_closed():
                            stream_buffer.close()
                        else:
                            LOG.info("Audio upstream worker ended: %s", e)
                            stream_buffer.close(error=e)
                    finally:
                        if proc and proc.poll() is None:
                            try:
                                proc.terminate()
                                proc.wait(timeout=3)
                            except Exception:
                                try:
                                    proc.kill()
                                except Exception:
                                    pass

                # Start the producer thread
                threading.Thread(target=_upstream_worker, daemon=True).start()

                # Consumer: Serve to client
                try:
                    while True:
                        chunk = stream_buffer.read()
                        if chunk is None: break
                        self.wfile.write(chunk)
                except Exception:
                    # Client disconnected
                    stream_buffer.close() # Signal stop to producer if blocked
                    pass
                return

            # --- VIDEO Path (HLS Redirect) ---
            hls_url = get_proxy().get_transcoded_url(target_url, headers=req_headers, transcode_profile="auto")
            self.send_response(302)
            self.send_header('Location', hls_url)
            self.end_headers()
            return

        # 3. --- Route: /transcode/<session_id>/... ---
        if parsed.path.startswith('/transcode/'):
            parts = parsed.path.split('/')
            if len(parts) >= 4:
                session_id, filename = parts[2], parts[3]
                converter = get_proxy().get_converter(session_id)
                if not converter: return self.send_error(404)
                converter.touch()

                if filename == "stream.m3u8":
                    # Serve real FFmpeg output when available. Only use bootstrap after
                    # upstream media starts flowing; otherwise Chromecast can appear to
                    # play a dead stream and never request real segments.
                    # Cap playlist hold time below Chromecast's internal manifest-fetch
                    # timeout (~8-10s). If FFmpeg isn't ready in that window but upstream
                    # bytes are arriving, serve the 1s bootstrap segment so the receiver
                    # gets a valid playlist immediately and re-polls — beats 503 →
                    # MEDIA_LOAD_FAILED, even for fresh-session profiles.
                    if not converter.wait_for_playlist(
                        timeout=_REAL_HLS_PLAYLIST_WAIT_SECONDS,
                        extended_timeout=_REAL_HLS_PLAYLIST_WAIT_SECONDS + _HLS_PLAYLIST_EXTENDED_WAIT_SECONDS,
                    ):
                        if not converter.can_serve_bootstrap():
                            detail = converter.startup_error() or "HLS converter is waiting for upstream media"
                            LOG.info("HLS playlist unavailable for session %s: %s", session_id, detail)
                            data = detail.encode("utf-8", errors="replace")
                            self.send_response(503)
                            self.send_header('Content-Type', 'text/plain; charset=utf-8')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self._send_no_cache_headers()
                            self.send_header('Content-Length', str(len(data)))
                            self.end_headers()
                            self.wfile.write(data)
                            return

                        LOG.info("Serving bootstrap playlist for session %s while FFmpeg warms up", session_id)
                        data = (
                            "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
                            "#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-DISCONTINUITY\n"
                            "#EXTINF:1.0,\n"
                            f"http://{get_proxy().host}:{get_proxy().port}/bootstrap.ts\n"
                        ).encode('utf-8')
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self._send_no_cache_headers()
                        self.send_header('Content-Length', str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return

                    # Real playlist rewrite
                    try:
                        with open(converter.playlist_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                        drop_unstable_start = is_fresh_transcode_profile(converter.profile)
                        effective_lines = (
                            filter_unstable_hls_start(lines, converter.temp_dir)
                            if drop_unstable_start else lines
                        )
                        stats = hls_playlist_stats(effective_lines)
                        base = f"http://{get_proxy().host}:{get_proxy().port}/transcode/{session_id}/"
                        data = rewrite_hls_playlist(effective_lines, base).encode("utf-8")
                        LOG.debug(
                            "Serving HLS playlist for session %s: media_sequence=%s segments=%s duration=%.2fs first=%s",
                            session_id,
                            stats["media_sequence"],
                            stats["segment_count"],
                            stats["duration"],
                            stats["first_segment"],
                        )
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self._send_no_cache_headers()
                        self.send_header('Content-Length', str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                    except: self.send_error(500)
                    return
                
                # Serve segments
                file_path = os.path.join(converter.temp_dir, filename)
                if not os.path.exists(file_path): return self.send_error(404)
                try:
                    file_size = os.path.getsize(file_path)
                except OSError:
                    return self.send_error(404)
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp2t')
                self.send_header('Access-Control-Allow-Origin', '*')
                self._send_no_cache_headers()
                self.send_header('Content-Length', str(file_size))
                self.end_headers()
                try:
                    with open(file_path, 'rb') as f: shutil.copyfileobj(f, self.wfile)
                except: pass
                return

        # 4. --- Route: /bootstrap.ts (1s black segment) ---
        if parsed.path == '/bootstrap.ts':
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp2t')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            cmd = [
                get_ffmpeg_path(), "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=640x360:r=10:d=1",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-b:v", "1M",
                "-c:a", "aac", "-b:a", "64k", "-f", "mpegts", "-muxrate", "2M", "pipe:1"
            ]
            creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=creation_flags)
            try:
                data = proc.stdout.read()
                if data: self.wfile.write(data)
            except: pass
            finally:
                try: proc.terminate()
                except: pass
            return

        self.send_error(404)


class StreamProxy:
    def __init__(self):
        self.server = None
        self.thread = None
        self.port = 0
        self.host = self._get_local_ip()
        self.converters = {}
        self.converter_sources = {}
        self.lock = threading.Lock()
        self._cleanup_thread = None
        self._running = False

    def _get_local_ip(self):
        """Robust primary IP detection for Chromecast compatibility."""
        try:
            # Method 1: Connected socket (fastest, most accurate for primary route)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith('127.'): return ip
        except: pass

        try:
            # Method 2: Hostname lookup
            ip = socket.gethostbyname(socket.gethostname())
            if ip and not ip.startswith('127.'): return ip
        except: pass

        try:
            # Method 3: Interface scan (last resort)
            # We don't assume netifaces is installed here, use standard socket
            for addr in socket.getaddrinfo(socket.gethostname(), None):
                ip = addr[4][0]
                if '.' in ip and not ip.startswith('127.'): return ip
        except: pass

        return '127.0.0.1'

    def start(self):
        if self.server: return
        self.server = socketserver.ThreadingTCPServer((self.host, 0), StreamProxyHandler)
        self.port = self.server.server_address[1]
        self._running = True
        self._ensure_firewall_rule()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        LOG.info(f"Proxy started at http://{self.host}:{self.port}")

    def stop(self):
        self._running = False
        if self.server: self.server.shutdown()
        with self.lock:
            for c in self.converters.values(): c.stop()
            self.converters.clear()
            self.converter_sources.clear()

    def get_stream_url(self, target_url, headers=None, mode="auto"):
        params = {'url': target_url, 'mode': mode}
        if headers:
            if isinstance(headers, dict):
                clean = normalize_request_headers(headers, add_default_user_agent=False)
                params['headers'] = base64.b64encode(json.dumps(clean).encode()).decode()
            else: params['headers'] = headers
        return f"http://{self.host}:{self.port}/stream?{urllib.parse.urlencode(params)}"

    def get_audio_url(self, target_url, headers=None):
        return self.get_stream_url(target_url, headers, mode="audio")

    def get_transcoded_url(self, target_url, headers=None, transcode_profile="auto"):
        tag = transcode_profile
        source_key = hashlib.md5(f"{target_url}|{tag}".encode()).hexdigest()
        fresh_session = is_fresh_transcode_profile(tag)
        if fresh_session:
            session_id = hashlib.md5(f"{target_url}|{tag}|{time.time_ns()}".encode()).hexdigest()
        else:
            session_id = source_key

        with self.lock:
            if fresh_session:
                old_sessions = list(self.converter_sources.values())
                self.converter_sources.clear()
                for old_session in old_sessions:
                    old_converter = self.converters.pop(old_session, None)
                    if old_converter:
                        old_converter.stop()
                self.converters[session_id] = HLSConverter(target_url, headers, transcode_profile)
                self.converter_sources[source_key] = session_id
            elif session_id not in self.converters:
                self.converters[session_id] = HLSConverter(target_url, headers, transcode_profile)
            else: self.converters[session_id].touch()
        return f"http://{self.host}:{self.port}/transcode/{session_id}/stream.m3u8"

    def get_converter(self, session_id):
        with self.lock: return self.converters.get(session_id)

    def _cleanup_loop(self):
        while self._running:
            time.sleep(10)
            now = time.time()
            with self.lock:
                dead = [sid for sid, c in self.converters.items() if now - c.last_access > 60]
                for sid in dead:
                    self.converters[sid].stop()
                    del self.converters[sid]
                if dead:
                    dead_set = set(dead)
                    self.converter_sources = {
                        key: sid
                        for key, sid in self.converter_sources.items()
                        if sid not in dead_set
                    }

    def _ensure_firewall_rule(self):
        if os.name != "nt" or not self.port: return
        rule_name = f"IPTV Proxy ({self.port})"
        try:
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule_name}"], capture_output=True, creationflags=flags)
            subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={rule_name}", "dir=in", "action=allow", "protocol=TCP", f"localport={self.port}", "profile=private,domain"], capture_output=True, creationflags=flags)
        except: pass

_PROXY = None
_PROXY_LOCK = threading.Lock()


def get_proxy():
    global _PROXY
    if _PROXY is None:
        with _PROXY_LOCK:
            if _PROXY is None:
                _PROXY = StreamProxy()
    return _PROXY
