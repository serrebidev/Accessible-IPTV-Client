"""A capture that wrote nothing is not a saved recording.

ffmpeg exits 0 when a stream closes before the first frame, and the report
said "Recording saved" pointing at a file that was missing or empty.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


def test_a_missing_file_is_not_media(tmp_path):
    rec = SimpleNamespace(out_path=str(tmp_path / "gone.mkv"))
    assert main._recording_produced_media(rec) is False


def test_an_empty_file_is_not_media(tmp_path):
    out = tmp_path / "empty.mkv"
    out.write_bytes(b"")
    assert main._recording_produced_media(SimpleNamespace(out_path=str(out))) is False


def test_a_file_with_bytes_is_media(tmp_path):
    out = tmp_path / "out.mkv"
    out.write_bytes(b"\x1aE\xdf\xa3")
    assert main._recording_produced_media(SimpleNamespace(out_path=str(out))) is True
