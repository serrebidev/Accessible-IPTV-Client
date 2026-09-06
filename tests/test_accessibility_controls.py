"""Focused tests for accessible controls added to the main window."""

import os
import sys
import types
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


class _MenuItem:
    def __init__(self):
        self.enabled = None

    def Enable(self, value=True):
        self.enabled = bool(value)


class _Recorder:
    def __init__(self, active_key=None):
        self.active_key = active_key

    def is_recording(self, key):
        return key == self.active_key

    def has_active(self):
        return self.active_key is not None


def test_recording_menu_disables_the_action_that_cannot_succeed():
    start, stop, stop_all = _MenuItem(), _MenuItem(), _MenuItem()
    channel = {"name": "News"}
    frame = types.SimpleNamespace(
        _recording_menu_items=(start, stop, stop_all),
        _selected_channel=lambda: channel,
        _channel_record_key=lambda _channel: "news",
        recorder=_Recorder(active_key="news"),
    )

    main.IPTVClient._update_recording_menu_state(frame)
    assert start.enabled is False
    assert stop.enabled is True
    assert stop_all.enabled is True

    frame.recorder = _Recorder()
    main.IPTVClient._update_recording_menu_state(frame)
    assert start.enabled is True
    assert stop.enabled is False
    assert stop_all.enabled is False


class _FocusTarget:
    def __init__(self):
        self.focused = False

    def SetFocus(self):
        self.focused = True


class _KeyEvent:
    def __init__(self, key, shift=False):
        self.key = key
        self.shift = shift
        self.skipped = False

    def GetKeyCode(self):
        return self.key

    def ShiftDown(self):
        return self.shift

    def Skip(self):
        self.skipped = True


def test_shift_tab_from_epg_returns_to_the_channel_list():
    channels, url = _FocusTarget(), _FocusTarget()
    frame = types.SimpleNamespace(channel_list=channels, url_display=url)
    event = _KeyEvent(main.wx.WXK_TAB, shift=True)

    main.IPTVClient._on_epg_display_key(frame, event)

    assert channels.focused is True
    assert url.focused is False
    assert event.skipped is False


def test_about_urls_and_diagnostic_redaction_are_safe():
    assert main.TELEGRAM_SUPPORT_URL == "https://t.me/SerrebiProjects"
    assert main.PROJECT_GITHUB_URL == "https://github.com/serrebidev/Accessible-IPTV-Client"
    assert main.SERREBI_GITHUB_URL == "https://github.com/serrebidev"

    user_key, pass_key, token_key = "username", "password", "token"
    report = main._redact_diagnostic_text(
        "https://example.test/live?" + user_key + "=alice&" + pass_key
        + "=secret " + token_key + "=abc"
    )
    assert "alice" not in report
    assert "secret" not in report
    assert "abc" not in report


def test_catchup_download_uses_the_programme_window(monkeypatch, tmp_path):
    started = []

    class Recorder:
        def is_recording(self, _key):
            return False

        def start(self, *args, **kwargs):
            started.append((args, kwargs))
            return types.SimpleNamespace(out_path=str(tmp_path / "programme.mkv"))

    frame = types.SimpleNamespace(
        config={"recording_format": "provider_mkv"},
        recorder=Recorder(),
        _parse_epg_time=lambda value: {
            "start": datetime.datetime(2026, 1, 1, 10, tzinfo=datetime.timezone.utc),
            "end": datetime.datetime(2026, 1, 1, 10, 30, tzinfo=datetime.timezone.utc),
        }[value],
        _resolve_show_url=lambda _channel, _show: ("https://catchup.example/programme", True),
        _channel_display_name=lambda _channel: "News",
        _channel_record_key=lambda _channel: "news",
        _on_recording_finished=lambda *_args: None,
        _note_recording_started=lambda: None,
        _recording_format_label=lambda _fmt: "Provider quality",
    )
    monkeypatch.setattr(main, "get_recordings_dir", lambda _config: str(tmp_path))
    monkeypatch.setattr(main, "channel_http_headers", lambda _channel: {})
    monkeypatch.setattr(main.wx, "MessageBox", lambda *_args, **_kwargs: None)

    main.IPTVClient._download_catchup_programme(
        frame,
        {"name": "News"},
        {"start": "start", "end": "end", "show_title": "The Programme"},
    )

    args, kwargs = started[0]
    assert args[0] == "https://catchup.example/programme"
    assert args[1] == "The Programme - News"
    assert kwargs["duration"] == 1800.0
    assert kwargs["metadata"]["catchup"] is True


def test_channel_context_scheduling_offers_the_upcoming_week(monkeypatch):
    calls = []

    class Database:
        def __init__(self, _path, readonly=False):
            assert readonly is True

        def get_schedule(self, channel, start, end):
            calls.append((channel, start, end))
            return [{"title": "Tonight", "start": "20260101100000", "end": "20260101110000"}]

        def close(self):
            return None

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target
            assert daemon is True

        def start(self):
            self.target()

    shown = []
    channel = {"name": "News"}
    frame = types.SimpleNamespace(
        _channel_display_name=lambda _channel: "News",
        _show_epg_dialog=lambda *args: shown.append(args),
    )
    monkeypatch.setattr(main, "EPGDatabase", Database)
    monkeypatch.setattr(main, "get_db_path", lambda: "epg.db")
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(main.wx, "CallAfter", lambda callback, *args: callback(*args))

    main.IPTVClient._schedule_channel_recording(frame, channel)

    assert calls[0][0] is channel
    assert calls[0][2] - calls[0][1] == datetime.timedelta(days=7)
    assert shown[0] == (channel, "News", [{"title": "Tonight", "start": "20260101100000", "end": "20260101110000"}])
