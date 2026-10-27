"""Stale UI delivery and recording/source startup ownership, without native VLC."""
from concurrent.futures import Future
from io import BytesIO
import queue
import time

import pytest
from types import SimpleNamespace
import client_timeshift
from client_timeshift import LiveBufferMixin
import live_buffer


def harness(monkeypatch):
    callbacks, events, active = queue.Queue(), [], [0]
    monkeypatch.setattr(client_timeshift.wx, 'CallAfter', lambda fn, *args: callbacks.put((fn, args)))
    import recorder
    import catchup_direct
    monkeypatch.setattr(recorder, 'get_ffmpeg_path', lambda: 'unused')
    monkeypatch.setattr(catchup_direct, 'settle_media_session', lambda: None)
    class Frame:
        def __init__(self):
            self._current_url, self._destroyed, self._is_paused = '', False, False
            self.clock = 0
            self.player = SimpleNamespace(get_time=lambda: self.clock, get_state=lambda: 'Playing')
        def stop(self, manual=False):
            done = Future()
            done.set_result(None)
            if not getattr(self, '_buffer_transition', False) and hasattr(self, '_on_buffer_stop'):
                self._on_buffer_stop()
            return done
        def IsShown(self): return True
        def _update_status_label(self, *args, **kw): return
    real = live_buffer.LiveBufferSession
    class Session(real):
        def start(self, ffmpeg, source, headers=None, *, cap_mbps=None):
            active[0] += 1
            events.append(('open', source, active[0], cap_mbps))
            assert active[0] == 1
            owner = self
            class Process:
                stderr, stopped = BytesIO(), False
                def poll(self): return 0 if self.stopped else None
                def terminate(self): self.stopped = True
                def kill(self): self.stopped = True
                def wait(self, timeout=None):
                    time.sleep(0.02)
                    if not getattr(owner, 'counted', False):
                        active[0] -= 1
                        events.append(('close', source, active[0]))
                        owner.counted = True
                    return 0
            self.process = Process()
            self.window.begin('seg-000000000.ts')
            self.window.append(b'x' * 188)
            self.window.finish()
            self.window.publish(b'#EXTM3U\n#EXTINF:2,\nseg-000000000.ts\n')
    monkeypatch.setattr(live_buffer, 'LiveBufferSession', Session)
    class App(LiveBufferMixin):
        def __init__(self):
            self.config = {'live_buffer_enabled': True}
            self.default_player, self.caster = 'Built-in Player', None
            self.recorder = SimpleNamespace(has_active_connection=lambda key: False)
            self._internal_player_frame, self._internal_player_channel = Frame(), None
            self._exit_requested = False
        def _terminate_media_probe(self, channel): return
        def _launch_stream(self, url, title=None, *, stream_kind='live', channel=None,
                           show_internal_player=True, focus_player=True, _buffer_bypass=False):
            if not _buffer_bypass and self._intercept_live_buffer(
                    url, title, stream_kind, channel, show_internal_player, focus_player):
                return
            if not url.startswith('http://127.0.0.1:'):
                assert active[0] == 0
                events.append(('direct', url, active[0]))
            if self._internal_player_frame is None:
                self._internal_player_frame = Frame()
            self._internal_player_frame._current_url, self._internal_player_channel = url, channel
    app = App()
    def pump(predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            try:
                fn, args = callbacks.get(timeout=0.01)
                fn(*args)
            except queue.Empty:
                continue
        assert predicate(), events
    def wait_queued():
        deadline = time.monotonic() + 3
        while callbacks.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert not callbacks.empty()
    return app, events, active, pump, wait_queued


def test_stale_ui_result_is_closed_before_next_source_opens(monkeypatch):
    app, events, active, pump, wait_queued = harness(monkeypatch)
    try:
        app._launch_stream('https://example.invalid/first.ts', channel={'url': 'first'})
        wait_queued()
        app._launch_stream('https://example.invalid/second.ts', channel={'url': 'second'})
        pump(lambda: app._live_buffer_work_done.is_set())
        assert [event[0] for event in events] == ['open', 'close', 'open']
        assert active[0] == 1 and app._live_buffer_current['channel']['url'] == 'second'
    finally:
        app._close_live_buffer_player()
        app._live_buffer_retiring_done.wait(3)
        app._live_buffers.close()


def test_stop_then_direct_play_waits_for_pending_ingest_cleanup(monkeypatch):
    app, events, active, pump, wait_queued = harness(monkeypatch)
    try:
        app._launch_stream('https://example.invalid/first.ts', channel={'url': 'first'})
        wait_queued()
        app._close_live_buffer_player()
        app.config['live_buffer_enabled'] = False
        app._launch_stream('https://example.invalid/direct.ts', channel={'url': 'direct'})
        pump(lambda: any(event[0] == 'direct' for event in events))
        assert [event[0] for event in events] == ['open', 'close', 'direct'] and active[0] == 0
    finally:
        app._close_live_buffer_player()
        app._live_buffers.close()


def test_scheduled_recording_winning_startup_race_prevents_second_source(monkeypatch):
    import catchup_urls
    app, events, active, pump, _ = harness(monkeypatch)
    monkeypatch.setattr(catchup_urls, 'single_stream_provider_key', lambda url: 'fixture')
    failures, recording = [], [False]
    monkeypatch.setattr(client_timeshift, 'message_box', lambda *args, **kw: failures.append(args))
    app.recorder.has_active_connection = lambda key: recording[0]
    registry = app._ensure_live_buffers()
    try:
        with registry.ingest_gate:
            app._launch_stream('https://example.invalid/live.ts', channel={'url': 'live'})
            recording[0] = True
        pump(lambda: bool(failures))
        assert app._live_buffer_work_done.wait(3)
        assert active[0] == 0 and events == []
    finally:
        app._close_live_buffer_player()
        registry.close()


def test_nonzero_native_clock_is_not_added_to_logical_segment_origin(monkeypatch):
    app, _, _, _, _ = harness(monkeypatch)
    frame = app._internal_player_frame
    frame._current_url = 'local'
    frame.clock = 3000000
    app._live_buffer_current = dict(url='local', position=20, last_clock=None,
        session=SimpleNamespace(window=SimpleNamespace(snapshot=lambda: ())))
    assert app._buffer_position()[2] == 20
    frame.clock += 500
    assert app._buffer_position()[2] == 20.5
    frame.clock = 0
    assert app._buffer_position()[2] == 20.5
    frame.clock = 1000
    assert app._buffer_position()[2] == 21.5


@pytest.mark.parametrize('saved,expected', [(2.5, 2.5), ('3.5', 3.5), (0, 0.0),
    ('invalid', 0.0), (-2, 0.0), (0.1, 0.25), (900, 500.0)])
def test_cold_start_buffer_uses_saved_normalized_cap_without_creating_frame(monkeypatch, saved, expected):
    app, events, _, pump, _ = harness(monkeypatch)
    app._internal_player_frame = None
    app.config['internal_player_variant_max_mbps'] = saved
    before = dict(app.config)
    try:
        app._launch_stream('https://example.invalid/master.m3u8', channel={'url': 'master'})
        pump(lambda: app._live_buffer_work_done.is_set())
        opened = next(event for event in events if event[0] == 'open')
        assert opened[3] == expected
        assert app.config == before  # normalization must not mutate live config on the worker
    finally:
        app._close_live_buffer_player()
        app._live_buffer_retiring_done.wait(3)
        app._live_buffers.close()


def test_existing_player_cap_remains_authoritative(monkeypatch):
    app, events, _, pump, _ = harness(monkeypatch)
    app.config['internal_player_variant_max_mbps'] = 8
    app._internal_player_frame._variant_max_mbps = 2
    try:
        app._launch_stream('https://example.invalid/master.m3u8', channel={'url': 'master'})
        pump(lambda: app._live_buffer_work_done.is_set())
        assert next(event for event in events if event[0] == 'open')[3] == 2
    finally:
        app._close_live_buffer_player()
        app._live_buffer_retiring_done.wait(3)
        app._live_buffers.close()
