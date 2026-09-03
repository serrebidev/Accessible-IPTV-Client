"""Smoke-test the wx wiring that pytest cannot reach.

The favorites category, the preferred-audio-track dialog and the shutdown countdown
are mostly logic that ``tests/test_favorites.py``, ``tests/test_audio_preference.py``
and ``tests/test_power.py`` cover headlessly. What they cannot cover is the wx side:
that the menu items really exist, that a virtual list row re-fires focus (which is the
only feedback a screen reader gets when a favorite is toggled), and that the built-in
player accepts the preference arguments.

Config load/save and the deferred startup work are stubbed, so this touches neither
the user's iptvclient.conf nor the network.

Run: python tools/smoke_favorites_shutdown.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx

import favorites
import main

SAVED = {}
CONFIG = {
    "playlists": [], "epgs": [], "media_player": "Built-in Player", "custom_player_path": "",
    "minimize_to_tray": False, "auto_check_updates": False, "epg_enabled": False,
    "show_player_on_enter": True, "language": "en", "recordings_dir": tempfile.gettempdir(),
    "recording_format": "provider_mkv", "recording_pre_padding_minutes": 0,
    "recording_post_padding_minutes": 2, "favorites": [], "preferred_audio_tracks": [],
    "prefer_audio_description": False, "shutdown_after_recordings": False,
    "internal_player_buffer_seconds": 2.0, "internal_player_max_buffer_seconds": 18.0,
    "internal_player_variant_max_mbps": 0.0,
}

CHANNELS = [
    {"name": "BBC One", "group": "UK", "tvg-id": "bbc1.uk"},
    {"name": "Sky News", "group": "UK"},
    {"name": "CNN", "group": "US"},
]


def build_frame():
    main.load_config = lambda: dict(CONFIG)
    main.save_config = lambda cfg: SAVED.update(cfg)
    main.IPTVClient._run_deferred_startup_tasks = lambda self: None
    frame = main.IPTVClient()
    frame.all_channels = CHANNELS
    frame.channels_by_group = {"UK": CHANNELS[:2], "US": CHANNELS[2:]}
    frame._invalidate_favorites_cache()
    frame._refresh_group_ui()
    assert frame._group_keys == ["All Channels", "UK", "US"], frame._group_keys
    return frame


def test_menus(frame):
    labels = []
    menu_bar = frame.GetMenuBar()
    if menu_bar is None:
        print("menus: skipped (this platform uses the button menu)")
        return
    for index in range(menu_bar.GetMenuCount()):
        for item in menu_bar.GetMenu(index).GetMenuItems():
            labels.append(item.GetItemLabelText())
    for wanted in ("Add to Favorites", "Go to Favorites", "Preferred Audio Track...",
                   "Shut Down the Computer When Recordings Finish"):
        assert any(wanted in label for label in labels), (wanted, labels)
    print("menus: OK")


def test_favorites(frame):
    frame.current_group = "All Channels"
    frame._populate_channel_list_chunked(CHANNELS)
    frame.channel_list.SetSelection(0)
    assert frame.channel_list.OnGetItemText(0, 0) == "BBC One"

    frame._toggle_favorite_selected()
    assert SAVED["favorites"] == ["bbc1.uk|BBC One"], SAVED["favorites"]
    assert frame._group_keys == ["All Channels", favorites.FAVORITES_GROUP, "UK", "US"]
    assert frame.group_list.GetString(1).startswith("Favorites (1)"), frame.group_list.GetString(1)
    # The row text carries the marker and the row still holds focus, which is what
    # makes NVDA read the change back to the user.
    assert frame.channel_list.OnGetItemText(0, 0) == "BBC One (Favorite)"
    assert frame.channel_list.GetFocusedItem() == 0
    assert frame.favorite_menu_item.GetItemLabelText().startswith("Remove from Favorites")

    frame._go_to_favorites()
    assert frame.current_group == favorites.FAVORITES_GROUP, frame.current_group
    assert frame.channel_list.GetItemCount() == 1
    assert frame.channel_list.OnGetItemText(0, 0) == "BBC One", "marker not suppressed in Favorites"

    frame.channel_list.SetSelection(0)
    frame._toggle_favorite(CHANNELS[0])
    assert SAVED["favorites"] == []
    assert favorites.FAVORITES_GROUP not in frame._group_keys, frame._group_keys
    assert frame.current_group == "All Channels", frame.current_group
    print("favorites: OK")


def test_shutdown_arming(frame):
    frame._set_shutdown_after_recordings(True)
    assert SAVED["shutdown_after_recordings"] is True
    assert frame._recorded_since_shutdown_armed is False, "armed with nothing to wait for"
    frame._maybe_shutdown_after_recordings()
    assert frame._shutdown_dialog is None, "would have powered off with nothing recorded"

    frame._note_recording_started()
    frame._maybe_shutdown_after_recordings()
    assert frame._shutdown_dialog is not None, "did not start the countdown"
    frame._shutdown_dialog._stop_timer()
    frame._destroy_shutdown_dialog()
    frame._set_shutdown_after_recordings(False)
    assert SAVED["shutdown_after_recordings"] is False
    print("shutdown arming: OK")


def test_audio_preference_dialog(parent):
    dlg = main.AudioTrackPreferenceDialog(parent, keywords=["English AD", "English"],
                                          prefer_audio_description=True)
    assert dlg.get_prefer_audio_description() is True
    assert dlg.get_keywords() == ["English AD", "English"], dlg.get_keywords()
    dlg.keywords_txt.SetValue(" audio description ,, English , English ")
    assert dlg.get_keywords() == ["audio description", "English"], dlg.get_keywords()
    assert dlg.keywords_txt.GetName(), "the text field has no accessible name"
    dlg.Destroy()
    print("audio preference dialog: OK")


def test_shutdown_countdown():
    fired = []
    dlg = main.ShutdownCountdownDialog(None, on_cancel=lambda: fired.append("cancel"),
                                       on_shutdown=lambda: fired.append("shutdown"), seconds=3)
    assert "3" in dlg.message.GetLabel(), dlg.message.GetLabel()
    dlg._on_tick(None)
    assert "2" in dlg.message.GetLabel(), dlg.message.GetLabel()
    dlg._on_tick(None)
    dlg._on_tick(None)
    assert fired == ["shutdown"], fired
    dlg._cancel()  # a late cancel after it has fired must change nothing
    assert fired == ["shutdown"], fired
    dlg.Destroy()

    fired = []
    dlg = main.ShutdownCountdownDialog(None, on_cancel=lambda: fired.append("cancel"),
                                       on_shutdown=lambda: fired.append("shutdown"), seconds=60)
    dlg._cancel()
    dlg._on_tick(None)  # a tick queued before the cancel must not power anything off
    assert fired == ["cancel"], fired
    dlg.Destroy()
    print("shutdown countdown: OK")


def test_player_preference(parent):
    try:
        frame_cls = main._load_internal_player_frame_class()
    except Exception as err:
        print("built-in player: skipped (%s)" % err)
        return
    saved = []
    player = frame_cls(parent, preferred_audio_tracks=["English AD"],
                       prefer_audio_description=True,
                       on_audio_preference=saved.append)
    try:
        assert player._preferred_audio_keywords()[0] == "English AD"
        player.set_preferred_audio_tracks(["Deutsch"], prefer_audio_description=False)
        assert player._preferred_audio_keywords() == ["Deutsch"]
        assert player._audio_preference_pending is True
        # A track the user chose by hand outranks a preference change.
        player._wanted_audio_track_name = "English"
        player._audio_preference_pending = False
        player.set_preferred_audio_tracks(["Francais"])
        assert player._audio_preference_pending is False
        # Rebuilding the submenu with no media loaded must not raise.
        player._on_audio_track_menu_open(None)
        items = [i.GetItemLabelText() for i in player.audio_track_menu.GetMenuItems()]
        assert items == ["No audio tracks available"], items
    finally:
        player._allow_close = True
        player.Destroy()
    print("built-in player: OK")


if __name__ == "__main__":
    app = wx.App()
    parent = wx.Frame(None)
    frame = build_frame()
    test_menus(frame)
    test_favorites(frame)
    test_shutdown_arming(frame)
    test_audio_preference_dialog(parent)
    test_shutdown_countdown()
    test_player_preference(parent)
    frame._exit_forced = True
    frame.Destroy()
    parent.Destroy()
    print("ALL SMOKE TESTS PASSED")
