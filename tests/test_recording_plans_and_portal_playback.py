"""Regression coverage for capture shutdown, portal identity, and opt-in planning actions."""
import datetime as dt
import errno
import json
import threading
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

import client_recording
import dvr
import favorite_collections
import main
import planning_tools
import playlist
import programme_reminders as reminders
import recorder
import recording_edits
import recording_limits
import recording_power
import stream_proxy


NOW = 1_850_000_000


def stamp(value):
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).strftime("%Y%m%d%H%M%S")


def show(start, episode="S01E02", duration=1200):
    return {"title": "Matinée", "start": stamp(start), "end": stamp(start + duration), "episode": episode}


def portal(number=17, name="Station", provider="portal-a"):
    return {"name": name, "provider-id": provider, "provider-type": "stalker", "url": "",
            "tvg-id": "s" + str(number), "provider-data": {"id": str(number), "cmd": "play:" + str(number),
                                                         "number": number}}


def put(db, ch, programme):
    db.insert_channel(ch["tvg-id"], ch["name"])
    db.insert_programme(ch["tvg-id"], programme["title"], programme["start"], programme["end"],
                        episode=programme["episode"])
    db.commit()


def test_active_capture_can_veto_exit_without_a_later_booking(monkeypatch):
    capture = SimpleNamespace(id=3, title="Concert", metadata={})
    owner = SimpleNamespace(minimize_to_tray=False, _update_install_pending=False, _exit_forced=False,
                            _exit_requested=True, _catchup_downloads={}, _upcoming_dvr_jobs=lambda: [],
                            recorder=SimpleNamespace(has_active=lambda: True, list_active=lambda: [capture]))
    prompt = Mock(return_value=wx.NO)
    monkeypatch.setattr(main, "message_box", prompt)
    event = SimpleNamespace(CanVeto=lambda: True, Veto=Mock())
    main.IPTVClient.on_close(owner, event)
    assert "Concert" in prompt.call_args.args[0] and prompt.call_args.args[2] & wx.NO_DEFAULT
    event.Veto.assert_called_once()
    assert not owner._exit_requested and not getattr(owner, "_closing_application", False)


@pytest.mark.parametrize("reason,code,state", [("scheduled", 0, "completed"), ("exit", 0, "stopped"),
                                                ("exit", 1, "partial"), ("scheduled", 1, "partial")])
def test_shutdown_keeps_final_outcome_and_does_not_restart_scheduler(tmp_path, reason, code, state):
    capture_file = tmp_path / "concert.mkv"
    capture_file.write_bytes(b"media")
    scheduler = dvr.DVRScheduler(str(tmp_path / "schedule.json"), on_start=Mock(), on_stop=Mock())
    job = dvr.build_job(portal(), show(NOW), "provider_mkv", job_id="event")
    scheduler.add_job(dict(job, status=dvr.STATUS_STOPPING))
    owner = SimpleNamespace(_suppress_recording_notifications=True, _ensure_dvr_scheduler=Mock(return_value=scheduler))
    capture = SimpleNamespace(metadata={"dvr_job_id": "event"}, out_path=str(capture_file), stop_reason=reason,
                              stopped_by_user=True, started_at=NOW, media_written_seconds=job["stop_ts"]-NOW,
                              stderr_tail=[])
    client_recording.RecordingReportsMixin._on_recording_finished(owner, capture, code)
    owner._ensure_dvr_scheduler.assert_called_once_with(start=False)
    assert scheduler.get_job("event")["status"] == state
    assert json.loads((tmp_path/"schedule.json").read_text())["jobs"][0]["status"] == state


def test_shutdown_waits_for_completion_even_after_capture_leaves_active_list(tmp_path):
    manager = recorder.RecordingManager()
    released, completed = threading.Event(), threading.Event()
    watcher = threading.Thread(target=released.wait)
    watcher.start()
    try:
        manager._watchers.add(watcher)
        assert manager.begin_shutdown(completed.set)
        assert not completed.is_set()
        with pytest.raises(RuntimeError, match="closing"):
            manager.start("test", "capture", "provider_mkv", {}, str(tmp_path), _storage_checked=True)
    finally:
        released.set()
        watcher.join(2)
    assert completed.wait(2)


def test_portal_resolution_runs_off_ui_and_late_response_cannot_play(monkeypatch):
    from background_tasks import LatestTask
    entered, release = threading.Event(), threading.Event()
    delivery = Queue()
    worker = LatestTask(lambda *args: delivery.put(args))
    calls, played = [], []
    first, second = portal(), portal(1)
    def resolve(ch):
        calls.append((ch, threading.get_ident()))
        if ch is first:
            entered.set()
            assert release.wait(3)
        return "address-" + ch["tvg-id"]
    owner = SimpleNamespace(_portal_playback_worker=worker, _show_playing_info=Mock(),
                            _channel_display_name=lambda ch: ch["name"], _resolve_live_url=resolve)
    try:
        main.IPTVClient._resolve_for_playback(owner, first, None, lambda *value: played.append(value))
        assert entered.wait(2)
        main.IPTVClient._resolve_for_playback(owner, second, None, lambda *value: played.append(value))
        release.set()
        callback, *args = delivery.get(timeout=3)
        callback(*args)
        assert played == [("address-s1", False)]
        assert all(ident != threading.get_ident() for _ch, ident in calls)
    finally:
        release.set()
        worker.close()


def test_cached_portal_numbers_override_list_positions(monkeypatch):
    first, second = portal(), portal(1)
    owner = SimpleNamespace(scoped_all_channels=lambda: [first, second], _play_live_channel=Mock())
    dialog = Mock()
    dialog.ShowModal.return_value = wx.ID_OK
    dialog.GetValue.side_effect = ["1", "17"]
    monkeypatch.setattr(wx, "TextEntryDialog", lambda *args: dialog)
    for _attempt in range(2):
        main.IPTVClient._go_to_channel_number(owner)
    assert [call.args[0] for call in owner._play_live_channel.call_args_list] == [second, first]


def test_portal_favourite_and_legacy_reminder_survive_resolving_and_renaming():
    first, second = portal(), portal(17, provider="portal-b")
    entry = favorite_collections.selected_entry(first, [first, second])
    renamed = dict(first, name="Renamed", url="temporary-address")
    assert favorite_collections.resolve([entry], [second, renamed])[0][1] == renamed
    assert reminders.resolve_channel({"channel_key": reminders.channel_key(first)}, [first, second]) is first
    duplicate = dict(first, **{"provider-data": {"cmd": "another", "id": "9"}})
    assert reminders.resolve_channel({"channel_key": reminders.channel_key(first)}, [first, duplicate]) is None
    assert "temporary-address" not in json.dumps(entry)


def test_other_airings_includes_unresolved_portal(tmp_path):
    ch = portal()
    db = playlist.EPGDatabase(str(tmp_path/"guide.db"))
    try:
        put(db, ch, show(NOW+1200))
        job = dvr.build_job(portal(provider="other"), show(NOW+500), "provider_mkv")
        matches, _truncated = recording_edits.other_airings(db, job, [ch], now=NOW)
        assert len(matches) == 1 and matches[0][0] == ch
    finally:
        db.close()


@pytest.mark.parametrize("keep,delta", [(True, 120), (False, None)])
def test_reminder_retime_preserves_identity_preference_and_rejects_stale_edits(tmp_path, keep, delta):
    ch = portal()
    store = reminders.ReminderStore(str(tmp_path/"reminders.json"))
    old, new = show(NOW+1800), show(NOW+2400)
    row = reminders.build(ch, dict(old, channel_id=ch["tvg-id"]), now=NOW)
    store.add(row)
    store.snooze(row["id"], minutes=2, now=NOW+1800)
    before = store.list()[0]
    db = playlist.EPGDatabase(str(tmp_path/"guide.db"))
    try:
        put(db, ch, new)
        proposal, = reminders.guide_changes(db, [before], [ch], now=NOW)
        assert proposal[2]
        new_id = store.retime(before, proposal[1], keep_snooze=keep, now=NOW)
        after = reminders.ReminderStore(store.path).list()[0]
        assert after["id"] == new_id != row["id"] and after["lead"] == row["lead"]
        assert after.get("notify_at") == (None if delta is None else after["start"]+delta)
        with pytest.raises(ValueError):
            store.retime(before, proposal[1], now=NOW)
        put(db, ch, old)
        assert reminders.guide_changes(db, [row], [ch], now=NOW) == []
    finally:
        db.close()


def test_reminder_cannot_overwrite_existing_booking(tmp_path):
    ch = portal()
    store = reminders.ReminderStore(str(tmp_path/"reminders.json"))
    first, second = [reminders.build(ch, show(NOW+d), now=NOW) for d in (1800, 3600)]
    for row in (first, second):
        store.add(row)
    with pytest.raises(ValueError, match="already"):
        store.retime(first, show(NOW+3600), now=NOW)
    assert len(store.list()) == 2


def test_pause_skips_due_occurrence_and_resumes_after_reload(tmp_path):
    clock = [NOW]
    start = Mock()
    def scheduler():
        return dvr.DVRScheduler(str(tmp_path/"schedule.json"), on_start=start, on_stop=Mock(), clock=lambda: clock[0])
    s = scheduler()
    row = dvr.build_job(portal(), show(NOW+100), "provider_mkv", repeat="daily", pre_padding_minutes=0)
    s.add_job(row)
    day = dt.datetime.fromtimestamp(row["start_ts"]).date().isoformat()
    s.set_pause_period(row, [day, day])
    s = scheduler()
    clock[0] = row["start_ts"]
    s.tick()
    assert s.get_job(row["id"])["status"] == dvr.STATUS_SKIPPED
    start.assert_not_called()
    successor, = s.list_jobs(include_done=False)
    assert successor["start_ts"] > clock[0] and not dvr.paused_occurrence(successor)
    with pytest.raises(ValueError):
        s.set_pause_period(row, None)
    s.set_pause_period(successor, None)
    assert "pause_dates" not in s.get_job(successor["id"])


def test_series_pause_releases_episode_for_later_airing_and_conflict_budget(tmp_path):
    s = dvr.DVRScheduler(str(tmp_path/"s.json"), on_start=Mock(), on_stop=Mock(), clock=lambda: NOW)
    ch = portal()
    rule = dvr.build_job(ch, show(NOW+1200), "provider_mkv", repeat="series", pre_padding_minutes=0)
    s.add_job(rule)
    day = dt.datetime.fromtimestamp(rule["start_ts"]).date().isoformat()
    s.set_pause_period(rule, [day, day])
    rerun = dvr.build_job(ch, show(NOW+86400+1200), "provider_mkv")
    s.add_series_episodes(s.get_job(rule["id"]), [rerun], reminders.channel_key)
    assert s.get_job(rerun["id"])["series_source"] == rule["id"]
    config = {"playlists": [{"type": "stalker", "base_url": "https://tv.invalid", "id": "portal-a"}]}
    config["recording_connection_limits"] = {recording_limits.channel_key(ch, config): 1}
    assert recording_limits.peak_demand(config, ch, NOW+1100, NOW+1400, s.list_jobs()) == (1, 1)
    assert recording_power.desired_state({"wake_for_recordings": True}, False, [s.get_job(rule["id"])], NOW)[1] is None


def test_calendar_groups_bookings_retains_uids_and_uses_padded_utc_windows():
    jobs = [dvr.build_job(portal(), show(NOW+delta), "provider_mkv", pre_padding_minutes=2,
                          post_padding_minutes=3) for delta in (1800, 3600)]
    content = planning_tools.recording_calendar(jobs, now=NOW).decode()
    assert content.count("BEGIN:VEVENT") == 2 and content.count("BEGIN:VCALENDAR") == 1
    assert not any(x in content for x in ("play:17", "portal-a"))
    for field, key in (("DTSTART", "start_ts"), ("DTEND", "stop_ts")):
        value = dt.datetime.fromtimestamp(jobs[0][key], dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        assert f"{field}:{value}" in content
    edited = [dict(job, start_ts=job["start_ts"]+30) for job in jobs]
    get_uids = lambda text: [line for line in text.splitlines() if line.startswith("UID:")]
    assert get_uids(content) == get_uids(planning_tools.recording_calendar(edited, now=NOW).decode())
    with pytest.raises(ValueError):
        planning_tools.recording_calendar([dict(jobs[0], status="failed")], now=NOW)


def test_casting_retries_each_lost_interface_once(monkeypatch):
    bind = Mock(side_effect=[OSError(errno.EADDRNOTAVAIL, "gone"), Mock(server_address=("192.0.2.2", 1400))])
    monkeypatch.setattr(stream_proxy.socketserver, "ThreadingTCPServer", bind)
    monkeypatch.setattr(stream_proxy.StreamProxy, "_get_local_ip",
                        lambda self, exclude=None: "192.0.2.2" if exclude else "192.0.2.1")
    p = stream_proxy.StreamProxy()
    monkeypatch.setattr(p, "_ensure_firewall_rule", lambda: None)
    monkeypatch.setattr(p, "_remove_firewall_rule", lambda: None)
    try:
        p.start()
        assert p.host == "192.0.2.2"
        assert [call.args[0][0] for call in bind.call_args_list] == ["192.0.2.1", "192.0.2.2"]
    finally:
        p.stop()


def test_booking_due_to_stop_while_starting_stops_once_by_real_id(tmp_path):
    now = [NOW]
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    captures = []
    def start(_job):
        entered.set()
        assert release.wait(4)
        return 17
    def stop(job):
        captures.append(job["recording_id"])
        stopped.set()
    scheduler = dvr.DVRScheduler(str(tmp_path / "dvr.json"), on_start=start, on_stop=stop, clock=lambda: now[0])
    job = scheduler.add_job(dvr.build_job(portal(), show(NOW), "provider_mp4"))
    try:
        scheduler.tick()
        assert entered.wait(2)
        now[0] = job["stop_ts"]
        scheduler.tick()
        assert not captures
    finally:
        release.set()
    assert stopped.wait(2)
    scheduler.stop(wait=True, timeout=None)
    assert captures == [17]


@pytest.mark.parametrize("stop", [main.IPTVClient._menu_stop_player, main.IPTVClient._tray_stop_player])
def test_manual_stop_discards_a_portal_link_waiting_for_ui_delivery(stop):
    from background_tasks import LatestTask
    pending = Queue()
    played = Mock()
    worker = LatestTask(lambda *args: pending.put(args))
    owner = SimpleNamespace(_portal_playback_worker=worker, _show_playing_info=Mock(),
                            _channel_display_name=lambda ch: ch["name"], _resolve_live_url=lambda ch: "stream")
    try:
        main.IPTVClient._resolve_for_playback(owner, portal(), None, played)
        deliver, = pending.get(timeout=2)
        stop(owner)
        deliver()
        played.assert_not_called()
    finally:
        worker.close()
