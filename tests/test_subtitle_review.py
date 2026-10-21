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
        _speak_subtitles=False, _is_paused=False, subtitle_label=label, spoken=[], _on_cue_cb=None, _subtitle_generation=0,
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


def test_seeking_back_into_a_gap_rebounds_review_to_the_playhead():
    frame = _frame()
    _play_to(frame, 5500)
    _play_to(frame, 2500)  # seek back into the gap after "One"
    assert _say(frame, 0) == "Last subtitle: One"
    assert _say(frame, 1) == "No later subtitle."
    _play_to(frame, 500)  # before the first cue
    assert _say(frame, 0) == "No subtitle has been shown yet."


def test_subtitles_off_keeps_what_was_already_shown():
    frame = _frame()
    _play_to(frame, 3500)
    frame.player.video_get_spu = lambda: -1
    _play_to(frame, 5500)
    assert _say(frame, 0) == "Last subtitle: Two"


def test_started_cue_lookup():
    import subtitle_cues
    assert subtitle_cues.started(CUES, 999) is None
    assert subtitle_cues.started(CUES, 1000) == 0
    assert subtitle_cues.started(CUES, 4500) == 1
    assert subtitle_cues.started(CUES, 99999) == 2


def test_new_commands_are_offered_in_the_keyboard_shortcuts_dialog():
    import inspect
    import main
    source = inspect.getsource(main.IPTVClient._customize_shortcuts)
    for action in ("read_subtitle", "previous_subtitle", "next_subtitle"):
        assert '("player", "%s"' % action in source


def test_the_players_cue_reaches_the_speech_manager():
    """The built-in player's cues have to reach the shared manager.

    Without a cue sink the manager never saw them, so "Read current subtitle"
    and "Review recent subtitles" always answered "No subtitle text available
    yet." - the app's own player could not use the feature its menu offers.
    """
    import main as appmod

    seen = []

    class FakeManager:
        def on_cue(self, text, start_ms=None, end_ms=None, source="", track="", generation=0):
            seen.append((text, start_ms, end_ms, source))

    client = appmod.IPTVClient.__new__(appmod.IPTVClient)
    client._subtitle_manager = FakeManager()

    appmod.IPTVClient._on_player_subtitle_cue(
        client, "Hello", start_ms=1000, end_ms=3000, source="builtin-file")

    assert seen == [("Hello", 1000, 3000, "builtin-file")]


def test_the_builtin_player_sends_the_cue_timing():
    """The player looked for cue.start_ms, which the cue never has.

    Every cue reached the manager without a timing, so the duplicate rule
    fell back to the wording and two consecutive lines with the same text
    were merged - the second was never spoken.
    """
    import inspect
    import internal_player

    source = inspect.getsource(internal_player.InternalPlayerFrame)
    assert "cue.start_ms" not in source
    assert 'getattr(cue, "start", None)' in source


def test_the_subtitle_speech_toggle_saves_the_setting(monkeypatch):
    """The toggle called a method the frame does not have.

    ``self.save_config()`` raised AttributeError, so the menu item popped a
    Python error dialog, the setting was never written and the toggle did
    nothing at all.
    """
    import main

    saved = []
    spoken = []
    monkeypatch.setattr(main, "save_config", lambda cfg: saved.append(dict(cfg)))
    monkeypatch.setattr(main.live_announce, "speak", lambda text: None)
    client = types.SimpleNamespace(
        config={"speak_subtitles": False, "media_player": "VLC"},
        _subtitle_manager=types.SimpleNamespace(set_auto_speech=spoken.append),
        _ensure_mpv_subtitle_session=lambda: None,
    )

    main.IPTVClient._on_toggle_subtitle_speech(client)

    assert client.config["speak_subtitles"] is True
    assert saved and saved[0]["speak_subtitles"] is True
    assert spoken == [True]
