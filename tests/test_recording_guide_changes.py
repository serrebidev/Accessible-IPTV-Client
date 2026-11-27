"""Guide import, durable recording edits and deadline comparisons without a real provider."""

import datetime as dt
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import dvr
import playlist
import programme_reminders as reminders
import recorder
import recording_edits as edits
import recording_limits
from tools.check_hungarian_notes import problems


NOW = 1_850_000_000


def stamp(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y%m%d%H%M%S")


def station(key, source):
    return {
        "name": "Concert " + key,
        "tvg-id": key,
        "playlist-id": source,
        "url": f"https://example.invalid/{source}/{key}",
    }


def programme(start, episode="0.4.0/2", duration=1800):
    return dict(title="Matinée", episode=episode, start=stamp(start), end=stamp(start + duration))


@pytest.fixture
def guide(tmp_path):
    db = playlist.EPGDatabase(str(tmp_path / "epg.db"))
    try:
        yield db
    finally:
        db.close()


def put(db, channel, programme):
    db.insert_channel(channel["tvg-id"], channel["name"])
    db.insert_programme(
        channel["tvg-id"], programme["title"], programme["start"], programme["end"], episode=programme["episode"]
    )
    db.commit()


def test_split_xmltv_episode_survives_real_import_and_scheduler_reload(tmp_path, guide):
    a, b = station("a", "first"), station("b", "second")
    plan = [(a, 1, "0.4.0/2"), (a, 2, "0.4.1/2"), (a, 3, "0.4.0/2"), (a, 4, "0.5."), (b, 1, "0.4.0/2")]
    xml = tmp_path / "guide.xml"
    xml.write_text(
        '<tv><channel id="a"><display-name>Concert a</display-name></channel>'
        '<channel id="b"><display-name>Concert b</display-name></channel>'
        + "".join(
            f'<programme channel="{ch["tvg-id"]}" start="{stamp(NOW + h * 3600)} +0000" '
            f'stop="{stamp(NOW + h * 3600 + 1800)} +0000"><title>Matinée</title>'
            f'<episode-num system="xmltv_ns">{ep}</episode-num></programme>'
            for ch, h, ep in plan
        )
        + "</tv>",
        encoding="utf-8",
    )
    guide.import_epg_xml([str(xml)])
    date = dt.datetime.fromtimestamp(NOW, dt.timezone.utc)
    rows = guide.get_schedule(a, date, date + dt.timedelta(days=1))

    def scheduler():
        return dvr.DVRScheduler(str(tmp_path / "jobs"), on_start=Mock(), on_stop=Mock(), clock=lambda: NOW)

    s = scheduler()
    first = s.add_job(dvr.build_job(a, rows[0], "provider_mkv", repeat="series"))
    candidates = [dvr.build_job(a, r, "provider_mkv") for r in rows]
    s.add_series_episodes(first, candidates, reminders.channel_key)
    s = scheduler()
    s.add_series_episodes(first, candidates, reminders.channel_key)
    assert [j["program"]["episode"] for j in s.list_jobs()] == ["0.4.0/2", "0.4.1/2", "0.5."]
    alternate, more = edits.other_airings(guide, first, [a, b], now=NOW)
    assert not more
    assert [(ch["playlist-id"], row["episode"], same) for ch, row, same in alternate] == [
        ("second", "0.4.0/2", True),
        ("first", "0.4.0/2", True),
    ]


@pytest.mark.parametrize(
    "value,key",
    [
        ("0.4.", "ep:1x5"),
        ("S01E05", "ep:1x5"),
        ("1x5", "ep:1x5"),
        ("0/2 . 4/22 . 0/2", "ep:1x5:part1"),
        ("0.4.1", "ep:1x5:part2"),
        (".4.1/2", "ep:?x5:part2"),
        ("0.4./2", "ep:1x5"),
        ("0..0/2", None),
        ("0..", None),
    ],
)
def test_xmltv_number_and_legacy_number(value, key):
    assert dvr.program_episode_key({"episode": value}) == key


def test_large_mp4_completion_outlasts_size_budget_and_orphan_still_expires(tmp_path, monkeypatch):
    now = [NOW]
    monkeypatch.setattr(recorder.os.path, "getsize", lambda _: 16 * 1024**3)
    budget = recorder.finalize_timeout_seconds("provider_mp4", "sample.mp4")
    assert budget == 2078
    for elapsed, expected in ((1801, "completed"), (budget, "completed"), (dvr.STOP_TIMEOUT_SECONDS + 1, "failed")):
        now[0] = NOW
        s = dvr.DVRScheduler(
            str(tmp_path / str(elapsed)), on_start=Mock(return_value=1), on_stop=Mock(), clock=lambda: now[0]
        )
        job = s.add_job(dvr.build_job(station("a", "one"), programme(NOW + 600), "provider_mp4"))
        started = threading.Event()
        def update():
            if s.get_job(job["id"]).get("recording_id") == 1:
                started.set()
        s.on_update = update
        now[0] = job["start_ts"]
        s.tick()
        assert started.wait(3)
        now[0] = job["stop_ts"]
        s.tick()
        now[0] += elapsed
        s.tick()
        s.mark_finished(job["id"], success=True, output_path="sample.mp4")
        assert s.get_job(job["id"])["status"] == expected
        s.on_stop.assert_called_once()
    assert dvr.STOP_TIMEOUT_SECONDS > recorder.FINALIZE_TIMEOUT_CAP_SECONDS + recorder.TERMINATE_GRACE_SECONDS


@pytest.mark.parametrize("fmt,seconds", [("provider_mp4", 2078), ("provider_mkv", 30)])
def test_scheduler_uses_recorders_actual_budget_once_and_expires_an_orphan(tmp_path, monkeypatch, fmt, seconds):
    import threading

    now = [NOW]
    process = Mock()
    process.poll.return_value = None
    path = str(tmp_path / "in-progress.part")
    rec = recorder.Recording(7, "dvr", "", "Matinée", fmt, str(tmp_path / "done"), process, partial_path=path)
    monkeypatch.setattr(recorder.os.path, "getsize", lambda _: 16 * 1024**3)
    calculate = Mock(wraps=recorder.finalize_timeout_seconds)
    monkeypatch.setattr(recorder, "finalize_timeout_seconds", calculate)
    manager = recorder.RecordingManager()
    scheduler = dvr.DVRScheduler(
        "", on_start=lambda job: rec, on_stop=lambda job: manager._graceful_stop(rec, wait=True), clock=lambda: now[0]
    )
    # A stored video format may be remapped by the actual recorder.
    job = scheduler.add_job(dvr.build_job(station("a", "one"), programme(NOW + 600), "provider_mp4"))
    started = threading.Event()

    def update():
        if scheduler.get_job(job["id"]).get("recording_id") == 7:
            started.set()

    scheduler.on_update = update
    now[0] = job["start_ts"]
    scheduler.tick()
    assert started.wait(3)
    now[0] = job["stop_ts"]
    scheduler.tick()
    process.wait.assert_called_once_with(timeout=seconds)
    now[0] += seconds + dvr.STOP_GRACE_SECONDS
    scheduler.tick()
    assert scheduler.get_job(job["id"])["status"] == dvr.STATUS_STOPPING
    now[0] += 1
    scheduler.tick()
    assert scheduler.get_job(job["id"])["status"] == dvr.STATUS_FAILED
    calculate.assert_called_once_with(fmt, path)


def test_retime_preserves_identity_padding_and_concurrent_edits(tmp_path, guide):
    a = station("a", "one")
    s = dvr.DVRScheduler(str(tmp_path / "jobs"), on_start=Mock(), on_stop=Mock(), clock=lambda: NOW)
    original = programme(NOW + 3600)
    job = s.add_job(dvr.build_job(a, original, "provider_mkv", pre_padding_minutes=3, post_padding_minutes=7))
    moved = programme(NOW + 4800)
    put(guide, a, moved)
    put(guide, station("other", "two"), programme(NOW + 4500))
    put(guide, a, programme(NOW + 7000, episode="0.4.1/2"))
    options = edits.changed_guide_times(guide, s.list_jobs(), now=NOW)
    assert [(r["start"], exact) for _, r, exact in options] == [(moved["start"], True)]
    revision, jobs = s.edit_snapshot()
    change = edits.retime_booking(job, options[0][1], jobs, NOW)
    assert s.get_job(job["id"]) == job
    s.apply_reviewed_edit(revision, change)
    stored = s.get_job(job["id"])
    assert edits.padding(stored) == (3, 7) and stored["start_ts"] == NOW + 4800 - 180
    assert stored["stop_ts"] == NOW + 4800 + 1800 + 420
    assert not edits.changed_guide_times(guide, [stored], now=NOW)
    with pytest.raises(ValueError):
        s.apply_reviewed_edit(revision, change)


def test_retime_excludes_clock_rules_expired_and_unrelated_repeats(guide):
    a = station("a", "one")
    job = dvr.build_job(a, programme(NOW + 3600, ""), "provider_mkv")
    for offset in (3900, 14000):
        put(guide, a, programme(NOW + offset, ""))
    assert [(p["start"], e) for _, p, e in edits.changed_guide_times(guide, [job], now=NOW)] == [
        (stamp(NOW + 3900), False)
    ]
    for changes in (
        {"manual": True},
        {"repeat": "daily"},
        {"status": "recording"},
        {"start_ts": NOW},
        {"program": dict(job["program"], channel_id="other")},
    ):
        assert not edits.changed_guide_times(guide, [dict(job, **changes)], now=NOW)
    put(guide, a, job["program"])
    assert not edits.changed_guide_times(guide, [job], now=NOW)


def test_simultaneous_source_change_and_account_capacity(guide, monkeypatch):
    a, b = station("a", "first"), station("a", "second")
    p = programme(NOW + 3600)
    put(guide, a, p)
    old = dvr.build_job(a, p, "provider_mkv")
    rows, _ = edits.other_airings(guide, old, [a, b, dict(b)], now=NOW)
    assert len(rows) == 1 and rows[0][0] == b and rows[0][2]
    keep = dvr.build_job(a, programme(NOW + 3590), "provider_mkv")
    jobs = {j["id"]: j for j in (old, keep)}
    changes = edits.move_airing(old, b, rows[0][1], old["format"], jobs, NOW)
    peaks = {src: str(i) * 64 for i, src in enumerate(("first", "second"), 1)}
    monkeypatch.setattr(recording_limits, "channel_key", lambda ch, cfg: peaks[ch["playlist-id"]])
    config = {"recording_connection_limits": {key: 1 for key in peaks.values()}}
    assert not edits.warnings(config, changes, jobs)
    assert edits.warnings(config, changes, jobs | {"busy": dict(keep, id="busy", channel=b)})
    assert not edits.other_airings(guide, old, [a, dict(a, url=a["url"] + "2")], now=NOW)[0]


def test_cancelled_time_review_and_replaced_guide_never_write(guide, monkeypatch):
    import recording_edits_ui as ui

    job = dvr.build_job(station("a", "one"), programme(NOW + 3600), "provider_mkv")
    registry = {job["id"]: job}
    scheduler = SimpleNamespace(edit_snapshot=lambda: (1, registry), apply_reviewed_edit=Mock())
    owner = SimpleNamespace(config={}, _ensure_dvr_scheduler=lambda **kwargs: scheduler)

    def inline(parent, name, fn, done, dispatch):
        try:
            value = fn()
        except ValueError as error:
            done(None, error)
        else:
            done(value, None)

    monkeypatch.setattr(ui, "start_operation", inline)
    monkeypatch.setattr(ui, "confirm", lambda *args: False)
    monkeypatch.setattr(ui, "error_box", Mock())
    change = {job["id"]: dict(job, stop_ts=job["stop_ts"] + 60)}
    ui._review(object(), owner, job, lambda jobs: change, Mock(), question="Apply?")
    scheduler.apply_reviewed_edit.assert_not_called()
    monkeypatch.setattr(ui, "confirm", lambda *args: True)

    def changed():
        raise ValueError("guide changed")

    ui._review(object(), owner, job, lambda jobs: change, Mock(), question="Apply?", validate=changed)
    scheduler.apply_reviewed_edit.assert_not_called()
    ui.error_box.assert_called_once()


def test_current_release_note_is_compiled_in_hungarian():
    assert problems() == []


def test_review_panel_and_optional_import_notice_use_recorded_source_and_recheck_guide(tmp_path, monkeypatch):
    import recording_edits_ui as ui

    path = str(tmp_path / "guide")
    db = playlist.EPGDatabase(path)
    one = station("a", "first")
    old = programme(NOW + 3600)
    moved = programme(NOW + 4800)
    s = dvr.DVRScheduler(str(tmp_path / "schedule"), on_start=Mock(), on_stop=Mock(), clock=lambda: NOW)
    job = s.add_job(dvr.build_job(one, old, "provider_mkv", pre_padding_minutes=2, post_padding_minutes=3))
    owner = SimpleNamespace(config={}, _ensure_dvr_scheduler=lambda **kw: s, _show_or_queue_message_box=Mock())
    parent = SimpleNamespace(closed=False)

    def inline(parent, name, fn, done, dispatch):
        try:
            value = fn()
        except Exception as error:
            done(None, error)
        else:
            done(value, None)

    choose = Mock()
    choose.GetSelection.return_value = 0
    monkeypatch.setattr(ui, "start_operation", inline)
    monkeypatch.setattr(ui.options, "get_db_path", lambda: path)
    monkeypatch.setattr(ui.wx, "SingleChoiceDialog", Mock(return_value=choose))
    monkeypatch.setattr(ui, "show_modal", lambda dlg: ui.wx.ID_OK)
    monkeypatch.setattr(ui, "error_box", Mock())
    try:
        put(db, one, moved)
        ui.review_guide_changes(parent, owner, Mock(), notify_only=True)
        owner._show_or_queue_message_box.assert_called_once()
        assert s.get_job(job["id"]) == job

        def replace_while_confirming(*args):
            db.conn.execute("DELETE FROM programmes")
            db.commit()
            return True

        monkeypatch.setattr(ui, "confirm", replace_while_confirming)
        ui.review_guide_changes(parent, owner, Mock())
        ui.error_box.assert_called_once()
        assert s.get_job(job["id"]) == job
        put(db, one, moved)
        monkeypatch.setattr(ui, "confirm", lambda *args: True)
        notified = Mock()
        ui.review_guide_changes(parent, owner, notified)
        notified.assert_called_once()
        updated = s.get_job(job["id"])
        assert updated["program"]["start"] == moved["start"] and edits.padding(updated) == (2, 3)
    finally:
        db.close()
