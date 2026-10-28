"""Bounded, durable reminders. No media URLs, timers or GUI objects are stored."""
import copy
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time

import dvr
import favorites
from http_headers import channel_http_headers

MAX_REMINDERS = 500
STATES = {'scheduled', 'ready', 'notified', 'expired'}


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
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 253402300799


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
                or type(lead) is not int or not 0 <= lead <= 120 or row.get('status') not in STATES):
            continue
        expected = hashlib.sha256(json.dumps([source, start]).encode()).hexdigest()
        if expected != key:
            continue
        result[key] = {'id': key, 'channel_key': source, 'start': start, 'end': end, 'lead': lead,
                       'title': safe_title(row.get('title')), 'channel': safe_title(row.get('channel')),
                       'status': row['status']}
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


def resolve_channel(row, channels):
    matches = {(str(ch['url']), json.dumps(channel_http_headers(ch), sort_keys=True, default=str)): ch
               for ch in channels if ch.get('url') and channel_key(ch) == row['channel_key']}
    return next(iter(matches.values())) if len(matches) == 1 else None


class ReminderStore:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
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

    def list(self):
        with self._lock:
            return copy.deepcopy(self.rows)

    def _commit(self, rows):
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
        self.rows = normalized

    def add(self, row):
        checked = normalize([row])
        if not checked:
            raise ValueError('Invalid reminder')
        with self._lock:
            rows = [r for r in self.rows if r['id'] != row['id']]
            active = [r for r in rows if r['status'] in {'scheduled', 'ready'}]
            if len(active) >= MAX_REMINDERS:
                raise ValueError('Too many active reminders (500)')
            self._commit([checked[0], *rows])

    def remove(self, key=None):
        with self._lock:
            self._commit([] if key is None else [r for r in self.rows if r['id'] != key])

    def set_lead(self, key, lead, *, now=None):
        now = time.time() if now is None else now
        with self._lock:
            row = next((dict(r) for r in self.rows if r['id'] == key), None)
            if not row or row['start'] <= now or type(lead) is not int or not 0 <= lead <= 120:
                raise ValueError('Invalid reminder lead time')
            row.update(lead=lead, status='scheduled')
            self.add(row)

    def due(self, now=None):
        now = time.time() if now is None else now
        if not valid_time(now):
            return []
        with self._lock:
            rows = self.list()
            for row in rows:
                if row['status'] in {'scheduled', 'ready'}:
                    if now >= row['end']:
                        row['status'] = 'expired'
                    elif now >= row['start'] - row['lead'] * 60:
                        row['status'] = 'ready'
            if rows != self.rows:
                self._commit(rows)
            return [r for r in rows if r['status'] == 'ready' and r['start'] - r['lead'] * 60 <= now < r['end']]

    def acknowledge(self, key):
        with self._lock:
            rows = self.list()
            for row in rows:
                if row['id'] == key and row['status'] == 'ready':
                    row['status'] = 'notified'
            self._commit(rows)
