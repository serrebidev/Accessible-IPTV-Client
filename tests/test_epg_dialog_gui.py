"""GUI tests: the EPG schedule and catch-up download dialogs really build.

Regression cover for the "View EPG does nothing" report: the dialog
constructors called ``SetAccessibleName``, which does not exist in wxPython,
so the ``ChannelEPGDialog`` constructor raised inside a ``wx.CallAfter`` and
the window silently never appeared. These tests construct the real dialogs
against real wx, so any constructor-level crash fails loudly here.

Skipped when wxPython or a usable display is unavailable.
"""
import os
import sys
import types
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")

import main as appmod  # noqa: E402

ChannelEPGDialog: Any = appmod.ChannelEPGDialog
CatchupDownloadDialog: Any = appmod.CatchupDownloadDialog


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


def _programmes(with_description: bool):
    """Three programmes spanning today; the middle one is airing now."""
    base = "20260907"
    progs = [
        {"title": "Morning News", "start": base + "080000", "end": base + "090000",
         "description": "The morning headlines." if with_description else ""},
        {"title": "Midday Report", "start": base + "090000", "end": base + "100000",
         "description": "Reports from around the world." if with_description else ""},
        {"title": "Evening News", "start": base + "190000", "end": base + "200000",
         "description": "The day in review." if with_description else ""},
    ]
    return progs


def test_channel_epg_dialog_builds_and_shows_description(wx_app):
    dlg = ChannelEPGDialog(None, "Sky Mix", _programmes(with_description=True))
    try:
        assert dlg.list_ctrl.GetItemCount() == 3
        # The first row is selected on construction; the description field
        # follows the selection.
        assert dlg.description_field.GetValue() == "The morning headlines."
    finally:
        dlg.Destroy()


def test_channel_epg_dialog_builds_without_descriptions(wx_app):
    dlg = ChannelEPGDialog(None, "Sky Mix", _programmes(with_description=False))
    try:
        assert dlg.list_ctrl.GetItemCount() == 3
        assert dlg.description_field.GetValue() == appmod._(
            "No description available for this programme.")
    finally:
        dlg.Destroy()


def test_catchup_download_dialog_builds(wx_app):
    # log_path / written_path point at files that do not exist: the dialog
    # must still build (progress reads them defensively every second).
    rec = types.SimpleNamespace(
        title="Sky Mix: Evening News", log_path="Z:/no/such/rec.log",
        written_path="Z:/no/such/out.mp4")
    dlg = CatchupDownloadDialog(None, rec, duration=3600.0, on_cancel=lambda: None)
    try:
        assert dlg.gauge.GetRange() == 100
        details = dlg.details_field.GetValue()
        assert "Progress" in details and "Elapsed" in details
    finally:
        dlg.Destroy()
