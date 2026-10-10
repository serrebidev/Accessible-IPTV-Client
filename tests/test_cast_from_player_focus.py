"""A failed cast from the built-in player must leave the player usable."""

import types

import main


def test_failed_cast_keeps_focus_in_the_player(monkeypatch):
    focused, shown = [], []
    player = types.SimpleNamespace(
        IsShown=lambda: True, Raise=lambda: None,
        cast_btn=types.SimpleNamespace(SetFocus=lambda: focused.append(True)))
    device = types.SimpleNamespace(display_name="RB Room")

    class FailingCaster:
        def is_connected(self):
            return False

        def connect(self, _device):
            pass

        def play(self, *_a, **_k):
            raise RuntimeError("no answer")

    class Dialog:
        def __init__(self, parent, _caster):
            shown.append(("devices", parent))

        def ShowModal(self):
            return main.wx.ID_OK

        def get_selected_device(self):
            return device

        def Destroy(self):
            pass

    class SyncThread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(main, "CastDiscoveryDialog", Dialog)
    monkeypatch.setattr(main.threading, "Thread", SyncThread)
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a: fn(*a))
    monkeypatch.setattr(main, "message_box", lambda *a: shown.append(("box", a[-1])))
    client = types.SimpleNamespace(_internal_player_frame=player,
                                   _ensure_caster=FailingCaster)

    main.IPTVClient._cast_from_internal_player(client, "http://h/live.ts", "News", {})

    assert shown == [("devices", player), ("box", player)]
    assert focused == [True]
