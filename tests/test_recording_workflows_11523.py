import datetime
from queue import Queue
from threading import Event, Thread
from time import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import dvr
import planning_tools
import recorder
import recording_media
import recording_outcome
import recording_queue
import storage_monitor
from background_tasks import LatestTask
from client_recording import RecordingReportsMixin
from subtitle_cues import Cue


def test_series_request_is_replayed_after_an_in_flight_search(tmp_path):
    entered, release, rescanned = Event(), Event(), Event()
    count = []

    def scan():
        count.append(1)
        if len(count) == 1:
            entered.set()
            assert release.wait(5)
        else:
            rescanned.set()

    scheduler = dvr.DVRScheduler(str(tmp_path / "dvr.json"), on_start=Mock(), on_stop=Mock(),
                                 on_series=scan, clock=lambda: 100, poll_seconds=.2)
    scheduler.start()
    try:
        assert entered.wait(3)
        for _ in range(4):
            scheduler.request_series_scan()
        # An overlapping tick may not consume a pending request.
        scheduler._start_series_scan(100)
        assert len(count) == 1
        release.set()
        assert rescanned.wait(3)
    finally:
        release.set()
        scheduler.stop(wait=True)
    assert len(count) == 2


def test_late_start_is_partial_even_if_media_time_appears_to_cover_the_window(tmp_path):
    path = tmp_path / "recording.mkv"
    path.write_bytes(b"recorded")
    rec = SimpleNamespace(out_path=path, started_at=1020, ended_at=1060, media_written_seconds=60)
    assert recording_outcome.classify(rec, 0, scheduled_start=1000, planned_seconds=60) == "partial"
    assert recording_outcome.classify(rec, 0, scheduled_start=1017, planned_seconds=60) == "completed"


def test_slow_destination_validation_does_not_delay_another_start(tmp_path, monkeypatch):
    slow, release, started = Event(), Event(), Event()

    def check(path, reserve):
        if path == "slow":
            slow.set()
            assert release.wait(5)
        return {"path": str(tmp_path)}

    def open_rec(url, title, *args, **kwargs):
        if title == "fast":
            started.set()
        return object()

    manager = recorder.RecordingManager()
    monkeypatch.setattr(recorder.recording_storage, "check_destination", check)
    monkeypatch.setattr(manager, "_start_reserved", open_rec)
    a = Thread(target=manager.start, args=("https://example.invalid/1", "slow", "provider_mkv", {}, "slow"))
    b = Thread(target=manager.start, args=("https://example.invalid/2", "fast", "provider_mkv", {}, "fast"))
    a.start()
    try:
        assert slow.wait(3)
        b.start()
        assert started.wait(2)
    finally:
        release.set()
        a.join(5)
        if b.ident:
            b.join(5)
    assert not manager._reserved_paths and not manager._starting


def test_storage_monitor_notifies_healthy_probe_when_another_is_blocked(tmp_path, monkeypatch):
    slow, release = Event(), Event()
    sampled = Queue()
    monitor = storage_monitor.SpaceMonitor()
    paths = [tmp_path / name for name in ("slow", "fast")]

    def measure(path):
        if path == str(paths[0]):
            slow.set()
            assert release.wait(5)
        else:
            sampled.put(path)
        return (path, ""), 1

    monkeypatch.setattr(storage_monitor, "_measure", measure)
    rows = [SimpleNamespace(id=i, written_path=str(path / "a.mkv"), stopping=False) for i, path in enumerate(paths)]
    stopped = []
    try:
        monitor.check(rows, (True, 1024, 256, True), Mock(), stopped.append, background=True)
        assert slow.wait(2)
        assert sampled.get(timeout=2) == str(paths[1])
        with monitor._lock:
            result_published = isinstance(monitor._pending[str(paths[1])], tuple)
        if not result_published:
            from time import monotonic, sleep
            deadline = monotonic() + 2
            while monotonic() < deadline:
                with monitor._lock:
                    if isinstance(monitor._pending[str(paths[1])], tuple):
                        break
                sleep(.01)
        monitor.check(rows, (True, 1024, 256, True), Mock(), stopped.append, background=True)
        assert stopped == [1]
    finally:
        release.set()


def test_latest_playback_can_use_second_worker_and_ignores_obsolete_result():
    entered, release = Event(), Event()
    dispatched = Queue()
    worker = LatestTask(lambda callback: dispatched.put(callback), parallelism=2)
    received = []
    def blocked(_canceled):
        entered.set()
        assert release.wait(5)
        return "obsolete"
    try:
        worker.submit(blocked, lambda value, error: received.append(value))
        assert entered.wait(2)
        worker.submit(lambda _canceled: "current", lambda value, error: received.append(value))
        dispatched.get(timeout=2)()
        assert received == ["current"]
    finally:
        worker.close()
        release.set()


def test_saved_queue_round_trip_order_and_confirmation(tmp_path):
    rows = [dict(path=str(tmp_path / name), directory=str(tmp_path), title=name, size=12, modified_ns=1)
            for name in ("b.mkv", "a.mkv")]
    data = recording_queue.save_named({}, "Este", rows)
    assert recording_queue.saved_queues(data)["Este"] == rows
    with pytest.raises(ValueError):
        recording_queue.save_named(data, "ESTE", rows)
    assert list(recording_queue.save_named(data, "ESTE", rows[::-1], replace=True).values()) == [rows[::-1]]
    assert recording_queue.saved_queues({"invalid": [{"path": "https://example.invalid"}]}) == {}


def test_schedule_filters_exclude_paused_items_from_the_week():
    today = time()
    date = datetime.datetime.fromtimestamp(today + 60).date().isoformat()
    rows = [
        dict(id="active", status="scheduled", start_ts=today + 60, title="Hírek", channel_name="Rádió"),
        dict(id="paused", status="scheduled", start_ts=today + 60, title="Zene", pause_dates=[date, date]),
        dict(id="partial", status="partial", start_ts=today - 60, title="Zene"),
    ]
    for query, view, expected in (("HÍREK rádió", "week", "active"), ("", "week", "active"),
                                  ("", "problems", "partial"), ("", "paused", "paused")):
        assert [row["id"] for row in planning_tools.filter_recording_schedule(rows, query, view, today)] == [expected]


def test_notification_modes_preserve_history_without_showing_a_dialog(monkeypatch):
    import live_announce

    speech = Mock()
    monkeypatch.setattr(live_announce, "speak", speech)
    owner = SimpleNamespace(config={"recording_success_notification": "history"}, _show_or_queue_message_box=Mock())
    send = RecordingReportsMixin._report_recording_success
    send(owner, "message", "caption", "spoken")
    assert len(owner._notification_history) == 1
    speech.assert_not_called()
    owner.config["recording_success_notification"] = "speech"
    send(owner, "message", "caption", "spoken")
    speech.assert_called_once_with("spoken")
    owner._show_or_queue_message_box.assert_not_called()
    owner.config.clear()
    send(owner, "message", "caption", "spoken")
    owner._show_or_queue_message_box.assert_called_once()


def test_transcript_keeps_original_timestamps_and_accents():
    transcript = recording_media.transcript([Cue(1500, 2200, "Jó estét!"), Cue(5000, 6000, "Őrjárat")])
    assert transcript.decode("utf-8-sig") == "00:00:01.500 – 00:00:02.200\nJó estét!\n\n00:00:05.000 – 00:00:06.000\nŐrjárat\n\n"


def test_local_excerpt_encodes_audio_and_does_not_replace_existing_output(tmp_path, monkeypatch):
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is unavailable")
    monkeypatch.setattr(recorder, "get_ffmpeg_path", lambda: ffmpeg)
    source = tmp_path / "source.wav"
    subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=800:duration=3", str(source)], check=True)
    before = source.read_bytes()
    output = tmp_path / "clip.mkv"
    stat = source.stat()
    identity = f"local-recording:{stat.st_size}:{stat.st_mtime_ns}"
    recording_media.save_excerpt(source, identity, output, 1000, 2000, lambda: False)
    sample = subprocess.check_output([ffmpeg, "-nostdin", "-loglevel", "error", "-i", str(output),
                                      "-ar", "44100", "-f", "s16le", "-ac", "1", "-"])
    assert 85000 <= len(sample) <= 95000
    assert source.read_bytes() == before
    with pytest.raises(ValueError):
        recording_media.save_excerpt(source, identity, output, 1000, 2000, lambda: False)
    assert list(tmp_path.glob(".iptv-excerpt-*")) == []


def test_leaving_lists_next_unpaused_recurrence_instead_of_paused_occurrence():
    from main import IPTVClient

    future = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) + datetime.timedelta(days=2)
    channel = {"name": "Radio", "url": "https://example.invalid"}
    utc = future.astimezone(datetime.timezone.utc)
    row = dvr.build_job(channel, {"title": "News", "start": utc.strftime("%Y%m%d%H%M%S"),
        "end": (utc + datetime.timedelta(minutes=10)).strftime("%Y%m%d%H%M%S")}, "provider_mkv", repeat="daily")
    row["pause_dates"] = [future.date().isoformat(), future.date().isoformat()]
    one_off = dict(row, id="one-off", repeat="")
    owner = SimpleNamespace(dvr_scheduler=SimpleNamespace(list_jobs=lambda **kw: [row, one_off]))
    [upcoming] = IPTVClient._upcoming_dvr_jobs(owner)
    assert datetime.datetime.fromtimestamp(upcoming["start_ts"]).date() == future.date() + datetime.timedelta(days=1)
    assert row["start_ts"] == future.timestamp()


def test_unconfirmed_queue_entry_can_be_retried_after_failure(tmp_path):
    from internal_player import InternalPlayerFrame

    source = tmp_path / "recording.mkv"
    source.write_bytes(b"media")
    stat = source.stat()
    dispatch = Queue()
    launch = Mock(return_value=True)
    owner = SimpleNamespace(recorder=SimpleNamespace(list_active=lambda: []), _launch_stream=launch)
    queue = recording_queue.RecordingQueue(owner, lambda fn, *args: dispatch.put((fn, args)))
    queue.add([dict(path=str(source), directory=str(tmp_path), size=stat.st_size,
        title="recording", modified_ns=stat.st_mtime_ns)])
    queue.start()
    fn, args = dispatch.get(timeout=3)
    fn(*args)
    frame = SimpleNamespace(_vlc_generation=1, _destroyed=False, stop=Mock(), _navigation_message=Mock())
    InternalPlayerFrame._fail_queued_recording(frame, queue, 1, queue.ticket, "test failure")
    frame.stop.assert_called_once_with(manual=True)
    assert not queue.playing and len(queue.pending) == 1
    queue.start()
    fn, args = dispatch.get(timeout=3)
    fn(*args)
    assert launch.call_count == 2
    queue.started(frame, 1, queue.ticket)
    assert queue.pending == []
    queue.stop()


def test_schedule_search_delete_and_select_all_act_on_text_instead_of_bookings(monkeypatch):
    import main

    search = Mock()
    monkeypatch.setattr(main.wx, "Window", SimpleNamespace(FindFocus=lambda: search))
    dialog = SimpleNamespace(schedule_filter=search, _select_all=Mock(), _on_delete_selected=Mock())
    for code, ctrl in ((main.wx.WXK_DELETE, False), (ord("A"), True)):
        event = Mock(GetKeyCode=Mock(return_value=code), ControlDown=Mock(return_value=ctrl))
        main.ScheduledRecordingsDialog._on_char_hook(dialog, event)
        event.Skip.assert_called_once()
    dialog._on_delete_selected.assert_not_called()
    dialog._select_all.assert_not_called()
    event = Mock(GetKeyCode=Mock(return_value=ord("F")), ControlDown=Mock(return_value=True))
    main.ScheduledRecordingsDialog._on_char_hook(dialog, event)
    search.SetFocus.assert_called_once()
    search.SelectAll.assert_called_once()


def test_changelog_groups_hungarian_catalog_help_and_release_notes():
    from tools import release

    subjects = ["Polish Hungarian localization: docs/help/hu.md",
                "Polish Hungarian localization: locale/hu/LC_MESSAGES/iptvclient.po",
                "Polish Hungarian localization: docs/release-note-translations-20261127.json"]
    result = release.build_release_notes([{"subject": subject, "body": ""} for subject in subjects])
    assert result.strip().splitlines() == ["## Other changes", "- Refine Hungarian menus, help and release notes"]


def test_pause_filter_includes_existing_series_rule_after_its_first_recording():
    today = datetime.datetime.fromtimestamp(time()).date()
    pause = [today.isoformat(), (today + datetime.timedelta(days=2)).isoformat()]
    series = dict(id="series", status="completed", repeat="series", pause_dates=pause)
    rows = [series, dict(series, id="canceled", status="canceled"),
            dict(series, id="ordinary", repeat="weekly"),
            dict(series, id="expired", pause_dates=["2000-01-01", "2000-01-02"])]
    assert planning_tools.filter_recording_schedule(rows, "", "paused", time()) == [series]


def test_canceled_excerpt_does_not_touch_the_input_or_start_ffmpeg(tmp_path, monkeypatch):
    import subprocess

    launch = Mock(side_effect=AssertionError("FFmpeg should not start"))
    monkeypatch.setattr(subprocess, "Popen", launch)
    target = tmp_path / "output.mkv"
    recording_media.save_excerpt(tmp_path / "missing.mkv", "", target, 0, 2000, lambda: True)
    launch.assert_not_called()
    assert list(tmp_path.iterdir()) == []
