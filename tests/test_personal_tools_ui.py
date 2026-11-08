"""Real native controls, worker lifetime guards and seek/bookmark integration."""
import copy
import time
from types import SimpleNamespace

import pytest
import wx
import favorite_collections
import internal_player
import media_navigation
from media_navigation_ui import MediaNavigationMixin
import options
import personal_tools_ui as ui
import saved_searches
import subtitle_cues
from subtitle_pipeline import TimedTextSource, PlaybackPosition

CHANNEL = {"name": "Test", "tvg-id": "test", "playlist-id": "source", "url": "https://example.invalid"}


@pytest.fixture
def owner(tmp_path, monkeypatch):
    app = wx.GetApp() or wx.App(False)
    class Owner(ui.PersonalToolsMixin, wx.Frame):
        def _selected_channel(self):
            return CHANNEL
    frame = Owner(None)
    frame.config = {"playlists": [], "epgs": [], "favorites": ["unchanged"]}
    frame.all_channels = [CHANNEL]
    monkeypatch.setattr(options, "load_config", lambda: copy.deepcopy(frame.config))
    monkeypatch.setattr(options, "get_config_write_target", lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(ui.full_backup, "paths", lambda: {"search_seen": str(tmp_path / "seen.json")})
    frame.Show()
    app.Yield()
    yield frame
    frame._stop_saved_searches()
    frame.Destroy()
    app.Yield()


def test_favourite_dialog_preserves_default_and_order(owner, monkeypatch):
    dialog = ui.FavouriteListsDialog(owner)
    try:
        monkeypatch.setattr(ui, "text_entry", lambda *a: "Esti tévé")
        dialog._new(None)
        dialog._add(None)
        assert dialog.entries.GetString(0) == "Test"
        assert owner.config["favorites"] == ["unchanged"]
        assert dialog.entries.GetName() == "Channels"
        assert dialog.lists.GetName() == "Favourite Lists"
        monkeypatch.setattr(ui, "confirm", lambda *a: True)
        dialog._remove(None)
        assert dialog.entries.GetCount() == 0
        assert owner.config["favorites"] == ["unchanged"]
    finally:
        dialog.Destroy()


def test_failed_config_write_keeps_favourites_in_memory(owner, monkeypatch):
    def fail(config):
        raise OSError("disk full")
    monkeypatch.setattr(options, "_save_config_locked", fail)
    with pytest.raises(OSError):
        owner._save_tool_setting("favorite_collections", lambda value: favorite_collections.create([], "A")[0])
    assert "favorite_collections" not in owner.config


def test_running_recording_start_is_readonly_and_preserves_seconds(owner):
    now = time.time()
    job = {"title": "Title", "status": "recording", "start_ts": now-60.125, "stop_ts": now+600}
    dialog = ui.RecordingTimesDialog(owner, CHANNEL, job)
    try:
        assert not dialog.start.IsEditable() and dialog.end.IsEditable()
        ended = []
        dialog.EndModal = ended.append
        dialog._accept(None)
        assert ended == [wx.ID_OK]
        assert dialog.values[1] == job["start_ts"]
        assert dialog.end.GetName().startswith("End")
    finally:
        dialog.Destroy()


def test_search_editor_keeps_scope_and_has_named_native_controls(owner):
    rule = saved_searches.new_rule("híradó", channels=["a"*64], description=True)
    dialog = ui.SearchRuleDialog(owner, owner, rule)
    try:
        dialog.EndModal = lambda code: None
        dialog.query.SetValue("koncert")
        dialog._accept(None)
        assert dialog.value["id"] == rule["id"]
        assert dialog.value["channels"] == rule["channels"]
        assert dialog.value["description"] is True
        assert dialog.scope.GetName() == "Channels"
    finally:
        dialog.Destroy()


def test_closed_dialog_does_not_receive_worker_result(owner, monkeypatch):
    rows, key = favorite_collections.create([], "A")
    owner.config["favorite_collections"] = favorite_collections.edit(rows, key, add=CHANNEL)
    queued, threads = [], []
    monkeypatch.setattr(ui.wx, "CallAfter", lambda callback, *args: queued.append((callback,args)))
    monkeypatch.setattr(ui.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: threads.append(kw["target"])))
    dialog = ui.FavouriteListsDialog(owner)
    dialog._play(None)
    dialog.closed = True
    dialog.Destroy()
    threads[0]()
    callback, args = queued.pop()
    callback(*args)  # must never address a destroyed native control


def test_saved_search_completion_from_replaced_playlist_is_discarded(owner, monkeypatch):
    owner.config["saved_programme_searches"] = [saved_searches.new_rule("news")]
    queued, workers, committed = [], [], []
    monkeypatch.setattr(ui.wx, "CallAfter", lambda callback, *args: queued.append((callback,args)))
    monkeypatch.setattr(ui.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: workers.append(kw["target"])))
    monkeypatch.setattr(saved_searches, "scan", lambda *a, **kw: [{"rule":"old","matches":[]}])
    monkeypatch.setattr(saved_searches, "commit_seen", lambda *a: committed.append(a))
    owner._scan_saved_searches()
    owner.all_channels = [dict(CHANNEL)]
    workers[0]()
    callback, args = queued.pop(0)
    callback(*args)
    assert not committed and not getattr(owner, "_saved_search_results", [])
    assert queued  # a new scan is queued for the replacement playlist


class NavigationHarness(MediaNavigationMixin):
    def __init__(self):
        self.position, self.length = 30000, 120000
        self._vlc_generation = 1
        self._current_stream_kind = "vod"
        self.sent, self.messages, self.saves = [], [], []
        self.player = SimpleNamespace(get_time=lambda: self.position, get_length=lambda: self.length,
                                      is_seekable=lambda: True, set_time=self.sent.append)
    def _navigation_message(self, text):
        self.messages.append(text)
    def _save_resume_checkpoint(self, force=False):
        self.saves.append(self.position)


def test_seek_waits_for_actual_clock_and_combines_repeated_shortcuts():
    frame = NavigationHarness()
    frame._seek_media(delta=10000)
    frame._seek_media(delta=10000)
    assert frame.sent == [40000, 50000]
    assert frame._poll_media_seek() and not frame.saves
    frame.position = 50000
    assert not frame._poll_media_seek()
    assert frame.saves == [50000]
    assert "00:00:50" in frame.messages[-1] and "00:01:10" in frame.messages[-1]


def test_seek_never_affects_live_or_stale_session():
    frame = NavigationHarness()
    frame._current_stream_kind = "live"
    frame._seek_media(delta=10000)
    assert not frame.sent
    frame._current_stream_kind = "vod"
    frame._seek_media(delta=10000)
    frame._vlc_generation += 1
    frame.position = 40000
    assert not frame._poll_media_seek() and not frame.saves


def test_pending_seek_cannot_overwrite_existing_resume_bookmark():
    frame = SimpleNamespace(_pending_media_seek=media_navigation.PendingSeek(1, 60000, time.monotonic(), 10000),
                            _vlc_generation=1)
    internal_player.InternalPlayerFrame._save_resume_checkpoint(frame, force=True)
    # No _resume_config or player is needed: pending validation returns before
    # even looking at the old media clock.


def test_explicit_seek_invalidates_subtitle_timeline_without_rebuilding_index():
    source = TimedTextSource([subtitle_cues.Cue(0, 5000, "first"), subtitle_cues.Cue(10000, 15000, "second")])
    before = source.sample(PlaybackPosition(2000), source="test")
    index = source._index
    source.seeked()
    after = source.sample(PlaybackPosition(12000), source="test")
    assert after.snapshot.generation > before.snapshot.generation
    assert after.snapshot.text == "second" and source._index is index


def test_manual_edit_dispatches_only_one_pending_or_running_job(owner):
    # Use the actual scheduled-recordings control and handler, not a source assertion.
    import main
    job = {"id":"a", "status":"recording", "title":"Test", "channel_name":"Test", "format":"mkv"}
    calls = []
    owner._schedule_window_label = lambda row: "20:00"
    owner._recording_format_label = str
    owner._schedule_by_time = lambda **kw: calls.append(kw)
    sched = SimpleNamespace(list_jobs=lambda **kw: [job])
    dialog = main.ScheduledRecordingsDialog(owner, sched)
    try:
        dialog._edit_times()
        assert calls[0]["job"] == job and calls[0]["job"] is not job
    finally:
        dialog.Destroy()
