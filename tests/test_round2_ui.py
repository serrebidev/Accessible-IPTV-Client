import copy
from types import SimpleNamespace

import pytest
import wx

import accessible_tools_ui
import episode_continuation_ui
import named_bookmarks
import recording_limits_ui
import session_tools_ui


@pytest.fixture
def owner():
    app = wx.GetApp() or wx.App(False)
    frame = wx.Frame(None)
    frame.config = {}
    frame.all_channels = []
    frame.recorder = SimpleNamespace(list_active=lambda: [])
    def save(key, operation):
        frame.config[key] = operation(copy.deepcopy(frame.config.get(key)))
    frame._save_tool_setting = save
    yield frame
    frame.Destroy()
    app.Yield()


def test_named_bookmark_dialog_uses_saved_positions_and_refuses_a_changed_player(owner, monkeypatch):
    key = 'a' * 64
    owner.config['named_playback_bookmarks'] = named_bookmarks.put({}, key, 'Próba', 20000)
    player = wx.Frame(owner)
    player._resume_key = key
    player._vlc_generation = 2
    player.player = SimpleNamespace(is_seekable=lambda: True)
    player._media_clock = lambda: (1000, 60000)
    dialog = session_tools_ui.BookmarksDialog(player)
    try:
        assert dialog.list.GetName() == 'Bookmarks for the current item:'
        assert dialog.list.GetString(0) == 'Próba — 00:00:20'
        messages = []
        monkeypatch.setattr(session_tools_ui, '_error', lambda parent, text: messages.append(text))
        player._vlc_generation = 3
        dialog.go(None)
        assert dialog.target is None and messages
        player._vlc_generation = 2
        result = []
        dialog.EndModal = result.append
        dialog.go(None)
        assert result == [wx.ID_OK] and dialog.target == 20000
    finally:
        dialog.Destroy()
        player.Destroy()


def test_notification_history_is_accessible_and_refreshes_without_mutating_it(owner):
    owner._notification_history = named_bookmarks.notification([], 'Felvétel', 'Elkészült.', now=1000)
    dialog = session_tools_ui.NotificationsDialog(owner)
    try:
        assert dialog.list.GetName() == 'Notifications from this session:'
        assert dialog.details.GetName() == 'Details'
        assert not dialog.details.IsEditable()
        assert dialog.details.GetValue() == 'Elkészült.'
        dialog.refresh()
        assert len(owner._notification_history) == 1
    finally:
        dialog.Destroy()


def test_stale_natural_end_callback_cannot_use_the_new_episode():
    episode_continuation_ui.finished(SimpleNamespace(_vlc_generation=12, _destroyed=False), 11)
    episode_continuation_ui.finished(SimpleNamespace(_destroyed=True), 11)


def test_next_episode_countdown_cancels_after_a_new_playback_request(owner):
    dialog = episode_continuation_ui.NextEpisodeDialog(owner, 'Episode', lambda: False)
    try:
        result = []
        dialog.IsModal = lambda: True
        dialog.EndModal = result.append
        dialog.tick(None)
        assert result == [wx.ID_CANCEL]
    finally:
        dialog.timer.Stop()
        dialog.Destroy()


def test_next_episode_modal_starts_on_cancel(owner):
    dialog = episode_continuation_ui.NextEpisodeDialog(owner, 'Episode', lambda: True)
    observed = []

    def inspect():
        focus = wx.Window.FindFocus()
        observed.append(focus.GetId() if focus else None)
        dialog.EndModal(wx.ID_CANCEL)

    timer = wx.CallLater(100, inspect)
    try:
        assert dialog.ShowModal() == wx.ID_CANCEL
        assert observed == [wx.ID_CANCEL]
    finally:
        timer.Stop()
        dialog.timer.Stop()
        dialog.Destroy()


def test_recording_library_switches_between_restore_and_permanent_delete(owner, tmp_path, monkeypatch):
    monkeypatch.setattr(accessible_tools_ui.options, 'get_recordings_dir', lambda config: str(tmp_path))
    monkeypatch.setattr(accessible_tools_ui.threading, 'Thread', lambda **kwargs: SimpleNamespace(start=lambda: None))
    dialog = accessible_tools_ui.RecordingLibraryDialog(owner)
    try:
        dialog.loaded([], '')
        dialog.deleted.SetValue(True)
        row = {'path': 'fixture', 'title': 'Deleted', 'channel': '', 'date': '', 'duration': None, 'status': 'unknown'}
        dialog.all_rows = [row]
        dialog.filter()
        assert dialog.restore.IsEnabled() and not dialog.play.IsEnabled()
        assert dialog.remove.GetLabel() == dialog.remove.GetName() == 'Delete Recording File...'
        dialog.deleted.SetValue(False)
        dialog.filter()
        assert dialog.play.IsEnabled() and not dialog.restore.IsEnabled()
        assert dialog.remove.GetLabel() == dialog.remove.GetName() == 'Move to Recording Trash...'
        assert not dialog.forget_folder.IsEnabled()
        dialog.closed = True
        dialog.operation_done(RuntimeError('late'))
    finally:
        dialog.Destroy()


def test_account_discovery_result_is_ignored_after_dialog_close(owner, monkeypatch):
    monkeypatch.setattr(recording_limits_ui.threading, 'Thread', lambda **kwargs: SimpleNamespace(start=lambda: None))
    dialog = recording_limits_ui.RecordingLimitsDialog(owner)
    try:
        assert dialog.list.GetName() == 'Provider accounts'
        dialog.closed = True
        dialog.loaded([], 'late result')
        assert dialog.status.GetLabel() == 'Loading accounts...'
    finally:
        dialog.Destroy()
