"""Tests for the built-in player's preferred audio track selection.

The user this is for cannot see the track menu, so the matching rules matter: picking
the wrong track is worse than picking none, and a track list that libVLC has not
finished publishing yet must not be mistaken for "no match".
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import internal_player  # noqa: E402

AD_KEYWORDS = internal_player.preferred_audio_keywords(prefer_audio_description=True)


class TestTrackMatching:
    def test_whole_words_match_in_any_position(self):
        assert internal_player.audio_track_matches("English AD", "ad")
        assert internal_player.audio_track_matches("AD (English)", "ad")
        assert internal_player.audio_track_matches("Track 2 - [eng ad]", "ad")

    def test_short_keywords_never_match_inside_a_word(self):
        # The bug this prevents: "AD" selecting the Radio track.
        assert not internal_player.audio_track_matches("Radio 4", "ad")
        assert not internal_player.audio_track_matches("Advertising feed", "ad")

    def test_long_keywords_match_inside_a_compound_word(self):
        assert internal_player.audio_track_matches("Audiodescription-Ton", "audio description")
        assert internal_player.audio_track_matches("Audiodeskription", "audiodeskription")

    def test_multi_word_keywords_need_the_words_in_order(self):
        assert internal_player.audio_track_matches("Audio Description (eng)", "audio description")
        assert not internal_player.audio_track_matches("Description of audio", "audio description")

    def test_matching_ignores_case_and_punctuation(self):
        assert internal_player.audio_track_matches("[ENGLISH] - Audio_Description", "audio description")

    def test_non_latin_track_names_tokenize(self):
        # A Cyrillic or CJK name must not collapse to no tokens at all, or a user
        # who typed their own wording would silently never get a match.
        assert internal_player.audio_track_matches("Аудиодескрипция (рус)",
                                                   "аудиодескрипция")
        assert internal_player.audio_track_matches("音声解説", "音声解説")

    def test_empty_inputs(self):
        assert not internal_player.audio_track_matches("", "ad")
        assert not internal_player.audio_track_matches("English AD", "")
        assert not internal_player.audio_track_matches(None, None)


class TestKeywordList:
    def test_user_wording_comes_before_the_built_in_guesses(self):
        keywords = internal_player.preferred_audio_keywords(
            ["German AD"], prefer_audio_description=True)
        assert keywords[0] == "German AD"
        assert "audio description" in keywords

    def test_audio_description_is_opt_in(self):
        assert internal_player.preferred_audio_keywords(["English"]) == ["English"]
        assert internal_player.preferred_audio_keywords() == []

    def test_duplicates_are_dropped_case_insensitively(self):
        keywords = internal_player.preferred_audio_keywords(
            ["AD", "ad", "English"], prefer_audio_description=True)
        assert keywords.count("AD") == 1
        assert "ad" not in keywords[1:]


class TestTrackSelection:
    def test_picks_the_audio_description_track(self):
        tracks = [(0, "Track 1 - [English]"), (1, "English AD"), (2, "Deutsch")]
        assert internal_player.select_preferred_audio_track(tracks, AD_KEYWORDS) == 1

    def test_leaves_an_ordinary_stereo_only_channel_alone(self):
        tracks = [(0, "Track 1 - [English]"), (1, "Radio Deutschland")]
        assert internal_player.select_preferred_audio_track(tracks, AD_KEYWORDS) is None

    def test_earlier_keywords_win(self):
        tracks = [(0, "English"), (1, "Deutsch")]
        keywords = ["deutsch", "english"]
        assert internal_player.select_preferred_audio_track(tracks, keywords) == 1

    def test_no_tracks_or_no_keywords(self):
        assert internal_player.select_preferred_audio_track([], AD_KEYWORDS) is None
        assert internal_player.select_preferred_audio_track([(0, "English AD")], []) is None


class _FakeChoice:
    def __init__(self):
        self.items = []
        self.enabled = None
        self.selection = None
        self.name = ""

    def SetItems(self, items):
        self.items = list(items)

    def Enable(self, value=True):
        self.enabled = bool(value)

    def SetSelection(self, index):
        self.selection = index

    def SetName(self, name):
        self.name = name


class TestTabReachableAudioTrackControl:
    def test_choice_lists_and_announces_the_active_track(self):
        choice = _FakeChoice()
        frame = types.SimpleNamespace(
            audio_track_choice=choice,
            _audio_track_choice_ids=[],
            _audio_track_choice_signature=(),
            _get_audio_tracks=lambda: [(0, "English"), (3, "English AD")],
            _current_audio_track_id=lambda: 3,
        )

        internal_player.InternalPlayerFrame._refresh_audio_track_choice(frame)

        assert choice.items == ["English", "English AD"]
        assert choice.enabled is True
        assert choice.selection == 1
        assert "English AD" in choice.name


def _stub_frame(tracks, current_id=0, keywords=("audio description",), prefer_ad=False):
    """A stand-in with just enough state for the preference methods.

    The real frame needs libVLC and a window, so the methods under test are called
    unbound against this. That is the whole point of them not touching wx.
    """
    frame = types.SimpleNamespace()
    frame.selected = []
    frame.status = []
    frame._wanted_audio_track_name = None
    frame._audio_track_label = ""
    frame._audio_reapply_pending = False
    frame._audio_preference_pending = True
    frame._audio_preference_attempts = 0
    frame._max_audio_preference_attempts = 3
    frame._preferred_audio_tracks = list(keywords)
    frame._prefer_audio_description = prefer_ad
    frame._channel_audio_track = ""
    frame._get_audio_tracks = lambda: list(tracks)
    frame._current_audio_track_id = lambda: current_id
    frame._select_audio_track = frame.selected.append
    frame._update_status_label = lambda *args, **kwargs: frame.status.append(args)
    frame._preferred_audio_keywords = types.MethodType(
        internal_player.InternalPlayerFrame._preferred_audio_keywords, frame)
    return frame


def _apply(frame):
    internal_player.InternalPlayerFrame._maybe_apply_preferred_audio_track(frame)


class TestApplyingThePreference:
    def test_a_renamed_track_comes_back_by_its_position(self):
        # The TVP 2 bug: the remembered name no longer matches after a
        # reconnect, so the stream stayed on its first track. The remembered
        # slot still points at the same audio.
        frame = _stub_frame([(0, "Stereo"), (1, "Newly Named Track"), (2, "Other")],
                            keywords=())
        frame._audio_track_fallback_index = 1
        _apply(frame)
        assert frame.selected == [1]

    def test_no_remembered_slot_leaves_the_stream_alone(self):
        frame = _stub_frame([(0, "Stereo"), (1, "Something")], keywords=())
        frame._audio_track_fallback_index = None
        _apply(frame)
        assert frame.selected == []

    def test_ad_preference_takes_the_last_named_description_track(self):
        frame = _stub_frame([(0, "English"), (1, "Polski"), (2, "AD (eng)"),
                             (3, "AD (pol)")], keywords=(), prefer_ad=True)
        frame._audio_track_fallback_index = None
        _apply(frame)
        assert frame.selected == [3]

    def test_ad_preference_guesses_the_last_track_when_none_is_named(self):
        # Providers append the audio description track after the ordinary
        # ones, so on a stream whose labels say nothing useful the highest
        # number is the best guess there is.
        frame = _stub_frame([(0, "Track 1"), (1, "Track 2"), (2, "Track 3")],
                            keywords=(), prefer_ad=True)
        frame._audio_track_fallback_index = None
        _apply(frame)
        assert frame.selected == [2]

    def test_ad_guess_never_fires_without_the_preference(self):
        frame = _stub_frame([(0, "Track 1"), (1, "Track 2")], keywords=())
        frame._audio_track_fallback_index = None
        _apply(frame)
        assert frame.selected == []

    def test_ad_guess_defers_to_a_remembered_slot(self):
        # current_id=1 so the remembered slot 0 actually requires a switch;
        # on the slot the stream already plays, no switch is correct.
        frame = _stub_frame([(0, "Track 1"), (1, "Track 2")],
                            current_id=1, keywords=(), prefer_ad=True)
        frame._audio_track_fallback_index = 0
        _apply(frame)
        assert frame.selected == [0]

    def test_switches_to_the_matching_track(self):
        frame = _stub_frame([(0, "English"), (1, "Audio Description")])
        _apply(frame)
        assert frame.selected == [1]
        assert frame._audio_preference_pending is False

    def test_a_track_list_that_is_still_empty_is_retried(self):
        frame = _stub_frame([])
        _apply(frame)
        assert frame._audio_preference_pending is True, "gave up before libVLC published tracks"
        _apply(frame)
        _apply(frame)
        assert frame._audio_preference_pending is False, "retried forever"
        assert frame.selected == []

    def test_a_late_arriving_track_is_still_picked_up(self):
        tracks = []
        frame = _stub_frame(tracks)
        frame._get_audio_tracks = lambda: list(tracks)
        _apply(frame)
        tracks.extend([(0, "English"), (1, "Audio Description")])
        _apply(frame)
        assert frame.selected == [1]

    def test_a_manual_choice_is_never_overridden(self):
        frame = _stub_frame([(0, "English"), (1, "Audio Description")])
        frame._wanted_audio_track_name = "English"
        _apply(frame)
        assert frame.selected == []
        assert frame._audio_preference_pending is False

    def test_already_on_the_preferred_track_does_not_reselect_it(self):
        frame = _stub_frame([(0, "Audio Description"), (1, "English")], current_id=0)
        _apply(frame)
        assert frame.selected == []
        # It is still recorded as wanted, so a reconnect restores it.
        assert frame._wanted_audio_track_name == "Audio Description"
        assert frame._audio_track_label == "Audio Description"

    def test_nothing_happens_without_a_preference(self):
        frame = _stub_frame([(0, "English"), (1, "Audio Description")], keywords=())
        _apply(frame)
        assert frame.selected == []
        assert frame._audio_preference_pending is False

    def test_no_match_gives_up_after_the_attempt_budget(self):
        frame = _stub_frame([(0, "English"), (1, "Deutsch")])
        for _ in range(frame._max_audio_preference_attempts):
            _apply(frame)
        assert frame.selected == []
        assert frame._audio_preference_pending is False


class TestLastManualTrackIsRemembered:
    def test_manual_pick_leads_the_match_list(self):
        frame = _stub_frame(
            [(0, "English"), (1, "Polski"), (2, "Audio Description")],
            keywords=("audio description",))
        frame._last_manual_audio_track = "Polski"
        frame._update_status_label = lambda *a, **k: None
        frame._refresh_audio_track_choice = lambda: None
        frame.player = types.SimpleNamespace(
            audio_set_track=lambda tid: frame.selected.append(tid))
        frame._select_audio_track = types.MethodType(
            internal_player.InternalPlayerFrame._select_audio_track, frame)
        _apply(frame)
        assert frame.selected == [1]
        assert frame._wanted_audio_track_name == "Polski"

    def test_selecting_a_track_records_it_as_the_last_manual_track(self):
        frame = types.SimpleNamespace()
        frame.selected = []
        frame.status = []
        frame._wanted_audio_track_name = None
        frame._audio_track_label = ""
        frame._audio_reapply_pending = False
        frame._last_manual_audio_track = ""
        frame._on_last_track_changed_cb = lambda name, index=None: frame.status.append(name)
        frame._get_audio_tracks = lambda: [(0, "English"), (1, "Polski")]
        frame.player = types.SimpleNamespace(
            audio_set_track=lambda tid: frame.selected.append(tid))
        frame._update_status_label = lambda *a, **k: None
        frame._refresh_audio_track_choice = lambda: None

        internal_player.InternalPlayerFrame._select_audio_track(frame, 1, manual=True)

        assert frame._last_manual_audio_track == "Polski"
        assert frame._wanted_audio_track_name == "Polski"
        assert "Polski" in frame.status  # persisted via the callback

    def test_an_automatic_preference_match_is_not_a_manual_pick(self):
        frame = _stub_frame([(0, "English"), (1, "Audio Description")])
        frame._last_manual_audio_track = ""
        frame.player = types.SimpleNamespace(
            audio_set_track=lambda tid: frame.selected.append(tid))
        frame._select_audio_track = types.MethodType(
            internal_player.InternalPlayerFrame._select_audio_track, frame)
        frame._update_status_label = lambda *a, **k: None
        frame._refresh_audio_track_choice = lambda: None

        _apply(frame)

        assert frame.selected == [1]
        assert frame._last_manual_audio_track == "", (
            "the automatic match must not overwrite the hand-picked track")

    def test_last_manual_track_survives_a_stream_change(self):
        frame = _stub_frame([], keywords=())
        frame._last_manual_audio_track = "Polski"
        frame._wanted_audio_track_name = "Polski"
        frame._audio_track_label = "Polski"
        frame._audio_reapply_pending = True
        frame._arm_audio_preference = lambda: None

        internal_player.InternalPlayerFrame._begin_new_stream_audio_state(frame)

        assert frame._last_manual_audio_track == "Polski"
        assert frame._wanted_audio_track_name is None
        assert frame._audio_track_label == ""
        assert frame._audio_reapply_pending is False

class TestPerChannelTrackIsRemembered:
    """The track a channel was last watched with comes back with that channel."""

    def test_the_channel_track_leads_the_match_list(self):
        frame = _stub_frame([], keywords=("english",))
        frame._channel_audio_track = "Polski"
        assert internal_player.InternalPlayerFrame._preferred_audio_keywords(frame)[0] == "Polski"

    def test_it_outranks_the_audio_description_default(self):
        # Ticking "prefer audio description" is a default for channels the user
        # has not decided about; a track hand-picked on *this* channel is a
        # decision, so it has to win.
        frame = _stub_frame([], keywords=(), prefer_ad=True)
        frame._channel_audio_track = "Polski"
        keywords = internal_player.InternalPlayerFrame._preferred_audio_keywords(frame)
        assert keywords[0] == "Polski"
        assert "audio description" in keywords, "AD is still the fallback"

    def test_audio_description_still_wins_on_an_undecided_channel(self):
        frame = _stub_frame([(0, "English"), (1, "English AD")], keywords=(), prefer_ad=True)
        _apply(frame)
        assert frame.selected == [1]

    def test_the_remembered_track_is_picked_over_the_first_one(self):
        frame = _stub_frame(
            [(0, "English"), (1, "Polski"), (2, "English AD")],
            keywords=(), prefer_ad=True)
        frame._channel_audio_track = "Polski"
        _apply(frame)
        assert frame.selected == [1]

    def test_a_manual_pick_becomes_this_channel_track(self):
        frame = types.SimpleNamespace()
        frame.selected = []
        frame._wanted_audio_track_name = None
        frame._audio_track_label = ""
        frame._audio_reapply_pending = False
        frame._last_manual_audio_track = ""
        frame._channel_audio_track = ""
        frame._on_last_track_changed_cb = None
        frame._get_audio_tracks = lambda: [(0, "English"), (1, "Polski")]
        frame.player = types.SimpleNamespace(
            audio_set_track=lambda tid: frame.selected.append(tid))
        frame._update_status_label = lambda *a, **k: None
        frame._refresh_audio_track_choice = lambda: None

        internal_player.InternalPlayerFrame._select_audio_track(frame, 1, manual=True)

        assert frame._channel_audio_track == "Polski"

    def test_an_automatic_match_does_not_become_the_channel_track(self):
        frame = _stub_frame([(0, "English"), (1, "Audio Description")])
        frame.player = types.SimpleNamespace(
            audio_set_track=lambda tid: frame.selected.append(tid))
        frame._select_audio_track = types.MethodType(
            internal_player.InternalPlayerFrame._select_audio_track, frame)
        frame._update_status_label = lambda *a, **k: None
        frame._refresh_audio_track_choice = lambda: None

        _apply(frame)

        assert frame.selected == [1]
        assert frame._channel_audio_track == ""

    def test_switching_channels_replaces_the_remembered_track(self):
        frame = _stub_frame([], keywords=())
        frame._channel_audio_track = "Polski"
        frame._arm_audio_preference = lambda: None
        internal_player.InternalPlayerFrame.set_channel_audio_track(frame, "")
        assert frame._channel_audio_track == "", (
            "the previous channel's track leaked into the next one")

    def test_a_new_stream_keeps_the_channel_track(self):
        frame = _stub_frame([], keywords=())
        frame._channel_audio_track = "Polski"
        frame._arm_audio_preference = lambda: None
        internal_player.InternalPlayerFrame._begin_new_stream_audio_state(frame)
        assert frame._channel_audio_track == "Polski"


class TestWhichTrackTheControlsShow:
    """libVLC's reported track id is a hint; what we asked for is the answer."""

    TRACKS = [(0, "English"), (1, "English AD")]

    def test_the_requested_track_wins_over_a_stale_libvlc_id(self):
        # libVLC keeps answering audio_get_track() with the old id for a moment
        # after a switch. That used to park the control on "English" while the
        # audio description was playing.
        assert internal_player.active_audio_track_index(
            self.TRACKS, 0, "English AD") == 1

    def test_an_unknown_libvlc_id_does_not_fall_back_to_the_first_track(self):
        assert internal_player.active_audio_track_index(
            self.TRACKS, 99, "English AD") == 1

    def test_libvlc_is_used_when_nothing_was_requested(self):
        assert internal_player.active_audio_track_index(self.TRACKS, 1, "") == 1
        assert internal_player.active_audio_track_index(self.TRACKS, 0, None) == 0

    def test_an_unknown_id_and_no_request_falls_back_to_the_first_track(self):
        assert internal_player.active_audio_track_index(self.TRACKS, 99, "") == 0
        assert internal_player.active_audio_track_index(self.TRACKS, None, "") == 0

    def test_a_requested_track_that_is_gone_falls_back_to_libvlc(self):
        assert internal_player.active_audio_track_index(
            self.TRACKS, 1, "Deutsch") == 1

    def test_no_tracks(self):
        assert internal_player.active_audio_track_index([], 3, "English AD") == 0

    def test_the_choice_control_announces_the_requested_track(self):
        choice = _FakeChoice()
        frame = types.SimpleNamespace(
            audio_track_choice=choice,
            _audio_track_choice_ids=[],
            _audio_track_choice_signature=(),
            _wanted_audio_track_name="English AD",
            _get_audio_tracks=lambda: list(self.TRACKS),
            _current_audio_track_id=lambda: 0,  # stale
        )

        internal_player.InternalPlayerFrame._refresh_audio_track_choice(frame)

        assert choice.selection == 1
        assert "English AD" in choice.name
