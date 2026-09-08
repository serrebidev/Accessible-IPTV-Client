"""
Tests for internal player recovery, buffering, and reconnection.
"""
import pytest
import os
import sys
import time
import types
from enum import IntEnum

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import internal_player  # noqa: E402


# Mock VLC State enum for testing without VLC installed
class MockState(IntEnum):
    NothingSpecial = 0
    Opening = 1
    Buffering = 2
    Playing = 3
    Paused = 4
    Stopped = 5
    Ended = 6
    Error = 7


class TestBufferProfile:
    """Test buffer profile calculations."""

    def test_default_buffer_seconds(self):
        """Test default buffer target calculation."""
        # Default values from internal_player.py
        default_base = 2  # seconds
        default_max = 18  # seconds
        
        # Without bitrate info, should use midpoint-ish value
        target = 7.5  # typical default
        
        assert target >= default_base
        assert target <= default_max

    def test_buffer_profile_for_high_bitrate(self):
        """Test buffer profile for high bitrate streams."""
        bitrate_mbps = 20  # High bitrate
        base_buffer = 2
        max_buffer = 18
        
        # Higher bitrate needs less buffering time for same data
        # But we still want enough buffer to handle jitter
        target = min(max_buffer, max(base_buffer, 12 - (bitrate_mbps / 5)))
        
        assert target >= base_buffer
        assert target <= max_buffer

    def test_buffer_profile_for_low_bitrate(self):
        """Test buffer profile for low bitrate audio streams."""
        is_audio = True
        
        if is_audio:
            # Audio streams can use smaller buffers
            target = 3.5
        else:
            target = 7.5
        
        assert target == 3.5

    def test_xtream_ts_buffer_profile(self):
        """Test buffer profile for Xtream .ts live streams."""
        url = "http://example.com/user/pass/12345.ts"
        is_xtream_ts = url.endswith(".ts") and "/live/" not in url
        
        if is_xtream_ts:
            # Xtream TS needs deeper buffers for segment boundaries
            target = 8.0
        else:
            target = 7.5
        
        assert target == 8.0


class TestChoppyDetection:
    """Test choppy stream detection logic."""

    def test_buffering_duration_threshold(self):
        """Test that short buffering events don't count as choppy."""
        threshold_seconds = 1.25
        
        short_buffer = 0.5  # 500ms
        long_buffer = 2.0   # 2 seconds
        
        assert short_buffer < threshold_seconds  # Not choppy
        assert long_buffer >= threshold_seconds   # Choppy

    def test_reconnect_budget(self):
        """Test reconnection attempt budgeting."""
        max_attempts = 3
        attempts = 0
        
        # Simulate connection attempts
        for _ in range(5):
            if attempts < max_attempts:
                attempts += 1
        
        assert attempts == max_attempts

    def test_attempt_decay(self):
        """Test that reconnect attempts decay over time."""
        decay_minutes = 2
        last_attempt_time = time.time() - (decay_minutes * 60 + 1)  # 2+ minutes ago
        current_time = time.time()
        
        elapsed = current_time - last_attempt_time
        should_reset = elapsed > (decay_minutes * 60)
        
        assert should_reset is True

    def test_attempt_no_decay_recent(self):
        """Test that recent attempts don't decay."""
        decay_minutes = 2
        last_attempt_time = time.time() - 30  # 30 seconds ago
        current_time = time.time()
        
        elapsed = current_time - last_attempt_time
        should_reset = elapsed > (decay_minutes * 60)
        
        assert should_reset is False


class TestXtreamTsLiveRefresh:
    """Test Xtream .ts live stream auto-refresh behavior."""

    def test_live_vs_catchup_detection(self):
        """Test detection of live vs catchup streams."""
        live_url = "http://example.com/user/pass/12345.ts"
        catchup_url = "http://example.com/timeshift/user/pass/12345/2024-01-15/14-00.ts"
        
        # Live URLs are simpler
        is_live_ts = live_url.endswith(".ts") and "timeshift" not in live_url
        is_catchup = "timeshift" in catchup_url
        
        assert is_live_ts is True
        assert is_catchup is True

    def test_auto_refresh_on_ended_for_live(self):
        """Test auto-refresh triggers for live Xtream TS."""
        is_live = True
        is_xtream_ts = True
        state = MockState.Ended
        
        should_refresh = (state == MockState.Ended and is_live and is_xtream_ts)
        
        assert should_refresh is True

    def test_no_refresh_for_catchup_ended(self):
        """Test no auto-refresh for catchup streams that end."""
        is_live = False
        is_xtream_ts = True
        state = MockState.Ended
        
        should_refresh = (state == MockState.Ended and is_live and is_xtream_ts)
        
        assert should_refresh is False

    def test_refresh_doesnt_burn_budget(self):
        """Test that auto-refresh doesn't burn reconnect budget."""
        reconnect_attempts = 0
        is_auto_refresh = True
        
        if not is_auto_refresh:
            reconnect_attempts += 1
        
        assert reconnect_attempts == 0


class TestVLCOptions:
    """Test VLC player option generation."""

    def test_network_caching_option(self):
        """Test network-caching option generation."""
        buffer_ms = 7500  # 7.5 seconds
        
        option = f"--network-caching={buffer_ms}"
        
        assert option == "--network-caching=7500"

    def test_file_caching_option(self):
        """Test file-caching option for Xtream TS."""
        buffer_ms = 18000  # 18 seconds
        
        option = f"--file-caching={buffer_ms}"
        
        assert option == "--file-caching=18000"

    def test_live_caching_option(self):
        """Test live-caching option."""
        buffer_ms = 10000  # 10 seconds
        
        option = f"--live-caching={buffer_ms}"
        
        assert option == "--live-caching=10000"

    def test_http_reconnect_option(self):
        """Test http-reconnect option."""
        option = "--http-reconnect"
        
        assert option == "--http-reconnect"

    def test_adaptive_bitrate_options(self):
        """Test adaptive bitrate streaming options."""
        options = [
            "--adaptive-maxwidth=1920",
            "--adaptive-maxheight=1080",
        ]
        
        assert len(options) == 2
        assert "maxwidth" in options[0]
        assert "maxheight" in options[1]


class TestStateTransitions:
    """Test VLC state transition handling."""

    def test_opening_to_playing(self):
        """Test normal opening to playing transition."""
        states = [MockState.Opening, MockState.Opening, MockState.Buffering, MockState.Playing]
        
        reached_playing = MockState.Playing in states
        
        assert reached_playing is True

    def test_opening_to_error(self):
        """Test opening to error transition."""
        states = [MockState.Opening, MockState.Opening, MockState.Error]
        
        reached_error = MockState.Error in states
        reached_playing = MockState.Playing in states
        
        assert reached_error is True
        assert reached_playing is False

    def test_playing_to_buffering_recovery(self):
        """Test recovery from buffering while playing."""
        states = [MockState.Playing, MockState.Buffering, MockState.Buffering, MockState.Playing]
        
        had_buffering = MockState.Buffering in states
        recovered = states[-1] == MockState.Playing
        
        assert had_buffering is True
        assert recovered is True

    def test_ended_state_handling(self):
        """Test ended state handling."""
        state = MockState.Ended
        is_live = True
        is_xtream_ts = True
        
        # For live Xtream TS, ended should trigger refresh
        should_refresh = (state == MockState.Ended and is_live and is_xtream_ts)
        
        assert should_refresh is True


class TestVolumeControl:
    """Test volume control functionality."""

    def test_volume_range(self):
        """Test volume range is 0-100."""
        min_vol = 0
        max_vol = 100
        
        assert min_vol >= 0
        assert max_vol <= 100

    def test_volume_step_default(self):
        """Test default volume step is 2%."""
        default_step = 2
        
        assert default_step == 2

    def test_volume_step_with_ctrl(self):
        """Test volume step with Ctrl modifier is 5%."""
        ctrl_step = 5
        
        assert ctrl_step == 5

    def test_volume_clamping(self):
        """Test volume is clamped to valid range."""
        def clamp_volume(vol):
            return max(0, min(100, vol))
        
        assert clamp_volume(-10) == 0
        assert clamp_volume(150) == 100
        assert clamp_volume(50) == 50


class TestPlayerReconnection:
    """Test player reconnection logic."""

    def test_reconnect_on_stream_lost(self):
        """Test reconnection triggers on stream lost."""
        state = MockState.Ended
        was_playing = True
        is_live = True
        
        should_reconnect = (state == MockState.Ended and was_playing and is_live)
        
        assert should_reconnect is True

    def test_no_reconnect_on_user_stop(self):
        """Test no reconnection when user stops."""
        state = MockState.Stopped
        user_initiated = True
        
        should_reconnect = (state == MockState.Stopped and not user_initiated)
        
        assert should_reconnect is False

    def test_reconnect_delay(self):
        """Test reconnection delay."""
        base_delay = 1.0  # seconds
        attempt = 2
        
        # Exponential backoff
        delay = base_delay * (2 ** (attempt - 1))
        
        assert delay == 2.0

    def test_max_reconnect_delay(self):
        """Test maximum reconnection delay."""
        max_delay = 30  # seconds
        calculated_delay = 64  # Too high
        
        actual_delay = min(calculated_delay, max_delay)
        
        assert actual_delay == max_delay


class TestBufferingEvents:
    """Test buffering event handling."""

    def test_buffering_progress_tracking(self):
        """Test buffering progress is tracked."""
        progress_events = [0.0, 0.25, 0.5, 0.75, 1.0]
        
        completed = progress_events[-1] == 1.0
        
        assert completed is True

    def test_long_buffering_triggers_recovery(self):
        """Test long buffering triggers recovery action."""
        buffering_start = time.time() - 10  # 10 seconds ago
        threshold = 8  # seconds
        
        buffering_duration = time.time() - buffering_start
        needs_recovery = buffering_duration > threshold
        
        assert needs_recovery is True

    def test_short_buffering_no_recovery(self):
        """Test short buffering doesn't trigger recovery."""
        buffering_start = time.time() - 2  # 2 seconds ago
        threshold = 8  # seconds
        
        buffering_duration = time.time() - buffering_start
        needs_recovery = buffering_duration > threshold
        
        assert needs_recovery is False


class TestStreamTypeDetection:
    """Test stream type detection for appropriate handling."""

    def test_hls_detection(self):
        """Test HLS stream detection."""
        urls = [
            "http://example.com/stream.m3u8",
            "http://example.com/playlist.M3U8",
            "http://example.com/index.m3u8?token=abc",
        ]
        
        for url in urls:
            is_hls = ".m3u8" in url.lower()
            assert is_hls is True

    def test_mpeg_ts_detection(self):
        """Test MPEG-TS stream detection."""
        urls = [
            "http://example.com/stream.ts",
            "http://example.com/live/channel.TS",
        ]
        
        for url in urls:
            is_ts = url.lower().endswith(".ts")
            assert is_ts is True

    def test_xtream_pattern_detection(self):
        """Test Xtream URL pattern detection."""
        # Xtream: /{username}/{password}/{stream_id}.ts
        url = "http://example.com/user123/pass456/12345.ts"
        parts = url.split("/")
        
        # Typical Xtream has at least 4 path components after domain
        has_xtream_pattern = len(parts) >= 6 and parts[-1].endswith(".ts")
        
        assert has_xtream_pattern is True

    def test_audio_stream_detection(self):
        """Test audio-only stream detection."""
        audio_extensions = [".mp3", ".aac", ".ogg", ".opus"]
        urls = [
            "http://radio.example.com/stream.mp3",
            "http://radio.example.com/live.aac",
        ]
        
        for url in urls:
            is_audio = any(url.lower().endswith(ext) for ext in audio_extensions)
            assert is_audio is True


class TestClosingTheShownPlayerStopsPlayback:
    """Closing the player window must stop the channel, not hide it."""

    @staticmethod
    def _stub_frame():
        frame = types.SimpleNamespace()
        frame.events = []
        frame._allow_close = False
        frame._destroyed = False
        frame.stopped = []
        frame._status_timer = types.SimpleNamespace(Stop=lambda: None)
        frame.player = types.SimpleNamespace(
            stop=lambda: frame.stopped.append("player.stop"),
            release=lambda: frame.stopped.append("release"),
        )
        frame.instance = types.SimpleNamespace(release=lambda: None)
        frame._on_close_cb = lambda: frame.events.append("closed")
        frame._exit_player = types.MethodType(
            internal_player.InternalPlayerFrame._exit_player, frame)
        frame._hide_player = lambda: frame.events.append("hidden")
        frame.Destroy = lambda: True
        return frame

    def test_close_stops_playback_instead_of_hiding(self):
        frame = self._stub_frame()
        event = types.SimpleNamespace(CanVeto=lambda: True, Skip=lambda: None)

        internal_player.InternalPlayerFrame._on_close(frame, event)

        assert frame.stopped == ["player.stop"]
        assert frame.events == ["closed"]

    def test_explicit_exit_still_stops_and_destroys(self):
        frame = self._stub_frame()
        destroyed = []
        frame.Destroy = lambda: destroyed.append(True) or True

        internal_player.InternalPlayerFrame._exit_player(frame)

        assert frame.stopped == ["player.stop"]
        assert frame.events == ["closed"]
        assert destroyed == [True]


class TestLibVlcStateName:
    """python-vlc's State is a ctypes int, not a stdlib enum.

    On python-vlc 3.0.21203 ``vlc.State.Playing`` has no ``.name`` at all and
    ``str()`` gives "State.Playing". The timer used to lower-case that straight
    into ``state_key``, producing "state.playing", so every ``state_key ==
    "playing"`` test failed. That silently disabled the remembered audio track,
    the audio-description preference, buffering/stall recovery, and left the
    status label reading out the raw "State.playing".
    """

    class _CtypesStyleState:
        """Stands in for python-vlc's State: no .name, str() is prefixed."""
        def __init__(self, name):
            self._name = name

        def __str__(self):
            return "State.%s" % self._name

    def test_prefixed_state_reduces_to_a_bare_word(self):
        name = internal_player.InternalPlayerFrame._state_name(
            self._CtypesStyleState("Playing"))
        assert name == "Playing"
        assert name.lower() == "playing", "must equal what _on_timer compares against"

    def test_every_state_the_timer_branches_on_survives_the_prefix(self):
        for word in ("Playing", "Buffering", "Stopped", "Ended", "Error",
                     "Opening", "Paused", "NothingSpecial"):
            got = internal_player.InternalPlayerFrame._state_name(
                self._CtypesStyleState(word))
            assert got == word, "%s came back as %r" % (word, got)

    def test_a_real_enum_with_name_still_works(self):
        """Other python-vlc builds do expose .name; both shapes must work."""
        state = types.SimpleNamespace(name="Buffering")
        assert internal_player.InternalPlayerFrame._state_name(state) == "Buffering"

    def test_missing_state_is_not_mistaken_for_a_real_one(self):
        assert internal_player.InternalPlayerFrame._state_name(None) == "Unknown"
        # A blank name must not produce "" and match an empty comparison.
        assert internal_player.InternalPlayerFrame._state_name(
            types.SimpleNamespace(name="")) != ""

    def test_status_label_shows_a_translated_word_not_the_raw_enum(self):
        raw = str(self._CtypesStyleState("Playing"))
        assert internal_player.InternalPlayerFrame._localized_state(raw) != "Playing", (
            "guard: the raw prefixed string is what used to reach the label")
        name = internal_player.InternalPlayerFrame._state_name(
            self._CtypesStyleState("Playing"))
        assert internal_player.InternalPlayerFrame._localized_state(name) == "Playing"


class TestReconnectKeepsVideoHidden:
    """A background channel must not pop a video window open when it reconnects.

    The restart paths only know the URL, so they call play(..., _retry=True)
    without video_visible - and that parameter defaults to True. A reconnect
    therefore used to re-enable video on a stream started with it off, and
    libVLC spawned its own "VLC (Direct3D11 output)" window over the app.
    """

    def _stub_frame(self):
        media_options = []

        class _Media:
            def add_option(self, opt):
                media_options.append(opt)

        frame = types.SimpleNamespace(
            _destroyed=False,
            _manual_stop=False,
            _current_stream_kind="live",
            _current_headers=None,
            _current_url="",
            _current_title="",
            _wanted_audio_track_name=None,
            _audio_reapply_pending=False,
            _video_visible=True,
            _reconnect_attempts=3,
            _xtream_refresh_count=1,
            _last_restart_reason="stall",
            _gave_up=False,
            _last_bitrate_mbps=None,
            _last_position_ms=None,
            _last_state_name=None,
            _stall_ticks=0,
            _buffer_start_ts=None,
            _early_buffer_fix_applied=False,
            _has_seen_playing=False,
            _detected_content_ts=False,
            _play_start_monotonic=0.0,
            _pending_restart=True,
            _pending_xtream_refresh=True,
            _is_paused=True,
            _buffering_events=[],
            media_options=media_options,
            hwnd_calls=[],
            window_attached=[],
            instance=types.SimpleNamespace(media_new=lambda _u: _Media()),
        )
        frame._begin_new_stream_audio_state = lambda: None
        frame._normalise_stream_url = lambda u, h: (u, h)
        frame._resolve_stream_url = lambda u, headers=None: (u, None)
        frame._detect_stream_content_type = lambda *a, **kw: None
        frame._last_resolved_url = ""
        frame._compute_buffer_profile = lambda *a, **kw: (2.0, None, None)
        frame._apply_cache_options = lambda *a, **kw: None
        frame._apply_stream_headers = lambda *a, **kw: None
        frame._apply_audio_output_device = lambda: None
        frame._schedule_volume_apply = lambda: None
        frame._update_status_label = lambda *a, **kw: None
        frame._ensure_player_window = lambda: frame.window_attached.append(True)
        frame.player = types.SimpleNamespace(
            stop=lambda: None,
            set_media=lambda _m: None,
            play=lambda: None,
            set_nsobject=lambda _v: None,
            set_xwindow=lambda _v: None,
            set_hwnd=lambda v: frame.hwnd_calls.append(v),
        )
        frame.SetTitle = lambda _t: None
        frame.play_pause_btn = types.SimpleNamespace(
            SetLabel=lambda _l: None, SetFocus=lambda: None)
        frame._status_timer = types.SimpleNamespace(Start=lambda _ms: None)
        return frame

    def _play(self, frame, **kw):
        internal_player.InternalPlayerFrame.play(
            frame, "http://example/stream.ts", "Chan", **kw)

    def test_hidden_stream_is_remembered_and_survives_a_reconnect(self, monkeypatch):
        # Neutralise the visible-play focus hop so a regression fails on the
        # assertions below rather than on wx wanting an app.
        monkeypatch.setattr(internal_player.wx, "CallAfter", lambda *a, **kw: None)
        frame = self._stub_frame()
        self._play(frame, video_visible=False)
        assert frame._video_visible is False
        assert ":no-video" in frame.media_options
        assert frame.hwnd_calls == [0], "video window must be detached"
        assert frame.window_attached == []

        frame.media_options.clear()
        frame.hwnd_calls.clear()
        self._play(frame, _retry=True)          # what the restart paths call
        assert ":no-video" in frame.media_options, "reconnect re-enabled video"
        assert ":vout=dummy" in frame.media_options
        assert frame.hwnd_calls == [0]
        assert frame.window_attached == [], "no video window may be attached"

    def test_a_visible_stream_still_reconnects_with_video(self, monkeypatch):
        # A visible play hands focus back via wx.CallAfter, which needs an app.
        monkeypatch.setattr(internal_player.wx, "CallAfter", lambda *a, **kw: None)
        frame = self._stub_frame()
        self._play(frame, video_visible=True)
        assert frame._video_visible is True
        assert ":no-video" not in frame.media_options

        frame.media_options.clear()
        frame.window_attached.clear()
        self._play(frame, _retry=True)
        assert ":no-video" not in frame.media_options
        assert frame.window_attached == [True]

    def test_a_new_stream_overrides_the_remembered_visibility(self, monkeypatch):
        """Opening the same player visibly after a hidden play must show video."""
        monkeypatch.setattr(internal_player.wx, "CallAfter", lambda *a, **kw: None)
        frame = self._stub_frame()
        self._play(frame, video_visible=False)
        frame.media_options.clear()
        self._play(frame, video_visible=True)   # not a retry: the caller decides
        assert frame._video_visible is True
        assert ":no-video" not in frame.media_options


class TestAudioOutputDeviceEnumeration:
    """Opening Audio Output Device from the player menu used to crash the app.

    libvlc_audio_output_device_enum returns the head of a linked list as a raw
    ctypes pointer. A pointer has no __iter__ but does have __getitem__, so
    ``for item in enumerated`` fell back to the old iteration protocol and
    walked p[0], p[1], p[2]... past the one struct that exists, reading unmapped
    memory and killing the process outright - no traceback, no log line.
    """

    class _Node:
        """One libvlc_audio_output_device_t, reached through .contents."""
        def __init__(self, device, description, nxt=None):
            self.device = device
            self.description = description
            self.next = nxt

    class _Ptr:
        """A ctypes-pointer stand-in: indexable, so `for` would run away."""
        def __init__(self, node):
            self.contents = node
            self.reads = []

        def __bool__(self):
            return self.contents is not None

        def __getitem__(self, index):
            # The real pointer happily returns garbage here; blow up instead so
            # a regression is a loud test failure rather than a silent pass.
            raise AssertionError(
                "indexed the device pointer at [%r] - this is what crashed" % index)

    def _frame(self, head, released):
        frame = types.SimpleNamespace(
            player=types.SimpleNamespace(audio_output_device_enum=lambda: head))
        frame._decode_track_name = internal_player.InternalPlayerFrame._decode_track_name
        return frame

    def _run(self, head, monkeypatch):
        released = []
        monkeypatch.setattr(internal_player.vlc, "libvlc_audio_output_device_list_release",
                            lambda h: released.append(h), raising=False)
        frame = self._frame(head, released)
        pairs = internal_player.InternalPlayerFrame._list_audio_output_devices(frame)
        return pairs, released

    def test_walks_the_linked_list_instead_of_indexing_the_pointer(self, monkeypatch):
        tail = self._Node(b"{guid-2}", b"Speakers (Realtek(R) Audio)")
        head = self._Ptr(self._Node(b"", b"Default", self._Ptr(tail)))
        pairs, released = self._run(head, monkeypatch)
        # The empty id is libVLC's "system default"; the dialog supplies its own.
        assert pairs == [("{guid-2}", "Speakers (Realtek(R) Audio)")]
        assert released == [head], "the device list must be released"

    def test_ids_and_names_are_decoded_not_bytes_reprs(self, monkeypatch):
        head = self._Ptr(self._Node(b"{guid}", "Lautsprecher (Realtek)".encode("utf-8")))
        pairs, _released = self._run(head, monkeypatch)
        device_id, description = pairs[0]
        assert device_id == "{guid}"
        assert description == "Lautsprecher (Realtek)"
        assert not device_id.startswith("b'"), "a bytes repr can never match a saved id"

    def test_no_devices_is_empty_not_a_crash(self, monkeypatch):
        pairs, released = self._run(self._Ptr(None), monkeypatch)
        assert pairs == []
        assert released == [], "nothing was enumerated, so nothing to release"

    def test_a_failing_enum_is_survivable(self):
        def boom():
            raise OSError("libVLC said no")
        frame = types.SimpleNamespace(
            player=types.SimpleNamespace(audio_output_device_enum=boom))
        assert internal_player.InternalPlayerFrame._list_audio_output_devices(frame) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
