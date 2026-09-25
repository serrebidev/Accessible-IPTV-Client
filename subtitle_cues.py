"""Timed text cues from a local SRT or WebVTT file, for subtitle speech.

libVLC renders subtitles but never hands their text to Python, so the player
parses the file it loaded itself and looks cues up against the media clock.
"""

import bisect
import html
import re
from pathlib import Path
from typing import List, NamedTuple, Optional

MAX_FILE_BYTES = 20 * 1024 * 1024
SPEAKABLE_SUFFIXES = (".srt", ".vtt")

_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")
_TAG = re.compile(r"<[^>]*>|\{\\[^}]*\}")


class Cue(NamedTuple):
    start: int  # milliseconds
    end: int
    text: str


def _ms(h, m, s, frac) -> int:
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0"))


def parse(text: str) -> List[Cue]:
    """Cues sorted by start time; blocks without a timing line are skipped."""
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip("\n").split("\n")
        for i, line in enumerate(lines):
            match = _TIME.search(line)
            if not match:
                continue
            g = match.groups()
            body = " ".join(html.unescape(_TAG.sub("", part)).strip() for part in lines[i + 1:])
            body = " ".join(body.split())
            start, end = _ms(*g[:4]), _ms(*g[4:])
            if body and end > start:
                cues.append(Cue(start, end, body))
            break
    cues.sort()
    return cues


def load(path: str) -> List[Cue]:
    """Parse a subtitle file; raises OSError/ValueError when it is not usable."""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("subtitle file too large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        import chardet
        text = raw.decode(chardet.detect(raw).get("encoding") or "cp1252", errors="replace")
    return parse(text)


def active(cues: List[Cue], ms: int) -> Optional[int]:
    """Index of the cue showing at ``ms``; the latest-starting one wins on overlap."""
    i = bisect.bisect_right(cues, (ms, float("inf"), "")) - 1
    while i >= 0 and cues[i].start <= ms:
        if ms < cues[i].end:
            return i
        if ms - cues[i].start > 60 * 60 * 1000:
            break  # ponytail: linear back-scan for overlaps; bounded to one hour of cues
        i -= 1
    return None
