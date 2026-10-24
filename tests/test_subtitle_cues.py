import subtitle_cues


SRT = """1
00:00:01,000 --> 00:00:02,500
<i>Hello</i> there,
general Kenobi.

2
00:00:03,000 --> 00:00:04,000
{\\an8}Second &amp; last
"""

VTT = """WEBVTT

intro
00:01.000 --> 00:02.000 align:start
<v Bob>Hi Bob</v>

01:00:00.000 --> 01:00:01.000
Hour mark
"""


def test_srt_cues_strip_markup_and_join_lines():
    cues = subtitle_cues.parse(SRT)
    assert cues == [
        subtitle_cues.Cue(1000, 2500, "Hello there, general Kenobi."),
        subtitle_cues.Cue(3000, 4000, "Second & last"),
    ]


def test_vtt_cues_accept_short_timestamps_and_settings():
    cues = subtitle_cues.parse(VTT)
    assert [c.text for c in cues] == ["Hi Bob", "Hour mark"]
    assert cues[1].start == 3_600_000


def test_active_cue_lookup_handles_gaps_and_overlaps():
    cues = subtitle_cues.parse(SRT)
    assert subtitle_cues.active(cues, 500) is None
    assert subtitle_cues.active(cues, 1000) == 0
    assert subtitle_cues.active(cues, 2600) is None
    assert subtitle_cues.active(cues, 3999) == 1
    overlap = [subtitle_cues.Cue(0, 5000, "long"), subtitle_cues.Cue(1000, 2000, "short")]
    assert subtitle_cues.active(overlap, 1500) == 1
    assert subtitle_cues.active(overlap, 3000) == 0


def test_load_falls_back_from_utf8(tmp_path):
    path = tmp_path / "latin.srt"
    lines = ["Café crème à côté", "Où êtes-vous allé hier soir ?", "Très bien, merci beaucoup.",
             "Je préfère le thé à la crème brûlée.", "C'était déjà réglé, n'est-ce pas ?"] * 4
    text = "".join(f"{i + 1}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\n{line}\n\n"
                   for i, line in enumerate(lines))
    path.write_bytes(text.encode("cp1252"))
    assert [c.text for c in subtitle_cues.load(str(path))] == lines


def test_load_survives_an_encoding_python_does_not_have(tmp_path, monkeypatch):
    """chardet can name an encoding Python has no codec for (EUC-TW, ISO-2022-CN).

    The lookup raised before the decode was tried, the cue thread died, and
    the status line had already said the file loaded.
    """
    import chardet

    class _Unknown:
        encoding = "EUC-TW"

    monkeypatch.setattr(chardet, "detect", lambda raw: _Unknown())
    path = tmp_path / "legacy.srt"
    path.write_bytes("1\n00:00:01,000 --> 00:00:02,500\nHello there\n".encode("cp1252"))

    assert [c.text for c in subtitle_cues.load(str(path))] == ["Hello there"]


def test_loader_bounds_each_read_before_checking_file_size(tmp_path, monkeypatch):
    import pytest
    from pathlib import Path

    path = tmp_path / "oversized.srt"
    path.write_bytes(b"x" * 32)
    monkeypatch.setattr(subtitle_cues, "MAX_FILE_BYTES", 8)
    actual_open = Path.open
    reads = []

    class BoundedRead:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size=-1):
            reads.append(size)
            assert 0 <= size <= 9, "the loader must not allocate the entire untrusted file"
            return self.stream.read(size)

    monkeypatch.setattr(Path, "open", lambda self, *args, **kwargs: BoundedRead(actual_open(self, *args, **kwargs)))
    with pytest.raises(ValueError, match="too large"):
        subtitle_cues.load(path)
    assert reads == [9]


def test_file_exactly_at_byte_limit_keeps_its_final_unicode_character(tmp_path, monkeypatch):
    content = "1\n00:00:01,000 --> 00:00:02,000\nÁrvíztűrő\n".encode("utf-8")
    path = tmp_path / "boundary.srt"
    path.write_bytes(content)
    monkeypatch.setattr(subtitle_cues, "MAX_FILE_BYTES", len(content))
    assert subtitle_cues.load(path) == [subtitle_cues.Cue(1000, 2000, "Árvíztűrő")]
