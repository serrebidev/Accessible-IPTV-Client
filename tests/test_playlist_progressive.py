from __future__ import annotations

import types
import time

import main


class _ChannelList:
    def __init__(self, focused=False):
        self.selection = -1
        self.focused = focused
        self.count = 0
        self.selections = []
        self.focus_calls = 0

    def GetSelection(self):
        return self.selection

    def SetSelection(self, index):
        self.selection = index
        self.selections.append(index)

    def set_virtual_count(self):
        self.count += 1

    def HasFocus(self):
        return self.focused

    def SetFocus(self):
        self.focus_calls += 1


def _client(channels, *, focused=False):
    client = types.SimpleNamespace(
        displayed=[],
        _populate_token=0,
        _PLAYLIST_LARGE_DISPLAY_THRESHOLD=3,
        _PLAYLIST_DISPLAY_BATCH_SIZE=2,
        channel_list=_ChannelList(focused=focused),
        IsShown=lambda: True,
        IsIconized=lambda: False,
        on_highlight=lambda: None,
        _maybe_autostart_epg_import=lambda: None,
    )
    client.source = channels
    return client


def test_large_channel_publication_batches_stop_after_a_new_population(monkeypatch):
    queued = []
    monkeypatch.setattr(main.wx, "CallLater", lambda _delay, callback, *args: queued.append((callback, args)))
    first = [{"name": f"first-{i}"} for i in range(6)]
    second = [{"name": f"second-{i}"} for i in range(6)]
    client = _client(first)

    main.IPTVClient._populate_channel_list_chunked(client, first)
    stale_callback, stale_args = queued.pop(0)
    main.IPTVClient._populate_channel_list_chunked(client, second)

    stale_callback(*stale_args)

    assert [row["data"]["name"] for row in client.displayed] == ["second-0", "second-1"]


def test_refresh_population_restores_selected_channel_without_stealing_focus(monkeypatch):
    monkeypatch.setattr(main.wx, "CallLater", lambda _delay, callback, *args: None)
    channels = [{"name": "One"}, {"name": "Two"}]
    client = _client(channels, focused=True)
    client.displayed = [{"type": "channel", "data": channels[1]}]
    client.channel_list.selection = 0

    main.IPTVClient._populate_channel_list_chunked(
        client,
        channels,
        selected_channel_key="Two",
        preserve_channel_focus=True,
    )

    assert client.channel_list.selection == 1
    assert client.channel_list.focus_calls == 0


def test_large_refresh_defers_selection_until_selected_batch_arrives(monkeypatch):
    queued = []
    monkeypatch.setattr(
        main.wx,
        "CallLater",
        lambda _delay, callback, *args: queued.append((callback, args)),
    )
    channels = [{"name": f"Channel {i}"} for i in range(6)]
    client = _client(channels, focused=True)
    client.displayed = [{"type": "channel", "data": channels[4]}]
    client.channel_list.selection = 0

    main.IPTVClient._populate_channel_list_chunked(
        client,
        channels,
        selected_channel_key="Channel 4",
        preserve_channel_focus=True,
    )

    assert client.channel_list.selections == []
    while queued:
        callback, args = queued.pop(0)
        callback(*args)
    assert client.channel_list.selection == 4
    assert client.channel_list.focus_calls == 0


def test_large_publication_exposes_first_batch_and_callback_timings(monkeypatch):
    queued = []
    timestamps = []
    monkeypatch.setattr(
        main.wx,
        "CallLater",
        lambda _delay, callback, *args: queued.append((callback, args)),
    )
    channels = [{"name": f"Channel {i}"} for i in range(7)]
    client = _client(channels)
    client._PLAYLIST_LARGE_DISPLAY_THRESHOLD = 3
    client._PLAYLIST_DISPLAY_BATCH_SIZE = 2
    original_set_count = client.channel_list.set_virtual_count
    client.channel_list.set_virtual_count = lambda: (
        timestamps.append(time.perf_counter()),
        original_set_count(),
    )[1]

    started = time.perf_counter()
    main.IPTVClient._populate_channel_list_chunked(client, channels)
    first_batch_ready = time.perf_counter()
    while queued:
        callback, args = queued.pop(0)
        callback(*args)
    finished = time.perf_counter()

    assert len(client.displayed) == len(channels)
    assert first_batch_ready >= started
    assert len(timestamps) == 4
    assert timestamps[0] <= timestamps[-1] <= finished


def test_account_discovery_drops_results_for_replaced_playlist(monkeypatch):
    jobs = []
    callbacks = []
    old_channels = [{"name": "Old"}]
    shown = []
    client = types.SimpleNamespace(
        playlist_sources=["old.m3u"],
        all_channels=old_channels,
        _playlist_load_token=1,
        _present_account_info=lambda accounts, error: shown.append((accounts, error)),
    )

    class FakeThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            jobs.append(self.target)

    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    monkeypatch.setattr(main, "_lower_current_thread_priority", lambda: None)
    monkeypatch.setattr(main.account_info, "discover_accounts", lambda *_args: ["old"])
    monkeypatch.setattr(main.wx, "CallAfter", lambda callback, *args: callbacks.append((callback, args)))

    main.IPTVClient.show_account_info(client, None)
    client.all_channels = [{"name": "New"}]
    client._playlist_load_token = 2
    jobs.pop()()
    callback, args = callbacks.pop()
    callback(*args)

    assert shown == []
