"""Real wx controls must stay reachable and reflect failed playback."""
import types
from concurrent.futures import Future

import pytest
import wx

import internal_player
import main as appmod
from internal_player import InternalPlayerFrame


@pytest.fixture
def player_frame():
    app = wx.GetApp() or wx.App()
    frame = InternalPlayerFrame(None)
    frame.Show()
    app.Yield()
    frame._notify_box = lambda *args: None
    yield frame
    frame.Destroy()
    app.Yield()


def test_tab_skips_disabled_and_hidden_controls(player_frame):
    frame = player_frame
    frame._current_url = "https://example.invalid/stream"
    frame._update_status_label("Opening")
    frame.play_pause_btn.SetFocus()
    frame._focus_control_step(False)
    assert wx.Window.FindFocus() is frame.volume_slider
    frame.record_btn.Hide()
    frame.stop_btn.SetFocus()
    frame._focus_control_step(True)
    assert wx.Window.FindFocus() is frame.cast_btn


def test_tab_from_slider_stays_in_named_controls(player_frame):
    frame = player_frame
    frame._current_url = "https://example.invalid/stream"
    frame._update_status_label("Opening")
    frame.volume_slider.SetFocus()
    event = types.SimpleNamespace(
        GetKeyCode=lambda: wx.WXK_TAB, ControlDown=lambda: False,
        AltDown=lambda: False, ShiftDown=lambda: False, Skip=lambda: None)
    frame._on_key_down(event)
    assert wx.Window.FindFocus() is frame.play_pause_btn


@pytest.mark.parametrize("fast_refresh", [False, True])
def test_failed_connection_disables_buttons_menus_and_pause_shortcut(player_frame, fast_refresh):
    frame = player_frame
    frame._current_url = frame._last_resolved_url = "https://example.invalid/live/user/pass/123.ts"
    frame._current_stream_kind = "live"
    frame._has_seen_playing = True
    frame._xtream_refresh_count = frame._max_xtream_refreshes
    frame._reconnect_attempts = frame._max_reconnect_attempts
    frame._update_status_label("Playing")
    frame.play_pause_btn.SetFocus()
    if fast_refresh:
        frame._restart_expected_xtream_live()
    else:
        frame._schedule_restart("playback error")
    assert not frame.play_pause_btn.IsEnabled()
    assert not frame.stop_btn.IsEnabled()
    items = frame.GetMenuBar().GetMenu(0).GetMenuItems()
    assert not items[0].IsEnabled()
    assert not items[1].IsEnabled()
    assert wx.Window.FindFocus() is frame.record_btn
    calls = []
    frame._vlc_call = calls.append
    frame._on_toggle_pause()
    assert calls == []


def test_manual_stop_keeps_play_available_but_disables_stop(player_frame):
    frame = player_frame
    frame._current_url = frame._last_resolved_url = "https://example.invalid/stream"
    frame.stop(manual=True)
    assert frame.play_pause_btn.IsEnabled()
    assert frame.play_pause_btn.GetLabel() == "Play"
    assert not frame.stop_btn.IsEnabled()


def test_pause_toggle_updates_accessible_name_while_switching_and_playing(player_frame):
    frame = player_frame
    frame._current_url = "https://example.invalid/stream"
    frame._vlc_switch = Future()
    frame._vlc_call = lambda _call: None
    frame._on_toggle_pause()
    assert frame.play_pause_btn.GetLabel() == frame.play_pause_btn.GetName() == "Resume"
    frame._on_toggle_pause()
    assert frame.play_pause_btn.GetLabel() == frame.play_pause_btn.GetName() == "Pause"

    frame._vlc_switch = None
    frame.player = types.SimpleNamespace(get_state=lambda: None, pause=lambda: None)
    frame._on_toggle_pause()
    assert frame.play_pause_btn.GetLabel() == frame.play_pause_btn.GetName() == "Resume"


@pytest.mark.parametrize("manual_stop", [False, True])
def test_resume_paths_update_accessible_name_immediately(player_frame, manual_stop):
    frame = player_frame
    frame._current_url = "https://example.invalid/stream"
    frame._manual_stop = manual_stop
    frame.player = types.SimpleNamespace(
        get_state=lambda: internal_player.vlc.State.Stopped, play=lambda: None)
    frame.play = lambda *_args, **_kwargs: None
    frame._vlc_call = lambda _call: None
    frame._update_status_label = lambda *_args: None
    frame.play_pause_btn.SetName("old name")
    frame._on_toggle_pause()
    assert frame.play_pause_btn.GetLabel() == frame.play_pause_btn.GetName() == "Pause"


@pytest.mark.parametrize("queued", [False, True])
def test_cast_callback_failure_uses_player_modal_and_restores_focus(monkeypatch, caplog, queued):
    app = wx.GetApp() or wx.App()
    host = wx.Frame(None, title="main window")
    for name in ("_deferred_notifications", "_modal_box_is_open",
                 "_show_or_queue_message_box", "_show_message_box",
                 "_drain_deferred_notifications"):
        setattr(host, name, getattr(appmod.IPTVClient, name).__get__(host))
    host.frame = host
    host._DEFERRED_NOTIFICATION_LIMIT = 8
    host._modal_box_depth = int(queued)
    host.Show()
    frame = InternalPlayerFrame(host)
    frame.Show()
    app.Yield()
    url = "https://example.invalid/live/user/password/123.ts"
    shown = []

    def fake_box(message, caption, style, *, parent):
        shown.append((message, caption, style, parent))
        host.Raise()
        host.SetFocus()
        return wx.OK

    monkeypatch.setattr(appmod, "message_box", fake_box)
    try:
        frame._current_url = url
        frame._on_cast_cb = lambda *_args: (_ for _ in ()).throw(RuntimeError(url))
        frame.cast_btn.SetFocus()
        frame._on_cast()
        if queued:
            assert shown == []
            host._modal_box_depth = 0
            host._drain_deferred_notifications()
        assert shown == [("Casting Error", "Casting", wx.OK | wx.ICON_ERROR, frame)]
        assert url not in str(shown)
        assert "Cast callback failed: RuntimeError" in caplog.text
        assert url not in caplog.text
        assert wx.Window.FindFocus() is frame.cast_btn
    finally:
        frame.Destroy()
        host.Destroy()
        app.Yield()
