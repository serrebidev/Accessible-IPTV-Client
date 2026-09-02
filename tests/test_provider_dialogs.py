"""GUI tests for the Playlist Manager's provider dialogs (Xtream / Stalker).

Regression cover for the "app unresponsive when adding a Stalker portal" report
(issue #7): the nested provider dialog opened from the already-modal Playlist
Manager could end up behind its parent - invisible, but still blocking input, so
the app looked frozen with no way to type credentials. These tests pin the two
guards that fix it: the dialog is raised and focused once its modal loop starts,
and a dialog that fails to build can no longer wedge the manager.

Skipped when wxPython or a usable display is unavailable.
"""
import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")

import playlist  # noqa: E402

# The dialog classes live behind an ``if WX_AVAILABLE`` guard, so a static checker
# only ever sees the no-wx stubs; go through Any-typed aliases to keep it quiet.
PlaylistManagerDialog: Any = playlist.PlaylistManagerDialog
StalkerPortalDialog: Any = playlist.StalkerPortalDialog
XtreamCodesDialog: Any = playlist.XtreamCodesDialog


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


@pytest.fixture
def manager(wx_app):
    frame = wx.Frame(None, title="test host")
    dlg = PlaylistManagerDialog(frame, [])
    yield dlg
    dlg.Destroy()
    frame.Destroy()


@pytest.fixture
def stalker(manager):
    dlg = StalkerPortalDialog(manager)
    yield dlg
    dlg.Destroy()


# --------------------------------------------------------------------------- #
# Dialog construction
# --------------------------------------------------------------------------- #
def test_stalker_dialog_builds_every_field(stalker):
    for attr in ("name_ctrl", "url_ctrl", "user_ctrl", "pass_ctrl", "mac_ctrl", "auto_epg_ctrl", "mac_btn"):
        assert hasattr(stalker, attr), attr
    # A dialog that fits nothing would be the invisible-window failure mode.
    width, height = stalker.GetSize()
    assert width > 100 and height > 100


def test_stalker_dialog_marks_credentials_optional(stalker):
    assert stalker.user_ctrl.GetName() == "Optional portal account username"
    assert stalker.pass_ctrl.GetName() == "Optional portal account password"


def test_stalker_dialog_focuses_first_field(stalker):
    assert stalker.first_field is stalker.name_ctrl


def test_xtream_dialog_focuses_first_field(manager):
    dlg = XtreamCodesDialog(manager)
    try:
        assert dlg.first_field is dlg.name_ctrl
    finally:
        dlg.Destroy()


def test_default_mac_has_six_octets(stalker):
    assert len(stalker.mac_ctrl.GetValue().split(":")) == 6


@pytest.mark.parametrize("raw, expected", [
    ("001A79123456", "00:1A:79:12:34:56"),
    ("00-1a-79-12-34-56", "00:1A:79:12:34:56"),
    ("00:1a:79:12:34:56", "00:1A:79:12:34:56"),
])
def test_mac_sanitizing(stalker, raw, expected):
    assert stalker._sanitize_mac(raw) == expected


def test_stalker_get_data(stalker):
    stalker.name_ctrl.SetValue("My Portal")
    stalker.url_ctrl.SetValue("http://portal.example.com/c/")
    stalker.user_ctrl.SetValue("user1")
    stalker.pass_ctrl.SetValue("pass1")
    stalker.mac_ctrl.SetValue("00:1A:79:12:34:56")
    data = stalker.get_data()
    assert data == {
        "type": "stalker",
        "name": "My Portal",
        "base_url": "http://portal.example.com/c/",
        "username": "user1",
        "password": "pass1",
        "mac": "00:1A:79:12:34:56",
        "auto_epg": True,
    }


def test_stalker_get_data_allows_mac_only_authentication(stalker):
    stalker.url_ctrl.SetValue("http://portal.example.com/c/")
    data = stalker.get_data()
    assert data is not None
    assert data["username"] == ""
    assert data["password"] == ""
    assert data["mac"] == stalker.mac_ctrl.GetValue()


def test_stalker_get_data_still_requires_url(stalker):
    assert stalker.get_data() is None


# --------------------------------------------------------------------------- #
# Accessible decoration is Windows-only
# --------------------------------------------------------------------------- #
def test_custom_accessible_only_on_msw(manager, monkeypatch):
    ctrl = wx.TextCtrl(manager)
    try:
        monkeypatch.setattr(playlist.wx, "Platform", "__WXGTK__")
        playlist._attach_field_accessible(ctrl, "Username", "Portal account username")
        assert not hasattr(ctrl, "_field_accessible")

        monkeypatch.setattr(playlist.wx, "Platform", "__WXMSW__")
        playlist._attach_field_accessible(ctrl, "Username", "Portal account username")
        assert isinstance(ctrl._field_accessible, playlist._FieldAccessible)
    finally:
        ctrl.Destroy()


def test_attach_field_accessible_swallows_failures(manager, monkeypatch):
    ctrl = wx.TextCtrl(manager)
    try:
        monkeypatch.setattr(playlist.wx, "Platform", "__WXMSW__")
        monkeypatch.setattr(ctrl, "SetAccessible", lambda _acc: (_ for _ in ()).throw(RuntimeError("boom")))
        playlist._attach_field_accessible(ctrl, "Username", "desc")  # must not raise
        assert not hasattr(ctrl, "_field_accessible")
    finally:
        ctrl.Destroy()


# --------------------------------------------------------------------------- #
# Nested modal dialogs are raised and focused (issue #7)
# --------------------------------------------------------------------------- #
class _FakeModalDialog:
    """Stands in for a shown dialog so the modal loop can be driven in-process."""

    def __init__(self, result=wx.ID_CANCEL, shown=True):
        self._result = result
        self._shown = shown
        self.raised = False
        self.self_focused = False

    def IsShown(self):
        return self._shown

    def Raise(self):
        self.raised = True

    def SetFocus(self):
        self.self_focused = True

    def ShowModal(self):
        # A real ShowModal runs a nested event loop, which is what dispatches the
        # pending CallAfter that raises the window.
        wx.GetApp().ProcessPendingEvents()
        return self._result


def test_show_modal_raised_raises_the_window(wx_app):
    dlg = _FakeModalDialog()
    assert playlist._show_modal_raised(dlg) == wx.ID_CANCEL
    assert dlg.raised
    assert dlg.self_focused


def test_show_modal_raised_focuses_first_field(wx_app):
    dlg = _FakeModalDialog(result=wx.ID_OK)
    focused = []

    class _Field:
        def SetFocus(self):
            focused.append(True)

    assert playlist._show_modal_raised(dlg, _Field()) == wx.ID_OK
    assert dlg.raised
    assert focused == [True]
    assert not dlg.self_focused


def test_show_modal_raised_skips_a_dismissed_dialog(wx_app):
    dlg = _FakeModalDialog(shown=False)
    assert playlist._show_modal_raised(dlg) == wx.ID_CANCEL
    assert not dlg.raised


# --------------------------------------------------------------------------- #
# Geometry fallback for window managers that won't stack the child on top
# --------------------------------------------------------------------------- #
def test_stalker_dialog_centred_on_parent_is_fully_concealed(manager, stalker):
    """The condition the nudge exists for: centring hides the dialog completely."""
    stalker.CenterOnParent()
    assert manager.GetScreenRect().Contains(stalker.GetScreenRect())


def test_nudge_moves_a_concealed_dialog_clear_of_its_parent(manager, stalker, monkeypatch):
    monkeypatch.setattr(playlist.wx, "Platform", "__WXGTK__")
    stalker.CenterOnParent()
    playlist._nudge_off_parent(stalker)
    assert not manager.GetScreenRect().Contains(stalker.GetScreenRect())
    # Still on the display, not shoved off-screen.
    area = wx.Display(0).GetClientArea()
    assert area.Contains(stalker.GetScreenRect().GetTopLeft())


def test_nudge_leaves_other_platforms_centred(manager, stalker, monkeypatch):
    monkeypatch.setattr(playlist.wx, "Platform", "__WXMSW__")
    stalker.CenterOnParent()
    before = tuple(stalker.GetScreenRect())
    playlist._nudge_off_parent(stalker)
    assert tuple(stalker.GetScreenRect()) == before


def test_nudge_leaves_a_visible_dialog_alone(manager, stalker, monkeypatch):
    monkeypatch.setattr(playlist.wx, "Platform", "__WXGTK__")
    parent_rect = manager.GetScreenRect()
    stalker.Move(parent_rect.GetRight() + 10, parent_rect.GetTop())
    before = tuple(stalker.GetScreenRect())
    playlist._nudge_off_parent(stalker)
    assert tuple(stalker.GetScreenRect()) == before


def test_nudge_survives_a_dialog_without_geometry(monkeypatch):
    monkeypatch.setattr(playlist.wx, "Platform", "__WXGTK__")
    playlist._nudge_off_parent(_FakeModalDialog())  # must not raise


# --------------------------------------------------------------------------- #
# A broken provider dialog must not wedge the manager
# --------------------------------------------------------------------------- #
def test_add_provider_source_survives_a_dialog_that_cannot_open(manager):
    class _Boom:
        def __init__(self, _parent):
            raise RuntimeError("dialog exploded while building")

    manager._add_provider_source(_Boom)  # must not raise
    assert manager.playlist_sources == []
    assert manager.lb.GetCount() == 0


def test_wx_errors_are_not_shown_as_modal_dialogs(wx_app):
    """The failure paths above reach ``wx.LogError``, whose GUI target is a message box.

    conftest redirects wx logging to stderr, but constructing ``wx.App`` installs wx's own
    GUI target over it -- and a queued error then blocks the interpreter at exit behind a
    dialog with no event loop to show it, which looks exactly like a hung test run.
    """
    assert isinstance(wx.Log.GetActiveTarget(), wx.LogStderr)


def test_add_provider_source_records_the_account(manager):
    class _Stub(_FakeModalDialog):
        def __init__(self, _parent):
            super().__init__(result=wx.ID_OK)
            self.destroyed = False

        def get_data(self):
            return {"type": "stalker", "name": "Portal One", "base_url": "http://p/", "username": "u", "password": "p"}

        def Destroy(self):
            self.destroyed = True

    manager._add_provider_source(_Stub)
    assert len(manager.playlist_sources) == 1
    added = manager.playlist_sources[0]
    assert added["type"] == "stalker"
    assert added["id"]
    assert manager.lb.GetCount() == 1
    assert "Portal One" in manager.lb.GetString(0)


def test_add_provider_source_ignores_cancel(manager):
    class _Stub(_FakeModalDialog):
        def __init__(self, _parent):
            super().__init__(result=wx.ID_CANCEL)

        def get_data(self):
            raise AssertionError("get_data must not be called on cancel")

        def Destroy(self):
            pass

    manager._add_provider_source(_Stub)
    assert manager.playlist_sources == []
    assert manager.lb.GetCount() == 0
