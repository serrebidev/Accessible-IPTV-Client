"""Cross-check restored schedules, guide identities and work performed on the normal paths."""

import datetime as dt
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import channel_widgets
import dvr
import full_backup
import planning_ui
import playlist
import programme_reminders as reminders
import recorder
import saved_searches
import stream_proxy


def channel(cid, source="a", name="Station"):
    return {"tvg-id": cid, "name": name, "playlist-id": source, "url": f"https://{source}.invalid/{cid}"}


def programme(start, end, **details):
    utc = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    return dict(title="Example", start=utc(start), end=utc(end), **details)


def scheduler(path, now):
    return dvr.DVRScheduler(str(path), on_start=Mock(), on_stop=Mock(), clock=lambda: now)


@pytest.mark.parametrize("operation", ["cancel", "delete", "change", "duplicate"])
def test_series_publish_rechecks_rule_and_episode_in_the_transaction(tmp_path, operation):
    now = int(time.time())
    s = scheduler(tmp_path / "dvr.json", now)
    ch = channel("series")
    parent = s.add_job(
        dvr.build_job(ch, programme(now + 1000, now + 2000, episode="1x1"), "provider_mkv", repeat="series")
    )
    second = dvr.build_job(ch, programme(now + 3000, now + 4000, episode="1x2"), "provider_mkv")
    if operation == "delete":
        s.delete_job(parent["id"])
    elif operation == "cancel":
        s.cancel_job(parent["id"])
    elif operation == "change":
        s.set_repeat(parent["id"], "weekly")
    else:
        s.add_series_episodes(parent, [second], reminders.channel_key)
    s.add_series_episodes(parent, [second], reminders.channel_key)
    children = [j for j in scheduler(tmp_path / "dvr.json", now).list_jobs() if j.get("series_source")]
    assert len(children) == int(operation == "duplicate")


@pytest.mark.parametrize("repeat", ["daily", "weekly", "weekdays"])
@pytest.mark.parametrize("already_present", [False, True])
def test_old_encrypted_backup_rearms_one_future_occurrence(tmp_path, repeat, already_present):
    now = int(time.time())
    ch = channel("regular")
    parent = dvr.build_job(
        ch,
        programme(now - 3 * 86400, now - 3 * 86400 + 1800),
        "provider_mkv",
        pre_padding_minutes=5,
        post_padding_minutes=10,
    )
    parent.update(repeat=repeat, weekdays=[0, 2, 4])
    old = [parent]
    if already_present:
        successor = dict(dvr.next_time_occurrence(parent, now, future_only=True), id="legacy-successor")
        # An explicit change to this existing capture's lead-in still represents the same airing.
        successor.update(pre_padding_minutes=7, start_ts=successor["start_ts"] - 120)
        old.append(successor)
    data = dict(config={"playlists": [], "epgs": []}, jobs=old, reminders=[], search_seen={})
    targets = {key: str(tmp_path / (key + ".json")) for key in data}
    path = tmp_path / "encrypted"
    full_backup.export_bundle(path, data, "fixture")
    for _ in range(2):
        full_backup.stage_restore(full_backup.import_bundle(path, "fixture"), targets)
        assert full_backup.apply_pending(targets)
        s = scheduler(targets["jobs"], now)
        s.tick()
        pending = s.list_jobs(include_done=False)
        assert len(pending) == 1 and pending[0]["start_ts"] > now
        assert pending[0]["repeat"] == repeat and pending[0]["post_padding_minutes"] == 10
        assert s.get_job(parent["id"])["status"] == "missed"
        s.on_start.assert_not_called()


@pytest.mark.parametrize("legacy", [False, True])
def test_long_programme_and_identical_named_favourites(tmp_path, legacy):
    now = int(time.time())
    when = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    db = playlist.EPGDatabase(str(tmp_path / "guide"))
    try:
        db._utcnow = lambda: when
        db.insert_channel("marathon", "Marathon")
        show = programme(now - 30 * 3600, now + 3600)
        db.insert_programme("marathon", "Marathon", show["start"], show["end"], "Notes", "1x3", "Encore")
        db.commit()
        if legacy:
            db.conn.execute("DROP INDEX idx_programmes_cross_date")
            db.commit()
            db.close()
            db = playlist.EPGDatabase(str(tmp_path / "guide"), readonly=True)
            db._utcnow = lambda: when
        assert db.get_all_now_playing()[0]["channel_id"] == "marathon"
        assert db.get_all_now_next()["marathon"]["now"]["title"] == "Marathon"
        channels = [channel("marathon", s) for s in ("a", "b")]
        rows = db.programmes_at(when, channels, {"a": "Radio A", "b": "Radio B"})
        view = SimpleNamespace(dialog=SimpleNamespace(filtered_programs=rows))
        labels = [channel_widgets._VirtualWhatsOnList.OnGetItemText(view, i, 0) for i in range(2)]
        assert len(set(labels)) == 2 and "Radio A" in labels[0] and "Radio B" in labels[1]
        assert [r["playlist_channel"] for r in rows] == channels
        assert db.programme_details(rows[0]) == dict(subtitle="Encore", episode="1x3", description="Notes")
        if legacy:
            db.close()
            db = playlist.EPGDatabase(str(tmp_path / "guide"))
        db.conn.execute("DELETE FROM programmes")
        with pytest.raises(ValueError):
            db.programme_details(rows[0])
    finally:
        db.close()


def test_one_channel_search_only_folds_eligible_titles(tmp_path, monkeypatch):
    now = int(time.time())
    path = tmp_path / "guide"
    db = playlist.EPGDatabase(str(path))
    channels = [channel(str(i)) for i in range(100)]
    try:
        for ch in channels:
            cid = ch["tvg-id"]
            db.insert_channel(cid, cid)
            for n in range(20):
                p = programme(now + 10 + n * 60, now + 60 + n * 60)
                db.insert_programme(cid, "Adás %02d" % n, p["start"], p["end"])
        db.commit()
    finally:
        db.close()
    counted = []

    class Count(sqlite3.Connection):
        def create_function(self, name, n, fn, **kwargs):
            def counted_fold(value):
                counted.append(value)
                return fn(value)

            super().create_function(name, n, counted_fold if name == "search_fold" else fn, **kwargs)

    orig = sqlite3.connect
    monkeypatch.setattr(saved_searches.sqlite3, "connect", lambda *a, **kw: orig(*a, factory=Count, **kw))
    for scope, visits, matches in [([reminders.channel_key(channels[0])], 20, 1), ([], 2000, 100)]:
        counted.clear()
        rule = saved_searches.new_rule("ADÁS 19", channels=scope)
        data = saved_searches.scan(path, [rule], channels, now=now)
        assert (len(counted), len(data[0]["matches"])) == (visits, matches)


@pytest.mark.parametrize("delay", [65, 310])
def test_snooze_write_retry_keeps_requested_time_without_duplicate(tmp_path, monkeypatch, delay):
    now = int(time.time())
    clock = [now]
    monkeypatch.setattr(planning_ui.time, "time", lambda: clock[0])
    store = reminders.ReminderStore(str(tmp_path / "reminders"))
    row = reminders.build(channel("one"), programme(now + 120, now + 1800), lead=5, now=now)
    store.add(row)
    store.due()

    class Owner(planning_ui.PlanningMixin):
        _reminders_stopped = False
        _reminder_error_reported = False

        def _ensure_reminders(self):
            return store

        def _reminder_modal_open(self):
            return False

    owner = Owner()
    owner._reminder_seen = set()
    owner._show_or_queue_message_box = Mock()

    def run(_owner, _name, work, ready, _dispatch):
        try:
            result = work()
        except OSError as error:
            ready(None, error)
        else:
            ready(result, None)

    monkeypatch.setattr(planning_ui, "start_operation", run)
    alert = Mock(return_value=SimpleNamespace(action="snooze", Destroy=lambda: None))
    monkeypatch.setattr(planning_ui, "ReminderAlert", alert)
    monkeypatch.setattr(planning_ui, "show_modal", lambda dialog: None)
    with monkeypatch.context() as failure:
        failure.setattr(reminders.os, "replace", Mock(side_effect=OSError("disk busy")))
        owner._poll_reminders()
    assert owner._show_or_queue_message_box.call_count == 1
    clock[0] += delay
    owner._reminder_errors_after = 0
    owner._poll_reminders()
    owner._poll_reminders()
    assert alert.call_count == (2 if delay >= 300 else 1)
    persisted = reminders.ReminderStore(store.path).list()[0]
    assert persisted["notify_at"] == (now + delay + 300 if delay >= 300 else now + 300)


def test_recording_completion_reads_whole_log_once(tmp_path, monkeypatch):
    media, log = tmp_path / "record.mkv", tmp_path / "record.log"
    media.write_bytes(b"fixture")
    log.write_text("[info] line\n" * 18000 + "[warning] sample\n[info] time=00:05:00.00\n")
    rec = recorder.Recording(
        1,
        "key",
        "https://example.invalid",
        "Demo",
        "provider_mkv",
        str(media),
        SimpleNamespace(wait=lambda: None, returncode=0, stdin=None),
        log_path=str(log),
    )
    old, visits = recorder._read_log_lines, []

    def count(path):
        visits.append(path)
        yield from old(path)

    monkeypatch.setattr(recorder, "_read_log_lines", count)
    done = Mock()
    recorder.RecordingManager()._watch(rec, done)
    assert visits == [str(log)]
    assert rec.problem_counts["warnings"] == 1 and rec.media_written_seconds == 300
    done.assert_called_once()


def test_native_ffmpeg_on_unix_with_windows_binary_next_to_source(monkeypatch, tmp_path):
    monkeypatch.setattr(stream_proxy.sys, "platform", "linux")
    monkeypatch.setattr(stream_proxy, "__file__", str(tmp_path / "stream_proxy.py"))
    (tmp_path / "ffmpeg.exe").write_bytes(b"windows")
    monkeypatch.setattr(stream_proxy.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert stream_proxy.get_ffmpeg_path() == "/usr/bin/ffmpeg"
