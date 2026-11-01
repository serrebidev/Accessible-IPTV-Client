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


def test_index_search_preserves_playlist_order_and_substring_semantics():
    channels, groups, refs = _models()
    index = PlaylistIndex(channels, groups)

    assert index.search(channels, "news") == [refs[0], refs[2]]


def test_index_handles_scope_without_matches():
    channels, groups, _ = _models()
    index = PlaylistIndex(channels, groups)

    assert index.all_for_scope("missing") == []
    assert index.groups_for_scope("missing") == {}
