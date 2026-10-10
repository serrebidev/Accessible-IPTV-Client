"""MPV subtitle adapter: protocol handling without a player, plus an optional
live test against a real mpv (skipped when mpv is not installed)."""

import json
import shutil
import time

import pytest

from mpv_subtitle_adapter import MpvSubtitleAdapter, _session_endpoint
from subtitle_speech import SubtitleSpeechManager


def _adapter():
    spoken = []
    states = []
    mgr = SubtitleSpeechManager(spoken.append)
    mgr.set_auto_speech(True)
    ad = MpvSubtitleAdapter(mgr, states.append)
    return ad, mgr, spoken, states


def _event(pid, data, name="sub-text"):
    return json.dumps(
        {"event": "property-change", "id": pid, "name": name, "data": data}
    ).encode()


def test_sub_text_event_becomes_cue():
    ad, mgr, spoken, states = _adapter()
    ad._dispatch(_event(2, "Hello there"))
    assert spoken == ["Hello there"]
    assert states == ["first_cue"]
    recent = mgr.get_recent(10)
    assert recent[0].source == "mpv-ipc"


def test_empty_and_null_sub_text_are_not_cues():
    ad, mgr, spoken, _states = _adapter()
    ad._dispatch(_event(2, ""))
    ad._dispatch(_event(2, None))
    assert spoken == []
    assert mgr.get_recent(10) == []


def test_timing_arrives_on_separate_property_changes():
    ad, _mgr, spoken, _states = _adapter()
    ad._dispatch(_event(2, "Timed cue"))
    ad._dispatch(_event(3, 1.5, name="sub-start"))
    ad._dispatch(_event(4, 3.25, name="sub-end"))
    assert spoken == ["Timed cue"]  # spoken once, on the text change
    recent = _mgr.get_recent(10)
    assert len(recent) == 1
    assert recent[0].start_ms == 1500
    assert recent[0].end_ms == 3250


def test_bad_timing_values_do_not_break_cues():
    ad, _mgr, spoken, _states = _adapter()
    ad._dispatch(_event(3, "not-a-number", name="sub-start"))
    ad._dispatch(_event(2, "Still spoken"))
    assert spoken == ["Still spoken"]
    assert _mgr.get_recent(10)[0].start_ms is None


def test_track_change_clears_stale_cues():
    ad, mgr, spoken, _states = _adapter()
    ad._dispatch(_event(2, "First track cue"))
    ad._dispatch(_event(5, 2, name="sid"))
    assert mgr.read_current() is False  # cleared on track switch
    ad._dispatch(_event(2, "Second track cue"))
    assert spoken[-1] == "Second track cue"
    assert mgr.get_recent(10)[-1].track == "2"


def test_end_of_file_clears_cues():
    ad, mgr, spoken, _states = _adapter()
    ad._dispatch(_event(2, "A cue"))
    ad._dispatch(json.dumps({"event": "end-file", "reason": "stop"}).encode())
    assert mgr.read_current() is False
    assert spoken == ["A cue"]


def test_malformed_messages_are_ignored():
    ad, _mgr, spoken, _states = _adapter()
    ad._dispatch(b"not json at all\n")
    ad._dispatch(json.dumps(["a", "list"]).encode())
    ad._dispatch(json.dumps({"request_id": 999, "data": "x"}).encode())
    assert spoken == []


def test_request_response_matching():
    ad, _mgr, _spoken, _states = _adapter()
    holder = {}

    def fake_send(message):
        rid = message["request_id"]
        holder["rid"] = rid
        return True

    ad._send = fake_send

    import threading

    def answer():
        time.sleep(0.1)
        ad._dispatch(json.dumps(
            {"request_id": holder["rid"], "error": "success",
             "data": "mpv 0.37.0"}).encode())

    threading.Thread(target=answer, daemon=True).start()

    # _request pumps inline until the reader loop exists; emulate the loop.
    ad._transport = type("T", (), {"read_line": lambda self, deadline=None: None})()
    resp = ad._request(["get_property", "mpv-version"], timeout=2.0)
    assert resp is not None and resp["data"] == "mpv 0.37.0"


def test_session_endpoints_are_unique_per_session():
    assert _session_endpoint() != _session_endpoint()


def test_disconnect_reports_unavailable_and_clears():
    ad, mgr, spoken, states = _adapter()
    ad._dispatch(_event(2, "A cue"))
    ad.available = True
    ad._on_disconnect()
    assert states[-1] == "unavailable"
    assert mgr.read_current() is False


mpv_exe = shutil.which("mpv")
ffmpeg_exe = shutil.which("ffmpeg")


@pytest.mark.skipif(mpv_exe is None or ffmpeg_exe is None,
                    reason="mpv and ffmpeg not installed")
def test_live_mpv_delivers_cues(tmp_path):
    """End to end against a real mpv: our own instance, per-session IPC."""
    import subprocess

    clip = tmp_path / "t.mp4"
    subprocess.run(
        [ffmpeg_exe, "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=duration=8:size=320x240:rate=10",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True, timeout=60)
    srt = tmp_path / "t.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nLive cue one\n\n"
        "2\n00:00:03,500 --> 00:00:05,000\nLive cue two\n",
        encoding="utf-8")
    spoken = []
    states = []
    mgr = SubtitleSpeechManager(spoken.append)
    mgr.set_auto_speech(True)
    ad = MpvSubtitleAdapter.launch(
        mpv_exe, str(clip), mgr, states.append,
        extra_args=["--vo=null", "--ao=null",
                    f"--sub-file={srt}", "--sid=1"])
    assert ad is not None
    try:
        deadline = time.time() + 25
        while time.time() < deadline and len(spoken) < 2:
            time.sleep(0.2)
        assert "Live cue one" in spoken
        assert "Live cue two" in spoken
        assert "first_cue" in states
        recent = mgr.get_recent(10)
        assert recent[0].start_ms == 1000
    finally:
        ad.close()
    assert ad.available is False


def test_generation_bump_drops_pending_property_state():
    ad, mgr, spoken, _states = _adapter()
    ad._dispatch(_event(2, "Old cue"))
    assert spoken == ["Old cue"]
    # Track switch: new generation, stale property state discarded.
    ad._dispatch(_event(5, 2, name="sid"))
    # A late timing event from the old stream must not touch the new one.
    ad._dispatch(_event(3, 9.0, name="sub-start"))
    assert mgr.get_recent(10) == []
    assert spoken == ["Old cue"]
    # The new generation's cues carry the new generation identity.
    ad._dispatch(_event(2, "New cue"))
    recent = mgr.get_recent(10)
    assert len(recent) == 1
    assert recent[0].text == "New cue"
    assert recent[0].generation == 1
    assert recent[0].track == "2"
    assert spoken == ["Old cue", "New cue"]


def test_text_event_after_end_of_file_starts_new_generation():
    # After end-of-file the transport is a new stream: a sub-text event is a
    # newly displayed cue, not a resurrection of the old one. mpv's IPC is a
    # single ordered connection, so old-stream text cannot arrive here; the
    # generation key on the recorded cue keeps the boundary explicit.
    ad, mgr, spoken, _states = _adapter()
    ad._dispatch(_event(2, "First file cue"))
    ad._dispatch(json.dumps({"event": "end-file", "reason": "stop"}).encode())
    assert mgr.get_recent(10) == []
    ad._dispatch(_event(2, "First file cue"))
    assert spoken == ["First file cue", "First file cue"]
    recent = mgr.get_recent(10)
    assert len(recent) == 1
    assert recent[0].generation == 1
