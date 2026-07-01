"""
Tests for EPG database freshness helpers.
"""
import datetime
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playlist import (
    EPGDatabase,
    _derive_playlist_region,
    _detect_region_from_id,
    _expand_tvg_id_candidates,
    _ordered_channel_tokens,
    _parse_xmltv_to_utc_str,
    canonicalize_name,
    epg_database_has_usable_data,
    extract_callsigns,
    extract_group,
    strip_noise_words,
    tokenize_channel_name,
)


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
