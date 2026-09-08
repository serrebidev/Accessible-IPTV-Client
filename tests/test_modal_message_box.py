"""Tests for the queued-modal-box guard and About-dialog link activation.

Regression cover for two reports:

* Stopping a recording while its "Stopping recording..." box was still open
  let the finish callback open a second modal box *inside* the first one's
  message loop. On wxMSW that desynchronized the parent's enable count and
  left the main window permanently disabled ("unavailable" to NVDA, dead to
  Alt+F4 and Escape). The fix defers finish notifications until no modal box
  is open.
* The About dialog's HyperlinkCtrl links did not respond to Enter or Space,
  so pressing them activated the default OK button and closed the dialog. The
  first fix answered *every* key, so Tab and the arrow keys opened a browser
  window each while merely moving through the dialog.
"""
import os
import sys
import types
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")

import main as appmod  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


@pytest.fixture
def frame(wx_app):
    frame = wx.Frame(None, title="modal guard host")
    yield frame
    frame.Destroy()


# --------------------------------------------------------------------------- #
# The queued-modal-box guard
# --------------------------------------------------------------------------- #
def test_notification_deferred_while_modal_box_open(frame, monkeypatch):
    shown = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **kw: shown.append(a) or wx.OK)
    client = appmod.IPTVClient.__new__(appmod.IPTVClient)
    client.frame = frame
    client._modal_box_depth = 1  # a modal box ("Stopping recording...") is up

    rec = types.SimpleNamespace(out_path="C:/x/rec.mp4", title="Demo")
    appmod.IPTVClient._report_recording_saved(client, rec)
    assert shown == []  # deferred, not shown while a modal box is up

    client._modal_box_depth = 0  # the user closed the modal box
    appmod.IPTVClient._drain_deferred_notifications(client)
    assert len(shown) == 1  # delivered once the modal box is gone


def test_notification_shown_immediately_without_modal(frame, monkeypatch):
    shown = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **kw: shown.append(a) or wx.OK)
    client = appmod.IPTVClient.__new__(appmod.IPTVClient)
    client.frame = frame

    rec = types.SimpleNamespace(out_path="C:/x/rec.mp4", title="Demo")
    appmod.IPTVClient._report_recording_saved(client, rec)
    assert len(shown) == 1


def test_deferred_queue_is_fifo_and_does_not_double_fire(frame, monkeypatch):
    shown = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **kw: shown.append(a) or wx.OK)
    client = appmod.IPTVClient.__new__(appmod.IPTVClient)
    client.frame = frame
    client._modal_box_depth = 1

    for i in range(3):
        rec = types.SimpleNamespace(out_path=f"C:/x/rec{i}.mp4", title=f"D{i}")
        appmod.IPTVClient._report_recording_saved(client, rec)
    assert shown == []
    client._modal_box_depth = 0
    appmod.IPTVClient._drain_deferred_notifications(client)
    assert [a[0].splitlines()[1] for a in shown] == [f"C:/x/rec{i}.mp4" for i in range(3)]
    appmod.IPTVClient._drain_deferred_notifications(client)
    assert len(shown) == 3  # no duplicates on a second drain


# --------------------------------------------------------------------------- #
# About dialog hyperlinks
# --------------------------------------------------------------------------- #
def test_about_dialog_links_activate_on_enter_and_space(wx_app, monkeypatch):
    opened = []
    monkeypatch.setattr(wx, "LaunchDefaultBrowser", lambda url, *a, **kw: opened.append(url) or True)

    dlg = appmod.AccessibleAboutDialog(None)
    try:
        links = [w for w in dlg.GetChildren()[0].GetChildren() if isinstance(w, wx.adv.HyperlinkCtrl)]
        assert len(links) == 3
        for link in links:
            key_event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            key_event.SetKeyCode(wx.WXK_RETURN)
            link.GetEventHandler().ProcessEvent(key_event)
            key_event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            key_event.SetKeyCode(wx.WXK_SPACE)
            link.GetEventHandler().ProcessEvent(key_event)
        assert len(opened) == 6
    finally:
        dlg.Destroy()


def test_about_dialog_links_ignore_navigation_keys(wx_app, monkeypatch):
    """Tab (and any other key) must move focus, not open a browser window."""
    opened = []
    monkeypatch.setattr(wx, "LaunchDefaultBrowser", lambda url, *a, **kw: opened.append(url) or True)

    dlg = appmod.AccessibleAboutDialog(None)
    try:
        links = [w for w in dlg.GetChildren()[0].GetChildren() if isinstance(w, wx.adv.HyperlinkCtrl)]
        assert links
        for key in (wx.WXK_TAB, wx.WXK_DOWN, wx.WXK_RIGHT, wx.WXK_ESCAPE, ord("A")):
            for link in links:
                key_event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
                key_event.SetKeyCode(key)
                link.GetEventHandler().ProcessEvent(key_event)
        assert opened == []
    finally:
        dlg.Destroy()


# --------------------------------------------------------------------------- #
# Every box in main.py counts towards the modal depth
# --------------------------------------------------------------------------- #
def test_message_box_helper_marks_a_box_as_open(monkeypatch):
    """A box opened anywhere in main.py has to defer finish notifications.

    ``_stop_recording_for_channel`` opens "Stopping recording for X..." with a
    plain box, not through the frame's own helper, so the frame's instance
    counter never saw it and the finish callback still opened a second box
    inside the first one's message loop.
    """
    seen = []

    def fake_box(*_args, **_kwargs):
        seen.append(appmod.modal_box_is_open())
        return wx.OK

    monkeypatch.setattr(wx, "MessageBox", fake_box)
    assert appmod.modal_box_is_open() is False
    appmod.message_box("hello", "caption", wx.OK)
    assert seen == [True]
    assert appmod.modal_box_is_open() is False


def test_stop_recording_box_defers_the_finish_notification(frame, monkeypatch):
    shown = []
    client = appmod.IPTVClient.__new__(appmod.IPTVClient)
    client.frame = frame
    client._modal_box_depth = 0

    rec = types.SimpleNamespace(out_path="C:/x/rec.mp4", title="Demo")

    def fake_box(message, *_args, **_kwargs):
        shown.append(message)
        if message.startswith("Stopping"):
            # The recorder's watcher thread lands here, mid-message-loop.
            appmod.IPTVClient._report_recording_saved(client, rec)
        return wx.OK

    monkeypatch.setattr(wx, "MessageBox", fake_box)
    appmod.message_box("Stopping recording for News...", "Recording", wx.OK)
    assert shown == ["Stopping recording for News..."]  # nothing opened inside

    appmod.IPTVClient._drain_deferred_notifications(client)
    assert len(shown) == 2
    assert shown[1].splitlines()[1] == "C:/x/rec.mp4"
