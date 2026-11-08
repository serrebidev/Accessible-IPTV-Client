"""Bounded, cancelable programme searches and durable notification history."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import uuid

import channel_identity
import programme_reminders
from i18n import gettext as _

MAX_RULES = 30
MAX_RESULTS = 500
MAX_SEEN = 20000


class ScanCanceled(Exception):
    pass


def normalize(value):
    rows, seen = [], set()
    for raw in (value if isinstance(value, list) else [])[:MAX_RULES]:
        if not isinstance(raw, dict):
            continue
        key, query = raw.get("id"), raw.get("query")
        if (not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key) or key in seen
                or not isinstance(query, str) or not 2 <= len(query.strip()) <= 100
                or any(ord(c) < 32 for c in query)):
            continue
        scope = raw.get("channels")
        if not isinstance(scope, list) or len(scope) > 2000:
            continue
        if any(not isinstance(k, str) or not re.fullmatch(r"[a-f0-9]{64}", k) for k in scope):
            continue
        seen.add(key)
        rows.append({"id": key, "query": query.strip(), "channels": list(dict.fromkeys(scope)),
                     "description": raw.get("description") is True,
                     "enabled": raw.get("enabled", True) is True})
    return rows


def new_rule(query, *, channels=(), description=False):
    raw = {"id": uuid.uuid4().hex, "query": query, "channels": list(channels),
           "description": bool(description), "enabled": True}
    rows = normalize([raw])
    if not rows:
        raise ValueError(_("Enter a search of 2 to 100 characters and choose at most 2000 channels."))
    return rows[0]


def signature(rules):
    return hashlib.sha256(json.dumps(normalize(rules), sort_keys=True).encode()).hexdigest()


def scan(path, rules, channels, *, canceled=lambda: False, now=None, budget=20):
    """One read-only SQLite snapshot; no network or media connections."""
    now = time.time() if now is None else now
    deadline = time.monotonic() + budget

    def checkpoint():
        if canceled():
            raise ScanCanceled()
        if time.monotonic() > deadline:
            raise TimeoutError(_("The programme search took too long. Narrow the search and try again."))

    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: int(canceled() or time.monotonic() > deadline), 2000)
        db.execute("BEGIN")
        guides = {str(key): {"id": str(key), "display_name": str(name or "")}
                  for key, name in db.execute("SELECT id, display_name FROM channels")}
        checkpoint()
        indexes = channel_identity.guide_indexes(guides)
        mapped = {}
        for i, channel in enumerate(channels):
            if i % 256 == 0:
                checkpoint()
            if channel.get("kind") in {"movie", "series"}:
                continue
            entry = channel_identity.match_guide_channel(channel, indexes)
            if entry:
                key = programme_reminders.channel_key(channel)
                if key:
                    mapped.setdefault(entry["id"], {})[key] = programme_reminders.safe_title(channel.get("name"))
        stamp = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y%m%d%H%M%S")
        db.create_function("search_fold", 1, lambda x: str(x or "").casefold(), deterministic=True)
        output = []
        columns = {row[1] for row in db.execute("PRAGMA table_info(programmes)")}
        for rule in normalize(rules):
            checkpoint()
            if not rule["enabled"]:
                continue
            where = "instr(search_fold(title), ?) > 0"
            args = [stamp(now), stamp(now + 14 * 86400), rule["query"].casefold()]
            if rule["description"] and "description" in columns:
                where += " OR instr(search_fold(description), ?) > 0"
                args.append(rule["query"].casefold())
            desc = "description" if "description" in columns else "''"
            query = ("SELECT channel_id, title, start, end, " + desc + " FROM programmes "
                     "WHERE start >= ? AND start <= ? AND (" + where + ") ORDER BY start, channel_id, title")
            matches, identities, truncated = [], set(), False
            scope = set(rule["channels"])
            for cid, title, start, end, description in db.execute(query, args):
                checkpoint()
                eligible = mapped.get(str(cid), {})
                if scope:
                    eligible = {key: name for key, name in eligible.items() if key in scope}
                if not eligible:
                    continue
                try:
                    start_ts = dt.datetime.strptime(start, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
                    end_ts = dt.datetime.strptime(end, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
                    if end_ts <= start_ts:
                        continue
                except (ValueError, TypeError, OverflowError):
                    continue
                # A guide slot gets one notification, even if several playlist
                # variants carry it. Actions still resolve a current source key.
                identity = hashlib.sha256(json.dumps([rule["id"], str(cid), start]).encode()).hexdigest()
                if identity in identities:
                    continue
                if len(matches) == MAX_RESULTS:
                    truncated = True
                    break
                identities.add(identity)
                matches.append({"id": identity, "rule": rule["id"], "channel_keys": list(eligible),
                                "channel": next(iter(eligible.values())), "channel_id": str(cid),
                                "title": programme_reminders.safe_title(title), "start": start, "end": end,
                                "end_ts": end_ts, "description": str(description or "")[:16000]})
            output.append({"rule": rule["id"], "query": rule["query"], "matches": matches, "truncated": truncated})
        return output
    except sqlite3.OperationalError:
        checkpoint()
        raise
    finally:
        db.close()


def normalize_seen(value, *, now=None):
    now = time.time() if now is None else now
    if not isinstance(value, dict):
        raise ValueError(_("The saved search history is damaged."))
    rows = {k: v for k, v in value.items() if isinstance(k, str) and re.fullmatch(r"[a-f0-9]{64}", k)
            and type(v) in (int, float) and now < v <= now + 16 * 86400}
    return dict(sorted(rows.items(), key=lambda item: item[1])[:MAX_SEEN])


def read_seen(path):
    if not os.path.exists(path):
        return {}
    if os.path.getsize(path) > 4 * 1024 * 1024:
        raise ValueError(_("The saved search history is damaged."))
    with open(path, encoding="utf-8") as handle:
        return normalize_seen(json.load(handle))


def commit_seen(path, old, results, *, now=None):
    """Return new count only after durable persistence; failure cannot erase state."""
    seen = normalize_seen(copy.deepcopy(old), now=now)
    matches = {m["id"]: m["end_ts"] for result in results for m in result["matches"]}
    count = len(matches.keys() - seen.keys())
    seen.update(matches)
    # Keep every match in the current bounded result set before older history.
    # Otherwise a full history can evict a still-visible future match and alert
    # about the same programme again on every scan.
    seen = dict(sorted(seen.items(), key=lambda item: (item[0] not in matches, item[1]))[:MAX_SEEN])
    seen = normalize_seen(seen, now=now)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix="search-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(seen, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return seen, count
