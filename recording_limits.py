"""Account-scoped recording budgets and exact interval capacity checks.

These are user-assigned budgets for recordings, not a claim about connections
on other devices. Existing exclusive-provider and local-buffer rules still apply.
"""
import hashlib
import json
import math
import re

import account_info
from i18n import gettext as _


def account_key(account):
    return hashlib.sha256(json.dumps(account.dedupe_key).encode()).hexdigest()


def normalize(value):
    if not isinstance(value, dict):
        return {}
    return {key: limit for key, limit in value.items()
            if isinstance(key, str) and re.fullmatch(r"[0-9a-f]{64}", key)
            and type(limit) is int and 1 <= limit <= 64}


def channel_key(channel, config):
    channel = channel if isinstance(channel, dict) else {}
    provider = channel.get("provider-id")
    if provider:
        # Discover each configured source separately so aliases of one account
        # retain their provider id while producing the same hashed account key.
        for source in config.get("playlists", []):
            for account in account_info.discover_accounts([source]):
                if account.provider_id == provider:
                    return account_key(account)
    accounts = account_info.discover_accounts(channels=[channel])
    return account_key(accounts[0]) if len(accounts) == 1 else ""


def check_start(config, url, metadata, active):
    key = metadata.get("recording_account") or channel_key(dict(metadata.get("channel") or {}, url=url), config)
    limit = normalize(config.get("recording_connection_limits")).get(key, 0)
    if limit:
        used = sum(getattr(rec, "buffer_lease", None) is None
                   and (rec.metadata.get("recording_account") or channel_key(
                       dict(rec.metadata.get("channel") or {}, url=rec.url), config)) == key for rec in active)
        if used >= limit:
            raise RuntimeError(_("The recording connection limit for this account has been reached ({limit}). Existing recordings will continue.").format(limit=limit))
    return key


def peak_demand(config, channel, start, end, jobs, *, exclude=None):
    key = channel_key(channel, config)
    limit = normalize(config.get("recording_connection_limits")).get(key, 0)
    if not limit:
        return None
    events = [(start, 1), (end, -1)]
    for job in jobs:
        if job.get("id") == exclude or job.get("status") not in {"scheduled", "recording", "stopping"}:
            continue
        if channel_key(job.get("channel"), config) != key:
            continue
        a, b = job.get("start_ts"), job.get("stop_ts")
        if not all(type(value) in (int, float) and math.isfinite(value) for value in (a, b)):
            continue
        if a < end and b > start:
            events.extend(((max(a, start), 1), (min(b, end), -1)))
    current = peak = 0
    for _time, delta in sorted(events):  # End before start at a shared boundary.
        current += delta
        peak = max(peak, current)
    return peak, limit


def warning(config, channel, start, end, jobs, *, exclude=None):
    demand = peak_demand(config, channel, start, end, jobs, exclude=exclude)
    if demand is None:
        overlaps = [job for job in jobs if job.get("id") != exclude
                    and job.get("start_ts", 0) < end and job.get("stop_ts", 0) > start]
        return _("This overlaps {count} recording(s). Continue?").format(count=len(overlaps)) if overlaps else ""
    peak, limit = demand
    if peak > limit:
        return _("This schedule needs {count} simultaneous recording connections for the same account, but its recording limit is {limit}. Schedule it anyway?").format(count=peak, limit=limit)
    return ""
