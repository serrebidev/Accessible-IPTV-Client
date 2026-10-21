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
