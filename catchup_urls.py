"""Catch-up archive URLs, ffmpeg exit reasons and download retry rules.

Everything here is wx-free: the URLs are built from a channel dict, and the
same rules are used by the UI's download flow and its tests.
"""
import datetime
import logging
import re
import threading
import urllib.parse
from typing import Dict, Optional

from i18n import gettext as _
from i18n import N_
from options import utc_to_local
from http_headers import split_stream_modifiers

# Child of the rotating-file "EPG" logger configured in playlist.py, so UI/search
# diagnostics land in the same log file and honor the same EPG_DEBUG switch.
LOG = logging.getLogger("EPG.ui")

# Catch-up downloads: providers refuse bursts of connections with 403s and
# flaky networks drop streams, so a failed download is retried automatically
# (with the delay doubled per attempt) instead of making the user start over.
# User cancellations are never retried; the budget is small on purpose.
_CATCHUP_RETRY_MAX_ATTEMPTS = 3
_CATCHUP_RETRY_BASE_DELAY_SECONDS = 2.0

# A catch-up download counts as complete when ffmpeg wrote at least this
# share of the programme length. Stats rounding and streams that end a
# second early are normal; anything shorter means the provider closed the
# connection mid-file and the download is retried rather than celebrated.
_CATCHUP_SHORT_COMPLETION_RATIO = 0.95
_CATCHUP_RETRYABLE_RE = re.compile(
r"403\b|429\b|50[0-9]\b|connection (?:reset|refused|closed)|timed? ?out|"
r"temporarily unavailable|no route to host|server returned", re.IGNORECASE)

# Teleelevidenie counts every media request against an account-wide, one-stream
# allowance.  Keep this deliberately narrow: ``timeshift`` alone does not say
# that an unrelated provider has the same restriction.
_ONE_STREAM_PROVIDER_SUFFIXES = ("teleelevidenie.com",)


def single_stream_provider_key(url: str) -> str:
    """The exclusive-connection key for a known one-stream provider, or ``""``."""
    if not url:
        return ""
    try:
        base_url, _headers = split_stream_modifiers(url)
        host = (urllib.parse.urlsplit(base_url).hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return ""
    for suffix in _ONE_STREAM_PROVIDER_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return suffix
    return ""


def _ffmpeg_error_tag(a, b, c, d) -> int:
    """FFmpeg's FFERRTAG: the negative code ffmpeg exits with for that error."""
    def byte(ch):
        return ch if isinstance(ch, int) else ord(ch)
    return -(byte(a) | (byte(b) << 8) | (byte(c) << 16) | (byte(d) << 24))


# ffmpeg exits with the AVERROR of whatever stopped it, and Windows reports that
# as an unsigned 32-bit number: a refused download read "code 3436169992", which
# is HTTP 403 Forbidden. These put the common ones into words.
_FFMPEG_EXIT_REASONS = (
    ((_ffmpeg_error_tag(0xF8, "4", "0", "3"),),
     N_("The provider refused access (HTTP 403 Forbidden). Many providers allow "
        "only one stream per account at a time: stop other playback or downloads "
        "from this account and try again.")),
    ((_ffmpeg_error_tag(0xF8, "4", "0", "1"),),
     N_("The provider asked for a login (HTTP 401 Unauthorized). Check the "
        "playlist's user name and password.")),
    ((_ffmpeg_error_tag(0xF8, "4", "0", "4"),),
     N_("The provider does not have this programme (HTTP 404 Not Found). It may "
        "be older than the provider's archive.")),
    ((_ffmpeg_error_tag(0xF8, "4", "0", "0"), _ffmpeg_error_tag(0xF8, "4", "2", "9"),
      _ffmpeg_error_tag(0xF8, "4", "X", "X")),
     N_("The provider rejected the request (HTTP 4xx error).")),
    ((_ffmpeg_error_tag(0xF8, "5", "X", "X"),),
     N_("The provider's server had an error (HTTP 5xx). Try again later.")),
    ((_ffmpeg_error_tag("I", "N", "D", "A"),),
     N_("The stream sent data that could not be read.")),
    # ETIMEDOUT / ECONNREFUSED as the Windows CRT, Linux and Winsock number them.
    ((-138, -110, -10060),
     N_("The connection to the provider timed out.")),
    ((-107, -111, -10061),
     N_("The provider's server refused the connection.")),
)


def _ffmpeg_exit_reason(rc) -> str:
    """Plain words for an ffmpeg exit code, or "" when it is not a known one."""
    try:
        code = int(rc)
    except (TypeError, ValueError):
        return ""
    if code > 0x7FFFFFFF:
        code -= 1 << 32
    for codes, reason in _FFMPEG_EXIT_REASONS:
        if code in codes:
            return _(reason)
    return ""


def _catchup_failure_is_retryable(rc: int, stderr_lines, *, stopped_by_user: bool = False) -> bool:
    """True when a finished download failed for a reason retrying can fix."""
    if stopped_by_user:
        return False
    # rc == 0.0 (a float) is the truncation sentinel from
    # _handle_truncated_catchup_download: the process really exited clean but
    # the transfer came up short, so the success rule must not short-circuit
    # here. rc == 0 (int) stays a genuine clean exit.
    if not rc and not (isinstance(rc, float) and rc == 0.0):
        return False
    text = "\n".join(stderr_lines or [])
    return bool(_CATCHUP_RETRYABLE_RE.search(text))


def _schedule_retry(fn, delay_seconds: float):
    """Run ``fn`` once after ``delay_seconds`` on a daemon thread."""
    timer = threading.Timer(delay_seconds, fn)
    timer.daemon = True
    timer.start()
    return timer

# EPG-style placeholders some providers embed in catchup-source templates.
# ${start}/${timestamp} (teleelevidenie), {utc}/{lutc}, and the long variants
# all appear in the wild; Kodi's IPTV Simple documents the {S} family.
_CATCHUP_TEMPLATE_TOKENS = (
    ("${start}", "start"), ("${timestamp}", "lutc"),
    ("${duration}", "duration"), ("${end}", "end"),
    ("{utc}", "start"), ("{lutc}", "lutc"),
    ("{utcstart}", "start"), ("{utcend}", "end"),
    ("{duration}", "duration"),
    ("{S}", "start"), ("{E}", "end"), ("{L}", "lutc"), ("{D}", "duration"),
    ("{Y}", "start_year"), ("{m}", "start_month"), ("{d}", "start_day"),
    ("{H}", "start_hour"), ("{M}", "start_minute"),
    ("{y}", "end_year"), ("{e}", "end_day"), ("{h}", "end_hour"), ("{i}", "end_minute"),
)


def _catchup_token_value(kind: str, start_dt, end_dt, now, wall_start=None, wall_end=None) -> str:
    """Render one catchup-source placeholder as a string.

    Epoch tokens are instants and stay on the UTC value. The date-and-hour
    tokens name a time on the provider's own clock, so they use the channel's
    ``catchup-timezone``: an archive asked for 12:00 UTC by a provider reading
    local time answers with a programme from the wrong hour.
    """
    wall_start = wall_start if wall_start is not None else start_dt
    wall_end = wall_end if wall_end is not None else end_dt
    if kind == "start":
        return str(int(start_dt.timestamp()))
    if kind == "end":
        return str(int(end_dt.timestamp()))
    if kind == "lutc":
        return str(int(now.timestamp()))
    if kind == "duration":
        return str(max(1, int((end_dt - start_dt).total_seconds())))
    if kind == "start_year":
        return wall_start.strftime("%Y")
    if kind == "start_month":
        return wall_start.strftime("%m")
    if kind == "start_day":
        return wall_start.strftime("%d")
    if kind == "start_hour":
        return wall_start.strftime("%H")
    if kind == "start_minute":
        return wall_start.strftime("%M")
    if kind == "end_year":
        return wall_end.strftime("%Y")
    if kind == "end_day":
        return wall_end.strftime("%d")
    if kind == "end_hour":
        return wall_end.strftime("%H")
    if kind == "end_minute":
        return wall_end.strftime("%M")
    return ""


def _expand_catchup_template(source: str, start_dt, end_dt, offset_hours: float = 0.0,
                             tz_name: str = ""):
    """Fill an EPG-template ``catchup-source`` in, or return None if it is not one.

    Providers such as teleelevidenie ship ``catchup="append"`` plus a template
    like ``?utc=${start}&lutc=${timestamp}``. That must be appended to the
    channel's live URL with real epoch values, not treated as a static base
    path -- the old code turned it into ``<host>/<start>/<duration>/``, which
    the server answers with 403.
    """
    text = (source or "").strip()
    if not text:
        return None
    expanded = text
    matched = False
    for token, kind in _CATCHUP_TEMPLATE_TOKENS:
        if token in expanded:
            matched = True
            break
    if not matched:
        return None

    if offset_hours:
        try:
            shift = datetime.timedelta(hours=float(offset_hours))
        except (TypeError, ValueError):
            shift = datetime.timedelta(0)
        start_dt = start_dt - shift
        end_dt = end_dt - shift
    wall_start = _catchup_wall_clock(start_dt, tz_name)
    wall_end = _catchup_wall_clock(end_dt, tz_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    for token, kind in _CATCHUP_TEMPLATE_TOKENS:
        while token in expanded:
            expanded = expanded.replace(
                token,
                _catchup_token_value(kind, start_dt, end_dt, now, wall_start, wall_end),
                1,
            )
    return expanded


def _positive_timeshift_days(channel: Dict[str, str]) -> Optional[int]:
    """Return a positive M3U ``timeshift`` window, expressed in days.

    Some providers use the older ``timeshift="N"`` attribute instead of the
    newer catchup/catchup-days pair. The attribute says how much archive is
    available, but not how its URL is built, so URL inference stays
    provider-specific below.
    """
    value = channel.get("timeshift")
    try:
        days = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


def _implicit_catchup_source(channel: Dict[str, str]) -> str:
    """Infer a catch-up template when a known provider only sends timeshift.

    Teleelevidenie's current dynamic playlists mark archive-capable channels as
    ``timeshift="3"`` without the ``catchup-source`` template present in its
    older playlists. Its HLS and TS endpoints both accept the same utc/lutc
    query parameters, so the live container format does not affect this rule.
    """
    if _positive_timeshift_days(channel) is None:
        return ""
    raw_url = str(channel.get("url") or "").split("|", 1)[0].strip()
    try:
        host = (urllib.parse.urlparse(raw_url).hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return ""
    if host == "teleelevidenie.com" or host.endswith(".teleelevidenie.com"):
        return "?utc=${start}&lutc=${timestamp}"
    return ""


# Xtream Codes live URL: /live/USER/PASS/ID[.ext] or the short /USER/PASS/ID[.ext].
_XTREAM_LIVE_PATH_RE = re.compile(r"^/(?:live/)?([^/]+)/([^/]+)/(\d+)(?:\.[A-Za-z0-9]+)?$")


def _catchup_wall_clock(dt: datetime.datetime, tz_name: str = "") -> datetime.datetime:
    """``dt`` on the clock the provider's archive reads catch-up starts in.

    ``tz_name`` is the playlist's ``catchup-timezone``: "UTC" (Dispatcharr) or
    an IANA zone. Without one, or when the zone is unknown here, the user's
    local time is used, which is what Xtream servers in the user's region
    expect.
    """
    name = (tz_name or "").strip()
    if name.upper() in {"UTC", "GMT", "Z", "ETC/UTC", "ETC/GMT"}:
        return dt.astimezone(datetime.timezone.utc)
    if name:
        try:
            from zoneinfo import ZoneInfo
            return dt.astimezone(ZoneInfo(name))
        except Exception:
            LOG.debug("_catchup_wall_clock: unknown catch-up timezone %r", name, exc_info=True)
    return utc_to_local(dt)


def _xtream_timeshift_url(channel: Dict[str, str], start_dt: datetime.datetime,
                          end_dt: datetime.datetime) -> str:
    """Xtream Codes archive URL for a ``catchup="xc"`` channel without a source.

    Xtream playlists (and Dispatcharr's XC output) mark archive channels with
    ``catchup="xc"`` and no ``catchup-source``: the archive URL is implied by
    the live URL. ``/live/U/P/ID`` becomes ``/timeshift/U/P/MIN/START/ID.ts``.
    The live URL's ``|Referer=...|Cookie=...`` tail is kept: a provider that
    needs those headers for live needs them for the archive too.
    """
    raw_url, sep, modifiers = str(channel.get("url") or "").partition("|")
    raw_url = raw_url.strip()
    modifiers = modifiers.strip()
    try:
        parsed = urllib.parse.urlparse(raw_url)
    except (TypeError, ValueError):
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    m = _XTREAM_LIVE_PATH_RE.match(parsed.path or "")
    if not m:
        return ""
    user, password, stream_id = m.groups()
    duration = max(1, int((end_dt - start_dt).total_seconds() // 60))
    start = _catchup_wall_clock(start_dt, channel.get("catchup-timezone", ""))
    try:
        offset = channel.get("catchup-offset")
        if offset:
            start -= datetime.timedelta(hours=float(offset))
    except (TypeError, ValueError):
        LOG.debug("_xtream_timeshift_url: ignored catch-up offset", exc_info=True)
    token = start.strftime("%Y-%m-%d:%H-%M")
    url = (f"{parsed.scheme}://{parsed.netloc}/timeshift/{user}/{password}/"
           f"{duration}/{token}/{stream_id}.ts")
    if parsed.query:
        # A provider token in the live URL's query authorises the archive too.
        url = f"{url}?{parsed.query}"
    ua = channel.get("http-user-agent")
    # Read the tail with the same parser playback uses, so aliases such as
    # "UA=" count as a User-Agent and the provider's own value is not overridden.
    tail_headers = split_stream_modifiers("x|" + modifiers)[1] if modifiers else {}
    if ua and not tail_headers.get("user-agent"):
        modifiers = "|".join(filter(None, [modifiers, f"User-Agent={urllib.parse.quote(ua)}"]))
    return f"{url}|{modifiers}" if modifiers else url
