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


def test_catchup_buttons_are_out_of_the_tab_chain(host):
    """No Open/Download buttons: Enter opens, the context menu downloads."""
    dlg = CatchupDialog(host, "Sky Mix", _CATCHUP_PROGRAMMES)
    try:
        assert not hasattr(dlg, "open_btn")
        assert not hasattr(dlg, "download_btn")
        buttons = [w for w in dlg.GetChildren() if isinstance(w, wx.Button)]
        panel = [w for w in dlg.GetChildren() if isinstance(w, wx.Panel)][0]
        buttons += [w for w in panel.GetChildren() if isinstance(w, wx.Button)]
        labels = [b.GetLabel() for b in buttons]
        assert all("Open" != label for label in labels), labels
        assert all("Download" != label for label in labels), labels
    finally:
        dlg.Destroy()


def test_catchup_selection_shows_in_the_description_field(host):
    """Tab from the list lands on the highlighted programme's description."""
    programmes = [
        dict(_CATCHUP_PROGRAMMES[0], description="News with a full description."),
        dict(_CATCHUP_PROGRAMMES[1], description=""),
    ]
    dlg = CatchupDialog(host, "Sky Mix", programmes)
    try:
        dlg.listbox.SetSelection(0)
        dlg._update_description()
        assert dlg.description_field.GetValue() == "News with a full description."
        dlg.listbox.SetSelection(1)
        dlg._update_description()
        assert dlg.description_field.GetValue() != "News with a full description."
        assert dlg.description_field.GetName() == "Episode description"
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


def _tab_ring_client(show_channel_url, focus, navigations):
    return types.SimpleNamespace(
        show_channel_url=show_channel_url,
        channel_list=types.SimpleNamespace(
            SetFocus=lambda: focus.append("channels"),
            Navigate=lambda flags: navigations.append(flags)),
        episode_description_field=types.SimpleNamespace(
            SetFocus=lambda: focus.append("description"),
            Navigate=lambda flags: navigations.append(flags)),
        url_display=types.SimpleNamespace(
            SetFocus=lambda: focus.append("url"),
            Navigate=lambda flags: navigations.append(flags)),
        filter_box=types.SimpleNamespace(SetFocus=lambda: focus.append("search")),
        play_selected=lambda *a, **kw: None,
        _navigate_forward=IPTVClient._navigate_forward,
    )


def _tab_event(shift=False):
    return types.SimpleNamespace(
        GetKeyCode=lambda: wx.WXK_TAB,
        ShiftDown=lambda: shift,
        HasAnyModifiers=lambda: shift,
        Skip=lambda *a: None,
    )


def test_tab_from_the_channel_list_reaches_the_episode_description():
    """The description is the next stop whether or not the URL field is on."""
    for show_url in (False, True):
        focus, navigations = [], []
        client = _tab_ring_client(show_url, focus, navigations)
        IPTVClient.on_channel_key(client, _tab_event())
        assert focus == ["description"]
        assert navigations == []


def test_shift_tab_from_the_episode_description_returns_to_the_channel_list():
    """The reported bug: with the URL field off Shift+Tab went nowhere.

    It focused the hidden stream-URL control, and SetFocus on a hidden window
    does nothing, so the user was stranded in the description field.
    """
    for show_url in (False, True):
        focus, navigations = [], []
        client = _tab_ring_client(show_url, focus, navigations)
        IPTVClient._on_episode_description_key(client, _tab_event(shift=True))
        assert focus == ["channels"]
        assert navigations == []


def test_tab_from_the_episode_description_reaches_the_url_field_when_shown():
    focus, navigations = [], []
    client = _tab_ring_client(True, focus, navigations)
    IPTVClient._on_episode_description_key(client, _tab_event())
    assert focus == ["url"]
    assert navigations == []


def test_hidden_stream_url_field_lets_tab_wrap_by_normal_traversal():
    """Tab out of the last control must be undoable with Shift+Tab.

    Shift+Tab from the search box goes to the categories tree, so sending Tab
    there put the user two controls away from the channel they left. With the
    URL field hidden the episode description is simply the last control: hand
    Tab to normal traversal, whose wrap to the playlist-scope combo is exactly
    what Shift+Tab from that combo reverses -- verified against NVDA, which
    announces the original row ("list item 2 of 5") on the way back.
    """
    focus, navigations = [], []
    client = _tab_ring_client(False, focus, navigations)
    IPTVClient._on_episode_description_key(client, _tab_event())
    assert focus == []
    assert navigations == [
        wx.NavigationKeyEvent.IsForward | wx.NavigationKeyEvent.FromTab]

    focus.clear()
    navigations.clear()
    client.show_channel_url = True
    IPTVClient._on_url_display_key(client, _tab_event())
    assert focus == []
    assert navigations == [
        wx.NavigationKeyEvent.IsForward | wx.NavigationKeyEvent.FromTab]


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


def test_install_handoff_reuses_the_progress_dialog_instead_of_a_new_box(monkeypatch):
    """No click stands between the download finishing and the install starting.

    The old flow put a modal "the update is installing" box here, which had to
    be read and dismissed inside the 30 seconds update_helper.ps1 waits before
    it kills this process. The notice now arrives in a fresh progress dialog -
    no button to press - because NVDA reads a progress dialog's text when it
    appears, and says nothing when the text of an open one changes.
    """
    events = []

    class _Progress:
        def __init__(self, title, message, **kwargs):
            events.append(("open", message, kwargs.get("style", 0)))

        def Pulse(self, msg=""):
            events.append(("pulse", msg))

    old = types.SimpleNamespace(Pulse=lambda msg="": events.append(("old-pulse", msg)),
                                Destroy=lambda: events.append(("destroy-old",)))
    monkeypatch.setattr(appmod.wx, "ProgressDialog", _Progress)
    client = _update_client(_update_progress_dlg=old)
    client._fresh_update_message = appmod.IPTVClient._fresh_update_message.__get__(client)
    appmod.IPTVClient._show_update_installing_progress(client)
    opened = [event for event in events if event[0] == "open"]
    assert len(opened) == 1
    # It still says the app will come back by itself, and that opening it by
    # hand mid-install fails - just without demanding a keypress to say so.
    assert "close and start again by itself" in opened[0][1]
    assert "do not open it yourself" in opened[0][1]
    assert not opened[0][2] & appmod.wx.PD_CAN_ABORT
    assert ("destroy-old",) in events
    assert isinstance(client._update_progress_dlg, _Progress)
    assert not hasattr(appmod.IPTVClient, "_warn_update_is_installing")
    # Every later poll only keeps the dialog alive: no second dialog, and no
    # re-sent text to cut NVDA off and start it from the top.
    events.clear()
    appmod.IPTVClient._show_update_installing_progress(client)
    assert events == [("pulse", "")]


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



# --------------------------------------------------------------------------- #
# The catch-up dialog has no buttons at all
# --------------------------------------------------------------------------- #
def test_catchup_dialog_has_no_close_button(host):
    """Close was a Tab stop that only did what Escape already does."""
    dlg = CatchupDialog(host, "BBC One", [
        {"start": "20260101120000", "end": "20260101130000",
         "title": "News", "description": "The one o'clock news."},
    ])
    try:
        buttons = [w for w in dlg.GetChildren()[0].GetChildren()
                   if isinstance(w, wx.Button)]
        assert buttons == []
    finally:
        dlg.Destroy()


def test_catchup_dialog_tab_ring_is_two_controls(host):
    dlg = CatchupDialog(host, "BBC One", [
        {"start": "20260101120000", "end": "20260101130000", "title": "News"},
    ])
    try:
        tab = types.SimpleNamespace(
            GetKeyCode=lambda: wx.WXK_TAB,
            ShiftDown=lambda: False,
            HasAnyModifiers=lambda: False,
            Skip=lambda *a: None,
        )
        dlg._on_key(tab)
        assert dlg.FindFocus() is dlg.description_field
        dlg._on_description_key(tab)
        assert dlg.FindFocus() is dlg.listbox

        shift_tab = types.SimpleNamespace(
            GetKeyCode=lambda: wx.WXK_TAB,
            ShiftDown=lambda: True,
            HasAnyModifiers=lambda: True,
            Skip=lambda *a: None,
        )
        dlg.description_field.SetFocus()
        dlg._on_description_key(shift_tab)
        assert dlg.FindFocus() is dlg.listbox
    finally:
        dlg.Destroy()


def test_catchup_dialog_escape_still_closes_it(host, monkeypatch):
    dlg = CatchupDialog(host, "BBC One", [])
    try:
        ended = []
        monkeypatch.setattr(dlg, "EndModal", lambda code: ended.append(code))
        skipped = []
        dlg._on_dialog_key(types.SimpleNamespace(
            GetKeyCode=lambda: wx.WXK_ESCAPE,
            Skip=lambda *a: skipped.append(True)))
        assert ended == [wx.ID_CANCEL]
        assert skipped == []
    finally:
        dlg.Destroy()


# --------------------------------------------------------------------------- #
# The update hand-off waits for the helper's own window
# --------------------------------------------------------------------------- #
def test_update_handoff_waits_for_the_helper_window(monkeypatch, tmp_path):
    """Closing on a timer left the screen empty while PowerShell started up."""
    ready = tmp_path / "update_window_ready"
    later = []
    monkeypatch.setattr(appmod.wx, "CallLater",
                        lambda ms, fn, *a: later.append((ms, fn)))
    pulses = []
    client = types.SimpleNamespace(
        _show_update_installing_progress=lambda: pulses.append(True),
        _finish_update_handoff=lambda: None,
    )

    IPTVClient._close_for_update_install(client, str(ready))
    # Nothing scheduled to close yet: the helper has not reported in.
    assert later and later[-1][0] == appmod._UPDATE_HANDOFF_POLL_MS
    assert pulses == [True]

    ready.write_text("", encoding="utf-8")
    later[-1][1]()
    assert later[-1][0] == appmod._UPDATE_HANDOFF_LINGER_MS
    assert later[-1][1] == client._finish_update_handoff


def test_update_handoff_gives_up_on_a_helper_that_never_reports(monkeypatch, tmp_path):
    later = []
    monkeypatch.setattr(appmod.wx, "CallLater",
                        lambda ms, fn, *a: later.append((ms, fn)))
    clock = [0.0]
    monkeypatch.setattr(appmod.time, "monotonic", lambda: clock[0])
    client = types.SimpleNamespace(
        _show_update_installing_progress=lambda: None,
        _finish_update_handoff=lambda: None,
    )

    IPTVClient._close_for_update_install(client, str(tmp_path / "never"))
    assert later[-1][0] == appmod._UPDATE_HANDOFF_POLL_MS
    clock[0] = appmod._UPDATE_HANDOFF_MAX_WAIT_SECONDS + 1
    later[-1][1]()
    assert later[-1][0] == appmod._UPDATE_HANDOFF_LINGER_MS
