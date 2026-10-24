"""#EXTM3U header parsing: guide URLs and the EXTINF name separator.

Playlist text is parsed in main.py; these three helpers are the pieces of that
parse that other modules (refresh, cache, EPG source discovery) also need, so
they live here rather than in the UI module.
"""
import re
from typing import List

_M3U_ATTR_RE = re.compile(r'([A-Za-z0-9_\-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^",\s]+))')

# #EXTM3U header attributes that name the playlist's own XMLTV guide.
_PLAYLIST_EPG_ATTRS = ("x-tvg-url", "url-tvg")


def _playlist_header_epg_urls(text: str) -> List[str]:
    """Guide URLs a playlist advertises in its #EXTM3U header.

    ``x-tvg-url`` (and its older alias ``url-tvg``) may list several guides
    separated by commas. Only http(s) URLs are used: a header cannot be
    allowed to point the importer at a file on the user's computer. Only the
    first line is read, so a 12 MB playlist is not split for this.
    """
    if not text:
        return []
    head = text.lstrip("\ufeff \t\r\n")
    end = head.find("\n")
    first = (head if end == -1 else head[:end]).strip()
    if not first[:7].upper() == "#EXTM3U":
        return []
    urls: List[str] = []
    for match in _M3U_ATTR_RE.finditer(first[7:]):
        if match.group(1).lower() not in _PLAYLIST_EPG_ATTRS:
            continue
        value = match.group(2) or match.group(3) or ""
        if match.group(4):
            # _M3U_ATTR_RE ends an unquoted value at a comma, but an unquoted
            # guide list (x-tvg-url=https://a/1.xml,https://b/2.xml) runs to
            # the next whitespace.
            value = re.match(r"\S*", match.string[match.start(4):]).group(0)
        for part in value.split(","):
            url = part.strip()
            scheme, sep, rest = url.partition("://")
            if not sep or scheme.lower() not in ("http", "https"):
                continue
            # The importer recognises only lowercase schemes; "HTTP://..."
            # would otherwise be opened as a local file path and fail.
            url = f"{scheme.lower()}://{rest}"
            if url not in urls:
                urls.append(url)
    return urls


def _merge_playlist_header_guides(previous, fetched, playlist_sources):
    """(guides per playlist, flat guide list) after a playlist load.

    A playlist read in this load replaces its own entry, also with an empty
    list when its header dropped the guide; one kept from the previous load
    in a partial refresh keeps its entry; a playlist no longer configured
    loses it.
    """
    merged = dict(previous)
    merged.update(fetched)
    by_source = {src: list(guides) for src, guides in merged.items() if src in playlist_sources}
    flat: List[str] = []
    for guides in by_source.values():
        for epg in guides:
            if epg not in flat:
                flat.append(epg)
    return by_source, flat


def _extinf_name_comma(line: str) -> int:
    """Index of the comma separating an #EXTINF's attributes from its name.

    The separator is the first comma *outside* a quoted attribute value. Real
    playlists ship values that contain commas — iptv-org, for one, emits
    http-user-agent="Mozilla/5.0 (... (KHTML, like Gecko) Chrome/145 ..." — and
    splitting on the first raw comma made the rest of the attribute list the
    channel name while truncating the attributes themselves, losing the
    channel's group and headers with it.

    Returns -1 when the line holds no comma, and falls back to the first raw
    comma when quoting is unbalanced, which is what a malformed line used to get.
    """
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in ('"', "'"):
            quote = char
        elif char == ",":
            return index
    return line.find(",")
