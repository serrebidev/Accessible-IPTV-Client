"""Video-on-demand (movies & series) catalogue building for Accessible IPTV Client.

Two content sources are supported:

* **Xtream providers** — the ``player_api.php`` JSON endpoints expose movies and
  series as a proper browsable catalogue with categories. Series episodes are
  loaded lazily per series (:func:`xtream_series_episodes`) so we never
  enumerate every episode of every show up front.
* **Plain M3U / m3u_plus playlists** — there is no structured VOD API, so we
  apply a conservative heuristic that splits movies and series out of the flat
  channel list using ``group-title`` hints and ``SxxExx`` episode naming.

Everything is returned as plain ``dict`` items so movie and episode entries can
flow through the existing channel-list and playback code unchanged. Series
episodes are ordered by season then episode so they can be streamed in order.

A catalogue is a pair ``(group_order, groups)`` where ``group_order`` is a list
of category labels (in display order) and ``groups`` maps each label to a list
of raw item dicts. Raw items are one of:

* movie  — ``{"kind": "movie", "name", "url", "group", ...}`` (plays directly)
* series — ``{"kind": "series", "name", "group", ...loader info...}``

Series loader info differs by source: M3U series carry their episodes inline
under ``"episodes"``; Xtream series carry ``"series_id"`` / ``"provider-id"`` so
episodes can be fetched on demand.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from i18n import gettext as _
import logging

LOG = logging.getLogger(__name__)

KIND_MOVIE = "movie"
KIND_SERIES = "series"

# Season/episode patterns, most specific first. "S01E02", "S1 E2", "1x05".
_SE_RE = re.compile(r"[sS](\d{1,3})[\s._x-]*[eE](\d{1,3})")
_SE_ALT_RE = re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,3})(?!\d)")
_EP_ONLY_RE = re.compile(r"\b[eE]p(?:isode)?[\s._-]*(\d{1,3})(?!\d)")

# group-title keywords that mark a bucket as movies or series.
_SERIES_HINTS = ("series", "tv show", "tv shows", "shows", "sezon", "season")
_MOVIE_HINTS = ("vod", "movie", "movies", "film", "films", "cinema", "peli")


def parse_season_episode(name: str) -> Optional[Tuple[int, int]]:
    """Return ``(season, episode)`` parsed from *name*, or ``None``.

    An episode-only match (e.g. "Episode 5") is reported as season 0.
    """
    if not name:
        return None
    m = _SE_RE.search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _SE_ALT_RE.search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _EP_ONLY_RE.search(name)
    if m:
        return 0, int(m.group(1))
    return None


def _series_title(name: str) -> str:
    """Strip a trailing SxxExx marker (and following episode title) to get the show title."""
    if not name:
        return name
    # Cut at the first season/episode marker so "Breaking Bad S01E02 - Pilot"
    # collapses to "Breaking Bad".
    for rx in (_SE_RE, _SE_ALT_RE, _EP_ONLY_RE):
        m = rx.search(name)
        if m:
            head = name[: m.start()].strip(" -_.|:")
            if head:
                return head
    return name.strip(" -_.|:")


def _sort_episodes(episodes: List[Dict]) -> List[Dict]:
    """Order episode dicts by (season, episode); untagged episodes keep insertion order last."""
    def key(item):
        se = item.get("_se")
        if not se:
            return (10 ** 6, item.get("_order", 0))
        return (se[0], se[1])

    for i, ep in enumerate(episodes):
        ep.setdefault("_order", i)
    return sorted(episodes, key=key)


def _add(group_order: List[str], groups: Dict[str, List[Dict]], label: str, item: Dict) -> None:
    bucket = groups.get(label)
    if bucket is None:
        bucket = []
        groups[label] = bucket
        group_order.append(label)
    bucket.append(item)


# --------------------------------------------------------------------------- #
# Plain M3U heuristic (source #2)
# --------------------------------------------------------------------------- #
def _flat_item(ch: Dict, category: str) -> Dict:
    """A directly-playable VOD entry (movie, or a single-stream '24/7 show')."""
    item = dict(ch)
    item["kind"] = KIND_MOVIE
    item["group"] = category
    return item


def categorize_m3u_vod(channels: List[Dict]) -> Tuple[List[str], Dict[str, List[Dict]]]:
    """Split movies and series out of a flat channel list using group-title hints.

    Conservative on purpose — plain M3U has no VOD API, so mistakes are easy:

    * An entry is considered VOD **only** when its ``group-title`` explicitly
      names movies or series. Name-only ``SxxExx`` guessing is not enough (real
      providers tag the group, and blind matching swept in malformed entries —
      e.g. a base64 logo blob pasted as a channel name).
    * A drill-in **series folder** is created only for a genuinely episodic show:
      two or more episodes carrying two or more distinct ``SxxExx`` markers.
      Everything else (movies, and single-stream "24/7 <Show>" channels) is a
      flat, directly-playable item under its category — no pointless one-item
      folders.

    Category labels are the provider's own ``group-title`` verbatim, so the
    listing reads the way the provider organised it.
    """
    group_order: List[str] = []
    groups: Dict[str, List[Dict]] = {}

    # First pass: bucket candidates by category, splitting movie vs series hint.
    order: List[str] = []
    movie_by_cat: Dict[str, List[Dict]] = {}
    # category -> show_title_lower -> [(se, channel), ...]
    series_by_cat: Dict[str, Dict[str, List[Tuple[Optional[Tuple[int, int]], Dict]]]] = {}
    show_display: Dict[Tuple[str, str], str] = {}

    def note_category(cat: str):
        if cat not in movie_by_cat and cat not in series_by_cat and cat not in order:
            order.append(cat)

    for ch in channels:
        name = (ch.get("name") or ch.get("tvg-name") or ch.get("tvg_name") or "").strip()
        if not name:
            continue
        category = (ch.get("group") or "").strip()
        gl = category.lower()
        is_series = any(h in gl for h in _SERIES_HINTS)
        is_movie = any(h in gl for h in _MOVIE_HINTS)
        if not (is_series or is_movie):
            continue  # require an explicit group-title hint — no blind guessing

        note_category(category)
        if is_series and not is_movie:
            show = _series_title(name)
            key = show.lower()
            bucket = series_by_cat.setdefault(category, {}).setdefault(key, [])
            bucket.append((parse_season_episode(name), ch))
            show_display.setdefault((category, key), show)
        else:
            movie_by_cat.setdefault(category, []).append(_flat_item(ch, category))

    seen_urls: Dict[str, set] = {}

    def add_flat(category: str, item: Dict):
        # Collapse duplicate listings of the same stream within a category.
        url = item.get("url", "")
        urls = seen_urls.setdefault(category, set())
        if url and url in urls:
            return
        if url:
            urls.add(url)
        _add(group_order, groups, category, item)

    for category in order:
        for key, entries in series_by_cat.get(category, {}).items():
            markers = [se for se, _ in entries if se]
            if len(entries) >= 2 and len(set(markers)) >= 2:
                # Genuinely episodic: a browsable series folder.
                episodes = []
                for se, ch in entries:
                    ep = dict(ch)
                    ep["_se"] = se
                    episodes.append(ep)
                series = {
                    "kind": KIND_SERIES,
                    "name": show_display.get((category, key), key),
                    "group": category,
                    "episodes": _sort_episodes(episodes),
                }
                _add(group_order, groups, category, series)
            else:
                # Not a real series — flat playable item(s).
                for _se, ch in entries:
                    add_flat(category, _flat_item(ch, category))
        for item in movie_by_cat.get(category, []):
            add_flat(category, item)

    return group_order, groups


# --------------------------------------------------------------------------- #
# Xtream player_api catalogue (source #1)
# --------------------------------------------------------------------------- #
def _category_map(rows: List[Dict]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in rows:
        cid = row.get("category_id")
        if cid is None:
            continue
        out[str(cid)] = row.get("category_name") or _("Uncategorized")
    return out


def build_xtream_catalog(client, provider_id: Optional[str]) -> Tuple[List[str], Dict[str, List[Dict]]]:
    """Build a movie + series catalogue for one Xtream provider via player_api.

    Network-heavy: issues a handful of JSON requests. Call from a worker thread.
    Series episodes are *not* fetched here — only the series list — so this stays
    a bounded number of requests regardless of how many episodes exist.
    """
    group_order: List[str] = []
    groups: Dict[str, List[Dict]] = {}

    # Movies.
    try:
        vod_cats = _category_map(client.get_vod_categories())
        for s in client.get_vod_streams():
            sid = s.get("stream_id")
            if sid is None:
                continue
            category = vod_cats.get(str(s.get("category_id")), _("Movies"))
            ext = s.get("container_extension") or "mp4"
            movie = {
                "kind": KIND_MOVIE,
                "name": s.get("name") or s.get("title") or str(sid),
                "url": client.vod_stream_url(sid, ext),
                "group": category,
                "provider-type": "xtream",
                "provider-id": provider_id,
            }
            _add(group_order, groups, _("Movies") + " — " + category, movie)
    except Exception:
        # A provider may not offer VOD; keep whatever we did collect.
        LOG.debug("build_xtream_catalog: ignored exception", exc_info=True)

    # Series (episodes loaded lazily on open).
    try:
        ser_cats = _category_map(client.get_series_categories())
        for s in client.get_series():
            series_id = s.get("series_id")
            if series_id is None:
                continue
            category = ser_cats.get(str(s.get("category_id")), _("Series"))
            series = {
                "kind": KIND_SERIES,
                "name": s.get("name") or s.get("title") or str(series_id),
                "group": category,
                "series_id": series_id,
                "provider-id": provider_id,
                "provider-type": "xtream",
            }
            _add(group_order, groups, _("Series") + " — " + category, series)
    except Exception:
        LOG.debug("build_xtream_catalog: ignored exception", exc_info=True)

    return group_order, groups


def xtream_series_episodes(client, series_id, provider_id: Optional[str]) -> List[Dict]:
    """Fetch and order the episodes of one Xtream series as playable channel dicts."""
    info = client.get_series_info(series_id)
    seasons = info.get("episodes") if isinstance(info, dict) else None
    episodes: List[Dict] = []
    list_form = False
    if isinstance(seasons, dict):
        season_items = seasons.items()
    elif isinstance(seasons, list):
        # Some panels return a list of season arrays instead of a keyed object.
        season_items = enumerate(seasons)
        list_form = True
    else:
        season_items = []
    for season_key, entries in season_items:
        if not isinstance(entries, list):
            continue
        s_no = int(season_key) if str(season_key).isdigit() else 0
        if list_form:
            s_no += 1
        for idx, ep in enumerate(entries):
            if not isinstance(ep, dict):
                continue
            eid = ep.get("id")
            if eid is None:
                continue
            try:
                e_no = int(ep.get("episode_num") or 0)
            except (TypeError, ValueError):
                e_no = 0
            if not e_no:
                e_no = idx + 1
            ext = ep.get("container_extension") or "mp4"
            title = ep.get("title") or _("Episode {num}").format(num=e_no)
            label = "S%02dE%02d - %s" % (s_no, e_no, title)
            episodes.append({
                "kind": KIND_MOVIE,  # a resolved, directly-playable entry
                "name": label,
                "url": client.series_stream_url(eid, ext),
                "provider-type": "xtream",
                "provider-id": provider_id,
                "_se": (s_no, e_no),
            })
    return _sort_episodes(episodes)


def merge_catalogs(catalogs: List[Tuple[List[str], Dict[str, List[Dict]]]]) -> Tuple[List[str], Dict[str, List[Dict]]]:
    """Merge several ``(group_order, groups)`` catalogues into one, preserving order."""
    group_order: List[str] = []
    groups: Dict[str, List[Dict]] = {}
    for order, buckets in catalogs:
        for label in order:
            for item in buckets.get(label, []):
                _add(group_order, groups, label, item)
    return group_order, groups
