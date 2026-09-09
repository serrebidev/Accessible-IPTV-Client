"""Tests for the digit-token, bytes-track-name and EPG schema fixes.

* Channel-name tokenization must keep digits and quality tags: "TV 6 HD" and
  "TV 4 HD" differ only by their digit once noise words are stripped, and
  dropping those tokens made both names match nothing in the EPG database
  (no View EPG, no catch-up, no on-air row labels).
* libVLC audio track names arrive as bytes for non-ASCII text; the decoder
  must turn them into real strings so preferences can match and save.
* A read-only open of an old EPG database must report its missing columns
  instead of letting every query die with "no such column".
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import options  # noqa: E402
import playlist  # noqa: E402


class TestChannelNameTokens:
    def test_digit_tokens_are_kept(self):
        assert playlist.tokenize_channel_name("TV 6 HD") == {"6", "hd"}

    def test_quality_tags_are_kept_but_resolutions_dropped(self):
        assert "hd" in playlist.tokenize_channel_name("Polsat HD")
        assert "720p" not in playlist.tokenize_channel_name("Sky 720p")
        assert "4k" not in playlist.tokenize_channel_name("Sky 4k")

    def test_noise_words_still_stripped(self):
        assert playlist.tokenize_channel_name("The Sports Channel") == {"sports"}

    def test_tv6_and_tv4_now_differ(self):
        assert playlist.tokenize_channel_name("TV 6 HD") != playlist.tokenize_channel_name("TV 4 HD")

    def test_single_letters_still_dropped(self):
        assert playlist.tokenize_channel_name("A Sports") == {"sports"}


class TestTrackNameDecoding:
    def test_bytes_decode_utf8(self):
        raw = "Ścieżka 2 - [mis]".encode("utf-8")
        from internal_player import InternalPlayerFrame
        assert InternalPlayerFrame._decode_track_name(raw) == "Ścieżka 2 - [mis]"

    def test_invalid_bytes_replaced_not_crashed(self):
        from internal_player import InternalPlayerFrame
        out = InternalPlayerFrame._decode_track_name(b"\xff\xfe bad")
        assert isinstance(out, str) and out

    def test_str_passthrough(self):
        from internal_player import InternalPlayerFrame
        assert InternalPlayerFrame._decode_track_name("  Track 1  ") == "Track 1"

    def test_none_is_empty(self):
        from internal_player import InternalPlayerFrame
        assert InternalPlayerFrame._decode_track_name(None) == ""

    def test_normalise_audio_tracks_decodes_bytes(self):
        from internal_player import InternalPlayerFrame
        expected = "Ścieżka 1"
        desc = [(1, expected.encode("utf-8")), (2, "English")]
        tracks = InternalPlayerFrame._normalise_audio_tracks(desc)
        assert tracks[0][1] == expected
        assert tracks[1] == (2, "English")


class TestCoerceStringListBytes:
    def test_bytes_items_are_decoded(self):
        raw = "Ścieżka 2".encode("utf-8")
        assert options.coerce_string_list([raw, "ok"]) == ["Ścieżka 2", "ok"]

    def test_undecodable_bytes_survive_as_replacement_text(self):
        out = options.coerce_string_list([b"\xff\xfe"])
        assert out == ["\ufffd\ufffd"]


class TestChannelAudioTrackStore:
    """The per-channel audio-track memory has to survive a hand-edited config."""

    def test_non_dict_values_become_an_empty_map(self):
        for junk in (None, "bbc one", ["bbc one"], 7):
            assert options.coerce_channel_audio_tracks(junk) == {}

    def test_blank_keys_and_values_are_dropped(self):
        out = options.coerce_channel_audio_tracks(
            {"bbc one": "English AD", "": "x", "  ": "y", "itv": "  ", "sky": None})
        assert out == {"bbc one": "English AD"}

    def test_bytes_names_are_decoded_so_the_config_can_be_written(self):
        # A bytes value in here used to make save_config throw, silently losing
        # every other preference change in that same write.
        out = options.coerce_channel_audio_tracks({"tvp": "Ścieżka 2".encode("utf-8")})
        assert out == {"tvp": "Ścieżka 2"}

    def test_the_oldest_entries_are_evicted_first(self):
        limit = options.MAX_REMEMBERED_CHANNEL_AUDIO_TRACKS
        stored = {f"channel {i}": f"track {i}" for i in range(limit + 10)}
        out = options.coerce_channel_audio_tracks(stored)
        assert len(out) == limit
        assert "channel 0" not in out
        assert out[f"channel {limit + 9}"] == f"track {limit + 9}"

    def test_normalizing_a_config_fills_the_key_in(self):
        cfg = {}
        options.normalize_channel_and_audio_settings(cfg)
        assert cfg["channel_audio_tracks"] == {}

    def test_track_indices_coerce(self):
        out = options.coerce_channel_audio_track_indices({
            "tvp": 2, "floaty": 1.0, "negative": -1, "huge": 10 ** 6,
            "bool": True, "junk": "two", "bytes-key": 3,
        })
        # bools are ints in Python but never a slot index.
        assert out == {"tvp": 2, "floaty": 1, "bytes-key": 3}

    def test_track_indices_junk_collapses_to_empty(self):
        assert options.coerce_channel_audio_track_indices(None) == {}
        assert options.coerce_channel_audio_track_indices({"a": "x"}) == {}
        assert options.coerce_channel_audio_track_indices({"a": [1]}) == {}

    def test_normalizing_a_config_fills_the_indices_key_in(self):
        cfg = {}
        options.normalize_channel_and_audio_settings(cfg)
        assert cfg["channel_audio_track_indices"] == {}


class TestEPGSchemaCheck:
    def _make_db(self, tmp_path, with_description: bool):
        import sqlite3
        p = tmp_path / ("epg" + ("_new" if with_description else "_old") + ".db")
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE channels (id TEXT PRIMARY KEY, display_name TEXT, norm_name TEXT, group_tag TEXT)")
        cols = "id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, title TEXT, start TEXT, end TEXT"
        if with_description:
            cols += ", description TEXT"
        conn.execute(f"CREATE TABLE programmes ({cols})")
        conn.commit()
        conn.close()
        return str(p)

    def test_old_database_reports_missing_description(self, tmp_path):
        db = playlist.EPGDatabase(self._make_db(tmp_path, False), readonly=True)
        try:
            assert db._missing_columns == ["description"]
        finally:
            db.close()

    def test_new_database_reports_nothing_missing(self, tmp_path):
        db = playlist.EPGDatabase(self._make_db(tmp_path, True), readonly=True)
        try:
            assert db._missing_columns == []
        finally:
            db.close()

    def test_read_write_open_migrates_old_database(self, tmp_path):
        path = self._make_db(tmp_path, False)
        db = playlist.EPGDatabase(path)  # writable: _create_tables migrates
        try:
            assert db._check_schema() == []
        finally:
            db.close()
