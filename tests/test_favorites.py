"""Tests for favorite channels (favorites.py).

The point of these is the identity rule. A favorite is stored in the config file and
looked up again after the next playlist refresh, so the key must not be built from
anything the provider regenerates -- above all not the resolved stream URL, which
carries the account credentials and changes on every resolve.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import favorites  # noqa: E402


XTREAM = {
    "name": "BBC One HD",
    "group": "UK",
    "provider-type": "xtream",
    "provider-id": "prov-1",
    "stream-id": "4242",
    "tvg-id": "bbc1.uk",
    "url": "http://panel.example/live/user/pass/4242.ts",
}


class TestChannelKey:
    def test_key_survives_a_url_change(self):
        refreshed = dict(XTREAM, url="http://panel.example/live/user/newpass/4242.ts")
        assert favorites.channel_key(refreshed) == favorites.channel_key(XTREAM)

    def test_key_carries_no_credentials(self):
        key = favorites.channel_key(XTREAM)
        assert "pass" not in key
        assert "user" not in key
        assert "http" not in key

    def test_key_separates_two_providers_with_the_same_channel(self):
        other = dict(XTREAM, **{"provider-id": "prov-2"})
        assert favorites.channel_key(other) != favorites.channel_key(XTREAM)

    def test_key_separates_two_streams_from_one_provider(self):
        other = dict(XTREAM, **{"stream-id": "4243", "name": "BBC Two HD"})
        assert favorites.channel_key(other) != favorites.channel_key(XTREAM)

    def test_plain_m3u_channel_keys_on_its_name(self):
        assert favorites.channel_key({"name": "Sky News"}) == "Sky News"

    def test_underscore_field_spellings_are_accepted(self):
        assert favorites.channel_key({"tvg_name": "Dave"}) == "Dave"
        assert favorites.channel_key({"name": "Dave", "stream_id": "7"}) == "7|Dave"

    def test_nothing_to_key_on_returns_empty(self):
        assert favorites.channel_key({}) == ""
        assert favorites.channel_key({"url": "http://example/x.ts"}) == ""
        assert favorites.channel_key(None) == ""
        assert favorites.channel_key("not a channel") == ""


class TestNormalize:
    def test_drops_blanks_duplicates_and_non_strings(self):
        assert favorites.normalize(["a", "a", "  ", None, 7, " b "]) == ["a", "b"]

    def test_missing_or_wrong_typed_config_value(self):
        assert favorites.normalize(None) == []
        assert favorites.normalize([]) == []
        # A bare string in the config file is not a one-item list of keys.
        assert favorites.normalize("a,b") == []


class TestFilterChannels:
    def test_returns_playlist_order_not_favorited_order(self):
        channels = [{"name": n} for n in ("A", "B", "C", "D")]
        picked = favorites.filter_channels(channels, ["D", "B"])
        assert [ch["name"] for ch in picked] == ["B", "D"]

    def test_unknown_keys_are_ignored(self):
        channels = [{"name": "A"}]
        assert favorites.filter_channels(channels, ["A", "gone"]) == [{"name": "A"}]

    def test_no_keys_or_no_channels(self):
        assert favorites.filter_channels([{"name": "A"}], []) == []
        assert favorites.filter_channels([], ["A"]) == []

    def test_same_name_in_two_categories_is_one_favorite(self):
        # Deliberate: marking "BBC One" means the channel, not one row of it.
        channels = [{"name": "BBC One", "group": "UK"}, {"name": "BBC One", "group": "News"}]
        assert len(favorites.filter_channels(channels, ["BBC One"])) == 2


class TestToggle:
    def test_add_then_remove_round_trips(self):
        keys, added = favorites.toggle([], XTREAM)
        assert added is True
        assert keys == [favorites.channel_key(XTREAM)]
        keys, added = favorites.toggle(keys, XTREAM)
        assert added is False
        assert keys == []

    def test_adding_appends_and_keeps_existing_order(self):
        keys, _added = favorites.toggle(["first"], {"name": "Second"})
        assert keys == ["first", "Second"]

    def test_unkeyable_channel_changes_nothing(self):
        keys, added = favorites.toggle(["first"], {"url": "http://example/x.ts"})
        assert added is False
        assert keys == ["first"]


def test_favorites_group_sentinel_is_english():
    # Stored and compared in English like the "All Channels" sentinel, so a language
    # change cannot orphan the category.
    assert favorites.FAVORITES_GROUP == "Favorites"


# --------------------------------------------------------------------------- #
# Category wiring in the main frame
#
# These drive the real IPTVClient methods against a namespace double, the same way
# tests/test_search_filter.py does, because the part that breaks is never the key
# rule -- it is the sentinel category being out of step with the list beside it.
# --------------------------------------------------------------------------- #
from types import SimpleNamespace  # noqa: E402


class FakeListBox:
    def __init__(self, items=None, selection=0):
        self.items = list(items or [])
        self.selection = selection

    def GetSelection(self):
        return self.selection

    def SetSelection(self, index):
        self.selection = index

    def GetCount(self):
        return len(self.items)

    def GetString(self, index):
        return self.items[index]

    def Insert(self, item, pos):
        self.items.insert(pos, item)

    def SetString(self, pos, item):
        self.items[pos] = item

    def Delete(self, pos):
        self.items.pop(pos)


def _client(favorite_names=(), all_names=("A", "B", "C"), group="All Channels",
            group_items=("All Channels (3)", "UK (3)"), selection=0):
    from main import IPTVClient

    channels = [{"name": name} for name in all_names]
    keys = [favorites.channel_key({"name": name}) for name in favorite_names]
    client = SimpleNamespace(
        view_mode="live",
        playlist_scope="",
        playlist_sources=[],
        all_channels=channels,
        channels_by_group={"UK": channels},
        current_group=group,
        favorite_keys=keys,
        _favorite_key_set=set(keys),
        _favorites_cache=None,
        _group_keys=[item.split(" (")[0] for item in group_items],
        group_list=FakeListBox(group_items, selection=selection),
    )
    for name in ("_favorite_channels", "_invalidate_favorites_cache", "_source_for_group",
                 "_favorites_group_label", "_update_favorites_group_row",
                 "_decorate_channel_label", "_is_favorite",
                 "scoped_all_channels", "scoped_channels_by_group"):
        setattr(client, name, _bind(IPTVClient, name, client))
    return client


def _bind(cls, name, instance):
    method = getattr(cls, name)
    return lambda *args, **kwargs: method(instance, *args, **kwargs)


class TestCategoryWiring:
    def test_source_for_group_serves_each_sentinel(self):
        client = _client(favorite_names=["B"])
        assert client._source_for_group("All Channels") == client.all_channels
        assert client._source_for_group(favorites.FAVORITES_GROUP) == [{"name": "B"}]
        assert client._source_for_group("UK") == client.all_channels
        assert client._source_for_group("nonexistent") == []

    def test_favorites_are_cached_until_invalidated(self):
        client = _client(favorite_names=["B"])
        first = client._favorite_channels()
        assert client._favorite_channels() is first
        client._invalidate_favorites_cache()
        assert client._favorite_channels() is not first

    def test_first_favorite_inserts_the_category_second(self):
        client = _client(favorite_names=["B"])
        client._update_favorites_group_row()
        assert client._group_keys == ["All Channels", favorites.FAVORITES_GROUP, "UK"]
        assert client.group_list.items[1].endswith("(1)")

    def test_inserting_keeps_the_selected_category_selected(self):
        client = _client(favorite_names=["B"], selection=1)  # "UK" is selected
        client._update_favorites_group_row()
        assert client.group_list.GetString(client.group_list.GetSelection()).startswith("UK")

    def test_an_extra_favorite_only_relabels_the_row(self):
        client = _client(favorite_names=["A", "B"],
                         group_items=("All Channels (3)", "Favorites (1)", "UK (3)"))
        client._group_keys = ["All Channels", favorites.FAVORITES_GROUP, "UK"]
        client._update_favorites_group_row()
        assert client._group_keys == ["All Channels", favorites.FAVORITES_GROUP, "UK"]
        assert client.group_list.items[1].endswith("(2)")

    def test_removing_the_last_favorite_drops_the_category(self):
        client = _client(favorite_names=[],
                         group_items=("All Channels (3)", "Favorites (1)", "UK (3)"),
                         group=favorites.FAVORITES_GROUP, selection=1)
        client._group_keys = ["All Channels", favorites.FAVORITES_GROUP, "UK"]
        client._update_favorites_group_row()
        assert favorites.FAVORITES_GROUP not in client._group_keys
        # The category the user was on has gone, so they land on All Channels
        # rather than on a stale selection.
        assert client.group_list.GetSelection() == 0
        assert client.current_group == "All Channels"

    def test_nothing_happens_while_the_playlist_is_still_loading(self):
        client = _client(favorite_names=["B"], group_items=("Loading playlists...",))
        client._group_keys = []
        client._update_favorites_group_row()
        assert client.group_list.items == ["Loading playlists..."]

    def test_nothing_happens_in_the_vod_view(self):
        client = _client(favorite_names=["B"])
        client.view_mode = "vod"
        client._update_favorites_group_row()
        assert favorites.FAVORITES_GROUP not in client._group_keys


class TestRowLabels:
    def test_a_favorite_is_marked_in_an_ordinary_category(self):
        client = _client(favorite_names=["B"])
        assert client._decorate_channel_label("B", {"name": "B"}) != "B"
        assert client._decorate_channel_label("B", {"name": "B"}).startswith("B")
        assert client._decorate_channel_label("A", {"name": "A"}) == "A"

    def test_no_marker_inside_the_favorites_category(self):
        client = _client(favorite_names=["B"], group=favorites.FAVORITES_GROUP)
        assert client._decorate_channel_label("B", {"name": "B"}) == "B"

    def test_no_marker_at_all_without_favorites(self):
        client = _client()
        assert client._decorate_channel_label("A", {"name": "A"}) == "A"
