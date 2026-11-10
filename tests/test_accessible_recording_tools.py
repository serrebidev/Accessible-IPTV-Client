"""Regression cases and cross-feature contracts for accessible recording tools."""
import copy
import json
from types import SimpleNamespace

import pytest
import wx

import accessible_tools_ui as ui
import channel_identity
import channel_preferences
import client_recording
import dvr
import internal_player
import main
import options
import recording_library
import recording_outcome
import storage_monitor
import playback_resume
import shortcuts
from personal_tools_ui import PersonalToolsMixin
from playlist import EPGDatabase


@pytest.fixture(autouse=True)
def clear_mapping():
    channel_preferences.configure({})
    yield
    channel_preferences.configure({})


@pytest.fixture
def app():
    application = wx.GetApp() or wx.App(False)
    yield application
    application.Yield()


def test_real_save_failure_does_not_commit_memory_or_destroy_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    original = {"favorites": ["existing"]}
    path.write_text(json.dumps(original))
    owner = SimpleNamespace(config=copy.deepcopy(original))
    monkeypatch.setattr(options, "load_config", lambda: copy.deepcopy(original))
    monkeypatch.setattr(options, "get_config_write_target", lambda: str(path))
    monkeypatch.setattr(options, "_log_error", lambda text: None)
    monkeypatch.setattr(options.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        PersonalToolsMixin._save_tool_setting(owner, "favorite_collections", lambda old: ["new"])
    assert owner.config == original
    assert json.loads(path.read_text()) == original
    assert list(tmp_path.iterdir()) == [path]


def test_epg_schedule_does_not_publish_before_durable_save(tmp_path, monkeypatch):
    scheduler = dvr.DVRScheduler(str(tmp_path / "schedule.json"), on_start=lambda job: None, on_stop=lambda job: None)
    monkeypatch.setattr(dvr.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        scheduler.add_job({"id": "new", "status": dvr.STATUS_SCHEDULED, "start_ts": 1, "stop_ts": 100})
    assert scheduler.list_jobs() == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("status", ["failed", "missed", "partial", "stopped"])
def test_unsuccessful_episode_can_be_recorded_from_a_later_airing(status):
    job = {"id": "series", "status": status, "repeat": "series", "program": {"episode": "0.4."}}
    assert dvr.taken_episode_keys([job], "series") == set()


@pytest.mark.parametrize("status", ["scheduled", "recording", "stopping", "completed"])
def test_active_or_complete_episode_still_blocks_duplicates(status):
    job = {"id": "series", "status": status, "program": {"episode": "0.4."}}
    assert dvr.taken_episode_keys([job], "series") == {"ep:1x5"}


def test_partial_ffmpeg_failure_reaches_dvr_status(tmp_path, monkeypatch):
    out = tmp_path / "partial.mkv"
    out.write_bytes(b"partial")
    scheduler = dvr.DVRScheduler(str(tmp_path / "dvr.json"), on_start=lambda job: None, on_stop=lambda job: None)
    scheduler.add_job({"id": "job", "status": "recording", "start_ts": 1, "stop_ts": 3601})
    rec = SimpleNamespace(id=1, out_path=str(out), metadata={"dvr_job_id": "job"},
                          stderr_tail=["network failed"], stopped_by_user=False)
    receiver = SimpleNamespace(_ensure_dvr_scheduler=lambda **kwargs: scheduler, _shared_recordings={},
                               _maybe_shutdown_after_recordings=lambda: None,
                               _sync_internal_player_record_state=lambda: None)
    monkeypatch.setattr(client_recording.wx, "CallAfter", lambda *args, **kwargs: None)
    client_recording.RecordingReportsMixin._on_recording_finished(receiver, rec, 1)
    assert scheduler.get_job("job")["status"] == "partial"
    assert out.read_bytes() == b"partial"


@pytest.mark.parametrize("reason,code,written,expected", [
    ("", 0, 3600, "completed"), ("", 1, 100, "partial"),
    ("", 0, 100, "partial"), ("user", 0, 100, "stopped"),
    ("scheduled", 0, 3598, "completed"), ("storage", 0, 100, "partial")])
def test_recording_outcome_distinguishes_endings(tmp_path, reason, code, written, expected):
    out = tmp_path / "capture.mkv"
    out.write_bytes(b"media")
    rec = SimpleNamespace(out_path=str(out), stop_reason=reason, stopped_by_user=bool(reason),
                          media_written_seconds=written, planned_seconds=3600)
    assert recording_outcome.classify(rec, code) == expected
    assert recording_outcome.classify(rec, code, exiting=True) == "partial"


def test_partial_channel_id_does_not_confuse_numbered_channels():
    owner = SimpleNamespace(all_channels=[{"name": "BBC 10", "tvg-id": "bbc10"}], _program_match_cache=None)
    assert main.IPTVClient._find_matching_channel_for_program(
        owner, {"channel_name": "BBC 1", "channel_id": "bbc1"}) is None


def test_manual_guide_mapping_is_provider_scoped_and_consistent(tmp_path):
    channel = {"name": "Channel 1", "tvg-id": "old", "playlist-id": "one"}
    other = dict(channel, **{"playlist-id": "two"})
    key = channel_preferences.channel_key(channel)
    channel_preferences.configure({"epg_channel_overrides": {key: "selected"}})
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.conn.execute("INSERT INTO channels(id,display_name) VALUES ('selected','Guide 9')")
        db.conn.commit()
        assert db.resolve_best_channel_id(channel) == "selected"
        assert channel_preferences.epg_id(other) == ""
        indexes = channel_identity.guide_indexes({"selected": {"display_name": "Guide 9"}})
        assert channel_identity.match_guide_channel(channel, indexes) == indexes.by_id["selected"]
        owner = SimpleNamespace(all_channels=[channel], _program_match_cache=None)
        assert main.IPTVClient._find_matching_channel_for_program(owner, {"channel_id": "selected"}) == channel
        assert main.IPTVClient._find_matching_channel_for_program(owner, {"channel_id": "old", "channel_name": "Channel 1"}) is None
        db.conn.execute("DELETE FROM channels")
        db.conn.commit()
        assert db.resolve_best_channel_id(channel) is None
    finally:
        db.close()


def test_mapping_reset_invalidates_the_reverse_match_cache():
    channel = {"name": "Channel", "tvg-id": "old", "playlist-id": "source"}
    owner = SimpleNamespace(all_channels=[channel], _program_match_cache=None)
    channel_preferences.configure({"epg_channel_overrides": {channel_preferences.channel_key(channel): "new"}})
    assert main.IPTVClient._find_matching_channel_for_program(owner, {"channel_id": "new"}) == channel
    channel_preferences.configure({})
    assert main.IPTVClient._find_matching_channel_for_program(owner, {"channel_id": "old"}) == channel


def test_space_monitor_warns_once_per_drive_and_stops_all_affected_recordings(tmp_path, monkeypatch):
    rows = [SimpleNamespace(id=i, written_path=str(tmp_path / str(i)), stopping=False) for i in range(2)]
    free = [512]
    monkeypatch.setattr(storage_monitor.shutil, "disk_usage", lambda path: SimpleNamespace(free=free[0] * storage_monitor.MIB))
    monitor, messages, stopped = storage_monitor.SpaceMonitor(), [], []
    def stop(identity):
        stopped.append(identity)
        rows[identity].stopping = True
    for _repeat in range(2):
        monitor.check(rows, (True, 1024, 256, True), lambda *args: messages.append(args), stop)
    assert len(messages) == 1 and messages[0][0] == "warning"
    free[0] = 128
    monitor.check(rows, (True, 1024, 256, True), lambda *args: messages.append(args), stop)
    assert stopped == [0, 1]
    assert messages[-1][0] == "stopping"
    monitor.check(rows, (True, 1024, 256, True), lambda *args: messages.append(args), stop)
    assert len(messages) == 2 and stopped == [0, 1]


def test_space_query_failure_warns_without_stopping(tmp_path, monkeypatch):
    row = SimpleNamespace(id=1, written_path=str(tmp_path / "movie"), stopping=False)
    monkeypatch.setattr(storage_monitor.shutil, "disk_usage", lambda path: (_ for _ in ()).throw(OSError("offline")))
    monitor, messages, stopped = storage_monitor.SpaceMonitor(), [], []
    for _repeat in range(2):
        monitor.check([row], (True, 1024, 256, True), lambda *args: messages.append(args), stopped.append)
    assert len(messages) == 1 and messages[0][0] == "unavailable"
    assert stopped == []


def test_local_library_filters_active_files_and_preserves_outcome(tmp_path):
    path = tmp_path / "Film.mkv"
    path.write_bytes(b"recorded")
    rec = SimpleNamespace(out_path=str(path), title="Film", metadata={"channel_name": "TV"},
                          media_written_seconds=90, outcome="partial")
    recording_library.remember(rec, 1)
    rows = recording_library.scan(tmp_path)
    assert len(rows) == 1 and rows[0]["status"] == "partial" and rows[0]["duration"] == 90
    assert recording_library.scan(tmp_path, [str(path)]) == []
    channel = recording_library.playback_channel(tmp_path, rows[0])
    assert channel["kind"] == "movie" and channel["url"] == path.as_uri()
    path.write_bytes(b"replacement with another size")
    with pytest.raises(ValueError):
        recording_library.playback_channel(tmp_path, rows[0])
    assert recording_library.scan(tmp_path)[0]["status"] == "unknown"


def test_library_delete_checks_root_and_current_file_signature(tmp_path):
    directory = tmp_path / "recordings"
    directory.mkdir()
    path = directory / "one.mkv"
    path.write_bytes(b"one")
    row = recording_library.scan(directory)[0]
    with pytest.raises(ValueError):
        recording_library.delete(directory, row, [str(path)])
    assert path.exists()
    with pytest.raises(ValueError):
        recording_library.delete(tmp_path, row)
    assert path.exists()
    recording_library.delete(directory, row)
    assert not path.exists()


def test_channel_volume_is_bounded_and_provider_scoped():
    one = {"name": "TV", "playlist-id": "one"}
    two = dict(one, **{"playlist-id": "two"})
    values = channel_preferences.remember_volume({}, channel_preferences.channel_key(one), 45)
    config = {"channel_volumes": values}
    assert channel_preferences.volume(config, channel_preferences.channel_key(one), 80) == 45
    assert channel_preferences.volume(config, channel_preferences.channel_key(two), 80) == 80
    assert channel_preferences.volume({"channel_volumes": {"key": False}}, "key", 80) == 80


def test_mute_restores_sound_without_changing_volume_or_pausing():
    muted, announcements = [], []
    frame = SimpleNamespace(_volume_value=43, _muted=False,
        player=SimpleNamespace(audio_set_mute=muted.append),
        mute_item=SimpleNamespace(Check=lambda value: None),
        _update_status_label=lambda text, **kwargs: announcements.append(text))
    internal_player.InternalPlayerFrame.toggle_mute(frame)
    internal_player.InternalPlayerFrame.toggle_mute(frame)
    assert muted == [True, False] and frame._volume_value == 43
    assert len(announcements) == 2


@pytest.mark.parametrize("context,action,key", [("main", "previous_channel", "Ctrl+Shift+M"),
                                               ("player", "audio_track", "M")])
def test_new_mute_default_does_not_steal_an_existing_personal_shortcut(context, action, key):
    bindings = shortcuts.effective({"shortcuts": {context + "." + action: key}}, context)
    assert shortcuts.parse(bindings[action])[:2] == shortcuts.parse(key)[:2]
    assert shortcuts.parse(bindings["mute"])[:2] != shortcuts.parse(key)[:2]


def test_volume_changes_keep_mute_and_apply_sleep_gain():
    calls = []
    slider = SimpleNamespace(GetValue=lambda: 80, SetValue=lambda value: None)
    frame = SimpleNamespace(_volume_value=80, _muted=True, _sleep_gain=0.5,
        player=SimpleNamespace(audio_set_volume=lambda value: calls.append(("volume", value)),
                               audio_set_mute=lambda value: calls.append(("mute", value))),
        volume_slider=slider, _update_status_label=lambda: None)
    internal_player.InternalPlayerFrame._apply_volume(frame, 60)
    assert calls == [("volume", 30), ("mute", True)]
    assert frame._volume_value == 60 and frame._muted is True


def test_local_recording_resumes_only_the_same_file(tmp_path):
    path = tmp_path / "Film.mkv"
    path.write_bytes(b"video")
    row = recording_library.scan(tmp_path)[0]
    channel = recording_library.playback_channel(tmp_path, row)
    key = playback_resume.item_key(channel)
    entries = playback_resume.checkpoint({}, key, 90_000, 600_000, info=playback_resume.metadata(channel))
    loaded, lookup_key = playback_resume.lookup(entries, channel)
    assert loaded[lookup_key]["position_ms"] == 90_000
    path.write_bytes(b"different video")
    replacement = recording_library.playback_channel(tmp_path, recording_library.scan(tmp_path)[0])
    assert playback_resume.item_key(replacement) != key


def test_pending_volume_is_saved_before_switching_context():
    old = {"name": "One", "playlist-id": "provider"}
    new = {"name": "Two", "playlist-id": "provider"}
    old_key, new_key = (channel_preferences.channel_key(ch) for ch in (old, new))
    owner = SimpleNamespace(config={"remember_channel_volume": True, "channel_volumes": {old_key: 20, new_key: 35}},
                            _remember_channel_volume=lambda *args: None)
    calls = []
    def flush():
        calls.append("flush")
        owner.config["channel_volumes"][new_key] = 45
    frame = SimpleNamespace(_volume_context=old_key, _volume_value=22, _unscoped_volume=80,
                            _flush_channel_volume=flush, set_volume_context=lambda key, value, save: calls.append((key, value)))
    ui.AccessibleToolsMixin._prepare_channel_volume(owner, frame, new)
    assert calls == ["flush", (new_key, 45)]


def test_local_recording_checkpoints_do_not_pollute_the_provider_vod_library():
    config = {"playback_bookmarks": {"unrelated-provider-entry": {"keep": True}}}
    saved = []
    frame = SimpleNamespace(_resume_config=config, _resume_store="recording_playback_bookmarks",
        _resume_key="a" * 64, _resume_prepared=None, _current_stream_kind="vod", _manual_stop=False,
        _destroyed=False, _has_seen_playing=True, _resume_start_ms=0, _resume_last_save=0,
        player=SimpleNamespace(get_time=lambda: 90_000, get_length=lambda: 600_000),
        _resume_metadata={"title": "Local film"}, _resume_save=lambda: saved.append(True))
    internal_player.InternalPlayerFrame._save_resume_checkpoint(frame, force=True)
    assert config["playback_bookmarks"] == {"unrelated-provider-entry": {"keep": True}}
    assert config["recording_playback_bookmarks"]["a" * 64]["position_ms"] == 90_000
    assert saved == [True]


def test_failed_checkpoint_keeps_previous_bookmark_and_announces_only_once():
    previous = {"untouched": {"position_ms": 30_000}}
    config = {"recording_playback_bookmarks": previous}
    messages = []

    def cannot_save():
        raise OSError("disk full")

    frame = SimpleNamespace(_resume_config=config, _resume_store="recording_playback_bookmarks",
        _resume_key="a" * 64, _resume_prepared=None, _current_stream_kind="vod", _manual_stop=False,
        _destroyed=False, _has_seen_playing=True, _resume_start_ms=0, _resume_last_save=0,
        player=SimpleNamespace(get_time=lambda: 90_000, get_length=lambda: 600_000),
        _resume_metadata={"title": "Local film"}, _resume_save=cannot_save,
        _notify_box=lambda *args: messages.append(args))
    for _ in range(2):
        internal_player.InternalPlayerFrame._save_resume_checkpoint(frame, force=True)
        assert config["recording_playback_bookmarks"] is previous
    assert len(messages) == 1 and "disk full" in messages[0][0]
    assert messages[0][1] == "Recording Library"
    frame._resume_save = lambda: None
    internal_player.InternalPlayerFrame._save_resume_checkpoint(frame, force=True)
    assert config["recording_playback_bookmarks"]["a" * 64]["position_ms"] == 90_000
    assert frame._resume_save_failed is False


def test_schedule_refresh_and_delete_confirmation_preserve_selection(app, monkeypatch):
    host = wx.Frame(None)
    host._schedule_window_label = lambda job: "20:00"
    host._recording_format_label = str
    jobs = [{"id": str(i), "title": "Recording " + str(i), "channel_name": "TV",
             "status": "scheduled", "format": "provider_mkv"} for i in range(3)]
    dialog = main.ScheduledRecordingsDialog(host, SimpleNamespace(list_jobs=lambda **kwargs: copy.deepcopy(jobs)))
    try:
        dialog.list_ctrl.Select(0)
        dialog.list_ctrl.Select(1)
        dialog.refresh()
        assert [row["id"] for row in dialog._selected_jobs()] == ["0", "1"]
        prompts = []
        monkeypatch.setattr(main, "message_box", lambda message, *args, **kwargs: prompts.append(message) or wx.NO)
        dialog._on_delete_selected(None)
        assert "2 selected" in prompts[0] and "files will be kept" in prompts[0]
    finally:
        dialog.Destroy()
        host.Destroy()


def test_new_native_dialogs_have_named_controls_and_late_workers_are_ignored(app, tmp_path, monkeypatch):
    host = wx.Frame(None)
    host.config = {}
    host.recorder = SimpleNamespace(list_active=lambda: [])
    monkeypatch.setattr(ui.options, "get_recordings_dir", lambda config: str(tmp_path))
    monkeypatch.setattr(ui.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    storage = ui.SpaceSettingsDialog(host)
    mapping = ui.EpgMappingDialog(host, {"name": "TV"})
    library = ui.RecordingLibraryDialog(host)
    try:
        assert storage.warning.GetName() == "Warn below (MiB):"
        assert mapping.list.GetName() == "Programme guide channels"
        assert library.list.GetName() == "Recordings"
        mapping.closed = library.closed = True
        mapping.loaded([], "")
        library.loaded([], "")
    finally:
        storage.Destroy()
        mapping.Destroy()
        library.Destroy()
        host.Destroy()
