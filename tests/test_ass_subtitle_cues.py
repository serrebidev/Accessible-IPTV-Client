"""ASS/SSA words feed the same timeline as SRT; no visual renderer or OCR."""
import pytest

from subtitle_cues import Cue, load, parse, parse_ass
from subtitle_pipeline import PlaybackPosition, TimedTextSource
from subtitle_session import SubtitleSessionController
from subtitle_speech import SubtitleSpeechManager

ASS = r"""[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname
Style: Default,Arial

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Comment: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,Not spoken
Dialogue: 0,0:00:01.25,0:00:02.50,Default,,0,0,0,,{\i1}Árvíztűrő{\i0}\Nszöveg, vesszővel.
Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,{\k20}Kara{\k30}oke\htext
Dialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,{\p1}m 0 0 l 100 100{\p0}Visible words
"""


def test_ass_events_preserve_centiseconds_commas_unicode_and_karaoke_words():
    assert parse(ASS) == [Cue(1250, 2500, "Árvíztűrő szöveg, vesszővel."),
                          Cue(3000, 4000, "Karaoke text"), Cue(5000, 6000, "Visible words")]


def test_ssa_marked_field_and_declared_field_order_are_not_assumed():
    text = "[Events]\nFormat: Marked, End, Start, Name, Text\n" \
           "Dialogue: Marked=0,0:00:02.00,0:00:01.00,Bob,Hello, Bob\n"
    assert parse_ass(text) == [Cue(1000, 2000, "Hello, Bob")]


@pytest.mark.parametrize("body,expected", [
    (r"{\p1}m 0 0 l 50 50", ""),
    (r"{\p1}m 0 0{\bord1} l 50 50{\p0}Actual text", "Actual text"),
    (r"{\pbo50}Real words", "Real words"),
    (r"{inline comment}A\nB\NC\hD", "A B C D"),
    (r"1 < 2 &amp; 3", "1 < 2 &amp; 3"),
])
def test_drawing_only_events_and_formatting_are_not_spoken(body, expected):
    text = "[Events]\nFormat: Start, End, Text\nDialogue: 0:00:01.00,0:00:02.00," + body
    assert [cue.text for cue in parse_ass(text)] == ([expected] if expected else [])


@pytest.mark.parametrize("start,end", [("0:99:00.00", "1:00:00.00"), ("0:00:99.00", "0:01:00.00"),
                                      ("not a time", "0:00:02.00"), ("0:00:02.00", "0:00:01.00"),
                                      ("0:00:02.00", "0:00:02.00")])
def test_invalid_event_times_are_not_promoted_to_speech(start, end):
    assert parse_ass(f"[Events]\nFormat: Start, End, Text\nDialogue: {start},{end},Wrong") == []


@pytest.mark.parametrize("format", ["Start, End, Text, Style", "Start, Text", "Start, End, Text, Text"])
def test_ambiguous_or_incomplete_formats_do_not_guess_text_columns(format):
    assert parse_ass(f"[Events]\nFormat: {format}\nDialogue: 0:00:01.00,0:00:02.00,Wrong,extra") == []


def test_style_and_attachment_sections_do_not_become_dialogue_events():
    assert parse_ass("[V4+ Styles]\nFormat: Start, End, Text\n"
                     "Dialogue: 0:00:01.00,0:00:02.00,Not a cue\n") == []


def test_explicit_srt_format_does_not_interpret_caption_text_as_ass_sections(tmp_path):
    path = tmp_path / "literal.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\n[Events]\n", encoding="utf-8")
    assert load(path) == [Cue(1000, 2000, "[Events]")]


@pytest.mark.parametrize("suffix", [".ass", ".ssa", ".ASS"])
def test_files_reach_the_real_shared_timeline_and_selected_speech_backend(tmp_path, suffix):
    path = tmp_path / ("Felirat – őű" + suffix)
    path.write_text(ASS, encoding="utf-8-sig")
    source = TimedTextSource.from_file(path)
    spoken = []
    manager = SubtitleSpeechManager(spoken.append)
    manager.set_auto_speech(True)
    controller = SubtitleSessionController(manager)
    sink = controller.bind(controller.activate_session("builtin-file"))
    for position in (1500, 2700, 3500, 5500):
        sink.on_snapshot(source.sample(PlaybackPosition(position), track=path.as_uri()).snapshot)
    assert spoken == [cue.text for cue in parse_ass(ASS)]
    assert [cue.start_ms for cue in manager.get_recent()] == [1250, 3000, 5000]
