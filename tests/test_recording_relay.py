"""The relay that lets the built-in player watch what a recording is reading.

One provider connection instead of two (issue #13): ffmpeg writes a copy of
the stream to its stdout and the player reads it from here.
"""
import os
import io
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

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


def test_joining_player_gets_only_two_seconds_of_recent_stream(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(recording_relay, "monotonic", lambda: now[0], raising=False)
    pipe = _Pipe()
    relay = recording_relay.RecordingRelay(pipe)
    try:
        pipe.feed(b"old-")
        assert _wait_for(lambda: relay._backlog_size == 4)
        now[0] = 1.0
        pipe.feed(b"recent-")
        assert _wait_for(lambda: relay._backlog_size == 11)
        now[0] = 2.1
        pipe.feed(b"live")
        pipe.end()
        assert _wait_for(lambda: relay.closed)
        output = io.BytesIO()
        relay._serve(output)
        assert output.getvalue() == b"recent-live"
        assert relay._backlog_size == 11
    finally:
        pipe.end()
        relay.close()


def test_joining_after_a_source_gap_does_not_replay_stale_stream(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(recording_relay, "monotonic", lambda: now[0], raising=False)
    pipe = _Pipe()
    relay = recording_relay.RecordingRelay(pipe)
    try:
        pipe.feed(b"stale")
        pipe.end()
        assert _wait_for(lambda: relay.closed)
        now[0] = 2.1
        output = io.BytesIO()
        relay._serve(output)
        assert output.getvalue() == b""
        assert relay._backlog_size == 0
    finally:
        relay.close()


class _SlowWriter(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.resume = threading.Event()

    def write(self, chunk):
        result = super().write(chunk)
        if not self.started.is_set():
            self.started.set()
            assert self.resume.wait(5)
        return result


def test_slow_player_skips_old_chunks_after_a_write_stalls(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(recording_relay, "monotonic", lambda: now[0], raising=False)
    pipe = _Pipe()
    relay = recording_relay.RecordingRelay(pipe)
    output = _SlowWriter()
    reader = threading.Thread(target=relay._serve, args=(output,))
    try:
        pipe.feed(b"first-")
        pipe.feed(b"stale-")
        assert _wait_for(lambda: relay._backlog_size == 12)
        reader.start()
        assert output.started.wait(5)
        now[0] = 3.0
        pipe.feed(b"live")
        pipe.end()
        assert _wait_for(lambda: relay.closed)
        output.resume.set()
        reader.join(5)
        assert not reader.is_alive()
        assert output.getvalue() == b"first-live"
    finally:
        output.resume.set()
        pipe.end()
        reader.join(5)
        relay.close()


def test_full_player_queue_keeps_newest_chunks_without_blocking_recording(monkeypatch):
    monkeypatch.setattr(recording_relay, "monotonic", lambda: 0.0, raising=False)
    pipe = _Pipe()
    relay = recording_relay.RecordingRelay(pipe)
    output = _SlowWriter()
    reader = threading.Thread(target=relay._serve, args=(output,))
    try:
        pipe.feed(b"first-")
        reader.start()
        assert output.started.wait(5)
        chunks = [bytes((index // 256, index % 256)) for index in range(300)]
        for chunk in chunks:
            pipe.feed(chunk)
        pipe.end()
        assert _wait_for(lambda: relay.closed)
        output.resume.set()
        reader.join(5)
        assert not reader.is_alive()
        assert output.getvalue() == b"first-" + b"".join(chunks[-256:])
    finally:
        output.resume.set()
        pipe.end()
        reader.join(5)
        relay.close()


def test_the_relay_refuses_a_request_without_its_token():
    """The relay serves the recording being made.

    Any process on the machine could find the port and watch it, so the URL
    carries a token and a request without it is refused.
    """
    pipe = _Pipe()
    pipe.feed(b"payload")
    relay = recording_relay.RecordingRelay(pipe)
    try:
        assert relay.url.endswith("/live.ts")
        assert relay.url.count("/") == 4, "the URL carries no token"

        port = relay.url.split(":")[2].split("/")[0]
        stranger = "http://127.0.0.1:%s/live.ts" % port
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(stranger, timeout=5)
        assert excinfo.value.code == 404

        with urllib.request.urlopen(relay.url, timeout=5) as response:
            assert response.status == 200
    finally:
        pipe.end()
        relay.close()
