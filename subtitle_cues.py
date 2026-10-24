"""Timed text cues from SRT, WebVTT and ASS/SSA files, for subtitle speech.

libVLC renders subtitles but never hands their text to Python, so the player
parses the file it loaded itself and looks cues up against the media clock.
"""

import bisect
import codecs
import html
import logging
import re
from pathlib import Path
from typing import List, NamedTuple, Optional

LOG = logging.getLogger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024
SPEAKABLE_SUFFIXES = (".srt", ".vtt", ".ass", ".ssa")

_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})[ \t]*-->[ \t]*"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})(?:[ \t]+[^\r\n]*)?")
_MARKUP_START = re.compile(r"<|\{\\")
_ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})\.(\d{1,3})\Z")
_DRAWING_MODE = re.compile(r"\\p(\d+)(?=\\|\s|$)")


class Cue(NamedTuple):
    start: int  # milliseconds
    end: int
    text: str


def _ms(h, m, s, frac) -> int:
    # A malformed event must not abort every subsequent cue. Bound conversion
    # before int(): Python rejects enormous digit strings, and libVLC uses i64.
    if len(h or "") > 19 or int(m) >= 60 or int(s) >= 60:
        raise ValueError("invalid subtitle timestamp")
    value = ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0"))
    if value > (1 << 63) - 1:
        raise ValueError("subtitle timestamp exceeds the media clock")
    return value


def _strip_markup(text: str) -> str:
    """Strip closed inline tags without quadratic retries on broken markup.

    Preserve an unclosed fragment as literal text (e.g. mathematical '<').
    No regex scans the remaining line again for every unmatched opener.
    """
    parts, offset = [], 0
    while match := _MARKUP_START.search(text, offset):
        end = text.find(">" if match[0] == "<" else "}", match.end())
        if end < 0:
            break
        parts.append(text[offset:match.start()])
        offset = end + 1
    parts.append(text[offset:])
    return "".join(parts)


def _ass_plain_text(text: str) -> str:
    """Discard overrides, comments and drawing instructions, not spoken text.

    Drawing mode persists across override blocks until an explicit \\p0.
    Karaoke timing is presentation markup; the complete event text is retained.
    ASS backslash line/space escapes are not HTML entity syntax.
    """
    drawing = False
    parts, offset = [], 0
    while offset < len(text):
        opening = text.find("{", offset)
        body = text[offset:opening] if opening >= 0 else text[offset:]
        if not drawing:
            parts.append(body.replace("}", "").replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " "))
        if opening < 0:
            break
        closing = text.find("}", opening + 1)
        if closing < 0:
            break  # unfinished ASS overrides are not spoken as instructions
        for mode in _DRAWING_MODE.finditer(text[opening + 1:closing]):
            drawing = bool(mode.group(1).lstrip("0"))
        offset = closing + 1
    return " ".join("".join(parts).split())


def _ass_timestamp(text: str) -> Optional[int]:
    match = _ASS_TIME.fullmatch(text.strip())
    if not match or int(match[2]) >= 60 or int(match[3]) >= 60:
        return None
    try:
        return _ms(*match.groups())
    except ValueError:
        return None


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
    """Sorted spoken cues; metadata and malformed events are not dialogue.

    A timing line is first, or follows one cue identifier. WebVTT NOTE, STYLE
    and REGION blocks are metadata, even when they contain a timing example.
    Keep the permissive legacy comma/dot and short-fraction time spellings.
    """
    if format_hint.casefold().lstrip(".") in ("ass", "ssa") or (
            not format_hint and re.match(r"(?is)^\ufeff?\s*\[(?:script info|events)\]", text)):
        return parse_ass(text)
    cues = []
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    is_vtt = format_hint.casefold().lstrip(".") == "vtt" or bool(re.match(r"^WEBVTT(?:[ \t\n]|$)", text))
    for block in re.split(r"\n[ \t]*\n", text):
        lines = block.strip("\n").split("\n")
        if is_vtt and (re.match(r"^(?:WEBVTT|NOTE)(?:[ \t]|$)", lines[0])
                       or lines[0].rstrip(" \t") in ("STYLE", "REGION")):
            continue
        for i, line in enumerate(lines[:2]):
            match = _TIME.fullmatch(line.strip())
            if not match:
                continue
            g = match.groups()
            body = " ".join(html.unescape(_strip_markup(part)).strip() for part in lines[i + 1:])
            body = " ".join(body.split())
            try:
                start, end = _ms(*g[:4]), _ms(*g[4:])
            except ValueError:
                break
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
        # UTF-32 LE begins with the UTF-16 LE marker; test longer BOMs first.
        if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            text = raw.decode("utf-32", errors="replace")
        elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            text = raw.decode("utf-16", errors="replace")
        else:
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
        i -= 1
    return None


class CueIndex:
    """Immutable start/end index for a sorted file's playback-time queries.

    Find the rightmost started cue whose end is still in the future. A maximum
    end tree prunes expired ranges, so long gaps and deeply overlapping cues
    need logarithmic lookup without an arbitrary subtitle-duration cutoff.
    Rebuild only when the owner replaces the file, never in its timer tick.
    """

    def __init__(self, cues):
        cues = tuple(cues)
        self._starts = tuple(cue.start for cue in cues)
        if any(a > b for a, b in zip(self._starts, self._starts[1:])):
            raise ValueError("cue index requires start-sorted cues")
        self._size = 1 << (max(1, len(self._starts)) - 1).bit_length()
        self._max_end = [float("-inf")] * (2 * self._size)
        for i, cue in enumerate(cues):
            self._max_end[self._size + i] = cue.end
        for i in range(self._size - 1, 0, -1):
            self._max_end[i] = max(self._max_end[2 * i], self._max_end[2 * i + 1])

    def started(self, ms):
        index = bisect.bisect_right(self._starts, ms) - 1
        return index if index >= 0 else None

    def active(self, ms):
        limit = self.started(ms)
        if limit is None:
            return None

        def find(node, left, right):
            if left > limit or self._max_end[node] <= ms:
                return None
            if left == right:
                return left
            middle = (left + right) // 2
            result = find(2 * node + 1, middle + 1, right)
            return result if result is not None else find(2 * node, left, middle)

        return find(1, 0, self._size - 1)
