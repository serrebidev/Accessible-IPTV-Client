"""Shared helpers for building HTTP header dictionaries from channel metadata."""

import urllib.parse
from typing import Dict, List, Optional, Tuple

# ``|Key=Value`` modifier names, as they appear after a stream URL in M3U
# playlists, mapped onto the canonical header keys the rest of the app uses.
_MODIFIER_ALIASES = {
    "user-agent": "user-agent", "ua": "user-agent", "http-user-agent": "user-agent",
    "referer": "referer", "referrer": "referer",
    "http-referrer": "referer", "http-referer": "referer",
    "origin": "origin", "http-origin": "origin",
    "cookie": "cookie", "http-cookie": "cookie",
    "authorization": "authorization", "auth": "authorization",
    "http-authorization": "authorization",
    "x-forwarded-for": "x-forwarded-for", "xff": "x-forwarded-for",
    "accept": "accept", "http-accept": "accept",
    "range": "range", "http-range": "range",
}


def normalize_header_name(key: str) -> str:
    """``x-forwarded-for`` -> ``X-Forwarded-For``."""
    return "-".join(part.capitalize() for part in key.split("-") if part)


def split_stream_modifiers(url: str) -> Tuple[str, Dict[str, object]]:
    """Split ``<url>|User-Agent=...|Referer=...`` into the URL and its headers.

    The pipe tail is an M3U convention that players understand and HTTP does
    not. Anything that fetches a stream itself - a HEAD probe, ffmpeg - has to
    strip it first, or it goes out as part of the query string and the request
    fails.
    """
    if not url:
        return "", {}
    base, sep, tail = url.partition("|")
    headers: Dict[str, object] = {}
    extras: List[str] = []
    if sep:
        for part in tail.split("|"):
            token = part.strip()
            if not token or "=" not in token:
                continue
            key, value = token.split("=", 1)
            key = key.strip().lower()
            value = urllib.parse.unquote_plus(value.strip())
            if not value:
                continue
            canonical = _MODIFIER_ALIASES.get(key)
            if canonical:
                headers[canonical] = value
            elif key in ("bearer", "token"):
                headers["authorization"] = "Bearer " + value
            elif key in ("host", "http-host"):
                extras.append("Host: " + value)
            else:
                extras.append(normalize_header_name(key) + ": " + value)
    if extras:
        headers["_extra"] = extras
    return base.strip(), headers


def merge_headers(base: Optional[Dict[str, object]],
                  extra: Optional[Dict[str, object]]) -> Dict[str, object]:
    """``base`` wins; ``extra`` fills the gaps. ``_extra`` lists are concatenated."""
    merged: Dict[str, object] = dict(base or {})
    for key, value in (extra or {}).items():
        if not value:
            continue
        if key == "_extra":
            combined = list(merged.get("_extra") or []) + [v for v in value if v]
            seen = set()
            deduped = []
            for line in combined:
                prefix = line.split(":", 1)[0].strip().lower()
                if prefix in seen:
                    continue
                seen.add(prefix)
                deduped.append(line)
            merged["_extra"] = deduped
        else:
            merged.setdefault(key, value)
    return merged


def channel_http_headers(channel: Optional[Dict[str, str]]) -> Dict[str, object]:
    """Collect per-channel HTTP headers for players/casters."""
    headers: Dict[str, object] = {}
    if not channel:
        return headers

    def _copy(keys, target: str) -> None:
        for key in keys:
            val = channel.get(key)
            if val:
                headers[target] = val
                return

    _copy(["http-user-agent"], "user-agent")
    _copy(["http-referrer", "http-referer"], "referer")
    _copy(["http-origin"], "origin")
    _copy(["http-cookie"], "cookie")
    _copy(["http-authorization"], "authorization")
    _copy(["http-accept"], "accept")

    extra = channel.get("http-headers")
    if isinstance(extra, (str, tuple, set)):
        extra = [extra]
    if isinstance(extra, list):
        headers["_extra"] = [str(h) for h in extra if h]

    return headers
