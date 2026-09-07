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
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

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
        if err.code not in (403, 404, 405, 410, 501):
            return False
        # Some servers reject HEAD outright; a 1-byte ranged GET settles it.
        try:
            ranged = dict(request_headers)
            ranged["Range"] = "bytes=0-0"
            req = urllib.request.Request(url, headers=ranged)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _headers_look_like_media(resp.headers)
        except Exception:
            LOG.debug("catchup_direct.probe_direct_url: ignored exception", exc_info=True)
            return False
    except Exception:
        LOG.debug("catchup_direct.probe_direct_url: ignored exception", exc_info=True)
        return False


def _resolve_redirects(url: str, headers: Optional[Dict[str, object]],
                       timeout: float) -> str:
    """The URL after following redirects, or ``url`` when that fails.

    The redirect often lands on a host where the catch-up files live; the
    candidate builder needs that final form (the community script does the
    same ``GET`` + ``r.url`` dance).
    """
    try:
        req = urllib.request.Request(url, headers=_clean_headers(headers))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final = resp.geturl()
        return final or url
    except Exception:
        LOG.debug("catchup_direct._resolve_redirects: ignored exception", exc_info=True)
        return url


def direct_download_url(url: str, start_epoch: int, duration_seconds: int,
                        headers: Optional[Dict[str, object]] = None,
                        timeout: float = 6.0) -> Optional[str]:
    """A verified fast direct URL for this catch-up programme, or None.

    Network work (redirect follow + a HEAD probe per candidate); keep it off
    the GUI thread. ``headers`` are the channel's HTTP headers (user agent,
    referer, ...) so the probe is authenticated exactly like playback.
    """
    if not url or not start_epoch or not duration_seconds or duration_seconds <= 0:
        return None
    utc = int(start_epoch)
    duration = int(duration_seconds)
    resolved = _resolve_redirects(url, headers, timeout)
    tried = set()
    for base in (resolved, url):
        for candidate in candidate_direct_urls(base, utc, duration):
            if candidate in tried or candidate == base:
                continue
            tried.add(candidate)
            if probe_direct_url(candidate, headers, timeout):
                return candidate
    return None
