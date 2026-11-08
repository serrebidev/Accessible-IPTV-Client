"""Pure validation for on-demand seek controls; never changes playback rate."""
import re
import time
from dataclasses import dataclass

from i18n import gettext as _


def parse_position(value):
    value = str(value).strip()
    if not re.fullmatch(r"\d{1,6}(:\d{1,2}){0,2}", value):
        raise ValueError(_("Enter seconds, MM:SS or HH:MM:SS."))
    parts = [int(p) for p in value.split(":")]
    if any(p >= 60 for p in parts[1:]):
        raise ValueError(_("Minutes and seconds after a colon must be below 60."))
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    if seconds > 7 * 86400:
        raise ValueError(_("The requested position is too large."))
    return seconds * 1000


def clock_text(milliseconds):
    seconds = max(0, int(milliseconds)) // 1000
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def target_position(current, length, *, delta=None, target=None):
    if type(current) is not int or current < 0:
        raise ValueError(_("The playback position is not available yet."))
    if (delta is None) == (target is None):
        raise ValueError("Specify one seek target")
    value = current + int(delta) if delta is not None else int(target)
    if type(length) is not int or length <= 0:
        raise ValueError(_("The media duration is not available yet."))
    return max(0, min(value, max(0, length - 1000)))


@dataclass
class PendingSeek:
    generation: int
    target: int
    started: float
    origin: int

    def outcome(self, generation, position, *, now=None):
        if generation != self.generation:
            return "stale"
        now = time.monotonic() if now is None else now
        # Do not mistake the old clock for success on small seeks. +/- 1 s
        # accommodates keyframe timing without silently accepting an ignored jump.
        if type(position) is int and abs(position - self.target) <= 1000:
            return "done"
        return "failed" if now - self.started >= 8 else "pending"
