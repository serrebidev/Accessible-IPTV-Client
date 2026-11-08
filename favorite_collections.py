"""Named, ordered favourites, independent of the existing default favourites."""
import copy
import re
import uuid

import programme_reminders
from i18n import gettext as _

MAX_LISTS = 50
MAX_CHANNELS = 2000


def clean_name(value):
    text = str(value or "").strip()
    if not text or len(text) > 80 or any(ord(c) < 32 for c in text):
        raise ValueError(_("Enter a name of 1 to 80 characters."))
    return text


def normalize(value):
    if not isinstance(value, list):
        return []
    output, ids, names = [], set(), set()
    for item in value[:MAX_LISTS]:
        if not isinstance(item, dict) or not re.fullmatch(r"[a-f0-9]{32}", str(item.get("id", ""))):
            continue
        try:
            name = clean_name(item.get("name"))
        except ValueError:
            continue
        if item["id"] in ids or name.casefold() in names:
            continue
        entries, seen = [], set()
        raw = item.get("entries")
        for entry in (raw if isinstance(raw, list) else [])[:MAX_CHANNELS]:
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key) or key in seen:
                continue
            entries.append({"key": key, "name": programme_reminders.safe_title(entry.get("name"))})
            seen.add(key)
        ids.add(item["id"])
        names.add(name.casefold())
        output.append({"id": item["id"], "name": name, "entries": entries})
    return output


def create(collections, name):
    rows = normalize(collections)
    if len(rows) >= MAX_LISTS:
        raise ValueError(_("The maximum number of favourite lists is 50."))
    name = clean_name(name)
    if any(row["name"].casefold() == name.casefold() for row in rows):
        raise ValueError(_("A list with this name already exists."))
    row = {"id": uuid.uuid4().hex, "name": name, "entries": []}
    return rows + [row], row["id"]


def edit(collections, identity, *, name=None, add=None, remove=None, move=None, delete=False):
    rows = normalize(collections)
    row = next((r for r in rows if r["id"] == identity), None)
    if row is None:
        raise ValueError(_("The selected list no longer exists."))
    if delete:
        return [r for r in rows if r["id"] != identity]
    if name is not None:
        name = clean_name(name)
        if any(r["id"] != identity and r["name"].casefold() == name.casefold() for r in rows):
            raise ValueError(_("A list with this name already exists."))
        row["name"] = name
    if add is not None:
        key = programme_reminders.channel_key(add)
        if not key:
            raise ValueError(_("Channel Not Found"))
        if not any(entry["key"] == key for entry in row["entries"]):
            if len(row["entries"]) >= MAX_CHANNELS:
                raise ValueError(_("A favourite list can contain at most 2000 channels."))
            row["entries"].append({"key": key, "name": programme_reminders.safe_title(add.get("name"))})
    if remove is not None:
        row["entries"] = [e for e in row["entries"] if e["key"] != remove]
    if move is not None:
        key, delta = move
        if delta not in (-1, 1):
            raise ValueError("Invalid list movement")
        index = next((i for i, e in enumerate(row["entries"]) if e["key"] == key), -1)
        if index >= 0 and 0 <= index + delta < len(row["entries"]):
            row["entries"][index], row["entries"][index + delta] = row["entries"][index + delta], row["entries"][index]
    return copy.deepcopy(rows)


def resolve(entries, channels):
    """Preserve missing rows; ambiguous identities cannot start arbitrary media."""
    index = {}
    wanted = {e["key"] for e in entries}
    for channel in channels:
        key = programme_reminders.channel_key(channel)
        if key in wanted:
            index.setdefault(key, []).append(channel)
    return [(entry, programme_reminders.resolve_channel({"channel_key": entry["key"]}, index.get(entry["key"], [])))
            for entry in entries]
