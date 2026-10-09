"""The background media-type probe never opens a connection while something plays.

Dispatcharr's SceneTime plan allows two connections. Arrowing through the list
while watching made the probe take the second one, so the next tune failed with
"All active M3U profiles have reached maximum connection limits" (2026-10-01).
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402

CH = {"name": "Global", "url": "http://provider.invalid/live/global.ts"}


class _Proc:
    def __init__(self):
        self.killed = False

    def poll(self):
        return 0 if self.killed else None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def _client(playing):
    client = types.SimpleNamespace(
        _media_probe_inflight=set(),
        _media_probe_procs={},
        _classify_channel_media=lambda _c: (main.media_type.MEDIA_UNKNOWN, None),
        _channel_record_key=lambda c: "key:" + c["name"],
        _channel_display_name=lambda c: c["name"],
        _internal_player_has_media=lambda: playing,
        _single_stream_provider_busy=lambda *_a, **_k: False,
    )
    client.started = []
    client._probe_channel_media_worker = lambda *a: client.started.append(a)
    for name in ("_probe_channel_media_now", "_terminate_media_probe"):
        setattr(client, name, types.MethodType(getattr(main.IPTVClient, name), client))
    return client


def test_no_probe_while_the_player_has_a_stream(monkeypatch):
    monkeypatch.setattr(main.IPTVClient, "_single_stream_provider_busy", lambda *_a, **_k: False)
    started = []
    monkeypatch.setattr(main.threading, "Thread", lambda target, args, daemon: types.SimpleNamespace(
        start=lambda: started.append(args)))
    _client(playing=True)._probe_channel_media_now(CH)
    assert started == []
    _client(playing=False)._probe_channel_media_now(CH)
    assert len(started) == 1


def test_a_real_session_preempts_every_probe():
    client = _client(playing=False)
    a, b = _Proc(), _Proc()
    client._media_probe_procs = {"key:Global": a, "key:Other": b}
    client._media_probe_inflight = {"key:Global", "key:Other"}
    client._terminate_media_probe({"name": "Sky One"})
    assert a.killed and b.killed
    assert client._media_probe_inflight == set() and client._media_probe_procs == {}


def test_preempted_probe_makes_playback_wait_for_the_server(monkeypatch):
    # 2026-10-08: probes of CBC and Saisons still held both SceneTime
    # connections when Sky Mix was opened 0.1 s later, so Dispatcharr fell back
    # to dead backup streams and the channel took 50 s to start.
    clock = [1000.0]
    monkeypatch.setattr(main.catchup_direct.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(main.catchup_direct, "_released_at", {})
    client = _client(playing=False)
    proc = _Proc()
    proc.probe_url = "https://tv.example/live/u/p/93448"
    client._media_probe_procs = {"key:Saisons": proc}
    client._terminate_media_probe({"name": "Sky Mix"})
    settle = main.catchup_direct._MEDIA_SESSION_SETTLE_SECONDS
    remaining = main.catchup_direct.media_settle_remaining
    assert remaining("https://tv.example/live/u/p/76953") == settle
    assert remaining("https://other.example/live/1") == 0.0
    clock[0] += settle
    assert remaining("https://tv.example/live/u/p/76953") == 0.0