"""Bounded, durable reminders. No media URLs, timers or GUI objects are stored."""
import copy
import hashlib
import json
import math
import logging
import os
import re
import tempfile
import uuid
import threading
import time

import dvr
import favorites
from http_headers import channel_http_headers
from i18n import gettext as _

MAX_REMINDERS = 500
STATES = {'scheduled', 'ready', 'notified', 'expired'}
LOG = logging.getLogger(__name__)


def channel_key(channel):
    if not isinstance(channel, dict):
        return ''
    source = str(channel.get('provider-id') or channel.get('playlist-id') or '')
    identity = favorites.channel_key(channel)
    if not identity:
        return ''
    return hashlib.sha256(json.dumps([source, identity]).encode()).hexdigest()


def safe_title(value):
    text = str(value or '').strip()
    if re.search(r'://|www\.|[\x00-\x1f]', text, re.I):
        return ''
    return text[:240]


def valid_time(value):
    return type(value) in (int, float) and 0 <= value <= 253402300799 and math.isfinite(value)


def source_names(config):
    names = {source.get('id') or source.get('provider_id'): safe_title(source.get('name'))
             for source in config.get('playlists', ()) if isinstance(source, dict)
             and (source.get('id') or source.get('provider_id'))}
    aliases = config.get('playlist_names')
    if isinstance(aliases, dict):
        names.update({'m3u:' + key: safe_title(name) for key, name in aliases.items()
                      if isinstance(key, str) and re.fullmatch('[a-f0-9]{64}', key)})
    return names


def normalize(rows):
    if not isinstance(rows, list):
        return []
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key, source = row.get('id'), row.get('channel_key')
        start, end, lead = (row.get(k) for k in ('start', 'end', 'lead'))
        if (not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key)
                or not isinstance(source, str) or not re.fullmatch('[a-f0-9]{64}', source)
                or not valid_time(start) or not valid_time(end) or end <= start
                or type(lead) is not int or not 0 <= lead <= 120
                or not isinstance(row.get('status'), str) or row['status'] not in STATES):
            continue
        expected = hashlib.sha256(json.dumps([source, start]).encode()).hexdigest()
        if expected != key:
            continue
        result[key] = {'id': key, 'channel_key': source, 'start': start, 'end': end, 'lead': lead,
                       'title': safe_title(row.get('title')), 'channel': safe_title(row.get('channel')),
                       'status': row['status']}
        snooze = row.get('notify_at')
        if valid_time(snooze) and start - lead * 60 <= snooze < end:
            result[key]['notify_at'] = snooze
    # Keep active entries first; then newest completed history. Never displace a
    # pending reminder with old history during normalization or capacity checks.
    return sorted(result.values(), key=lambda r: (r['status'] not in {'scheduled', 'ready'},
                  r['start'] if r['status'] in {'scheduled', 'ready'} else -r['start'], r['id']))[:MAX_REMINDERS]


def build(channel, program, lead=5, *, now=None):
    now = time.time() if now is None else now
    if not isinstance(channel, dict) or not isinstance(program, dict) or not valid_time(now):
        raise ValueError('Invalid programme')
    start = dvr.parse_epg_utc(program.get('start', '')).timestamp()
    end = dvr.parse_epg_utc(program.get('end', '')).timestamp()
    source = channel_key(channel)
    if not source or start <= now or end <= start or type(lead) is not int or not 0 <= lead <= 120:
        raise ValueError('Invalid or already-started programme')
    key = hashlib.sha256(json.dumps([source, start]).encode()).hexdigest()
    return {'id': key, 'channel_key': source, 'title': safe_title(dvr.program_title(program)),
            'channel': safe_title(dvr.channel_name(channel)), 'start': start, 'end': end,
            'lead': lead, 'status': 'scheduled'}


def media_identity(channel):
    return str(channel['url']), json.dumps(channel_http_headers(channel), sort_keys=True, default=str)


def resolve_channel(row, channels):
    matches = {media_identity(ch): ch
               for ch in channels if ch.get('url') and channel_key(ch) == row['channel_key']}
    return next(iter(matches.values())) if len(matches) == 1 else None


class ReminderStore:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        self._write_lock = threading.RLock()
        self._load_error = None
        self.load_warning = ''
        self.rows = []
        if os.path.exists(path):
            # Don't replace a corrupt/unreadable file with an empty list.
            if os.path.getsize(path) > 2 * 1024 * 1024:
                raise ValueError('Reminder file exceeds its size limit')
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('reminders'), list):
                raise ValueError('Invalid reminder file')
            self.rows = normalize(data['reminders'])
            if len(self.rows) != len(data['reminders']):
                backup = self.path + '.corrupt-' + uuid.uuid4().hex
                try:
                    import shutil
                    with open(self.path, 'rb') as source, open(backup, 'xb') as target:
                        shutil.copyfileobj(source, target)
                        target.flush()
                        os.fsync(target.fileno())
                    self.load_warning = _("Invalid reminders were skipped. The original file was preserved at {path}.").format(path=backup)
                except OSError as error:
                    try:
                        os.unlink(backup)
                    except OSError:
                        LOG.debug("Could not remove incomplete reminder backup", exc_info=True)
                    self._load_error = error
                    self.load_warning = _("Invalid reminders could not be backed up. Changes are disabled to protect the original file.")

    def list(self):
        with self._lock:
            return copy.deepcopy(self.rows)

    def _commit(self, rows):
        if self._load_error is not None:
            raise OSError(self.load_warning) from self._load_error
        normalized = normalize(rows)
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=directory, prefix='reminders-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump({'version': 1, 'reminders': normalized}, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        with self._lock:
            self.rows = normalized

    def add(self, row):
        checked = normalize([row])
        if not checked:
            raise ValueError('Invalid reminder')
        with self._write_lock:
            rows = [r for r in self.list() if r['id'] != row['id']]
            active = [r for r in rows if r['status'] in {'scheduled', 'ready'}]
            if len(active) >= MAX_REMINDERS:
                raise ValueError('Too many active reminders (500)')
            self._commit([checked[0], *rows])

    def remove(self, key=None):
        with self._write_lock:
            self._commit([] if key is None else [r for r in self.list() if r['id'] != key])

    def set_lead(self, key, lead, *, now=None):
        now = time.time() if now is None else now
        with self._write_lock:
            row = next((dict(r) for r in self.list() if r['id'] == key), None)
            if not row or row['start'] <= now or type(lead) is not int or not 0 <= lead <= 120:
                raise ValueError('Invalid reminder lead time')
            row.update(lead=lead, status='scheduled')
            row.pop('notify_at', None)
            self.add(row)

    def due(self, now=None):
        now = time.time() if now is None else now
        if not valid_time(now):
            return []
        with self._write_lock:
            rows = self.list()
            for row in rows:
                if row['status'] in {'scheduled', 'ready'}:
                    if now >= row['end']:
                        row['status'] = 'expired'
                    elif now >= row.get('notify_at', row['start'] - row['lead'] * 60):
                        row['status'] = 'ready'
            if rows != self.rows:
                self._commit(rows)
            return [r for r in rows if r['status'] == 'ready' and r.get('notify_at', r['start'] - r['lead'] * 60) <= now < r['end']]

    def snooze(self, key, *, minutes=5, at_start=False, now=None):
        now = time.time() if now is None else now
        if not valid_time(now) or type(minutes) is not int or not 1 <= minutes <= 120:
            raise ValueError(_("Invalid reminder postponement."))
        with self._write_lock:
            rows = self.list()
            row = next((r for r in rows if r['id'] == key), None)
            target = row['start'] if row and at_start else now + minutes * 60
            if not row or row['status'] == 'expired' or not now < target < row['end']:
                raise ValueError(_("The reminder cannot be postponed beyond the programme's end."))
            row.update(status='scheduled', notify_at=target)
            self._commit(rows)

    def acknowledge(self, key):
        with self._write_lock:
            rows = self.list()
            for row in rows:
                if row['id'] == key and row['status'] == 'ready':
                    row['status'] = 'notified'
            self._commit(rows)

    def save_alert_choice(self, key, target, *, now=None):
        """A retry keeps the originally requested time and respects subsequent edits."""
        now = time.time() if now is None else now
        with self._write_lock:
            rows = self.list()
            row = next((r for r in rows if r['id'] == key), None)
            if not row or row['status'] != 'ready':
                return
            if row['end'] <= now:
                row['status'] = 'expired'
            elif target <= now or target >= row['end']:
                return  # Still due. The next poll can show it again.
            else:
                row.update(status='scheduled', notify_at=target)
            self._commit(rows)
