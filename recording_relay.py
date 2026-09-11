"""Hand the built-in player the stream a recording is already reading.

Many IPTV providers allow one connection per account, and some block accounts
that open more. Watching a channel while recording it used to open two: libVLC
for the picture and ffmpeg for the file. Instead, the recording's ffmpeg writes
a second, untouched MPEG-TS copy of what it reads to its stdout, and this relay
serves that copy to the player over local HTTP - one provider connection.

The pump reads the pipe no matter what: if ffmpeg ever blocked on a full pipe
the recording itself would stall, so a missing or slow player simply misses
data. A player that joins starts from a short backlog, so it finds a keyframe
quickly instead of waiting for the next one.
"""

import collections
import http.server
import logging
import socketserver
import threading

LOG = logging.getLogger(__name__)

_CHUNK_BYTES = 64 * 1024
# What a player joining mid-stream is handed first (a few seconds of video).
_BACKLOG_BYTES = 2 * 1024 * 1024
# Per-player slack before chunks are dropped for it; the recording never waits.
_CLIENT_QUEUE_CHUNKS = 256


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class _Client:
    def __init__(self, backlog):
        self.chunks = collections.deque(backlog)


class RecordingRelay:
    """Serve one pipe of MPEG-TS to any number of local players at ``url``."""

    def __init__(self, source, host: str = "127.0.0.1"):
        self._source = source
        self._cond = threading.Condition()
        self._backlog: "collections.deque[bytes]" = collections.deque()
        self._backlog_size = 0
        self._clients: "list[_Client]" = []
        self._closed = False
        relay = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, format, *args):  # noqa: A002 - base class name
                pass

            def _send_headers(self):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp2t")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

            def do_HEAD(self):
                self._send_headers()

            def do_GET(self):
                self._send_headers()
                relay._serve(self.wfile)

        self._server = _Server((host, 0), Handler)
        self.url = "http://%s:%d/live.ts" % (host, self._server.server_address[1])
        threading.Thread(target=self._server.serve_forever, daemon=True,
                         name="RecordingRelayServer").start()
        threading.Thread(target=self._pump, daemon=True, name="RecordingRelayPump").start()

    @property
    def closed(self) -> bool:
        return self._closed

    def _read(self) -> bytes:
        read1 = getattr(self._source, "read1", None)
        data = read1(_CHUNK_BYTES) if callable(read1) else self._source.read(_CHUNK_BYTES)
        return bytes(data) if isinstance(data, (bytes, bytearray)) else b""

    def _pump(self) -> None:
        try:
            while True:
                chunk = self._read()
                if not chunk:
                    break
                with self._cond:
                    self._backlog.append(chunk)
                    self._backlog_size += len(chunk)
                    while self._backlog_size > _BACKLOG_BYTES and len(self._backlog) > 1:
                        self._backlog_size -= len(self._backlog.popleft())
                    for client in self._clients:
                        if len(client.chunks) < _CLIENT_QUEUE_CHUNKS:
                            client.chunks.append(chunk)
                    self._cond.notify_all()
        except Exception:
            LOG.debug("RecordingRelay._pump: ignored exception", exc_info=True)
        finally:
            with self._cond:
                self._closed = True
                self._cond.notify_all()

    def _serve(self, wfile) -> None:
        with self._cond:
            client = _Client(self._backlog)
            self._clients.append(client)
        try:
            while True:
                with self._cond:
                    while not client.chunks and not self._closed:
                        self._cond.wait(1.0)
                    if not client.chunks:
                        return  # the recording ended and everything was sent
                    chunks = list(client.chunks)
                    client.chunks.clear()
                for chunk in chunks:
                    wfile.write(chunk)
                wfile.flush()
        except OSError:
            # The player went away; the recording carries on.
            LOG.debug("RecordingRelay._serve: player disconnected", exc_info=True)
        finally:
            with self._cond:
                self._clients = [c for c in self._clients if c is not client]

    def close(self) -> None:
        """Stop serving. Players still connected get what is left, then EOF."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            LOG.debug("RecordingRelay.close: ignored exception", exc_info=True)
