"""
Tests for EPG database freshness helpers.
"""
import datetime
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playlist import (
    _derive_playlist_region,
    _detect_region_from_id,
    _expand_tvg_id_candidates,
    _ordered_channel_tokens,
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
