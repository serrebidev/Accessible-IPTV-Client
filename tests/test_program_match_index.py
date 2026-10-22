"""The programme-match index: built off the GUI thread, used by the dialogs.

Playing or scheduling a programme from "What's on Now" resolves its channel
in the playlist. That lookup is an index over every channel, and building it
takes seconds on a full playlist - the app freezes while it runs and the
screen reader says nothing. It is built in the worker now, before the
dialog appears.
"""

import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def _client(channels):
    client = types.SimpleNamespace()
    client.config = {"epg_enabled": True}
    client.all_channels = list(channels)
    client._program_match_cache = None
    client._program_match_index = types.MethodType(
        main.IPTVClient._program_match_index, client)
    client._present_whats_on_now = lambda programs, error: None
    return client


class _FakeDB:
    def __init__(self, *_args, **_kwargs):
        pass

    def get_all_now_playing(self):
        return [{"channel_name": "CNN", "channel_id": "cnn", "title": "News"}]

    def close(self):
        pass


def test_whats_on_now_builds_the_channel_index_before_the_dialog(monkeypatch):
    monkeypatch.setattr(main, "EPGDatabase", _FakeDB)
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: None)
    client = _client([{"name": "CNN", "tvg-id": "cnn", "url": "http://h/1"}])

    main.IPTVClient.show_whats_on_now(client, None)

    deadline = time.monotonic() + 5
    while client._program_match_cache is None and time.monotonic() < deadline:
        time.sleep(0.02)

    assert client._program_match_cache is not None, \
        "the channel index was left to be built on the GUI thread"


def test_the_index_is_dropped_when_the_channel_list_is_replaced():
    """The index is keyed on the channel list, so a new list needs a new one."""
    channels = [{"name": "CNN", "tvg-id": "cnn", "url": "http://h/1"}]
    client = _client(channels)

    main.IPTVClient._program_match_index(client)
    assert client._program_match_cache is not None

    client.all_channels = list(channels) + [{"name": "BBC", "url": "http://h/2"}]
    main.IPTVClient._program_match_index(client)
    rows, _by_tvg_id, _memo = client._program_match_cache[1], None, None
    assert len(rows) == 2


class _CountingRows(list):
    """The rows of the index, counting how many of them are looked at."""

    def __init__(self, rows):
        super().__init__(rows)
        self.visited = 0

    def __iter__(self):
        for row in super().__iter__():
            self.visited += 1
            yield row


CHANNELS = [
    {"name": "BBC One HD", "tvg-name": "BBC One", "tvg-id": "bbc.one.uk", "url": "u1"},
    {"name": "BBC Two", "tvg-name": "BBC Two", "tvg-id": "bbc.two.uk", "url": "u2"},
    {"name": "CNN International", "tvg-name": "CNN Intl", "tvg-id": "cnn.int", "url": "u3"},
    {"name": "Sky Sports Main Event", "tvg-name": "", "tvg-id": "", "url": "u4"},
]


def _client_with_rows(channels):
    client = _client(channels)
    main.IPTVClient._program_match_index(client)
    index = client._program_match_cache
    counting = _CountingRows(index.rows)
    client._program_match_cache = index._replace(rows=counting)
    return client, counting


def test_a_matched_programme_does_not_scan_the_whole_playlist():
    """The strong match rules are equality rules, so they are lookups.

    The scan they replaced touched every channel in the playlist: half a
    second on a 257,000-channel provider, on the GUI thread, for every row
    the user highlighted.
    """
    client, rows = _client_with_rows(CHANNELS)

    got = main.IPTVClient._find_matching_channel_for_program(
        client, {"channel_name": "CNN International", "channel_id": ""})

    assert got is not None and got["url"] == "u3"
    assert rows.visited == 0, "the lookup still scanned the playlist"


def test_a_fuzzy_programme_still_finds_its_channel():
    """When nothing matches strongly, the weak rules still run."""
    client, rows = _client_with_rows(CHANNELS)

    got = main.IPTVClient._find_matching_channel_for_program(
        client, {"channel_name": "Sky Sports Main", "channel_id": ""})

    assert got is not None and got["url"] == "u4"
    assert rows.visited > 0, "the fuzzy rules never ran"


def test_the_first_channel_wins_when_two_match_the_same_way():
    """Ties keep the first channel, like the scan the lookups replaced."""
    channels = [
        {"name": "Feed A", "tvg-name": "Feed A", "tvg-id": "", "url": "a"},
        {"name": "Feed B", "tvg-name": "Feed B", "tvg-id": "", "url": "b"},
    ]
    client, _rows = _client_with_rows(channels)

    got = main.IPTVClient._find_matching_channel_for_program(
        client, {"channel_name": "Feed B", "channel_id": ""})

    assert got["url"] == "b"


def test_the_index_is_built_off_the_gui_thread():
    """The build covers every channel; the user must not wait for it."""
    client = _client(CHANNELS)
    client._program_match_cache = None

    main.IPTVClient._warm_program_match_index(client)

    deadline = time.monotonic() + 5
    while client._program_match_cache is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert client._program_match_cache is not None, "the index was not built"
