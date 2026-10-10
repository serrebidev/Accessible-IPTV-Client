import contextlib
import io
import os
import sys
import http.server
import socketserver
import subprocess
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import recorder
from recorder import (
    RECORDING_FORMATS,
    build_ffmpeg_command,
    format_extension,
    sanitize_filename,
)
import options


FFMPEG = "ffmpeg"


def _available_ffmpeg():
    path = recorder.get_ffmpeg_path()
    try:
        subprocess.run([path, "-version"], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        return None
    return path


def _cmd(fmt, url="http://host/live.ts", out="out", headers=None):
    ext = format_extension(fmt)
    return build_ffmpeg_command(FFMPEG, url, f"{out}.{ext}", fmt, headers)


def _make_source_ts(ffmpeg, path):
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=duration=1:size=96x54:rate=8",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-f", "mpegts", str(path),
    ], check=True, timeout=30)


@contextlib.contextmanager
def _looping_ts_server(source):
    """Serve ``source`` forever over HTTP, the way a live channel would."""

    class FixtureHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass

        def do_GET(self):
            if self.path != "/source.ts":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/MP2T")
            self.end_headers()
            bytes_sent = 0
            try:
                while True:
                    with open(source, "rb") as handle:
                        while True:
                            chunk = handle.read(4096)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                            bytes_sent += len(chunk)
                            if bytes_sent > 32768:
                                time.sleep(0.02)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

    class ReusableServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    with ReusableServer(("127.0.0.1", 0), FixtureHandler) as httpd:
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield "http://127.0.0.1:{port}/source.ts".format(port=httpd.server_address[1])
        finally:
            httpd.shutdown()


def _top_level_boxes(path):
    """The names of an MP4's top-level boxes, in file order."""
    names = []
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        offset = 0
        while offset < size:
            handle.seek(offset)
            header = handle.read(16)
            if len(header) < 8:
                break
            box_size = int.from_bytes(header[0:4], "big")
            names.append(header[4:8].decode("latin-1"))
            if box_size == 1:
                box_size = int.from_bytes(header[8:16], "big")
            elif box_size == 0:
                break
            if box_size < 8:
                break
            offset += box_size
    return names


def test_every_format_has_a_builder_and_extension():
    for key, (label, ext, kind) in RECORDING_FORMATS.items():
        cmd = _cmd(key)
        assert cmd[0] == FFMPEG
        assert cmd[-1].endswith(f".{ext}")
        assert kind in ("video", "audio")
        assert label  # human-readable


def test_provider_formats_stream_copy():
    mkv = _cmd("provider_mkv")
    assert "-c" in mkv and mkv[mkv.index("-c") + 1] == "copy"
    assert "libx264" not in mkv
    mp4 = _cmd("provider_mp4")
    # MP4 keeps the video bitstream verbatim but re-encodes audio to AAC: provider
    # streams also carry MP3/AC3, which no bitstream filter can mux into MP4, so a
    # plain copy plus aac_adtstoasc failed on those channels.
    assert "-c:v" in mp4 and mp4[mp4.index("-c:v") + 1] == "copy"
    assert "-c:a" in mp4 and mp4[mp4.index("-c:a") + 1] == "aac"
    assert "libx264" not in mp4
    assert "+faststart" in mp4
    assert mp4[-1].endswith(".mp4")


def test_x264_formats_reencode_to_h264_aac():
    for fmt in ("x264_mp4", "x264_mkv"):
        cmd = _cmd(fmt)
        assert "libx264" in cmd
        assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"
    assert "+faststart" in _cmd("x264_mp4")
    assert "+faststart" not in _cmd("x264_mkv")


def test_audio_formats_drop_video_and_pick_codec():
    expectations = {
        "audio_wav": ("pcm_s16le", "wav"),
        "audio_flac": ("flac", "flac"),
        "audio_mp3_v0": ("libmp3lame", "mp3"),
        "audio_aac_m4a": ("aac", "m4a"),
        "audio_opus": ("libopus", "opus"),
    }
    for fmt, (codec, ext) in expectations.items():
        cmd = _cmd(fmt)
        assert "-vn" in cmd
        assert codec in cmd
        assert cmd[-1].endswith(f".{ext}")
    # MP3 V0 == LAME -q:a 0
    mp3 = _cmd("audio_mp3_v0")
    assert mp3[mp3.index("-q:a") + 1] == "0"


def test_header_args_precede_input():
    headers = {
        "user-agent": "TestAgent/9",
        "referer": "http://ref.example/",
        "http-cookie": "a=b",
        "_extra": ["X-Token: secret"],
    }
    cmd = _cmd("provider_mkv", headers=headers)
    i_index = cmd.index("-i")
    assert "-user_agent" in cmd and cmd.index("-user_agent") < i_index
    assert cmd[cmd.index("-user_agent") + 1] == "TestAgent/9"
    assert "-referer" in cmd and cmd.index("-referer") < i_index
    # Remaining headers fold into a single -headers blob, also before -i.
    h_index = cmd.index("-headers")
    assert h_index < i_index
    blob = cmd[h_index + 1]
    assert "Cookie: a=b" in blob
    assert "X-Token: secret" in blob
    assert blob.endswith("\r\n")


def test_reconnect_flags_present():
    cmd = _cmd("provider_mkv")
    assert "-reconnect" in cmd
    assert "-rw_timeout" in cmd


def test_unknown_format_falls_back_to_provider_mkv():
    cmd = build_ffmpeg_command(FFMPEG, "http://h/x", "out.bin", "nonsense")
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"


def test_sanitize_filename():
    assert sanitize_filename('A/B:C*?"<>|D') .strip()  # illegal chars removed, non-empty
    assert "/" not in sanitize_filename("a/b")
    assert ":" not in sanitize_filename("a:b")
    assert sanitize_filename("") == "Recording"
    assert sanitize_filename("   ") == "Recording"
    assert len(sanitize_filename("x" * 500)) <= 120


def test_unique_output_path_uses_timestamp_and_collision_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder.time, "strftime", lambda _fmt: "2026-06-18 12-34-56")
    manager = recorder.RecordingManager()
    first = manager._unique_output_path(str(tmp_path), "A/B:C", "mkv")
    assert os.path.basename(first) == "A B C - 2026-06-18 12-34-56.mkv"
    open(first, "w", encoding="utf-8").close()
    second = manager._unique_output_path(str(tmp_path), "A/B:C", "mkv")
    assert os.path.basename(second) == "A B C - 2026-06-18 12-34-56 (2).mkv"


def test_unique_output_path_can_be_named_for_when_the_programme_aired(tmp_path):
    """A catch-up download carries the programme's start, not the download time."""
    import datetime
    # The exact name below is the air time; the clock would give today's date.
    manager = recorder.RecordingManager()
    aired = datetime.datetime(2026, 9, 10, 20, 30)
    first = manager._unique_output_path(str(tmp_path), "Ojciec Mateusz 35 - TVP 1", "mkv", when=aired)
    assert os.path.basename(first) == "Ojciec Mateusz 35 - TVP 1 - 2026-09-10 20-30.mkv"
    open(first, "w", encoding="utf-8").close()
    # Downloading the same episode again does not overwrite the first copy.
    again = manager._unique_output_path(str(tmp_path), "Ojciec Mateusz 35 - TVP 1", "mkv", when=aired)
    assert os.path.basename(again) == "Ojciec Mateusz 35 - TVP 1 - 2026-09-10 20-30 (2).mkv"


def test_normalize_recording_format_clamps():
    assert options.normalize_recording_format("audio_flac") == "audio_flac"
    assert options.normalize_recording_format("bogus") == options.DEFAULT_RECORDING_FORMAT
    assert options.normalize_recording_format(None) == options.DEFAULT_RECORDING_FORMAT
    assert options.normalize_recording_format(123) == options.DEFAULT_RECORDING_FORMAT


def test_get_recordings_dir_honors_explicit_dir(tmp_path):
    target = tmp_path / "my recs"
    result = options.get_recordings_dir({"recordings_dir": str(target)})
    assert os.path.normcase(result) == os.path.normcase(str(target))
    assert os.path.isdir(result)


def test_get_recordings_dir_default_uses_videos_subfolder():
    result = options.get_recordings_dir({})
    assert result.endswith("Accessible IPTV Recordings")


def test_recording_manager_records_http_stream_end_to_end(tmp_path):
    ffmpeg = _available_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg is not available")

    source = tmp_path / "source.ts"
    _make_source_ts(ffmpeg, source)

    with _looping_ts_server(source) as url:
        finished = threading.Event()
        result = {}

        def on_finish(rec, rc):
            result["recording"] = rec
            result["returncode"] = rc
            finished.set()

        manager = recorder.RecordingManager()
        try:
            rec = manager.start(
                url,
                "End To End Channel",
                "provider_mkv",
                {},
                str(tmp_path),
                key="e2e-channel",
                on_finish=on_finish,
                duration=2.0,
            )
            assert finished.wait(30)
            assert result["returncode"] == 0
            assert rec.out_path.endswith(".mkv")
            assert os.path.exists(rec.out_path)
            assert os.path.getsize(rec.out_path) > 1024
            assert not manager.list_active()

            subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-i", rec.out_path,
                "-f", "null", "-",
            ], check=True, timeout=30)
        finally:
            manager.stop_all(wait=True)


def test_provider_mp4_maps_only_what_mp4_can_hold():
    """MP4 cannot carry DVB teletext/subtitle or data streams.

    "-map 0" with "-c:s copy" made ffmpeg abort at header write on every channel
    that carries teletext ("Could not find tag for codec ... not currently
    supported in container") and leave a 0-byte recording behind.
    """
    cmd = _cmd("provider_mp4")
    assert [cmd[i + 1] for i, part in enumerate(cmd) if part == "-map"] == ["0:v?", "0:a?"]
    assert "-dn" in cmd and "-sn" in cmd
    assert "-c:s" not in cmd
    # MKV keeps everything the provider sent; that is what it is for.
    mkv = _cmd("provider_mkv")
    assert [mkv[i + 1] for i, part in enumerate(mkv) if part == "-map"] == ["0"]
    assert mkv[mkv.index("-c") + 1] == "copy"


def test_full_ffmpeg_output_is_requested_without_progress_spam():
    cmd = _cmd("provider_mp4")
    assert cmd[cmd.index("-loglevel") + 1] == "level+info"
    assert "-nostats" in cmd


def test_only_mp4_outputs_ask_for_faststart():
    for fmt in ("provider_mp4", "x264_mp4"):
        assert "+faststart" in _cmd(fmt)
        assert recorder.format_uses_faststart(fmt)
    for fmt in ("provider_mkv", "x264_mkv", "audio_aac_m4a", "audio_flac"):
        assert "+faststart" not in _cmd(fmt)
        assert not recorder.format_uses_faststart(fmt)


def test_finalize_timeout_scales_with_the_output_file(monkeypatch):
    """A +faststart MP4 rewrites itself on close, so the budget must follow its size.

    The fixed 8 second wait this replaces killed ffmpeg partway through that rewrite,
    which left the file as ftyp + one huge mdat and no moov atom: unplayable, with a
    whole recording stranded inside it.
    """
    monkeypatch.setattr(recorder.os.path, "getsize", lambda _p: 5 * 1024 ** 3)
    assert recorder.finalize_timeout_seconds("provider_mp4", "big.mp4") > 300
    # A container that does not rewrite itself only needs the flat grace period.
    assert (recorder.finalize_timeout_seconds("provider_mkv", "big.mkv")
            == recorder.FINALIZE_GRACE_SECONDS)
    # ...and the budget is capped, so a wedged ffmpeg cannot block the stop forever.
    monkeypatch.setattr(recorder.os.path, "getsize", lambda _p: 10 ** 15)
    assert (recorder.finalize_timeout_seconds("provider_mp4", "huge.mp4")
            == recorder.FINALIZE_TIMEOUT_CAP_SECONDS)


def test_finalize_timeout_survives_a_missing_output_file():
    assert recorder.finalize_timeout_seconds("provider_mp4", "nope.mp4") > 0


def test_recording_log_sits_beside_the_recording():
    out_dir = os.path.join("recs")
    path = recorder.recording_log_path(out_dir, os.path.join(out_dir, "Show - stamp.mp4"))
    assert path == os.path.join(out_dir, "logs", "Show - stamp.log")


def test_provider_connection_key_prevents_a_second_recording():
    """Manual and scheduled jobs have distinct keys but share one account slot."""
    manager = recorder.RecordingManager()
    active = recorder.Recording(1, "manual:tvp", "https://my.teleelevidenie.com/play/a",
                                "TVP", "provider_mkv", "out.mkv", _StubProcess(),
                                connection_key="teleelevidenie.com")
    manager._recordings[active.id] = active

    assert manager.has_active_connection("teleelevidenie.com")
    with pytest.raises(RuntimeError, match="only stream"):
        manager.start("https://my.teleelevidenie.com/play/b", "Scheduled", "provider_mkv",
                      {}, "unused", key="dvr:42", connection_key="teleelevidenie.com")


def test_read_log_problems_keeps_only_warnings_and_errors(tmp_path):
    log = tmp_path / "rec.log"
    log.write_text(
        "[info] Input #0, mpegts, from 'stream':\n"
        "[warning] Non-monotonic DTS in output stream\n"
        "[info] Press [q] to stop\n"
        "[error] Could not write header\n",
        encoding="utf-8",
    )
    assert recorder.read_log_problems(str(log)) == [
        "[warning] Non-monotonic DTS in output stream",
        "[error] Could not write header",
    ]
    assert recorder.read_log_problems(str(tmp_path / "absent.log")) == []
    assert recorder.read_log_problems("") == []


def test_count_log_problems_counts_every_severity_across_the_whole_log(tmp_path):
    """The finish report needs totals, not just the last dozen tail lines."""
    log = tmp_path / "rec.log"
    lines = ["# header", "[info] Input #0, mpegts"]
    lines += ["[warning] HTTP error 403 Forbidden"] * 40
    lines += ["[error] Error opening input file https://example.invalid/live.ts"]
    lines += ["[fatal] Error opening input files: Server returned 403 Forbidden"]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert recorder.count_log_problems(str(log)) == {
        "warnings": 40, "errors": 1, "fatals": 1}
    # A clean capture reports zeros rather than being indistinguishable
    # from a missing log.
    clean = tmp_path / "clean.log"
    clean.write_text("[info] all fine\n", encoding="utf-8")
    assert recorder.count_log_problems(str(clean)) == {
        "warnings": 0, "errors": 0, "fatals": 0}
    assert recorder.count_log_problems(str(tmp_path / "absent.log")) == {
        "warnings": 0, "errors": 0, "fatals": 0}
    assert recorder.count_log_problems("") == {
        "warnings": 0, "errors": 0, "fatals": 0}


def test_stopping_an_mp4_recording_leaves_a_playable_file(tmp_path):
    """The regression test for the bug: a stopped MP4 must have its moov atom.

    ffmpeg is asked to quit and must be given long enough to write the moov atom and
    run the +faststart rewrite. Killing it first produces a file every player rejects
    with "moov atom not found".
    """
    ffmpeg = _available_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg is not available")

    source = tmp_path / "source.ts"
    _make_source_ts(ffmpeg, source)

    with _looping_ts_server(source) as url:
        finished = threading.Event()
        manager = recorder.RecordingManager()
        try:
            rec = manager.start(
                url, "Stop Me Cleanly", "provider_mp4", {}, str(tmp_path),
                key="stop-me", on_finish=lambda *_args: finished.set(),
            )
            time.sleep(3)  # let real media reach the mdat
            manager.stop(rec.id, wait=True)
            assert finished.wait(120)
            assert not rec.finalize_timed_out

            boxes = _top_level_boxes(rec.out_path)
            assert "moov" in boxes, f"finalized without a moov atom: {boxes}"
            # +faststart puts the index in front of the media data.
            assert boxes.index("moov") < boxes.index("mdat"), boxes
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error",
                            "-i", rec.out_path, "-f", "null", "-"],
                           check=True, timeout=60)

            # The complete ffmpeg output is kept for diagnosis, URLs and
            # credentials included: masking them would make 403/timeout
            # failures impossible to diagnose from the log.
            assert os.path.isfile(rec.log_path)
            with open(rec.log_path, encoding="utf-8", errors="replace") as handle:
                log = handle.read()
            assert "Input #0" in log
            assert url in log
        finally:
            manager.stop_all(wait=True)


class _StubProcess:
    """A stand-in for ffmpeg that records how it was asked to stop."""

    def __init__(self, exits_after_waits=1):
        self.stdin = io.BytesIO()
        self.wait_timeouts = []
        self.terminated = False
        self.killed = False
        self.returncode = 0
        self._remaining = exits_after_waits

    def poll(self):
        return None if self._remaining > 0 else 0

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        self._remaining -= 1
        if self._remaining > 0:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return 0

    def terminate(self):
        self.terminated = True
        self._remaining = 0

    def kill(self):
        self.killed = True
        self._remaining = 0


def _stub_recording(proc, out_path, fmt="provider_mp4"):
    return recorder.Recording(1, "key", "http://host/live.ts", "Title", fmt,
                              str(out_path), proc)


def test_stop_waits_for_the_container_instead_of_killing_ffmpeg(tmp_path, monkeypatch):
    """The bug this fixes: a big +faststart MP4 was killed while still being written.

    ffmpeg had already rewritten the mdat header but had not yet written the moov
    atom, so the recording came out as ftyp + one enormous mdat and no index at all.
    A multi-gigabyte capture has to be given minutes to finish, not eight seconds.
    """
    monkeypatch.setattr(recorder.os.path, "getsize", lambda _p: 5 * 1024 ** 3)
    proc = _StubProcess()
    rec = _stub_recording(proc, tmp_path / "big.mp4")

    recorder.RecordingManager()._graceful_stop(rec, wait=True)

    assert proc.wait_timeouts and proc.wait_timeouts[0] > 300, proc.wait_timeouts
    assert not proc.terminated and not proc.killed
    assert not rec.finalize_timed_out


def test_shutdown_terminates_ffmpeg_that_will_not_stop(tmp_path):
    """Closing the app must not leave an FFmpeg stream process behind."""
    proc = _StubProcess(exits_after_waits=99)  # still working when we give up waiting
    rec = _stub_recording(proc, tmp_path / "big.mp4")

    recorder.RecordingManager()._graceful_stop(rec, wait=True, detach=True)

    assert proc.wait_timeouts == [recorder.DETACH_WAIT_SECONDS, recorder.TERMINATE_GRACE_SECONDS]
    assert proc.terminated
    assert rec.detached


def test_a_wedged_ffmpeg_is_still_escalated(tmp_path, monkeypatch):
    """Waiting generously must not mean waiting forever."""
    monkeypatch.setattr(recorder.os.path, "getsize", lambda _p: 0)
    proc = _StubProcess(exits_after_waits=2)  # ignores "q", dies on terminate
    rec = _stub_recording(proc, tmp_path / "stuck.mp4")

    recorder.RecordingManager()._graceful_stop(rec, wait=True)

    assert proc.terminated
    assert rec.finalize_timed_out


def test_recording_log_keeps_the_stream_url(tmp_path):
    """The per-recording log exists for troubleshooting; URLs stay in it."""
    url = "http://provider.example/live/user/pass/123.ts"
    log = tmp_path / "rec.log"
    header = recorder.RecordingManager()._open_log(str(log), ["ffmpeg", "-i", url, "out.mp4"], url)
    assert header is not None
    header.close()

    body = log.read_text(encoding="utf-8")
    assert url in body
    assert "<headers>" not in body


def test_settle_partial_output_renames_only_a_clean_download(tmp_path):
    """A finished download takes its real name; anything else is discarded."""
    manager = recorder.RecordingManager()
    final = tmp_path / "out.mkv"
    partial = tmp_path / "out.mkv.part"
    partial.write_bytes(b"123")
    rec = recorder.Recording(1, "key", "url", "Title", "provider_mkv",
                             str(final), None, partial_path=str(partial))

    manager._settle_partial_output(rec, 0)
    assert final.exists() and not partial.exists()

    # A user-cancelled run leaves nothing behind: ffmpeg cannot resume it.
    partial.write_bytes(b"123")
    rec.stopped_by_user = True
    manager._settle_partial_output(rec, 0)
    assert not partial.exists()

    # A timed-out finalize would be unplayable too.
    rec.stopped_by_user = False
    rec.finalize_timed_out = True
    partial.write_bytes(b"123")
    manager._settle_partial_output(rec, 0)
    assert not partial.exists()


def test_download_style_recording_hides_its_partial_file(tmp_path):
    """keep_partial=False: the .part file only becomes the real file on success."""
    ffmpeg = _available_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg is not available")
    source = tmp_path / "source.ts"
    _make_source_ts(ffmpeg, source)
    with _looping_ts_server(source) as url:
        finished = threading.Event()
        result = {}

        def on_finish(rec, rc):
            result["rec"] = rec
            result["rc"] = rc
            finished.set()

        manager = recorder.RecordingManager()
        try:
            rec = manager.start(
                url, "Download Style", "provider_mkv", {}, str(tmp_path),
                key="dl-style", on_finish=on_finish, duration=2.0,
                keep_partial=False,
            )
            assert rec.partial_path == rec.out_path + ".part"
            assert rec.written_path == rec.partial_path
            assert finished.wait(30)
            assert result["rc"] == 0
            assert os.path.exists(rec.out_path)
            assert not os.path.exists(rec.partial_path)
        finally:
            manager.stop_all(wait=True)


def test_canceled_download_leaves_no_partial_file(tmp_path):
    """ffmpeg cannot resume a partial file, so cancelling discards it entirely."""
    ffmpeg = _available_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg is not available")
    source = tmp_path / "source.ts"
    _make_source_ts(ffmpeg, source)
    with _looping_ts_server(source) as url:
        finished = threading.Event()
        result = {}

        def on_finish(rec, rc):
            result["rec"] = rec
            result["rc"] = rc
            finished.set()

        manager = recorder.RecordingManager()
        try:
            rec = manager.start(
                url, "Canceled Download", "provider_mkv", {}, str(tmp_path),
                key="dl-cancel", on_finish=on_finish, duration=30.0,
                keep_partial=False,
            )
            final, partial = rec.out_path, rec.partial_path
            time.sleep(1.5)  # let ffmpeg write something first
            manager.stop(rec.id, wait=True)
            assert finished.wait(30)
            assert result["rec"].stopped_by_user
            assert not os.path.exists(partial)
            assert not os.path.exists(final)
        finally:
            manager.stop_all(wait=True)


@pytest.mark.parametrize("url", [
    "rtmp://host/live/stream",
    "rtsp://host/stream",
    "udp://@239.0.0.1:1234",
])
def test_non_http_inputs_get_no_http_only_options(url):
    """ffmpeg refuses to open any non-HTTP input given these ("Option reconnect not found")."""
    cmd = build_ffmpeg_command(FFMPEG, url, "out.mkv", "provider_mkv",
                               {"User-Agent": "UA", "Referer": "http://r/", "X-Token": "t"})
    before_input = cmd[:cmd.index("-i")]
    for option in ("-reconnect", "-reconnect_streamed", "-reconnect_delay_max",
                   "-user_agent", "-referer", "-headers"):
        assert option not in before_input, option
    assert "-rw_timeout" in before_input
    assert cmd[cmd.index("-i") + 1] == url


def test_rtsp_input_uses_tcp_like_the_player():
    cmd = build_ffmpeg_command(FFMPEG, "rtsp://host/stream", "out.mkv", "provider_mkv")
    assert cmd[cmd.index("-rtsp_transport") + 1] == "tcp"
    assert cmd.index("-rtsp_transport") < cmd.index("-i")


def test_unique_output_path_skips_a_download_still_in_progress(tmp_path):
    """A download writes <name>.part until it completes; its name is taken."""
    import datetime
    manager = recorder.RecordingManager()
    aired = datetime.datetime(2026, 9, 10, 20, 30)
    first = manager._unique_output_path(str(tmp_path), "Show - TV", "mkv", when=aired)
    open(first + ".part", "w", encoding="utf-8").close()
    second = manager._unique_output_path(str(tmp_path), "Show - TV", "mkv", when=aired)
    assert second != first


def test_unique_output_path_skips_a_name_reserved_by_a_starting_recording(tmp_path):
    import datetime
    manager = recorder.RecordingManager()
    aired = datetime.datetime(2026, 9, 10, 20, 30)
    first = manager._unique_output_path(str(tmp_path), "Show - TV", "mkv", when=aired)
    manager._reserved_paths.add(first)
    assert manager._unique_output_path(str(tmp_path), "Show - TV", "mkv", when=aired) != first


def test_exit_stops_ffmpeg_that_is_still_finalizing_an_earlier_stop(tmp_path):
    """A stop already in progress used to make exit wait 5 s and leave ffmpeg running."""
    proc = _StubProcess(exits_after_waits=99)
    rec = _stub_recording(proc, tmp_path / "big.mp4")
    rec.stopping = True  # the user stopped it earlier; it is still writing the file

    recorder.RecordingManager()._graceful_stop(rec, wait=True, detach=True)

    assert proc.terminated
    assert rec.detached


def test_relay_failure_does_not_leave_ffmpeg_running(tmp_path, monkeypatch):
    """Nothing would drain ffmpeg's stdout copy, so the recording itself would stall."""
    import recording_relay

    proc = _StubProcess(exits_after_waits=99)
    proc.stdout = io.BytesIO()
    monkeypatch.setattr(recorder.subprocess, "Popen", lambda *a, **kw: proc)

    def broken_relay(_source):
        raise OSError("no port")

    monkeypatch.setattr(recording_relay, "RecordingRelay", broken_relay)
    manager = recorder.RecordingManager()

    with pytest.raises(OSError):
        manager.start("http://host/live.ts", "Title", "provider_mkv", None, str(tmp_path),
                      share_with_player=True)

    assert proc.killed
    assert manager.list_active() == []
    assert manager._reserved_paths == set()


def test_decoder_prefixed_problems_are_counted(tmp_path):
    """``[h264 @ addr] [error]`` lines are errors too; they used to count as none."""
    log = tmp_path / "rec.log"
    log.write_text(
        "[h264 @ 00000244d66ec580] [error] mmco: unref short failure\n"
        "[h264 @ 00000244d66ec580] [warning] Increasing reorder buffer to 2\n"
        "2026-09-19 20:20:08.100 [Parsed_volume_0 @ 0000] [Eval @ 0001] [error] bad\n"
        "[info] Output #0, mp3, to 'out.mp3':\n",
        encoding="utf-8",
    )
    assert recorder.count_log_problems(str(log)) == {
        "warnings": 1, "errors": 2, "fatals": 0}
    # The finish dialog shows the line without ffmpeg's date prefix.
    assert recorder.read_log_problems(str(log))[-1] == (
        "[Parsed_volume_0 @ 0000] [Eval @ 0001] [error] bad")


def test_parse_log_line_reads_time_level_and_component():
    parsed = recorder.parse_log_line(
        "2026-09-19 20:20:07.514 [h264 @ 00000244d66ec580] [error] mmco: unref short failure")
    assert parsed["level"] == "error"
    assert parsed["component"] == "h264"
    assert parsed["message"] == "mmco: unref short failure"
    assert parsed["when"].second == 7 and parsed["when"].microsecond == 514000
    plain = recorder.parse_log_line("[warning] Non-monotonic DTS")
    assert plain["when"] is None and plain["component"] == ""
    assert recorder.parse_log_line("# ffmpeg -i x") is None
    assert recorder.parse_log_line("[q] command received. Exiting.") is None


def test_summary_groups_problems_by_kind_and_places_them_in_time(tmp_path):
    log = tmp_path / "rec.log"
    log.write_text("\n".join([
        "# 2026-09-19 20:20:07",
        "2026-09-19 20:20:07.100 [h264 @ 0000] [error] mmco: unref short failure",
        "2026-09-19 20:20:07.110 [h264 @ 0000] [error] mmco: unref short failure",
        "2026-09-19 20:20:07.200 [info] Input #0, mpegts, from 'x':",
        "2026-09-19 20:20:08.000 [info] Output #0, mp3, to 'out.mp3':",
        # Same message, different numbers: one kind.
        "2026-09-19 20:32:11.000 [http @ 0002] [warning] Will reconnect at 100 in 0 second(s)",
        "2026-09-19 21:01:44.000 [http @ 0002] [warning] Will reconnect at 900 in 0 second(s)",
        "2026-09-19 21:05:00.000 [mp3 @ 0003] [error] Packet corrupt",
        "    Last message repeated 2 times",
        "2026-09-19 21:29:50.000 [info] size=  107025KiB time=01:09:54.38 bitrate= 209.0kbits/s",
    ]) + "\n", encoding="utf-8")

    summary = recorder.summarize_log(str(log))
    assert summary["output_opened"] and summary["timestamps"]
    opening, recording = summary["phases"]["opening"], summary["phases"]["recording"]
    assert [(k["message"], k["count"]) for k in opening] == [("mmco: unref short failure", 2)]
    reconnect, corrupt = recording
    assert reconnect["count"] == 2 and reconnect["offsets"] == [723.0, 2496.0]
    assert corrupt["count"] == 3
    assert recorder.count_log_problems(str(log)) == {"warnings": 2, "errors": 5, "fatals": 0}

    lines = recorder.format_recording_summary(
        out_path="out.mp3", started_at=1000.0, ended_at=1000.0 + 4194,
        planned_seconds=4200.0, written_seconds=recorder.parse_ffmpeg_progress(str(log)),
        file_size=109593600, ending="stopped on request (exit code 0).", summary=summary)
    text = "\n".join(lines)
    assert all(line.startswith("#") for line in lines)
    assert "# Planned length: 1:10:00" in text
    assert "# Recorded length: 1:09:54 (99.9% of planned, 0:00:06 short)" in text
    assert "# Problems while opening the stream: 0 warnings, 2 errors, 0 fatal errors" in text
    assert "# Problems during the recording: 2 warnings, 3 errors, 0 fatal errors" in text
    assert ("2 times: warning from http: Will reconnect at 100 in 0 second(s). "
            "At 0:12:03, 0:41:36.") in text
    assert "3 times: error from mp3: Packet corrupt. At 0:44:52." in text
    # The summary is not read back as more problems.
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    assert recorder.count_log_problems(str(log)) == {"warnings": 2, "errors": 5, "fatals": 0}


def test_summary_of_a_recording_that_never_started_writing(tmp_path):
    log = tmp_path / "rec.log"
    log.write_text("[http @ 0001] [error] HTTP error 403 Forbidden\n"
                   "[in#0 @ 0002] [fatal] Error opening input files: Server returned 403\n",
                   encoding="utf-8")
    text = "\n".join(recorder.format_recording_summary(
        out_path="out.mkv", started_at=0.0, ended_at=2.0, planned_seconds=None,
        written_seconds=None, file_size=None, ending="ffmpeg failed (exit code 1).",
        summary=recorder.summarize_log(str(log))))
    assert "# Planned length: none, recorded until stopped" in text
    assert "# Recorded length: unknown" in text
    assert "# File size: no file was written" in text
    assert "never started writing" in text
    assert "once: fatal from in#0: Error opening input files: Server returned 403" in text


def test_scheduled_stop_time_gives_the_planned_length():
    assert recorder._planned_seconds(90.0, {}, 1000.0) == 90.0
    assert recorder._planned_seconds(None, {"planned_stop_ts": 1600.0}, 1000.0) == 600.0
    assert recorder._planned_seconds(None, {"planned_stop_ts": 900.0}, 1000.0) is None
    assert recorder._planned_seconds(None, {}, 1000.0) is None


def test_log_timestamps_are_asked_for_only_when_ffmpeg_supports_them():
    cmd = build_ffmpeg_command(FFMPEG, "http://h/x", "out.mkv", "provider_mkv", None,
                               log_datetime=True)
    assert cmd[cmd.index("-loglevel") + 1] == "level+datetime+info"
    assert recorder.ffmpeg_supports_log_datetime("") is False
    missing = os.path.join(os.path.dirname(__file__), "no-such-ffmpeg.exe")
    assert recorder.ffmpeg_supports_log_datetime(missing) is False
    assert missing not in recorder._LOG_DATETIME_SUPPORT


def test_finished_recording_log_ends_with_a_summary(tmp_path):
    ffmpeg = _available_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg is not available")
    source = tmp_path / "source.ts"
    _make_source_ts(ffmpeg, source)

    with _looping_ts_server(source) as url:
        finished = threading.Event()
        manager = recorder.RecordingManager()
        try:
            rec = manager.start(url, "Summary", "provider_mkv", {}, str(tmp_path),
                                on_finish=lambda *_args: finished.set(), duration=3)
            assert finished.wait(60)
        finally:
            manager.stop_all(wait=True)

    with open(rec.log_path, encoding="utf-8", errors="replace") as handle:
        log = handle.read()
    assert "-stats_period" in rec.command
    assert "time=00:00:" in log
    tail = log[log.index("# ===== Recording summary ====="):]
    assert "# How it ended: finished normally." in tail
    assert "# Planned length: 0:00:03" in tail
    assert "# Recorded length: 0:00:0" in tail
    assert "# File size: " in tail and "no file" not in tail
    assert tail.rstrip().endswith("# ===== End of summary =====")
    if recorder.ffmpeg_supports_log_datetime(ffmpeg):
        assert "level+datetime+info" in log.splitlines()[1]


# --------------------------------------------------------------------------- #
# Where in a recording its problems happened
# --------------------------------------------------------------------------- #
def _datetime_log(tmp_path, lines):
    log = tmp_path / "rec.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(log)


def test_problem_times_places_each_kind_in_the_recording(tmp_path):
    log = _datetime_log(tmp_path, [
        "2026-09-19 20:00:00.000 [info] Input #0 from somewhere",
        "2026-09-19 20:00:00.000 [info] Output #0 to file out.mkv",
        "2026-09-19 20:00:10.000 [h264 @ 0001] [error] Cannot use 4:2:2",
        "2026-09-19 20:00:10.100 [info] Last message repeated 3 times",
        "2026-09-19 20:00:40.000 [info] time=00:00:35.00 speed=1.1x",
        "2026-09-19 20:01:10.000 [mpegts @ 0002] [warning] Will reconnect at 100",
    ])
    problems = recorder.recording_problem_times(log)
    assert [p["message"] for p in problems] == [
        "Cannot use 4:2:2", "Will reconnect at 100"]
    first = problems[0]
    assert first["count"] == 4
    assert first["clock_times"] == ["0:00:10", "0:00:10", "0:00:10", "0:00:10"]
    assert first["jump_times"] == ["0:00:10"]
    # The newest time= line before the problem is 0:00:35, but it is logged
    # after this problem happened, so nothing in the file can be named yet.
    assert first["media_times"] == []


def test_problem_times_names_media_positions_for_downloads(tmp_path):
    log = _datetime_log(tmp_path, [
        "2026-09-19 20:00:00.000 [info] Output #0 to file out.mp4",
        "2026-09-19 20:00:30.000 [info] time=00:00:25.00",
        "2026-09-19 20:00:50.000 [h264 @ 0001] [error] non-existing PPS",
        "2026-09-19 20:01:10.000 [info] time=00:00:45.00",
        "2026-09-19 20:01:20.000 [h264 @ 0001] [error] non-existing PPS",
    ])
    problems = recorder.recording_problem_times(log)
    assert len(problems) == 1
    assert problems[0]["clock_times"] == ["0:00:50", "0:01:20"]
    assert problems[0]["media_times"] == ["0:00:25", "0:00:45"]
    assert problems[0]["jump_times"] == ["0:00:25", "0:00:45"]


def test_problem_times_skips_opening_phase_and_unstamped_logs(tmp_path):
    opened = _datetime_log(tmp_path, [
        "2026-09-19 19:59:00.000 [mpegts @ 0002] [error] probe failed",
        "2026-09-19 20:00:00.000 [info] Output #0 to file out.mkv",
    ])
    assert recorder.recording_problem_times(opened) == []

    plain = tmp_path / "plain.log"
    plain.write_text("[h264 @ 0001] [error] no timestamps at all\n", encoding="utf-8")
    assert recorder.recording_problem_times(str(plain)) == []

    assert recorder.recording_problem_times("") == []
    assert recorder.recording_problem_times(str(tmp_path / "missing.log")) == []


def test_media_at_offset_reads_the_newest_stats_line_before_it(tmp_path):
    log = _datetime_log(tmp_path, [
        "2026-09-19 20:00:00.000 [info] Output #0 to file out.mp4",
        "2026-09-19 20:00:30.000 [info] time=00:00:25.00",
        "2026-09-19 20:01:00.000 [info] time=00:00:55.00",
    ])
    assert recorder.media_at_offset(log, 40.0) == "0:00:25"
    assert recorder.media_at_offset(log, 0.0) == ""
    assert recorder.media_at_offset(log, 3600.0) == "0:00:55"
    assert recorder.media_at_offset("", 10.0) == ""
    assert recorder.media_at_offset(str(tmp_path / "gone.log"), 10.0) == ""

    plain = tmp_path / "plain.log"
    plain.write_text("time=00:00:10.00\n", encoding="utf-8")
    assert recorder.media_at_offset(str(plain), 10.0) == ""


def test_provider_mka_copies_audio_only():
    label, ext, kind = RECORDING_FORMATS["provider_mka"]
    assert kind == "audio"
    assert ext == "mka"
    assert label  # human-readable
    cmd = _cmd("provider_mka")
    # Only audio is mapped in; video, subtitle and data tracks are excluded.
    assert "-map" in cmd and cmd[cmd.index("-map") + 1] == "0:a?"
    assert "-vn" in cmd and "-sn" in cmd and "-dn" in cmd
    # Stream copy: the source audio is preserved verbatim, never transcoded.
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "copy"
    assert "-c:v" not in cmd
    for encoder in ("libx264", "libmp3lame", "libopus", "flac", "pcm_s16le", "aac"):
        assert encoder not in cmd
    assert cmd[-1].endswith(".mka")
    assert recorder.format_extension("provider_mka") == "mka"


def test_probe_media_type_classifies_reports(monkeypatch):
    audio_report = (
        "Input #0, mp3, from 'http://example.com/r':\n"
        "  Stream #0:0: Audio: mp3, 44100 Hz, stereo, fltp, 128 kb/s\n"
    )
    video_report = (
        "Input #0, mpegts, from 'http://example.com/tv':\n"
        "  Stream #0:0: Video: h264, yuv420p, 1280x720, 25 fps\n"
        "  Stream #0:1: Audio: aac, 48000 Hz, stereo\n"
    )
    radio_with_art = audio_report + (
        "  Stream #0:1: Video: mjpeg, 300x300 (attached pic)\n"
    )
    seen = {}

    def fake_report(url, headers=None, timeout=20.0, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return {"audio": audio_report, "video": video_report,
                "art": radio_with_art}[url]

    monkeypatch.setattr(recorder, "probe_stream_report", fake_report)
    assert recorder.probe_media_type("audio") == "audio"
    assert recorder.probe_media_type("video") == "video"
    # Attached cover art does not make a radio stream look like video.
    assert recorder.probe_media_type("art") == "audio"
    assert seen["url"] == "art"


def test_probe_media_type_unknown_when_stream_silent(monkeypatch):
    monkeypatch.setattr(recorder, "probe_stream_report", lambda *a, **k: "")
    assert recorder.probe_media_type("http://example.com/dead") == "unknown"


def test_probe_audio_streams_shares_the_stream_report(monkeypatch):
    report = (
        "Input #0, mpegts, from 'http://example.com/tv':\n"
        "  Stream #0:0: Video: h264, 1280x720\n"
        "  Stream #0:1: Audio: mp3, 44100 Hz, stereo\n"
        "  Stream #0:2: Audio: aac, 48000 Hz, stereo\n"
    )
    calls = []
    monkeypatch.setattr(
        recorder, "probe_stream_report",
        lambda url, headers=None, timeout=20.0: calls.append(url) or report)
    tracks = recorder.probe_audio_streams("http://example.com/tv")
    assert calls == ["http://example.com/tv"]
    # Both audio tracks are listed (in 0:a:N order); the video track is not.
    assert len(tracks) == 2
    assert all(set(t) >= {"language", "title", "dispositions"} for t in tracks)


def test_probe_stream_report_on_popen_hook_allows_preemption(monkeypatch):
    """The on_popen hook receives the live probe so a session can kill it."""
    received = []

    class FakeProc:
        def __init__(self, *args, **kwargs):
            self.killed = False
            self.args = args

        def communicate(self, timeout=None):
            return b"", b"Stream #0:0: Audio: mp3\n"

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return None

    monkeypatch.setattr(recorder.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(recorder, "get_ffmpeg_path", lambda: "ffmpeg")
    report = recorder.probe_stream_report(
        "http://example.com/r", on_popen=received.append)
    assert len(received) == 1
    assert isinstance(received[0], FakeProc)
    assert "Audio: mp3" in report
    # Preempting the probe: kill it, and the report path still behaves.
    received[0].kill()
    assert received[0].killed


def test_probe_stream_report_timeout_kills_probe(monkeypatch):
    import subprocess as stdlib_subprocess

    class SlowProc:
        def __init__(self, *args, **kwargs):
            self.killed = False
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise stdlib_subprocess.TimeoutExpired("ffmpeg", timeout)
            return b"", b""

        def kill(self):
            self.killed = True

    proc = SlowProc()
    monkeypatch.setattr(recorder.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(recorder, "get_ffmpeg_path", lambda: "ffmpeg")
    assert recorder.probe_stream_report("http://example.com/hung") == ""
    assert proc.killed
