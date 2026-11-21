"""Regression tests for crash recovery, non-blocking edits and per-file diagnostics."""
import datetime as dt
import json
import os
from pathlib import Path
import threading
import time
from unittest.mock import patch

import pytest

import dvr
import recorder
import recording_library as library


CHANNEL = {"name": "Duna", "tvg-id": "duna", "url": "https://example.invalid/tv"}
PROGRAM = {"title": "Esti műsor", "start": "20261116200000", "end": "20261116210000"}


def job(repeat="", state="scheduled"):
    row = dvr.build_job(CHANNEL, PROGRAM, "provider_mkv", job_id="original",
                        repeat=repeat, pre_padding_minutes=3, post_padding_minutes=7)
    row["status"] = state
    if repeat == "weekdays":
        row.update(repeat=repeat, weekdays=[0, 3])
    return row


def scheduler(path, now, start=lambda _row: 1):
    return dvr.DVRScheduler(str(path), clock=lambda: now, on_start=start, on_stop=lambda _row: None)


@pytest.mark.parametrize("state", ["recording", "stopping"])
@pytest.mark.parametrize(("repeat", "next_day"), [("daily", "17"), ("weekly", "23"), ("weekdays", "19")])
def test_restart_recovers_one_padded_successor_durably(tmp_path, state, repeat, next_day):
    path = tmp_path / "schedule.json"
    row = job(repeat, state)
    row.update(recording_id=43, output_path="partial.mkv")
    path.write_text(json.dumps({"jobs": [row]}))
    now = dvr.parse_epg_utc("20261117060000").timestamp()
    sched = scheduler(path, now)
    assert sched.get_job("original")["output_path"] == "partial.mkv"
    assert sched.get_job("original")["status"] == dvr.STATUS_FAILED
    pending, = sched.list_jobs(include_done=False)
    assert pending["status"] == "scheduled" and pending["output_path"] == ""
    assert pending["program"]["start"] == f"202611{next_day}200000"
    assert pending["program"]["end"] == f"202611{next_day}210000"
    assert pending["start_ts"] + 180 == dvr.parse_epg_utc(pending["program"]["start"]).timestamp()
    assert pending["stop_ts"] - 420 == dvr.parse_epg_utc(pending["program"]["end"]).timestamp()
    assert scheduler(path, now).list_jobs(include_done=False) == [pending]


@pytest.mark.parametrize("repeat,state,expected", [("daily", "canceled", "canceled"), ("", "recording", "failed")])
def test_cancel_and_once_do_not_spawn_successors(tmp_path, repeat, state, expected):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"jobs": [job(repeat, state)]}))
    row, = scheduler(path, dvr.parse_epg_utc("20261118000000").timestamp()).list_jobs()
    assert row["status"] == expected


@pytest.mark.parametrize("repeat", ["daily", "weekly", "weekdays"])
def test_skip_one_is_atomic_and_stale_actions_cannot_skip_twice(tmp_path, repeat):
    path = tmp_path / "schedule.json"
    original = job(repeat)
    sched = scheduler(path, original["start_ts"] - 1000)
    sched.add_job(original)
    old_bytes = path.read_bytes()
    with patch.object(sched, "_write_proposal", side_effect=OSError("disk full")), pytest.raises(OSError):
        sched.skip_occurrence("original", expected_start=original["start_ts"])
    assert path.read_bytes() == old_bytes and sched.get_job("original")["status"] == "scheduled"
    with pytest.raises(ValueError):
        sched.skip_occurrence("original", expected_start=0)
    successor = sched.skip_occurrence("original", expected_start=original["start_ts"])
    with pytest.raises(ValueError):
        sched.skip_occurrence("original", expected_start=original["start_ts"])
    reloaded = scheduler(path, original["start_ts"] - 1000)
    assert reloaded.get_job("original")["status"] == "skipped"
    assert reloaded.list_jobs(include_done=False) == [successor]


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="requires a per-process local timezone")
def test_weekly_after_clock_change_keeps_local_wall_time_and_padding(tmp_path):
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Budapest"
    time.tzset()
    try:
        program = dict(PROGRAM, start="20261023180000", end="20261023190000")
        row = dvr.build_job(CHANNEL, program, "provider_mkv", repeat="weekly", pre_padding_minutes=4)
        sched = scheduler(tmp_path / "clock.json", row["start_ts"] - 1000)
        sched.add_job(row)
        next_row = sched.skip_occurrence(row["id"], expected_start=row["start_ts"])
        assert next_row["program"]["start"] == "20261030190000"
        assert dt.datetime.fromtimestamp(next_row["start_ts"]).strftime("%H:%M") == "19:56"
    finally:
        if previous is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = previous
        time.tzset()


def test_blocked_disk_allows_reads_and_starts_another_recording(tmp_path):
    path = tmp_path / "schedule.json"
    due = job()
    started, saving, release = threading.Event(), threading.Event(), threading.Event()
    def on_start(_row):
        started.set()
        return 23
    sched = scheduler(path, due["start_ts"] + 5, start=on_start)
    sched.add_job(due)
    future = dict(due, id="future", start_ts=due["start_ts"] + 86400, stop_ts=due["stop_ts"] + 86400)
    fsync = os.fsync
    def hold(fd):
        saving.set()
        assert release.wait(5)
        fsync(fd)
    errors = []
    def add():
        try:
            sched.add_job(future)
        except Exception as error:
            errors.append(error)
    with patch.object(dvr.os, "fsync", hold):
        writer = threading.Thread(target=add)
        writer.start()
        try:
            assert saving.wait(2)
            assert [j["id"] for j in sched.list_jobs()] == ["original"]
            sched.tick()
            assert started.wait(2)
            assert sched.get_job("original")["status"] == "recording"
            assert not sched.get_job("future")
        finally:
            release.set()
            writer.join(5)
            sched.stop(wait=True)
    sched.save()
    assert not errors
    by_id = {j["id"]: j for j in json.loads(path.read_text())["jobs"]}
    assert set(by_id) == {"original", "future"}
    assert by_id["original"]["recording_id"] == 23


def test_50_trash_items_read_only_their_own_journals(tmp_path):
    for i in range(50):
        (tmp_path / f"{i}.mkv").write_bytes(b"fixture")
    for row in library.scan(tmp_path):
        library.trash(tmp_path, row)
    selected = library.scan_trash(tmp_path)
    with patch.object(library, "_read", wraps=library._read) as read:
        for row in selected:
            library.delete_trashed(tmp_path, row)
    assert len(selected) == read.call_count == 50
    assert library.scan_trash(tmp_path) == []


def test_one_pass_handles_cr_progress_and_limited_repeats(tmp_path):
    path = tmp_path / "fixture.log"
    day = "2026-11-17 20:00:"
    lines = [day + "00.000 [info] Output #0 to file local.mkv",
             day + "01.000 [mpegts @ 0001] [warning] Packet discontinuity",
             day + "02.000 [info] time=00:00:01.50 speed=1.0x",
             day + "04.000 [mpegts @ 0001] [warning] Packet discontinuity",
             day + "04.000 Last message repeated 10000 times"]
    path.write_bytes(("\r".join(lines) + "\n").encode())
    with patch.object(recorder, "parse_log_line", wraps=recorder.parse_log_line) as parse:
        issue, = recorder.recording_problem_times(str(path), max_times=3)
    assert parse.call_count <= len(lines)
    assert issue["count"] == 10002
    assert issue["positions"] == [("0:00:01", True), ("0:00:02", False)]
    assert len(issue["clock_times"]) == 3


def test_problem_log_must_belong_to_selected_unchanged_recording(tmp_path):
    path = tmp_path / "film.mkv"
    path.write_bytes(b"media")
    row, = library.scan(tmp_path)
    log = Path(recorder.recording_log_path(str(tmp_path), str(path)))
    log.parent.mkdir()
    def write_footer(media, extra):
        lines = [recorder._SUMMARY_MARKER, f"# File: {media}", *extra, "diagnostic detail" * 5000]
        log.write_text("\n".join(lines))
    signature = [f"# Media signature: {row['size']} {row['modified_ns']}"]
    write_footer(path, signature)
    assert library.problem_log(tmp_path, row) == str(log)
    with pytest.raises(ValueError):
        library.problem_log(tmp_path, row, [str(path)])
    write_footer(tmp_path / "unrelated.mkv", signature)
    with pytest.raises(ValueError):
        library.problem_log(tmp_path, row)
    write_footer(path, signature)
    path.write_bytes(b"new media")
    with pytest.raises(ValueError):
        library.problem_log(tmp_path, library.scan(tmp_path)[0])
    stamp = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    write_footer(path, [f"# Started: {stamp}", f"# Ended: {stamp} (ran for 0:00:01)"])
    assert library.problem_log(tmp_path, library.scan(tmp_path)[0]) == str(log)
    write_footer(path, ["# Started: 2000-01-01 00:00:00", "# Ended: 2000-01-01 00:01:00 (ran for 0:01:00)"])
    with pytest.raises(ValueError):
        library.problem_log(tmp_path, library.scan(tmp_path)[0])


def test_stale_log_reserves_its_filename_across_formats(tmp_path):
    rec = recorder.RecordingManager()
    when = dt.datetime(2026, 11, 21, 19, 30)
    original = rec._unique_output_path(str(tmp_path), "Híradó", "mkv", when)
    log = Path(recorder.recording_log_path(str(tmp_path), original))
    log.parent.mkdir()
    log.write_text("old recording")
    new = rec._unique_output_path(str(tmp_path), "Híradó", "ts", when)
    assert Path(new).stem != Path(original).stem and log.read_text() == "old recording"


def test_broken_compiled_hungarian_notes_are_reported(tmp_path, monkeypatch):
    from tools import check_hungarian_notes as check
    folder = tmp_path / "locale/hu/LC_MESSAGES"
    folder.mkdir(parents=True)
    (folder / "release_notes.po").write_text('msgid "Title"\nmsgstr "Cím"\n')
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setattr(check.i18n_tools, "extract_release_notes", lambda: {"Title": {}})
    assert check.problems() == ["Title"]
    (folder / "release_notes.mo").write_bytes(b"broken")
    assert check.problems() == ["Title"]


def test_reviewed_notes_match_only_exact_subject_and_preserve_translated_entries(tmp_path):
    from tools import i18n_tools as i18n
    (tmp_path / "release-note-translations-example.json").write_text(json.dumps(
        {"translations": {"New feature": {"hu": "Új funkció"}}}))
    ids = ["New feature (#40)", "New feature in beta (#40)", "New feature"]
    messages = {key: {"locations": set(), "plural": None} for key in ids}
    hu = i18n.prepared_notes(messages, tmp_path)["hu"]
    assert hu == {"New feature (#40)": "Új funkció (#40)", "New feature": "Új funkció"}
    po = tmp_path / "release_notes.po"
    po.write_text('msgid "New feature"\nmsgstr "Meglévő fordítás"\n', encoding="utf-8")
    i18n.update_po(str(po), messages, reviewed=hu)
    assert {entry["msgid"]: entry["msgstr"] for entry in i18n.parse_po(str(po))} == {
        ids[0]: "Új funkció (#40)", ids[1]: "", ids[2]: "Meglévő fordítás"}
