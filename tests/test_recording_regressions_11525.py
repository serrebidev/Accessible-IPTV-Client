"""Exercise complete recording paths and failure ordering, including native wx dispatch."""
from concurrent.futures import Future
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest
import wx

import dvr
import full_backup
import main
import playback_resume
import recorder
import recording_library

CHANNEL = {"name": "Station", "url": "https://example.invalid/live"}


def wait_for_gui(predicate):
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        wx.GetApp().Yield()
        sleep(.002)
    assert predicate()


@pytest.fixture
def client(monkeypatch, tmp_path):
    app = wx.GetApp() or wx.App(False)
    monkeypatch.setattr(main, "message_box", Mock())
    owner = SimpleNamespace(
        config={"recordings_dir": str(tmp_path / "recordings")},
        recorder=Mock(),
        _internal_player_channel=CHANNEL,
        _internal_player_stream_kind="live",
        _selected_channel=lambda: CHANNEL,
        _channel_record_key=lambda _: "station",
        _channel_display_name=lambda ch: ch["name"],
        _resolve_live_url=lambda ch: ch["url"],
        _recording_audio_intent=lambda _: None,
        _recording_audio_choice=lambda *_: None,
        _recording_format_for_channel=lambda _: ("audio_wav", "audio", "saved"),
        _take_media_probes=lambda: (),
        _stop_media_probes=lambda *_: None,
        _player_is_showing=lambda _: False,
        _sync_internal_player_record_state=Mock(),
        _show_or_queue_message_box=lambda *args: main.message_box(*args),
        _on_recording_finished=Mock(),
        _note_recording_started=Mock(),
        _recording_format_label=lambda fmt: fmt,
        _launch_stream=Mock(),
    )
    owner.recorder.is_recording.return_value = False
    owner.recorder.start.return_value = SimpleNamespace(id=2, out_path="station.wav", relay=None)
    for name in ("_record_selected", "_record_from_internal_player", "_record_channel",
                 "_stop_recording_for_channel", "_stop_selected_recording", "_announce_live_recording"):
        setattr(owner, name, getattr(main.IPTVClient, name).__get__(owner))
    yield owner
    owner._closing_application = True
    app.Yield()


@pytest.mark.parametrize("entry", ["_record_selected", "_record_from_internal_player"])
@pytest.mark.parametrize("stage", ["portal", "folder", "probe cleanup", "engine"])
def test_pending_recording_keeps_wx_responsive(client, monkeypatch, entry, stage):
    entered, released = Event(), Event()
    def stalled(result):
        assert not wx.IsMainThread()
        entered.set()
        assert released.wait(8)
        return result

    if stage == "portal":
        client._resolve_live_url = lambda ch: stalled(ch["url"])
    elif stage == "folder":
        monkeypatch.setattr(main, "get_recordings_dir", lambda _config: stalled("unused"))
    elif stage == "probe cleanup":
        client._stop_media_probes = lambda *_: stalled(None)
    else:
        client.recorder.start.side_effect = lambda *a, **k: stalled(client.recorder.start.return_value)

    try:
        getattr(client, entry)()
        wait_for_gui(entered.is_set)
        heartbeats = []
        wx.CallAfter(heartbeats.append, "wx is still processing events")
        wait_for_gui(lambda: bool(heartbeats))
        assert not released.is_set()
        client._note_recording_started.assert_not_called()
    finally:
        released.set()
    wait_for_gui(lambda: client._note_recording_started.called)
    assert len(main.message_box.call_args_list) == 1


def test_cancel_restart_ignores_a_stale_audio_probe(client):
    entered, released = Event(), Event()
    client._recording_audio_intent = Mock(side_effect=[{"index": 0}, {"index": 2}])
    def choose(_url, _headers, intent):
        if intent["index"] == 0:
            entered.set()
            assert released.wait(8)
            return (0, 3)
        return (2, 3)
    client._recording_audio_choice = choose
    try:
        client._record_selected()
        wait_for_gui(entered.is_set)
        client._stop_selected_recording()
        client._record_from_internal_player()
    finally:
        released.set()
    wait_for_gui(lambda: client._note_recording_started.called)
    client.recorder.start.assert_called_once()
    assert client.recorder.start.call_args.kwargs["audio_track"] == 2


def test_late_native_start_releases_only_its_own_id_before_restarting(client):
    entered, released = Event(), Event()
    canceled = []
    starts = []
    def start(*args, **kwargs):
        if not starts:
            starts.append(1)
            entered.set()
            assert released.wait(8)
            return SimpleNamespace(id=1, out_path="stale.wav")
        assert canceled == [1]
        starts.append(2)
        return SimpleNamespace(id=2, out_path="current.wav")
    client.recorder.start.side_effect = start
    client.recorder.stop.side_effect = lambda rec_id, **_: canceled.append(rec_id)
    try:
        client._record_selected()
        wait_for_gui(entered.is_set)
        client._record_from_internal_player()
        client._record_selected()
    finally:
        released.set()
    wait_for_gui(lambda: client._note_recording_started.called)
    assert starts == [1, 2]
    client.recorder.stop.assert_called_once_with(1, wait=True)
    assert "current.wav" in main.message_box.call_args.args[0]


def test_cancel_during_real_engine_storage_check_never_reserves_or_spawns(client, monkeypatch):
    entered, released = Event(), Event()
    engine = recorder.RecordingManager()
    client.recorder = engine
    def disk_check(path, _reserve):
        assert not wx.IsMainThread()
        entered.set()
        assert released.wait(8)
        return {"path": path}
    monkeypatch.setattr(recorder.recording_storage, "check_destination", disk_check)
    spawn = Mock()
    monkeypatch.setattr(engine, "_start_reserved", spawn)
    try:
        client._record_selected()
        wait_for_gui(entered.is_set)
        client._stop_selected_recording()
    finally:
        released.set()
    wait_for_gui(lambda: not client._recording_start_lanes)
    spawn.assert_not_called()
    assert not engine.list_active() and not engine._starting and not engine._destination_gates
    client._note_recording_started.assert_not_called()


def test_late_relay_does_not_override_a_new_player_selection(client):
    entered, released = Event(), Event()
    frame = SimpleNamespace(_vlc_generation=1, IsShown=lambda: True)
    frame.stop = lambda **_: setattr(frame, "_vlc_generation", 2)
    client._internal_player_frame = frame
    client._player_is_showing = lambda _: True
    client.recorder.start.return_value.relay = SimpleNamespace(url="http://127.0.0.1/relay")
    def capture(*_args, **_kwargs):
        entered.set()
        assert released.wait(8)
        return client.recorder.start.return_value
    client.recorder.start.side_effect = capture
    try:
        client._record_from_internal_player()
        wait_for_gui(entered.is_set)
        frame._vlc_generation += 1  # another selection reached the player
    finally:
        released.set()
    wait_for_gui(lambda: client._note_recording_started.called)
    client._launch_stream.assert_not_called()
    assert not getattr(client, "_shared_recordings", {})


def test_main_window_recording_writes_readable_media_with_real_ffmpeg(client, tmp_path):
    try:
        recorder.get_ffmpeg_path()
    except (OSError, RuntimeError):
        pytest.skip("FFmpeg is unavailable")
    source = tmp_path / "sample.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 8000)
    client._resolve_live_url = lambda _: source.as_uri()
    client.recorder = recorder.RecordingManager()
    client._record_selected()
    wait_for_gui(lambda: client._on_recording_finished.called or
                 any("Could not start" in args.args[0] for args in main.message_box.call_args_list))
    rec, status = client._on_recording_finished.call_args.args
    assert status == 0
    with wave.open(rec.out_path, "rb") as wav:
        assert wav.getnframes() / wav.getframerate() == pytest.approx(1, abs=.02)


def schedule_job():
    def stamp(t):
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%d%H%M%S")
    return dvr.build_job(CHANNEL, {"title": "Programme", "start": stamp(3600), "end": stamp(7200)},
                         "provider_mkv", job_id="fixture", pre_padding_minutes=0, post_padding_minutes=0)


@pytest.mark.parametrize("persistent", [False, True])
def test_dvr_tick_retries_atomic_write_and_recovers_latest_schedule(tmp_path, monkeypatch, persistent):
    path = tmp_path / "recordings.json"
    warn = Mock()
    now = [0]
    clock = lambda: now[0]
    scheduler = dvr.DVRScheduler(str(path), on_start=Mock(), on_stop=Mock(), on_save_error=warn, clock=clock)
    scheduler.add_job(schedule_job())
    replace = dvr.os.replace
    failures = []
    def locked(source, destination):
        if Path(destination) == path and (persistent or not failures):
            failures.append(destination)
            raise PermissionError("temporarily locked")
        return replace(source, destination)
    now[0] = 7300
    monkeypatch.setattr(scheduler, "_SAVE_RETRY_DELAYS", (0, 0))
    with monkeypatch.context() as patch:
        patch.setattr(dvr.os, "replace", locked)
        scheduler.tick()
        scheduler.stop(wait=True)
        assert scheduler.get_job("fixture")["status"] == dvr.STATUS_MISSED
        if persistent:
            warn.assert_called_once()
            assert json.loads(path.read_text())["jobs"][0]["status"] == dvr.STATUS_SCHEDULED
            scheduler._save_retry_at = 0
            scheduler.tick()
            scheduler.stop(wait=True)
            warn.assert_called_once()
        else:
            warn.assert_not_called()
    if persistent:
        scheduler._save_retry_at = 0
        scheduler.tick()
        scheduler.stop(wait=True)
    restored = dvr.DVRScheduler(str(path), on_start=Mock(), on_stop=Mock(), clock=clock)
    assert restored.get_job("fixture")["status"] == dvr.STATUS_MISSED
    restored.on_start.assert_not_called()
    assert failures and not list(tmp_path.glob("*.tmp"))


def test_invalid_pause_period_cannot_replace_existing_recording_schedule(tmp_path):
    targets = {name: str(tmp_path / (name + ".json")) for name in ("config", "jobs", "reminders", "search_seen")}
    schedule = dvr.DVRScheduler(targets["jobs"], on_start=Mock(), on_stop=Mock(), clock=lambda: 0)
    schedule.add_job(schedule_job())
    before = Path(targets["jobs"]).read_bytes()
    job = dict(schedule_job(), pause_dates=["2030-03-20", "2030-03-19"], repeat="daily")
    bundle = dict(config={"playlists": [], "epgs": []}, jobs=[job], reminders=[], search_seen={})
    with pytest.raises(ValueError):
        full_backup.stage_restore(bundle, targets)
    assert not Path(full_backup.pending_path(targets)).exists()
    assert Path(targets["jobs"]).read_bytes() == before


def test_recording_resume_uses_exact_match_after_an_unavailable_folder(tmp_path, monkeypatch):
    offline, ready = tmp_path / "offline", tmp_path / "ready"
    ready.mkdir()
    (ready / "recording.mkv").write_bytes(b"recording")
    row, = recording_library.scan(str(ready))
    channel = recording_library.playback_channel(str(ready), row)
    key = playback_resume.item_key(channel)
    scan = recording_library.scan
    def check(directory, *a, **kw):
        if directory == str(offline):
            raise PermissionError("offline recording share")
        return scan(directory, *a, **kw)
    monkeypatch.setattr(recording_library, "scan", check)
    entries = {key: {"position_ms": 40000, "length_ms": 120000, "updated": 100}}
    assert key in playback_resume.normalize(entries)
    assert recording_library.resolve_resume(key, entries, [str(offline), str(ready)]) == channel


def test_record_start_does_not_nest_a_message_box(client):
    client._notification_history = []
    client._DEFERRED_NOTIFICATION_LIMIT = main.IPTVClient._DEFERRED_NOTIFICATION_LIMIT
    client._modal_box_is_open = lambda: True
    for name in ("_show_or_queue_message_box", "_deferred_notifications"):
        setattr(client, name, getattr(main.IPTVClient, name).__get__(client))
    client._record_selected()
    wait_for_gui(lambda: bool(client._deferred_notifications()))
    queued, = client._deferred_notifications()
    assert "Recording started" in queued[0]
    main.message_box.assert_not_called()


@pytest.mark.parametrize("switch_channel", [False, True])
def test_channel_selection_releases_advisory_probe_off_wx(client, switch_channel):
    entered, released = Event(), Event()
    killed = Event()

    def wait(timeout=None):
        entered.set()
        assert released.wait(8)
        return 0

    old = SimpleNamespace(poll=lambda: None, kill=killed.set, wait=wait, probe_url=CHANNEL["url"])
    client._media_probe_inflight = {"old"}
    client._media_probe_procs = {"old": old}
    client._terminate_media_probe = main.IPTVClient._terminate_media_probe.__get__(client)
    alternate = dict(CHANNEL, name="Second", url="https://example.invalid/second")

    try:
        main.IPTVClient._play_live_channel(client, CHANNEL)
        wait_for_gui(entered.is_set)
        assert killed.is_set()
        heartbeat = Event()
        wx.CallAfter(heartbeat.set)
        wait_for_gui(heartbeat.is_set)
        if switch_channel:
            main.IPTVClient._play_live_channel(client, alternate)
        else:
            main.IPTVClient._cancel_pending_portal_playback(client)
        client._launch_stream.assert_not_called()
    finally:
        released.set()
    finished = client._retiring_media_probes
    wait_for_gui(finished.done)
    if switch_channel:
        wait_for_gui(lambda: client._launch_stream.called)
        client._launch_stream.assert_called_once()
        assert client._launch_stream.call_args.args[0] == alternate["url"]
    else:
        wx.GetApp().Yield()
        client._launch_stream.assert_not_called()


def test_dvr_stop_timeout_does_not_delay_the_next_due_recording(tmp_path, monkeypatch):
    from threading import Thread

    when = [0]
    writing, release, began = Event(), Event(), Event()
    def start(job):
        if job["id"] == "next":
            began.set()
        return 2

    schedule = dvr.DVRScheduler(str(tmp_path / "dvr.json"), on_start=start, on_stop=Mock(),
                               clock=lambda: when[0])
    previous = schedule_job()
    upcoming = dict(previous, id="next", start_ts=7400, stop_ts=7800)
    schedule.add_job(previous)
    schedule.add_job(upcoming)
    with schedule._lock:
        schedule._jobs[previous["id"]]["status"] = dvr.STATUS_STOPPING
        schedule._stopping_deadlines[previous["id"]] = 7300
    save = schedule.save
    def blocked_save():
        writing.set()
        assert release.wait(8)
        save()
    monkeypatch.setattr(schedule, "save", blocked_save)
    when[0] = 7500
    tick = Thread(target=schedule.tick, daemon=True)
    tick.start()
    try:
        assert writing.wait(3)
        assert began.wait(3), "the next scheduled recording was held up by a schedule write"
        assert schedule.get_job(previous["id"])["status"] == dvr.STATUS_FAILED
    finally:
        release.set()
        tick.join(timeout=8)
        schedule.stop(wait=True, timeout=None)


@pytest.mark.parametrize("replace", [False, True])
def test_catchup_playback_discards_a_delayed_portal_result(client, monkeypatch, replace):
    entered, release, posted = Event(), Event(), Event()
    programme = {"title": "Archive", "start": "20261128080000", "end": "20261128090000"}
    dialog = SimpleNamespace(ShowModal=lambda: wx.ID_OK, get_selection=lambda: programme, Destroy=Mock())
    monkeypatch.setattr(main, "CatchupDialog", lambda *_args, **_kwargs: dialog)
    client._catchup_dialog_open = True
    client._show_playing_info = Mock()
    def resolve(_channel, _show):
        assert not wx.IsMainThread()
        entered.set()
        assert release.wait(8)
        return "https://example.invalid/archive", True
    client._resolve_show_url = resolve
    archive = dict(CHANNEL, **{"provider-type": "stalker"})

    try:
        main.IPTVClient._show_catchup_dialog(client, archive, [programme])
        dialog.Destroy.assert_called_once()
        assert not client._catchup_dialog_open
        wait_for_gui(entered.is_set)
        wx.CallAfter(posted.set)
        wait_for_gui(posted.is_set)
        if replace:
            main.IPTVClient._play_live_channel(client, CHANNEL)
    finally:
        release.set()
    worker = client._portal_playback_worker
    try:
        wait_for_gui(lambda: worker.running == 0 and client._launch_stream.called)
        client._launch_stream.assert_called_once()
        args = client._launch_stream.call_args.args
        if replace:
            assert args[0] == CHANNEL["url"] and not hasattr(client, "_catchup_return")
        else:
            assert args[0] == "https://example.invalid/archive"
            assert client._catchup_return == {"channel": archive, "start": programme["start"]}
    finally:
        worker.close()


@pytest.mark.parametrize("cancel_retry", [False, True])
def test_archive_download_waits_for_storage_off_wx(client, monkeypatch, tmp_path, cancel_retry):
    entered, release, pulse = Event(), Event(), Event()
    dialog = Mock()
    monkeypatch.setattr(main, "CatchupDownloadDialog", Mock(return_value=dialog))
    client._catchup_downloads = {}
    client._catchup_retry_state = {8: 1} if cancel_retry else {}
    client._catchup_retry_timers = {}
    client._close_catchup_dialog = Mock()
    client._catchup_download_finished = Mock()

    def destination(_config):
        assert not wx.IsMainThread()
        entered.set()
        assert release.wait(8)
        return str(tmp_path)
    monkeypatch.setattr(main, "get_recordings_dir", destination)

    def recorder_start(*_args, **kwargs):
        # Very short downloads can finish before the GUI is told they started.
        rec = SimpleNamespace(id=9, out_path="archive.mkv")
        kwargs["on_finish"](rec, 0)
        return rec
    client.recorder.start.side_effect = recorder_start
    try:
        main.IPTVClient._start_catchup_recording(
            client, CHANNEL["url"], "Archive", "catchup:test", {"start": "20261128080000"},
            3600.0, "provider_mkv", {}, retry_of=8 if cancel_retry else None)
        wait_for_gui(entered.is_set)
        wx.CallAfter(pulse.set)
        wait_for_gui(pulse.is_set)
        client._close_catchup_dialog.assert_not_called()
        if cancel_retry:
            main.IPTVClient._cancel_catchup_download(client, 8)
    finally:
        release.set()
    wait_for_gui(lambda: not client._pending_catchup_starts)
    if cancel_retry:
        client.recorder.start.assert_not_called()
        dialog.Show.assert_not_called()
        client._catchup_download_finished.assert_not_called()
    else:
        dialog.Show.assert_called_once()
        client._catchup_download_finished.assert_called_once()
        assert client._catchup_download_finished.call_args.args[0].id == 9



def test_recording_ignores_failure_from_an_already_finished_playback_probe(client):
    completed = Future()
    completed.set_exception(OSError("earlier playback cleanup failed"))
    client._retiring_media_probes = completed

    client._record_selected()

    wait_for_gui(lambda: not client._pending_recording_starts)
    client.recorder.start.assert_called_once()
    client._note_recording_started.assert_called_once()
