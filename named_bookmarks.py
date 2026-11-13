"""Explicit, named positions, independent of automatic playback checkpoints."""
import re
import time
import uuid

from i18n import gettext as _
from playback_resume import MAX_MS

LIMIT = 1000
KEY = re.compile(r"[0-9a-f]{64}\Z")
IDENTITY = re.compile(r"[0-9a-f]{32}\Z")


def clean_name(value):
    if not isinstance(value, str):
        raise ValueError(_("Enter a bookmark name of 1 to 120 characters."))
    name = value.strip()
    if not 1 <= len(name) <= 120 or any(ord(char) < 32 for char in name):
        raise ValueError(_("Enter a bookmark name of 1 to 120 characters."))
    return name


def normalize(value):
    result = {}
    if not isinstance(value, dict):
        return result
    count = 0
    for key, entries in value.items():
        if not isinstance(key, str) or not KEY.fullmatch(key) or not isinstance(entries, list):
            continue
        rows, seen = [], set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            identity, position = entry.get("id"), entry.get("position_ms")
            if (not isinstance(identity, str) or not IDENTITY.fullmatch(identity) or identity in seen
                    or type(position) is not int or not 0 <= position <= MAX_MS):
                continue
            try:
                name = clean_name(entry.get("name"))
            except ValueError:
                continue
            seen.add(identity)
            rows.append({"id": identity, "name": name, "position_ms": position})
            count += 1
            if count >= LIMIT:
                break
        if rows:
            result[key] = sorted(rows, key=lambda row: (row["position_ms"], row["id"]))
        if count >= LIMIT:
            break
    return result


def put(value, key, name, position, *, identity=None):
    result = normalize(value)
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError(_("This command is available during on-demand playback."))
    name = clean_name(name)
    if type(position) is not int or not 0 <= position <= MAX_MS:
        raise ValueError(_("The playback position is not available yet."))
    rows = result.get(key, [])
    if identity is not None and not any(row["id"] == identity for row in rows):
        raise ValueError(_("The bookmark is no longer available. Reopen the list."))
    if any(row["name"].casefold() == name.casefold() and row["id"] != identity for row in rows):
        raise ValueError(_("A bookmark with this name already exists for this item."))
    if identity is None and sum(map(len, result.values())) >= LIMIT:
        raise ValueError(_("The bookmark limit has been reached. Delete an unused bookmark first."))
    identity = identity or uuid.uuid4().hex
    result[key] = [row for row in rows if row["id"] != identity] + [
        {"id": identity, "name": name, "position_ms": position}]
    return normalize(result)


def remove(value, key, identity):
    result = normalize(value)
    result[key] = [row for row in result.get(key, []) if row["id"] != identity]
    return normalize(result)


def notification(history, caption, message, *, now=None):
    """A bounded session history, with obvious credentials removed at entry."""
    from diagnostic_privacy import sharing_excerpt
    stamp = time.time() if now is None else now
    entry = {"time": stamp, "caption": sharing_excerpt(str(caption))[:240],
             "message": sharing_excerpt(str(message))[:16000]}
    return (list(history or ()) + [entry])[-200:]
