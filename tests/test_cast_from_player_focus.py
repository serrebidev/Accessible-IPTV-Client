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

        def disconnect(self):
            shown.append(("disconnected", None))

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

    # The failed cast's relay must not keep holding a one-stream provider.
    assert shown == [("devices", player), ("disconnected", None), ("box", player)]
    assert focused == [True]


def test_a_cast_failure_after_the_player_closed_does_not_raise(monkeypatch):
    """The player can be closed while the cast failure waits for its box.

    The failure box is raised from the GUI thread after the cast gave up, and
    by then the player frame may be gone. A destroyed wx object raises on
    every call, so the player has to be probed before it is used.
    """
    boxes = []
    player = types.SimpleNamespace(
        Raise=lambda: None,
        cast_btn=types.SimpleNamespace(SetFocus=lambda: None))
    calls = []

    def _is_shown():
        calls.append(1)
        if len(calls) == 1:
            # Alive when the cast started.
            return True
        # Destroyed before the failure box was raised.
        raise RuntimeError("wrapped C/C++ object of type Frame has been deleted")

    player.IsShown = _is_shown

    class FailingCaster:
        def is_connected(self):
            return False

        def connect(self, _device):
            pass

        def play(self, *_a, **_k):
            raise RuntimeError("no answer")

        def disconnect(self):
            pass

    class Dialog:
        def __init__(self, parent, _caster):
            pass

        def ShowModal(self):
            return main.wx.ID_OK

        def get_selected_device(self):
            return types.SimpleNamespace(display_name="RB Room")

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
    monkeypatch.setattr(main, "message_box", lambda *a: boxes.append(a))
    client = types.SimpleNamespace(_internal_player_frame=player,
                                   _ensure_caster=FailingCaster)

    # Must not raise: the player is gone by the time the box is raised.
    main.IPTVClient._cast_from_internal_player(client, "http://h/live.ts", "News", {})

    assert len(boxes) == 1
