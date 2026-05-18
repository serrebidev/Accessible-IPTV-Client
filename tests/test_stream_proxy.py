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
    hls_playlist_is_ready,
    hls_playlist_stats,
    normalize_request_headers,
    rewrite_hls_playlist,
)


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
