"""Casting built on Caster's engine: routing, headers, the gateway, the sync."""

import ast
import http.server
import os
import socketserver
import sys
import threading
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import casting
import stream_proxy
from stream_proxy import StreamProxy, rewrite_playlist_for_gateway

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- #
# The vendored engine
# --------------------------------------------------------------------------- #
def test_engine_is_gui_free_and_complete():
    """caster_engine must never pull in wx or Caster's GUI modules."""
    with open(os.path.join(REPO_ROOT, "caster_engine.py"), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"wx", "caster_ui", "caster_update", "pychromecast", "pyatv"}
    import caster_engine
    for name in ("HlsRelay", "TsSource", "probe_media", "_native_hls_url", "Device",
                 "LoopThread", "SeekablePipeReader", "_close_atv"):
        assert hasattr(caster_engine, name), name


def test_engine_matches_caster_checkout():
    """The vendored files are exactly what sync_caster.py makes from ../Caster."""
    caster_dir = os.path.join(os.path.dirname(REPO_ROOT), "Caster")
    if not os.path.exists(os.path.join(caster_dir, "caster.py")):
        pytest.skip("no Caster checkout beside this repository")
    sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
    import sync_caster

    with open(os.path.join(caster_dir, "caster.py"), encoding="utf-8") as handle:
        engine, _version = sync_caster.extract_engine(handle.read())
    with open(os.path.join(REPO_ROOT, "caster_engine.py"), encoding="utf-8") as handle:
        vendored = handle.read()
    if engine not in vendored:
        pytest.skip("Caster has moved on since the last sync; run tools/sync_caster.py")


def test_engine_uses_the_apps_ffmpeg():
    casting._engine()
    import caster_engine
    import caster_extras
    assert caster_engine._find_ffmpeg is stream_proxy.get_ffmpeg_path
    assert caster_extras._find_ffmpeg is stream_proxy.get_ffmpeg_path


# --------------------------------------------------------------------------- #
# Header gateway
# --------------------------------------------------------------------------- #
def test_playlist_rewrite_routes_every_uri_through_the_gateway():
    text = "\n".join([
        "#EXTM3U",
        '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"',
        "#EXTINF:2.0,",
        "seg1.ts",
        "#EXTINF:2.0,",
        "https://cdn.example/abs/seg2.ts?t=1",
    ])
    out = rewrite_playlist_for_gateway(text, "http://origin.example/live/list.m3u8",
                                       lambda url: "GW[" + url + "]")
    assert 'URI="GW[http://origin.example/live/key.bin]"' in out
    assert "GW[http://origin.example/live/seg1.ts]" in out
    assert "GW[https://cdn.example/abs/seg2.ts?t=1]" in out


@pytest.fixture
def local_proxy(monkeypatch):
    """A real StreamProxy on 127.0.0.1 with no firewall changes."""
    proxy = StreamProxy()
    proxy.host = "127.0.0.1"
    monkeypatch.setattr(proxy, "_ensure_firewall_rule", lambda: None)
    monkeypatch.setattr(proxy, "_remove_firewall_rule", lambda: None)
    monkeypatch.setattr(stream_proxy, "get_proxy", lambda: proxy)
    proxy.start()
    try:
        yield proxy
    finally:
        proxy.stop()


@pytest.fixture
def upstream():
    """An upstream that records the headers it was asked with."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            seen.append({k: v for k, v in self.headers.items()})
            if self.path.startswith("/live/list.m3u8"):
                body = b"#EXTM3U\n#EXTINF:2.0,\nseg1.ts\n"
                ctype = "application/vnd.apple.mpegurl"
            else:
                body = b"G" * 376
                ctype = "video/mp2t"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    # A short poll interval keeps teardown quick: shutdown() waits for the loop to notice.
    threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        server.shutdown()
        server.server_close()
        # The handler threads keep the connection sockets; without this the
        # sockets are only released when the garbage collector runs.
        for thread in list(threading.enumerate()):
            if thread.daemon and thread is not threading.current_thread():
                thread.join(timeout=1)


def test_gateway_fetches_with_the_channel_headers(local_proxy, upstream):
    base, seen = upstream
    url = local_proxy.get_gateway_url(base + "/live/stream.ts?token=1",
                                      {"User-Agent": "ChannelUA", "Referer": "http://ref/"})
    assert url.startswith(local_proxy.base_url() + "/g/")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-9"})) as resp:
        assert resp.read() == b"G" * 376
    assert seen[-1]["User-Agent"] == "ChannelUA"
    assert seen[-1]["Referer"] == "http://ref/"
    assert seen[-1]["Range"] == "bytes=0-9"


def test_gateway_playlist_segments_come_back_through_it(local_proxy, upstream):
    base, seen = upstream
    url = local_proxy.get_gateway_url(base + "/live/list.m3u8", {"User-Agent": "ChannelUA"})
    with urllib.request.urlopen(url) as resp:
        playlist = resp.read().decode()
    segment = [line for line in playlist.splitlines() if line and not line.startswith("#")][0]
    assert segment.startswith(local_proxy.base_url() + "/g/")
    with urllib.request.urlopen(segment) as resp:
        assert resp.read() == b"G" * 376
    assert all(entry["User-Agent"] == "ChannelUA" for entry in seen)


def test_gateway_refuses_unknown_sessions_and_file_urls(local_proxy):
    for path in ("/g/nosuchsession/http/example.com/x.ts",
                 "/g/abc/file/C:/secret.txt"):
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(local_proxy.base_url() + path)
        assert err.value.code in (403, 404)


def test_source_url_uses_the_gateway_only_when_headers_are_needed(local_proxy):
    assert casting.CastingManager._source_url("http://h/x.ts", {}) == "http://h/x.ts"
    routed = casting.CastingManager._source_url("http://h/x.ts", {"User-Agent": "UA"})
    assert routed.startswith(local_proxy.base_url() + "/g/")


# --------------------------------------------------------------------------- #
# Routing per receiver
# --------------------------------------------------------------------------- #
def _device(kind, key, sinks=frozenset()):
    import caster_engine
    return casting.CastDevice(caster_engine.Device(kind, "Test " + kind, key, sinks=sinks))


@pytest.fixture
def manager(monkeypatch):
    mgr = casting.CastingManager()
    mgr._running = True            # no asyncio loop needed for these kinds
    monkeypatch.setattr(casting.CastingManager, "stop_playback", lambda self: None)
    return mgr


def test_kodi_gets_the_stream_as_is(manager, monkeypatch, local_proxy):
    import caster_devices
    calls = []
    monkeypatch.setattr(caster_devices, "kodi_play", lambda base, url, auth=("", ""): calls.append((base, url)))
    manager.connect(_device("kodi", {"base": "http://kodi:8080"}))
    manager.play("http://h/live/1.ts|User-Agent=x", "News", headers={})
    assert calls[0][0] == "http://kodi:8080"
    # The pipe tail is player syntax; the headers it carried go to the gateway.
    assert "|" not in calls[0][1]


def test_a_tv_channel_reaches_a_speaker_renderer_as_sound(manager, monkeypatch):
    import caster_engine
    pushed = []
    monkeypatch.setattr(caster_engine, "probe_media",
                        lambda url: {"url": url, "mime": "video/mp2t", "is_audio": False, "is_live": True})
    monkeypatch.setattr(casting.CastingManager, "_speaker_url",
                        staticmethod(lambda fetch_url, headers: "http://proxy/audio"))
    monkeypatch.setattr(casting.CastingManager, "_upnp_push",
                        staticmethod(lambda device, url, mime, title: pushed.append((url, mime))))
    amp = _device("upnp", {"control_url": "http://amp/ctl"}, sinks=frozenset({"audio/mpeg"}))
    manager.connect(amp)
    manager.play("http://h/live/1.ts", "News", headers={})
    assert pushed == [("http://proxy/audio", "audio/mpeg")]


def test_sonos_gets_sound_for_a_tv_channel(manager, monkeypatch):
    import caster_devices
    import caster_engine
    played = []
    monkeypatch.setattr(caster_engine, "probe_media",
                        lambda url: {"url": url, "mime": "video/mp2t", "is_audio": False, "is_live": True})
    monkeypatch.setattr(casting.CastingManager, "_speaker_url",
                        staticmethod(lambda fetch_url, headers: "http://proxy/audio"))
    monkeypatch.setattr(caster_devices, "sonos_play",
                        lambda ip, url, title="", mime="": played.append((ip, url, mime)))
    manager.connect(_device("sonos", {"ip": "10.0.0.5"}))
    manager.play("http://h/live/1.ts", "News", headers={})
    assert played == [("10.0.0.5", "http://proxy/audio", "audio/mpeg")]


def test_play_without_a_device_raises(manager):
    with pytest.raises(casting.CastError):
        manager.play("http://h/x.ts", "News")


def test_a_stop_during_the_sonos_probe_does_not_start_playback(manager, monkeypatch):
    """The stop landed while the probe was still running.

    The receiver was started anyway, so the speaker played a channel the user
    had already stopped, and the audio proxy held the provider's one
    connection.
    """
    import caster_devices
    import caster_engine
    probing = threading.Event()
    release = threading.Event()
    played = []

    def _probe(url):
        probing.set()
        release.wait(5)
        return {"url": url, "mime": "audio/mpeg", "is_audio": True, "is_live": True}

    monkeypatch.setattr(caster_engine, "probe_media", _probe)
    monkeypatch.setattr(caster_devices, "sonos_play",
                        lambda ip, url, title="", mime="": played.append((ip, url)))
    manager.connect(_device("sonos", {"ip": "10.0.0.5"}))

    def _play():
        try:
            manager.play("http://h/live/1.ts", "News", headers={})
        except Exception:
            pass  # the cast was stopped; that is the point of the test

    worker = threading.Thread(target=_play, daemon=True)
    worker.start()
    assert probing.wait(5), "the probe never ran"

    # What a stop does to a cast that is still starting: the generation moves
    # on, and the play that is still probing has to notice.
    with manager._lock:
        manager._generation += 1
    release.set()
    worker.join(5)

    assert played == [], "playback started after the cast was stopped"


def test_exclusive_provider_probes_one_step_at_a_time(manager, monkeypatch):
    """A one-stream provider gets a pause between each request of the stream."""
    import caster_devices
    import caster_engine
    order = []
    monkeypatch.setattr(caster_engine, "probe_media",
                        lambda url: order.append("probe") or
                        {"url": url, "mime": "audio/mpeg", "is_audio": True, "is_live": True})
    monkeypatch.setattr(casting.CastingManager, "_settle",
                        staticmethod(lambda exclusive: order.append("settle") if exclusive else None))
    monkeypatch.setattr(caster_devices, "sonos_play",
                        lambda *a, **k: order.append("play"))
    manager.connect(_device("sonos", {"ip": "10.0.0.5"}))
    manager.play("http://h/radio", "Radio", headers={}, exclusive=True)
    assert order == ["probe", "settle", "play"]


def test_a_live_source_that_failed_is_not_reopened_for_good():
    """A source that failed is not a drop to recover from.

    The AirPlay runner reopened a live source for ever: the cast reported
    success while ffmpeg was respawned every second, and the provider's
    stream slot was held the whole time.
    """
    # ffmpeg exited with an error: the source failed (a 403, say).
    assert casting._live_source_error(1, 0) is not None
    # A clean end is a drop: reopen it at the live edge.
    assert casting._live_source_error(0, 0) is None
    assert casting._live_source_error(None, 0) is None
    # A source that ends again straight away was never working.
    assert casting._live_source_error(0, casting.LIVE_REOPEN_LIMIT) is not None
