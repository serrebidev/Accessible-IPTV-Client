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

            # The complete ffmpeg output is kept for diagnosis, with the stream URL
            # masked out of the recorded command line: it carries provider credentials.
            assert os.path.isfile(rec.log_path)
            log = open(rec.log_path, encoding="utf-8", errors="replace").read()
            assert "Input #0" in log
            assert "<stream url>" in log
            assert url not in log
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


def test_shutdown_leaves_ffmpeg_to_finish_on_its_own(tmp_path):
    """Closing the app must not truncate a recording that is still finalizing."""
    proc = _StubProcess(exits_after_waits=99)  # still working when we give up waiting
    rec = _stub_recording(proc, tmp_path / "big.mp4")

    recorder.RecordingManager()._graceful_stop(rec, wait=True, detach=True)

    assert proc.wait_timeouts == [recorder.DETACH_WAIT_SECONDS]
    assert not proc.terminated and not proc.killed
    assert rec.detached


def test_a_wedged_ffmpeg_is_still_escalated(tmp_path, monkeypatch):
    """Waiting generously must not mean waiting forever."""
    monkeypatch.setattr(recorder.os.path, "getsize", lambda _p: 0)
    proc = _StubProcess(exits_after_waits=2)  # ignores "q", dies on terminate
    rec = _stub_recording(proc, tmp_path / "stuck.mp4")

    recorder.RecordingManager()._graceful_stop(rec, wait=True)

    assert proc.terminated
    assert rec.finalize_timed_out


def test_redact_log_removes_the_stream_url(tmp_path):
    """Recording logs are made to be sent to somebody; provider credentials are not."""
    url = "http://provider.example/live/user/pass/123.ts"
    log = tmp_path / "rec.log"
    log.write_text(f"[info] Input #0, mpegts, from '{url}':\n", encoding="utf-8")

    recorder.redact_log(str(log), url)

    body = log.read_text(encoding="utf-8")
    assert url not in body
    assert recorder.LOG_URL_PLACEHOLDER in body
