"""Reading the current subtitle again and reviewing the ones already shown."""
import types

import internal_player
from internal_player import InternalPlayerFrame
from subtitle_cues import Cue

CUES = [Cue(1000, 2000, "One"), Cue(3000, 4000, "Two"), Cue(5000, 6000, "Three")]


def _frame(cues=CUES, time_ms=0):
    label = types.SimpleNamespace(value="")
    label.SetLabel = lambda value: setattr(label, "value", value)
    frame = types.SimpleNamespace(
        _subtitle_cues=list(cues), _cue_index=None, _last_cue_index=None, _review_cue_index=None,
        _speak_subtitles=False, _is_paused=False, subtitle_label=label, spoken=[],
        player=types.SimpleNamespace(video_get_spu=lambda: 1, video_get_spu_delay=lambda: 0,
                                     get_time=lambda: frame.time_ms),
        time_ms=time_ms)
    frame._speak = lambda ctrl: frame.spoken.append(ctrl.value)
    return frame


def _play_to(frame, ms):
    frame.time_ms = ms
    InternalPlayerFrame._on_cue_timer(frame)


def _say(frame, step):
    return InternalPlayerFrame._subtitle_review_text(frame, step)


def test_nothing_to_review_without_a_loaded_file():
    frame = _frame(cues=[])
    assert _say(frame, 0) == "No subtitle text to read. Load an SRT or WebVTT file."
    assert _say(frame, -1) == "No subtitle text to read. Load an SRT or WebVTT file."


def test_nothing_to_review_before_the_first_cue_appears():
    frame = _frame()
    _play_to(frame, 500)
    assert _say(frame, 0) == "No subtitle has been shown yet."
    assert _say(frame, -1) == "No subtitle has been shown yet."


def test_read_current_cue_or_the_last_one_shown():
    frame = _frame()
    _play_to(frame, 3500)
    assert _say(frame, 0) == "Two"
    _play_to(frame, 4500)  # gap between cues
    assert frame.subtitle_label.value == ""
    assert _say(frame, 0) == "Last subtitle: Two"


def test_review_moves_back_and_never_reads_ahead_of_playback():
    frame = _frame()
    _play_to(frame, 1500)
    _play_to(frame, 3500)
    assert _say(frame, 1) == "No later subtitle."
    assert _say(frame, -1) == "One"
    assert _say(frame, -1) == "No earlier subtitle."
    assert _say(frame, 1) == "Two"
    assert _say(frame, 1) == "No later subtitle."


def test_a_new_cue_resets_the_review_position():
    frame = _frame()
    _play_to(frame, 3500)
    assert _say(frame, -1) == "One"
    _play_to(frame, 5500)
    assert _say(frame, -1) == "Two"


def test_review_follows_a_seek_back():
    frame = _frame()
    _play_to(frame, 5500)
    _play_to(frame, 1500)  # catch-up seek back to the first cue
    assert _say(frame, 1) == "No later subtitle."
    assert _say(frame, 0) == "One"


def test_review_does_not_change_the_on_screen_cue_or_speak_it_twice():
    frame = _frame()
    frame._speak_subtitles = True
    _play_to(frame, 1500)
    _play_to(frame, 3500)
    assert frame.spoken == ["One", "Two"]
    _say(frame, -1)
    _play_to(frame, 3600)  # same cue still showing
    assert frame.subtitle_label.value == "Two"
    assert frame.spoken == ["One", "Two"]


def test_loading_new_cues_forgets_the_review_position(monkeypatch):
    frame = _frame()
    _play_to(frame, 3500)
    frame._subtitle_generation = 0
    frame._cue_timer = types.SimpleNamespace(Start=lambda *_: None, Stop=lambda: None)
    InternalPlayerFrame._set_subtitle_cues(frame, list(CUES))
    assert _say(frame, 0) == "No subtitle has been shown yet."


def test_review_commands_speak_through_the_live_announcer(monkeypatch):
    said = []
    monkeypatch.setattr(internal_player.live_announce, "speak", said.append)
    frame = _frame()
    _play_to(frame, 3500)
    frame._subtitle_review_text = lambda step: InternalPlayerFrame._subtitle_review_text(frame, step)
    InternalPlayerFrame._review_subtitle(frame, -1)
    InternalPlayerFrame._read_current_subtitle(frame)
    assert said == ["One", "Two"]
