"""Tests for the app-wide modal-box guard (modal_guard.py).

GUI-free: the guard exists so a second box never opens inside the first one's
message loop. On wxMSW that desynchronizes the parent-enable bookkeeping and
leaves the main window disabled for good - "unavailable" to NVDA, dead to
Alt+F4 and Escape.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx  # noqa: E402

import modal_guard  # noqa: E402


def test_a_box_marks_the_app_as_busy(monkeypatch):
    seen = []
    monkeypatch.setattr(wx, "MessageBox",
                        lambda *a, **kw: seen.append(modal_guard.modal_box_is_open()) or wx.OK)
    monkeypatch.setattr(wx, "CallAfter", lambda fn: fn())

    assert modal_guard.modal_box_is_open() is False
    modal_guard.message_box("hello", "caption", wx.OK)
    assert seen == [True]
    assert modal_guard.modal_box_is_open() is False


def test_the_depth_is_restored_when_the_box_raises(monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("no window")

    monkeypatch.setattr(wx, "MessageBox", explode)
    monkeypatch.setattr(wx, "CallAfter", lambda fn: fn())

    try:
        modal_guard.message_box("hello", "caption", wx.OK)
    except RuntimeError:
        pass
    assert modal_guard.modal_box_is_open() is False


def test_the_closed_hook_fires_when_the_last_box_closes(monkeypatch):
    fired = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **kw: wx.OK)
    monkeypatch.setattr(wx, "CallAfter", lambda fn: fn())
    modal_guard.set_modal_box_closed_hook(lambda: fired.append(True))
    try:
        modal_guard.message_box("hello", "caption", wx.OK)
        assert fired == [True]
    finally:
        modal_guard.set_modal_box_closed_hook(None)
