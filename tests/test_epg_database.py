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
    epg_database_has_usable_data,
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
