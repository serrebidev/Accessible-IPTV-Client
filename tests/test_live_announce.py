"""Tests for the screen-reader announcement helper (live_announce.py).

The module needs a real wx window, so these tests are GUI tests: they build a
frame, put it in front, and check that the announcement reaches the control the
reader looks at.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")  # noqa: E402

import live_announce  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


@pytest.fixture
def window(wx_app):
    frame = wx.Frame(None, title="announce host")
    frame.Show()
    wx_app.Yield()
    yield frame
    frame.Destroy()
    wx_app.Yield()


def test_the_text_is_put_on_a_hidden_label_in_the_front_window(window):
    live_announce.speak("Channel changed")
    label = getattr(window, "_live_announcer", None)
    assert label is not None
    assert label.GetLabel() == "Channel changed"


def test_nothing_is_announced_without_text(window):
    live_announce.speak("")
    assert getattr(window, "_live_announcer", None) is None


def test_the_announcement_targets_a_real_control(window):
    """A live-region event needs a window handle, so the control must exist."""
    live_announce.speak("Channel changed")
    label = getattr(window, "_live_announcer", None)
    assert label is not None
    assert label.GetHandle() != 0
