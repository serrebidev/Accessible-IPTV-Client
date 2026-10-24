"""GUI tests: every dialog in the app really constructs.

Regression cover for the "View EPG does nothing" class of bug: a dialog whose
constructor crashes inside a ``wx.CallAfter`` looks like a silently dead menu
item. These tests build each dialog with real wx and minimal stubs, so a
constructor-level crash (missing wx method, attribute typo, bad label order)
fails loudly here instead of shipping.

Skipped when wxPython or a usable display is unavailable.
"""
import os
import sys
import threading
import types
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")

import account_info  # noqa: E402
import main as appmod  # noqa: E402
from internal_player import AudioDeviceDialog  # type: ignore[attr-defined]  # noqa: E402

AccessibleAboutDialog: Any = appmod.AccessibleAboutDialog
CastDiscoveryDialog: Any = appmod.CastDiscoveryDialog
AccountInfoDialog: Any = appmod.AccountInfoDialog
CatchupDialog: Any = appmod.CatchupDialog
AudioTrackPreferenceDialog: Any = appmod.AudioTrackPreferenceDialog
RecordingPaddingDialog: Any = appmod.RecordingPaddingDialog
ShutdownCountdownDialog: Any = appmod.ShutdownCountdownDialog
ScheduledRecordingsDialog: Any = appmod.ScheduledRecordingsDialog
ChangelogDialog: Any = appmod.ChangelogDialog
WhatsOnNowDialog: Any = appmod.WhatsOnNowDialog


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


@pytest.fixture
def host(wx_app):
    frame = wx.Frame(None, title="dialog sweep host")
    yield frame
    frame.Destroy()


def test_about_dialog_builds(host):
    dlg = AccessibleAboutDialog(host)
    try:
        assert dlg.GetTitle()
    finally:
        dlg.Destroy()


def test_cast_discovery_dialog_builds(host):
    # discover_all never finishes during the test, so the pending
    # wx.CallAfter can never fire against the destroyed dialog.
    # A fixed sleep woke up once a long suite had torn down the wx.App, and
    # the CallAfter then failed on the daemon thread; block for good instead.
    caster = types.SimpleNamespace(discover_all=lambda: threading.Event().wait() or [])
    dlg = CastDiscoveryDialog(host, caster)
    try:
        assert dlg.listbox.GetCount() == 0
    finally:
        dlg.Destroy()


def test_account_info_dialog_builds(host, monkeypatch):
    accounts = [
        account_info.Account(kind="xtream", base_url="http://panel.example/", username="u"),
        account_info.Account(kind="stalker", base_url="http://portal.example/c/", mac="00:1A:79:00:00:01"),
    ]
    # The first account is looked up on a daemon thread and the answer comes
    # back with wx.CallAfter. A pending CallAfter that fires after the wx.App
    # is torn down fails on that thread, so block the fetch for good instead
    # - the same reason the cast discovery test above does.
    monkeypatch.setattr(account_info, "fetch_account_report",
                        lambda *a, **k: threading.Event().wait())
    dlg = AccountInfoDialog(host, accounts)
    try:
        assert dlg.listbox.GetCount() == 2
    finally:
        dlg.Destroy()


def test_catchup_dialog_builds(host):
    progs = [{"title": "Evening News", "start": "20260907190000", "end": "20260907200000"}]
    dlg = CatchupDialog(host, "Sky Mix", progs)
    try:
        assert "Sky Mix" in dlg.GetTitle()
    finally:
        dlg.Destroy()


def test_audio_track_dialog_builds(host):
    dlg = AudioTrackPreferenceDialog(host)
    try:
        assert dlg.GetTitle()
    finally:
        dlg.Destroy()


def test_recording_padding_dialog_builds(host):
    dlg = RecordingPaddingDialog(host, 1, 3)
    try:
        assert dlg.get_padding() == (1, 3)
    finally:
        dlg.Destroy()


def test_shutdown_countdown_dialog_builds(host):
    dlg = ShutdownCountdownDialog(host, on_cancel=lambda: None, on_shutdown=lambda: None, seconds=5)
    try:
        assert dlg.GetTitle()
    finally:
        dlg.Destroy()


def test_scheduled_recordings_dialog_builds(host):
    scheduler = types.SimpleNamespace(list_jobs=lambda **kw: [])
    dlg = ScheduledRecordingsDialog(host, scheduler)
    try:
        assert dlg.list_ctrl.GetColumnCount() == 5
    finally:
        dlg.Destroy()


def test_changelog_dialog_builds(host):
    dlg = ChangelogDialog(host)
    try:
        history = dlg.text.GetValue()
        assert history.startswith("# What's New")
        assert "Readable release history" not in history
        assert "\n## v" in history
    finally:
        dlg.Destroy()


def test_scheduled_recordings_dialog_populates_on_open(host):
    """The list is filled when the window opens; Refresh stays for manual use."""
    job = {"id": "j1", "status": "scheduled", "title": "News",
           "channel_name": "TVP 1", "display_title": "News - TVP 1",
           "start_ts": 0, "stop_ts": 3600, "format": "provider_mkv"}
    scheduler = types.SimpleNamespace(list_jobs=lambda **kw: [job])

    class Parent(wx.Frame):
        def _schedule_window_label(self, _job):
            return "1970-01-01 00:00 - 1970-01-01 01:00"

        def _recording_format_label(self, _fmt):
            return "MKV"

    parent = Parent(host)
    try:
        dlg = ScheduledRecordingsDialog(parent, scheduler)
        try:
            assert dlg.list_ctrl.GetItemCount() == 1
            assert dlg.list_ctrl.GetItemText(0, 1) == "News"
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()


def test_the_scheduled_recordings_context_menu_does_not_move_the_dialog(host, monkeypatch):
    """The dialog jumped back to the middle of the main window every time.

    The user opened the context menu with the Applications key or Shift+F10
    and the window moved under them for no reason.
    """
    scheduler = types.SimpleNamespace(list_jobs=lambda **kw: [])
    dlg = ScheduledRecordingsDialog(host, scheduler)
    centred = []
    monkeypatch.setattr(dlg, "CenterOnParent", lambda: centred.append(True))
    monkeypatch.setattr(dlg.list_ctrl, "PopupMenu", lambda menu, pos: None)
    try:
        dlg._show_context_menu(keyboard=True)
        assert centred == [], "the dialog was moved while the context menu was open"
    finally:
        dlg.Destroy()


def test_scheduled_recordings_delete_shortcut_is_silent_when_empty(host, monkeypatch):
    scheduler = types.SimpleNamespace(list_jobs=lambda **kw: [])
    dlg = ScheduledRecordingsDialog(host, scheduler)
    calls = []
    monkeypatch.setattr(dlg, "_on_delete_selected", lambda event: calls.append(event))
    event = types.SimpleNamespace(GetKeyCode=lambda: wx.WXK_DELETE, Skip=lambda: None)
    try:
        dlg._on_char_hook(event)
        assert calls == []
    finally:
        dlg.Destroy()


def test_scheduled_recordings_delete_shortcuts_act_when_populated(host, monkeypatch):
    job = {"id": "j1", "status": "scheduled", "title": "News",
           "channel_name": "TVP 1", "display_title": "News - TVP 1",
           "start_ts": 0, "stop_ts": 3600, "format": "provider_mkv"}
    scheduler = types.SimpleNamespace(list_jobs=lambda **kw: [job])

    class Parent(wx.Frame):
        def _schedule_window_label(self, _job):
            return "1970-01-01 00:00 - 1970-01-01 01:00"

        def _recording_format_label(self, _fmt):
            return "MKV"

    parent = Parent(host)
    try:
        dlg = ScheduledRecordingsDialog(parent, scheduler)
        calls = []
        monkeypatch.setattr(dlg, "_on_delete_selected", lambda event: calls.append(event))
        try:
            for key in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
                event = types.SimpleNamespace(GetKeyCode=lambda key=key: key, Skip=lambda: None)
                dlg._on_char_hook(event)
            assert len(calls) == 2
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()


def test_scheduled_recordings_menu_key_is_the_applications_key(host, monkeypatch):
    """WXK_MENU is Alt, so handling it here opened the menu on Alt.

    The Applications key must open the context menu; Alt must fall through to
    normal handling like any other unhandled key.
    """
    scheduler = types.SimpleNamespace(list_jobs=lambda **kw: [])
    dlg = ScheduledRecordingsDialog(host, scheduler)
    opened = []
    monkeypatch.setattr(dlg, "_show_context_menu", lambda keyboard: opened.append(keyboard))
    skipped = []
    try:
        alt = types.SimpleNamespace(GetKeyCode=lambda: wx.WXK_MENU, Skip=lambda: skipped.append(True))
        dlg._on_char_hook(alt)
        assert opened == []
        assert skipped == [True]

        apps = types.SimpleNamespace(
            GetKeyCode=lambda: wx.WXK_WINDOWS_MENU, Skip=lambda: skipped.append(True))
        dlg._on_char_hook(apps)
        assert opened == [True]
    finally:
        dlg.Destroy()


def test_scheduled_recordings_ctrl_a_selects_every_row(host):
    jobs = [
        {"id": "one", "status": "scheduled", "title": "News", "channel_name": "TVP 1", "format": "provider_mkv"},
        {"id": "two", "status": "scheduled", "title": "Film", "channel_name": "TVP 2", "format": "provider_mkv"},
    ]
    scheduler = types.SimpleNamespace(list_jobs=lambda **kw: jobs)

    class Parent(wx.Frame):
        def _schedule_window_label(self, _job):
            return "time"

        def _recording_format_label(self, _fmt):
            return "format"

    parent = Parent(host)
    dlg = ScheduledRecordingsDialog(parent, scheduler)
    event = types.SimpleNamespace(GetKeyCode=lambda: ord("A"), ControlDown=lambda: True, Skip=lambda: None)
    try:
        dlg._on_char_hook(event)
        assert len(dlg._selected_jobs()) == 2
    finally:
        dlg.Destroy()
        parent.Destroy()


def test_scheduled_recordings_delete_confirms_the_selected_title(host, monkeypatch):
    jobs = [
        {"id": "one", "status": "scheduled", "title": "Evening News", "channel_name": "TVP 1", "format": "provider_mkv"},
        {"id": "two", "status": "scheduled", "title": "Film", "channel_name": "TVP 2", "format": "provider_mkv"},
    ]
    deleted, prompts = [], []
    scheduler = types.SimpleNamespace(list_jobs=lambda **kw: jobs, delete_job=lambda job_id: deleted.append(job_id))

    class Parent(wx.Frame):
        def _schedule_window_label(self, _job):
            return "time"

        def _recording_format_label(self, _fmt):
            return "format"

    parent = Parent(host)
    dlg = ScheduledRecordingsDialog(parent, scheduler)
    monkeypatch.setattr(appmod, "message_box", lambda text, *_args: prompts.append(text) or wx.YES)
    try:
        dlg._on_delete_selected(None)
        assert prompts == ["Remove scheduled recording 'Evening News' from the list?"]
        assert deleted == ["one"]
    finally:
        dlg.Destroy()
        parent.Destroy()


def test_scheduled_recordings_single_item_uses_the_item_confirmation(host, monkeypatch):
    job = {"id": "one", "status": "scheduled", "title": "Evening News", "channel_name": "TVP 1", "format": "provider_mkv"}
    prompts = []
    scheduler = types.SimpleNamespace(list_jobs=lambda **kw: [job], delete_job=lambda _job_id: None)

    class Parent(wx.Frame):
        def _schedule_window_label(self, _job):
            return "time"

        def _recording_format_label(self, _fmt):
            return "format"

    parent = Parent(host)
    dlg = ScheduledRecordingsDialog(parent, scheduler)
    monkeypatch.setattr(appmod, "message_box", lambda text, *_args: prompts.append(text) or wx.NO)
    try:
        dlg._on_delete_selected(None)
        assert prompts == ["Remove scheduled recording 'Evening News' from the list?"]
    finally:
        dlg.Destroy()
        parent.Destroy()


def test_whats_on_now_dialog_builds(host):
    progs = [
        {"title": "Evening News", "start": "20260907190000", "end": "20260907200000",
         "channel_name": "Sky Mix"},
        {"title": "Late Film", "start": "20260907200000", "end": "20260907220000",
         "channel_name": "Cinema One"},
    ]
    dlg = WhatsOnNowDialog(host, progs, schedule_callback=None)
    try:
        assert dlg.listbox.GetItemCount() == 2
    finally:
        dlg.Destroy()


def test_audio_device_dialog_builds(host):
    dlg = AudioDeviceDialog(host, devices=[("dev1", "Speakers"), ("dev2", "Headphones")], current="dev1")
    try:
        # + 1 for the always-present System default entry.
        assert dlg.list_ctrl.GetItemCount() == 3 if hasattr(dlg, "list_ctrl") else dlg.GetTitle()
        panel = dlg.GetChildren()[0]
        labels = [child for child in panel.GetChildren()
                  if isinstance(child, wx.StaticText)]
        assert any(label.GetLabel() == "Audio output devices" for label in labels)
    finally:
        dlg.Destroy()


def test_exception_logging_hooks_install(monkeypatch):
    """_install_exception_logging routes uncaught UI exceptions to the log."""
    import threading

    calls = []
    monkeypatch.setattr(appmod.LOG, "error", lambda msg, *a, **kw: calls.append(msg))
    old_ui_hook, old_thread_hook = sys.excepthook, threading.excepthook
    try:
        appmod._install_exception_logging()
        try:
            raise RuntimeError("event loop explosion")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        assert any("event loop" in c for c in calls)

        calls.clear()
        try:
            raise ValueError("thread explosion")
        except ValueError:

            exc_tb = sys.exc_info()[2]
            threading.excepthook(
                threading.ExceptHookArgs((ValueError, ValueError("x"), exc_tb, None)))
        assert any("thread" in c for c in calls)
    finally:
        sys.excepthook = old_ui_hook
        threading.excepthook = old_thread_hook
