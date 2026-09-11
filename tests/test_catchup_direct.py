"""Tests for the fast direct-download URL derivation."""

import http.server
import threading
import time

import pytest

import catchup_direct


class _OneStreamProvider(http.server.BaseHTTPRequestHandler):
    """A redirector plus an archive server that allows one stream per token.

    Modelled on teleelevidenie as measured: ``/play/...`` answers 302 to the
    archive's ``timeshift_abs-<utc>.ts``; any request to that stream holds the
    token, and while it is held the ``index-<utc>-<len>.mp4`` file is 403.
    """

    busy_until = 0.0
    requests: list = []

    def log_message(self, format, *args):  # noqa: A002 - base class name
        pass

    def _reply(self, status, ctype="", location=""):
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", "0" if status != 200 else "1000")
        self.end_headers()

    def _answer(self):
        cls = type(self)
        path = self.path.split("?", 1)[0]
        cls.requests.append((self.command, path))
        if path.startswith("/play/"):
            self._reply(302, location="/PL_TVP1_HD/timeshift_abs-1789065000.ts?token=abc")
        elif path.startswith("/PL_TVP1_HD/timeshift_abs-"):
            cls.busy_until = time.monotonic() + 30
            self._reply(200, "video/mpeg")
        elif path == "/PL_TVP1_HD/index-1789065000-3300.mp4" and "token=abc" in self.path:
            if time.monotonic() < cls.busy_until:
                self._reply(403, "text/plain")
            else:
                self._reply(200, "video/mp4")
        else:
            self._reply(404, "text/plain")

    do_HEAD = _answer
    do_GET = _answer


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(catchup_direct, "_MEDIA_SESSION_SETTLE_SECONDS", 0)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    _OneStreamProvider.busy_until = 0.0
    _OneStreamProvider.requests = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OneStreamProvider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def test_the_probe_never_opens_the_archive_stream(provider):
    """The reported failure: resolving the redirect by following it opened the
    stream, so the .mp4 probe - and then ffmpeg - were refused with 403."""
    url = provider + "/play/mpegts-c468-tabc?utc=1789065000&lutc=1789142000"
    found = catchup_direct.direct_download_url(url, 1789065000, 3300)
    assert found == provider + "/PL_TVP1_HD/index-1789065000-3300.mp4?token=abc"
    assert not [r for r in _OneStreamProvider.requests if "timeshift_abs" in r[1]]


def test_next_hop_reads_the_location_without_following_it(provider):
    target, is_media = catchup_direct._next_hop(provider + "/play/x", {}, 5.0)
    assert target == provider + "/PL_TVP1_HD/timeshift_abs-1789065000.ts?token=abc"
    assert is_media is False
    assert _OneStreamProvider.requests == [("HEAD", "/play/x")]


def test_candidates_swap_a_dated_m3u8_for_its_mp4():
    url = "https://host/seg/index-1700000000-60.m3u8?token=abc"
    out = catchup_direct.candidate_direct_urls(url, 1700000099, 90)
    # The playlist's own numbers are the server's truth and come first.
    assert out[0] == "https://host/seg/index-1700000000-60.mp4?token=abc"
    assert "https://host/seg/index-1700000099-90.mp4?token=abc" in out


def test_candidates_keep_the_query_string():
    url = "https://host/dir/index.m3u8?token=abc"
    out = catchup_direct.candidate_direct_urls(url, 1000, 60)
    assert all("token=abc" in candidate for candidate in out)


def test_candidates_try_the_first_path_segment():
    url = "https://host/deep/dir/index.m3u8?utc=1000&dur=60"
    out = catchup_direct.candidate_direct_urls(url, 1000, 60)
    assert "https://host/deep/index-1000-60.mp4?utc=1000&dur=60" in out


def test_candidates_have_no_duplicates():
    url = "https://host/one/index-1000-60.m3u8?x=1"
    out = catchup_direct.candidate_direct_urls(url, 1000, 60)
    assert len(out) == len(set(out))


def test_candidates_reject_useless_urls():
    assert catchup_direct.candidate_direct_urls("", 1, 1) == []
    assert catchup_direct.candidate_direct_urls("not a url", 1, 1) == []


def test_media_header_check_rejects_html_fallbacks():
    class Headers:
        def __init__(self, content_type, length=None):
            self._ct = content_type
            self._len = length

        def get(self, name, default=None):
            if name == "Content-Type":
                return self._ct
            if name == "Content-Length":
                return self._len
            return default

    assert catchup_direct._headers_look_like_media(Headers("video/mp4"))
    assert catchup_direct._headers_look_like_media(Headers(""))
    assert not catchup_direct._headers_look_like_media(Headers("text/html"))
    assert not catchup_direct._headers_look_like_media(Headers("application/json"))
