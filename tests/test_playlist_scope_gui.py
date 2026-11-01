"""Scope activation and traversal through real main-window wx controls."""

import pytest
import wx
from unittest.mock import patch

import main
from client_m3u import M3uCacheMixin
from tools.playlist_benchmark import build_playlist_text, group_channels
from tools.smoke_favorites_shutdown import CONFIG


def _key(control, code, *, shift=False):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(code)
    event.SetShiftDown(shift)
    control.GetEventHandler().ProcessEvent(event)
    return event


@pytest.fixture
def scope_frame(monkeypatch):
    app = wx.GetApp() or wx.App()
    saves = []
    config = {**CONFIG, "playlist_scope": "p1"}
    monkeypatch.setattr(main, "load_config", lambda: config.copy())
    monkeypatch.setattr(main, "save_config", lambda value: saves.append(value["playlist_scope"]))
    monkeypatch.setattr(main.IPTVClient, "_run_deferred_startup_tasks", lambda self: None)
    frame = main.IPTVClient()
    frame.Show()
    app.Yield()
    frame.playlist_sources = [{"id": "p1", "name": "One"}, {"id": "p2", "name": "Two"}]
    frame.all_channels = [
        {"name": "One", "group": "First", "playlist-id": "p1"},
        {"name": "Two", "group": "Second", "playlist-id": "p2"},
    ]
    frame.channels_by_group = {"First": frame.all_channels[:1], "Second": frame.all_channels[1:]}
    frame._fill_playlist_scope_combo()
    frame._refresh_group_ui()
    frame.playlist_scope_combo.SetFocus()
    app.Yield()
    yield frame, saves, app
    frame._exit_forced = True
    frame.Destroy()
    app.Yield()


def test_enter_commits_once_and_keeps_combo_focus(scope_frame):
    frame, saves, app = scope_frame
    combo = frame.playlist_scope_combo
    combo.SetSelection(2)

    _key(combo, wx.WXK_RETURN)
    _key(combo, wx.WXK_RETURN)
    app.Yield()

    assert frame.playlist_scope == "p2"
    assert saves == ["p2"]
    assert wx.Window.FindFocus() is combo
    assert frame._group_keys == ["All Channels", "Second"]
    assert frame.channel_list.GetCount() == 1


def test_enter_empty_playlist_keeps_combo_focus(scope_frame):
    frame, saves, app = scope_frame
    combo = frame.playlist_scope_combo
    frame.all_channels = frame.all_channels[:1]
    frame.channels_by_group = {"First": frame.all_channels}
    combo.SetSelection(2)

    _key(combo, wx.WXK_RETURN)
    app.Yield()

    assert frame.playlist_scope == "p2"
    assert saves == ["p2"]
    assert frame.channel_list.GetCount() == 0
    assert wx.Window.FindFocus() is combo


def test_mouse_choice_commits_once_and_keeps_combo_focus(scope_frame):
    frame, saves, app = scope_frame
    combo = frame.playlist_scope_combo
    combo.SetSelection(2)
    combo.SetFocus()
    combo.GetEventHandler().ProcessEvent(wx.MouseEvent(wx.wxEVT_LEFT_DOWN))
    choice = wx.CommandEvent(wx.wxEVT_CHOICE, combo.GetId())
    combo.GetEventHandler().ProcessEvent(choice)
    combo.GetEventHandler().ProcessEvent(choice)
    app.Yield()

    assert frame.playlist_scope == "p2"
    assert saves == ["p2"]
    assert wx.Window.FindFocus() is combo


def test_tab_traverses_before_refresh_and_focus_stays_on_categories(scope_frame):
    frame, saves, app = scope_frame
    combo = frame.playlist_scope_combo
    combo.SetSelection(2)

    event = _key(combo, wx.WXK_TAB)
    assert event.GetSkipped()
    assert saves == []
    assert frame.playlist_scope == "p1"
    combo.Navigate(wx.NavigationKeyEvent.IsForward)
    assert wx.Window.FindFocus() is frame.group_list

    app.Yield()
    assert frame.playlist_scope == "p2"
    assert saves == ["p2"]
    assert wx.Window.FindFocus() is frame.group_list
    assert frame._group_keys == ["All Channels", "Second"]
    assert frame.channel_list.GetCount() == 1


def test_shift_tab_leaves_preview_and_traverses_back(scope_frame):
    frame, saves, app = scope_frame
    combo = frame.playlist_scope_combo
    combo.SetSelection(2)

    event = _key(combo, wx.WXK_TAB, shift=True)
    assert event.GetSkipped()
    combo.Navigate(wx.NavigationKeyEvent.IsBackward)
    app.Yield()

    assert frame.playlist_scope == "p1"
    assert saves == []
    assert wx.Window.FindFocus() is not combo


def test_escape_restores_active_choice_without_refresh(scope_frame):
    frame, saves, app = scope_frame
    combo = frame.playlist_scope_combo
    combo.SetSelection(2)

    _key(combo, wx.WXK_ESCAPE)
    app.Yield()

    assert combo.GetSelection() == 1
    assert frame.playlist_scope == "p1"
    assert saves == []
    assert wx.Window.FindFocus() is combo


def test_large_playlist_arrow_previews_do_no_scope_work_until_enter(scope_frame):
    frame, saves, app = scope_frame
    channels = M3uCacheMixin()._parse_m3u_return(build_playlist_text(100_000))
    assert len(channels) == 100_000
    for index, channel in enumerate(channels):
        channel["playlist-id"] = "p1" if index % 2 == 0 else "p2"
    frame.all_channels = channels
    frame.channels_by_group = group_channels(channels)
    frame._invalidate_playlist_index()
    combo = frame.playlist_scope_combo

    # EVT_CHOICE follows each native arrow selection. Neither that event nor
    # the matching key hook may rebuild the 100k-channel scope or save it.
    with (patch.object(frame, "_refresh_group_ui", wraps=frame._refresh_group_ui) as refresh,
          patch.object(frame, "scoped_all_channels", wraps=frame.scoped_all_channels) as scoped_all,
          patch.object(frame, "scoped_channels_by_group", wraps=frame.scoped_channels_by_group) as scoped_groups):
        for selection in (2, 0, 1, 2) * 3:
            _key(combo, wx.WXK_DOWN)
            combo.SetSelection(selection)
            choice = wx.CommandEvent(wx.wxEVT_CHOICE, combo.GetId())
            combo.GetEventHandler().ProcessEvent(choice)
        app.Yield()

        assert saves == []
        assert refresh.call_count == scoped_all.call_count == scoped_groups.call_count == 0
        assert frame.playlist_scope == frame.config["playlist_scope"] == "p1"
        assert wx.Window.FindFocus() is combo

        _key(combo, wx.WXK_RETURN)
        _key(combo, wx.WXK_RETURN)
        app.Yield()

        assert saves == ["p2"]
        assert refresh.call_count == 1
        assert scoped_all.call_count >= 1
        assert scoped_groups.call_count >= 1
        assert frame.playlist_scope == frame.config["playlist_scope"] == "p2"
        assert frame.channel_list.GetCount() == 50_000
        assert wx.Window.FindFocus() is combo
