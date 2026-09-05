"""Tests for the playlist-scope picker (categories/channels from one playlist).

The scope is stored in config["playlist_scope"] as the playlist source's stable
"id", with the empty string meaning "All playlists". These tests pin the
pure scoping helpers and the frame-level filtering without opening a window.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def _ch(name, pid=None):
    ch = {"name": name}
    if pid is not None:
        ch["playlist-id"] = pid
    return ch


def _stub(scope, channels, sources=None):
    return SimpleNamespace(
        playlist_scope=scope,
        all_channels=channels,
        channels_by_group={},
        playlist_sources=sources or [],
    )


class TestScopeHelpers:
    def test_all_playlists_sentinel_is_empty_string(self):
        assert main.ALL_PLAYLISTS_SCOPE == ""

    def test_untagged_channel_visible_in_all_playlists(self):
        assert main._scope_includes_channel(_ch("A"), "")

    def test_untagged_channel_hidden_from_single_playlist(self):
        assert not main._scope_includes_channel(_ch("A"), "p1")

    def test_matching_tag_visible(self):
        assert main._scope_includes_channel(_ch("A", "p1"), "p1")

    def test_other_playlist_tag_hidden(self):
        assert not main._scope_includes_channel(_ch("A", "p2"), "p1")

    def test_false_and_blank_tags_never_match_a_scope(self):
        assert not main._scope_includes_channel({"name": "A", "playlist-id": False}, "p1")
        assert not main._scope_includes_channel({"name": "A", "playlist-id": ""}, "p1")

    def test_scoped_channels_all_returns_same_list_for_all_scope(self):
        channels = [_ch("A"), _ch("B", "p1")]
        assert main._scoped_channels(channels, "") is channels

    def test_scoped_channels_filters_other_playlists(self):
        channels = [_ch("A"), _ch("B", "p1"), _ch("C", "p2")]
        got = main._scoped_channels(channels, "p1")
        assert [ch["name"] for ch in got] == ["B"]

    def test_source_scope_id_reads_dict_source(self):
        assert main._source_scope_id({"id": "p1"}) == "p1"
        assert main._source_scope_id({"provider_id": "p2"}) == "p2"
        assert main._source_scope_id({}) == ""
        assert main._source_scope_id("http://example.com/x.m3u").startswith("m3u:")

    def test_plain_sources_are_selectable_and_have_distinct_private_ids(self):
        sources = ["https://example.com/a.m3u?token=secret", "C:/lists/b.m3u"]
        assert main._tagged_sources(sources) == sources
        ids = [main._source_scope_id(src) for src in sources]
        assert ids[0] != ids[1]
        assert "secret" not in ids[0]
        assert ids[0] == main._source_scope_id(sources[0])

    def test_client_pid_scope(self):
        assert main._client_pid_scope("prov-123", "prov-123") is True
        assert main._client_pid_scope("wrapped:prov-123", "prov-123") is True
        assert main._client_pid_scope("prov-999", "prov-123") is False
        assert main._client_pid_scope("", "") is True


class TestScopedAccessors:
    def test_scoped_all_channels_filters(self):
        stub = _stub("p1", [_ch("A"), _ch("B", "p1"), _ch("C", "p2")])
        got = main.IPTVClient.scoped_all_channels(stub)
        assert [ch["name"] for ch in got] == ["B"]

    def test_scoped_all_channels_all_scope_returns_original(self):
        channels = [_ch("A")]
        stub = _stub("", channels)
        assert main.IPTVClient.scoped_all_channels(stub) is channels

    def test_scoped_channels_by_group_filters_per_list(self):
        stub = _stub("p1", [])
        stub.channels_by_group = {
            "News": [_ch("A"), _ch("B", "p1")],
            "Movies": [_ch("C", "p2")],
        }
        got = main.IPTVClient.scoped_channels_by_group(stub)
        assert [ch["name"] for ch in got["News"]] == ["B"]
        assert "Movies" not in got

    def test_scoped_channels_by_group_all_scope_is_original_dict(self):
        groups = {"News": [_ch("A")]}
        stub = _stub("", [])
        stub.channels_by_group = groups
        assert main.IPTVClient.scoped_channels_by_group(stub) is groups


class TestComboIndex:
    def test_index_zero_for_all_scope(self):
        stub = _stub("", [])
        assert main.IPTVClient._combo_index_for_scope(stub, "") == 0

    def test_index_for_known_scope(self):
        stub = _stub("p1", [])
        stub.playlist_sources = [{"id": "p1", "name": "One"}, {"id": "p2"}]
        # Combo index 0 is "All playlists"; playlists start at 1.
        assert main.IPTVClient._combo_index_for_scope(stub, "p1") == 1
        assert main.IPTVClient._combo_index_for_scope(stub, "p2") == 2

    def test_unknown_scope_falls_back_to_all(self):
        stub = _stub("gone", [])
        stub.playlist_sources = [{"id": "p1"}]
        assert main.IPTVClient._combo_index_for_scope(stub, "gone") == 0


class TestScopeChange:
    def test_change_persists_and_resets_group(self, monkeypatch):
        saved = {}
        invalidate = []
        stub = _stub("p1", [])
        stub.playlist_sources = [{"id": "p2", "name": "Two"}]
        stub.config = {"playlist_scope": "p1"}
        stub._favorite_key_set = set()
        stub.filter_box = SimpleNamespace(ChangeValue=lambda _v: None)
        stub.current_group = "News"
        stub._group_keys = ["News"]
        stub.group_list = SimpleNamespace(GetSelection=lambda: 0)
        stub._invalidate_favorites_cache = lambda: invalidate.append(1)
        stub._refresh_group_ui = lambda: None

        class FakeCombo:
            def GetSelection(self):
                return 1  # second entry = first playlist in the picker

        stub.playlist_scope_combo = FakeCombo()

        monkeypatch.setattr(main, "save_config", lambda cfg: saved.update(cfg))

        main.IPTVClient.on_playlist_scope_changed(stub, None)

        assert stub.playlist_scope == "p2"
        assert saved["playlist_scope"] == "p2"
        assert stub.current_group == "All Channels"
        assert invalidate == [1]

    def test_selecting_all_playlists_stores_sentinel(self, monkeypatch):
        saved = {}
        stub = _stub("p1", [])
        stub.playlist_sources = [{"id": "p1", "name": "One"}]
        stub.config = {"playlist_scope": "p1"}
        stub._favorite_key_set = set()
        stub.filter_box = SimpleNamespace(ChangeValue=lambda _v: None)
        stub.current_group = "All Channels"
        stub._group_keys = []
        stub.group_list = SimpleNamespace(GetSelection=lambda: 0)
        stub._invalidate_favorites_cache = lambda: None
        stub._refresh_group_ui = lambda: None

        class FakeCombo:
            def GetSelection(self):
                return 0  # "All playlists"

        stub.playlist_scope_combo = FakeCombo()

        # save_config must be called with the sentinel, not the playlist id.
        monkeypatch.setattr(main, "save_config", lambda cfg: saved.update(cfg))
        monkeypatch.setattr(stub, "_invalidate_favorites_cache", lambda: None)

        main.IPTVClient.on_playlist_scope_changed(stub, None)
        assert stub.playlist_scope == ""
        assert saved["playlist_scope"] == ""

    def test_same_scope_change_is_ignored(self, monkeypatch):
        stub = _stub("p1", [])
        stub.playlist_sources = [{"id": "p1", "name": "One"}]
        stub.config = {"playlist_scope": "p1"}
        stub._favorite_key_set = set()
        stub.filter_box = SimpleNamespace(ChangeValue=lambda _v: None)
        stub.current_group = "News"
        stub._group_keys = ["News"]
        stub.group_list = SimpleNamespace(GetSelection=lambda: 0)
        stub._invalidate_favorites_cache = lambda: None

        class FakeCombo:
            def GetSelection(self):
                return 1

        stub.playlist_scope_combo = FakeCombo()
        called = []
        monkeypatch.setattr(main, "save_config", lambda cfg: called.append(1))

        main.IPTVClient.on_playlist_scope_changed(stub, None)
        assert called == []
        assert stub.current_group == "News"
