"""Real files, shared scheduling and speech: reject metadata, retain dialogue."""
import codecs
import random

import pytest

from subtitle_cues import Cue, CueIndex, active, load, parse
from subtitle_pipeline import PlaybackPosition, TimedTextSource
from subtitle_session import SubtitleSessionController
from subtitle_speech import SubtitleSpeechManager


@pytest.mark.parametrize("marker", ["NOTE", "NOTE example", "NOTE\texample", "STYLE", "STYLE \t", "REGION"])
@pytest.mark.parametrize("hint", ["", ".vtt", "VTT"])
def test_webvtt_metadata_timing_examples_cannot_become_spoken_cues(marker, hint):
    text = (f"WEBVTT\n\n{marker}\n00:01.000 --> 00:02.000\nNot dialogue\n\n"
            "cue-id\n00:03.000 --> 00:04.000 align:start\n<v Narrator>Actual words</v>\n")
    assert parse(text, hint) == [Cue(3000, 4000, "Actual words")]


def test_srt_identifier_named_note_is_not_a_webvtt_comment():
    assert parse("NOTE\n00:00:01,000 --> 00:00:02,000\nDialogue\n", ".srt") == [Cue(1000, 2000, "Dialogue")]


def test_vtt_metadata_prefix_is_not_confused_with_a_longer_cue_identifier():
    assert parse("WEBVTT\n\nNOTEBOOK\n00:01.000 --> 00:02.000\nDialogue\n") == [Cue(1000, 2000, "Dialogue")]


@pytest.mark.parametrize("timing", [
    "00:60:01,000 --> 01:01:02,000", "00:01:60,000 --> 00:02:02,000",
    "-00:00:01,000 --> 00:00:02,000", "prefix 00:00:01,000 --> 00:00:02,000",
    "00:00:01,0000 --> 00:00:02,000", "00:00:01,000 --> 00:00:02,0000",
    "00:00:02,000 --> 00:00:01,000", "00:00:02,000 --> 00:00:02,000",
    "9" * 5000 + ":00:01,000 --> 00:00:02,000",
    "9999999999999999999:00:01,000 --> 9999999999999999999:00:02,000",
])
def test_bad_srt_event_does_not_discard_a_later_valid_caption(timing):
    text = f"1\n{timing}\nBad event\n\n2\n00:00:03,000 --> 00:00:04,000\nStill valid\n"
    assert parse(text) == [Cue(3000, 4000, "Still valid")]


def test_timing_examples_deeper_in_a_block_do_not_start_a_caption():
    text = "Damaged block\nUnrelated description\n00:00:01,000 --> 00:00:02,000\nNot a cue\n"
    assert parse(text) == []


@pytest.mark.parametrize("hours", ["9" * 5000, "9999999999999999999"])
def test_ass_bad_time_skips_only_that_event(hours):
    text = ("[Events]\nFormat: Start, End, Text\n"
            f"Dialogue: {hours}:00:01.00,{hours}:00:02.00,Invalid\n"
            "Dialogue: 0:00:03.00,0:00:04.00,Valid\n")
    assert parse(text, ".ass") == [Cue(3000, 4000, "Valid")]


def test_large_ass_drawing_mode_value_cannot_abort_text_extraction():
    text = ("[Events]\nFormat: Start, End, Text\n"
            "Dialogue: 0:00:01.00,0:00:02.00,{\\p" + "9" * 5000 + "}m 0 0{\\p0}Words\n")
    assert parse(text, ".ssa") == [Cue(1000, 2000, "Words")]


def test_long_unfinished_ass_override_does_not_hide_the_next_event():
    text = ("[Events]\nFormat: Start, End, Text\n"
            "Dialogue: 0:00:01.00,0:00:02.00," + "{" * 200_000 + "\\p1 hidden\n"
            "Dialogue: 0:00:03.00,0:00:04.00,Valid words\n")
    assert parse(text, ".ass") == [Cue(3000, 4000, "Valid words")]


def test_many_unclosed_html_openers_are_preserved_without_repeated_suffix_scans():
    body = "<" * 200_000
    assert parse("1\n00:00:01,000 --> 00:00:02,000\n" + body) == [Cue(1000, 2000, body)]


@pytest.mark.parametrize("body,expected", [("Value < 3", "Value < 3"),
                                           ("<i>A</i> {\\an8}<b>B</b> &amp; C", "A B & C"),
                                           ("<00:00:01.200><v Speaker>A</v><c.green>B</c>", "AB")])
def test_inline_markup_and_literal_comparison_preserve_spoken_words(body, expected):
    assert parse("1\n00:00:01,000 --> 00:00:02,000\n" + body) == [Cue(1000, 2000, expected)]


@pytest.mark.parametrize("encoding,bom", [
    ("utf-16-le", codecs.BOM_UTF16_LE), ("utf-16-be", codecs.BOM_UTF16_BE),
    ("utf-32-le", codecs.BOM_UTF32_LE), ("utf-32-be", codecs.BOM_UTF32_BE),
])
@pytest.mark.parametrize("suffix,content", [
    (".srt", "1\r\n00:00:01,000 --> 00:00:02,000\r\nŐrült víz, tűz és jég.\r\n"),
    (".vtt", "WEBVTT\r\n\r\n00:01.000 --> 00:02.000\r\nŐrült víz, tűz és jég.\r\n"),
    (".ssa", "[Events]\nFormat: Start, End, Text\nDialogue: 0:00:01.00,0:00:02.00,Őrült víz, tűz és jég.\n"),
])
def test_declared_unicode_encodings_do_not_depend_on_charset_guessing(tmp_path, monkeypatch, encoding, bom,
                                                                    suffix, content):
    import chardet
    monkeypatch.setattr(chardet, "detect", lambda raw: pytest.fail("a Unicode BOM must be authoritative"))
    path = tmp_path / ("Ékezetes felirat – őű" + suffix)
    path.write_bytes(bom + content.encode(encoding))
    assert load(path) == [Cue(1000, 2000, "Őrült víz, tűz és jég.")]


def test_real_unsupported_codec_result_uses_the_existing_legacy_fallback(tmp_path, monkeypatch):
    import chardet
    monkeypatch.setattr(chardet, "detect", lambda raw: {"encoding": "EUC-TW", "confidence": 1.0})
    path = tmp_path / "legacy.srt"
    path.write_bytes("1\n00:00:01,000 --> 00:00:02,000\nCafé\n".encode("cp1252"))
    assert load(path) == [Cue(1000, 2000, "Café")]


def test_long_active_cue_survives_a_gap_longer_than_an_hour():
    cues = [Cue(0, 10_000_000, "Long-lived"), Cue(1, 2, "Expired overlay")]
    assert active(cues, 7_200_000) == 0
    assert CueIndex(cues).active(7_200_000) == 0
    assert TimedTextSource(cues).sample(PlaybackPosition(7_200_000)).snapshot.text == "Long-lived"


def test_index_matches_a_brute_force_oracle_for_nested_overlaps_and_random_seeks():
    randomizer = random.Random(82471)
    cues = sorted(Cue(start, start + randomizer.randrange(1, 5000), str(i))
                  for i in range(1500) for start in [randomizer.randrange(0, 10000)])
    index = CueIndex(iter(cues))
    for ms in [0, 1, 15000] + [randomizer.randrange(0, 16000) for _ in range(500)]:
        expected = next((i for i in range(len(cues) - 1, -1, -1) if cues[i].start <= ms < cues[i].end), None)
        assert index.active(ms) == expected
        expected_started = next((i for i in range(len(cues) - 1, -1, -1) if cues[i].start <= ms), None)
        assert index.started(ms) == expected_started


def test_many_expired_cues_do_not_hide_an_earlier_long_lived_cue():
    cues = [Cue(0, 1_000_000, "Still visible")]
    cues.extend(Cue(i, i + 1, "Expired") for i in range(1, 100_000))
    index = CueIndex(cues)
    assert index.active(200_000) == 0
    assert index.active(1_000_000) is None
    assert index.started(200_000) == len(cues) - 1


@pytest.mark.parametrize("cues", [[], [Cue(1000, 2000, "Single")],
                                  [Cue(1000, 2000, "First"), Cue(1000, 3000, "Second")]])
def test_index_boundary_and_tie_semantics_match_the_sorted_file(cues):
    index = CueIndex(cues)
    for ms in (-1, 0, 999, 1000, 1999, 2000, 2999, 3000):
        assert index.active(ms) == active(cues, ms)


def test_unordered_index_input_is_rejected_instead_of_silently_selecting_wrong_cues():
    with pytest.raises(ValueError, match="start-sorted"):
        CueIndex([Cue(2000, 3000, "Later"), Cue(1000, 2000, "Earlier")])


def test_file_metadata_and_rejected_events_never_reach_speech_or_review(tmp_path):
    path = tmp_path / "review.vtt"
    path.write_text("WEBVTT\n\nNOTE a timing example\n00:00.000 --> 00:10.000\nNot dialogue\n\n"
                    "00:99.000 --> 01:00.000\nMalformed\n\n"
                    "00:01.000 --> 00:02.000\nIgen.\n\n00:03.000 --> 00:04.000\nIgen.\n", encoding="utf-8")
    source = TimedTextSource.from_file(path)
    spoken = []
    manager = SubtitleSpeechManager(spoken.append)
    manager.set_auto_speech(True)
    owner = SubtitleSessionController(manager)
    sink = owner.bind(owner.activate_session("file"))
    for ms in (500, 1500, 2500, 3500, 4500):
        sink.on_snapshot(source.sample(PlaybackPosition(ms), track=path.as_uri()).snapshot)
    assert spoken == ["Igen.", "Igen."]
    assert [(cue.text, cue.start_ms) for cue in manager.get_recent()] == [("Igen.", 1000), ("Igen.", 3000)]
    assert not manager.read_current()
    assert manager.read_previous()
    assert spoken == ["Igen.", "Igen.", "Igen."]
