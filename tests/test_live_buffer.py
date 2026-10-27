"""Store limits, HTTP capability boundaries and real shared TS source tests."""
from pathlib import Path
import urllib.error
import urllib.request
import pytest
from live_buffer import DiskWindow, BufferError, LiveBufferSession, LiveBufferRegistry, source_key


def segment(window, number, size=188):
    name = 'seg-%09d.ts' % number
    window.begin(name)
    for offset in range(0, size, 65536):
        window.append(b'x' * min(65536, size - offset))
    window.finish()
    return name


def manifest(first, last, duration=2):
    return ('#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:%d\n' % first + ''.join(
        '#EXTINF:%s,\nseg-%09d.ts\n' % (duration, i) for i in range(first, last + 1))).encode()


def test_partial_writes_are_bounded_and_old_history_is_evicted_first(tmp_path):
    window = DiskWindow(tmp_path, max_bytes=65536)
    name = segment(window, 0, 40000)
    window.publish(manifest(0, 0))
    window.begin('seg-000000001.ts')
    window.append(b'y' * 40000)
    assert window.used == 40000 and not (tmp_path / name).exists()
    with pytest.raises(BufferError):
        window.append(b'z' * 30000)
    assert sum(p.stat().st_size for p in tmp_path.iterdir()) <= 65536
    window.abort()
    assert window.used == 0


def test_time_window_preserves_absolute_positions_after_eviction(tmp_path):
    window = DiskWindow(tmp_path, max_bytes=65536, seconds=4)
    for i in range(5):
        segment(window, i)
        window.publish(manifest(max(0, i - 2), i))
    assert [(r.sequence, r.start, r.end) for r in window.snapshot()] == [(3, 6, 8), (4, 8, 10)]
    assert window.used == 376


@pytest.mark.parametrize('payload', [b'bad', manifest(0, 0, 'nan'), manifest(0, 0, -1),
    b'#EXTM3U\n#EXTINF:2,\n../../bad.ts\n'])
def test_bad_manifest_is_rejected(tmp_path, payload):
    with pytest.raises((BufferError, ValueError)):
        DiskWindow(tmp_path).publish(payload)


def test_out_of_order_commits_preserve_future_files_and_holes_cannot_be_false_sequences(tmp_path):
    window = DiskWindow(tmp_path, max_bytes=65536)
    window.publish(manifest(0, 0))
    segment(window, 0)
    assert window.snapshot()[0].start == 0
    segment(window, 2)
    assert 'seg-000000002.ts' in window.files
    window.publish(manifest(0, 2))
    assert [r.sequence for r in window.snapshot()] == [2]


def test_loopback_views_are_read_only_and_expired_files_return_gone():
    session = LiveBufferSession(max_bytes=65536, seconds=4)
    try:
        segment(session.window, 0)
        session.window.publish(manifest(0, 0))
        url, _ = session.cursor(999)
        body = urllib.request.urlopen(url, timeout=2).read()
        assert session._write_token.encode() not in body and b'PLAYLIST-TYPE:EVENT' not in body
        address = url.rsplit('/', 1)[0] + '/seg-000000000.ts'
        assert urllib.request.urlopen(address, timeout=2).read() == b'x' * 188
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(urllib.request.Request(url, data=b'x', method='PUT'), timeout=2)
        assert err.value.code == 404
        for i in range(1, 4):
            segment(session.window, i)
            session.window.publish(manifest(0, i))
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(address, timeout=2)
        assert err.value.code == 410
    finally:
        folder = Path(session._temp.name)
        session.close()
        assert not folder.exists()


def test_recording_lease_and_protected_cursor_outlive_player_seeks_and_stop():
    session, registry = LiveBufferSession(max_bytes=65536), LiveBufferRegistry()
    try:
        segment(session.window, 0)
        session.window.publish(manifest(0, 0))
        registry.put('https://example.invalid/live', {}, session)
        local, headers, lease = registry.recording_input('https://example.invalid/live', {})
        for _ in range(50):
            session.cursor()
        assert urllib.request.urlopen(local, timeout=2).status == 200
        assert headers == {} and len(session._views) <= 32
        session.release()
        assert not session._closed.is_set()
        lease.release()
        lease.release()
        assert session._closed.is_set()
        assert source_key('a', {'A': 'b'}) == source_key('a', {'a': 'b'})
    finally:
        registry.close()


def test_hls_master_selects_one_variant_and_preserves_headers(monkeypatch):
    from io import BytesIO
    from live_buffer import resolve_hls_input
    hits = []
    class Response(BytesIO):
        def geturl(self): return hits[-1][0]
    def fetch(request, timeout):
        hits.append((request.full_url, request.get_header('Authorization')))
        return Response(b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=6000000\nhigh.m3u8\n'
                        b'#EXT-X-STREAM-INF:BANDWIDTH=1000000\nlow.m3u8\n' if len(hits) == 1
                        else b'#EXTM3U\n#EXTINF:2,\none.ts\n')
    monkeypatch.setattr(urllib.request, 'urlopen', fetch)
    assert resolve_hls_input('https://example.invalid/master.m3u8', {'Authorization': 'Bearer fixture'}, 2).endswith('/low.m3u8')
    assert hits == [('https://example.invalid/master.m3u8', 'Bearer fixture'),
                    ('https://example.invalid/low.m3u8', 'Bearer fixture')]


@pytest.mark.parametrize('payload', [
    b'#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,URI="subs.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1\na.m3u8\n',
    b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nfile:///private.m3u8\n',
    b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nmaster.m3u8\n', b'x' * (256 * 1024 + 1)],
    ids=['rendition-loss', 'protocol-escape', 'cycle', 'oversize-256k'])
def test_hls_metadata_refuses_rendition_loss_protocol_escape_cycles_and_oversize(monkeypatch, payload):
    from io import BytesIO
    from live_buffer import resolve_hls_input
    class Response(BytesIO):
        def geturl(self): return 'https://example.invalid/master.m3u8'
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **kw: Response(payload))
    with pytest.raises(BufferError):
        resolve_hls_input('https://example.invalid/master.m3u8')


def test_invalid_config_does_not_enable_buffering():
    from live_buffer import buffer_settings
    assert buffer_settings({}) == (False, 600, 512)
    assert buffer_settings({'live_buffer_enabled': 'true', 'live_buffer_seconds': float('inf'),
                            'live_buffer_mib': True}) == (False, 600, 512)
    assert buffer_settings({'live_buffer_enabled': True, 'live_buffer_seconds': -1,
                            'live_buffer_mib': 99999}) == (True, 60, 4096)


def test_unsupported_codec_warning_prevents_silent_subtitle_loss():
    from io import BytesIO
    from types import SimpleNamespace
    session = LiveBufferSession(max_bytes=65536)
    try:
        session.process = SimpleNamespace(stderr=BytesIO(b'codec subrip is muxed as a private data stream\n'), poll=lambda: 0)
        session._drain_stderr()
        segment(session.window, 0)
        session.window.publish(manifest(0, 0))
        with pytest.raises(BufferError):
            session.wait_ready(1)
    finally:
        session.close()


def test_real_recording_rewind_and_player_stop_share_one_provider_get(tmp_path, monkeypatch):
    import http.server
    import shutil
    import subprocess
    import threading
    import time
    import recorder
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        pytest.skip('FFmpeg/FFprobe unavailable')
    source = tmp_path / 'provider.ts'
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=25',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '16',
                    '-c:v', 'mpeg2video', '-g', '25', '-c:a', 'mp2', '-f', 'mpegts', str(source)],
                   check=True, timeout=20)
    payload, requests = source.read_bytes(), []
    class Provider(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): return
        def do_GET(self):
            requests.append((self.path, self.headers.get('User-Agent')))
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Content-Type', 'video/mp2t')
            self.end_headers()
            try:
                step = 32768
                for offset in range(0, len(payload), step):
                    self.wfile.write(payload[offset:offset + step])
                    self.wfile.flush()
                    time.sleep(step / len(payload) * 16)
            except OSError:
                return
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = 'http://127.0.0.1:%d/source.ts' % server.server_address[1]
    headers = {'User-Agent': 'IPTV buffer test'}
    session, registry = LiveBufferSession(max_bytes=8 * 1024**2, seconds=30), LiveBufferRegistry()
    manager = recorder.RecordingManager()
    manager.live_buffer_registry = registry
    monkeypatch.setattr(recorder, 'get_ffmpeg_path', lambda: ffmpeg)
    try:
        registry.put(url, headers, session)
        session.start(ffmpeg, url, headers)
        session.wait_ready(12)
        deadline = time.monotonic() + 12
        while len(session.window.snapshot()) < 4 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(session.window.snapshot()) >= 4 and session.process.poll() is None
        local, chosen = session.cursor(4)
        def first_pts(input_url):
            import json
            result = subprocess.check_output([ffprobe, '-v', 'error', '-select_streams', 'v:0',
                '-read_intervals', '%+#1', '-show_entries', 'packet=pts_time', '-of', 'json', input_url], timeout=10)
            return float(json.loads(result)['packets'][0]['pts_time'])
        assert abs(first_pts(local) - first_pts(str(source)) - chosen.start) < 0.5
        recording = manager.start(url, 'Buffered recording', 'provider_mkv', headers,
                                  str(tmp_path / 'recordings'), duration=1)
        assert recording.url.startswith(session.origin)
        assert recording.key == url  # public identity must not become a private loopback cursor
        session.release()
        assert not session._closed.is_set()
        assert recording.process.wait(timeout=15) == 0
        deadline = time.monotonic() + 8
        while recording.buffer_lease is not None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert recording.buffer_lease is None and session._closed.is_set()
        assert Path(recording.out_path).stat().st_size > 188
        assert requests == [('/source.ts', 'IPTV buffer test')]
    finally:
        manager.stop_all(wait=True)
        registry.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_playlist_reload_target_does_not_shrink_and_large_gop_change_fails_visibly(tmp_path):
    window = DiskWindow(tmp_path, max_bytes=65536)
    segment(window, 0)
    window.publish(manifest(0, 0, 2))
    assert window.target_duration == 3
    segment(window, 1)
    window.publish(manifest(1, 1, 1))
    assert window.target_duration == 3
    segment(window, 2)
    window.publish(manifest(2, 2, 10))
    assert window.error and window.target_duration == 3
