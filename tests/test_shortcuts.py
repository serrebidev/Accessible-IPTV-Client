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
