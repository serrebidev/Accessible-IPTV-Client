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
