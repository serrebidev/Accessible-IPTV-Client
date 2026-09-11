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


def test_shift_tab_from_the_url_field_returns_to_the_episode_description():
    """The URL field now sits after the description, so back means description."""
    description, url = _FocusTarget(), _FocusTarget()
    frame = types.SimpleNamespace(
        episode_description_field=description, url_display=url)
    event = _KeyEvent(main.wx.WXK_TAB, shift=True)

    main.IPTVClient._on_url_display_key(frame, event)

    assert description.focused is True
    assert url.focused is False
    assert event.skipped is False


def test_about_urls_are_listed_and_diagnostics_keep_urls():
    assert main.TELEGRAM_SUPPORT_URL == "https://t.me/SerrebiProjects"
    assert main.PROJECT_GITHUB_URL == "https://github.com/serrebidev/Accessible-IPTV-Client"
    assert main.SERREBI_GITHUB_URL == "https://github.com/serrebidev"

    # The diagnostic report is deliberately verbatim: whoever receives it needs
    # the stream URL and credentials to reproduce a playback or download bug.
    user_key, pass_key, token_key = "username", "password", "token"
    report = (
        "https://example.test/live?" + user_key + "=alice&" + pass_key
        + "=secret " + token_key + "=abc"
    )
    assert "alice" in report
    assert "secret" in report
    assert "abc" in report


def test_catchup_download_uses_the_programme_window(monkeypatch, tmp_path):
    started = []

    class Recorder:
        def is_recording(self, _key):
            return False

        def start(self, *args, **kwargs):
            started.append((args, kwargs))
            return types.SimpleNamespace(out_path=str(tmp_path / "programme.mkv"), id=7)

    dialogs = []

    class Dialog:
        def __init__(self, parent, rec, **kwargs):
            dialogs.append((parent, rec, kwargs))
            self.rec = rec

        def Show(self):
            pass

        def Raise(self):
            pass

    frame = types.SimpleNamespace(
        config={"recording_format": "provider_mkv"},
        recorder=Recorder(),
        _catchup_downloads={},
        _maybe_shutdown_after_recordings=lambda: None,
        _catchup_download_finished=lambda *_args: None,
        _note_recording_started=lambda: None,
    )
    monkeypatch.setattr(main, "CatchupDownloadDialog", Dialog)
    monkeypatch.setattr(main, "get_recordings_dir", lambda _config: str(tmp_path))
    monkeypatch.setattr(main.wx, "MessageBox", lambda *_args, **_kwargs: None)

    main.IPTVClient._start_catchup_recording(
        frame,
        "https://catchup.example/programme",
        "The Programme - News",
        "catchup:abc",
        {"start": "start", "end": "end", "show_title": "The Programme"},
        1800.0,
        "provider_mkv",
        {},
    )

    args, kwargs = started[0]
    assert args[0] == "https://catchup.example/programme"
    assert args[1] == "The Programme - News"
    assert kwargs["duration"] == 1800.0
    assert kwargs["metadata"]["catchup"] is True
    # Stats lines in the log are what the progress dialog reads.
    assert kwargs["show_stats"] is True
    # A download is a throwaway capture: the recorder must write to a .part
    # file so nothing partial ever lands in the recordings folder.
    assert kwargs["keep_partial"] is False
    # The progress window replaces the old "download started" message box.
    assert len(dialogs) == 1
    # No parseable programme start: the recorder falls back to the clock.
    assert kwargs["file_time"] is None


def test_catchup_download_is_named_for_the_programme_start(monkeypatch, tmp_path):
    """The file's date is when the programme aired, as the EPG shows it."""
    started = []

    class Recorder:
        def is_recording(self, _key):
            return False

        def start(self, *args, **kwargs):
            started.append(kwargs)
            return types.SimpleNamespace(out_path=str(tmp_path / "x.mkv"), id=8)

    class Dialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def Show(self):
            pass

        def Raise(self):
            pass

    frame = types.SimpleNamespace(
        config={"recording_format": "provider_mkv"},
        recorder=Recorder(),
        _catchup_downloads={},
        _catchup_download_finished=lambda *_args: None,
        _note_recording_started=lambda: None,
    )
    monkeypatch.setattr(main, "CatchupDownloadDialog", Dialog)
    monkeypatch.setattr(main, "get_recordings_dir", lambda _config: str(tmp_path))

    main.IPTVClient._start_catchup_recording(
        frame, "https://catchup.example/p", "Ojciec Mateusz 35 - TVP 1", "catchup:x",
        {"start": "20260910183000", "end": "20260910192500"}, 3300.0, "provider_mkv", {})

    aired = started[0]["file_time"]
    # EPG times are UTC; the name uses local time, like the EPG dialogs.
    assert aired.utcoffset() is not None
    assert aired.astimezone(datetime.timezone.utc) == datetime.datetime(
        2026, 9, 10, 18, 30, tzinfo=datetime.timezone.utc)


def test_catchup_download_prefers_the_fast_direct_url(monkeypatch, tmp_path):
    """When the provider hosts a direct file, that URL is what gets recorded."""

    class Recorder:
        def is_recording(self, _key):
            return False

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    frame = types.SimpleNamespace(
        config={"recording_format": "provider_mkv"},
        recorder=Recorder(),
        _catchup_downloads={},
        _parse_epg_time=lambda value: {
            "start": datetime.datetime(2026, 1, 1, 10, tzinfo=datetime.timezone.utc),
            "end": datetime.datetime(2026, 1, 1, 10, 30, tzinfo=datetime.timezone.utc),
        }[value],
        _resolve_show_url=lambda _channel, _show: ("https://catchup.example/index.m3u8?tok=1", True),
        _channel_display_name=lambda _channel: "News",
        _channel_record_key=lambda _channel: "news",
        _recording_audio_intent=lambda _channel, **_kw: None,
    )
    for name in ("_download_catchup_programme", "_begin_catchup_download",
                 "_start_catchup_recording"):
        setattr(frame, name, getattr(main.IPTVClient, name).__get__(frame))
    queued = []
    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    monkeypatch.setattr(main, "get_recordings_dir", lambda _config: str(tmp_path))
    monkeypatch.setattr(main.catchup_direct, "direct_download_url",
                        lambda *_args, **_kwargs: "https://catchup.example/index-123-1800.mp4?tok=1")
    callafter = []
    monkeypatch.setattr(main.wx, "CallAfter", lambda cb, *a: callafter.append((cb, a)))

    main.IPTVClient._download_catchup_programme(
        frame,
        {"name": "News"},
        {"start": "start", "end": "end", "show_title": "The Programme"},
    )

    # The probe handed the fast direct file to the UI-thread starter.
    assert len(callafter) == 1
    callback, cb_args = callafter[0]
    assert callback == frame._start_catchup_recording
    assert cb_args[0] == "https://catchup.example/index-123-1800.mp4?tok=1"
    assert cb_args[2].startswith("catchup:")


def test_catchup_download_finish_reports_and_closes(monkeypatch, tmp_path):
    boxes = []
    monkeypatch.setattr(main.wx, "MessageBox", lambda msg, *a, **k: boxes.append(msg))
    destroyed = []

    class Dialog:
        def __init__(self):
            self.closed = False

        def notify_recording_finished(self):
            self.Destroy()

        def Destroy(self):
            destroyed.append(True)

    dlg = Dialog()
    rec = types.SimpleNamespace(
        id=3, out_path=str(tmp_path / "done.mkv"), stopped_by_user=False,
        stderr_tail=[], title="The Programme")
    frame = types.SimpleNamespace(
        _catchup_downloads={3: dlg},
        _maybe_shutdown_after_recordings=lambda: None,
        _recording_failure_detail=lambda _rec: "detail",
        _show_or_queue_message_box=lambda msg, cap, style: boxes.append(msg),
    )

    # The recorder's watcher thread calls this; wx.CallAfter is monkeypatched
    # to run synchronously so the UI-thread side is observed directly.
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    main.IPTVClient._catchup_download_finished(frame, rec, 0)

    # The progress window was closed and the completion box reported.
    assert destroyed == [True]
    assert frame._catchup_downloads == {}
    assert boxes and "done.mkv" in boxes[0]


def test_catchup_download_suppressed_on_exit(monkeypatch, tmp_path):
    boxes = []
    monkeypatch.setattr(main.wx, "MessageBox", lambda msg, *a, **k: boxes.append(msg))
    closed = []

    class Dialog:
        def notify_recording_finished(self):
            closed.append(True)

    rec = types.SimpleNamespace(
        id=5, out_path=str(tmp_path / "x.mkv"), stopped_by_user=False, stderr_tail=[])
    frame = types.SimpleNamespace(
        _catchup_downloads={5: Dialog()},
        _maybe_shutdown_after_recordings=lambda: None,
        _suppress_recording_notifications=True,
    )
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))

    main.IPTVClient._catchup_download_finished(frame, rec, 0)

    # The app is exiting: no box, no dialog work, bookkeeping dropped.
    assert boxes == []
    assert closed == []
    assert frame._catchup_downloads == {}


def test_close_warns_while_a_download_is_running(monkeypatch):
    answers = []
    monkeypatch.setattr(main.wx, "MessageBox", lambda *a, **k: answers.append(a) or main.wx.NO)

    frame = types.SimpleNamespace(
        minimize_to_tray=False,
        _update_install_pending=False,
        _exit_forced=False,
        _catchup_downloads={1: object()},
    )
    vetoed = []

    class Event:
        def CanVeto(self):
            return True

        def Veto(self):
            vetoed.append(True)

    main.IPTVClient.on_close(frame, Event())

    assert len(answers) == 1
    assert vetoed == [True]


def test_close_without_downloads_does_not_warn(monkeypatch):
    answers = []
    monkeypatch.setattr(main.wx, "MessageBox", lambda *a, **k: answers.append(a) or main.wx.NO)

    # Everything on_close touches after the warning gate, stubbed out.
    frame = types.SimpleNamespace(
        minimize_to_tray=False,
        _update_install_pending=False,
        _exit_forced=False,
        _catchup_downloads={},
        _search_token=0,
        _populate_token=0,
        caster=None,
        tray_icon=None,
        _internal_player_frame=None,
    )
    for name in ("_stop_epg_poll_timer", "_cancel_epg_autostart_timer",
                 "_stop_dvr_scheduler", "_release_recordings_on_exit"):
        setattr(frame, name, lambda *a, **k: None)
    frame._epg_executor = types.SimpleNamespace(shutdown=lambda wait: None)
    destroyed = []
    frame.Destroy = lambda: destroyed.append(True)

    class Event:
        def CanVeto(self):
            return True

        def Veto(self):
            raise AssertionError("must not veto a normal exit")

    main.IPTVClient.on_close(frame, Event())

    assert answers == []
    assert destroyed == [True]


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
