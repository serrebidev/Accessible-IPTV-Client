import os
import sys
import http.server
import socketserver
import subprocess
import threading

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
    # MP4 from MPEG-TS needs the ADTS->ASC bitstream filter and faststart.
    assert "aac_adtstoasc" in mp4
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
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=duration=1:size=96x54:rate=8",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-f", "mpegts", str(source),
    ], check=True, timeout=30)

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
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        url = "http://127.0.0.1:{port}/source.ts".format(port=httpd.server_address[1])

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
            httpd.shutdown()