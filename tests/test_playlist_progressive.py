from __future__ import annotations

import types

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
