"""On-demand recording edits. A reviewed change is published as one scheduler transaction."""

import datetime as dt
import itertools
import time

import channel_identity
import channel_preferences
import dvr
import programme_reminders
import recording_limits
from i18n import gettext as _


def padding(job):
    return job.get("pre_padding_minutes", 0), job.get("post_padding_minutes", 0)


def with_padding(job, before, after):
    if any(type(v) is not int or not 0 <= v <= 180 for v in (before, after)):
        raise ValueError(_("The recording times are invalid. Check the recording schedule."))
    programme = job["program"]
    start, end = (dvr.parse_epg_utc(programme[k]).timestamp() for k in ("start", "end"))
    return dict(
        job,
        start_ts=start - before * 60,
        stop_ts=end + after * 60,
        pre_padding_minutes=before,
        post_padding_minutes=after,
    )


def edit_padding(job, before, after, future, jobs, now):
    changed = {}
    if job["status"] != dvr.STATUS_SCHEDULED:
        raise ValueError(_("The recording schedule changed. Check the times and try again."))
    rule_id = job["id"] if job.get("repeat") == "series" else job.get("series_source")
    effective = job["program"]["start"]
    if future and rule_id:
        rule = jobs.get(rule_id)
        if not rule or rule.get("repeat") != "series" or rule["status"] == dvr.STATUS_CANCELED:
            raise ValueError(_("The recording schedule changed. Check the times and try again."))
        retained = [change for change in rule.get("series_padding_changes", ()) if change[0] < effective]
        updated_rule = dict(rule)
        updated_rule.pop("series_padding_changes", None)
        if rule_id != job["id"]:
            retained.append([effective, before, after])
        if retained:
            updated_rule["series_padding_changes"] = retained
        changed[rule_id] = updated_rule
    for old in jobs.values():
        if old["id"] != job["id"] and not (
            future
            and rule_id
            and old.get("series_source") == rule_id
            and old.get("status") == dvr.STATUS_SCHEDULED
            and old["program"]["start"] >= effective
        ):
            continue
        new = with_padding(changed.get(old["id"], old), before, after)
        if new["stop_ts"] <= now:
            raise ValueError(_("This programme has already ended."))
        if old.get("repeat") in dvr.TIME_REPEATS | {"series"} and not future:
            new["future_padding"] = list(old.get("future_padding", padding(old)))
        else:
            new.pop("future_padding", None)
        changed[new["id"]] = new
    return changed


def move_airing(job, channel, programme, fmt, jobs, now):
    if job["status"] != dvr.STATUS_SCHEDULED:
        raise ValueError(_("The recording schedule changed. Check the times and try again."))
    before, after = padding(job)
    new = dvr.build_job(channel, programme, fmt, pre_padding_minutes=before, post_padding_minutes=after)
    if dvr.parse_epg_utc(programme["start"]).timestamp() <= now:
        raise ValueError(_("The programme guide changed. Refresh the list and try again."))
    key = programme_reminders.channel_key(channel)
    if any(
        row.get("status") in dvr.ACTIVE_STATUSES
        and row.get("start_at") == new["start_at"]
        and programme_reminders.channel_key(row.get("channel")) == key
        for row in jobs.values()
    ):
        raise ValueError(_("This recording is already scheduled."))
    changed = {job["id"]: dict(job, status=dvr.STATUS_SKIPPED, message=""), new["id"]: new}
    if job.get("repeat") in dvr.TIME_REPEATS:
        successor = dvr.next_time_occurrence(job, now)
        if successor["id"] not in jobs:
            changed[successor["id"]] = successor
    parent = job["id"] if job.get("repeat") == "series" else job.get("series_source")
    if parent:
        new["series_source"] = parent
    return changed


def warnings(config, changes, jobs):
    active = [j for j in (jobs | changes).values() if j.get("status") in dvr.ACTIVE_STATUSES]
    messages = []
    for job in changes.values():
        old = jobs.get(job["id"])
        if job["status"] == dvr.STATUS_SCHEDULED and (
            not old or (old["start_ts"], old["stop_ts"]) != (job["start_ts"], job["stop_ts"])
        ):
            warning = recording_limits.warning(
                config, job["channel"], job["start_ts"], job["stop_ts"], active, exclude=job["id"]
            )
            if warning and warning not in messages:
                messages.append(warning)
    return messages


def changed_guide_times(db, jobs, *, now=None, canceled=lambda: False):
    """Compare pending guide bookings within six hours on their original channel."""
    now = time.time() if now is None else now
    results = []
    channels = {}
    fields = db.programme_metadata_fields()
    for job in jobs:
        if canceled():
            break
        if (job.get("status") != dvr.STATUS_SCHEDULED or job.get("manual")
                or job.get("repeat") in dvr.TIME_REPEATS or job.get("start_ts", 0) <= now):
            continue
        old = job.get("program") or {}
        try:
            start, end = (dvr.parse_epg_utc(old[k]) for k in ("start", "end"))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        channel = job["channel"]
        key = (programme_reminders.channel_key(channel), channel_preferences.epg_id(channel))
        if key not in channels:
            channels[key] = db.resolve_best_channel_id(channel)
        cid = channels[key]
        if not cid or (old.get("channel_id") and old["channel_id"] != cid):
            continue
        declared = str(channel.get("tvg-id") or channel.get("tvg_id") or "").strip()
        if (declared and not key[1] and not old.get("channel_id")
                and channel_identity.xmltv_id(cid).casefold() != channel_identity.xmltv_id(declared).casefold()):
            continue  # A similarly named replacement station is not the booked source.
        title = dvr.program_title(old).strip().casefold()
        identity = dvr.program_episode_key(old)
        near = dt.timedelta(hours=6)
        times = [(start - near).strftime("%Y%m%d%H%M%S"), (start + near).strftime("%Y%m%d%H%M%S")]
        rows = db.conn.execute(
            "SELECT title,start,end," + fields + " FROM programmes WHERE channel_id=? AND start BETWEEN ? AND ? ORDER BY start,end",
            (cid, *times))
        candidates = []
        for name, a, b, sub, ep, desc in rows:
            if (name or "").strip().casefold() != title:
                continue
            candidate = dict(channel_id=cid, title=name, start=a, end=b, subtitle=sub or "",
                             episode=ep or "", description=desc or "")
            match = dvr.program_episode_key(candidate)
            if identity and match and identity != match:
                continue
            if (a, b) == (old["start"], old["end"]):
                candidates = []
                break  # unchanged broadcast, even when a later repeat also matches
            try:
                new_start, new_end = (dvr.parse_epg_utc(t) for t in (a, b))
            except (TypeError, ValueError, OverflowError):
                continue
            exact = bool(identity and match == identity)
            if new_start >= new_end or new_start.timestamp() - padding(job)[0] * 60 <= now:
                continue
            if exact or (new_start < end and new_end > start):
                candidates.append((job, candidate, exact))
        results.extend(candidates)
    return results


def retime_booking(job, programme, jobs, now):
    """Update the original booking in place, retaining all rule and padding fields."""
    if jobs.get(job["id"]) != job or job.get("status") != dvr.STATUS_SCHEDULED:
        raise ValueError(_("The recording schedule changed. Check the times and try again."))
    before, after = padding(job)
    new = with_padding(dict(job, program=dict(job["program"], **programme)), before, after)
    start, end = (dvr.parse_epg_utc(programme[k]).timestamp() for k in ("start", "end"))
    if new["start_ts"] <= now or end <= start:
        raise ValueError(_("The programme guide changed. Refresh the list and try again."))
    new.update(start_at=dvr.iso_from_ts(start), end_at=dvr.iso_from_ts(end))
    key = programme_reminders.channel_key(job["channel"])
    if any(other["id"] != job["id"] and other.get("start_at") == new["start_at"]
           and other["status"] in dvr.ACTIVE_STATUSES and programme_reminders.channel_key(other["channel"]) == key
           for other in jobs.values()):
        raise ValueError(_("This recording is already scheduled."))
    return {job["id"]: new}


def other_airings(db, job, channels, *, canceled=lambda: False, now=None, maximum=100):
    now = time.time() if now is None else now
    start = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    end = start + dt.timedelta(days=14)
    guides = {
        cid: {"id": cid, "display_name": name or ""}
        for cid, name in db.conn.execute("SELECT id, display_name FROM channels")
    }
    index = channel_identity.guide_indexes(guides)
    def guide_for(channel):
        override = channel_preferences.epg_id(channel)
        return guides.get(override) if override else channel_identity.match_guide_channel(channel, index)
    source = guide_for(job["channel"])
    original = job.get("program") or {}
    if source:
        try:
            info = db.programme_details(dict(original, channel_id=source["id"], title=dvr.program_title(original)))
        except ValueError:
            info = {}  # The old slot can disappear between two EPG imports.
        original = dict(original, **{k: v for k, v in info.items() if v and not original.get(k)})
    identity = dvr.program_episode_key(original)
    title = dvr.program_title(original).strip().casefold()
    db.conn.create_function("airing_title", 1, lambda s: (s or "").strip().casefold(), deterministic=True)
    db.conn.set_progress_handler(lambda: int(canceled()), 2000)
    fields = db.programme_metadata_fields()
    query = (
        """SELECT channel_id,title,start,end,"""
        + fields
        + """ FROM programmes
               WHERE start>? AND start<=? AND airing_title(title)=? ORDER BY start,channel_id,end,id"""
    )
    stamps = [x.strftime("%Y%m%d%H%M%S") for x in (start, end)]
    confirmed, possible = [], []
    cursor = iter(db.conn.execute(query, (*stamps, title)))
    first = next(cursor, None)
    if first is None:
        return [], False
    by_guide = {}
    for ch in channels:
        if canceled():
            return [], False
        if not ch.get("url") or ch.get("kind") in {"series", "movie"}:
            continue
        match = guide_for(ch)
        if match:
            identity_key = (programme_reminders.channel_key(ch), programme_reminders.media_identity(ch))
            by_guide.setdefault(match["id"], {}).setdefault(identity_key, ch)
    total = 0
    numbered = bool(identity and identity.startswith("ep:"))
    original_channel = job['channel']
    original_source = original_channel.get('provider-id') or original_channel.get('playlist-id')
    for cid, name, a, b, sub, ep, desc in itertools.chain((first,), cursor):
        if canceled():
            return [], False
        if cid not in by_guide:
            continue
        try:
            if dvr.parse_epg_utc(a) >= dvr.parse_epg_utc(b):
                continue
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        programme = dict(
            channel_id=cid, title=name, start=a, end=b, description=desc or "", episode=ep or "", subtitle=sub or ""
        )
        candidate = dvr.program_episode_key(programme)
        if numbered and candidate and candidate.startswith("ep:") and identity != candidate:
            old_episode, _, old_part = identity.partition(":part")
            new_episode, _, new_part = candidate.partition(":part")
            if old_episode != new_episode or (old_part and new_part):
                continue
        exact = numbered and identity == candidate
        group = confirmed if exact else possible
        for ch in by_guide[cid].values():
            if a == original.get("start"):
                other_source = ch.get('provider-id') or ch.get('playlist-id')
                if not original_source or not other_source or original_source == other_source:
                    continue
                if original_channel.get('url') and programme_reminders.media_identity(ch) == programme_reminders.media_identity(original_channel):
                    continue
            total += 1
            if len(group) < maximum:
                group.append((ch, programme, exact))
            if total > maximum and (len(confirmed) == maximum or not numbered):
                return (confirmed + possible)[:maximum], True
    return (confirmed + possible)[:maximum], total > maximum
