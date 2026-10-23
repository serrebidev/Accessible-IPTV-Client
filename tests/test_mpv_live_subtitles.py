"""A local, generated live HTTP source uses the real MPV helper and intake.

No provider credentials, external media, sound device or additional upstream
playback is used. This is not the native Windows IPC or screen-reader matrix.
"""
import json
import os
import shutil
import subprocess
import threading
import queue
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mpv_subtitle_adapter import MpvSubtitleAdapter
from mpv_subtitle_script import SCRIPT
from subtitle_session import SubtitleSessionController
from subtitle_speech import SubtitleSpeechManager


@pytest.mark.skipif(not (shutil.which("mpv") and shutil.which("ffmpeg")), reason="real MPV and FFmpeg required")
@pytest.mark.parametrize("subtitle_format", ["srt", "ass"])
def test_live_http_embedded_text_uses_one_stream_and_collects_before_speech_is_enabled(tmp_path, subtitle_format):
    sub = tmp_path / ("live." + subtitle_format)
    if subtitle_format == "ass":
        text = ("[Script Info]\nScriptType: v4.00+\n[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:00.50,0:00:01.20,Default,,0,0,0,,{\\i1}Live{\\i0} words\n"
                "Dialogue: 0,0:00:02.00,0:00:02.70,Default,,0,0,0,,Live words\n"
                "Dialogue: 0,0:00:03.50,0:00:04.20,Default,,0,0,0,,Last live cue\n")
    else:
        text = ("1\n00:00:00,500 --> 00:00:01,200\nLive words\n\n"
                "2\n00:00:02,000 --> 00:00:02,700\nLive words\n\n"
                "3\n00:00:03,500 --> 00:00:04,200\nLast live cue\n")
    sub.write_text(text, encoding="utf-8")
    helper, capture = tmp_path / "helper.lua", tmp_path / "capture.lua"
    helper.write_text(SCRIPT, encoding="utf-8")
    capture.write_text("local mp=require 'mp'; mp.register_script_message('iptvclient-subtitle-snapshot',"
                       "function(payload) print('IPTV_LIVE_SNAPSHOT '..payload) end)", encoding="utf-8")
    requests, producers = [], []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args): pass
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/x-matroska")
            self.end_headers()
        def do_GET(self):
            if self.path != "/generated-live":
                return self.send_error(404)
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "video/x-matroska")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            command = [shutil.which("ffmpeg"), "-nostdin", "-loglevel", "error", "-re",
                       "-f", "lavfi", "-i", "color=s=160x90:r=25:d=5", "-i", str(sub),
                       "-map", "0:v:0", "-map", "1:s:0", "-c:v", "mpeg4", "-c:s", subtitle_format,
                       "-f", "matroska", "-cluster_time_limit", "200", "-live", "1", "pipe:1"]
            producer = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            producers.append(producer)
            try:
                while True:
                    chunk = os.read(producer.stdout.fileno(), 16384)
                    if not chunk:
                        break
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                if producer.poll() is None:
                    producer.terminate()
                producer.wait(timeout=5)
                producer.stdout.close()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except OSError as exc:
        pytest.skip(f"loopback listener unavailable: {exc}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/generated-live"
    spoken, observations, history = [], [], []
    manager = SubtitleSpeechManager(spoken.append)
    controller = SubtitleSessionController(manager)
    sink = controller.bind(controller.activate_session("mpv-live-test"))
    adapter = MpvSubtitleAdapter(sink)
    process = None
    try:
        command = [shutil.which("mpv"), "--no-config", "--vo=null", "--ao=null", "--no-audio",
                   "--sub-auto=no", "--sid=1", "--cache=no", "--terminal=yes",
                   "--script=" + str(helper), "--script=" + str(capture), url]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = queue.Queue()
        done = threading.Event()
        def read_lines():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                done.set()
        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()
        deadline = time.monotonic() + 25
        diagnostics = []
        while not (done.is_set() and lines.empty()):
            if time.monotonic() > deadline:
                pytest.fail("the local live MPV test exceeded its bounded deadline")
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            diagnostics.append(line)
            if "IPTV_LIVE_SNAPSHOT " not in line:
                continue
            payload = line.split("IPTV_LIVE_SNAPSHOT ", 1)[1]
            snapshot = json.loads(payload)
            adapter._dispatch(json.dumps({"event": "client-message", "args": [
                "iptvclient-subtitle-snapshot", payload]}).encode())
            if snapshot["text"]:
                observations.append((snapshot["text"], snapshot.get("start"), snapshot.get("finish")))
                history = [(cue.text, cue.start_ms, cue.end_ms) for cue in manager.get_recent()]
                if not manager.auto_speech:
                    assert spoken == []
                    manager.set_auto_speech(True)
        assert process.wait(timeout=5) == 0, "".join(diagnostics)
        reader.join(timeout=5)
        process.stdout.close()
        assert observations, "".join(diagnostics)
        assert requests == ["/generated-live"]
        actual = sorted(set(observations), key=lambda cue: cue[1])
        expected = [("Live words", 0.5, 1.2), ("Live words", 2.0, 2.7), ("Last live cue", 3.5, 4.2)]
        assert len(actual) == len(expected)
        for observed, wanted in zip(actual, expected):
            assert observed[0] == wanted[0]
            # Matroska subtitle duration rounding can move the end by one ms.
            assert observed[1:] == pytest.approx(wanted[1:], abs=0.0011)
        assert spoken == ["Live words", "Last live cue"]
        assert [cue[:2] for cue in history] == [
            ("Live words", 500), ("Live words", 2000), ("Last live cue", 3500)]
        assert [cue[2] for cue in history] == pytest.approx([1200, 2700, 4200], abs=1)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process is not None and process.stdout is not None:
            process.stdout.close()
        adapter.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        for producer in producers:
            if producer.poll() is None:
                producer.kill()
                producer.wait(timeout=5)
