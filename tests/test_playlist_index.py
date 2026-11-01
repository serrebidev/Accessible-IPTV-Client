import types

from playlist_index import PlaylistIndex


def _models():
    first = {"name": "News One", "group": "News", "playlist-id": "a"}
    second = {"name": "Sports One", "group": "Sports", "playlist-id": "b"}
    third = {"name": "News Two", "group": "News", "playlist-id": "a"}
    all_channels = [first, second, third]
    groups = {"News": [first, third], "Sports": [second]}
    return all_channels, groups, (first, second, third)


def test_index_reuses_channel_references_and_scope_order():
    channels, groups, refs = _models()
    index = PlaylistIndex(channels, groups)
    index.set_all_groups(groups)

    assert index.all_for_scope("a") == [refs[0], refs[2]]
    assert index.groups_for_scope("a")["News"] == [refs[0], refs[2]]
    assert index.all_for_scope("a")[0] is refs[0]


def test_index_keeps_scope_membership_as_compact_positions():
    channels, groups, _ = _models()
    index = PlaylistIndex(channels, groups)

    assert index._scope_channels["a"].tolist() == [0, 2]
    assert index._scope_groups["a"]["News"].tolist() == [0, 2]


def test_index_search_preserves_playlist_order_and_substring_semantics():
    channels, groups, refs = _models()
    index = PlaylistIndex(channels, groups)

    assert index.search(channels, "news") == [refs[0], refs[2]]


def test_index_handles_scope_without_matches():
    channels, groups, _ = _models()
    index = PlaylistIndex(channels, groups)

    assert index.all_for_scope("missing") == []
    assert index.groups_for_scope("missing") == {}


def test_navigation_uses_scan_fallback_until_async_index_is_ready(monkeypatch):
    channels, groups, _ = _models()
    client = types.SimpleNamespace(
        all_channels=channels,
        channels_by_group=groups,
        playlist_scope="a",
        _playlist_index=None,
        _playlist_index_generation=0,
        _playlist_index_building=False,
        _playlist_load_token=0,
    )
    client._finish_playlist_index_warm = (
        lambda index, current_channels, generation:
        main.IPTVClient._finish_playlist_index_warm(
            client, index, current_channels, generation)
    )
    jobs = []

    class FakeThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            jobs.append(self.target)

    import main
    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    monkeypatch.setattr(main.wx, "CallAfter", lambda callback, *args: callback(*args))
    main.IPTVClient._warm_playlist_index_background(client)

    assert main.IPTVClient._get_playlist_index(client) is None
    assert main.IPTVClient.scoped_all_channels(client) == [channels[0], channels[2]]

    jobs.pop()()
    assert main.IPTVClient._get_playlist_index(client) is not None


def test_refresh_waits_for_stale_index_worker_before_starting_another(monkeypatch):
    channels, groups, _ = _models()
    client = types.SimpleNamespace(
        all_channels=channels,
        channels_by_group=groups,
        _playlist_index=None,
        _playlist_index_generation=0,
        _playlist_index_building=False,
        _playlist_load_token=0,
    )
    jobs = []

    class FakeThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            jobs.append(self.target)

    import main
    client._finish_playlist_index_warm = (
        lambda index, current_channels, generation:
        main.IPTVClient._finish_playlist_index_warm(
            client, index, current_channels, generation)
    )
    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    monkeypatch.setattr(main.wx, "CallAfter", lambda callback, *args: callback(*args))

    main.IPTVClient._warm_playlist_index_background(client)
    assert len(jobs) == 1

    client.all_channels = list(channels)
    client.channels_by_group = dict(groups)
    client._playlist_load_token = 1
    main.IPTVClient._invalidate_playlist_index(client)
    main.IPTVClient._warm_playlist_index_background(client)
    assert len(jobs) == 1

    jobs.pop(0)()
    assert client._playlist_index_building is False

    main.IPTVClient._warm_playlist_index_background(client)
    assert len(jobs) == 1
