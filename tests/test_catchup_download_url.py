"""The catch-up downloader must fetch, not play, the URL it is given.

An M3U stream URL can carry a ``|Key=Value`` tail (``|User-Agent=Mozilla...``)
and ``_build_generic_catchup_url`` re-attaches it to every template-style
catch-up URL, because players are the usual consumer and they understand it.
HTTP does not: the pipe lands in the query string, so the ``index-<utc>-
<duration>.mp4`` probe never matches and the download quietly falls back to the
HLS playlist -- which arrives at playback speed instead of line speed. That is
the whole point of the direct file, so the tail has to be stripped and its
headers carried over instead.
"""

import calendar
import os
import sys
import time
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import catchup_direct  # noqa: E402
import http_headers  # noqa: E402
import main  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
LIVE = "http://tv.example.invalid/live/chan1/index.m3u8"
CATCHUP = LIVE + "?utc=1757000000&lutc=1757003600|User-Agent=" + UA.replace(" ", "%20")


class TestSplitStreamModifiers:
    def test_a_plain_url_is_returned_untouched(self):
        assert http_headers.split_stream_modifiers(LIVE) == (LIVE, {})

    def test_the_pipe_tail_becomes_headers(self):
        url, headers = http_headers.split_stream_modifiers(
            LIVE + "|User-Agent=" + UA.replace(" ", "%20") + "|Referer=http://x.invalid/")
        assert url == LIVE
        assert headers["user-agent"] == UA
        assert headers["referer"] == "http://x.invalid/"

    def test_aliases_and_unknown_names(self):
        _url, headers = http_headers.split_stream_modifiers(
            LIVE + "|ua=curl|token=abc123|x-custom=hello")
        assert headers["user-agent"] == "curl"
        assert headers["authorization"] == "Bearer abc123"
        assert headers["_extra"] == ["X-Custom: hello"]

    def test_empty_and_malformed_tails_are_ignored(self):
        assert http_headers.split_stream_modifiers("") == ("", {})
        _url, headers = http_headers.split_stream_modifiers(LIVE + "|garbage|Referer=")
        assert headers == {}


class TestMergeHeaders:
    def test_the_channel_wins_and_the_url_fills_gaps(self):
        merged = http_headers.merge_headers(
            {"user-agent": "channel-ua"}, {"user-agent": "url-ua", "referer": "r"})
        assert merged == {"user-agent": "channel-ua", "referer": "r"}

    def test_extra_header_lines_are_concatenated_and_deduped(self):
        merged = http_headers.merge_headers(
            {"_extra": ["X-A: 1"]}, {"_extra": ["X-A: 2", "X-B: 3"]})
        assert merged["_extra"] == ["X-A: 1", "X-B: 3"]


class TestDirectUrlCandidates:
    def test_the_community_script_url_is_among_the_candidates(self):
        """The teleelevidenie download script resolves the redirect, then asks
        for ``<scheme>//<host>/<first path segment>/index-<utc>-<len>.mp4?<query>``."""
        resolved = "https://cdn.example.invalid/chan_hls/index.m3u8?token=abc"
        candidates = catchup_direct.candidate_direct_urls(resolved, 1757000000, 3600)
        assert ("https://cdn.example.invalid/chan_hls/"
                "index-1757000000-3600.mp4?token=abc") in candidates

    def test_a_pipe_tail_would_poison_every_candidate(self):
        """Why the tail has to go before the probe: it rides along in the query."""
        poisoned = catchup_direct.candidate_direct_urls(CATCHUP, 1757000000, 3600)
        assert all("User-Agent" in c for c in poisoned)
        clean_url, _headers = http_headers.split_stream_modifiers(CATCHUP)
        clean = catchup_direct.candidate_direct_urls(clean_url, 1757000000, 3600)
        assert clean and not any("User-Agent" in c for c in clean)


class TestBeginCatchupDownload:
    @staticmethod
    def _client(monkeypatch, probed, started, direct=None):
        client = types.SimpleNamespace()
        client._parse_epg_time = types.MethodType(main.IPTVClient._parse_epg_time, client)
        client._begin_catchup_download = types.MethodType(
            main.IPTVClient._begin_catchup_download, client)
        client._start_catchup_recording = lambda *a, **k: None

        def fake_direct(url, start_epoch, duration, headers=None, timeout=6.0):
            probed.append((url, start_epoch, duration, dict(headers or {})))
            return direct

        monkeypatch.setattr(main.catchup_direct, "direct_download_url", fake_direct)
        monkeypatch.setattr(main.wx, "CallAfter",
                            lambda fn, *a, **k: started.append((a, k)))
        return client

    @staticmethod
    def _channel():
        return {"name": "Chan 1", "url": LIVE, "http-user-agent": UA}

    SHOW = {"start": "20260904180000", "end": "20260904190000"}

    def test_the_probe_never_sees_the_pipe_tail(self, monkeypatch):
        probed, started = [], []
        client = self._client(monkeypatch, probed, started)

        client._begin_catchup_download(
            self._channel(), CATCHUP, "Show - Chan 1", "catchup:x",
            self.SHOW, 3600.0, "provider_mp4")

        (url, start_epoch, duration, headers), = probed
        assert "|" not in url
        assert url.endswith("?utc=1757000000&lutc=1757003600")
        assert duration == 3600
        # The window comes from the EPG entry, not from whatever the URL says.
        assert start_epoch == calendar.timegm(
            time.strptime(self.SHOW["start"], "%Y%m%d%H%M%S"))
        # The user agent survives as a real header instead of query junk.
        assert headers["user-agent"] == UA

    def test_the_recorder_gets_the_stripped_url_when_no_direct_file_exists(self, monkeypatch):
        probed, started = [], []
        client = self._client(monkeypatch, probed, started, direct=None)

        client._begin_catchup_download(
            self._channel(), CATCHUP, "Show - Chan 1", "catchup:x",
            self.SHOW, 3600.0, "provider_mp4")

        (args, _kwargs), = started
        assert "|" not in args[0], "ffmpeg would request the pipe as part of the query"

    def test_a_direct_file_is_preferred_over_the_playlist(self, monkeypatch):
        fast = "http://tv.example.invalid/live/index-1757000000-3600.mp4?x=1"
        probed, started = [], []
        client = self._client(monkeypatch, probed, started, direct=fast)

        client._begin_catchup_download(
            self._channel(), CATCHUP, "Show - Chan 1", "catchup:x",
            self.SHOW, 3600.0, "provider_mp4")

        (args, _kwargs), = started
        assert args[0] == fast


class TestFfmpegExitReason:
    def test_the_reported_code_is_http_403(self):
        """Windows showed ffmpeg's AVERROR_HTTP_FORBIDDEN as 3436169992."""
        reason = main._ffmpeg_exit_reason(3436169992)
        assert "403" in reason
        assert reason == main._ffmpeg_exit_reason(-858797304)

    def test_other_http_errors_have_words(self):
        assert "404" in main._ffmpeg_exit_reason(main._ffmpeg_error_tag(0xF8, "4", "0", "4"))
        assert "5xx" in main._ffmpeg_exit_reason(main._ffmpeg_error_tag(0xF8, "5", "X", "X"))

    def test_unknown_codes_say_nothing(self):
        assert main._ffmpeg_exit_reason(1) == ""
        assert main._ffmpeg_exit_reason(None) == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
