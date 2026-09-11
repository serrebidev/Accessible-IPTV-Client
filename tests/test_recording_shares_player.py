"""Recording the channel the built-in player shows uses one provider connection.

Issue #13: many providers allow one connection per account and some block
accounts that open more. Recording used to open a second one next to the
player's. Now the player lets go, the recording opens the stream, and the
player watches the recording's own copy of it through a local relay; when the
recording ends the player goes back to the provider by itself.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
import recorder  # noqa: E402

TVP = {"name": "TVP 1", "url": "http://provider.invalid/live/tvp1.ts"}
RELAY = "http://127.0.0.1:50123/live.ts"


class _Frame:
    def __init__(self, url="http://provider.invalid/live/tvp1.ts", shown=True):
        self._current_url = url
        self._manual_stop = False
        self._destroyed = False
        self.shown = shown
        self.stops = []

    def IsShown(self):
        return self.shown

    def stop(self, manual=False):
        self.stops.append(manual)
        self._manual_stop = self._manual_stop or manual


class _Recorder:
    def __init__(self, events):
        self.events = events
        self.started = []

    def is_recording(self, _key):
        return False

    def start(self, *args, **kwargs):
        self.events.append("record")
        self.started.append(kwargs)
        relay = types.SimpleNamespace(url=RELAY) if kwargs.get("share_with_player") else None
        return types.SimpleNamespace(id=7, out_path="C:/rec/tvp1.mkv", relay=relay)


def _bind(client, *names):
    for name in names:
        setattr(client, name, getattr(main.IPTVClient, name).__get__(client))
    return client


def _client(monkeypatch, *, showing, frame=None):
    events = []
    monkeypatch.setattr(main.threading, "Thread",
                        lambda target=None, daemon=None, **_k: types.SimpleNamespace(start=target))
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(main, "get_recordings_dir", lambda _config: "C:/rec")
    monkeypatch.setattr(main, "message_box", lambda *a, **k: None)
    monkeypatch.setattr(main.catchup_direct, "settle_media_session", lambda: events.append("settle"))
    frame = frame or _Frame()
    original_stop = frame.stop

    def stop(manual=False):
        events.append("player stop")
        original_stop(manual)

    frame.stop = stop
    client = types.SimpleNamespace(
        config={"recording_format": "provider_mkv"},
        recorder=_Recorder(events),
        events=events,
        launched=[],
        _internal_player_frame=frame,
        _channel_record_key=lambda channel: "rec:" + channel["name"],
        _resolve_live_url=lambda _channel: "http://provider.invalid/live/tvp1.ts",
        _channel_display_name=lambda _channel: "TVP 1",
        _recording_audio_intent=lambda _channel, **_k: None,
        _recording_audio_choice=lambda url, headers, intent: None,
        _note_recording_started=lambda: None,
        _recording_format_label=lambda fmt: fmt,
        _on_recording_finished=lambda *a: None,
        _sync_internal_player_record_state=lambda: None,
        _player_is_showing=lambda _channel: showing,
    )
    client._launch_stream = lambda url, title, **kwargs: (
        events.append("play " + url), client.launched.append((url, kwargs)))
    return _bind(client, "_record_channel", "_start_live_recording",
                 "_end_shared_playback", "_resume_direct_playback")


def test_recording_the_playing_channel_opens_one_connection(monkeypatch):
    client = _client(monkeypatch, showing=True)
    client._record_channel(TVP)

    # The player lets go first and the provider is given time to release it;
    # only then does the recording open the stream, and the player follows it.
    assert client.events == ["player stop", "settle", "record", "play " + RELAY]
    assert client.recorder.started[0]["share_with_player"] is True
    (url, kwargs), = client.launched
    assert kwargs["channel"] == TVP and kwargs["show_internal_player"] is True
    assert kwargs["focus_player"] is False
    assert client._shared_recordings[7]["url"] == RELAY


def test_recording_another_channel_leaves_the_player_alone(monkeypatch):
    client = _client(monkeypatch, showing=False)
    client._record_channel(TVP)
    assert client.events == ["record"]
    assert client.recorder.started[0]["share_with_player"] is False
    assert client.launched == []


def test_the_player_goes_back_without_stealing_focus_when_the_recording_ends(monkeypatch):
    client = _client(monkeypatch, showing=True, frame=_Frame(url=RELAY))
    client._end_shared_playback({"channel": TVP, "url": RELAY, "shown": True})
    # The recording's connection is released before the player reconnects.
    assert client.events == ["player stop", "settle",
                             "play http://provider.invalid/live/tvp1.ts"]
    (_url, kwargs), = client.launched
    assert kwargs["show_internal_player"] is True
    assert kwargs["focus_player"] is False


def test_relay_handoff_keeps_the_existing_focus_in_the_player():
    """The source changes, but no focus call can escape an open message box."""
    events = []
    play_kwargs = []

    class Frame:
        def Enable(self, value):
            events.append(("enable", value))

        def Show(self):
            events.append(("show", None))

        def Raise(self):
            events.append(("raise", None))

        def SetFocus(self):
            events.append(("focus", None))

        def play(self, _url, _title, **kwargs):
            events.append(("play", None))
            play_kwargs.append(kwargs)

    frame = Frame()
    client = types.SimpleNamespace(
        default_player="Built-in Player",
        show_player_on_enter=True,
        caster=None,
        config={},
        _ensure_internal_player=lambda: frame,
        _channel_audio_key=lambda _channel: "tvp 1",
        _sync_internal_player_record_state=lambda: None,
    )
    _bind(client, "_launch_stream")

    client._launch_stream(
        RELAY, "TVP 1", channel=TVP,
        show_internal_player=True, focus_player=False)

    assert ("enable", True) in events and ("show", None) in events
    assert ("play", None) in events
    assert ("raise", None) not in events and ("focus", None) not in events
    assert play_kwargs[0]["focus_controls"] is False


def test_no_hand_back_when_the_user_moved_on(monkeypatch):
    client = _client(monkeypatch, showing=True, frame=_Frame(url="http://other/ch.ts"))
    client._end_shared_playback({"channel": TVP, "url": RELAY, "shown": True})
    assert client.events == []


def test_no_hand_back_when_the_user_stopped_the_player(monkeypatch):
    frame = _Frame(url=RELAY)
    frame._manual_stop = True
    client = _client(monkeypatch, showing=True, frame=frame)
    client._end_shared_playback({"channel": TVP, "url": RELAY, "shown": True})
    assert client.events == []


def test_the_player_is_showing_only_its_own_live_channel():
    def client(**overrides):
        values = dict(
            _internal_player_channel=TVP, _internal_player_stream_kind="live",
            _internal_player_has_media=lambda: True,
            _channel_record_key=lambda channel: "rec:" + channel["name"], caster=None)
        values.update(overrides)
        return _bind(types.SimpleNamespace(**values), "_player_is_showing")

    assert client()._player_is_showing(TVP)
    assert not client()._player_is_showing({"name": "Polsat"})
    assert not client(_internal_player_stream_kind="catchup")._player_is_showing(TVP)
    assert not client(_internal_player_has_media=lambda: False)._player_is_showing(TVP)
    casting = types.SimpleNamespace(is_connected=lambda: True)
    assert not client(caster=casting)._player_is_showing(TVP)


def test_the_recording_writes_a_copy_for_the_player():
    cmd = recorder.build_ffmpeg_command(
        "ffmpeg", "http://provider.invalid/live.ts", "out.mp3", "audio_mp3_v0",
        copy_to_stdout=True)
    # Second output, after the file: the stream untouched, video included even
    # though the file itself is audio only.
    assert cmd[-1] == "pipe:1"
    tail = cmd[cmd.index("out.mp3") + 1:]
    assert tail == ["-map", "0:v?", "-map", "0:a?", "-c", "copy", "-f", "mpegts", "pipe:1"]
    assert "pipe:1" not in recorder.build_ffmpeg_command(
        "ffmpeg", "http://provider.invalid/live.ts", "out.mp3", "audio_mp3_v0")
