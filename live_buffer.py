"""Opt-in, bounded MPEG-TS segment spool; one owned input and local HLS views.

No rate manipulation, transcoding, archive seek or automatic direct fallback.
The HTTP receiver enforces quota before writing even incomplete output.
"""
from __future__ import annotations

import atexit
from collections import OrderedDict, deque
from dataclasses import dataclass
import hashlib
import http.server
import json
import logging
import math
from pathlib import Path
import re
import secrets
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit, urljoin
import urllib.request

LOG = logging.getLogger(__name__)
_CHUNK = 65536
_LIMIT = 256 * 1024
_SEGMENT = re.compile(r'seg-\d{1,12}\.ts\Z')


class BufferError(RuntimeError):
    pass


def buffer_settings(config):
    config = config if isinstance(config, dict) else {}
    def integer(key, default, low, high):
        value = config.get(key, default)
        return max(low, min(high, value)) if type(value) is int else default
    return (config.get('live_buffer_enabled') is True,
            integer('live_buffer_seconds', 600, 60, 1800),
            integer('live_buffer_mib', 512, 64, 4096))


def source_key(url, headers=None):
    from http_headers import merge_headers, split_stream_modifiers
    url, modifiers = split_stream_modifiers(url)
    headers = merge_headers(headers, modifiers)
    value = [url, sorted((str(k).lower(), str(v)) for k, v in headers.items())]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def resolve_hls_input(source, headers=None, cap_mbps=None):
    if not urlsplit(source).path.lower().endswith('.m3u8'):
        return source
    from stream_proxy import normalize_request_headers
    headers = normalize_request_headers(headers, add_default_user_agent=True)
    seen = set()
    for _ in range(4):
        if source in seen or urlsplit(source).scheme not in {'http', 'https'}:
            raise BufferError('invalid HLS master nesting')
        seen.add(source)
        with urllib.request.urlopen(urllib.request.Request(source, headers=headers), timeout=5) as response:
            payload, base = response.read(_LIMIT + 1), response.geturl()
        if len(payload) > _LIMIT:
            raise BufferError('oversized HLS metadata')
        lines = [line.strip() for line in payload.decode('utf-8-sig').splitlines() if line.strip()]
        if not lines or lines[0] != '#EXTM3U':
            raise BufferError('invalid HLS metadata')
        if not any(line.startswith('#EXT-X-STREAM-INF:') for line in lines):
            return base
        if any(line.startswith('#EXT-X-MEDIA:') and 'URI=' in line for line in lines):
            raise BufferError('separate HLS renditions require direct playback')
        variants, bandwidth = [], None
        for line in lines:
            if line.startswith('#EXT-X-STREAM-INF:'):
                match = re.search(r'(?:^|[,:])(?:AVERAGE-)?BANDWIDTH=(\d+)', line)
                bandwidth = int(match[1]) if match else 0
            elif not line.startswith('#') and bandwidth is not None:
                target = urljoin(base, line)
                if urlsplit(target).scheme not in {'http', 'https'}:
                    raise BufferError('invalid HLS variant protocol')
                variants.append((bandwidth, target))
                bandwidth = None
        if not variants:
            raise BufferError('no usable HLS variant')
        bounded = [v for v in variants if cap_mbps and 0 < v[0] <= cap_mbps * 1000000]
        source = (max(bounded) if bounded else min(variants) if cap_mbps else max(variants))[1]
    raise BufferError('excessive HLS nesting')


@dataclass(frozen=True)
class Segment:
    name: str
    sequence: int
    start: float
    duration: float
    size: int
    discontinuity: bool = False

    @property
    def end(self):
        return self.start + self.duration


class DiskWindow:
    def __init__(self, directory, *, max_bytes=512 * 1024**2, seconds=600):
        if type(max_bytes) is not int or max_bytes < _CHUNK:
            raise ValueError('invalid quota')
        if type(seconds) not in {int, float} or not math.isfinite(seconds) or seconds < 1:
            raise ValueError('invalid duration')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_bytes, self.seconds, self.used = max_bytes, seconds, 0
        self.files, self.timeline, self._known = OrderedDict(), [], {}
        self._last_end, self._active, self._manifest = 0.0, None, None
        self.closed, self.ended, self.error = False, False, ''
        self.target_duration = None
        self._lock = threading.RLock()
        self.changed = threading.Condition(self._lock)

    def _remove(self, name):
        (self.directory / name).unlink(missing_ok=True)
        self.used -= self.files.pop(name)
        self.timeline = [row for row in self.timeline if row.name != name]

    def begin(self, name):
        with self._lock:
            if self.closed or self._active is not None or not _SEGMENT.fullmatch(name) or name in self.files:
                raise BufferError('invalid segment upload')
            while len(self.files) >= 1024:
                self._remove(next(iter(self.files)))
            self._active = (name, open(self.directory / (name + '.part'), 'xb', buffering=0), 0)

    def append(self, data):
        if len(data) > _CHUNK:
            raise ValueError('oversized write')
        with self._lock:
            if self.closed or self._active is None:
                raise BufferError('no active segment')
            while self.used + len(data) > self.max_bytes and self.files:
                self._remove(next(iter(self.files)))
            if self.used + len(data) > self.max_bytes:
                raise BufferError('one segment exceeds quota')
            name, handle, size = self._active
            written = handle.write(data)
            self.used += written
            self._active = name, handle, size + written
            if written != len(data):
                raise OSError('short spool write')

    def finish(self):
        with self._lock:
            if self._active is None:
                raise BufferError('no active segment')
            name, handle, size = self._active
            handle.close()
            (self.directory / (name + '.part')).replace(self.directory / name)
            self.files[name] = size
            self.files = OrderedDict(sorted(self.files.items(), key=lambda item: int(item[0][4:-3])))
            self._active = None
            if self._manifest is not None:
                self.publish(self._manifest)
            self.changed.notify_all()

    def abort(self):
        with self._lock:
            if self._active is not None:
                name, handle, size = self._active
                handle.close()
                (self.directory / (name + '.part')).unlink(missing_ok=True)
                self.used -= size
                self._active = None

    def publish(self, payload):
        if len(payload) > _LIMIT:
            raise BufferError('oversized manifest')
        text = payload.decode('utf-8')
        if not text.startswith('#EXTM3U'):
            raise BufferError('invalid manifest')
        sequence, duration, disc, rows = 0, None, False, []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
                sequence = int(line.partition(':')[2])
                if not 0 <= sequence <= 2**53:
                    raise BufferError('invalid sequence')
            elif line.startswith('#EXTINF:'):
                duration = float(line.partition(':')[2].partition(',')[0])
                if not math.isfinite(duration) or not 0 < duration <= 3600:
                    raise BufferError('invalid duration')
            elif line == '#EXT-X-DISCONTINUITY':
                disc = True
            elif line and not line.startswith('#'):
                name = urlsplit(line).path.rsplit('/', 1)[-1]
                if duration is None or not _SEGMENT.fullmatch(name):
                    raise BufferError('invalid segment reference')
                rows.append((sequence, name, duration, disc))
                sequence, duration, disc = sequence + 1, None, False
        if len(rows) > 1024:
            raise BufferError('too many segments')
        if not rows:
            return
        with self.changed:
            if self.closed:
                return
            self._manifest = payload
            largest = math.ceil(max(row[2] for row in rows))
            if self.target_duration is None:
                # Keep a stable reload interval; tolerate sub-second GOP drift.
                self.target_duration = largest + 1
            elif largest > self.target_duration:
                self.error = 'source GOP duration changed beyond the established playlist target'
                self.changed.notify_all()
                return
            first = rows[0][0]
            start = self._known.get(first, self._last_end)
            known, timeline = {}, []
            for seq, name, dur, discontinuity in rows:
                known[seq] = start
                if name in self.files:
                    if timeline and seq != timeline[-1].sequence + 1:
                        timeline = []
                    timeline.append(Segment(name, seq, start, dur, self.files[name], discontinuity))
                start += dur
            self._known, self._last_end = known, start
            self.timeline = timeline
            self.ended = '#EXT-X-ENDLIST' in text and rows[-1][1] in self.files
            if timeline:
                cutoff = timeline[-1].end - self.seconds
                by_name = {row.name: row for row in timeline}
                for name in list(self.files):
                    row = by_name.get(name)
                    if (row is None and int(name[4:-3]) < first) or (row is not None and row.end <= cutoff):
                        self._remove(name)
            self.changed.notify_all()

    def snapshot(self):
        with self._lock:
            return tuple(self.timeline)

    def read(self, name, offset):
        with self._lock:
            if self.closed or name not in self.files:
                return b''
            with open(self.directory / name, 'rb') as handle:
                handle.seek(offset)
                return handle.read(_CHUNK)

    def close(self):
        with self.changed:
            self.closed = True
            self.abort()
            self.changed.notify_all()


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args)

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class LiveBufferSession:
    def __init__(self, *, max_bytes=512 * 1024**2, seconds=600, directory=None):
        self._temp = tempfile.TemporaryDirectory(prefix='iptv-timeshift-', dir=directory)
        self.window = DiskWindow(self._temp.name, max_bytes=max_bytes, seconds=seconds)
        self._write_token, self._view_token = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        self._views, self._initial, self._protected = OrderedDict(), set(), set()
        self._view_lock, self._lease_lock, self._close_lock = threading.Lock(), threading.Lock(), threading.Lock()
        self._leases = 1
        self._closed, self._shutdown_finished = threading.Event(), threading.Event()
        self.cleanup_failed, self.process = False, None
        self.stderr_tail = deque(maxlen=8)
        self._stderr_thread = self._input_thread = None
        self._segment_lock, self._manifest_lock = threading.Lock(), threading.Lock()
        self._activity_lock, self._uploads, self._last_activity = threading.Lock(), 0, time.monotonic()
        self._connections, self._connection_lock = set(), threading.Lock()
        self._server = _Server(('127.0.0.1', 0), self._handler())
        self.origin = 'http://127.0.0.1:%d' % self._server.server_address[1]
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()

    def _handler(self):
        session = self
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args):
                return

            def setup(self):
                super().setup()
                self.connection.settimeout(10)
                with session._connection_lock:
                    session._connections.add(self.connection)

            def finish(self):
                try:
                    super().finish()
                finally:
                    with session._connection_lock:
                        session._connections.discard(self.connection)

            def reply(self, code, body=b'', kind='text/plain'):
                self.close_connection = True
                try:
                    self.send_response(code)
                    self.send_header('Content-Type', kind)
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    if self.command != 'HEAD':
                        self.wfile.write(body)
                except OSError:
                    LOG.debug('Loopback client closed before reply', exc_info=True)

            def chunks(self, limit):
                encoding = self.headers.get('Transfer-Encoding', '').lower()
                if encoding:
                    if encoding != 'chunked':
                        raise BufferError('invalid transfer encoding')
                    total = 0
                    while True:
                        line = self.rfile.readline(128)
                        if not line.endswith(b'\r\n'):
                            raise BufferError('invalid chunk header')
                        size = int(line.split(b';')[0].strip(), 16)
                        if size < 0 or total + size > limit:
                            raise BufferError('upload exceeds quota')
                        if size == 0:
                            if self.rfile.readline(128) != b'\r\n':
                                raise BufferError('invalid trailer')
                            return
                        total += size
                        while size:
                            part = self.rfile.read(min(_CHUNK, size))
                            if not part:
                                raise BufferError('truncated upload')
                            size -= len(part)
                            yield part
                        if self.rfile.read(2) != b'\r\n':
                            raise BufferError('invalid chunk ending')
                else:
                    left = int(self.headers.get('Content-Length', '-1'))
                    if not 0 <= left <= limit:
                        raise BufferError('invalid body length')
                    while left:
                        part = self.rfile.read(min(_CHUNK, left))
                        if not part:
                            raise BufferError('truncated upload')
                        left -= len(part)
                        yield part

            def do_PUT(self):
                prefix = '/' + session._write_token + '/'
                path = urlsplit(self.path).path
                if not path.startswith(prefix):
                    return self.reply(404)
                name = path[len(prefix):]
                if name != 'index.m3u8' and not _SEGMENT.fullmatch(name):
                    return self.reply(404)
                with session._activity_lock:
                    session._uploads += 1
                    session._last_activity = time.monotonic()
                lock = session._manifest_lock if name == 'index.m3u8' else session._segment_lock
                locked = False
                try:
                    locked = lock.acquire(timeout=2)
                    if not locked:
                        raise BufferError('concurrent upload timeout')
                    if name == 'index.m3u8':
                        session.window.publish(b''.join(self.chunks(_LIMIT)))
                    else:
                        session.window.begin(name)
                        for data in self.chunks(session.window.max_bytes):
                            session.window.append(data)
                        session.window.finish()
                    self.reply(200)
                except (OSError, ValueError, BufferError) as err:
                    if locked and name != 'index.m3u8':
                        session.window.abort()
                    with session.window.changed:
                        session.window.error = type(err).__name__ + ': ' + str(err)
                        session.window.changed.notify_all()
                    self.reply(413)
                finally:
                    if locked:
                        lock.release()
                    with session._activity_lock:
                        session._uploads -= 1
                        session._last_activity = time.monotonic()

            do_POST = do_PUT

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                parts = urlsplit(self.path).path.split('/')
                if len(parts) != 4 or parts[1] != session._view_token:
                    return self.reply(404)
                with session._view_lock:
                    first = session._views.get(parts[2])
                    initial = parts[2] in session._initial
                    if parts[3] == 'index.m3u8' and self.command != 'HEAD':
                        session._initial.discard(parts[2])
                if first is None:
                    return self.reply(404)
                if parts[3] == 'index.m3u8':
                    return self.reply(200, session.playlist(first, initial=initial), 'application/vnd.apple.mpegurl')
                name = parts[3]
                row = next((row for row in session.window.snapshot() if row.name == name and row.sequence >= first), None)
                if row is None or not _SEGMENT.fullmatch(name):
                    return self.reply(410)
                self.close_connection = True
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp2t')
                self.send_header('Content-Length', str(row.size))
                self.send_header('Connection', 'close')
                self.end_headers()
                if self.command == 'HEAD':
                    return
                offset = 0
                while offset < row.size and not session._closed.is_set():
                    data = session.window.read(name, offset)
                    if not data:
                        return
                    self.wfile.write(data)
                    offset += len(data)
        return Handler

    def playlist(self, first, *, initial=False):
        rows = [row for row in self.window.snapshot() if row.sequence >= first]
        if initial and not self.window.ended:
            rows = rows[:3]
        if not rows:
            return b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n'
        lines = ['#EXTM3U', '#EXT-X-VERSION:3', '#EXT-X-TARGETDURATION:%d' % self.window.target_duration,
                 '#EXT-X-MEDIA-SEQUENCE:%d' % rows[0].sequence, '#EXT-X-START:TIME-OFFSET=0,PRECISE=YES']
        for row in rows:
            if row.discontinuity:
                lines.append('#EXT-X-DISCONTINUITY')
            lines += ['#EXTINF:%.6f,' % row.duration, row.name]
        if self.window.ended:
            lines.append('#EXT-X-ENDLIST')
        return ('\n'.join(lines) + '\n').encode()

    def cursor(self, behind=0, *, protected=False):
        if type(behind) not in {int, float} or not math.isfinite(behind):
            raise ValueError('invalid position')
        rows = self.window.snapshot()
        if not rows:
            raise BufferError('no completed history')
        target = max(rows[0].start, rows[-1].start - max(0, behind))
        row = next((r for r in reversed(rows) if r.start <= target), rows[0])
        name = secrets.token_urlsafe(12)
        with self._view_lock:
            if protected and len(self._protected) >= 16:
                raise BufferError('too many recordings')
            self._views[name] = row.sequence
            self._initial.add(name)
            if protected:
                self._protected.add(name)
            while len(self._views) > 32:
                old = next(key for key in self._views if key not in self._protected)
                self._views.pop(old)
                self._initial.discard(old)
        return self.origin + '/' + self._view_token + '/' + name + '/index.m3u8', row

    def start(self, ffmpeg, source, headers=None, *, cap_mbps=None, popen=subprocess.Popen):
        from recorder import _header_input_args
        from http_headers import merge_headers, split_stream_modifiers
        if self.process is not None or self._closed.is_set():
            raise BufferError('session already used')
        source, modifiers = split_stream_modifiers(source)
        headers = merge_headers(headers, modifiers)
        source = resolve_hls_input(source, headers, cap_mbps)
        cmd = [str(ffmpeg), '-hide_banner', '-loglevel', 'warning', '-nostdin', '-rw_timeout', '15000000']
        if urlsplit(source).scheme in {'http', 'https'}:
            cmd += ['-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5'] + _header_input_args(headers)
        elif urlsplit(source).scheme == 'rtsp':
            cmd += ['-rtsp_transport', 'tcp']
        dest = self.origin + '/' + self._write_token + '/'
        cmd += ['-i', source, '-map', '0:v?', '-map', '0:a?', '-map', '0:s?', '-map', '0:d?',
                '-c', 'copy', '-f', 'segment', '-segment_format', 'mpegts', '-segment_time', '2',
                '-segment_list_size', str(min(1000, math.ceil(self.window.seconds / 2) + 4)),
                '-segment_list_type', 'm3u8', '-segment_list', dest + 'index.m3u8', dest + 'seg-%09d.ts']
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        self.process = popen(cmd, **kwargs)
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._input_thread = threading.Thread(target=self._finish_input, daemon=True)
        self._stderr_thread.start()
        self._input_thread.start()

    def _drain_stderr(self):
        from diagnostic_privacy import sharing_excerpt
        try:
            if self.process.stderr is None:
                return
            while not self._closed.is_set():
                data = self.process.stderr.readline(4096)
                if not data:
                    break
                line = data.decode('utf-8', errors='replace').strip()
                if line:
                    self.stderr_tail.append(sharing_excerpt(line))
                if 'muxed as a private data stream' in line or 'not currently supported in container' in line:
                    with self.window.changed:
                        self.window.error = 'input codec cannot be transparently buffered'
                        self.window.changed.notify_all()
        except (OSError, ValueError):
            LOG.debug('Buffer stderr closed', exc_info=True)

    def _finish_input(self):
        self.process.wait()
        deadline = time.monotonic() + 10
        while not self._closed.wait(0.05):
            with self._activity_lock:
                quiet = self._uploads == 0 and time.monotonic() - self._last_activity >= 0.25
            if quiet or time.monotonic() >= deadline:
                with self.window.changed:
                    if not quiet:
                        self.window.error = 'final uploads did not drain'
                    self.window.ended = True
                    self.window.changed.notify_all()
                return

    def wait_ready(self, timeout=30, cancel=None):
        deadline, ended_at = time.monotonic() + timeout, None
        with self.window.changed:
            while not self.window.timeline:
                if self._closed.is_set() or self.window.error or (cancel is not None and cancel.is_set()):
                    raise BufferError('buffer input unavailable')
                if self.process is not None and self.process.poll() is not None:
                    ended_at = ended_at or time.monotonic()
                    if time.monotonic() - ended_at > 1:
                        raise BufferError('input ended without history')
                left = deadline - time.monotonic()
                if left <= 0:
                    raise BufferError('buffer startup timed out')
                self.window.changed.wait(min(left, 0.25))
            if self.window.error:
                raise BufferError('input cannot be transparently buffered')

    def acquire(self):
        with self._lease_lock:
            if self._closed.is_set():
                raise BufferError('source is closing')
            self._leases += 1
        return BufferLease(self)

    @property
    def lease_count(self):
        with self._lease_lock:
            return self._leases

    def release(self):
        with self._lease_lock:
            self._leases -= 1
            last = self._leases == 0
        if last:
            self.close()

    def close(self):
        with self._close_lock:
            if self._shutdown_finished.is_set():
                return
            self._closed.set()
            try:
                if self.process is not None and self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.cleanup_failed = True
                LOG.exception('Could not terminate buffer input')
            for thread in (self._stderr_thread, self._input_thread):
                if thread is not None:
                    thread.join(timeout=1)
            try:
                if self.process is not None and self.process.stderr is not None:
                    self.process.stderr.close()
                self.window.close()
            except (OSError, ValueError):
                self.cleanup_failed = True
                LOG.debug('Could not close buffer files', exc_info=True)
            with self._connection_lock:
                for connection in list(self._connections):
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        LOG.debug('Buffer socket already closed', exc_info=True)
            self._server.shutdown()
            self._server.server_close()
            self._server_thread.join(timeout=2)
            try:
                self._temp.cleanup()
            except OSError:
                self.cleanup_failed = True
                LOG.debug('Buffer cache still locked', exc_info=True)
            # Never declare an unkillable upstream safely released.
            if self.process is None or self.process.poll() is not None:
                self._shutdown_finished.set()


class BufferLease:
    def __init__(self, session):
        self.session, self.cursor_name = session, None
        self._released, self._lock = False, threading.Lock()

    def release(self):
        with self._lock:
            if self._released:
                return
            self._released = True
        if self.cursor_name:
            with self.session._view_lock:
                self.session._views.pop(self.cursor_name, None)
                self.session._initial.discard(self.cursor_name)
                self.session._protected.discard(self.cursor_name)
        self.session.release()


class LiveBufferRegistry:
    def __init__(self):
        self._lock, self.ingest_gate = threading.RLock(), threading.RLock()
        self._sessions, self._sources = {}, {}
        atexit.register(self.close)

    def put(self, url, headers, session):
        with self._lock:
            for value in self._sessions.values():
                if value.cleanup_failed:
                    if not value._shutdown_finished.is_set():
                        raise BufferError('previous source is still active')
                    try:
                        value._temp.cleanup()
                        value.cleanup_failed = False
                    except OSError as err:
                        raise BufferError('old cache remains locked') from err
            for key in [k for k, v in self._sessions.items() if v._shutdown_finished.is_set()]:
                self._sessions.pop(key)
                self._sources.pop(key)
            key = source_key(url, headers)
            if key in self._sessions and self._sessions[key] is not session:
                raise BufferError('source already owned')
            self._sessions[key], self._sources[key] = session, url

    def find(self, url, headers=None):
        with self._lock:
            value = self._sessions.get(source_key(url, headers))
            return value if value is not None and not value._closed.is_set() else None

    def owns_url(self, url):
        with self._lock:
            return any(source == url and not self._sessions[k]._closed.is_set() for k, source in self._sources.items())

    def owns_view(self, url):
        with self._lock:
            return any(url.startswith(s.origin + '/' + s._view_token + '/') for s in self._sessions.values())

    def recording_input(self, url, headers=None):
        with self._lock:
            old = self._sessions.get(source_key(url, headers))
            if old is not None and old._closed.is_set() and not old._shutdown_finished.is_set():
                raise BufferError('previous source still closing')
            session = self.find(url, headers)
            if session is None:
                return url, headers, None
            if session.window.error:
                raise BufferError('unhealthy buffered input')
            lease = session.acquire()
            try:
                local, _ = session.cursor(protected=True)
                lease.cursor_name = urlsplit(local).path.split('/')[2]
                return local, {}, lease
            except Exception:
                lease.release()
                raise

    def has_provider(self, provider):
        from catchup_urls import single_stream_provider_key
        with self._lock:
            return bool(provider and any(single_stream_provider_key(url) == provider and
                not self._sessions[key]._shutdown_finished.is_set() for key, url in self._sources.items()))

    def wait_provider_idle(self, provider, cancel, timeout=10):
        deadline = time.monotonic() + timeout
        while self.has_provider(provider):
            if cancel.wait(0.05) or time.monotonic() >= deadline:
                raise BufferError('previous provider source has not stopped')

    def close(self):
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            session.close()
