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

KIND_MOVIE = "movie"
KIND_SERIES = "series"

# Season/episode patterns, most specific first. "S01E02", "S1 E2", "1x05".
_SE_RE = re.compile(r"[sS](\d{1,3})[\s._x-]*[eE](\d{1,3})")
_SE_ALT_RE = re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,3})(?!\d)")
_EP_ONLY_RE = re.compile(r"[eE]p(?:isode)?[\s._-]*(\d{1,3})(?!\d)")

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
def categorize_m3u_vod(channels: List[Dict]) -> Tuple[List[str], Dict[str, List[Dict]]]:
    """Split movies and series out of a flat channel list using group-title hints.

    Conservative: an entry is treated as VOD only when its ``group-title``
    names movies/series, or its name carries an unmistakable ``SxxExx`` marker.
    Live channels that merely happen to contain a digit are left alone.
    """
    group_order: List[str] = []
    groups: Dict[str, List[Dict]] = {}
    # (category, show_title_lower) -> series dict, so episodes of one show merge.
    series_index: Dict[Tuple[str, str], Dict] = {}

    for ch in channels:
        name = (ch.get("name") or ch.get("tvg-name") or ch.get("tvg_name") or "").strip()
        if not name:
            continue
        group = (ch.get("group") or "").strip()
        gl = group.lower()
        se = parse_season_episode(name)
        is_series = any(h in gl for h in _SERIES_HINTS)
        is_movie = any(h in gl for h in _MOVIE_HINTS)

        if is_series or (se is not None and not is_movie):
            show = _series_title(name)
            category = group or _("Series")
            label = _("Series") + " — " + category
            key = (label, show.lower())
            series = series_index.get(key)
            if series is None:
                series = {
                    "kind": KIND_SERIES,
                    "name": show,
                    "group": category,
                    "episodes": [],
                }
                series_index[key] = series
                _add(group_order, groups, label, series)
            episode = dict(ch)
            episode["_se"] = se
            series["episodes"].append(episode)
        elif is_movie:
            category = group or _("Movies")
            label = _("Movies") + " — " + category
            movie = dict(ch)
            movie["kind"] = KIND_MOVIE
            movie["group"] = category
            _add(group_order, groups, label, movie)

    # Freeze episode ordering now that every episode of each show is collected.
    for series in series_index.values():
        series["episodes"] = _sort_episodes(series["episodes"])

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
        pass

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
        pass

    return group_order, groups


def xtream_series_episodes(client, series_id, provider_id: Optional[str]) -> List[Dict]:
    """Fetch and order the episodes of one Xtream series as playable channel dicts."""
    info = client.get_series_info(series_id)
    seasons = info.get("episodes") if isinstance(info, dict) else None
    episodes: List[Dict] = []
    if isinstance(seasons, dict):
        season_items = seasons.items()
    elif isinstance(seasons, list):
        # Some panels return a list of season arrays instead of a keyed object.
        season_items = enumerate(seasons)
    else:
        season_items = []
    for season_key, entries in season_items:
        if not isinstance(entries, list):
            continue
        s_no = int(season_key) if str(season_key).isdigit() else 0
        for ep in entries:
            if not isinstance(ep, dict):
                continue
            eid = ep.get("id")
            if eid is None:
                continue
            try:
                e_no = int(ep.get("episode_num") or 0)
            except (TypeError, ValueError):
                e_no = 0
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
