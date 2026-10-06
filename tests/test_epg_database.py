"""
Tests for EPG database freshness helpers.
"""
import datetime
import gzip
import hashlib
import io
import os
import random
import sqlite3
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import playlist
from playlist import (
    EPGDatabase,
    _derive_playlist_region,
    _detect_region_from_id,
    _expand_tvg_id_candidates,
    _http_download_gz_with_resume,
    _ordered_channel_tokens,
    _parse_xmltv_to_utc_str,
    canonicalize_name,
    epg_database_has_usable_data,
    extract_callsigns,
    extract_group,
    strip_noise_words,
    tokenize_channel_name,
)


def test_import_lock_from_exited_process_is_recovered(tmp_path):
    db_path = str(tmp_path / "epg.db")
    lock_path, pid_path = playlist._import_lock_paths(db_path)
    with open(lock_path, "w", encoding="ascii") as handle:
        handle.write("locked")
    with open(pid_path, "w", encoding="ascii") as handle:
        handle.write("999999999")
    os.utime(lock_path, (time.time() - 2, time.time() - 2))

    started = time.monotonic()
    assert playlist._try_acquire_import_lock(db_path, max_wait_sec=1)
    assert time.monotonic() - started < 1
    playlist._release_import_lock(db_path)


def _create_epg_schema(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE channels (
            id TEXT PRIMARY KEY,
            display_name TEXT,
            norm_name TEXT,
            group_tag TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE programmes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            title TEXT,
            start TEXT,
            end TEXT
        )
        """
    )
    conn.commit()
    return conn


def _xmltv_time(dt):
    return dt.strftime("%Y%m%d%H%M%S")


def test_epg_database_missing_file_is_not_usable(tmp_path):
    assert not epg_database_has_usable_data(str(tmp_path / "missing.db"))


def test_epg_database_without_tables_is_not_usable(tmp_path):
    path = tmp_path / "epg.db"
    sqlite3.connect(path).close()

    assert not epg_database_has_usable_data(str(path))


def test_epg_database_with_only_past_programmes_is_not_usable(tmp_path):
    path = tmp_path / "epg.db"
    now = datetime.datetime(2026, 5, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)
    conn = _create_epg_schema(path)
    conn.execute("INSERT INTO channels (id, display_name) VALUES (?, ?)", ("ch1", "Channel 1"))
    conn.execute(
        "INSERT INTO programmes (channel_id, title, start, end) VALUES (?, ?, ?, ?)",
        (
            "ch1",
            "Old Show",
            _xmltv_time(now - datetime.timedelta(hours=2)),
            _xmltv_time(now - datetime.timedelta(hours=1)),
        ),
    )
    conn.commit()
    conn.close()

    assert not epg_database_has_usable_data(str(path), now)


def test_epg_database_requires_joined_future_programmes(tmp_path):
    path = tmp_path / "epg.db"
    now = datetime.datetime(2026, 5, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)
    conn = _create_epg_schema(path)
    conn.execute(
        "INSERT INTO programmes (channel_id, title, start, end) VALUES (?, ?, ?, ?)",
        (
            "missing-channel",
            "Future Show",
            _xmltv_time(now),
            _xmltv_time(now + datetime.timedelta(hours=1)),
        ),
    )
    conn.commit()
    conn.close()

    assert not epg_database_has_usable_data(str(path), now)


def test_epg_database_with_joined_future_programmes_is_usable(tmp_path):
    path = tmp_path / "epg.db"
    now = datetime.datetime(2026, 5, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)
    conn = _create_epg_schema(path)
    conn.execute("INSERT INTO channels (id, display_name) VALUES (?, ?)", ("ch1", "Channel 1"))
    conn.execute(
        "INSERT INTO programmes (channel_id, title, start, end) VALUES (?, ?, ?, ?)",
        (
            "ch1",
            "Current Show",
            _xmltv_time(now - datetime.timedelta(minutes=30)),
            _xmltv_time(now + datetime.timedelta(minutes=30)),
        ),
    )
    conn.commit()
    conn.close()

    assert epg_database_has_usable_data(str(path), now)


def test_iptv_org_tvg_id_suffixes_keep_base_region():
    assert _detect_region_from_id("9Gem.au@Sydney") == "au"
    assert _detect_region_from_id("DareToDreamNetwork.us@SD") == "us"
    assert _detect_region_from_id("F1Channel.ie@US") == "ie"


def test_epgshare01_style_ids_resolve_trailing_country_segment():
    # epgshare01_ALL_SOURCES ids are "Name.With.Dots.xx"; some carry a disambiguating
    # digit ("ca2"/"in2" = second source for that country), which must still resolve.
    assert _detect_region_from_id("Dubai.ae") == "ae"
    assert _detect_region_from_id("Sama.Dubai.ae") == "ae"
    assert _detect_region_from_id("Dubai.Sports.1.ae") == "ae"
    assert _detect_region_from_id("Z.HD.ca2") == "ca"
    assert _detect_region_from_id("Star.Plus.in2") == "in"
    # A parenthetical qualifier and an embedded word ("de" = Spanish "of") in the id
    # itself must not distract from the real trailing country segment "ar".
    assert _detect_region_from_id("Canal.13.de.Argentina.(El.Trece).ar") == "ar"


def test_detect_region_from_id_ignores_prefix_collision_in_non_country_suffix_ids():
    # Regression: the last-resort fallback used to scan the *whole* id for the first
    # 2-3 letter run and treat it as a country code. epgshare01 uses non-country
    # source/brand suffixes (PEACOCK, bein, distro, dtvsp) on some ids; since none of
    # their dot-segments resolve, the old code fell through to that whole-string scan
    # and latched onto a coincidental prefix of the *channel name* instead of admitting
    # it doesn't know the region. A safe '' beats a confidently wrong country.
    assert _detect_region_from_id("Bravo.PEACOCK") == ""            # was "br" (Brazil)
    assert _detect_region_from_id("InDemand.PEACOCK") == ""         # was "in" (India)
    assert _detect_region_from_id("Cartoon.Network.PEACOCK") == ""  # was "ca" (Canada)
    assert _detect_region_from_id("Cheddar.News.distro") == ""      # was "ch" (Switzerland)
    assert _detect_region_from_id("Brave.News.dtvsp") == ""         # was "br" (Brazil)
    assert _detect_region_from_id("ESPN.Deportes.dtvsp") == ""      # was "es" (Spain)
    assert _detect_region_from_id("Independent.Voice.bein") == ""   # was "in" (India)
    # A genuine trailing country segment must still win despite the same suffix shape.
    assert _detect_region_from_id("USA.Network.PEACOCK") == "us"


def test_detect_region_from_id_handles_non_latin_scripts():
    assert _detect_region_from_id("Rotana.Cinema.sa") == "sa"
    assert _detect_region_from_id("Первый.Канал.ru") == "ru"  # Cyrillic id
    assert _detect_region_from_id("中央电视台.cn") == "cn"  # Chinese id
    assert _detect_region_from_id("قناة.دبي.ae") == "ae"  # Arabic id
    assert _detect_region_from_id("한국방송공사.kr") == "kr"  # Korean id
    # No dot-delimited country segment at all: stay empty rather than guess.
    assert _detect_region_from_id("中央电视台") == ""


def test_iptv_org_tvg_id_expansion_adds_city_variant():
    assert _expand_tvg_id_candidates("9Gem.au@Sydney") == [
        "9Gem.au@Sydney",
        "9Gem.au",
        "9GemSydney.au",
    ]
    assert _expand_tvg_id_candidates("DareToDreamNetwork.us@SD") == [
        "DareToDreamNetwork.us@SD",
        "DareToDreamNetwork.us",
    ]
    assert "antennatv.us" in _expand_tvg_id_candidates("antennatvhd.us")
    assert "altitudesports.us" in _expand_tvg_id_candidates("altitudesport.us")


def test_playlist_region_prefers_tvg_id_country_over_california_abbreviation():
    channel = {
        "name": "ABC 10 San Diego CA (KGTV) (720p)",
        "group": "General",
        "tvg-id": "KGTV101.us@HD",
        "tvg-name": "",
    }

    assert _derive_playlist_region(channel) == "us"


def test_ordered_channel_tokens_skip_quality_and_geoblock_noise():
    assert _ordered_channel_tokens("9Gem (720p) [Geo-blocked]")[:2] == ["9gem"]


def test_text_normalizers_handle_unicode_and_edge_cases_without_crashing():
    samples = [
        "Dubai", "روتانا سينما", "Первый канал", "中央电视台", "ΕΡΤ1", "כאן 11",
        "ไทยรัฐทีวี", "한국방송공사", "NHK総合", "", "   ", "!!!", "@Sydney", None,
    ]
    for s in samples:
        canonicalize_name(s)
        strip_noise_words(s)
        extract_group(s)
        tokenize_channel_name(s)
        extract_callsigns(s)


def test_insert_channel_handles_real_world_and_multiscript_ids(tmp_path):
    path = tmp_path / "epg.db"
    db = EPGDatabase(str(path))
    rows = [
        ("Dubai.ae", "Dubai"),
        ("Canal.13.de.Argentina.(El.Trece).ar", "Canal 13 de Argentina (El Trece)"),
        ("Rotana.Cinema.sa", "روتانا سينما"),
        ("Channel.One.Russia.ru", "Первый канал"),
        ("CCTV.1.cn", "中央电视台"),
        ("Kan.11.il", "כאן 11"),
        ("ERT.1.gr", "ΕΡΤ1"),
        ("Thairath.TV.th", "ไทยรัฐทีวี"),
        ("Bravo.PEACOCK", "Bravo"),
        ("beIN.Sports.1.bein", "beIN Sports 1"),
        ("Newsy.distro", "Newsy"),
        ("ESPN.Deportes.dtvsp", "ESPN Deportes"),
        ("Z.HD.ca2", "Z HD"),
        ("Star.Plus.in2", "Star Plus"),
    ]
    for ch_id, name in rows:
        db.insert_channel(ch_id, name)
    db.commit()
    tags = dict(db.conn.execute("SELECT id, group_tag FROM channels").fetchall())
    db.close()

    # id-derived region wins even though the display name contains "de" (Spanish "of",
    # which also happens to be the German group synonym) -- avoids a false "de" tag.
    assert tags["Canal.13.de.Argentina.(El.Trece).ar"] == "ar"
    assert tags["Rotana.Cinema.sa"] == "sa"
    assert tags["Channel.One.Russia.ru"] == "ru"
    assert tags["CCTV.1.cn"] == "cn"
    assert tags["Z.HD.ca2"] == "ca"
    assert tags["Star.Plus.in2"] == "in"
    # Non-country source suffixes must not produce a confidently wrong group tag.
    assert tags["Bravo.PEACOCK"] == ""
    assert tags["beIN.Sports.1.bein"] == ""
    assert tags["Newsy.distro"] == ""
    assert tags["ESPN.Deportes.dtvsp"] == ""


def test_candidate_rows_stay_bounded_for_short_or_unicode_names(tmp_path):
    path = tmp_path / "epg.db"
    db = EPGDatabase(str(path))
    for i in range(30):
        db.insert_channel(f"filler{i}.us", f"Filler Channel {i}")
    db.insert_channel("CCTV.1.cn", "中央电视台")
    db.commit()

    c = db.conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    # None of these should degrade into an unfiltered table scan (e.g. via a
    # LIKE '%%' built from an empty brand/token key).
    for name, tvg_name, region in [("", "", ""), ("x", "", ""), ("!!!", "", ""), ("中", "", "cn")]:
        out = db._candidate_rows(c, name, tvg_name, region)
        assert len(out) < total
    db.close()


def test_region_repair_fixes_mismatch_and_marks_user_version(tmp_path):
    # A row written under old/buggy logic (or hand-corrupted) with an id that clearly
    # encodes "us" but a stale/wrong group_tag of "ca" must get corrected the first
    # time a writable EPGDatabase is opened against it.
    path = tmp_path / "epg.db"
    conn = _create_epg_schema(path)
    conn.execute(
        "INSERT INTO channels (id, display_name, norm_name, group_tag) VALUES (?, ?, ?, ?)",
        ("Some.Channel.us", "Some Channel", "somechannel", "ca"),
    )
    conn.commit()
    conn.close()

    db = EPGDatabase(str(path))
    try:
        group_tag = db.conn.execute(
            "SELECT group_tag FROM channels WHERE id = ?", ("Some.Channel.us",)
        ).fetchone()[0]
        user_version = db.conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()

    assert group_tag == "us"
    assert user_version == playlist._REGION_REPAIR_SCHEMA_VERSION


def test_region_repair_skips_full_table_scan_once_already_versioned(tmp_path, monkeypatch):
    # First open repairs (and version-stamps) the DB. A *second* open of the same,
    # already-stamped DB must not re-scan the channels table at all: patch
    # _detect_region_from_id to count calls, hand-corrupt a row's group_tag without
    # going through insert_channel, and confirm the (gated) repair pass makes zero
    # calls into the per-row region detector and leaves the corruption untouched.
    path = tmp_path / "epg.db"
    db = EPGDatabase(str(path))
    db.insert_channel("Some.Channel.us", "Some Channel")
    db.commit()
    db.close()

    # Re-corrupt directly via SQL (bypassing insert_channel's own correct-at-insert
    # logic) to simulate a row that would need fixing if the scan actually ran.
    conn = sqlite3.connect(path)
    conn.execute("UPDATE channels SET group_tag = 'ca' WHERE id = ?", ("Some.Channel.us",))
    conn.commit()
    conn.close()

    calls = []
    real_detect = playlist._detect_region_from_id

    def counting_detect(ch_id):
        calls.append(ch_id)
        return real_detect(ch_id)

    monkeypatch.setattr(playlist, "_detect_region_from_id", counting_detect)

    db2 = EPGDatabase(str(path))
    try:
        group_tag = db2.conn.execute(
            "SELECT group_tag FROM channels WHERE id = ?", ("Some.Channel.us",)
        ).fetchone()[0]
    finally:
        db2.close()

    assert calls == []  # no per-row scan happened
    assert group_tag == "ca"  # left untouched -- proves the scan, not luck, was skipped


def test_region_repair_reruns_after_schema_version_bump(tmp_path, monkeypatch):
    # Correctness guarantee: when _detect_region_from_id's logic changes (modeled here
    # by bumping the schema-version constant), a previously-versioned DB must still get
    # one more full repair pass so stale mismatches from before the logic change get
    # fixed -- the version gate must not permanently hide real mismatches.
    path = tmp_path / "epg.db"
    db = EPGDatabase(str(path))
    db.insert_channel("Some.Channel.us", "Some Channel")
    db.commit()
    stamped_version = db.conn.execute("PRAGMA user_version").fetchone()[0]
    db.close()

    conn = sqlite3.connect(path)
    conn.execute("UPDATE channels SET group_tag = 'ca' WHERE id = ?", ("Some.Channel.us",))
    conn.commit()
    conn.close()

    monkeypatch.setattr(playlist, "_REGION_REPAIR_SCHEMA_VERSION", stamped_version + 1)

    db2 = EPGDatabase(str(path))
    try:
        group_tag = db2.conn.execute(
            "SELECT group_tag FROM channels WHERE id = ?", ("Some.Channel.us",)
        ).fetchone()[0]
        new_version = db2.conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db2.close()

    assert group_tag == "us"
    assert new_version == stamped_version + 1


def test_norm_repair_fixes_mismatch_and_marks_application_id(tmp_path):
    # Mirrors test_region_repair_fixes_mismatch_and_marks_user_version, but for
    # _repair_norm_names/_NORM_REPAIR_SCHEMA_VERSION (gated via PRAGMA application_id
    # instead of user_version, since region-repair already owns user_version).
    path = tmp_path / "epg.db"
    conn = _create_epg_schema(path)
    conn.execute(
        "INSERT INTO channels (id, display_name, norm_name, group_tag) VALUES (?, ?, ?, ?)",
        ("chan1.us", "Some Channel HD", "totally-stale-value", "us"),
    )
    conn.commit()
    conn.close()

    db = EPGDatabase(str(path))
    try:
        norm_name = db.conn.execute(
            "SELECT norm_name FROM channels WHERE id = ?", ("chan1.us",)
        ).fetchone()[0]
        app_id = db.conn.execute("PRAGMA application_id").fetchone()[0]
    finally:
        db.close()

    assert norm_name == canonicalize_name(strip_noise_words("Some Channel HD"))
    assert app_id == playlist._NORM_REPAIR_SCHEMA_VERSION


def test_norm_repair_skips_full_table_scan_once_already_versioned(tmp_path, monkeypatch):
    # Mirrors test_region_repair_skips_full_table_scan_once_already_versioned: a second
    # open of an already-versioned DB must not re-run canonicalize_name at all, even
    # when a row has been hand-corrupted (bypassing insert_channel) since the first open.
    path = tmp_path / "epg.db"
    db = EPGDatabase(str(path))
    db.insert_channel("chan1.us", "Some Channel HD")
    db.commit()
    db.close()

    conn = sqlite3.connect(path)
    conn.execute("UPDATE channels SET norm_name = 'recorrupted' WHERE id = ?", ("chan1.us",))
    conn.commit()
    conn.close()

    calls = []
    real_canon = playlist.canonicalize_name

    def counting_canon(*args, **kwargs):
        calls.append(args)
        return real_canon(*args, **kwargs)

    monkeypatch.setattr(playlist, "canonicalize_name", counting_canon)

    db2 = EPGDatabase(str(path))
    try:
        norm_name = db2.conn.execute(
            "SELECT norm_name FROM channels WHERE id = ?", ("chan1.us",)
        ).fetchone()[0]
    finally:
        db2.close()

    assert calls == []  # no per-row scan happened
    assert norm_name == "recorrupted"  # left untouched -- proves the scan, not luck, was skipped


def test_norm_repair_reruns_after_schema_version_bump(tmp_path, monkeypatch):
    # Mirrors test_region_repair_reruns_after_schema_version_bump: bumping
    # _NORM_REPAIR_SCHEMA_VERSION must force one more full repair pass so a
    # previously-versioned DB still picks up a real canonicalize_name logic change.
    path = tmp_path / "epg.db"
    db = EPGDatabase(str(path))
    db.insert_channel("chan1.us", "Some Channel HD")
    db.commit()
    stamped_version = db.conn.execute("PRAGMA application_id").fetchone()[0]
    db.close()

    conn = sqlite3.connect(path)
    conn.execute("UPDATE channels SET norm_name = 'recorrupted' WHERE id = ?", ("chan1.us",))
    conn.commit()
    conn.close()

    monkeypatch.setattr(playlist, "_NORM_REPAIR_SCHEMA_VERSION", stamped_version + 1)

    db2 = EPGDatabase(str(path))
    try:
        norm_name = db2.conn.execute(
            "SELECT norm_name FROM channels WHERE id = ?", ("chan1.us",)
        ).fetchone()[0]
        new_version = db2.conn.execute("PRAGMA application_id").fetchone()[0]
    finally:
        db2.close()

    assert norm_name == canonicalize_name(strip_noise_words("Some Channel HD"))
    assert new_version == stamped_version + 1


def test_epg_search_can_skip_programme_title_scan(tmp_path):
    path = tmp_path / "epg.db"
    now = datetime.datetime.now(datetime.timezone.utc)
    current_start = _xmltv_time(now - datetime.timedelta(minutes=15))
    current_end = _xmltv_time(now + datetime.timedelta(minutes=45))

    db = EPGDatabase(str(path))
    db.insert_channel("news.example", "News Channel")
    db.insert_channel("movies.example", "Movie Channel")
    db.insert_programme("news.example", "Morning Magazine", current_start, current_end)
    db.insert_programme("movies.example", "Breaking News Special", current_start, current_end)
    db.commit()
    db.close()

    db = EPGDatabase(str(path), readonly=True)
    try:
        channel_only = db.get_channels_with_show("news", include_title_search=False, limit=10)
        with_titles = db.get_channels_with_show("news", include_title_search=True, limit=10)
    finally:
        db.close()

    assert {row["channel_id"] for row in channel_only} == {"news.example"}
    assert {row["channel_id"] for row in with_titles} == {"news.example", "movies.example"}


def test_xmltv_negative_half_hour_offset_parses_to_utc():
    # Newfoundland (-0330): 12:00 local is 15:30 UTC. A naive offset_val//100 / %100
    # split mishandles the half hour on negative offsets and would yield 14:50.
    assert _parse_xmltv_to_utc_str("20240101120000 -0330") == "20240101153000"
    # India (+0530): 12:00 local is 06:30 UTC.
    assert _parse_xmltv_to_utc_str("20240101120000 +0530") == "20240101063000"
    # Whole-hour offsets and UTC are unaffected.
    assert _parse_xmltv_to_utc_str("20240101120000 -0500") == "20240101170000"
    assert _parse_xmltv_to_utc_str("20240101120000 +0000") == "20240101120000"


def test_xmltv_short_timestamps_parse_to_utc():
    # The XMLTV spec allows omitting trailing components and the reference
    # parser fills month/day with 01 and the rest with zeros. Feeds in the
    # wild publish the minute form; a 14-digit-only regex made every
    # programme of such a guide parse to None and be dropped at import.
    assert _parse_xmltv_to_utc_str("202609270600 +0100") == "20260927050000"
    assert _parse_xmltv_to_utc_str("202609270600") == "20260927060000"
    assert _parse_xmltv_to_utc_str("2026092706") == "20260927060000"
    assert _parse_xmltv_to_utc_str("20260927") == "20260927000000"
    assert _parse_xmltv_to_utc_str("202609") == "20260901000000"
    assert _parse_xmltv_to_utc_str("2026") == "20260101000000"
    # Malformed digit counts and invalid fields stay rejected.
    assert _parse_xmltv_to_utc_str("20260927123") is None      # 11 digits
    assert _parse_xmltv_to_utc_str("20261327000000") is None   # month 13
    assert _parse_xmltv_to_utc_str("2026092706002") is None    # 13 digits


def _epg_gz_temp_path(url: str) -> str:
    h = hashlib.md5(url.encode("utf-8", "ignore")).hexdigest()
    return os.path.join(tempfile.gettempdir(), f"epg_{h}.xml.gz")


def _remove_if_exists(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


class _FakeGzHttpResponse:
    """Minimal urlopen() stand-in exposing the .info()/.status/.read() surface
    that _http_download_gz_with_resume relies on."""

    def __init__(self, data: bytes, headers: dict, status: int = 200):
        self._buf = io.BytesIO(data)
        self._headers = headers
        self.status = status

    def info(self):
        return self

    def get(self, name, default=None):
        return self._headers.get(name, default)

    def read(self, n=-1):
        return self._buf.read(n)

    def close(self):
        pass


def test_gz_download_with_resume_detects_truncated_full_download(monkeypatch):
    # Incompressible payload so the first-16KB-of-output quick probe only needs
    # a small compressed prefix, mirroring how a truncated multi-hundred-MB EPG
    # download still leaves an intact gzip header/first block.
    raw = random.Random(12345).randbytes(200_000)
    full_gz = gzip.compress(raw)
    full_len = len(full_gz)
    truncated_gz = full_gz[: full_len - 5000]
    assert len(truncated_gz) > (1 << 14)

    # Prove the old probe-only signal really would accept this truncated file,
    # so the assertions below are testing something real, not a strawman.
    with gzip.open(io.BytesIO(truncated_gz)) as gzf:
        gzf.read(1 << 14)

    url = "https://example.invalid/epg-download-truncated.xml.gz"
    temp_path = _epg_gz_temp_path(url)
    _remove_if_exists(temp_path)

    monkeypatch.setattr(
        playlist.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeGzHttpResponse(truncated_gz, {"Content-Length": str(full_len)}),
    )

    try:
        with pytest.raises(RuntimeError, match="incomplete gzip download"):
            _http_download_gz_with_resume(url, max_attempts=1)
        # Partial file must survive so the next attempt can resume via Range
        # instead of the caller wiping it and restarting from scratch.
        assert os.path.exists(temp_path)
        assert os.path.getsize(temp_path) == len(truncated_gz)
    finally:
        _remove_if_exists(temp_path)


def test_gz_download_with_resume_succeeds_on_complete_download(monkeypatch):
    raw = b"integration-test-epg-payload " * 5000
    full_gz = gzip.compress(raw)
    full_len = len(full_gz)

    url = "https://example.invalid/epg-download-complete.xml.gz"
    temp_path = _epg_gz_temp_path(url)
    _remove_if_exists(temp_path)

    monkeypatch.setattr(
        playlist.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeGzHttpResponse(full_gz, {"Content-Length": str(full_len)}),
    )

    stream = _http_download_gz_with_resume(url, max_attempts=1)
    try:
        assert stream.read() == raw
    finally:
        stream.close()

    assert not os.path.exists(temp_path)


def test_gz_download_with_resume_detects_truncated_resume_via_content_range(monkeypatch):
    raw = random.Random(999).randbytes(200_000)
    full_gz = gzip.compress(raw)
    full_len = len(full_gz)
    split = full_len // 2
    prefix, remainder = full_gz[:split], full_gz[split:]
    short_remainder = remainder[: len(remainder) - 5000]

    url = "https://example.invalid/epg-download-resume-truncated.xml.gz"
    temp_path = _epg_gz_temp_path(url)
    _remove_if_exists(temp_path)
    with open(temp_path, "wb") as f:
        f.write(prefix)

    seen_headers = []

    def fake_urlopen(req, timeout=None):
        seen_headers.append(dict(req.headers))
        headers = {"Content-Range": f"bytes {split}-{full_len - 1}/{full_len}"}
        return _FakeGzHttpResponse(short_remainder, headers, status=206)

    monkeypatch.setattr(playlist.urllib.request, "urlopen", fake_urlopen)

    try:
        with pytest.raises(RuntimeError, match="incomplete gzip download"):
            _http_download_gz_with_resume(url, max_attempts=1)
        assert seen_headers[0].get("Range") == f"bytes={split}-"
        assert os.path.getsize(temp_path) == split + len(short_remainder)
    finally:
        _remove_if_exists(temp_path)


def test_programme_descriptions_round_trip(tmp_path):
    path = tmp_path / "epg.db"
    now = datetime.datetime.now(datetime.timezone.utc)
    db = EPGDatabase(str(path))
    db.insert_channel("ch1", "Channel 1")
    db.insert_programme(
        "ch1", "Show",
        _xmltv_time(now - datetime.timedelta(minutes=30)),
        _xmltv_time(now + datetime.timedelta(minutes=30)),
        "A great episode.",
    )
    db.commit()
    now_next = db.get_now_next_by_id("ch1")
    db.close()
    assert now_next is not None
    assert now_next[0]["description"] == "A great episode."


def test_reimport_replaces_stale_programmes_in_same_slot(tmp_path):
    db = EPGDatabase(str(tmp_path / "epg.db"))
    db.insert_channel("3201", "HGTV East")
    db.insert_programme("3201", "News 12", "20260928030000", "20260928033000")
    db.insert_programme("3201", "News 12", "20260928040000", "20260928090000")
    db.insert_programme("3201", "Older show", "20260927030000", "20260927033000")
    db.insert_programme("3201", "House Hunters", "20260928030000", "20260928033000")
    db.insert_programme("3201", "Totally '90s House", "20260928040000", "20260928050000")
    rows = db.conn.execute(
        "SELECT title FROM programmes WHERE channel_id = ? ORDER BY start", ("3201",)
    ).fetchall()
    db.close()
    assert rows == [("Older show",), ("House Hunters",), ("Totally '90s House",)]


def test_channel_id_given_to_another_channel_drops_old_schedule(tmp_path):
    """A server renumber hands id 14703 from Sheffield Live TV to Sky Mix."""
    db = EPGDatabase(str(tmp_path / "epg.db"))
    db.insert_channel("14703", "Sheffield Live TV")
    db.insert_programme("14703", "Sheffield Live TV", "20261002010000", "20261002050000")
    db.insert_channel("14703", "Sky Mix HD")
    db.insert_programme("14703", "Road Wars", "20261002000000", "20261002010000")
    db.insert_channel("14703", "Sky Mix")  # same channel, noise word only: keep
    rows = db.conn.execute("SELECT title FROM programmes WHERE channel_id = '14703'").fetchall()
    db.close()
    assert rows == [("Road Wars",)]


def test_legacy_programme_table_is_migrated_and_descriptions_backfill(tmp_path):
    """Databases from before descriptions existed keep working and gain the column."""
    path = tmp_path / "epg.db"
    now = datetime.datetime.now(datetime.timezone.utc)
    start = _xmltv_time(now - datetime.timedelta(minutes=30))
    end = _xmltv_time(now + datetime.timedelta(minutes=30))
    conn = _create_epg_schema(path)
    conn.execute("CREATE UNIQUE INDEX ux_programmes ON programmes (channel_id, start, end)")
    conn.execute("INSERT INTO channels (id, display_name) VALUES ('ch1', 'Channel 1')")
    conn.execute(
        "INSERT INTO programmes (channel_id, title, start, end) VALUES ('ch1', 'Show', ?, ?)",
        (start, end),
    )
    conn.commit()
    conn.close()

    db = EPGDatabase(str(path))
    # Same slot, now with a description: the upsert must backfill, not duplicate.
    db.insert_programme("ch1", "Show", start, end, "Backfilled description.")
    db.commit()
    now_next = db.get_now_next_by_id("ch1")
    count = db.conn.execute("SELECT COUNT(*) FROM programmes").fetchone()[0]
    db.close()
    assert count == 1
    assert now_next[0]["description"] == "Backfilled description."


def test_get_all_now_next_returns_now_and_next_per_channel(tmp_path):
    path = tmp_path / "epg.db"
    now = datetime.datetime.now(datetime.timezone.utc)
    db = EPGDatabase(str(path))
    db.insert_channel("ch1", "Channel 1")
    db.insert_channel("ch2", "Channel 2")
    db.insert_programme("ch1", "Now Show",
                        _xmltv_time(now - datetime.timedelta(minutes=30)),
                        _xmltv_time(now + datetime.timedelta(minutes=30)), "Now description.")
    db.insert_programme("ch1", "Next Show",
                        _xmltv_time(now + datetime.timedelta(minutes=30)),
                        _xmltv_time(now + datetime.timedelta(minutes=90)))
    # A later programme must not shadow the earliest next one.
    db.insert_programme("ch1", "Later Show",
                        _xmltv_time(now + datetime.timedelta(minutes=90)),
                        _xmltv_time(now + datetime.timedelta(minutes=120)))
    # Channel 2 has only a future programme: no "now" entry.
    db.insert_programme("ch2", "Only Next",
                        _xmltv_time(now + datetime.timedelta(minutes=15)),
                        _xmltv_time(now + datetime.timedelta(minutes=75)))
    db.commit()
    try:
        result = db.get_all_now_next()
    finally:
        db.close()
    ch1 = result["ch1"]
    assert ch1["display_name"] == "Channel 1"
    assert ch1["now"]["title"] == "Now Show"
    assert ch1["next"]["title"] == "Next Show"
    # Descriptions ride along for the episode-description field; a programme
    # stored without one yields an empty string, never a missing key.
    assert ch1["now"]["description"] == "Now description."
    assert ch1["next"]["description"] == ""
    assert "now" not in result["ch2"]
    assert result["ch2"]["next"]["title"] == "Only Next"


def test_gz_download_does_not_resume_a_partial_file_from_an_earlier_run(monkeypatch):
    """Resuming yesterday's partial against today's feed spliced two different files."""
    raw = b"todays-epg-payload " * 5000
    full_gz = gzip.compress(raw)

    url = "https://example.invalid/epg-download-stale-partial.xml.gz"
    temp_path = _epg_gz_temp_path(url)
    _remove_if_exists(temp_path)
    stale = gzip.compress(b"yesterdays-epg-payload " * 5000)[:4000]
    with open(temp_path, "wb") as handle:
        handle.write(stale)
    old = playlist.time.time() - playlist._EPG_PARTIAL_MAX_AGE_SECONDS - 60
    os.utime(temp_path, (old, old))

    requests = []

    def urlopen(req, timeout=None):
        requests.append(req.get_header("Range"))
        return _FakeGzHttpResponse(full_gz, {"Content-Length": str(len(full_gz))})

    monkeypatch.setattr(playlist.urllib.request, "urlopen", urlopen)

    stream = _http_download_gz_with_resume(url, max_attempts=1)
    try:
        assert stream.read() == raw
    finally:
        stream.close()
    assert requests == [None]


def test_prune_old_programmes_removes_exactly_the_expired_rows(tmp_path):
    """Prune must delete expired rows and keep the ones inside the window."""
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        # Anchored to the app's own clock so the cutoff lands between the
        # expired rows and the ones inside the window, whatever today's date is.
        utcnow = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        old = (utcnow - datetime.timedelta(days=300)).strftime("%Y%m%d%H%M%S")
        edge = (utcnow - datetime.timedelta(days=30)).strftime("%Y%m%d%H%M%S")
        recent = (utcnow - datetime.timedelta(days=2)).strftime("%Y%m%d%H%M%S")
        future = (utcnow + datetime.timedelta(days=300)).strftime("%Y%m%d%H%M%S")
        rows = [
            ("ch1", "Expired long ago", old, old, ""),
            ("ch2", "Expired 30d", edge, edge, ""),
            ("ch3", "Within window", recent, recent, ""),
            ("ch4", "Future", future, future, ""),
        ]
        db.conn.executemany(
            "INSERT OR IGNORE INTO programmes (channel_id,title,start,end,description)"
            " VALUES (?,?,?,?,?)", rows)
        db.conn.commit()

        db.prune_old_programmes(days=14)

        kept = sorted(r[0] for r in db.conn.execute("SELECT title FROM programmes").fetchall())
        assert kept == ["Future", "Within window"]
    finally:
        db.close()


def test_prune_reclaims_file_space(tmp_path):
    """DELETE frees pages but never shrinks the file unless auto_vacuum is set.

    Without this the guide only ever grew: one user's epg.db reached 8 GB of
    mostly-empty pages that prune never returned to the filesystem.
    """
    db_path = str(tmp_path / "epg.db")
    db = EPGDatabase(db_path)
    try:
        assert db.conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2, "INCREMENTAL not active"

        old = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
               - datetime.timedelta(days=40)).strftime("%Y%m%d%H%M%S")
        keep = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                - datetime.timedelta(days=1)).strftime("%Y%m%d%H%M%S")
        rows = [
            (f"ch{i:03d}", "Expired", old, old, "x" * 200)
            for i in range(4000)
        ] + [
            (f"ch{i:03d}", "Keep", keep, keep, "x" * 200)
            for i in range(200)
        ]
        db.conn.executemany(
            "INSERT OR IGNORE INTO programmes (channel_id,title,start,end,description)"
            " VALUES (?,?,?,?,?)", rows)
        db.conn.commit()
        db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        size_full = os.path.getsize(db_path)

        db.prune_old_programmes(days=14)
        db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        size_after = os.path.getsize(db_path)
        assert db.conn.execute("SELECT COUNT(*) FROM programmes").fetchone()[0] == 200
        assert size_after < size_full, f"file did not shrink: {size_full} -> {size_after}"
    finally:
        db.close()


def test_winsock_connection_abort_is_treated_as_transient():
    """[WinError 10054] must be retried, not reported as a failed import.

    This is the error a 542 MB uncompressed XMLTV feed produced: the remote
    host tore the socket down mid-transfer and the import gave up at once.
    """
    from playlist import _is_transient_epg_error

    reported = "[WinError 10054] An existing connection was forcibly closed by the remote host"
    assert _is_transient_epg_error(OSError(reported))
    # Sibling Winsock aborts, all of which aborted the import outright before.
    for winerror in (10051, 10053, 10055, 10060, 10061):
        assert _is_transient_epg_error(OSError(winerror, "socket failure")), winerror

    # Genuine parse/data errors must still surface to the user.
    assert not _is_transient_epg_error(ValueError("malformed XMLTV: bad tvg id"))
    assert not _is_transient_epg_error(sqlite3.OperationalError("no such table: programmes"))


def test_epg_import_requests_gzip_encoded_feed(monkeypatch, tmp_path):
    """urllib sends no Accept-Encoding of its own.

    Dispatcharr (tv.serrebiradio.com) only compresses the XMLTV feed when the
    client asks, and the uncompressed body was 542 MB with no Content-Length.
    """
    captured = {}

    class _Resp:
        status = 200

        def info(self):
            return self

        def get(self, name, default=None):
            return default

        def peek(self, n=0):
            return b"<?xml version='1.0'?><tv></tv>"

        def read(self, n=-1):
            return b""

        def close(self):
            pass

    def urlopen(req, timeout=None):
        captured["accept_encoding"] = req.get_header("Accept-encoding")
        return _Resp()

    db = EPGDatabase(str(tmp_path / "epg.db"))
    monkeypatch.setattr(playlist.urllib.request, "urlopen", urlopen)
    try:
        db.import_epg_xml(["https://example.invalid/xmltv.php?username=u&password=p"])
    finally:
        db.close()
    assert captured.get("accept_encoding") == "gzip"


def test_reimport_keeps_history_of_a_channel_id_the_guide_defines_twice(tmp_path):
    """A Dispatcharr feed defined 390 channel ids twice under different names.

    The second definition read as a renumbered channel and deleted the id's
    programmes on every import, history and catch-up included.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
    fmt = "%Y%m%d%H%M%S +0000"
    xml_path = tmp_path / "guide.xml"
    xml_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><tv>'
        '<channel id="14170"><display-name>Sky Sports Tennis</display-name></channel>'
        '<channel id="14170"><display-name>Lacrosse Championships Gold Medal</display-name></channel>'
        f'<programme start="{now.strftime(fmt)}" stop="{(now + datetime.timedelta(hours=1)).strftime(fmt)}" '
        'channel="14170"><title>Tennis</title></programme>'
        '</tv>',
        encoding="utf-8",
    )
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.import_epg_xml([str(xml_path)])
        old_start = (now - datetime.timedelta(days=2)).strftime("%Y%m%d%H%M%S")
        old_end = (now - datetime.timedelta(days=2, hours=-1)).strftime("%Y%m%d%H%M%S")
        db.insert_programme("14170", "Earlier Match", old_start, old_end)
        db.commit()

        db.import_epg_xml([str(xml_path)])

        titles = {row[0] for row in db.conn.execute(
            "SELECT title FROM programmes WHERE channel_id = '14170'")}
        assert titles == {"Tennis", "Earlier Match"}
        name = db.conn.execute("SELECT display_name FROM channels WHERE id = '14170'").fetchone()[0]
        assert name == "Sky Sports Tennis"
    finally:
        db.close()


def test_epg_search_treats_percent_and_underscore_literally(tmp_path):
    now = datetime.datetime.now(datetime.timezone.utc)
    fmt = "%Y%m%d%H%M%S"
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.insert_channel("a", "100% News")
        db.insert_channel("b", "Sports 1005 PM")
        for cid in ("a", "b"):
            db.insert_programme(cid, "Show", (now - datetime.timedelta(minutes=5)).strftime(fmt),
                                (now + datetime.timedelta(minutes=55)).strftime(fmt))
        db.commit()
        names = {r["channel_name"] for r in db.get_channels_with_show("100%")}
        assert names == {"100% News"}
    finally:
        db.close()


def test_import_checkpoints_the_wal_between_batches(tmp_path):
    """wal_autocheckpoint is off during import; without a checkpoint per batch
    a 618 MB guide grew the WAL past 1.8 GB before the final TRUNCATE."""
    start = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
    fmt = "%Y%m%d%H%M%S +0000"
    parts = ['<?xml version="1.0" encoding="UTF-8"?><tv><channel id="c"><display-name>C</display-name></channel>']
    for i in range(15001):
        st = start + datetime.timedelta(minutes=i)
        parts.append(f'<programme start="{st.strftime(fmt)}" stop="{(st + datetime.timedelta(minutes=1)).strftime(fmt)}" '
                     f'channel="c"><title>P{i}</title></programme>')
    parts.append("</tv>")
    xml_path = tmp_path / "guide.xml"
    xml_path.write_text("".join(parts), encoding="utf-8")

    db = EPGDatabase(str(tmp_path / "epg.db"))
    executed = []
    real = db.conn

    class _Spy:
        def __getattr__(self, name):
            return getattr(real, name)

        def execute(self, sql, *args):
            executed.append(sql)
            return real.execute(sql, *args)

    db.conn = _Spy()
    try:
        db.import_epg_xml([str(xml_path)])
    finally:
        db.conn = real
        db.close()
    assert any("wal_checkpoint(PASSIVE)" in sql for sql in executed)
