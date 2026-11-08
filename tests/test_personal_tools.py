"""Behaviour and failure-path tests for all five personal tools."""
import copy
import datetime as dt
import json
import os
import sqlite3
import time

import pytest
import dvr
import favorite_collections as favourites
import full_backup
import manual_schedule as manual
import media_navigation as navigation
import programme_reminders as reminders
import saved_searches as searches
import settings_backup

NOW = 1900000000
CHANNEL = {"name": "Árvíztűrő TV", "tvg-id": "test.hu", "playlist-id": "source-a", "url": "https://example.invalid/one"}


def job(now=NOW):
    return manual.build_manual_job(CHANNEL, "Esti műsor", now + 600, now + 3600, "provider_mkv", now=now)


@pytest.mark.parametrize("start,end", [(NOW-1, NOW+60), (NOW+10, NOW+5), (NOW+1, NOW+8*86400),
                                        (float("nan"), NOW+60), (True, NOW+60), (NOW+10, float("inf"))])
def test_invalid_recording_window(start, end):
    with pytest.raises(ValueError):
        manual.validate_window(start, end, now=NOW)


def test_manual_job_uses_exact_times_without_epg_or_padding():
    row = job()
    assert (row["start_ts"], row["stop_ts"], row["pre_padding_minutes"], row["post_padding_minutes"]) == (NOW+600, NOW+3600, 0, 0)
    assert row["manual"] is True and row["channel"] == CHANNEL


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="POSIX timezone injection; Windows uses native local zone")
def test_local_clock_change_gap_fold_and_winter_offset(monkeypatch):
    old = os.environ.get("TZ")
    try:
        monkeypatch.setenv("TZ", "Europe/Budapest")
        time.tzset()
        with pytest.raises(ValueError, match="does not exist"):
            manual.local_timestamp("2026-03-29 02:30")
        with pytest.raises(manual.AmbiguousTime):
            manual.local_timestamp("2026-10-25 02:30")
        a = manual.local_timestamp("2026-10-25 02:30", 0)
        b = manual.local_timestamp("2026-10-25 02:30", 1)
        assert b-a == 3600
        assert dt.datetime.fromtimestamp(manual.local_timestamp("2026-12-01 20:00"), dt.timezone.utc).hour == 19
        assert dt.datetime.fromtimestamp(manual.local_timestamp("2026-07-01 20:00"), dt.timezone.utc).hour == 18
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def scheduler(tmp_path):
    return dvr.DVRScheduler(str(tmp_path / "schedule.json"), on_start=lambda j: "rec", on_stop=lambda j: None, clock=lambda: NOW)


def test_manual_persistence_duplicate_and_edit_compare_and_swap(tmp_path):
    sched = scheduler(tmp_path)
    row = job()
    sched.add_manual_job(row)
    duplicate = job()
    with pytest.raises(ValueError, match="already"):
        sched.add_manual_job(duplicate)
    expected = tuple(row[k] for k in ("start_ts", "stop_ts", "status"))
    updated = sched.edit_timing(row["id"], NOW+700, NOW+4000, expected=expected)
    assert sched.get_job(row["id"])["stop_ts"] == NOW+4000
    assert dvr.parse_epg_utc(updated["program"]["end"]).timestamp() == NOW+4000
    with pytest.raises(ValueError, match="changed"):
        sched.edit_timing(row["id"], NOW+800, NOW+5000, expected=expected)
    assert json.loads((tmp_path / "schedule.json").read_text(encoding="utf-8"))["jobs"][0]["stop_ts"] == NOW+4000


def test_manual_same_channel_on_other_provider_is_independent(tmp_path):
    sched = scheduler(tmp_path)
    first, second = job(), job()
    first["channel"].update({"provider-id": "a", "playlist-id": ""})
    second["channel"].update({"provider-id": "b", "playlist-id": ""})
    sched.add_manual_job(first)
    sched.add_manual_job(second)
    assert len(sched.list_jobs()) == 2


def test_manual_save_failure_never_mutates_memory(tmp_path, monkeypatch):
    sched, row = scheduler(tmp_path), job()
    sched.add_manual_job(row)
    previous = (tmp_path / "schedule.json").read_bytes()
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", fail)
    expected = tuple(row[k] for k in ("start_ts", "stop_ts", "status"))
    with pytest.raises(OSError):
        sched.edit_timing(row["id"], NOW+700, NOW+4000, expected=expected)
    assert sched.get_job(row["id"])["stop_ts"] == row["stop_ts"]
    assert (tmp_path / "schedule.json").read_bytes() == previous


def test_extended_running_job_rejects_stale_tick(tmp_path):
    sched, row = scheduler(tmp_path), job()
    row.update(status="recording", start_ts=NOW-60, stop_ts=NOW+60)
    sched.add_job(row)
    expected = tuple(row[k] for k in ("start_ts", "stop_ts", "status"))
    sched.edit_timing(row["id"], NOW-60, NOW+600, expected=expected)
    sched.clock = lambda: NOW+61
    sched._stop_job(row["id"], due=True)
    assert sched.get_job(row["id"])["status"] == "recording"
    with pytest.raises(ValueError):
        sched.edit_timing(row["id"], NOW-30, NOW+700, expected=(NOW-60, NOW+600, "recording"))


def test_postponed_recording_rejects_stale_start_and_expiry(tmp_path):
    sched, row = scheduler(tmp_path), job()
    sched.add_manual_job(row)
    old = tuple(row[k] for k in ("start_ts", "stop_ts", "status"))
    sched.edit_timing(row["id"], NOW+7200, NOW+8000, expected=old)
    sched.clock = lambda: NOW+4000
    sched._start_job(row["id"], due=True)
    sched._set_status(row["id"], "missed", expected_window=old)
    assert sched.get_job(row["id"])["status"] == "scheduled"


@pytest.mark.parametrize("value,expected", [("65",65000),("01:05",65000),("1:02:03",3723000),("0",0)])
def test_seek_parser(value, expected):
    assert navigation.parse_position(value) == expected


@pytest.mark.parametrize("value", ["1:60", "-1", "1:2:3:4", "nan", "999999", "", "1:02.5"])
def test_seek_parser_rejects(value):
    with pytest.raises(ValueError):
        navigation.parse_position(value)


def test_seek_clamps_and_confirms_actual_clock():
    assert navigation.target_position(10000, 60000, delta=-60000) == 0
    assert navigation.target_position(55000, 60000, delta=10000) == 59000
    pending = navigation.PendingSeek(1, 30000, 100, 10000)
    assert pending.outcome(1, 10000, now=101) == "pending"
    assert pending.outcome(1, 10000, now=108) == "failed"
    assert pending.outcome(1, 30500, now=101) == "done"
    assert pending.outcome(2, 30000, now=101) == "stale"


def test_favourites_order_names_source_identity_and_missing_channels():
    rows, identity = favourites.create([], "Esti tévézés")
    rows = favourites.edit(rows, identity, add=CHANNEL)
    second = dict(CHANNEL, **{"playlist-id": "source-b"})
    rows = favourites.edit(rows, identity, add=second)
    key = reminders.channel_key(second)
    rows = favourites.edit(rows, identity, move=(key, -1))
    assert rows[0]["entries"][0]["key"] == key
    assert len(rows[0]["entries"]) == 2
    resolved = favourites.resolve(rows[0]["entries"], [dict(CHANNEL, url="https://example.invalid/new")])
    assert resolved[0][1] is None
    assert resolved[1][1]["url"].endswith("/new")
    assert len(favourites.normalize(rows)[0]["entries"]) == 2
    with pytest.raises(ValueError, match="already"):
        favourites.create(rows, "ESTI TÉVÉZÉS")
    assert favourites.edit(rows, identity, delete=True) == []


def test_ambiguous_favourite_never_resolves_arbitrary_provider_url():
    rows, identity = favourites.create([], "A")
    rows = favourites.edit(rows, identity, add=CHANNEL)
    assert favourites.resolve(rows[0]["entries"], [CHANNEL, dict(CHANNEL, url="https://other.invalid")])[0][1] is None


def epg(tmp_path):
    path = str(tmp_path / "guide.db")
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE channels(id TEXT, display_name TEXT); CREATE TABLE programmes(channel_id TEXT, title TEXT, start TEXT, end TEXT, description TEXT);")
    stamp = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    db.execute("INSERT INTO channels VALUES (?, ?)", ("test.hu", CHANNEL["name"]))
    db.executemany("INSERT INTO programmes VALUES (?, ?, ?, ?, ?)", [
        ("test.hu", "ÁRVÍZTŰRŐ hír", stamp(NOW+600), stamp(NOW+3600), "zongora koncert"),
        ("test.hu", "Más műsor", stamp(NOW+7200), stamp(NOW+8000), "árvíztűrő leírás"),
        ("test.hu", "Árvíztűrő tegnap", stamp(NOW-3600), stamp(NOW-3000), ""),
    ])
    db.commit(); db.close()
    return path


def test_saved_search_unicode_description_scope_and_disabled(tmp_path):
    path = epg(tmp_path)
    rule = searches.new_rule("árvíztűrő")
    found = searches.scan(path, [rule], [CHANNEL], now=NOW)
    assert len(found[0]["matches"]) == 1
    rule["description"] = True
    assert len(searches.scan(path, [rule], [CHANNEL], now=NOW)[0]["matches"]) == 2
    rule["channels"] = ["f"*64]
    assert not searches.scan(path, [rule], [CHANNEL], now=NOW)[0]["matches"]
    rule["enabled"] = False
    assert searches.scan(path, [rule], [CHANNEL], now=NOW) == []


def test_search_cancellation_timeout_and_readonly_missing_file(tmp_path):
    path = epg(tmp_path)
    with pytest.raises(searches.ScanCanceled):
        searches.scan(path, [], [], canceled=lambda: True)
    with pytest.raises(TimeoutError):
        searches.scan(path, [], [], budget=-1)
    missing = str(tmp_path / "missing.db")
    with pytest.raises(sqlite3.OperationalError):
        searches.scan(missing, [], [])
    assert not os.path.exists(missing)


def test_search_notifications_persist_deduplicate_and_expire(tmp_path):
    result = searches.scan(epg(tmp_path), [searches.new_rule("árvíztűrő")], [CHANNEL, dict(CHANNEL)], now=NOW)
    path = str(tmp_path / "seen.json")
    seen, count = searches.commit_seen(path, {}, result, now=NOW)
    assert count == 1
    seen2, count2 = searches.commit_seen(path, seen, result, now=NOW)
    assert count2 == 0 and seen2 == seen
    assert searches.normalize_seen(seen, now=NOW+86400) == {}


def test_full_history_keeps_current_matches_and_does_not_alert_again(tmp_path, monkeypatch):
    monkeypatch.setattr(searches, "MAX_SEEN", 3)
    old = {str(i)*64: NOW+600+i for i in range(3)}
    result = [{"matches": [{"id":"a"*64, "end_ts": NOW+3600}]}]
    path = str(tmp_path / "seen.json")
    seen, count = searches.commit_seen(path, old, result, now=NOW)
    assert count == 1 and "a"*64 in seen
    assert searches.commit_seen(path, seen, result, now=NOW)[1] == 0


def bundle():
    return {"config": {"playlists": [], "epgs": [], "favorites": ["original"]},
            "jobs": [job()], "reminders": [reminders.build(CHANNEL, job()["program"], now=NOW)], "search_seen": {}}


def test_full_backup_encrypted_roundtrip_and_wrong_password(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW)
    path = str(tmp_path / "test.aiptv")
    data = bundle()
    full_backup.export_bundle(path, data, "árvíztűrő password")
    assert "Esti" not in open(path, encoding="utf-8").read()
    assert full_backup.import_bundle(path, "árvíztűrő password") == data
    with pytest.raises(ValueError, match="password"):
        full_backup.import_bundle(path, "wrong")


def test_legacy_backup_does_not_replace_sidecars(tmp_path):
    path = str(tmp_path / "old.aiptv")
    settings_backup.export_settings(path, bundle()["config"], "secret")
    assert full_backup.import_bundle(path, "secret") == {"config": bundle()["config"]}


def test_restored_jobs_do_not_resurrect_or_start_partway_through():
    data = bundle()
    data["jobs"][0].update(status="recording", recording_id="stale-native-id")
    restored = full_backup.validate(data, now=NOW)
    assert restored["jobs"][0]["status"] == "missed"
    assert restored["jobs"][0]["recording_id"] is None
    assert data["jobs"][0]["status"] == "recording"
    data = bundle()
    assert full_backup.validate(data, now=NOW+1000)["jobs"][0]["status"] == "missed"


def test_restore_interruption_is_completed_before_next_startup(tmp_path, monkeypatch):
    targets = {key: str(tmp_path / (key+".json")) for key in bundle()}
    data = bundle()
    full_backup.stage_restore(data, targets)
    replace, calls = os.replace, []
    def fail_second(source, target):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("locked")
        replace(source, target)
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_second)
        with pytest.raises(OSError):
            full_backup.apply_pending(targets)
    assert os.path.exists(full_backup.pending_path(targets))
    assert full_backup.apply_pending(targets)
    assert not full_backup.apply_pending(targets)
    assert json.loads(open(targets["jobs"], encoding="utf-8").read())["jobs"][0]["id"] == data["jobs"][0]["id"]
    assert json.loads(open(targets["reminders"], encoding="utf-8").read())["version"] == 1


@pytest.mark.parametrize("change", [lambda d: d.update(unexpected="/etc/file"),
    lambda d: d["jobs"][0].update(start_ts=float("nan")),
    lambda d: d["jobs"].append(copy.deepcopy(d["jobs"][0])),
    lambda d: d["reminders"][0].update(channel_key="bad"), lambda d: d.pop("jobs")])
def test_invalid_full_backup_is_rejected_before_writing(change):
    data = bundle()
    change(data)
    with pytest.raises(ValueError):
        full_backup.validate(data, now=NOW)
