"""Manual recording times. Native local-time conversion validates DST folds/gaps."""
import datetime as dt
import math
import time

import dvr
from i18n import gettext as _


class AmbiguousTime(ValueError):
    def __init__(self, candidates):
        self.candidates = tuple(candidates)
        super().__init__(_("This local time occurs twice when the clocks change."))


def local_candidates(text):
    """Use the OS's date-specific local zone, not today's fixed UTC offset."""
    try:
        value = dt.datetime.strptime(str(text).strip(), "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError(_("Enter a local date and time as YYYY-MM-DD HH:MM.")) from exc
    candidates = set()
    for isdst in (-1, 0, 1):
        try:
            stamp = time.mktime((*value.timetuple()[:8], isdst))
            if time.localtime(stamp)[:6] == value.timetuple()[:6] and stamp >= 0:
                candidates.add(stamp)
        except (OSError, OverflowError, ValueError):
            continue
    if not candidates:
        raise ValueError(_("This local time does not exist. Check the clock-change date."))
    return sorted(candidates)


def local_timestamp(text, occurrence=None):
    candidates = local_candidates(text)
    if len(candidates) > 1 and occurrence is None:
        raise AmbiguousTime(candidates)
    if occurrence not in (None, 0, 1):
        raise ValueError("Invalid clock-change occurrence")
    return candidates[min(occurrence or 0, len(candidates) - 1)]


def validate_window(start, end, *, now=None, allow_started=False):
    now = time.time() if now is None else now
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (start, end, now)):
        raise ValueError(_("Invalid recording time."))
    if end <= start or end <= now or end - start > 7 * 86400:
        raise ValueError(_("The end must be in the future and after the start, within seven days."))
    if not allow_started and start < now:
        raise ValueError(_("The recording start time has already passed."))


def build_manual_job(channel, title, start, end, fmt, *, now=None):
    validate_window(start, end, now=now)
    title = str(title).strip()
    if not title or len(title) > 240 or any(ord(c) < 32 for c in title):
        raise ValueError(_("Enter a title of 1 to 240 characters."))
    program = {"title": title,
               "start": dt.datetime.fromtimestamp(start, dt.timezone.utc).strftime("%Y%m%d%H%M%S"),
               "end": dt.datetime.fromtimestamp(end, dt.timezone.utc).strftime("%Y%m%d%H%M%S")}
    job = dvr.build_job(channel, program, fmt, pre_padding_minutes=0, post_padding_minutes=0)
    job["manual"] = True
    return job
