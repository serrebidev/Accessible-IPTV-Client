"""Portable ordered favourite lists. Only safe names and opaque identities leave the device."""

import hashlib
import json
import re

from i18n import gettext as _
import favorite_collections as lists
import planning_tools
import programme_reminders as reminders

FORMAT = "accessible-iptv-favourites-v1"
LIMIT = 3 * 1024 * 1024
DIGEST = re.compile(r"[a-f0-9]{64}\Z")


def public_name(value):
    if not isinstance(value, str):
        return ""
    value = reminders.safe_title(value)
    if not value.isprintable() or re.search(r"[@/\\?=]|(?:password|token|cookie|authorization)\s*:", value, re.I):
        return ""
    return value


def guide_key(ch):
    guide = str(ch.get("tvg-id") or ch.get("tvg_id") or "").strip().casefold()
    return hashlib.sha256(guide.encode("utf-8")).hexdigest() if guide else ""


def export_list(path, row, channels):
    name = public_name(row["name"])
    if not name:
        raise ValueError(_("Choose a list name without a web address or login details."))
    entries = []
    for entry, ch in lists.resolve(row["entries"], channels):
        entries.append(
            {
                "name": public_name(entry["name"]),
                "key": entry["key"],
                "guide": guide_key(ch) if ch else entry.get("guide", ""),
            }
        )
    data = json.dumps({"format": FORMAT, "name": name, "entries": entries}, ensure_ascii=False, indent=2)
    planning_tools.atomic_export(path, data.encode("utf-8"))


def read_list(path):
    invalid = _("Invalid favourite list file.")
    with open(path, "rb") as handle:
        data = handle.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError(invalid)
    try:
        bundle = json.loads(data.decode("utf-8-sig"))
    except (ValueError, RecursionError) as error:
        raise ValueError(invalid) from error
    if (
        not isinstance(bundle, dict)
        or set(bundle) != {"format", "name", "entries"}
        or bundle["format"] != FORMAT
        or not public_name(bundle["name"])
        or public_name(bundle["name"]) != bundle["name"]
        or not isinstance(bundle["entries"], list)
        or len(bundle["entries"]) > lists.MAX_CHANNELS
    ):
        raise ValueError(invalid)
    lists.clean_name(bundle["name"])
    keys = set()
    for item in bundle["entries"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "key", "guide"}
            or not isinstance(item["name"], str)
            or public_name(item["name"]) != item["name"]
            or not isinstance(item["key"], str)
            or not DIGEST.fullmatch(item["key"])
            or item["key"] in keys
            or not isinstance(item["guide"], str)
            or (item["guide"] and not DIGEST.fullmatch(item["guide"]))
        ):
            raise ValueError(invalid)
        keys.add(item["key"])
    return bundle


def match(entries, channels):
    by_key, by_guide, by_name = {}, {}, {}
    wanted = {e["key"] for e in entries}
    guides = {e["guide"] for e in entries} - {""}
    names = {e["name"].casefold() for e in entries} - {""}
    for ch in channels:
        if not reminders.playable(ch) or ch.get("kind") in {"movie", "series"}:
            continue
        key = reminders.station_key(ch)
        guide = guide_key(ch)
        name = public_name(ch.get("name")).casefold()
        if key and (key in wanted or guide in guides or name in names):
            by_key.setdefault(key, {}).setdefault(reminders.media_identity(ch), ch)
            if guide in guides:
                by_guide.setdefault(guide, set()).add(key)
            if name in names:
                by_name.setdefault(name, set()).add(key)
    result = []
    for item in entries:
        keys = (
            {item["key"]}
            if item["key"] in by_key
            else by_guide.get(item["guide"]) or by_name.get(item["name"].casefold(), ())
        )
        result.append((item, [(key, ch) for key in sorted(keys) for ch in by_key[key].values()]))
    return result


def build_entries(rows, choices):
    result, used, selected_media = [], set(), set()
    for (item, options), choice in zip(rows, choices, strict=True):
        entry = dict(item)
        if choice is not None:
            key, ch = options[choice]
            media = (key, reminders.media_identity(ch))
            if media in selected_media:
                raise ValueError(_("Choose a different channel that is not already in this list."))
            selected_media.add(media)
            entry.update(key=key, name=public_name(ch.get("name")), guide=guide_key(ch))
            if sum(candidate == key for candidate, _ in options) > 1:
                # The portable entry id stays independent of local URLs or request headers.
                entry.update(key=item["key"], match_key=key, variant=lists.variant_key(ch))
        elif any(key == item["key"] for key, _ch in options):
            # Honour “Leave unresolved” even when the portable key exists on this device.
            entry["key"] = hashlib.sha256(("unresolved-favourite:" + item["key"]).encode("ascii")).hexdigest()
        if entry["key"] in used:
            raise ValueError(_("Choose a different channel that is not already in this list."))
        used.add(entry["key"])
        result.append(entry)
    return result
