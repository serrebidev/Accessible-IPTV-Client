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
import types
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


@pytest.mark.parametrize("manager_class", [playlist.PlaylistManagerDialog, playlist.EPGManagerDialog])
def test_source_names_survive_reopen_without_changing_source(wx_app, monkeypatch, manager_class):
    source = "https://example.com/source"
    names = {}
    answer = ["My source"]

    class Entry:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def ShowModal(self):
            return wx.ID_OK
        def GetValue(self):
            return answer[0]

    monkeypatch.setattr(wx, "TextEntryDialog", Entry)
    dlg = manager_class(None, [source], names)
    try:
        dlg.OnRename(None)
        assert dlg.lb.GetString(0) == "My source"
        assert dlg.GetResult() == [source]
        assert names == {}
        saved = dlg.GetNames()
    finally:
        dlg.Destroy()
    reopened = manager_class(None, [source], saved)
    try:
        assert reopened.lb.GetString(0) == "My source"
        # A blank answer now keeps the current label instead of reverting to
        # the default, so a mis-keyed Enter cannot wipe a custom name.
        answer[0] = " "
        reopened.OnRename(None)
        assert reopened.lb.GetString(0) == "My source"
        assert reopened.GetNames() == saved
        # An unchanged name is a no-op too.
        answer[0] = "My source"
        reopened.OnRename(None)
        assert reopened.lb.GetString(0) == "My source"
        assert reopened.GetNames() == saved
    finally:
        reopened.Destroy()


def test_provider_names_are_isolated_until_manager_is_accepted(wx_app):
    source = {"type": "xtream", "id": "one", "name": "Original"}
    dlg = PlaylistManagerDialog(None, [source])
    try:
        dlg.playlist_sources[0]["name"] = "Edited"
        assert source["name"] == "Original"
        assert dlg.GetResult()[0]["name"] == "Edited"
    finally:
        dlg.Destroy()


def test_playlist_selected_actions_live_in_the_context_menu(manager, monkeypatch):
    """Rename/remove do not clutter the manager; Shift+F10 exposes all actions."""
    assert not hasattr(manager, "rename_btn")
    assert not hasattr(manager, "remove_btn")
    labels = []

    def popup(menu):
        labels.extend(item.GetItemLabelText() for item in menu.GetMenuItems())

    monkeypatch.setattr(manager.lb, "PopupMenu", popup)

    class _ContextEvent:
        def GetPosition(self):
            return wx.DefaultPosition

    manager._on_source_context_menu(_ContextEvent())
    assert labels == ["Copy URL", "Rename", "Delete"]


def test_deleting_a_playlist_asks_first(wx_app, monkeypatch):
    """Del and the context menu both drop a whole playlist; make it deliberate."""
    dlg = PlaylistManagerDialog(None, ["http://example.test/one.m3u",
                                       "http://example.test/two.m3u"])
    try:
        asked = []
        monkeypatch.setattr(dlg, "_confirm_remove",
                            lambda label: asked.append(label) or False)
        dlg.lb.SetSelection(0)
        dlg.OnRemove(None)
        assert asked == ["http://example.test/one.m3u"]
        assert len(dlg.playlist_sources) == 2
        assert dlg.lb.GetCount() == 2
        # The row the user was on stays selected, so Del twice by accident is
        # still one question about one playlist.
        assert dlg.lb.GetSelection() == 0

        asked.clear()
        monkeypatch.setattr(dlg, "_confirm_remove",
                            lambda label: asked.append(label) or True)
        dlg.OnRemove(None)
        assert asked == ["http://example.test/one.m3u"]
        assert dlg.playlist_sources == ["http://example.test/two.m3u"]
        assert dlg.lb.GetCount() == 1
        assert dlg.lb.GetSelection() == 0
    finally:
        dlg.Destroy()


def test_deleting_a_playlist_with_nothing_selected_asks_nothing(wx_app, monkeypatch):
    dlg = PlaylistManagerDialog(None, [])
    try:
        monkeypatch.setattr(dlg, "_confirm_remove",
                            lambda label: pytest.fail("asked with no selection"))
        dlg.OnRemove(None)
        assert dlg.playlist_sources == []
    finally:
        dlg.Destroy()


def test_source_manager_f2_and_delete_invoke_selected_actions(manager, monkeypatch):
    """Source lists follow the standard Windows F2 and Delete conventions."""
    calls = []
    monkeypatch.setattr(manager, "OnRename", lambda event: calls.append(("rename", event)))
    monkeypatch.setattr(manager, "OnRemove", lambda event: calls.append(("remove", event)))

    rename_event = types.SimpleNamespace(GetKeyCode=lambda: wx.WXK_F2, Skip=lambda: None)
    delete_event = types.SimpleNamespace(GetKeyCode=lambda: wx.WXK_DELETE, Skip=lambda: None)
    manager._on_source_shortcut(rename_event)
    manager._on_source_shortcut(delete_event)

    assert calls == [("rename", rename_event), ("remove", delete_event)]


def test_playlist_manager_copies_the_source_url(wx_app, monkeypatch):
    """Copy URL puts the selected playlist URL on the clipboard."""
    dlg = PlaylistManagerDialog(None, ["https://example.com/list.m3u", "C:\\playlists\\local.m3u"])
    copied = []
    monkeypatch.setattr(playlist, "_copy_text_to_clipboard", lambda text: copied.append(text) or True)
    monkeypatch.setattr(playlist.wx, "MessageBox", lambda *args, **kwargs: None)
    try:
        dlg.lb.SetSelection(0)
        dlg._copy_selected_url(None)
        assert copied == ["https://example.com/list.m3u"]
        # A local file path is not a URL; nothing is copied for it.
        dlg.lb.SetSelection(1)
        dlg._copy_selected_url(None)
        assert copied == ["https://example.com/list.m3u"]
        # Provider accounts copy the portal base URL.
        dlg.playlist_sources.append({"type": "xtream", "base_url": "https://portal.example"})
        dlg.lb.Append("provider")
        dlg.lb.SetSelection(2)
        dlg._copy_selected_url(None)
        assert copied[-1] == "https://portal.example"
    finally:
        dlg.Destroy()


def test_epg_manager_copy_url(wx_app, monkeypatch):
    """The EPG manager exposes Copy URL in its context menu; file rows have none.

    Rename and Delete sit beside it, as in the Playlist Manager.
    """
    dlg = playlist.EPGManagerDialog(None, ["https://epg.example/plar.xml", "C:\\epg\\guide.xml"])
    copied = []
    monkeypatch.setattr(playlist, "_copy_text_to_clipboard", lambda text: copied.append(text) or True)
    monkeypatch.setattr(playlist.wx, "MessageBox", lambda *args, **kwargs: None)
    states = []

    def popup(menu):
        states.extend((item.GetItemLabelText(), item.IsEnabled()) for item in menu.GetMenuItems())

    monkeypatch.setattr(dlg.lb, "PopupMenu", popup)

    class _ContextEvent:
        def GetPosition(self):
            return wx.DefaultPosition

    try:
        dlg.lb.SetSelection(0)
        dlg._on_source_context_menu(_ContextEvent())
        assert states == [("Copy URL", True), ("Rename", True), ("Delete", True)]
        dlg._copy_selected_url(None)
        assert copied == ["https://epg.example/plar.xml"]

        dlg.lb.SetSelection(1)
        dlg._on_source_context_menu(_ContextEvent())
        # A file row has no URL to copy, but can still be renamed or deleted.
        assert states[-3:] == [("Copy URL", False), ("Rename", True), ("Delete", True)]
        dlg._copy_selected_url(None)
        assert copied == ["https://epg.example/plar.xml"]
    finally:
        dlg.Destroy()


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
