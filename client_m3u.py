"""Playlist (.m3u) parsing and the on-disk parsed-playlist cache.

Split out of main.IPTVClient: no wx dependency. IPTVClient inherits
M3uCacheMixin so every call site and main.IPTVClient.<name> still resolves.
"""

import hashlib
import json
import logging
import os
import re
import threading
import urllib.parse
from typing import Dict, List, Optional, Tuple

import media_type
from options import get_cache_dir
from playlist_headers import _M3U_ATTR_RE, _extinf_name_comma

LOG = logging.getLogger("EPG.ui")


# Bump whenever _parse_m3u_return starts producing different channel dicts
# from the same playlist text; it salts the parsed-playlist cache key.
# 5: a playlist that starts with a byte order mark is read without it, so
#    the same text produces different channel dicts than before.
_PARSED_PLAYLIST_CACHE_VERSION = "5"
# One writer at a time for the parsed playlist cache: two loads can write the
# same cache, and one truncating the other's file would publish a broken one.
_PLAYLIST_CACHE_WRITE_LOCK = threading.Lock()

class M3uCacheMixin:
    def _parse_m3u_return(self, text, provider_info=None):
        provider_info = provider_info or {}
        provider_id = provider_info.get("provider-id")
        provider_type = provider_info.get("provider-type")
        # A playlist may start with a UTF-8 byte order mark. It is not a
        # comment, so the playlist would open with a channel whose URL is the
        # mark and the header, and the header's own attributes would be lost.
        text = text.lstrip("\ufeff")

        out: List[Dict[str, str]] = []
        append = out.append
        stream_id_for = self._extract_stream_id
        attr_iter = _M3U_ATTR_RE.finditer

        # Per-channel metadata, reset after each URL
        name = ""
        group = ""
        tvg_id = ""
        tvg_name = ""
        tvg_rec = ""
        media_hint = ""
        timeshift = ""
        catchup = ""
        catchup_type = ""
        catchup_days = ""
        catchup_source = ""
        catchup_offset = ""
        http_user_agent = ""
        http_referrer = ""
        http_origin = ""
        http_cookie = ""
        http_headers: List[str] = []
        http_auth = ""
        http_accept = ""
        # Playlist-wide catch-up clock from the #EXTM3U header. Dispatcharr
        # sends catchup-timezone="UTC" and its archive expects UTC start
        # times; without it the start goes out in the user's local time.
        catchup_timezone = ""

        for raw_line in text.splitlines():
            s = raw_line.strip()
            if not s:
                continue

            if s[0] == '#':
                upper_prefix = s[:10].upper()
                if upper_prefix.startswith("#EXTM3U"):
                    for match in attr_iter(s[7:]):
                        if match.group(1).lower() == "catchup-timezone":
                            catchup_timezone = (match.group(2) or match.group(3)
                                                or match.group(4) or "").strip()
                            break
                    continue
                if upper_prefix.startswith("#EXTINF"):
                    name = ""
                    group = ""
                    tvg_id = ""
                    tvg_name = ""
                    tvg_rec = ""
                    media_hint = ""
                    timeshift = ""
                    catchup = ""
                    catchup_type = ""
                    catchup_days = ""
                    catchup_source = ""
                    catchup_offset = ""
                    http_user_agent = ""
                    http_referrer = ""
                    http_origin = ""
                    http_cookie = ""
                    http_headers = []
                    http_auth = ""
                    http_accept = ""

                    comma_idx = _extinf_name_comma(s)
                    info_part = s if comma_idx == -1 else s[:comma_idx]
                    if comma_idx != -1:
                        name = s[comma_idx + 1:].strip()

                    colon_idx = info_part.find(':')
                    attr_segment = info_part[colon_idx + 1:] if colon_idx != -1 else ""
                    if attr_segment:
                        attrs: Dict[str, str] = {}
                        for match in attr_iter(attr_segment):
                            key = match.group(1).lower()
                            value = match.group(2) or match.group(3) or match.group(4) or ""
                            if key not in attrs:
                                attrs[key] = value.strip()
                        if attrs:
                            group = attrs.get("group-title", "")
                            tvg_id = attrs.get("tvg-id", "")
                            tvg_name = attrs.get("tvg-name", "")
                            tvg_rec = attrs.get("tvg-rec", "")
                            # Authoritative media-type metadata (issue #33):
                            # radio="true" and recognized equivalents. Parsed
                            # once here so recording, menus and probes share it.
                            media_hint = media_type.media_hint_from_attributes(attrs)
                            timeshift = attrs.get("timeshift", "")
                            catchup = attrs.get("catchup", "")
                            catchup_type = attrs.get("catchup-type", "")
                            catchup_days = attrs.get("catchup-days", "")
                            catchup_source = attrs.get("catchup-source", "")
                            catchup_offset = attrs.get("catchup-offset", "")
                            http_user_agent = attrs.get("http-user-agent", "")
                            http_referrer = attrs.get("http-referrer") or attrs.get("http-referer", http_referrer)
                            http_origin = attrs.get("http-origin", http_origin)
                            http_cookie = attrs.get("http-cookie", http_cookie)
                            http_auth = attrs.get("http-authorization", http_auth)
                            http_accept = attrs.get("http-accept", http_accept)
                    continue

                if upper_prefix.startswith("#EXTVLCOPT"):
                    colon_idx = s.find(':')
                    if colon_idx != -1:
                        data = s[colon_idx + 1:]
                        eq_idx = data.find('=')
                        if eq_idx != -1:
                            key = data[:eq_idx].strip().lower()
                            value = data[eq_idx + 1:].strip()
                            if key in {"catchup-source", "catchup_url"}:
                                catchup_source = value
                            elif key == "catchup-days":
                                catchup_days = value
                            elif key == "catchup-type":
                                catchup_type = value
                            elif key == "http-user-agent":
                                http_user_agent = value
                            elif key in {"http-referrer", "http-referer", "referer", "referrer"}:
                                http_referrer = value
                            elif key in {"http-origin", "origin"}:
                                http_origin = value
                            elif key in {"http-cookie", "cookie"}:
                                http_cookie = value
                            elif key in {"http-authorization", "authorization", "auth"}:
                                http_auth = value
                            elif key in {"http-accept", "accept"}:
                                http_accept = value
                            elif key.startswith("http-header"):
                                if value:
                                    http_headers.append(value)
                    continue

                if upper_prefix.startswith("#KODIPROP"):
                    colon_idx = s.find(':')
                    if colon_idx != -1:
                        data = s[colon_idx + 1:]
                        eq_idx = data.find('=')
                        if eq_idx != -1:
                            key = data[:eq_idx].strip().lower()
                            value = data[eq_idx + 1:].strip()
                            if key.endswith("catchup_days"):
                                catchup_days = value
                            elif key.endswith("catchup_source"):
                                catchup_source = value
                            elif key in {"http-referrer", "http-referer", "referer", "referrer"}:
                                http_referrer = value
                            elif key in {"http-origin", "origin"}:
                                http_origin = value
                            elif key in {"http-cookie", "cookie"}:
                                http_cookie = value
                            elif key in {"http-authorization", "authorization", "auth"}:
                                http_auth = value
                            elif key in {"http-accept", "accept"}:
                                http_accept = value
                    continue

                # Other comment/directive lines are ignored
                continue

            url = s
            # Channels with no explicit group-title fall to "Uncategorized"
            # (see the `ch.get("group") or "Uncategorized"` grouping below) rather
            # than being bucketed by a country code guessed from the name. That
            # guessing produced confusing giant "us"/"ca" groups that mixed
            # unrelated channels and swept in malformed entries.
            grp_value = group
            channel = {
                "name": name,
                "group": grp_value,
                "url": url,
                "tvg-id": tvg_id,
                "tvg-name": tvg_name,
            }
            if provider_id:
                channel["provider-id"] = provider_id
            if provider_type:
                channel["provider-type"] = provider_type
            if tvg_rec:
                channel["tvg-rec"] = tvg_rec
            if media_hint:
                channel["media_hint"] = media_hint
            if timeshift:
                channel["timeshift"] = timeshift
            if catchup:
                channel["catchup"] = catchup
            if catchup_type:
                channel["catchup-type"] = catchup_type
            if catchup_days:
                channel["catchup-days"] = catchup_days
            if catchup_source:
                channel["catchup-source"] = catchup_source
            if catchup_offset:
                channel["catchup-offset"] = catchup_offset
            # Dispatcharr advertises its own catch-up clock in the header
            # (catchup-timezone, an attribute it introduced) and no other
            # server is known to send it, so the whole playlist is marked as
            # coming from its restreamer: the player adds no buffer on top of
            # what Dispatcharr already holds.
            if catchup_timezone:
                channel["dispatcharr"] = True
                if catchup or catchup_source:
                    channel["catchup-timezone"] = catchup_timezone
            if http_user_agent:
                channel["http-user-agent"] = http_user_agent
            if http_referrer:
                channel["http-referrer"] = http_referrer
            if http_origin:
                channel["http-origin"] = http_origin
            if http_cookie:
                channel["http-cookie"] = http_cookie
            if http_auth:
                channel["http-authorization"] = http_auth
            if http_accept:
                channel["http-accept"] = http_accept
            if http_headers:
                # Preserve header order but drop duplicates case-insensitively.
                seen_headers = set()
                unique_headers: List[str] = []
                for hdr in http_headers:
                    key_lower = hdr.split(":", 1)[0].strip().lower() if ":" in hdr else hdr.lower()
                    if key_lower in seen_headers:
                        continue
                    seen_headers.add(key_lower)
                    unique_headers.append(hdr)
                channel["http-headers"] = unique_headers

            if provider_type == "xtream" or catchup_source:
                stream_id = stream_id_for(url)
                if stream_id:
                    channel["stream-id"] = stream_id

            append(channel)

            # Clear state after emitting the channel entry
            name = ""
            group = ""
            tvg_id = ""
            tvg_name = ""
            tvg_rec = ""
            media_hint = ""
            timeshift = ""
            catchup = ""
            catchup_type = ""
            catchup_days = ""
            catchup_source = ""
            catchup_offset = ""
            http_user_agent = ""
            http_referrer = ""
            http_origin = ""
            http_cookie = ""
            http_headers = []
            http_auth = ""
            http_accept = ""

        return out

    def _playlist_text_hash(self, text: str) -> str:
        if not text:
            return ""
        # The parsed-playlist cache is keyed by this hash, so the parser
        # version is part of it: a parser change must not be hidden behind
        # channels cached by an older build from the same playlist text.
        payload = _PARSED_PLAYLIST_CACHE_VERSION + "\n" + text
        return hashlib.sha1(payload.encode("utf-8", "surrogatepass")).hexdigest()

    def _parsed_cache_path_for_key(self, key: str) -> str:
        digest = hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest()
        cache_dir = get_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"parsed_{digest}.json")

    def _read_cached_playlist_file(
        self, cache_path: str
    ) -> Tuple[Optional[str], Optional[List[Dict[str, str]]]]:
        """Raw (hash, channels) read of a parsed-cache JSON file, no hash check/mutation.
        Split out of _load_cached_playlist so callers that already have the parsed
        result (e.g. the playlist-load prefill pass) can share it instead of paying
        for the disk read + JSON decode a second time."""
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            channels = data.get("channels")
            if not isinstance(channels, list):
                return None, None
            return data.get("hash"), channels
        except Exception:
            return None, None

    def _apply_cached_provider_meta(self, channels: List[Dict[str, str]], provider_meta: Optional[Dict[str, str]]) -> None:
        if not provider_meta:
            return
        pid = provider_meta.get("provider-id")
        ptype = provider_meta.get("provider-type")
        if not pid and not ptype:
            return
        for ch in channels:
            if pid:
                ch["provider-id"] = pid
            if ptype:
                ch["provider-type"] = ptype

    def _load_cached_playlist(
        self,
        cache_path: str,
        text_hash: Optional[str],
        provider_meta: Optional[Dict[str, str]] = None,
        skip_hash: bool = False,
    ) -> Optional[List[Dict[str, str]]]:
        try:
            stored_hash, channels = self._read_cached_playlist_file(cache_path)
            if channels is None:
                return None
            if not skip_hash and text_hash is not None and stored_hash != text_hash:
                return None
            self._apply_cached_provider_meta(channels, provider_meta)
            return channels
        except Exception:
            return None

    def _store_cached_playlist_async(
        self,
        cache_path: str,
        text_hash: str,
        channels: List[Dict[str, str]],
        provider_meta: Optional[Dict[str, str]] = None,
    ) -> None:
        """Write the parsed playlist cache on its own thread.

        Writing it is seconds on a big playlist (43 MB of JSON for 257,000
        channels), and the channels must not wait for it: the load worker
        writes it before the channel list is applied, so the list appeared ten
        seconds late.
        """
        threading.Thread(
            target=self._store_cached_playlist,
            args=(cache_path, text_hash, channels),
            kwargs={"provider_meta": provider_meta},
            name="playlist-cache-write",
            daemon=True,
        ).start()

    def _store_cached_playlist(
        self,
        cache_path: str,
        text_hash: str,
        channels: List[Dict[str, str]],
        provider_meta: Optional[Dict[str, str]] = None,
    ) -> None:
        payload = {"hash": text_hash, "channels": channels}
        if provider_meta:
            payload["provider"] = provider_meta
        tmp_path = cache_path + ".tmp"
        try:
            # One writer at a time: two loads can write the same cache, and
            # one truncating the other's file would publish a broken cache.
            with _PLAYLIST_CACHE_WRITE_LOCK:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, separators=(",", ":"))
                os.replace(tmp_path, cache_path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                LOG.debug("IPTVClient._store_cached_playlist: ignored exception", exc_info=True)

    def _extract_stream_id(self, url: str) -> str:
        try:
            path = urllib.parse.urlparse(url).path
        except Exception:
            path = ""
        if not path:
            return ""
        parts = [p for p in path.split("/") if p]
        if not parts:
            return ""
        last = parts[-1]
        m = re.match(r"(\d+)", last)
        if m:
            return m.group(1)
        if len(parts) >= 2:
            m = re.match(r"(\d+)", parts[-2])
            if m:
                return m.group(1)
        return ""
