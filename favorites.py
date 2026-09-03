"""Favorite channels for Accessible IPTV Client.

GUI-free so the identity rules can be tested headlessly. The GUI keeps the set of
favorite keys in ``iptvclient.conf`` under ``favorites`` and asks this module which
playlist entries those keys refer to.

The key has to survive a playlist reload, and that rules out the resolved stream URL:
Xtream and Stalker hand out a fresh, credential-bearing URL every time a channel is
resolved, and those URLs must not be written into the config file either. So the key is
built from the identifying metadata a provider does keep stable across refreshes --
provider type/id, the numeric stream id, the XMLTV id -- and falls back to the display
name for plain M3U playlists that carry nothing else. Two entries with the same name in
different categories therefore share one favorite, which is what a user marking "BBC
One" means anyway.

The public functions take ``object`` rather than a channel type on purpose: they are
fed both playlist entries and whatever a hand-edited config file happened to contain,
and junk has to come back as "no key" instead of an exception.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Set, Tuple, TypeVar

# Sentinel category key, handled like the existing "All Channels" one: stored and
# compared in English, translated only where it is displayed.
FAVORITES_GROUP = "Favorites"

ChannelT = TypeVar("ChannelT")


def display_name(channel: object) -> str:
    """The name a channel is listed under (same precedence as the channel list)."""
    if not isinstance(channel, dict):
        return ""
    for field in ("name", "tvg-name", "tvg_name", "tvg-id", "tvg_id"):
        value = channel.get(field)
        if value:
            return str(value).strip()
    return ""


def channel_key(channel: object) -> str:
    """Stable identity for a channel, or "" when there is nothing to key on."""
    if not isinstance(channel, dict):
        return ""
    parts = [
        channel.get("provider-type"),
        channel.get("provider-id"),
        channel.get("stream-id") or channel.get("stream_id"),
        channel.get("tvg-id") or channel.get("tvg_id"),
        display_name(channel),
    ]
    cleaned = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    return "|".join(cleaned)


def normalize(values: Optional[Iterable[object]]) -> List[str]:
    """Coerce a stored ``favorites`` value into an ordered, duplicate-free key list."""
    if not values or isinstance(values, (str, bytes)):
        return []
    out: List[str] = []
    seen: Set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        key = value.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def filter_channels(channels: Sequence[ChannelT], keys: Iterable[str]) -> List[ChannelT]:
    """The favorited channels, in playlist order.

    Playlist order rather than the order they were favorited in: the list is rebuilt
    from the playlist on every load, and a stable, predictable order matters more for
    keyboard navigation than remembering when each channel was starred.
    """
    wanted = {key for key in keys if key}
    if not wanted or not channels:
        return []
    return [ch for ch in channels if channel_key(ch) in wanted]


def toggle(keys: Iterable[str], channel: object) -> Tuple[List[str], bool]:
    """Add or remove ``channel``. Returns (new key list, whether it is now a favorite)."""
    key = channel_key(channel)
    current = normalize(keys)
    if not key:
        return current, False
    if key in current:
        return [existing for existing in current if existing != key], False
    return current + [key], True
