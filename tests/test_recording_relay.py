"""The relay that lets the built-in player watch what a recording is reading.

One provider connection instead of two (issue #13): ffmpeg writes a copy of
the stream to its stdout and the player reads it from here.
"""
import os
import queue
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recording_relay  # noqa: E402


class _Pipe:
    """Stands in for ffmpeg's stdout: read1() blocks until data or EOF."""

    def __init__(self):
        self._chunks = queue.Queue()

    def feed(self, data):
        self._chunks.put(data)

    def end(self):
        self._chunks.put(b"")

    def read1(self, _size):
        return self._chunks.get()


def _get_all(url, results):
    with urllib.request.urlopen(url, timeout=10) as response:
        results.append((response.status, response.headers.get("Content-Type"), response.read()))


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_player_gets_the_stream_until_the_recording_ends(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    pipe = _Pipe()
    relay = recording_relay.RecordingRelay(pipe)
    try:
        pipe.feed(b"backlog-")
        assert _wait_for(lambda: relay._backlog)
        results = []
        reader = threading.Thread(target=_get_all, args=(relay.url, results))
        reader.start()
        assert _wait_for(lambda: relay._clients)
        pipe.feed(b"live")
        pipe.end()
        reader.join(10)
        (status, ctype, body), = results
        assert status == 200 and ctype == "video/mp2t"
        # Joining mid-stream starts from the backlog, then carries on live.
        assert body == b"backlog-live"
    finally:
        relay.close()


def test_the_recording_never_waits_for_a_player():
    pipe = _Pipe()
    relay = recording_relay.RecordingRelay(pipe)
    try:
        for _ in range(200):  # 12.8 MB with nobody watching
            pipe.feed(b"x" * 64 * 1024)
        pipe.end()
        assert _wait_for(lambda: relay.closed)
        # Only a short backlog is kept for a player that joins later.
        assert relay._backlog_size <= recording_relay._BACKLOG_BYTES
    finally:
        relay.close()


def test_head_answers_like_a_stream(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    pipe = _Pipe()
    relay = recording_relay.RecordingRelay(pipe)
    try:
        request = urllib.request.Request(relay.url, method="HEAD")
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
            assert response.headers.get("Content-Type") == "video/mp2t"
    finally:
        pipe.end()
        relay.close()
