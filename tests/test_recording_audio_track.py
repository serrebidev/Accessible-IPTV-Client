"""Recordings keep the audio track the user listens to.

An audio-only recording (MP3, WAV, FLAC, M4A, Opus) holds one track, and left
to itself ffmpeg kept the one with the most channels - not the one playing,
and not the audio description. The stream is now asked which tracks it has,
and the player's own rules pick one. Video recordings keep every track and
mark the chosen one as the default.
"""
import os
import re
import subprocess
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_tracks  # noqa: E402
import main  # noqa: E402
import recorder  # noqa: E402

# ffmpeg 8's report for a DVB stream: Polish, Polish audio description, English.
DVB_REPORT = """Input #0, mpegts, from 'ad_test.ts':
  Duration: 00:00:02.01, start: 1.400000, bitrate: 1295 kb/s
  Program 1
    Metadata:
      service_name    : Service01
      service_provider: FFmpeg
  Stream #0:0[0x100]: Video: h264 (Constrained Baseline) ([27][0][0][0] / 0x001B), yuv420p(progressive), 96x54 [SAR 1:1 DAR 16:9], 8 fps, 8 tbr, 90k tbn, start 1.410911
  Stream #0:1[0x101](pol): Audio: mp2 (mp3float) ([3][0][0][0] / 0x0003), 44100 Hz, mono, fltp, 384 kb/s, start 1.400000
  Stream #0:2[0x102](pol): Audio: mp2 (mp3float) ([3][0][0][0] / 0x0003), 44100 Hz, mono, fltp, 384 kb/s, start 1.400000 (visual impaired) (descriptions)
  Stream #0:3[0x103](eng): Audio: mp2 (mp3float) ([3][0][0][0] / 0x0003), 44100 Hz, stereo, fltp, 384 kb/s, start 1.400000
At least one output file must be specified
"""

# An HLS master with named audio renditions and no DVB flags.
HLS_REPORT = """Input #0, hls, from 'https://host/master.m3u8':
  Duration: N/A, start: 0.000000, bitrate: N/A
  Program 0
    Metadata:
      variant_bitrate : 3000000
  Stream #0:0: Video: h264 (High), yuv420p, 1280x720
    Metadata:
      variant_bitrate : 3000000
  Stream #0:1(pol): Audio: aac (LC), 48000 Hz, stereo, fltp
    Metadata:
      comment         : Polski
  Stream #0:2(pol): Audio: aac (LC), 48000 Hz, stereo, fltp
    Metadata:
      comment         : Polski - audiodeskrypcja
"""

AD_KEYWORDS = audio_tracks.preferred_audio_keywords(prefer_audio_description=True)


def _labels(report):
    return [recorder.audio_stream_label(i, s)
            for i, s in enumerate(recorder.parse_audio_streams(report))]


# ------------------------------------------------------------ probe report

class TestProbeReport:
    def test_audio_streams_come_out_in_map_order(self):
        streams = recorder.parse_audio_streams(DVB_REPORT)
        assert [s["language"] for s in streams] == ["pol", "pol", "eng"]
        assert streams[1]["dispositions"] == {"visual impaired", "descriptions"}
        # "(mp3float)" and "(Constrained Baseline)" are codec notes, not flags.
        assert streams[0]["dispositions"] == set()

    def test_a_flagged_track_is_labelled_audio_description(self):
        assert _labels(DVB_REPORT) == [
            "Track 1 - [pol]",
            "Track 2 - [pol] - audio description",
            "Track 3 - [eng]",
        ]

    def test_hls_rendition_names_are_kept(self):
        streams = recorder.parse_audio_streams(HLS_REPORT)
        assert [s["title"] for s in streams] == ["Polski", "Polski - audiodeskrypcja"]
        # Polish providers say "audiodeskrypcja"; that now counts as AD.
        assert audio_tracks.names_audio_description(_labels(HLS_REPORT)[1])
        assert not audio_tracks.names_audio_description(_labels(HLS_REPORT)[0])

    def test_nothing_readable_means_no_streams(self):
        assert recorder.parse_audio_streams("") == []
        assert recorder.parse_audio_streams("Connection refused") == []

    def test_http_options_go_only_to_http_streams(self, monkeypatch):
        # ffmpeg refuses "-user_agent" on any other input and then lists nothing.
        seen = []
        monkeypatch.setattr(recorder.subprocess, "run",
                            lambda cmd, **_k: seen.append(cmd) or types.SimpleNamespace(stderr=b""))
        recorder.probe_audio_streams("http://h/live.ts", {"user-agent": "Box/1.0"})
        recorder.probe_audio_streams("udp://@239.0.0.1:1234", {"user-agent": "Box/1.0"})
        assert "-user_agent" in seen[0]
        assert "-user_agent" not in seen[1]


# ------------------------------------------------------------ ffmpeg command

AUDIO_FORMATS = ["audio_wav", "audio_flac", "audio_mp3_v0", "audio_aac_m4a", "audio_opus"]


class TestFfmpegCommand:
    def test_mp3_keeps_the_chosen_track(self):
        cmd = recorder.build_ffmpeg_command("ffmpeg", "http://h/x", "out.mp3",
                                            "audio_mp3_v0", audio_track=1)
        assert cmd[cmd.index("-map") + 1] == "0:a:1"
        assert cmd.index("-i") < cmd.index("-map") < cmd.index("-vn")

    @pytest.mark.parametrize("fmt", AUDIO_FORMATS)
    def test_every_audio_only_format_honours_it(self, fmt):
        cmd = recorder.build_ffmpeg_command("ffmpeg", "http://h/x", "out", fmt, audio_track=2)
        assert "0:a:2" in cmd

    @pytest.mark.parametrize("fmt", AUDIO_FORMATS)
    def test_without_a_choice_ffmpeg_decides_as_before(self, fmt):
        cmd = recorder.build_ffmpeg_command("ffmpeg", "http://h/x", "out", fmt)
        assert "-map" not in cmd
        assert not any(arg.startswith("-disposition") for arg in cmd)

    @pytest.mark.parametrize("fmt", ["provider_mkv", "provider_mp4", "x264_mp4", "x264_mkv"])
    def test_video_formats_keep_every_track_and_default_the_chosen_one(self, fmt):
        cmd = recorder.build_ffmpeg_command("ffmpeg", "http://h/x", "out", fmt,
                                            audio_track=1, audio_track_count=3)
        pairs = [(arg, cmd[i + 1]) for i, arg in enumerate(cmd) if arg.startswith("-disposition:a:")]
        assert pairs == [("-disposition:a:0", "-default"),
                         ("-disposition:a:1", "+default"),
                         ("-disposition:a:2", "-default")]
        assert "0:a:1" not in cmd  # nothing is dropped from a video recording


def _ffmpeg():
    path = recorder.get_ffmpeg_path()
    try:
        subprocess.run([path, "-version"], check=True, capture_output=True, timeout=10)
    except Exception:
        return None
    return path


def test_real_ffmpeg_finds_and_records_the_described_track(tmp_path):
    """End to end: probe a DVB-style stream, pick AD, and record only that into MP3."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg is not available")
    source = tmp_path / "ad.ts"
    # The ordinary track lasts 1 s, the described one 3 s, so the MP3's length
    # says which one it holds.
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=500:duration=3",
        "-map", "0", "-map", "1",
        "-metadata:s:a:0", "language=pol", "-metadata:s:a:1", "language=pol",
        "-disposition:a:1", "visual_impaired",
        "-c:a", "mp2", "-f", "mpegts", str(source),
    ], check=True, timeout=60)

    streams = recorder.probe_audio_streams(str(source))
    labels = [recorder.audio_stream_label(i, s) for i, s in enumerate(streams)]
    index = audio_tracks.select_preferred_audio_track(
        list(enumerate(labels)), AD_KEYWORDS, prefer_ad=True)
    assert index == 1, labels

    out = tmp_path / "ad.mp3"
    cmd = recorder.build_ffmpeg_command(ffmpeg, str(source), str(out), "audio_mp3_v0",
                                        audio_track=index)
    # Only the output half: the reconnect options are for HTTP inputs.
    tail = cmd[cmd.index("-i") + 2:]
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)] + tail,
                   check=True, timeout=60)
    report = subprocess.run([ffmpeg, "-hide_banner", "-i", str(out)],
                            capture_output=True, timeout=30).stderr.decode("utf-8", "replace")
    hours, minutes, seconds = re.search(r"Duration: (\d+):(\d+):([\d.]+)", report).groups()
    assert float(seconds) > 2.5, "the MP3 holds the 1-second ordinary track"


# ------------------------------------------------------------ choosing in main

def _bind(client, *names):
    for name in names:
        setattr(client, name, main.IPTVClient.__dict__[name].__get__(client, main.IPTVClient))
    return client


def _intent_client(config=None, frame=None, audio_key=""):
    client = types.SimpleNamespace(
        config=config or {},
        _internal_player_frame=frame,
        _internal_player_audio_key=audio_key,
    )
    return _bind(client, "_recording_audio_intent", "_channel_audio_key",
                 "_remembered_channel_audio_track", "_remembered_channel_audio_track_index",
                 "_bool_pref", "_internal_player_has_media")


def _player(tracks, current_id):
    return types.SimpleNamespace(
        _destroyed=False, _current_url="http://h/live.ts", _last_resolved_url="http://h/live.ts",
        _wanted_audio_track_name=None,
        _get_audio_tracks=lambda: list(tracks),
        _current_audio_track_id=lambda: current_id,
    )


TVP = {"name": "TVP 1"}
PLAYER_TRACKS = [(101, "Track 1 - [Polish]"), (102, "Track 2 - [Polish] Audiodeskrypcja")]


class TestIntent:
    def test_the_track_playing_in_the_player_wins(self):
        client = _intent_client(frame=_player(PLAYER_TRACKS, 102), audio_key="tvp 1",
                                config={"prefer_audio_description": False})
        intent = client._recording_audio_intent(TVP)
        assert intent == {"keywords": ["audio description", PLAYER_TRACKS[1][1]],
                          "fallback_index": 1, "prefer_ad": True}

    def test_an_ordinary_track_in_the_player_is_kept_too(self):
        # Even with the audio-description preference on: the user switched away.
        client = _intent_client(frame=_player(PLAYER_TRACKS, 101), audio_key="tvp 1",
                                config={"prefer_audio_description": True})
        intent = client._recording_audio_intent(TVP)
        assert intent == {"keywords": [PLAYER_TRACKS[0][1]], "fallback_index": 0,
                          "prefer_ad": False}

    def test_another_channel_in_the_player_is_not_used(self):
        client = _intent_client(frame=_player(PLAYER_TRACKS, 102), audio_key="polsat",
                                config={})
        assert client._recording_audio_intent(TVP) is None

    def test_off_the_ui_thread_the_player_is_left_alone(self):
        frame = _player(PLAYER_TRACKS, 102)
        frame._get_audio_tracks = lambda: pytest.fail("touched the player off the UI thread")
        client = _intent_client(frame=frame, audio_key="tvp 1",
                                config={"prefer_audio_description": True})
        intent = client._recording_audio_intent(TVP, from_player=False)
        assert intent["prefer_ad"] is True

    def test_the_audio_description_preference_applies_without_the_player(self):
        client = _intent_client(config={"prefer_audio_description": True})
        intent = client._recording_audio_intent(TVP)
        assert intent["keywords"][:2] == ["audio description", "audiodescription"]
        assert intent["prefer_ad"] is True

    def test_the_channels_remembered_track_comes_first(self):
        client = _intent_client(config={
            "prefer_audio_description": True,
            "channel_audio_tracks": {"tvp 1": "Track 1 - [Polish]"},
            "channel_audio_track_indices": {"tvp 1": 0},
        })
        intent = client._recording_audio_intent(TVP)
        assert intent["keywords"][0] == "Track 1 - [Polish]"
        assert intent["fallback_index"] == 0

    def test_no_preference_at_all_leaves_ffmpeg_to_choose(self):
        assert _intent_client(config={})._recording_audio_intent(TVP) is None


class TestChoice:
    @staticmethod
    def _choose(monkeypatch, intent, report=DVB_REPORT, seen=None):
        def fake_probe(url, headers=None, **_kwargs):
            if seen is not None:
                seen.append((url, dict(headers or {})))
            return recorder.parse_audio_streams(report)

        monkeypatch.setattr(main, "probe_audio_streams", fake_probe)
        return main.IPTVClient._recording_audio_choice("http://h/live.ts", {}, intent)

    def test_audio_description_is_found_by_its_flag(self, monkeypatch):
        intent = {"keywords": AD_KEYWORDS, "fallback_index": None, "prefer_ad": True}
        assert self._choose(monkeypatch, intent) == (1, 3)

    def test_the_players_position_carries_over(self, monkeypatch):
        # libVLC's name for the track never matches ffmpeg's; its slot does.
        intent = {"keywords": ["Track 1 - [Polish]"], "fallback_index": 2, "prefer_ad": False}
        assert self._choose(monkeypatch, intent) == (2, 3)

    def test_the_players_described_track_is_found_even_out_of_position(self, monkeypatch):
        intent = {"keywords": ["audio description", "Track 3 - [Polish] AD"],
                  "fallback_index": 2, "prefer_ad": True}
        assert self._choose(monkeypatch, intent) == (1, 3)

    def test_an_hls_rendition_named_audiodeskrypcja_is_found(self, monkeypatch):
        intent = {"keywords": AD_KEYWORDS, "fallback_index": None, "prefer_ad": True}
        assert self._choose(monkeypatch, intent, report=HLS_REPORT) == (1, 2)

    def test_a_stream_that_cannot_be_asked_keeps_the_old_behaviour(self, monkeypatch):
        intent = {"keywords": AD_KEYWORDS, "fallback_index": None, "prefer_ad": True}
        assert self._choose(monkeypatch, intent, report="") is None

    def test_no_intent_means_no_probe(self, monkeypatch):
        monkeypatch.setattr(main, "probe_audio_streams",
                            lambda *a, **k: pytest.fail("probed without a reason"))
        assert main.IPTVClient._recording_audio_choice("http://h/x", {}, None) is None

    def test_the_probe_never_sees_the_m3u_pipe_tail(self, monkeypatch):
        seen = []
        monkeypatch.setattr(main, "probe_audio_streams",
                            lambda url, headers=None, **_k: seen.append((url, dict(headers or {}))) or [])
        main.IPTVClient._recording_audio_choice(
            "http://h/live.ts|User-Agent=Box/1.0", {}, {"keywords": ["x"]})
        (url, headers), = seen
        assert url == "http://h/live.ts"
        assert "Box/1.0" in headers.values()


# ------------------------------------------------------------ recording paths

class _Recorder:
    def __init__(self):
        self.started = []

    def is_recording(self, _key):
        return False

    def start(self, *args, **kwargs):
        self.started.append((args, kwargs))
        return types.SimpleNamespace(out_path="C:/rec/x.mp3", id=1)


def _live_client(monkeypatch, choice, deferred):
    class DeferredThread:
        def __init__(self, target=None, daemon=None, **_kwargs):
            self.target = target

        def start(self):
            deferred.append(self.target)

    monkeypatch.setattr(main.threading, "Thread", DeferredThread)
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(main, "get_recordings_dir", lambda _config: "C:/rec")
    boxes = []
    monkeypatch.setattr(main, "message_box", lambda msg, *a, **k: boxes.append(msg))
    client = types.SimpleNamespace(
        config={"recording_format": "audio_mp3_v0"},
        recorder=_Recorder(),
        boxes=boxes,
        _channel_record_key=lambda _channel: "rec:tvp1",
        _resolve_live_url=lambda _channel: "http://h/live.ts",
        _channel_display_name=lambda _channel: "TVP 1",
        _recording_audio_intent=lambda _channel, **_k: {"keywords": ["x"]},
        _recording_audio_choice=lambda url, headers, intent: choice,
        _note_recording_started=lambda: None,
        _recording_format_label=lambda fmt: fmt,
        _on_recording_finished=lambda *a: None,
        _sync_internal_player_record_state=lambda: None,
    )
    return _bind(client, "_record_channel", "_start_live_recording")


def test_live_recording_keeps_the_chosen_track(monkeypatch):
    deferred = []
    client = _live_client(monkeypatch, (1, 3), deferred)
    client._record_channel(TVP)
    assert client.recorder.started == []  # the stream is still being asked
    deferred.pop()()
    (_args, kwargs), = client.recorder.started
    assert (kwargs["audio_track"], kwargs["audio_track_count"]) == (1, 3)


def test_pressing_record_again_during_the_probe_cancels_it(monkeypatch):
    deferred = []
    client = _live_client(monkeypatch, (1, 3), deferred)
    client._record_channel(TVP)
    client._record_channel(TVP)
    assert any("Stopping recording" in box for box in client.boxes)
    deferred.pop()()
    assert client.recorder.started == []


def test_scheduled_recording_keeps_the_chosen_track(monkeypatch):
    monkeypatch.setattr(main, "get_recordings_dir", lambda _config: "C:/rec")
    monkeypatch.setattr(main.wx, "CallAfter", lambda *a, **k: None)
    asked = []
    client = types.SimpleNamespace(
        config={},
        recorder=_Recorder(),
        _resolve_live_url=lambda _channel: "http://h/live.ts",
        _channel_display_name=lambda _channel: "TVP 1",
        _recording_audio_intent=lambda channel, **k: asked.append(k) or {"keywords": ["x"]},
        _recording_audio_choice=lambda url, headers, intent: (2, 3),
        _note_recording_started=lambda: None,
        _on_recording_finished=lambda *a: None,
    )
    main.IPTVClient._start_scheduled_recording(
        client, {"id": "j1", "title": "News", "format": "audio_mp3_v0", "channel": dict(TVP)})
    assert asked == [{"from_player": False}]
    (_args, kwargs), = client.recorder.started
    assert (kwargs["audio_track"], kwargs["audio_track_count"]) == (2, 3)


def test_catchup_download_probes_the_url_it_will_record(monkeypatch):
    monkeypatch.setattr(main.catchup_direct, "direct_download_url",
                        lambda *a, **k: "http://h/direct.ts")
    handed = []
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: handed.append(a))
    probed = []
    client = types.SimpleNamespace(
        _recording_audio_choice=lambda url, headers, intent: probed.append(url) or (1, 3),
        _start_catchup_recording=lambda *a: None,
    )
    _bind(client, "_begin_catchup_download", "_parse_epg_time")
    intent = {"keywords": AD_KEYWORDS, "fallback_index": None, "prefer_ad": True}
    client._begin_catchup_download(TVP, "http://h/archive.m3u8", "Show - TVP 1", "catchup:x",
                                   {"start": "20260910183000", "end": "20260910192500"},
                                   3300.0, "audio_mp3_v0", audio_intent=intent)
    assert probed == ["http://h/direct.ts"]
    args, = handed
    assert args[-2:] == (intent, (1, 3))


def test_a_catchup_retry_keeps_the_same_track_rule(monkeypatch):
    client = main.IPTVClient.__new__(main.IPTVClient)
    client._catchup_retry_state = {9: 0}
    client._catchup_retry_timers = {}
    intent = {"keywords": AD_KEYWORDS, "fallback_index": None, "prefer_ad": True}
    rec = types.SimpleNamespace(
        id=9, key="catchup:abc", url="http://old/direct.ts", title="TVP 1: News",
        stopped_by_user=False, stderr_tail=["[error] Server returned 403 Forbidden"],
        metadata={"hls_url": "http://hls/index.m3u8", "audio_intent": intent})
    scheduled = []
    monkeypatch.setattr(main, "_schedule_retry", lambda fn, delay: scheduled.append(fn) or None)
    assert main.IPTVClient._maybe_retry_catchup_download(
        client, rec, rc=1, channel=dict(TVP),
        show={"start": "20260910183000", "end": "20260910192500"},
        duration=3300.0, fmt="audio_mp3_v0")
    calls = []
    monkeypatch.setattr(client, "_begin_catchup_download",
                        lambda *a, **k: calls.append(k))
    scheduled[0]()
    assert calls[0]["audio_intent"] == intent
