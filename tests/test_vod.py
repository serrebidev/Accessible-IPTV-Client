"""Tests for the VOD catalogue building (vod.py)."""

import os
import sys
import types

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


class _BrokenXtream(_FakeXtream):
    """A provider that answers with values the app has to survive."""

    def get_vod_categories(self):
        # A category name that is not a string at all.
        return [{"category_id": "1", "category_name": 7}]

    def get_series_info(self, series_id):
        return {"episodes": {
            # A season number with thousands of digits, and an episode
            # number that is not a number.
            "9" * 5000: [{"id": 300, "episode_num": float("inf"),
                           "title": "Ep", "container_extension": "mp4"}],
        }}


def test_a_broken_provider_value_does_not_kill_the_catalogue():
    """The provider's JSON is untrusted input.

    int() of "inf" raises OverflowError and int() refuses a season number
    with thousands of digits; both were uncaught, so one bad value took the
    whole episode list - or the whole catalogue - with it.
    """
    order, groups = vod.build_xtream_catalog(_BrokenXtream(), "prov1")
    assert groups, "the catalogue was lost to one broken value"

    eps = vod.xtream_series_episodes(_BrokenXtream(), 7, "prov1")
    assert len(eps) == 1
    assert eps[0]["url"] == "http://host/series/u/p/300.mp4"


class _NullRowXtream:
    """A provider whose JSON carries a null entry among the good ones."""

    def get_vod_categories(self):
        return [None, {"category_id": "1", "category_name": "Action"}]

    def get_vod_streams(self, category_id=None):
        return [None, {"stream_id": 42, "name": "The Matrix", "category_id": "1",
                       "container_extension": "mkv"}]

    def get_series_categories(self):
        return [None, {"category_id": "9", "category_name": "Crime"}]

    def get_series(self, category_id=None):
        return [None, {"series_id": 7, "name": "The Wire", "category_id": "9"}]

    def get_series_info(self, series_id):
        return {"episodes": {}}

    def vod_stream_url(self, stream_id, ext="mp4"):
        return f"http://host/movie/u/p/{stream_id}.{ext}"


def test_a_null_row_does_not_take_the_catalogue_with_it():
    """One null entry used to raise, and the whole section was dropped.

    The provider's JSON is untrusted input: a null row is skipped, and the
    rest of the catalogue is still built.
    """
    order, groups = vod.build_xtream_catalog(_NullRowXtream(), "prov1")

    assert groups, "the catalogue was lost to one null row"
    names = [item.get("name") for items in groups.values() for item in items]
    assert "The Matrix" in names
    assert "The Wire" in names


# --------------------------------------------------------------------------- #
# The VOD view
# --------------------------------------------------------------------------- #
class _FakeList:
    def __init__(self):
        self.items = []
        self.selection = None

    def Freeze(self):
        pass

    def Thaw(self):
        pass

    def Clear(self):
        self.items = []
        self.selection = None

    def Append(self, item):
        self.items.append(item)

    def SetSelection(self, index):
        self.selection = index

    def GetSelection(self):
        return -1 if self.selection is None else self.selection


class _FakeText:
    def __init__(self):
        self.value = ""

    def SetValue(self, value):
        self.value = value


def _vod_client(order=None, groups=None):
    client = types.SimpleNamespace()
    client.group_list = _FakeList()
    client.channel_list = _FakeList()
    client.url_display = _FakeText()
    client.vod_group_order = list(order or [])
    client.vod_groups = dict(groups or {})
    client.vod_current_group = None
    client.vod_series_return_group = None
    client.vod_loaded = False
    client.vod_loading = False
    client._vod_load_token = 0
    client.provider_clients = {}
    client.playlist_scope = "all"
    client.scoped_all_channels = lambda: []
    client.on_group_select = lambda: None
    client._on_vod_catalog_ready = lambda token, order, groups: None
    return client


def test_an_empty_vod_catalogue_is_announced(monkeypatch):
    """An empty list is silent to a screen-reader user.

    The message was only an unselected row in the category list, so the view
    looked empty with nothing said about it.
    """
    import main

    spoken = []
    monkeypatch.setattr(main.live_announce, "speak", lambda text: spoken.append(text))
    client = _vod_client()

    main.IPTVClient._refresh_vod_group_ui(client)

    assert spoken, "the empty catalogue was not announced"
    assert "No Video on Demand content found" in spoken[0]
    assert client.group_list.selection == 0, "the message row was not selected"


def test_a_playlist_reload_supersedes_the_catalogue_being_built(monkeypatch):
    """The catalogue being built belongs to the playlist that was replaced.

    The result was accepted anyway, so the view showed the old playlist's
    catalogue - including a playlist that was gone - and the new playlist's
    VOD never arrived.
    """
    import main

    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: None)
    client = _vod_client()
    client.vod_loading = True
    client._vod_load_token = 5

    main.IPTVClient._load_vod_catalog(client, supersede=True)

    assert client._vod_load_token > 5, "the catalogue being built was not superseded"
