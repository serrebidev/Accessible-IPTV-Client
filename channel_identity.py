"""Which guide channel is this playlist channel?

One rule for every matcher in the app: a playlist channel and a guide
channel are the same channel when their names say so, and never when their
numbers say otherwise. "BBC 2" must not land on the guide's "BBC 3" just
because the noise stripped names of both are "bbc".

The name vocabulary itself lives in channel_names.py; this module owns the
matching policy. It is free of wx, so the matchers can be tested without
the app.
"""

import re
from typing import Dict, List, NamedTuple, Optional, Set

from channel_names import (canonicalize_name, numbers_disagree,
                           replace_word_numbers, significant_channel_numbers,
                           strip_noise_words)


def expand_tvg_id_candidates(tvg_id: str) -> List[str]:
    """Expand common XMLTV id variants such as IPTV-org channel.au@City."""
    raw = (tvg_id or "").strip()
    if not raw:
        return []
    candidates: List[str] = []
    seen: Set[str] = set()

    def add(value: str):
        value = (value or "").strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            candidates.append(value)

    add(raw)
    base, sep, suffix = raw.partition("@")
    base_for_variants = base or raw

    def add_base_variants(value: str):
        m = re.match(r'^(.+)\.([A-Za-z]{2,3}\d*)$', value or "")
        if not m:
            return
        name_part, region_part = m.groups()
        lowered_name = name_part.lower()
        for quality in ("fhd", "uhd", "hd", "sd", "4k", "8k"):
            if lowered_name.endswith(quality) and len(name_part) > len(quality):
                add(f"{name_part[:-len(quality)]}.{region_part}")
                break
        if lowered_name.endswith("sport"):
            add(f"{name_part}s.{region_part}")

    add_base_variants(base_for_variants)
    if sep and base:
        add(base)
        add_base_variants(base)
        suffix_clean = re.sub(r'[^A-Za-z0-9]+', '', suffix or "")
        if suffix_clean and suffix_clean.lower() not in {"sd", "hd", "fhd", "uhd", "4k", "8k"}:
            m = re.match(r'^(.+)\.([A-Za-z]{2,3}\d*)$', base)
            if m:
                name_part, region_part = m.groups()
                add(f"{name_part}{suffix_clean}.{region_part}")
    return candidates


class GuideIndexes(NamedTuple):
    """The guide's channels, indexed the way the matcher looks them up.

    The two name indexes keep every channel that answers to a key, in the
    guide's own order, so a name that answers to several channels can be
    asked for the one whose number agrees.
    """
    by_id: Dict[str, Dict[str, object]]
    by_id_lower: Dict[str, str]
    name_index: Dict[str, List[str]]
    stripped_index: Dict[str, List[str]]
    source_ids: Optional[Dict[str, List[str]]] = None
    collision_cache: Optional[dict] = None


def xmltv_id(identity):
    """Undo only the application's own source qualifier, not an XMLTV suffix."""
    match = re.fullmatch(r"epg:[0-9a-f]{40}:(.*)", str(identity))
    return match[1] if match else str(identity)


def choose_source_collision(channel, names):
    """An unscoped duplicate id requires one exact, number-safe display name."""
    wanted = {canonicalize_name(replace_word_numbers(str(channel.get(field) or "")))
              for field in ("name", "tvg-name")}
    wanted.discard("")
    numbers = significant_channel_numbers(str(channel.get("name") or ""), str(channel.get("tvg-name") or ""))
    matches = [key for key, name in names.items()
               if canonicalize_name(replace_word_numbers(name or "")) in wanted
               and not numbers_disagree(numbers, significant_channel_numbers(name or ""))]
    return matches[0] if len(matches) == 1 else None


def guide_indexes(channels: Dict[str, Dict[str, object]]) -> GuideIndexes:
    """Index the guide's channels by id, by name and by noise stripped name.

    Names are indexed both as written and with their word numbers as digits,
    because a guide may spell out "BBC Two" where the playlist says "BBC 2".
    """
    by_id_lower = {str(cid).lower(): cid for cid in channels}
    source_ids = {}
    name_index: Dict[str, List[str]] = {}
    stripped_index: Dict[str, List[str]] = {}
    for channel_id, entry in channels.items():
        source_ids.setdefault(xmltv_id(channel_id).lower(), []).append(channel_id)
        display = str(entry.get("display_name") or "")
        for key, index in (
            (canonicalize_name(display), name_index),
            (canonicalize_name(strip_noise_words(display)), stripped_index),
            (canonicalize_name(replace_word_numbers(display)), name_index),
            (canonicalize_name(strip_noise_words(replace_word_numbers(display))),
             stripped_index),
        ):
            if key:
                bucket = index.setdefault(key, [])
                if channel_id not in bucket:
                    bucket.append(channel_id)
    return GuideIndexes(channels, by_id_lower, name_index, stripped_index, source_ids, {})


def match_guide_channel(channel, indexes: GuideIndexes,
                        known_ids=None) -> Optional[Dict[str, object]]:
    """The guide entry for a playlist channel, or None.

    1) tvg-id, including the common XMLTV id variants, case-insensitive
    and tolerant of one extra dotted segment ("chan.tv" vs "chan"). An id is
    the channel's identity, not its name, so no number check applies.
    2) names: exact normalized, then noise-stripped, for the channel
    name and then the tvg-name, with word numbers read as digits.

    ``known_ids`` holds every guide channel id (lower case), including
    ones with nothing on air right now. A channel whose tvg-id is among
    them has a guide of its own, so when that guide is empty at the
    moment it gets no label rather than a namesake's: the noise-stripped
    name of "48 Hours" is "hours", which matched an unrelated channel.

    Numbers are read from the names only. Noise stripping turns "BBC 2" and
    "BBC 3" into the same key "bbc", so the number the name still carries is
    what keeps them apart; a number in an id is a database key and would
    only mask the name's disagreement.
    """
    import channel_preferences
    override = channel_preferences.epg_id(channel)
    if override:
        return indexes.by_id.get(override)
    raw_id = str(channel.get("tvg-id") or "").strip()
    scoped = (indexes.source_ids or {}).get(raw_id.lower(), [])
    cache = indexes.collision_cache if indexes.collision_cache is not None else {}
    if cache.get("known_ids") is not known_ids:
        counts = {}
        for identity in known_ids or ():
            original = xmltv_id(identity).lower()
            counts[original] = counts.get(original, 0) + 1
        cache.update(known_ids=known_ids, collisions={key for key, count in counts.items() if count > 1})
    if len(scoped) > 1 or raw_id.lower() in cache.get("collisions", ()):
        key = choose_source_collision(channel, {identity: str(indexes.by_id[identity].get("display_name") or "")
                                                for identity in scoped})
        return indexes.by_id.get(key)
    if len(scoped) == 1 and xmltv_id(scoped[0]) != scoped[0]:
        return indexes.by_id[scoped[0]]
    candidates = expand_tvg_id_candidates(raw_id)
    candidates.append(raw_id)
    if "." in raw_id:
        candidates.append(raw_id.rsplit(".", 1)[0])
    for candidate in candidates:
        channel_id = indexes.by_id_lower.get(candidate.strip().lower())
        if channel_id is not None:
            return indexes.by_id[channel_id]
    if known_ids and any(c.strip().lower() in known_ids for c in candidates if c.strip()):
        return None
    playlist_numbers = significant_channel_numbers(
        str(channel.get("tvg-name") or ""),
        str(channel.get("name") or ""))
    for source in (channel.get("name"), channel.get("tvg-name")):
        text = str(source or "").strip()
        if not text:
            continue
        spelled = replace_word_numbers(text)
        for key, index in (
            (canonicalize_name(text), indexes.name_index),
            (canonicalize_name(spelled), indexes.name_index),
            (canonicalize_name(strip_noise_words(text)), indexes.stripped_index),
            (canonicalize_name(strip_noise_words(spelled)), indexes.stripped_index),
        ):
            for channel_id in index.get(key, ()):
                entry = indexes.by_id[channel_id]
                if numbers_disagree(playlist_numbers, _guide_numbers(entry)):
                    continue
                return entry
    return None


def _guide_numbers(entry) -> frozenset:
    """The numbers a guide channel's name carries."""
    return significant_channel_numbers(str(entry.get("display_name") or ""))
