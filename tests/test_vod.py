"""Tests for the VOD catalogue building (vod.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vod


def test_parse_season_episode_variants():
    assert vod.parse_season_episode("Breaking Bad S01E02") == (1, 2)
    assert vod.parse_season_episode("Show s1 e15") == (1, 15)
    assert vod.parse_season_episode("Some Show 2x05") == (2, 5)
    assert vod.parse_season_episode("Thing Episode 7") == (0, 7)
    assert vod.parse_season_episode("CNN News") is None


def test_series_title_strips_marker():
    assert vod._series_title("Breaking Bad S01E02 - Pilot") == "Breaking Bad"
    assert vod._series_title("The Wire 1x01") == "The Wire"
    assert vod._series_title("Plain Movie") == "Plain Movie"


def test_categorize_m3u_splits_movies_and_series():
    channels = [
        {"name": "CNN", "group": "News", "url": "http://x/1"},
        {"name": "Inception", "group": "VOD Movies", "url": "http://x/movie/2"},
        {"name": "Breaking Bad S01E01", "group": "Series Drama", "url": "http://x/3"},
        {"name": "Breaking Bad S01E02", "group": "Series Drama", "url": "http://x/4"},
        {"name": "Breaking Bad S02E01", "group": "Series Drama", "url": "http://x/5"},
    ]
    order, groups = vod.categorize_m3u_vod(channels)

    # A live news channel must not be swept into VOD.
    assert "News" not in order
    # Category labels are the provider's own group-titles, verbatim.
    assert "VOD Movies" in order and "Series Drama" in order

    movies = groups["VOD Movies"]
    assert len(movies) == 1 and movies[0]["kind"] == vod.KIND_MOVIE
    assert movies[0]["url"] == "http://x/movie/2"

    series_bucket = groups["Series Drama"]
    assert len(series_bucket) == 1  # one episodic show, episodes merged into a folder
    series = series_bucket[0]
    assert series["kind"] == vod.KIND_SERIES
    assert series["name"] == "Breaking Bad"
    eps = series["episodes"]
    assert len(eps) == 3
    # Episodes must be ordered by (season, episode).
    assert [e["_se"] for e in eps] == [(1, 1), (1, 2), (2, 1)]


def test_single_stream_show_is_flat_not_a_folder():
    """A '24/7 <Show>' single stream must be directly playable, not a 1-item folder."""
    channels = [
        {"name": "Bar Rescue", "group": "24/7 Shows", "url": "http://x/br"},
        {"name": "Blue Bloods", "group": "24/7 Shows", "url": "http://x/bb"},
        {"name": "Bar Rescue", "group": "24/7 Shows", "url": "http://x/br"},  # dupe
    ]
    order, groups = vod.categorize_m3u_vod(channels)
    assert order == ["24/7 Shows"]
    items = groups["24/7 Shows"]
    # Deduped to two directly-playable items; no series folders.
    assert len(items) == 2
    assert all(it["kind"] == vod.KIND_MOVIE for it in items)
    assert {it["url"] for it in items} == {"http://x/br", "http://x/bb"}


def test_no_hint_and_garbage_names_are_excluded():
    """Entries without a movie/series group hint stay out of VOD (no blind SxxExx guessing)."""
    channels = [
        {"name": "US: ABC 9 Syracuse (WSYR)", "group": "US ABC", "url": "http://x/abc"},
        # Malformed entry: base64 logo blob as the name, empty group -> country fallback.
        {"name": "iVBORw0KGgoS01aE05bcd", "group": "us", "url": "http://x/junk"},
    ]
    order, groups = vod.categorize_m3u_vod(channels)
    assert order == [] and groups == {}


class _FakeXtream:
    def get_vod_categories(self):
        return [{"category_id": "1", "category_name": "Action"}]

    def get_vod_streams(self, category_id=None):
        return [{"stream_id": 42, "name": "The Matrix", "category_id": "1",
                 "container_extension": "mkv"}]

    def get_series_categories(self):
        return [{"category_id": "9", "category_name": "Crime"}]

    def get_series(self, category_id=None):
        return [{"series_id": 7, "name": "The Wire", "category_id": "9"}]

    def get_series_info(self, series_id):
        return {"episodes": {
            "2": [{"id": 200, "episode_num": 1, "title": "Ep A", "container_extension": "mp4"}],
            "1": [{"id": 100, "episode_num": 2, "title": "Ep B", "container_extension": "mp4"},
                  {"id": 101, "episode_num": 1, "title": "Ep C", "container_extension": "mp4"}],
        }}

    def vod_stream_url(self, stream_id, ext="mp4"):
        return f"http://host/movie/u/p/{stream_id}.{ext}"

    def series_stream_url(self, episode_id, ext="mp4"):
        return f"http://host/series/u/p/{episode_id}.{ext}"


def test_build_xtream_catalog():
    order, groups = vod.build_xtream_catalog(_FakeXtream(), "prov1")
    movie_label = vod._("Movies") + " — Action"
    series_label = vod._("Series") + " — Crime"
    assert movie_label in groups and series_label in groups

    movie = groups[movie_label][0]
    assert movie["url"] == "http://host/movie/u/p/42.mkv"

    series = groups[series_label][0]
    assert series["kind"] == vod.KIND_SERIES
    assert series["series_id"] == 7 and series["provider-id"] == "prov1"


def test_xtream_series_episodes_ordered():
    eps = vod.xtream_series_episodes(_FakeXtream(), 7, "prov1")
    assert [e["_se"] for e in eps] == [(1, 1), (1, 2), (2, 1)]
    assert eps[0]["url"] == "http://host/series/u/p/101.mp4"
    assert eps[0]["name"].startswith("S01E01")
