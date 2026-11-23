"""Bounded VOD progress with conservative identities and credential-free locators.

Never match by title. Xtream IDs are scoped to the configured account, content
kind and (for episodes) series; unstructured playlists retain exact-URL identity.
Legacy URL hashes migrate only when that exact item is encountered again.
"""
import hashlib
import json
import re
import time

_KEY = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
MAX_MS = 7 * 24 * 60 * 60 * 1000


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def _identifier(value):
    if type(value) not in (int, str):
        return ""
    text = str(value)
    return text if _ID.fullmatch(text) else ""


def source_key(channel):
    source = channel.get("provider-id") or channel.get("playlist-id")
    return _digest(["source", str(source)]) if source else ""


def legacy_key(channel):
    if not isinstance(channel, dict) or channel.get("kind") != "movie" or not channel.get("url"):
        return ""
    return _digest([str(channel.get(field) or "") for field in ("provider-id", "url")])


def locator(channel):
    if not isinstance(channel, dict) or channel.get("provider-type") != "xtream":
        return {}
    source = source_key(channel)
    content_type = channel.get("resume-type")
    content_id = _identifier(channel.get("resume-id"))
    if not source or not content_id or content_type not in ("movie", "episode"):
        return {}
    result = {"source": source, "type": content_type, "id": content_id}
    if content_type == "episode":
        series = _identifier(channel.get("series_id"))
        if not series:
            return {}
        result["series"] = series
    return result


def item_key(channel):
    old = legacy_key(channel)
    if not old:
        return ""
    stable = locator(channel)
    if stable:
        return _digest(["xtream-v2", stable])
    # Account/playlist scoping matters even for identical stream URLs.
    if channel.get("playlist-id") and not channel.get("provider-id"):
        return _digest(["playlist-v2", source_key(channel), str(channel["url"])])
    return old


def clean_metadata(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    title = value.get("title")
    # Provider text can itself contain credentials/URLs: don't persist it.
    if isinstance(title, str) and title.strip() and not re.search(r"://|www\.|[\r\n\x00-\x1f]", title, re.I):
        result["title"] = title.strip()[:240]
    loc = value.get("locator")
    if isinstance(loc, dict) and _KEY.fullmatch(str(loc.get("source", ""))):
        kind, identity = loc.get("type"), _identifier(loc.get("id"))
        if identity and kind in ("movie", "episode"):
            safe = {"source": loc["source"], "type": kind, "id": identity}
            if kind == "episode":
                series = _identifier(loc.get("series"))
                if not series:
                    return result
                safe["series"] = series
            result["locator"] = safe
    return result


def metadata(channel):
    if not isinstance(channel, dict):
        return {}
    return clean_metadata({"title": channel.get("name") or "", "locator": locator(channel)})


def normalize(entries):
    if not isinstance(entries, dict):
        return {}
    result = {}
    for key, value in entries.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key) or not isinstance(value, dict):
            continue
        position, length, updated = (value.get(name) for name in ("position_ms", "length_ms", "updated"))
        if not all(type(n) is int for n in (position, length, updated)):
            continue
        if not 30_000 <= position < length <= MAX_MS or not 0 <= updated <= 2**63 - 1:
            continue
        if length - position <= max(30_000, length // 20):
            continue
        result[key] = {"position_ms": position, "length_ms": length, "updated": updated}
        info = clean_metadata(value.get("metadata"))
        if info:
            result[key]["metadata"] = info
    return dict(sorted(result.items(), key=lambda pair: (-pair[1]["updated"], pair[0]))[:200])


def lookup(entries, channel):
    """Return normalized/migrated entries and key, without mutating the caller."""
    result = normalize(entries)
    key, old = item_key(channel), legacy_key(channel)
    # A legacy record from an unscoped M3U cannot safely be assigned to one of
    # multiple playlists. Preserve it rather than guessing an account.
    can_migrate = bool(channel and channel.get("provider-id")) or key == old
    if key and old != key and old in result and can_migrate:
        prior = result.pop(old)
        if key not in result or prior["updated"] > result[key]["updated"]:
            result[key] = prior
    if key in result:
        info = metadata(channel)
        if info:
            result[key]["metadata"] = info
    return normalize(result), key


def checkpoint(entries, key, position, length, *, now=None, info=None):
    result = normalize(entries)
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        return result
    if type(position) is not int or type(length) is not int or not 0 <= position <= length <= MAX_MS:
        return result
    if length == 0:
        return result
    if position < 30_000 or length - position <= max(30_000, length // 20):
        result.pop(key, None)
    else:
        stamp = int(time.time()) if now is None else now
        if type(stamp) is not int or not 0 <= stamp <= 2**63 - 1:
            return result
        record = {"position_ms": position, "length_ms": length, "updated": stamp}
        detail = clean_metadata(info) if info is not None else result.get(key, {}).get("metadata", {})
        if detail:
            record["metadata"] = detail
        result[key] = record
    return normalize(result)


def playable_items(groups):
    """Yield direct entries and inline M3U episodes; never fetch all series."""
    for items in groups.values():
        for item in items:
            if item.get("kind") == "series":
                yield from item.get("episodes", [])
            else:
                yield item


def find_current(key, entries, items):
    """Require one unambiguous current item, not a title or URL approximation."""
    matches = {}
    for item in items:
        new = item_key(item)
        legacy = legacy_key(item)
        if new == key or (legacy == key and (new == legacy or item.get("provider-id"))):
            # Identical duplicate catalogue rows are harmless; differing sources
            # or URLs with the same ID are ambiguous and must not play at random.
            identity = (new, str(item.get("url", "")))
            matches[identity] = item
    return next(iter(matches.values())) if len(matches) == 1 else None


def resolve_current(key, entries, channels, clients):
    """Worker-only resolution through current catalogues; no saved stream URLs.

    None = unavailable/ambiguous. Provider errors propagate so the UI can say
    'could not check' instead of falsely declaring the content removed.
    """
    import vod
    records = normalize(entries)
    if key not in records:
        return None
    info = records[key].get("metadata", {}).get("locator", {})
    if info:
        providers = [(pid, c) for pid, c in clients.items()
                     if source_key({"provider-id": pid}) == info["source"]]
        if len(providers) != 1:
            return None
        pid, client = providers[0]
        if info["type"] == "episode":
            items = vod.xtream_series_episodes(client, info["series"], pid, strict=True)
        else:
            # Don't swallow API errors as build_xtream_catalog does: a failed
            # check is different from a provider-confirmed missing movie.
            items = vod.xtream_movie_items(client, pid)
        return find_current(key, records, items)
    # The GUI supplies a reusable iterator factory. Provider lookups above
    # never need the potentially large local catalogue.
    items = channels if callable(channels) else lambda: iter(channels)
    _, groups = vod.categorize_m3u_vod(items())
    local = list(playable_items(groups))
    local.extend(item for item in items() if item.get("kind") == "movie")
    known = find_current(key, records, local)
    if known is not None:
        return known
    # Legacy Xtream URL hashes have no locator. Exact URL re-identification is
    # possible for movies; do not enumerate every episode of every series.
    for pid, client in clients.items():
        local.extend(vod.xtream_movie_items(client, pid))
    return find_current(key, records, local)
