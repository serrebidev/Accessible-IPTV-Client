"""Timed text cues from SRT, WebVTT and ASS/SSA files, for subtitle speech.

libVLC renders subtitles but never hands their text to Python, so the player
parses the file it loaded itself and looks cues up against the media clock.
"""

import bisect
import html
import logging
import re
from pathlib import Path
from typing import List, NamedTuple, Optional

LOG = logging.getLogger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024
SPEAKABLE_SUFFIXES = (".srt", ".vtt", ".ass", ".ssa")

_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")
_TAG = re.compile(r"<[^>]*>|\{\\[^}]*\}")
_ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})\.(\d{1,3})\Z")
_ASS_PART = re.compile(r"\{([^}]*)\}|([^{}]+)")
_DRAWING_MODE = re.compile(r"\\p(\d+)(?=\\|\s|$)")


class Cue(NamedTuple):
    start: int  # milliseconds
    end: int
    text: str


def _ms(h, m, s, frac) -> int:
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0"))


def _ass_plain_text(text: str) -> str:
    """Discard overrides, comments and drawing instructions, not spoken text.

    Drawing mode persists across override blocks until an explicit \\p0.
    Karaoke timing is presentation markup; the complete event text is retained.
    ASS backslash line/space escapes are not HTML entity syntax.
    """
    drawing = False
    parts = []
    for match in _ASS_PART.finditer(text):
        override, body = match.groups()
        if override is not None:
            for mode in _DRAWING_MODE.finditer(override):
                drawing = int(mode.group(1)) != 0
        elif not drawing:
            parts.append(body.replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " "))
    return " ".join("".join(parts).split())


def _ass_timestamp(text: str) -> Optional[int]:
    match = _ASS_TIME.fullmatch(text.strip())
    if not match or int(match[2]) >= 60 or int(match[3]) >= 60:
        return None
    return _ms(*match.groups())


def parse_ass(text: str) -> List[Cue]:
    """Read timed Dialogue events using the declared ASS/SSA event format.

    Format must identify Start, End and a final Text field. The last field
    consumes commas verbatim. Comments, styles, attachments and vector-only
    events are not speech. This extracts words/times, not visual typesetting.
    """
    cues = []
    in_events = False
    fields = None
    for line in text.lstrip("\ufeff").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_events = line.casefold() == "[events]"
            fields = None
            continue
        if not in_events:
            continue
        name, sep, value = line.partition(":")
        if not sep:
            continue
        if name.strip().casefold() == "format":
            declared = [field.strip().casefold() for field in value.split(",")]
            fields = declared if (declared and declared[-1] == "text"
                                  and len(set(declared)) == len(declared)
                                  and {"start", "end", "text"}.issubset(declared)) else None
        elif name.strip().casefold() == "dialogue" and fields:
            values = value.lstrip().split(",", len(fields) - 1)
            if len(values) != len(fields):
                continue
            event = dict(zip(fields, values))
            start, end = _ass_timestamp(event["start"]), _ass_timestamp(event["end"])
            body = _ass_plain_text(event["text"])
            if start is not None and end is not None and end > start and body:
                cues.append(Cue(start, end, body))
    cues.sort()
    return cues


def parse(text: str, format_hint: str = "") -> List[Cue]:
    """Cues sorted by start time; blocks without a timing line are skipped."""
    if format_hint.casefold().lstrip(".") in ("ass", "ssa") or (
            not format_hint and re.match(r"(?is)^\ufeff?\s*\[(?:script info|events)\]", text)):
        return parse_ass(text)
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
    # Enforce the limit while reading, not after allocating an arbitrary file.
    # One extra byte distinguishes an exactly-sized file from a larger one.
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("subtitle file too large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        import chardet

        # chardet can name an encoding Python has no codec for (EUC-TW,
        # ISO-2022-CN), and the lookup raises before the decode is tried.
        encoding = chardet.detect(raw).get("encoding") or "cp1252"
        try:
            text = raw.decode(encoding, errors="replace")
        except LookupError:
            LOG.debug("subtitle_cues: unknown encoding %r, using cp1252", encoding)
            text = raw.decode("cp1252", errors="replace")
    return parse(text, Path(path).suffix)


def started(cues: List[Cue], ms: int) -> Optional[int]:
    """Index of the latest cue that has started by ``ms``, shown or not."""
    i = bisect.bisect_right(cues, (ms, float("inf"), "")) - 1
    return i if i >= 0 else None


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
