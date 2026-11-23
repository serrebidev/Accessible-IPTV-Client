"""Named, ordered favourites, independent of the existing default favourites."""
import copy
import hashlib
import json
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
            if isinstance(entry.get('guide'), str) and re.fullmatch(r'[a-f0-9]{64}', entry['guide']):
                entries[-1]['guide'] = entry['guide']
            if all(isinstance(entry.get(k), str) and re.fullmatch('[a-f0-9]{64}', entry[k])
                   for k in ('match_key', 'variant')):
                entries[-1].update(match_key=entry['match_key'], variant=entry['variant'])
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


def variant_labels(labels):
    from collections import Counter
    counts = Counter(labels)
    seen = Counter()
    result = []
    for label in labels:
        seen[label] += 1
        if counts[label] > 1:
            label += " — " + _("Variant {number}").format(number=seen[label])
        result.append(label)
    return result


def selected_entry(channel, channels=None):
    key = programme_reminders.channel_key(channel)
    if not key or not channel.get("url"):
        raise ValueError(_("Channel Not Found"))
    entry = {"key": key, "name": programme_reminders.safe_title(channel.get("name"))}
    if channels is not None:
        chosen = programme_reminders.media_identity(channel)
        found = ambiguous = False
        for other in channels:
            if other.get("url") and programme_reminders.channel_key(other) == key:
                if programme_reminders.media_identity(other) == chosen:
                    found = True
                else:
                    ambiguous = True
                if found and ambiguous:
                    break
        if not found:
            raise ValueError(_("The channel list changed. Try again."))
        if ambiguous:
            variant = variant_key(channel)
            entry.update(match_key=key, variant=variant,
                         key=hashlib.sha256((key + variant).encode("ascii")).hexdigest())
    return entry


def edit(collections, identity, *, name=None, add=None, selection=None, remove=None, move=None, delete=False):
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
    if selection is not None or add is not None:
        entry = selection if selection is not None else selected_entry(add)
        if not any(e["key"] == entry["key"] or (entry.get("variant") and
                   (e.get("match_key"), e.get("variant")) == (entry["match_key"], entry["variant"]))
                   for e in row["entries"]):
            if len(row["entries"]) >= MAX_CHANNELS:
                raise ValueError(_("A favourite list can contain at most 2000 channels."))
            row["entries"].append(dict(entry))
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


def relink(collections, identity, old_key, channel, *, selection=None):
    """Replace one stale entry in place, preserving the order of the list."""
    rows = normalize(collections)
    row = next((item for item in rows if item["id"] == identity), None)
    if row is None:
        raise ValueError(_("The selected list no longer exists."))
    entry = next((e for e in row["entries"] if e["key"] == old_key), None)
    if entry is None:
        raise ValueError(_("The channel list changed. Try again."))
    replacement = selection if selection is not None else selected_entry(channel)
    if any(e is not entry and (e["key"] == replacement["key"] or (replacement.get("variant") and
           (e.get("match_key"), e.get("variant")) == (replacement["match_key"], replacement["variant"])))
           for e in row["entries"]):
        raise ValueError(_("Choose a different channel that is not already in this list."))
    entry.clear()
    entry.update(replacement)
    return rows


def variant_key(channel):
    identity = programme_reminders.media_identity(channel)
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def resolve(entries, channels):
    """Preserve missing rows; ambiguous identities cannot start arbitrary media."""
    index = {}
    wanted = {e.get("match_key", e["key"]) for e in entries}
    for channel in channels:
        key = programme_reminders.channel_key(channel)
        if key in wanted:
            index.setdefault(key, []).append(channel)
    result = []
    for entry in entries:
        key = entry.get('match_key', entry['key'])
        matches = index.get(key, ())
        if 'variant' in entry:
            matches = [ch for ch in matches if ch.get('url') and variant_key(ch) == entry['variant']]
        result.append((entry, programme_reminders.resolve_channel({'channel_key': key}, matches)))
    return result
