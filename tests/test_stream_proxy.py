import base64
import json
import os
import sys
import threading
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stream_proxy as stream_proxy_module
from stream_proxy import (
    HLSConverter,
    StreamProxy,
    filter_unstable_hls_start,
    get_ffmpeg_path,
    hls_playlist_is_ready,
    hls_playlist_stats,
    normalize_request_headers,
    rewrite_hls_playlist,
)


def test_a_refreshed_credential_replaces_the_running_converter():
    """The running ffmpeg has the credentials it started with.

    A provider that rotates its session cookie refuses the old one, so the
    cast died until the converter happened to be retired.
    """
    proxy = StreamProxy()
    url = "https://provider.example.test/live.ts"

    proxy.get_transcoded_url(url, {"Cookie": "old"})
    assert len(proxy.converters) == 1
    session_id, converter = next(iter(proxy.converters.items()))
    assert converter.headers["Cookie"] == "old"

    proxy.get_transcoded_url(url, {"Cookie": "new"})

    assert len(proxy.converters) == 1, "a second converter was left running"
    assert proxy.converters[session_id].headers["Cookie"] == "new"


def test_an_unchanged_credential_keeps_the_running_converter():
    """Re-issuing the same URL must not restart the transcode."""
    proxy = StreamProxy()
    url = "https://provider.example.test/live.ts"

    proxy.get_transcoded_url(url, {"Cookie": "same"})
    session_id, converter = next(iter(proxy.converters.items()))

    proxy.get_transcoded_url(url, {"Cookie": "same"})

    assert proxy.converters[session_id] is converter


def test_an_http_error_is_not_a_drop_to_reopen():
    """A live source that ends is reopened at the edge; a refused session is not.

    Reopening a 403 for ever held ffmpeg and the provider's stream slot
    with nothing reported.
    """
    import urllib.error

    refused = urllib.error.HTTPError("http://h/live.m3u8", 403, "Forbidden", None, None)
    assert stream_proxy_module._is_upstream_gone(refused)
    # A transport error is a drop.
    assert not stream_proxy_module._is_upstream_gone(OSError("connection reset"))


def test_the_ffmpeg_comes_from_the_app_not_the_current_directory(tmp_path, monkeypatch):
    """Windows resolves the current directory before PATH.

    An ffmpeg.exe that happens to sit in the folder the app was started
    from would be executed instead of the real one - with the user's
    privileges, on every transcode.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ffmpeg.exe").write_bytes(b"not ffmpeg")

    path = get_ffmpeg_path()

    assert os.path.dirname(path), "ffmpeg would be taken from the current directory"
    assert os.path.abspath(str(tmp_path)) not in os.path.abspath(path)


def test_a_gateway_session_keeps_every_host_it_was_issued_for():
    """One header set serves every URL the app issues with it.

    A provider's channels share one cookie, so they share one session, and a
    redirect the provider taught the proxy about has to survive the next URL.
    Replacing the host set lost those hosts, and the channel's credentials
    stopped going to them.
    """
    proxy = StreamProxy()
    headers = {"Cookie": "session=secret"}
    url = proxy.get_gateway_url("https://provider.example.test/live/one.ts", headers)
    sid = url.split("/g/")[1].split("/")[0]
    proxy.note_gateway_host(sid, "cdn.example.test")

    proxy.get_gateway_url("https://second.example.test/live/two.ts", headers)

    for host in ("provider.example.test", "second.example.test", "cdn.example.test"):
        assert proxy.gateway_headers_for(sid, host)["Cookie"] == "session=secret"
    # A host nobody named still gets nothing.
    assert proxy.gateway_headers_for(sid, "attacker.example") == {}


def test_the_gateway_keeps_the_channel_credentials_on_its_own_host():
    """The gateway URL carries the upstream host, and the token in it goes out
    to every receiver on the LAN.

    Sending the channel's credentials to whatever host a request names would
    hand them to whoever asked, so they only travel to the host the session
    was created for.
    """
    proxy = StreamProxy()
    proxy.host = "127.0.0.1"
    proxy.port = 12345

    url = proxy.get_gateway_url(
        "https://provider.example.test/live/stream.ts",
        {"Cookie": "session=secret", "User-Agent": "ChannelUA"},
    )
    sid = url.split("/g/")[1].split("/")[0]

    own = proxy.gateway_headers_for(sid, "provider.example.test")
    assert own["Cookie"] == "session=secret"

    # Somebody on the LAN reusing the token for their own host.
    stranger = proxy.gateway_headers_for(sid, "attacker.example")
    assert stranger == {}

    # A host the provider redirected the session to is part of the session.
    proxy.note_gateway_host(sid, "cdn.example.test")
    assert proxy.gateway_headers_for(sid, "cdn.example.test")["Cookie"] == "session=secret"

    # An unknown session is not a session at all.
    assert proxy.gateway_headers_for("nosuchsession", "provider.example.test") is None


def test_global_proxy_is_created_lazily():
    old_proxy = stream_proxy_module._PROXY
    try:
        stream_proxy_module._PROXY = None

        proxy = stream_proxy_module.get_proxy()

        assert isinstance(proxy, StreamProxy)
        assert stream_proxy_module._PROXY is proxy
        assert stream_proxy_module.get_proxy() is proxy
    finally:
        if stream_proxy_module._PROXY is not None:
            try:
                stream_proxy_module._PROXY.stop()
            except Exception:
                pass
        stream_proxy_module._PROXY = old_proxy


def test_normalize_request_headers_expands_extra_headers():
    headers = normalize_request_headers(
        {
            "user-agent": "TestAgent/1",
            "http-referrer": "https://example.test/page",
            "accept": ["video/mp2t"],
            "_extra": [
                "X-Provider-Token: abc123",
                "User-Agent: ShouldNotOverride",
                "malformed",
            ],
        }
    )

    assert headers["User-Agent"] == "TestAgent/1"
    assert headers["Referer"] == "https://example.test/page"
    assert headers["Accept"] == "video/mp2t"
    assert headers["X-Provider-Token"] == "abc123"
    assert "_extra" not in headers


def test_get_stream_url_preserves_extra_headers_in_encoded_query():
    proxy = StreamProxy()

    proxied = proxy.get_stream_url(
        "https://stream.example.test/live",
        headers={
            "http-user-agent": "TestAgent/2",
            "_extra": ["X-Provider-Token: def456"],
        },
    )

    query = urllib.parse.parse_qs(urllib.parse.urlparse(proxied).query)
    encoded_headers = query["headers"][0]
    decoded_headers = json.loads(base64.b64decode(encoded_headers).decode())

    assert decoded_headers["User-Agent"] == "TestAgent/2"
    assert decoded_headers["X-Provider-Token"] == "def456"
    assert "_extra" not in decoded_headers


def test_chromecast_transcode_url_uses_fresh_session_and_stops_previous(monkeypatch):
    monkeypatch.setattr(stream_proxy_module.time, "time_ns", lambda: 123456789)
    created = []

    class FakeConverter:
        def __init__(self, source_url, headers=None, transcode_profile="auto"):
            self.source_url = source_url
            self.headers = headers
            self.transcode_profile = transcode_profile
            self.stopped = False
            created.append(self)

        def stop(self):
            self.stopped = True

        def touch(self):
            pass

    monkeypatch.setattr(stream_proxy_module, "HLSConverter", FakeConverter)
    proxy = StreamProxy()
    proxy.host = "127.0.0.1"
    proxy.port = 12345

    first = proxy.get_transcoded_url("https://stream.example.test/live", transcode_profile="chromecast_h264")
    second = proxy.get_transcoded_url("https://stream.example.test/live", transcode_profile="chromecast_h264")

    assert first != second
    assert created[0].stopped
    assert not created[1].stopped
    assert len(proxy.converters) == 1


def test_chromecast_transcode_url_stops_previous_different_source(monkeypatch):
    created = []

    class FakeConverter:
        def __init__(self, source_url, headers=None, transcode_profile="auto"):
            self.source_url = source_url
            self.headers = headers
            self.transcode_profile = transcode_profile
            self.stopped = False
            created.append(self)

        def stop(self):
            self.stopped = True

        def touch(self):
            pass

    monkeypatch.setattr(stream_proxy_module, "HLSConverter", FakeConverter)
    proxy = StreamProxy()
    proxy.host = "127.0.0.1"
    proxy.port = 12345

    first = proxy.get_transcoded_url("https://stream.example.test/one", transcode_profile="chromecast_h264")
    second = proxy.get_transcoded_url("https://stream.example.test/two", transcode_profile="chromecast_h264")

    assert first != second
    assert created[0].stopped
    assert not created[1].stopped
    assert len(proxy.converters) == 1


def test_hls_converter_command_omits_removed_hls_version_option():
    converter = object.__new__(HLSConverter)
    converter.temp_dir = os.path.join(os.getcwd(), "unused-remux-dir")
    converter.playlist_path = os.path.join(converter.temp_dir, "stream.m3u8")
    converter.profile = "auto"

    cmd = converter._build_ffmpeg_command()

    assert "-hls_version" not in cmd
    assert "-hls_segment_type" in cmd
    assert "mpegts" in cmd
    assert cmd[cmd.index("-hls_list_size") + 1] == "8"
    assert "-hls_delete_threshold" not in cmd
    assert "-hls_init_time" not in cmd


def test_hls_converter_chromecast_profile_transcodes_video_to_h264():
    converter = object.__new__(HLSConverter)
    converter.temp_dir = os.path.join(os.getcwd(), "unused-remux-dir")
    converter.playlist_path = os.path.join(converter.temp_dir, "stream.m3u8")
    converter.profile = "chromecast_h264"

    cmd = converter._build_ffmpeg_command()

    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert "-pix_fmt" in cmd
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert "-force_key_frames" in cmd
    assert "-hls_flags" not in cmd


def test_hls_segment_cleanup_keeps_recent_backlog(tmp_path, monkeypatch):
    converter = object.__new__(HLSConverter)
    converter.temp_dir = str(tmp_path)
    monkeypatch.setattr(stream_proxy_module, "_HLS_RETAINED_SEGMENT_COUNT", 3)

    for index in range(1, 7):
        (tmp_path / f"seg_{index}.ts").write_bytes(b"segment")
    (tmp_path / "stream.m3u8").write_text("#EXTM3U\n", encoding="utf-8")

    converter._cleanup_old_segments_once()

    remaining = sorted(path.name for path in tmp_path.glob("seg_*.ts"))
    assert remaining == ["seg_4.ts", "seg_5.ts", "seg_6.ts"]


def test_hls_converter_bootstrap_requires_upstream_data():
    class RunningProcess:
        def poll(self):
            return None

    converter = object.__new__(HLSConverter)
    converter.process = RunningProcess()
    converter._bytes_pumped = 0
    converter._state_lock = threading.Lock()

    assert not converter.can_serve_bootstrap()

    converter._bytes_pumped = 1

    assert converter.can_serve_bootstrap()


def test_wait_for_playlist_extends_while_upstream_still_flowing(tmp_path, monkeypatch):
    """Slow CDNs (signed redirects, etc.) may take >base timeout to hand over
    the first segment. As long as upstream bytes are still arriving, the wait
    must continue up to the extended deadline instead of returning False at
    the base timeout — otherwise the proxy 503s and Chromecast idles to ERROR.
    """
    class RunningProcess:
        def poll(self):
            return None

    converter = object.__new__(HLSConverter)
    converter.temp_dir = str(tmp_path)
    converter.playlist_path = os.path.join(converter.temp_dir, "stream.m3u8")
    converter.profile = "chromecast_h264"
    converter.process = RunningProcess()
    converter._bytes_pumped = 0
    converter._startup_error = None
    converter._state_lock = threading.Lock()

    # Pretend upstream is steadily delivering bytes throughout the wait.
    clock = {"t": 1000.0}
    tick = {"sleeps": 0}

    def fake_sleep(secs):
        clock["t"] += secs if secs > 0 else 0.2
        tick["sleeps"] += 1
        converter._bytes_pumped += 8192
        # Simulate first segments landing well after the base timeout fires.
        if tick["sleeps"] == 75:
            for i in range(1, 8):
                (tmp_path / f"seg_{i}.ts").write_bytes(b"x" * (160 * 1024))
            playlist_lines = ["#EXTM3U\n", "#EXT-X-VERSION:3\n",
                              "#EXT-X-TARGETDURATION:2\n",
                              "#EXT-X-MEDIA-SEQUENCE:1\n"]
            for i in range(1, 8):
                playlist_lines.append("#EXTINF:2.0,\n")
                playlist_lines.append(f"seg_{i}.ts\n")
            (tmp_path / "stream.m3u8").write_text("".join(playlist_lines), encoding="utf-8")

    monkeypatch.setattr(stream_proxy_module.time, "sleep", fake_sleep)
    monkeypatch.setattr(stream_proxy_module.time, "time", lambda: clock["t"])

    # 75 sleeps × 0.2s = 15s — past the base 10s timeout but inside extended 30s.
    assert converter.wait_for_playlist(timeout=10, extended_timeout=30)


def test_handler_log_message_does_not_touch_stderr(monkeypatch):
    """In PyInstaller --noconsole builds sys.stderr is None. BaseHTTPRequestHandler's
    default log_message writes to it, which raises on the first line of every
    handler (send_response → log_request → log_message) and the receiver sees an
    empty reply. Our override must route through LOG and never raise.
    """
    from stream_proxy import StreamProxyHandler

    monkeypatch.setattr(stream_proxy_module.sys, "stderr", None)

    handler = object.__new__(StreamProxyHandler)
    handler.client_address = ("192.0.2.1", 9999)

    # Must not raise even though sys.stderr is None.
    handler.log_message("GET %s HTTP/1.1", "/transcode/abc/stream.m3u8")
    handler.log_error("simulated error %d", 500)


def test_wait_for_playlist_gives_up_when_upstream_stalls(tmp_path, monkeypatch):
    """If no upstream bytes arrive at all, we still bail at the base timeout."""
    class RunningProcess:
        def poll(self):
            return None

    converter = object.__new__(HLSConverter)
    converter.temp_dir = str(tmp_path)
    converter.playlist_path = os.path.join(converter.temp_dir, "stream.m3u8")
    converter.profile = "chromecast_h264"
    converter.process = RunningProcess()
    converter._bytes_pumped = 0
    converter._startup_error = None
    converter._state_lock = threading.Lock()

    clock = {"t": 1000.0}

    def fake_sleep(secs):
        clock["t"] += secs if secs > 0 else 0.2

    monkeypatch.setattr(stream_proxy_module.time, "sleep", fake_sleep)
    monkeypatch.setattr(stream_proxy_module.time, "time", lambda: clock["t"])

    assert not converter.wait_for_playlist(timeout=5, extended_timeout=30)


def test_rewrite_hls_playlist_preserves_ffmpeg_media_tags():
    rewritten = rewrite_hls_playlist(
        [
            "#EXTM3U\n",
            "#EXT-X-VERSION:3\n",
            "#EXT-X-TARGETDURATION:2\n",
            "#EXT-X-MEDIA-SEQUENCE:11\n",
            "#EXTINF:2.000000,\n",
            "seg_11.ts\n",
        ],
        "http://192.0.2.1:1234/transcode/session/",
    )

    assert rewritten.count("#EXT-X-TARGETDURATION") == 1
    assert "#EXT-X-DISCONTINUITY" not in rewritten
    assert "http://192.0.2.1:1234/transcode/session/seg_11.ts" in rewritten


def test_hls_playlist_readiness_waits_for_stable_start_window():
    not_ready, stats = hls_playlist_is_ready(
        [
            "#EXTM3U\n",
            "#EXT-X-MEDIA-SEQUENCE:1\n",
            "#EXTINF:0.167000,\n",
            "seg_1.ts\n",
            "#EXTINF:1.333000,\n",
            "seg_2.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_3.ts\n",
        ]
    )

    assert not not_ready
    assert stats["segment_count"] == 3

    ready, stats = hls_playlist_is_ready(
        [
            "#EXTM3U\n",
            "#EXT-X-MEDIA-SEQUENCE:1\n",
            "#EXTINF:0.167000,\n",
            "seg_1.ts\n",
            "#EXTINF:1.333000,\n",
            "seg_2.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_3.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_4.ts\n",
        ]
    )

    assert ready
    assert stats["duration"] >= 5.0


def test_hls_playlist_filter_drops_tiny_startup_segments(tmp_path):
    (tmp_path / "seg_1.ts").write_bytes(b"x" * 1000)
    (tmp_path / "seg_2.ts").write_bytes(b"x" * 2000)
    (tmp_path / "seg_3.ts").write_bytes(b"x" * (160 * 1024))
    (tmp_path / "seg_4.ts").write_bytes(b"x" * (170 * 1024))
    (tmp_path / "seg_5.ts").write_bytes(b"x" * (180 * 1024))

    lines = [
        "#EXTM3U\n",
        "#EXT-X-VERSION:3\n",
        "#EXT-X-TARGETDURATION:2\n",
        "#EXT-X-MEDIA-SEQUENCE:1\n",
        "#EXTINF:2.000000,\n",
        "seg_1.ts\n",
        "#EXTINF:2.000000,\n",
        "seg_2.ts\n",
        "#EXTINF:2.000000,\n",
        "seg_3.ts\n",
        "#EXTINF:2.000000,\n",
        "seg_4.ts\n",
        "#EXTINF:2.000000,\n",
        "seg_5.ts\n",
    ]

    filtered = filter_unstable_hls_start(lines, str(tmp_path))

    assert "#EXT-X-MEDIA-SEQUENCE:4" in filtered
    assert "seg_1.ts" not in filtered
    assert "seg_2.ts" not in filtered
    assert "seg_3.ts" not in filtered
    assert "seg_4.ts" in filtered


def test_hls_playlist_readiness_waits_for_post_startup_segment(tmp_path):
    for index in range(1, 4):
        (tmp_path / f"seg_{index}.ts").write_bytes(b"x" * (160 * 1024))

    ready, stats = hls_playlist_is_ready(
        [
            "#EXTM3U\n",
            "#EXT-X-MEDIA-SEQUENCE:1\n",
            "#EXTINF:2.000000,\n",
            "seg_1.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_2.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_3.ts\n",
        ],
        segment_dir=str(tmp_path),
        require_stable_start=True,
    )

    assert not ready
    assert stats["media_sequence"] == 4
    assert stats["segment_count"] == 0


def test_hls_playlist_filter_does_not_trim_later_sliding_windows(tmp_path):
    lines = [
        "#EXTM3U\n",
        "#EXT-X-MEDIA-SEQUENCE:31\n",
    ]
    for index in range(31, 39):
        (tmp_path / f"seg_{index}.ts").write_bytes(b"x" * (160 * 1024))
        lines.extend(["#EXTINF:2.000000,\n", f"seg_{index}.ts\n"])

    filtered = filter_unstable_hls_start(lines, str(tmp_path))
    stats = hls_playlist_stats(filtered)

    assert stats["media_sequence"] == 31
    assert stats["first_segment"] == "seg_31.ts"
    assert stats["segment_count"] == 8


def test_hls_playlist_readiness_uses_filtered_stable_window(tmp_path):
    (tmp_path / "seg_1.ts").write_bytes(b"x" * 1000)
    (tmp_path / "seg_2.ts").write_bytes(b"x" * 2000)
    for index in range(3, 7):
        (tmp_path / f"seg_{index}.ts").write_bytes(b"x" * (160 * 1024))

    ready, stats = hls_playlist_is_ready(
        [
            "#EXTM3U\n",
            "#EXT-X-MEDIA-SEQUENCE:1\n",
            "#EXTINF:2.000000,\n",
            "seg_1.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_2.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_3.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_4.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_5.ts\n",
            "#EXTINF:2.000000,\n",
            "seg_6.ts\n",
        ],
        segment_dir=str(tmp_path),
        require_stable_start=True,
    )

    assert ready
    assert stats["media_sequence"] == 4
    assert stats["first_segment"] == "seg_4.ts"



def test_proxy_only_fetches_http_upstreams():
    """urllib opens file:// too; the LAN-facing proxy must never serve local files."""
    assert stream_proxy_module.is_allowed_upstream_url("http://host/live.ts")
    assert stream_proxy_module.is_allowed_upstream_url("HTTPS://host/live.m3u8")
    assert not stream_proxy_module.is_allowed_upstream_url("file:///C:/Users/me/iptvclient.conf#.mp3")
    assert not stream_proxy_module.is_allowed_upstream_url("ftp://host/x.mp3")
    assert not stream_proxy_module.is_allowed_upstream_url("")


def test_proxy_urls_carry_the_access_token():
    proxy = StreamProxy()
    proxy.host = "127.0.0.1"
    proxy.port = 12345
    url = proxy.get_stream_url("http://host/live.ts")
    assert url.startswith("http://127.0.0.1:12345/" + proxy.token + "/stream?")
    assert len(proxy.token) >= 16
    assert StreamProxy().token != proxy.token


class _RecordingHandler(stream_proxy_module.StreamProxyHandler):
    def __init__(self, path):
        self.path = path
        self.errors = []
        self.client_address = ("192.0.2.1", 9999)

    def send_error(self, code, *_args, **_kwargs):
        self.errors.append(code)


def _with_token(monkeypatch, token):
    proxy = StreamProxy()
    proxy.token = token
    monkeypatch.setattr(stream_proxy_module, "get_proxy", lambda: proxy)
    return proxy


def test_proxy_refuses_requests_without_the_token(monkeypatch):
    _with_token(monkeypatch, "secret-token")
    for path in ("/stream?url=http%3A%2F%2Fhost%2Fx.mp3",
                 "/wrong/stream?url=http%3A%2F%2Fhost%2Fx.mp3",
                 "/bootstrap.ts"):
        handler = _RecordingHandler(path)
        handler.do_GET()
        assert handler.errors == [404], path


def test_proxy_refuses_a_file_url_even_with_the_token(monkeypatch):
    _with_token(monkeypatch, "secret-token")
    target = urllib.parse.quote("file:///C:/Users/me/iptvclient.conf#.mp3", safe="")
    handler = _RecordingHandler("/secret-token/stream?mode=audio&url=" + target)
    handler.do_GET()
    assert handler.errors == [403]


def test_an_unused_gateway_session_is_dropped():
    """A gateway session holds the channel's request headers.

    One that nothing uses must not stay in memory for the rest of the
    session.
    """
    import time

    proxy = StreamProxy()
    url = proxy.get_gateway_url("https://provider.example.test/live/stream.ts",
                                {"Cookie": "session=secret"})
    sid = url.split("/g/")[1].split("/")[0]
    assert sid in proxy._gateway_sessions

    proxy._expire_gateway_sessions(time.time() + 10)
    assert sid in proxy._gateway_sessions, "a session in use was dropped"

    proxy._expire_gateway_sessions(time.time() + 2 * 3600)
    assert sid not in proxy._gateway_sessions
    assert proxy.gateway_headers_for(sid, "provider.example.test") is None


def test_the_cleanup_path_does_not_deadlock_on_the_proxy_lock():
    """The cleanup loop holds the proxy lock and calls the gateway expiry,
    which takes that same lock again on the same thread.

    A non-reentrant lock deadlocked there: the cleanup thread wedged for
    good with the lock held, and every converter, playlist and segment
    request blocked ten seconds after the proxy started.
    """
    import time

    proxy = StreamProxy()
    done = threading.Event()

    def _cleanup_once():
        with proxy.lock:
            proxy._expire_gateway_sessions(time.time())
        done.set()

    worker = threading.Thread(target=_cleanup_once, daemon=True)
    worker.start()
    assert done.wait(5), "the cleanup path deadlocked on the proxy lock"

def test_the_proxy_handlers_are_daemon_threads():
    """The handler threads stream for as long as the receiver listens.

    As ordinary threads they are joined when the server closes and when the
    interpreter exits, so the app does not go away while a cast is playing.
    """
    proxy = StreamProxy()
    proxy.start()
    try:
        assert proxy.server is not None
        assert proxy.server.daemon_threads is True
    finally:
        proxy.stop()


def test_a_drive_relative_segment_name_is_refused():
    """A name like "C:file" escapes the folder it is joined to.

    Windows resolves it against that drive's current directory, so a client
    with the cast token could read a file from beside the application.
    """
    assert stream_proxy_module._is_safe_segment_name("seg1.ts") is True
    assert stream_proxy_module._is_safe_segment_name("..") is False
    assert stream_proxy_module._is_safe_segment_name("C:iptvclient.conf") is False
    assert stream_proxy_module._is_safe_segment_name("a:b") is False
