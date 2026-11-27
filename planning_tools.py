"""On-demand exports, library preferences and bounded weekday recurrence."""
import copy
import csv
import datetime as dt
import hashlib
import io
import os
import tempfile
import time
import uuid

from i18n import gettext as _


def checked_weekdays(value):
    if not isinstance(value, (list, tuple)) or any(type(d) is not int or not 0 <= d <= 6 for d in value):
        raise ValueError(_("Choose weekdays from Monday to Sunday."))
    return sorted(set(value))


def next_weekday_job(job, now, *, weekdays=None, future_only=False, earliest_date=None):
    """Keep programme wall times. Skip nonexistent DST windows, never guess gaps."""
    import dvr
    from manual_schedule import local_candidates
    days = checked_weekdays(job.get('weekdays', []) if weekdays is None else weekdays)
    if not days:
        return None
    pre = int(dvr._number(job.get('pre_padding_minutes'))) * 60
    post = int(dvr._number(job.get('post_padding_minutes'))) * 60
    previous_start = float(job['start_ts'])
    original = dt.datetime.fromtimestamp(previous_start + pre)
    end = dt.datetime.fromtimestamp(float(job['stop_ts']) - post)
    pre_minutes, post_minutes = job.get('future_padding', (pre // 60, post // 60))
    pre, post = int(pre_minutes) * 60, int(post_minutes) * 60
    offset = (end.date() - original.date()).days
    first = max(original.date() + dt.timedelta(days=1),
                dt.datetime.fromtimestamp(now).date() - dt.timedelta(days=max(1, offset)))
    if earliest_date is not None:
        first = max(first, earliest_date)
    for step in range(370):
        date = first + dt.timedelta(days=step)
        if date.weekday() not in days:
            continue
        starts = dt.datetime.combine(date, original.time())
        ends = dt.datetime.combine(date + dt.timedelta(days=offset), end.time())
        try:
            a = local_candidates(starts.strftime('%Y-%m-%d %H:%M'))
            b = local_candidates(ends.strftime('%Y-%m-%d %H:%M'))
        except ValueError:
            continue
        start = a[min(original.fold, len(a) - 1)] + original.second - pre
        stop = b[min(end.fold, len(b) - 1)] + end.second + post
        if start <= previous_start or stop <= now or stop <= start or (future_only and start <= now):
            continue
        result = copy.deepcopy(job)
        result.pop('future_padding', None)
        result.update(id=uuid.uuid4().hex, start_ts=start, stop_ts=stop,
                      pre_padding_minutes=pre // 60, post_padding_minutes=post // 60,
                      start_at=dvr.iso_from_ts(start + pre), end_at=dvr.iso_from_ts(stop - post),
                      status=dvr.STATUS_SCHEDULED, recording_id=None, output_path='', message='',
                      created_at=dvr.iso_from_ts(now))
        result['program'] = dict(result.get('program') or {},
            start=dt.datetime.fromtimestamp(start + pre, dt.timezone.utc).strftime('%Y%m%d%H%M%S'),
            end=dt.datetime.fromtimestamp(stop - post, dt.timezone.utc).strftime('%Y%m%d%H%M%S'))
        return result
    raise ValueError(_("No valid recording window was found for the selected weekdays."))


def atomic_export(path, content):
    """Replace only a complete export, preserving an existing file on failure."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix='.iptv-export-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def csv_cell(value):
    value = str(value or '')
    # CSV quoting does not prevent spreadsheet formula execution.
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def recording_csv(rows):
    text = io.StringIO(newline='')
    writer = csv.writer(text)
    writer.writerow([_("Title"), _("Channel"), _("Date"), _("Duration (seconds)"), _("Status"), _("Size (bytes)")])
    labels = {'completed': _("Completed"), 'partial': _("Partial"), 'stopped': _("Stopped by user"),
              'failed': _("Failed"), 'unknown': _("Unknown")}
    for row in rows:
        writer.writerow([csv_cell(row.get('title')), csv_cell(row.get('channel')), csv_cell(row.get('date')),
                         '' if row.get('duration') is None else str(row['duration']),
                         labels.get(row.get('status'), _("Unknown")), row.get('size', 0)])
    return text.getvalue().encode('utf-8-sig')


def ical_text(value):
    # RFC 5545 TEXT escaping; eliminate other control characters.
    value = ''.join(c for c in str(value or '') if ord(c) >= 32 or c in '\n\r\t')
    return value.replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def fold_ical(line):
    """75 octets per physical line, without splitting a UTF-8 character."""
    lines, current, length = [], '', 0
    for char in line:
        size = len(char.encode('utf-8'))
        if length + size > 75:
            lines.append(current)
            current, length = ' ', 1
        current += char
        length += size
    return '\r\n'.join([*lines, current])


def programme_calendar(title, channel, start, end, *, identity='', now=None):
    key = hashlib.sha256(f'{identity}\0{title}\0{channel}\0{start}'.encode()).hexdigest()
    return _calendar([(key, title, channel, start, end)], now)


def pause_preview(rule, period, bookings=(), *, now=None):
    """Return the first suppressed and first eligible programme start in local time."""
    import dvr
    now = time.time() if now is None else now
    first, last = map(dt.date.fromisoformat, period)

    def programme_start(job):
        return dt.datetime.fromtimestamp(job['start_ts'] + dvr._number(job.get('pre_padding_minutes')) * 60)

    if rule.get('repeat') == 'series':
        starts = [programme_start(job) for job in bookings
                  if (job.get('id') == rule['id'] or job.get('series_source') == rule['id'])
                  and job.get('status') == dvr.STATUS_SCHEDULED and job['start_ts'] > now]
        return (min((t for t in starts if first <= t.date() <= last), default=None),
                min((t for t in starts if t.date() > last), default=None))

    def occurrence(day):
        if rule['status'] == dvr.STATUS_SCHEDULED and rule['start_ts'] > now and programme_start(rule).date() >= day:
            return programme_start(rule)
        try:
            return programme_start(dvr.next_time_occurrence(rule, now, earliest_date=day, future_only=True))
        except (OverflowError, OSError, ValueError):
            return None

    skipped = occurrence(first)
    resume = occurrence(last + dt.timedelta(days=1)) if last < dt.date.max else None
    return skipped if skipped and skipped.date() <= last else None, resume


def recording_calendar(jobs, *, now=None):
    import dvr
    import programme_reminders
    now = time.time() if now is None else now
    events = {}
    for job in jobs:
        if (job.get("status") != dvr.STATUS_SCHEDULED or dvr.paused_occurrence(job)
                or not job.get("id") or job["start_ts"] <= now):
            raise ValueError(_("Select upcoming recordings outside the pause period."))
        key = hashlib.sha256(("booking:" + str(job["id"])).encode()).hexdigest()
        title = programme_reminders.safe_title(job.get("title")) or _("Scheduled Recording")
        channel = programme_reminders.safe_title(job.get("channel_name"))
        events[key] = (key, title, channel, job["start_ts"], job["stop_ts"])
    if not events:
        raise ValueError(_("Select upcoming recordings outside the pause period."))
    return _calendar(sorted(events.values(), key=lambda event: (event[3], event[0])), now)


def _calendar(events, now):
    import math

    def stamp(value):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    generated = stamp(time.time() if now is None else now)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Accessible IPTV Client//Programme//EN',
             'CALSCALE:GREGORIAN']
    for key, title, channel, start, end in events:
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in (start, end)) or end <= start:
            raise ValueError(_("Invalid programme times."))
        lines.extend(['BEGIN:VEVENT', 'UID:' + key + '@accessible-iptv-client', 'DTSTAMP:' + generated,
                      'DTSTART:' + stamp(start), 'DTEND:' + stamp(end), 'SUMMARY:' + ical_text(title),
                      'DESCRIPTION:' + ical_text(channel), 'END:VEVENT'])
    lines.append('END:VCALENDAR')
    return ('\r\n'.join(map(fold_ical, lines)) + '\r\n').encode('utf-8')


def library_view(value, directories):
    value = value if isinstance(value, dict) else {}
    folder = value.get('folder')
    return {'folder': folder if folder in directories or folder == '*' else directories[0],
            'query': str(value.get('query') or '')[:240],
            'status': value.get('status') if value.get('status') in ('', 'completed', 'partial', 'stopped', 'failed', 'unknown') else '',
            'sort': value.get('sort') if value.get('sort') in ('date', 'title', 'duration', 'size') else 'date',
            'descending': value.get('descending', True) is not False}
