"""Catch-up return, Player menu state, update messages and download windows.

* Closing the built-in player on a catch-up programme reopens that channel's
  catch-up list on the programme that was playing; a live channel never does.
* The Player menu (menu bar and tray) is greyed out while the built-in player
  has nothing loaded.
* The update progress dialog is handed each message once, so NVDA is not cut
  off and restarted by an identical re-set on every tick.
* Escape and Alt+F4 hide a download window without cancelling it, and
  View > Show Downloads brings the windows back, cycling through several.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")

import main  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


class _Item:
    def __init__(self):
        self.enabled = None

    def Enable(self, value=True):
        self.enabled = bool(value)


_BOUND = (
    "_internal_player_has_media",
    "_sync_player_controls_menu",
    "_on_internal_player_closed",
    "_fresh_update_message",
    "_apply_update_progress",
    "_show_catchup_downloads",
)


def _client(**attrs):
    client = types.SimpleNamespace(**attrs)
    for name in _BOUND:
        setattr(client, name, getattr(main.IPTVClient, name).__get__(client))
    return client


# ------------------------------------------------------------- Player menu

def _loaded_frame(**overrides):
    values = dict(_destroyed=False, _current_url="http://host/live.m3u8",
                  _last_resolved_url="http://host/live.m3u8")
    values.update(overrides)
    return types.SimpleNamespace(**values)


def test_player_menu_is_greyed_out_with_nothing_loaded():
    items = tuple(_Item() for _ in range(4))
    client = _client(_player_control_items=items, _internal_player_frame=None)
    client._sync_player_controls_menu()
    assert [item.enabled for item in items] == [False] * 4


def test_player_menu_is_available_while_a_stream_is_loaded():
    items = tuple(_Item() for _ in range(4))
    # Stopped, but with a stream to resume: still something to control.
    frame = _loaded_frame(_current_url=None)
    client = _client(_player_control_items=items, _internal_player_frame=frame)
    client._sync_player_controls_menu()
    assert [item.enabled for item in items] == [True] * 4


def test_player_menu_ignores_a_destroyed_player():
    client = _client(_internal_player_frame=_loaded_frame(_destroyed=True))
    assert client._internal_player_has_media() is False


def test_tray_player_controls_follow_the_player(wx_app):
    tray = main.TrayIcon
    for loaded in (False, True):
        fake = types.SimpleNamespace(
            TBMENU_RESTORE=tray.TBMENU_RESTORE,
            TBMENU_EXIT=tray.TBMENU_EXIT,
            TBMENU_PLAYER_SHOW=tray.TBMENU_PLAYER_SHOW,
            TBMENU_PLAYER_TOGGLE=tray.TBMENU_PLAYER_TOGGLE,
            TBMENU_PLAYER_STOP=tray.TBMENU_PLAYER_STOP,
            TBMENU_CAST=tray.TBMENU_CAST,
            TBMENU_RECORD_STOP=tray.TBMENU_RECORD_STOP,
            on_record_stop=None,
            parent=types.SimpleNamespace(_internal_player_has_media=lambda loaded=loaded: loaded),
        )
        menu = tray.CreatePopupMenu(fake)
        try:
            submenu = next(item.GetSubMenu() for item in menu.GetMenuItems()
                           if item.GetSubMenu())
            states = [item.IsEnabled() for item in submenu.GetMenuItems()
                      if not item.IsSeparator()]
            assert states == [loaded] * 4
        finally:
            menu.Destroy()


# ------------------------------------------------------ Catch-up return

def test_closing_a_catchup_playback_reopens_its_list(monkeypatch):
    queued = []
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: queued.append((fn, a)))
    target = {"channel": {"name": "TVP 1"}, "start": "20260910183000"}
    client = _client(
        _internal_player_frame=object(),
        _internal_player_stream_kind="catchup",
        _catchup_return=target,
        _return_to_catchup_list=lambda _ret: None,
    )
    client._on_internal_player_closed()
    assert queued == [(client._return_to_catchup_list, (target,))]
    assert client._catchup_return is None
    assert client._internal_player_frame is None
    assert client._internal_player_stream_kind == "live"


def test_closing_a_live_playback_does_not_reopen_catchup(monkeypatch):
    queued = []
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: queued.append(fn))
    client = _client(
        _internal_player_stream_kind="live",
        _catchup_return={"channel": {"name": "TVP 1"}, "start": "x"},
        _return_to_catchup_list=lambda _ret: None,
    )
    client._on_internal_player_closed()
    assert queued == []
    # A stale return target must not fire on some later close either.
    assert client._catchup_return is None


def _returning_client(opened, **overrides):
    values = dict(
        IsBeingDeleted=lambda: False,
        IsShown=lambda: True,
        _modal_box_is_open=lambda: False,
        _open_catchup_dialog=lambda channel, select_start="": opened.append((channel, select_start)),
    )
    values.update(overrides)
    return types.SimpleNamespace(**values)


def test_return_opens_the_list_on_the_played_programme():
    opened = []
    client = _returning_client(opened)
    main.IPTVClient._return_to_catchup_list(
        client, {"channel": {"name": "TVP 1"}, "start": "20260910183000"})
    assert opened == [({"name": "TVP 1"}, "20260910183000")]


@pytest.mark.parametrize("override", [
    {"IsShown": lambda: False},                        # minimized to the tray
    {"_suppress_recording_notifications": True},       # the app is quitting
    {"_modal_box_is_open": lambda: True},              # something else is asking
])
def test_return_stays_quiet_when_it_would_intrude(override):
    opened = []
    client = _returning_client(opened, **override)
    main.IPTVClient._return_to_catchup_list(client, {"channel": {}, "start": ""})
    assert opened == []


def test_catchup_list_opens_on_the_given_programme(wx_app):
    progs = [
        {"title": "A", "start": "20260910160000", "end": "20260910170000"},
        {"title": "B", "start": "20260910183000", "end": "20260910192500"},
    ]
    dlg = main.CatchupDialog(None, "TVP 1", progs, initial_start="20260910183000")
    try:
        assert dlg.listbox.GetSelection() == 1
    finally:
        dlg.Destroy()
    dlg = main.CatchupDialog(None, "TVP 1", progs, initial_start="gone")
    try:
        assert dlg.listbox.GetSelection() == 0
    finally:
        dlg.Destroy()


# -------------------------------------------------------- Update messages

def test_update_message_is_handed_over_once():
    client = _client()
    assert client._fresh_update_message("Installing") == "Installing"
    assert client._fresh_update_message("Installing") == ""
    assert client._fresh_update_message("Downloading") == "Downloading"
    assert client._fresh_update_message("") == ""


def test_update_progress_ticks_do_not_resend_the_phase():
    calls = []
    dlg = types.SimpleNamespace(
        Pulse=lambda msg="": calls.append(("pulse", msg)) or (True, False),
        Update=lambda pct, msg="": calls.append((pct, msg)) or (True, False),
    )
    client = _client(_update_progress_dlg=dlg)
    client._apply_update_progress("Downloading update...", 0.1)
    client._apply_update_progress("Downloading update...", 0.2)
    client._apply_update_progress("Verifying...", None)
    assert calls == [(10, "Downloading update..."), (20, ""), ("pulse", "Verifying...")]


# -------------------------------------------------------- Download windows

def test_show_downloads_cycles_through_the_windows():
    revealed = []

    class Window:
        def __init__(self, name):
            self.name, self.active = name, False

        def IsShown(self):
            return True

        def IsActive(self):
            return self.active

        def reveal(self):
            revealed.append(self.name)

    first, second = Window("first"), Window("second")
    client = _client(_catchup_downloads={1: first, 2: second})
    client._show_catchup_downloads()
    assert revealed == ["first"]
    first.active = True
    client._show_catchup_downloads()
    assert revealed == ["first", "second"]
    first.active, second.active = False, True
    client._show_catchup_downloads()
    assert revealed[-1] == "first"
    _client(_catchup_downloads={})._show_catchup_downloads()  # nothing to show


def _download_window(tmp_path, on_cancel):
    log_path = tmp_path / "rec.log"
    log_path.write_text("", encoding="utf-8")
    rec = types.SimpleNamespace(title="Ojciec Mateusz 35", log_path=str(log_path),
                                written_path=str(tmp_path / "out.mkv"))
    return main.CatchupDownloadDialog(None, rec, duration=3300.0, on_cancel=on_cancel)


def test_escape_and_alt_f4_hide_the_window_and_keep_downloading(wx_app, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "message_box",
                        lambda *a, **k: pytest.fail("closing the window asked to cancel"))
    cancelled = []
    dlg = _download_window(tmp_path, lambda: cancelled.append(True))
    try:
        # Escape must not be routed to the Cancel button.
        assert dlg.cancel_btn.GetId() != wx.ID_CANCEL
        dlg.Show()
        dlg._on_char_hook(types.SimpleNamespace(GetKeyCode=lambda: wx.WXK_ESCAPE,
                                                Skip=lambda: None))
        assert not dlg.IsShown()
        dlg.reveal()
        assert dlg.IsShown()
        vetoed = []
        dlg._on_close(types.SimpleNamespace(CanVeto=lambda: True,
                                            Veto=lambda: vetoed.append(True),
                                            Skip=lambda: None))
        assert vetoed == [True]
        assert not dlg.IsShown()
        assert cancelled == []
    finally:
        dlg._timer.Stop()
        dlg.Destroy()


def test_cancel_button_still_asks_before_stopping(wx_app, tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(main, "message_box",
                        lambda *a, **k: asked.append(a) or main.wx.NO)
    cancelled = []
    dlg = _download_window(tmp_path, lambda: cancelled.append(True))
    try:
        dlg._cancel_download()
        assert len(asked) == 1
        assert cancelled == []
    finally:
        dlg._timer.Stop()
        dlg.Destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows taskbar style")
def test_download_window_has_its_own_taskbar_button(wx_app, tmp_path):
    import ctypes
    user32 = ctypes.WinDLL("user32")
    get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    get_style.restype = ctypes.c_ssize_t
    get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
    dlg = _download_window(tmp_path, lambda: None)
    try:
        style = get_style(ctypes.c_void_p(int(dlg.GetHandle())), -20)
        assert style & 0x00040000  # WS_EX_APPWINDOW
    finally:
        dlg._timer.Stop()
        dlg.Destroy()
