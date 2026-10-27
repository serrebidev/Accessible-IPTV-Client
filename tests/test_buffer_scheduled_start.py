"""Scheduled GUI callback -> real DVR state and local recording lease regressions."""
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import dvr
import main
import recorder
from client_timeshift import LiveBufferMixin
from live_buffer import LiveBufferRegistry, LiveBufferSession


def client_for_schedule(monkeypatch, tmp_path, *, pending=False, registry=None, manager=None):
    monkeypatch.setattr(main.wx, 'CallAfter', lambda *args, **kw: None)
    monkeypatch.setattr(main, 'get_recordings_dir', lambda config: str(tmp_path / 'recordings'))
    client = SimpleNamespace(
        config={}, recorder=manager or SimpleNamespace(has_active_connection=lambda key: False),
        _live_buffer_pending=pending, _live_buffers=registry,
        _resolve_live_url=lambda channel: channel['url'],
        _terminate_media_probe=lambda channel: None,
        _classify_channel_media=lambda channel: ('video', 'saved'),
        _recording_audio_intent=lambda *a, **kw: None,
        _recording_audio_choice=lambda *a: None,
        _channel_display_name=lambda channel: 'Fixture',
        _note_recording_started=lambda: None, _on_recording_finished=lambda *a: None,
        _show_or_queue_message_box=lambda *a, **kw: None)
    client._buffer_source = lambda url, headers: LiveBufferMixin._buffer_source(client, url, headers)
    client._buffer_probe_input = lambda url, headers: LiveBufferMixin._buffer_probe_input(client, url, headers)
    job = dict(id='fixture', status=dvr.STATUS_RECORDING, title='Fixture programme', format='provider_mkv',
               start_ts=1, stop_ts=9999999999, channel={'url': 'https://example.invalid/live.ts'})
    scheduler = dvr.DVRScheduler(str(tmp_path / 'schedule.json'),
        on_start=lambda job: main.IPTVClient._start_scheduled_recording(client, job), on_stop=lambda job: None)
    scheduler.add_job(job)
    return client, scheduler, job


def test_pending_buffer_transition_is_failed_not_a_phantom_recording(monkeypatch, tmp_path):
    client, scheduler, job = client_for_schedule(monkeypatch, tmp_path, pending=True)
    attempts = []
    client.recorder.start = lambda *a, **kw: attempts.append((a, kw))
    scheduler._start_job_worker(job['id'], job)
    result = scheduler.get_job(job['id'])
    assert result['status'] == dvr.STATUS_FAILED
    assert result['recording_id'] is None and result.get('message')
    assert not attempts and not result.get('output_path')
    assert not (tmp_path / 'recordings').exists()


def test_ready_buffer_reaches_recorder_and_keeps_dvr_id_and_output(monkeypatch, tmp_path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('Real FFmpeg unavailable')
    source = tmp_path / 'source.ts'
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=96x54:rate=25',
                    '-t', '2', '-c:v', 'mpeg2video', '-g', '25', '-f', 'mpegts', str(source)],
                   check=True, timeout=15)
    session, registry, manager = LiveBufferSession(max_bytes=4 * 1024**2), LiveBufferRegistry(), recorder.RecordingManager()
    manager.live_buffer_registry = registry
    monkeypatch.setattr(recorder, 'get_ffmpeg_path', lambda: ffmpeg)
    try:
        payload = source.read_bytes()
        session.window.begin('seg-000000000.ts')
        for offset in range(0, len(payload), 65536):
            session.window.append(payload[offset:offset + 65536])
        session.window.finish()
        session.window.publish(b'#EXTM3U\n#EXTINF:2,\nseg-000000000.ts\n#EXT-X-ENDLIST\n')
        client, scheduler, job = client_for_schedule(monkeypatch, tmp_path, registry=registry, manager=manager)
        registry.put(job['channel']['url'], {}, session)
        probes = []
        client._recording_audio_choice = lambda url, *args: probes.append(url)
        scheduler._start_job_worker(job['id'], job)
        result = scheduler.get_job(job['id'])
        assert result['status'] == dvr.STATUS_RECORDING and isinstance(result['recording_id'], int)
        assert result['output_path'] and probes[0].startswith(session.origin)
        recording = manager._recordings[result['recording_id']]
        assert recording.url.startswith(session.origin) and recording.key == 'dvr:fixture'
        assert recording.process.wait(timeout=15) == 0
        assert Path(result['output_path']).stat().st_size > 188
    finally:
        manager.stop_all(wait=True)
        registry.close()


@pytest.mark.parametrize('pending,owned', [(True, False), (False, True)])
def test_only_advisory_probe_is_skipped_for_buffer_owned_or_pending_source(pending, owned):
    calls = []
    client = SimpleNamespace(_live_buffer_pending=pending,
        _live_buffers=SimpleNamespace(owns_url=lambda url: owned),
        _classify_channel_media=lambda channel: calls.append(channel))
    main.IPTVClient._probe_channel_media_now(client, {'url': 'https://example.invalid/live.ts'})
    assert calls == []
