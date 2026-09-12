"""Fast direct-download URLs for catch-up programmes.

Many IPTV backends expose every catch-up programme not only as an HLS playlist
but also as a progressive ``index-<utc>-<duration>.mp4`` file next to it. A
progressive file downloads as fast as HTTP allows, while the HLS pipeline is
pacing itself segment by segment -- so when the direct file exists it is the
right URL to hand to ffmpeg.

Everything here is GUI-free and urllib-based so it can run on a worker thread
and be unit-tested without a network (the candidate builder is pure).
"""

import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

LOG = logging.getLogger(__name__)

# ``index-<utc>-<duration>.m3u8`` -- when the playlist name itself carries the
# server's start/duration numbers, those are the authoritative ones.
_INDEX_DATED_RX = re.compile(
    r"^index-(?P<utc>\d{9,12})-(?P<dur>\d{2,7})\.m3u8$", re.IGNORECASE)

_REJECT_CONTENT_TYPES = frozenset({
    "application/json", "application/xhtml+xml", "application/xml", "text/html",
})


def _clean_headers(headers: Optional[Dict[str, object]]) -> Dict[str, str]:
    return {
        str(name): str(value) for name, value in (headers or {}).items()
        if value
    }


def candidate_direct_urls(url: str, utc: int, duration: int) -> List[str]:
    """Direct ``.mp4`` URLs worth probing for one catch-up playlist URL.

    Pure string work -- no network. Ordered most-likely first; callers dedupe
    and verify with a HEAD/ranged-GET probe.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return []
    if not parts.scheme or not parts.netloc:
        return []
    path = parts.path
    filename = path.rsplit("/", 1)[-1]
    directory = path[: len(path) - len(filename)] if filename else path
    query = parts.query

    def build(new_dir: str, new_file: str) -> str:
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, new_dir + new_file, query, ""))

    out: List[str] = []
    dated = _INDEX_DATED_RX.match(filename)
    if dated:
        # The playlist itself is date-stamped; trust the server's numbers.
        out.append(build(directory, "index-%s-%s.mp4" % (dated.group("utc"), dated.group("dur"))))
    if not dated or (int(dated.group("utc")) != utc or int(dated.group("dur")) != duration):
        out.append(build(directory, "index-%d-%d.mp4" % (utc, duration)))
    # Some backends host the files under the first path segment only, which is
    # what the community teleelevidenie download script does after following
    # the redirect.
    segments = [seg for seg in path.split("/") if seg]
    if len(segments) >= 2:
        out.append(build("/%s/" % segments[0], "index-%d-%d.mp4" % (utc, duration)))
    # Preserve order, drop duplicates.
    seen = set()
    unique = []
    for candidate in out:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _headers_look_like_media(resp_headers) -> bool:
    ctype = (resp_headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if not ctype:
        return True
    return ctype.startswith(("video/", "audio/", "application/octet-stream")) \
        and ctype not in _REJECT_CONTENT_TYPES


def probe_direct_url(url: str, headers: Optional[Dict[str, object]] = None,
                     timeout: float = 6.0) -> bool:
    """True when ``url`` answers like a real downloadable media file."""
    request_headers = _clean_headers(headers)
    try:
        req = urllib.request.Request(url, headers=request_headers, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not _headers_look_like_media(resp.headers):
                return False
            length = resp.headers.get("Content-Length")
            return length != "0"
    except urllib.error.HTTPError as err:
        # HTTPError doubles as an open response object holding a socket.
        # Close it now, or it leaks until GC and -W error reports the
        # ResourceWarning as an unraisable blamed on whichever test runs next.
        err.close()
        if err.code not in (403, 404, 405, 410, 501):
            return False
        # Some servers reject HEAD outright; a 1-byte ranged GET settles it.
        try:
            ranged = dict(request_headers)
            ranged["Range"] = "bytes=0-0"
            req = urllib.request.Request(url, headers=ranged)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _headers_look_like_media(resp.headers)
        except urllib.error.HTTPError as err:
            # Same leak as the outer handler: close before GC reports it.
            err.close()
            LOG.debug("catchup_direct.probe_direct_url: ignored exception", exc_info=True)
            return False
        except Exception:
            LOG.debug("catchup_direct.probe_direct_url: ignored exception", exc_info=True)
            return False
    except Exception:
        LOG.debug("catchup_direct.probe_direct_url: ignored exception", exc_info=True)
        return False


# Redirect chains are short; anything longer is a loop.
_MAX_REDIRECT_HOPS = 5

# Providers that allow one stream per account count a media request as a
# session for a moment after it closes: teleelevidenie answered a request made
# within ~1 s of closing its archive stream with 403, and one made 2 s later
# with 200. When the probe had to touch the media itself, wait this long before
# handing the URL to ffmpeg, or ffmpeg's own request is the one refused.
_MEDIA_SESSION_SETTLE_SECONDS = 2.5


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _next_hop(url: str, headers: Optional[Dict[str, object]],
              timeout: float) -> Tuple[Optional[str], bool]:
    """``(where url redirects to, whether the media itself answered)``.

    Only one hop is taken, and the target is never requested. That is the
    point: resolving the chain by *following* it opens the programme's stream
    on the media server, and on a one-stream-per-account provider that open
    session makes the very next request -- the direct-file probe, or ffmpeg --
    come back 403 Forbidden. Redirectors answer HEAD with their Location, so
    GET is only tried when HEAD is refused.
    """
    opener = urllib.request.build_opener(_NoRedirect)
    request_headers = _clean_headers(headers)
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=request_headers, method=method)
            with opener.open(req, timeout=timeout):
                return None, True
        except urllib.error.HTTPError as err:
            # Same leak as probe_direct_url: close the response promptly.
            err.close()
            if 300 <= err.code < 400:
                location = err.headers.get("Location")
                return (urllib.parse.urljoin(url, location) if location else None), False
            if method == "HEAD" and err.code in (405, 501):
                continue
            return None, False
        except Exception:
            LOG.debug("catchup_direct._next_hop: ignored exception", exc_info=True)
            return None, False


def settle_media_session() -> None:
    """Wait until a one-stream provider has let go of a media request.

    Call it after anything that requested the media itself (a verified
    ``.mp4`` probe, an ffprobe of the stream) and before ffmpeg asks for it.
    """
    time.sleep(_MEDIA_SESSION_SETTLE_SECONDS)


def direct_download_url(url: str, start_epoch: int, duration_seconds: int,
                        headers: Optional[Dict[str, object]] = None,
                        timeout: float = 6.0) -> Optional[str]:
    """A verified fast direct URL for this catch-up programme, or None.

    Network work (one HEAD per redirect hop and per candidate); keep it off
    the GUI thread. ``headers`` are the channel's HTTP headers (user agent,
    referer, ...) so the probe is authenticated exactly like playback.

    The redirect chain is walked lazily: each hop's Location is turned into
    candidates and probed before that Location is requested, so a chain that
    ends on the media server (teleelevidenie's ``/play/...`` -> archive
    ``timeshift_abs-<utc>.ts``) finds the ``.mp4`` next to it without ever
    opening the stream.
    """
    if not url or not start_epoch or not duration_seconds or duration_seconds <= 0:
        return None
    utc = int(start_epoch)
    duration = int(duration_seconds)
    tried = set()

    def probe_around(base: str) -> Optional[str]:
        for candidate in candidate_direct_urls(base, utc, duration):
            if candidate in tried or candidate == base:
                continue
            tried.add(candidate)
            if probe_direct_url(candidate, headers, timeout):
                return candidate
        return None

    current = url
    touched_media = False
    seen = {url}
    found = None
    for _hop in range(_MAX_REDIRECT_HOPS):
        target, is_media = _next_hop(current, headers, timeout)
        touched_media = touched_media or is_media
        if not target or target in seen:
            break
        seen.add(target)
        found = probe_around(target)
        if found:
            break
        current = target
    if not found:
        found = probe_around(url)
    # Verifying the file IS a request for the media (a HEAD, or a 1-byte GET
    # where HEAD is refused), so the provider holds the account's one stream
    # for a moment after it. ffmpeg starting straight after the probe was that
    # second stream and got 403 on every attempt, retries included.
    if found or touched_media:
        settle_media_session()
    return found
