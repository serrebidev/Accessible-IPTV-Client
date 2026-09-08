"""Behaviour (not just construction) of the dialogs the user drives by keyboard.

Regression cover for a batch of reports:

* Enter on a catch-up programme did nothing, because a wx.Dialog consumes Enter
  before the focused control ever sees an ``EVT_KEY_DOWN``.
* "Schedule Recording" was only reachable as a button, never from the row's own
  context menu (right-click / Shift+F10 / Applications key).
* The Playlist Manager opened with focus on the "Add File" button, so a screen
  reader user had to tab past the whole button row to hear their playlists.
* The read-only stream-URL field under the channel list is now optional.
* The built-in player can start and stop a recording of what it is playing.
"""
import os
import sys
import types
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")

import main as appmod  # noqa: E402
import playlist as playlistmod  # noqa: E402

CatchupDialog: Any = appmod.CatchupDialog
ChannelEPGDialog: Any = appmod.ChannelEPGDialog
WhatsOnNowDialog: Any = appmod.WhatsOnNowDialog
IPTVClient: Any = appmod.IPTVClient
PlaylistManagerDialog: Any = playlistmod.PlaylistManagerDialog
EPGManagerDialog: Any = playlistmod.EPGManagerDialog
SourceNamesMixin: Any = playlistmod._SourceNamesMixin


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


@pytest.fixture
def host(wx_app):
    frame = wx.Frame(None, title="dialog action host")
    yield frame
    frame.Destroy()


def _char_hook(key):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(key)
    return event


def _capture_menu(monkeypatch, ctrl, captured):
    """Record a popped-up menu's items. The menu itself is destroyed right
    after ``PopupMenu`` returns, so read it inside the stub, not afterwards."""
    def popup(_self, menu, *_args):
        captured.extend((item.GetItemLabelText(), item.IsEnabled())
                        for item in menu.GetMenuItems())
        return True

    monkeypatch.setattr(type(ctrl), "PopupMenu", popup)


# --------------------------------------------------------------------------- #
# Catch-up: Enter opens the programme
# --------------------------------------------------------------------------- #
_CATCHUP_PROGRAMMES = [
    {"title": "Evening News", "start": "20260907190000", "end": "20260907200000"},
    {"title": "Late Film", "start": "20260907200000", "end": "20260907220000"},
]


def test_catchup_enter_opens_the_selected_programme(host):
    dlg = CatchupDialog(host, "Sky Mix", _CATCHUP_PROGRAMMES)
    ended = []
    dlg.EndModal = lambda code: ended.append(code)  # type: ignore[assignment]
    try:
        dlg.listbox.SetSelection(1)
        dlg.listbox.GetEventHandler().ProcessEvent(_char_hook(wx.WXK_RETURN))
        assert ended == [wx.ID_OK]
        assert dlg.get_selection()["title"] == "Late Film"
    finally:
        dlg.Destroy()


def test_catchup_has_a_default_open_button(host):
    """The default button is what wxMSW fires for Enter anywhere in the dialog."""
    dlg = CatchupDialog(host, "Sky Mix", _CATCHUP_PROGRAMMES)
    try:
        assert dlg.open_btn.GetId() == wx.ID_OK
        assert dlg.GetDefaultItem() is dlg.open_btn
    finally:
        dlg.Destroy()


def test_catchup_download_button_reports_the_download_action(host):
    dlg = CatchupDialog(host, "Sky Mix", _CATCHUP_PROGRAMMES)
    ended = []
    dlg.EndModal = lambda code: ended.append(code)  # type: ignore[assignment]
    try:
        event = wx.CommandEvent(wx.wxEVT_BUTTON, dlg.download_btn.GetId())
        dlg.download_btn.GetEventHandler().ProcessEvent(event)
        assert ended == [wx.ID_SAVE]
    finally:
        dlg.Destroy()


def test_catchup_plain_keys_do_not_activate(host):
    dlg = CatchupDialog(host, "Sky Mix", _CATCHUP_PROGRAMMES)
    ended = []
    dlg.EndModal = lambda code: ended.append(code)  # type: ignore[assignment]
    try:
        for key in (wx.WXK_DOWN, wx.WXK_TAB, wx.WXK_MENU, ord("A")):
            dlg.listbox.GetEventHandler().ProcessEvent(_char_hook(key))
        assert ended == []
    finally:
        dlg.Destroy()


# --------------------------------------------------------------------------- #
# "Schedule Recording" in the EPG row context menus
# --------------------------------------------------------------------------- #
_EPG_PROGRAMMES = [
    {"title": "Evening News", "start": "20260907190000", "end": "20260907200000",
     "description": "The day in review.", "channel_name": "Sky Mix"},
]


def test_channel_epg_context_menu_offers_schedule_recording(host, monkeypatch):
    scheduled = []
    channel = {"name": "Sky Mix"}
    dlg = ChannelEPGDialog(host, "Sky Mix", _EPG_PROGRAMMES,
                           schedule_callback=lambda ch, prog: scheduled.append((ch, prog)),
                           channel=channel)
    try:
        captured = []
        _capture_menu(monkeypatch, dlg.list_ctrl, captured)
        dlg._show_context_menu()
        assert ("Schedule Recording", True) in captured

        dlg._on_schedule(None)
        assert scheduled == [(channel, _EPG_PROGRAMMES[0])]
    finally:
        dlg.Destroy()


def test_channel_epg_context_menu_is_inert_without_a_callback(host, monkeypatch):
    dlg = ChannelEPGDialog(host, "Sky Mix", _EPG_PROGRAMMES, schedule_callback=None)
    try:
        captured = []
        _capture_menu(monkeypatch, dlg.list_ctrl, captured)
        dlg._show_context_menu()
        assert ("Schedule Recording", False) in captured
    finally:
        dlg.Destroy()


def test_whats_on_now_context_menu_offers_play_and_schedule(host, monkeypatch):
    scheduled = []
    dlg = WhatsOnNowDialog(host, _EPG_PROGRAMMES,
                           schedule_callback=lambda prog: scheduled.append(prog))
    try:
        captured = []
        _capture_menu(monkeypatch, dlg.listbox, captured)
        dlg._show_context_menu()
        assert [label for label, _enabled in captured] == ["Play", "Schedule Recording"]

        dlg.listbox.Select(0)
        dlg._on_schedule(None)
        assert scheduled == [_EPG_PROGRAMMES[0]]
    finally:
        dlg.Destroy()


# --------------------------------------------------------------------------- #
# The source managers open on the list, not on the first button
# --------------------------------------------------------------------------- #
def test_source_managers_focus_their_list_on_open(host, monkeypatch):
    focused = []
    monkeypatch.setattr(SourceNamesMixin, "_focus_source_list",
                        lambda self: focused.append(type(self).__name__))

    dlg = PlaylistManagerDialog(host, ["http://example.invalid/a.m3u"])
    dlg.Destroy()
    dlg = EPGManagerDialog(host, ["http://example.invalid/epg.xml"])
    dlg.Destroy()

    assert focused == ["PlaylistManagerDialog", "EPGManagerDialog"]


def test_focus_source_list_selects_the_first_row(wx_app):
    calls = []
    listbox = types.SimpleNamespace(
        GetCount=lambda: 3,
        GetSelection=lambda: wx.NOT_FOUND,
        SetSelection=lambda index: calls.append(("select", index)),
        SetFocus=lambda: calls.append(("focus", None)),
    )
    holder = types.SimpleNamespace(lb=listbox)
    SourceNamesMixin._focus_source_list(holder)
    # The immediate pass focuses; the CallAfter pass runs on the next idle.
    assert ("focus", None) in calls


# --------------------------------------------------------------------------- #
# The stream-URL field is optional
# --------------------------------------------------------------------------- #
def test_stream_url_field_can_be_hidden(host):
    ctrl = wx.TextCtrl(host, style=wx.TE_READONLY | wx.TE_MULTILINE)
    client = types.SimpleNamespace(url_display=ctrl, show_channel_url=False)
    IPTVClient._apply_channel_url_visibility(client)
    assert not ctrl.IsShown()

    client.show_channel_url = True
    IPTVClient._apply_channel_url_visibility(client)
    assert ctrl.IsShown()


def test_hidden_stream_url_field_lets_tab_wrap_by_normal_traversal():
    """Tab out of the channel list must be undoable with Shift+Tab.

    Shift+Tab from the search box goes to the categories tree, so sending Tab
    there put the user two controls away from the channel they left. With the
    URL field hidden the channel list is simply the last control: hand Tab to
    normal traversal, whose wrap to the playlist-scope combo is exactly what
    Shift+Tab from that combo reverses -- verified against NVDA, which
    announces the original row ("list item 2 of 5") on the way back.
    """
    focus = []
    navigations = []
    client = types.SimpleNamespace(
        show_channel_url=False,
        channel_list=types.SimpleNamespace(
            Navigate=lambda flags: navigations.append(flags)),
        url_display=types.SimpleNamespace(SetFocus=lambda: focus.append("url")),
        filter_box=types.SimpleNamespace(SetFocus=lambda: focus.append("search")),
        play_selected=lambda *a, **kw: None,
    )
    event = types.SimpleNamespace(
        GetKeyCode=lambda: wx.WXK_TAB,
        ShiftDown=lambda: False,
        Skip=lambda *a: None,
    )
    IPTVClient.on_channel_key(client, event)
    assert focus == []
    assert navigations == [
        wx.NavigationKeyEvent.IsForward | wx.NavigationKeyEvent.FromTab]

    navigations.clear()
    client.show_channel_url = True
    IPTVClient.on_channel_key(client, event)
    assert focus == ["url"]
    assert navigations == []


def test_shift_tab_from_channel_list_still_goes_to_search():
    focus = []
    client = types.SimpleNamespace(
        show_channel_url=False,
        filter_box=types.SimpleNamespace(SetFocus=lambda: focus.append("search")),
        play_selected=lambda *a, **kw: None,
    )
    event = types.SimpleNamespace(
        GetKeyCode=lambda: wx.WXK_TAB,
        ShiftDown=lambda: True,
        Skip=lambda *a: None,
    )
    IPTVClient.on_channel_key(client, event)
    assert focus == ["search"]


# --------------------------------------------------------------------------- #
# Record from the built-in player
# --------------------------------------------------------------------------- #
def _player_client(**overrides):
    recorded = []
    client = types.SimpleNamespace(
        _internal_player_channel={"name": "Sky Mix"},
        _internal_player_stream_kind="live",
        _record_channel=lambda channel: recorded.append(channel),
        _sync_internal_player_record_state=lambda: recorded.append("sync"),
    )
    for key, value in overrides.items():
        setattr(client, key, value)
    return client, recorded


def test_player_record_button_records_the_playing_channel(monkeypatch):
    monkeypatch.setattr(appmod.wx, "MessageBox", lambda *a, **kw: wx.OK)
    client, recorded = _player_client()
    IPTVClient._record_from_internal_player(client)
    assert recorded == [{"name": "Sky Mix"}, "sync"]


def test_player_record_button_needs_something_playing(monkeypatch):
    shown = []
    monkeypatch.setattr(appmod.wx, "MessageBox", lambda *a, **kw: shown.append(a) or wx.OK)
    client, recorded = _player_client(_internal_player_channel=None)
    IPTVClient._record_from_internal_player(client)
    assert recorded == []
    assert len(shown) == 1


def test_player_record_button_refuses_catch_up(monkeypatch):
    shown = []
    monkeypatch.setattr(appmod.wx, "MessageBox", lambda *a, **kw: shown.append(a) or wx.OK)
    client, recorded = _player_client(_internal_player_stream_kind="catchup")
    IPTVClient._record_from_internal_player(client)
    assert recorded == []
    assert "catch-up" in shown[0][0]


def test_player_record_state_follows_the_recorder():
    states = []
    frame = types.SimpleNamespace(set_recording_state=lambda active: states.append(active))
    client = types.SimpleNamespace(
        _internal_player_frame=frame,
        _internal_player_channel={"name": "Sky Mix"},
        _channel_record_key=lambda _channel: "sky",
        recorder=types.SimpleNamespace(is_recording=lambda key: key == "sky"),
    )
    IPTVClient._sync_internal_player_record_state(client)
    assert states == [True]

    client.recorder = types.SimpleNamespace(is_recording=lambda _key: False)
    IPTVClient._sync_internal_player_record_state(client)
    assert states == [True, False]


def test_player_record_state_is_a_no_op_without_a_player():
    client = types.SimpleNamespace(_internal_player_frame=None)
    IPTVClient._sync_internal_player_record_state(client)  # must not raise


# --------------------------------------------------------------------------- #
# The update flow asks once and then gets on with it
# --------------------------------------------------------------------------- #
def _update_client(**overrides):
    """An IPTVClient stand-in carrying only the update-flow state."""
    client = types.SimpleNamespace(
        _update_progress_dlg=None,
        _update_in_progress=True,
        _update_install_pending=False,
        closed=[],
        boxes=[],
        Close=lambda: client.closed.append(True),
    )
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


def test_install_handoff_reuses_the_progress_dialog_instead_of_a_new_box():
    """No click stands between the download finishing and the install starting.

    The old flow put a modal "the update is installing" box here, which had to
    be read and dismissed inside the 30 seconds update_helper.ps1 waits before
    it kills this process.
    """
    pulses = []
    client = _update_client(
        _update_progress_dlg=types.SimpleNamespace(
            Pulse=lambda msg: pulses.append(msg)))
    appmod.IPTVClient._show_update_installing_progress(client)
    assert len(pulses) == 1
    # It still says the app will come back by itself, and that opening it by
    # hand mid-install fails - just without demanding a keypress to say so.
    assert "close and start again by itself" in pulses[0]
    assert "do not open it yourself" in pulses[0]
    assert not hasattr(appmod.IPTVClient, "_warn_update_is_installing")


def test_install_handoff_survives_a_missing_progress_dialog():
    client = _update_client(_update_progress_dlg=None)
    appmod.IPTVClient._show_update_installing_progress(client)  # must not raise


def test_close_for_update_install_lingers_before_quitting(monkeypatch):
    """The message needs to be on screen long enough for NVDA to speak it,
    and the app still has to quit well inside the helper's 30s window."""
    scheduled = []
    monkeypatch.setattr(
        appmod.wx, "CallLater",
        lambda ms, fn: scheduled.append((ms, fn)))
    handoffs = []
    client = _update_client(_finish_update_handoff=lambda: handoffs.append(True))
    appmod.IPTVClient._close_for_update_install(client)

    assert len(scheduled) == 1
    delay, callback = scheduled[0]
    assert delay == appmod._UPDATE_HANDOFF_LINGER_MS
    assert 0 < delay < 30_000, "must quit before update_helper.ps1 kills us"
    assert not client.closed, "closing before the linger would hide the message"

    callback()
    assert handoffs == [True]


def test_finish_update_handoff_keeps_the_gate_shut_then_closes():
    destroyed = []
    client = _update_client(
        _destroy_update_progress=lambda **kw: destroyed.append(kw))
    appmod.IPTVClient._finish_update_handoff(client)
    # end_flow=False: the update carries on in the helper after we are gone, so
    # a queued prompt must not be able to start a second one.
    assert destroyed == [{"end_flow": False}]
    assert client.closed == [True]


def test_finished_update_is_silent_on_success_and_loud_on_failure(monkeypatch, tmp_path):
    boxes = []
    monkeypatch.setattr(appmod, "message_box",
                        lambda *a, **kw: boxes.append(a[1] if len(a) > 1 else ""))
    monkeypatch.setattr(appmod, "get_user_config_dir", lambda create=False: str(tmp_path))

    pending = {"version": appmod.app_meta.APP_VERSION}
    monkeypatch.setattr(appmod.updater, "read_update_pending", lambda _d: dict(pending))
    monkeypatch.setattr(appmod.updater, "clear_update_pending", lambda _d: None)

    # Came back on the version we were aiming for: nothing to say.
    appmod.IPTVClient._report_finished_update(types.SimpleNamespace())
    assert boxes == []

    # Came back on the old version: the install did not land, so say so.
    pending["version"] = "9999.0.0"
    appmod.IPTVClient._report_finished_update(types.SimpleNamespace())
    assert len(boxes) == 1
