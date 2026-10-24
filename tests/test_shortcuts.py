import pytest
import wx

import shortcuts


def test_shortcut_override_replaces_default_and_rejects_conflicts():
    config = {}
    shortcuts.set_shortcut(config, "main", "previous_channel", "Ctrl+Shift+0")
    entries = shortcuts.main_entries(config)
    assert (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("0"), 4022) in entries
    assert (wx.ACCEL_CTRL, ord("0"), 4022) not in entries
    with pytest.raises(ValueError, match="conflicts with Previous Channel"):
        shortcuts.set_shortcut(config, "main", "channel_number", "Ctrl+Shift+0")
    with pytest.raises(ValueError, match="Ctrl or Alt"):
        shortcuts.set_shortcut(config, "main", "channel_number", "G")


def test_every_command_has_a_conflict_label():
    assert shortcuts.LABELS["main"].keys() == shortcuts.MAIN.keys()
    assert shortcuts.LABELS["player"].keys() == shortcuts.PLAYER.keys()


def test_a_hand_edited_config_cannot_install_a_bare_main_shortcut():
    """The config file is the user's, and a hand-edited entry is read too.

    A main-window shortcut without Ctrl or Alt would swallow ordinary typing
    in the search box, and F1 is the help key. Both fall back to the default.
    """
    config = {"shortcuts": {"main.favorite": "F", "main.exit": "F1"}}

    entries = shortcuts.main_entries(config)

    assert (wx.ACCEL_CTRL, ord("D"), 4019) in entries  # the default Ctrl+D
    assert not [e for e in entries if e[1] == ord("F") and not e[0]]
    assert (wx.ACCEL_CTRL, ord("Q"), 4004) in entries  # the default Ctrl+Q
    assert not [e for e in entries if e[1] == wx.WXK_F1]


def test_a_player_shortcut_may_stay_bare():
    """The player's own keys are single keys on purpose."""
    config = {"shortcuts": {"player.audio_track": "A"}}

    assert shortcuts.effective(config, "player")["audio_track"] == "A"
