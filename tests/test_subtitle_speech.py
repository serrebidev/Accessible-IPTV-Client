"""SubtitleSpeechManager: cue queue, speech routing, capability tracking."""

import pytest

from subtitle_speech import (
    ALL_CAPABILITIES,
    AVAILABLE,
    UNAVAILABLE,
    UNVERIFIED,
    SubtitleSpeechManager,
)


def _manager():
    spoken = []
    mgr = SubtitleSpeechManager(spoken.append)
    return mgr, spoken


def test_cue_recorded_for_review_even_when_auto_speech_off():
    mgr, spoken = _manager()
    mgr.on_cue("Hello", start_ms=1000, end_ms=2000, source="mpv-ipc")
    assert spoken == []
    recent = mgr.get_recent(10)
    assert [c.text for c in recent] == ["Hello"]
    assert recent[0].start_ms == 1000
    assert recent[0].end_ms == 2000


def test_auto_speech_speaks_new_cues():
    mgr, spoken = _manager()
    mgr.set_auto_speech(True)
    assert mgr.auto_speech
    mgr.on_cue("One")
    mgr.on_cue("Two")
    assert spoken == ["One", "Two"]


def test_empty_and_blank_cues_ignored():
    mgr, spoken = _manager()
    mgr.set_auto_speech(True)
    mgr.on_cue("")
    mgr.on_cue("   ")
    mgr.on_cue(None)
    assert spoken == []
    assert mgr.get_recent(10) == []


def test_duplicate_text_fills_timing_without_respeaking():
    mgr, spoken = _manager()
    mgr.set_auto_speech(True)
    mgr.on_cue("Hello")
    assert spoken == ["Hello"]
    # Same text arriving again without timing (e.g. a repeated property
    # change) updates the recorded cue instead of speaking or duplicating.
    mgr.on_cue("Hello", start_ms=1000, end_ms=3000, track="2")
    assert spoken == ["Hello"]
    recent = mgr.get_recent(10)
    assert len(recent) == 1
    assert recent[0].start_ms == 1000
    assert recent[0].end_ms == 3000
    assert recent[0].track == "2"


def test_update_cue_timing_fills_in_place_without_speaking():
    mgr, spoken = _manager()
    mgr.set_auto_speech(True)
    mgr.on_cue("Hello")
    assert spoken == ["Hello"]
    # Timing-only arrival (MPV's sub-start/sub-end after sub-text).
    mgr.update_cue_timing(1000, 3000, generation=0)
    assert spoken == ["Hello"]  # not re-spoken
    assert len(mgr.get_recent(10)) == 1  # not duplicated
    assert mgr.get_recent(10)[0].start_ms == 1000
    assert mgr.get_recent(10)[0].end_ms == 3000
    # Timing for a stale generation is ignored.
    mgr.update_cue_timing(5000, 7000, generation=99)
    assert mgr.get_recent(10)[0].start_ms == 1000


def test_identical_consecutive_cues_are_both_spoken():
    # Two genuine consecutive cues may both say "Yes."; the second must
    # still be recorded and spoken, not swallowed by text-only dedup.
    mgr, spoken = _manager()
    mgr.set_auto_speech(True)
    mgr.on_cue("Yes.", start_ms=1000, end_ms=2000)
    mgr.on_cue("Yes.", start_ms=5000, end_ms=6000)
    assert spoken == ["Yes.", "Yes."]
    assert len(mgr.get_recent(10)) == 2


def test_generation_keys_cues():
    mgr, spoken = _manager()
    mgr.set_auto_speech(True)
    mgr.on_cue("Hello", start_ms=1000, generation=0)
    assert spoken == ["Hello"]
    # Same words in a new media generation are a new cue, spoken again.
    mgr.on_cue("Hello", start_ms=1000, generation=1)
    assert spoken == ["Hello", "Hello"]
    recent = mgr.get_recent(10)
    assert [c.generation for c in recent] == [0, 1]


def test_read_current_and_previous():
    mgr, spoken = _manager()
    assert mgr.read_current() is False
    assert mgr.read_previous() is False
    mgr.on_cue("One")
    mgr.on_cue("Two")
    assert mgr.read_current() is True
    assert mgr.read_previous() is True
    assert spoken == ["Two", "One"]


def test_clear_and_source_switch_drop_stale_cues():
    mgr, spoken = _manager()
    mgr.on_cue("One")
    mgr.on_cue("Two")
    mgr.clear()
    assert mgr.read_current() is False
    assert mgr.read_previous() is False
    # Review must never expose cues from a previous channel, programme,
    # media generation or subtitle track.
    assert mgr.get_recent(10) == []
    mgr.on_cue("Three")
    mgr.set_source("other")
    assert mgr.read_current() is False
    assert mgr.get_recent(10) == []


def test_recent_history_bounded():
    mgr, _spoken = _manager()
    for i in range(70):
        mgr.on_cue(f"cue {i}")
    recent = mgr.get_recent(100)
    assert len(recent) == 50
    assert recent[0].text == "cue 20"
    assert [c.text for c in mgr.get_recent(3)] == ["cue 67", "cue 68", "cue 69"]


def test_speak_failure_never_raises_and_reports():
    failures = []

    def boom(_text):
        raise RuntimeError("nope")

    mgr = SubtitleSpeechManager(boom, on_speak_error=lambda t, e: failures.append((t, e)))
    mgr.set_auto_speech(True)
    mgr.on_cue("Hello")  # must not raise
    assert len(failures) == 1
    assert failures[0][0] == "Hello"
    assert isinstance(failures[0][1], RuntimeError)
    # The cue is still recorded for review even though speech failed.
    assert [c.text for c in mgr.get_recent(10)] == ["Hello"]
    # read_current retries speech and reports the failure again, no raise.
    assert mgr.read_current() is True
    assert len(failures) == 2


def test_speech_marshalled_through_ui_thread():
    marshalled = []
    spoken = []

    def fake_ui_thread(fn, *args):
        marshalled.append((fn, args))

    mgr = SubtitleSpeechManager(spoken.append, ui_thread=fake_ui_thread)
    mgr.set_auto_speech(True)
    mgr.on_cue("Hello")
    # Speech did not run inline; it was handed to the UI thread callable.
    assert spoken == []
    assert len(marshalled) == 1
    fn, args = marshalled[0]
    fn(*args)  # UI thread runs it
    assert spoken == ["Hello"]


def test_capability_baseline_is_honest():
    mgr, _spoken = _manager()
    assert mgr.get_capability("built-in", "timed_cues") == AVAILABLE
    assert mgr.get_capability("VLC", "timed_cues") == UNAVAILABLE
    assert mgr.get_capability("Kodi", "timed_cues") == UNAVAILABLE
    assert mgr.get_capability("MPV", "timed_cues") == UNVERIFIED
    assert mgr.get_capability("SomethingElse", "timed_cues") == UNVERIFIED


def test_capability_set_and_get():
    mgr, _spoken = _manager()
    mgr.set_capability("MPV", "timed_cues", AVAILABLE)
    assert mgr.get_capability("MPV", "timed_cues") == AVAILABLE
    caps = mgr.get_capabilities("MPV")
    assert set(caps) == set(ALL_CAPABILITIES)
    assert caps["timed_cues"] == AVAILABLE


def test_capability_invalid_values_rejected():
    mgr, _spoken = _manager()
    with pytest.raises(ValueError):
        mgr.set_capability("MPV", "nope", AVAILABLE)
    with pytest.raises(ValueError):
        mgr.set_capability("MPV", "timed_cues", "maybe")


def test_describe_capability():
    mgr, _spoken = _manager()
    assert mgr.describe_capability("built-in", "timed_cues") == "available"
    assert "not supported" in mgr.describe_capability("VLC", "timed_cues")
    assert "not verified" in mgr.describe_capability("MPV", "timed_cues")


def test_describe_capability_uses_translation():
    mgr, _spoken = _manager()
    seen = []

    def fake_gettext(s):
        seen.append(s)
        return f"XX:{s}"

    assert mgr.describe_capability("built-in", "timed_cues", fake_gettext) == "XX:available"
    assert mgr.describe_capability("VLC", "timed_cues", fake_gettext).startswith("XX:")
    assert mgr.describe_capability("MPV", "timed_cues", fake_gettext).startswith("XX:")
    assert seen == ["available", "not supported by this player", "not verified yet"]
