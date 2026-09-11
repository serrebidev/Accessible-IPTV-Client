"""EPG Manager row actions and description refresh on re-import."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playlist import EPGDatabase  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    wx = pytest.importorskip("wx")
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


def _context_menu(dlg, monkeypatch):
    import wx
    entries = []
    monkeypatch.setattr(dlg.lb, "PopupMenu", lambda menu: entries.extend(
        (item.GetItemLabelText(), item.IsEnabled()) for item in menu.GetMenuItems()))
    dlg._on_source_context_menu(types.SimpleNamespace(GetPosition=lambda: wx.DefaultPosition))
    return entries


def test_epg_manager_row_actions_live_in_the_context_menu(wx_app, monkeypatch):
    """Same as the Playlist Manager: no Rename/Delete buttons, all on the row."""
    import wx
    from playlist import EPGManagerDialog
    dlg = EPGManagerDialog(None, ["https://epg.ovh/pltv.xml", "C:\\guides\\local.xml"])
    try:
        assert not hasattr(dlg, "rename_btn")
        assert not hasattr(dlg, "remove_btn")
        labels = [child.GetLabel() for child in dlg.GetChildren()[0].GetChildren()
                  if isinstance(child, wx.Button)]
        assert "Rename" not in labels and "Delete" not in labels
        dlg.lb.SetSelection(0)
        assert _context_menu(dlg, monkeypatch) == [
            ("Copy URL", True), ("Rename", True), ("Delete", True)]
    finally:
        dlg.Destroy()


def test_epg_manager_delete_stays_on_the_list(wx_app):
    from playlist import EPGManagerDialog
    dlg = EPGManagerDialog(None, ["a.xml", "b.xml", "c.xml"])
    try:
        dlg.lb.SetSelection(2)
        dlg.OnRemove(None)
        assert dlg.GetResult() == ["a.xml", "b.xml"]
        assert dlg.lb.GetSelection() == 1
        dlg.lb.SetSelection(0)
        dlg.OnRemove(None)
        assert dlg.GetResult() == ["b.xml"]
        assert dlg.lb.GetSelection() == 0
    finally:
        dlg.Destroy()


def _store(db, description):
    db.insert_programme("TVP 1", "Ojciec Mateusz 35. Miłość na wagę.",
                        "20260910183000", "20260910192500", description)
    db.commit()
    return db.conn.execute(
        "SELECT description FROM programmes WHERE channel_id = 'TVP 1'").fetchall()


def test_a_longer_description_replaces_a_shorter_one(tmp_path):
    """A guide's series blurb gives way to the episode synopsis on re-import."""
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        blurb = "G: serial kryminalny. S35E451."
        synopsis = blurb + " Pełny opis odcinka, dodany później przez nadawcę."
        assert _store(db, blurb) == [(blurb,)]
        assert _store(db, synopsis) == [(synopsis,)]
        # Shorter or empty text never replaces what is already there.
        assert _store(db, "Krótko.") == [(synopsis,)]
        assert _store(db, "") == [(synopsis,)]
    finally:
        db.conn.close()
