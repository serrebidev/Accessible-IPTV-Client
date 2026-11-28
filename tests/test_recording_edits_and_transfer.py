import datetime as dt
import json
import time
from unittest.mock import Mock

import pytest

import dvr
import favorite_collections as collections
import favourite_transfer as transfer
import playlist
import programme_reminders as reminders
import recording_edits as edits


def channel(key, source="first", name="Concert", url=None):
    return {"name": name, "playlist-id": source, "tvg-id": key, "url": url or f"https://{source}.invalid/{key}"}


def show(start, episode="1x01"):
    stamp = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    return dict(title="Concert", start=stamp(start), end=stamp(start + 1800), episode=episode)


@pytest.fixture()
def data(tmp_path):
    now = int(time.time())
    return now, dvr.DVRScheduler(str(tmp_path / "schedule"), on_start=Mock(), on_stop=Mock(), clock=lambda: now)


@pytest.mark.parametrize("repeat", ["", "daily", "weekly", "weekdays", "series"])
@pytest.mark.parametrize("future", [False, True])
def test_padding_preserves_guide_archive_times_and_scopes(data, repeat, future):
    now, s = data
    first = dvr.build_job(
        channel("one"), show(now + 86400), "provider_mkv", pre_padding_minutes=2, post_padding_minutes=3
    )
    first.update(repeat=repeat, weekdays=[0, 2, 4])
    s.add_job(first)
    if repeat == "series":
        child = dict(
            dvr.build_job(
                first["channel"],
                show(now + 2 * 86400, "1x2"),
                first["format"],
                pre_padding_minutes=2,
                post_padding_minutes=3,
            ),
            series_source=first["id"],
        )
        s.add_job(child)
    revision, jobs = s.edit_snapshot()
    new = edits.edit_padding(first, 5, 20, future, jobs, now)
    s.apply_reviewed_edit(revision, new)
    stored = s.get_job(first["id"])
    assert (
        stored["program"] == first["program"]
        and stored["start_at"] == first["start_at"]
        and stored["end_at"] == first["end_at"]
    )
    assert (stored["start_ts"], stored["stop_ts"]) == (first["start_ts"] - 180, first["stop_ts"] + 1020)
    if repeat in dvr.TIME_REPEATS:
        next_one = dvr.next_time_occurrence(stored, now)
        assert edits.padding(next_one) == ((5, 20) if future else (2, 3))
    if repeat == "series":
        assert edits.padding(s.get_job(child["id"])) == ((5, 20) if future else (2, 3))
    with pytest.raises(ValueError):
        s.apply_reviewed_edit(revision, new)


def test_find_confirm_and_move_one_airing_atomically(tmp_path, data, monkeypatch):
    now, s = data
    one, two = channel("A"), channel("B", "second")
    p = show(now + 3600)
    parent = s.add_job(dvr.build_job(one, p, "provider_mkv", repeat="weekly"))
    db = playlist.EPGDatabase(str(tmp_path / "epg"))
    try:
        for ch in (one, two):
            db.insert_channel(ch["tvg-id"], ch["name"])
        for ch, hours, episode in [
            (one, 1, "1x01"),
            (one, 2, "1x02"),
            (two, 3, "S01E01"),
            (two, 4, ""),
            (two, 400, "1x01"),
        ]:
            item = show(now + hours * 3600, episode)
            db.insert_programme(ch["tvg-id"], item["title"], item["start"], item["end"], episode=episode)
        db.commit()
        results, truncated = edits.other_airings(db, parent, [one, two], now=now)
        assert not truncated and [(ch["tvg-id"], exact) for ch, p, exact in results] == [("B", True), ("B", False)]
        revision, jobs = s.edit_snapshot()
        ch, replacement, _ = results[0]
        update = edits.move_airing(parent, ch, replacement, "provider_mkv", jobs, now)
        with monkeypatch.context() as failure:
            failure.setattr(s, "_write_proposal", Mock(side_effect=OSError("disk")))
            with pytest.raises(OSError):
                s.apply_reviewed_edit(revision, update)
        assert s.get_job(parent["id"]) == parent and len(s.list_jobs()) == 1
        s.apply_reviewed_edit(revision, update, future_start=now + 3 * 3600)
        assert s.get_job(parent["id"])["status"] == dvr.STATUS_SKIPPED
        remaining = s.list_jobs(include_done=False)
        assert len(remaining) == 2
        assert any(j["repeat"] == "weekly" and j["channel"] == one for j in remaining)
        assert any(j["program"] == replacement and j["channel"] == two for j in remaining)
    finally:
        db.close()


def test_moving_one_series_airing_keeps_rule_and_cancels_replacement_with_parent(data):
    now, s = data
    src = channel("A")
    parent = s.add_job(dvr.build_job(src, show(now + 3600), "provider_mkv", repeat="series"))
    rev, jobs = s.edit_snapshot()
    update = edits.move_airing(parent, channel("B"), show(now + 7200), "provider_mkv", jobs, now)
    s.apply_reviewed_edit(rev, update)
    child = s.list_jobs(include_done=False)[0]
    assert child["series_source"] == parent["id"] and s.get_job(parent["id"])["repeat"] == "series"
    s.cancel_job(parent["id"])
    assert s.get_job(child["id"])["status"] == dvr.STATUS_CANCELED


def test_edit_from_a_series_child_keeps_earlier_airings_and_default_for_backfilled_guide(data):
    now, scheduler = data
    first = scheduler.add_job(dvr.build_job(channel("A"), show(now + 3600), "provider_mkv", repeat="series"))
    episodes = []
    for day in (1, 2, 3):
        job = dvr.build_job(first["channel"], show(now + day * 86400), "provider_mkv")
        episodes.append(scheduler.add_job(dict(job, series_source=first["id"])))
    revision, jobs = scheduler.edit_snapshot()
    edits_to_apply = edits.edit_padding(episodes[1], 4, 21, True, jobs, now)
    scheduler.apply_reviewed_edit(revision, edits_to_apply)
    stored = scheduler.get_job(first["id"])
    assert edits.padding(stored) == edits.padding(first)
    assert tuple(dvr.series_padding_at(stored, episodes[0]["program"]["start"])) == edits.padding(first)
    assert tuple(dvr.series_padding_at(stored, episodes[2]["program"]["start"])) == (4, 21)
    assert [edits.padding(scheduler.get_job(ep["id"])) for ep in episodes] == [edits.padding(first), (4, 21), (4, 21)]
    assert dvr.valid_stored_job(stored)


def test_portable_list_preserves_order_missing_and_ambiguous_channels(tmp_path):
    chs = [channel("north"), channel("south", name="Other"), channel("gone", name="Gone")]
    lists, ident = collections.create([], "Rádiók")
    for ch in chs:
        lists = collections.edit(lists, ident, add=ch)
    path = tmp_path / "radio.aiptvfav"
    transfer.export_list(path, lists[0], chs)
    text = path.read_text()
    assert "https:" not in text and "first.invalid" not in text
    bundle = transfer.read_list(path)
    local = [channel("north", "A"), channel("north", "B"), channel("south", "B", name="Renamed")]
    rows = transfer.match(bundle["entries"], local)
    assert [len(options) for _, options in rows] == [2, 1, 0]
    entries = transfer.build_entries(rows, [1, 0, None])
    assert entries[1]["key"] == reminders.channel_key(local[-1])
    imported = {"id": ident, "name": "Imported", "entries": entries}
    matched = collections.resolve(collections.normalize([imported])[0]["entries"], local)
    assert matched[0][1] in local[:2] and matched[1][1] == local[-1] and matched[2][1] is None
    second = tmp_path / "second.aiptvfav"
    transfer.export_list(second, imported, local)
    assert transfer.read_list(second)["entries"][-1] == bundle["entries"][-1]
    bundle["entries"][0]["url"] = "https://example.invalid/login"
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError):
        transfer.read_list(path)


def test_portable_list_excludes_address_like_labels_and_refuses_duplicate_choices(tmp_path):
    name = "https://example.invalid/secret"
    ch = channel("https://private.invalid/provider", name=name)
    lists, ident = collections.create([], "Media")
    lists = collections.edit(lists, ident, add=ch)
    path = tmp_path / "safe"
    transfer.export_list(path, lists[0], [ch])
    assert "private.invalid" not in path.read_text() and "secret" not in path.read_text()
    rows = transfer.match(transfer.read_list(path)["entries"], [ch])
    with pytest.raises(ValueError):
        transfer.build_entries(rows + rows, [0, 0])


def test_favourite_import_can_resolve_two_local_streams_with_the_same_name_id_and_source(tmp_path):
    one, two = (channel("same", url="http://example.invalid/" + route) for route in ("a", "b"))
    entry = dict(name=one["name"], key=reminders.channel_key(one), guide=transfer.guide_key(one))
    rows = transfer.match([entry], [one, one, two])
    assert len(rows[0][1]) == 2
    entries = transfer.build_entries(rows, [1])
    lists, identity = collections.create([], "Kedvencek")
    lists[0]["entries"] = entries
    (normalized,) = collections.normalize(lists)
    assert collections.resolve(normalized["entries"], [two, one])[0][1] == two
    assert collections.resolve(normalized["entries"], [one])[0][1] is None
    path = tmp_path / "one.aiptvfav"
    transfer.export_list(path, normalized, [one, two])
    assert transfer.read_list(path)["entries"] == [entry]
    assert entries[0]["variant"] not in path.read_text()
