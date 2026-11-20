import csv
import datetime as dt
import hashlib
import io
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

import dvr
import planning_tools as tools
import programme_reminders as reminders
import recording_library as library
from background_tasks import start_operation


def reminder():
    source, start = 'a' * 64, 2000000000
    return dict(id=hashlib.sha256(json.dumps([source, start]).encode()).hexdigest(),
                channel_key=source, title='Híradó', channel='TV', start=start,
                end=start + 3600, lead=5, status='scheduled')


@pytest.mark.parametrize('bad', [[], {}, None, 7, 'bogus'])
def test_invalid_schedule_status_does_not_hide_valid_jobs_or_erase_original(tmp_path, bad):
    path = tmp_path / 'schedule.json'
    raw = json.dumps({'jobs': [{'id': 'good', 'status': 'scheduled', 'start_ts': 2000000000,
                                'stop_ts': 2000000600}, {'id': 'bad', 'status': bad}]}).encode()
    path.write_bytes(raw)
    scheduler = dvr.DVRScheduler(str(path), on_start=lambda job: 1, on_stop=lambda job: None)
    assert scheduler.get_job('good') and scheduler.get_job('bad') is None
    assert scheduler.load_warning
    assert next(tmp_path.glob('schedule.json.corrupt-*')).read_bytes() == raw
    scheduler.save()
    assert len(json.loads(path.read_text())['jobs']) == 1


def test_bad_reminder_is_preserved_while_valid_reminders_remain_usable(tmp_path):
    path = tmp_path / 'reminders.json'
    raw = json.dumps({'version': 1, 'reminders': [reminder(), dict(reminder(), status=[])]}).encode()
    path.write_bytes(raw)
    store = reminders.ReminderStore(str(path))
    assert store.list() == [reminder()]
    assert next(tmp_path.glob('reminders.json.corrupt-*')).read_bytes() == raw
    store.remove()
    assert json.loads(path.read_text())['reminders'] == []


def test_preservation_failure_blocks_reminder_writes(tmp_path, monkeypatch):
    import shutil
    path = tmp_path / 'reminders.json'
    path.write_text(json.dumps({'version': 1, 'reminders': [dict(reminder(), status={})]}))
    original = path.read_bytes()
    monkeypatch.setattr(shutil, 'copyfileobj', lambda *args: (_ for _ in ()).throw(OSError('full')))
    store = reminders.ReminderStore(str(path))
    with pytest.raises(OSError):
        store.remove()
    assert path.read_bytes() == original


def test_writer_can_read_its_own_large_multibyte_index(tmp_path):
    rows = {f'{i}.mkv': dict(title='á' * 240, channel='é' * 240, duration=3600,
                            size=5, modified_ns=1, status='completed') for i in range(10000)}
    library._write(tmp_path, rows)
    assert library._read(tmp_path) == rows


def test_oversize_write_keeps_previous_readable_index(tmp_path, monkeypatch):
    library._write(tmp_path, {'old': {}})
    monkeypatch.setattr(library, '_MAX_INDEX_BYTES', 20)
    with pytest.raises(ValueError):
        library._write(tmp_path, {'new': {'title': 'a' * 30}})
    assert library._read(tmp_path) == {'old': {}}


def test_snooze_survives_restart_expires_and_can_be_changed(tmp_path):
    store = reminders.ReminderStore(str(tmp_path / 'r.json'))
    row = reminder()
    store.add(row)
    now = row['start'] - 100
    assert store.due(now)
    store.snooze(row['id'], now=now)
    restarted = reminders.ReminderStore(store.path)
    assert not restarted.due(now + 299)
    assert restarted.due(now + 300)
    restarted.snooze(row['id'], at_start=True, now=row['start'] - 10)
    assert not restarted.due(row['start'] - 1)
    assert restarted.due(row['start'])
    with pytest.raises(ValueError):
        restarted.snooze(row['id'], now=row['end'] - 10)
    assert not restarted.due(row['end'])


def test_reminder_snapshot_does_not_wait_for_disk_flush(tmp_path, monkeypatch):
    store = reminders.ReminderStore(str(tmp_path / 'r.json'))
    row = reminder()
    store.add(row)
    entered, release = threading.Event(), threading.Event()
    original = os.fsync
    def delayed(fd):
        entered.set()
        assert release.wait(3)
        return original(fd)
    monkeypatch.setattr(os, 'fsync', delayed)
    thread = threading.Thread(target=lambda: store.remove(row['id']))
    thread.start()
    try:
        assert entered.wait(2)
        start = time.monotonic()
        assert store.list() == [row]
        assert time.monotonic() - start < .2
    finally:
        release.set()
        thread.join(3)
    assert not store.list()


def test_exports_escape_formulae_fold_utf8_and_omit_internal_paths():
    data = tools.recording_csv([dict(title='=SUM(1,2)', channel='TV', date='2026', duration=None,
                                    size=5, status='completed', path='/private/secret', url='secret')])
    rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
    assert rows[1][0] == "'=SUM(1,2)"
    assert b'secret' not in data
    event = tools.programme_calendar('Á' * 100 + '\nEND:VEVENT', 'TV;1,2', 2000000000, 2000003600,
                                     identity='https://user:secret@example.invalid', now=2000000000)
    assert all(len(line) <= 75 for line in event.split(b'\r\n'))
    assert b'secret' not in event and event.count(b'BEGIN:VEVENT') == 1
    unfolded = event.decode().replace('\r\n ', '')
    assert '\\nEND:VEVENT' in unfolded and 'TV\\;1\\,2' in unfolded
    assert 'DTSTART:20330518T033320Z' in unfolded


def test_failed_export_preserves_existing_file(tmp_path, monkeypatch):
    path = tmp_path / 'export.csv'
    path.write_bytes(b'old')
    monkeypatch.setattr(os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('full')))
    with pytest.raises(OSError):
        tools.atomic_export(path, b'new')
    assert path.read_bytes() == b'old' and len(list(tmp_path.iterdir())) == 1


@pytest.mark.skipif(not hasattr(time, 'tzset'), reason='OS TZ fixture requires tzset')
def test_weekdays_skip_dst_gap_keep_overnight_and_jump_over_years(monkeypatch):
    old = os.environ.get('TZ')
    monkeypatch.setenv('TZ', 'Europe/Budapest')
    time.tzset()
    try:
        start = dt.datetime(2027, 3, 21, 2, 30).timestamp()  # Sunday before spring gap
        job = dict(id='a', repeat='weekdays', weekdays=[6], start_ts=start, stop_ts=start + 3600,
                   pre_padding_minutes=0, post_padding_minutes=0)
        nxt = tools.next_weekday_job(job, start + 3600)
        assert dt.datetime.fromtimestamp(nxt['start_ts']) == dt.datetime(2027, 4, 4, 2, 30)
        job.update(weekdays=[0, 1, 2, 3, 4], start_ts=dt.datetime(2027, 1, 1, 23, 30).timestamp(),
                   stop_ts=dt.datetime(2027, 1, 2, 1, 0).timestamp())
        nxt = tools.next_weekday_job(job, dt.datetime(2030, 6, 1).timestamp())
        assert dt.datetime.fromtimestamp(nxt['start_ts']).weekday() < 5
        assert dt.datetime.fromtimestamp(nxt['start_ts']).hour == 23
        assert dt.datetime.fromtimestamp(nxt['stop_ts']).hour == 1
        assert nxt['stop_ts'] > dt.datetime(2030, 6, 1).timestamp()
    finally:
        if old is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = old
        time.tzset()


def test_library_view_rejects_missing_folder_and_unsafe_deleted_mode():
    view = tools.library_view({'folder': '/removed', 'deleted': True, 'sort': [], 'status': {}}, ['/current'])
    assert view['folder'] == '/current' and view['sort'] == 'date' and 'deleted' not in view


def test_background_writes_are_bounded_and_closed_window_gets_no_delivery():
    owner = SimpleNamespace(closed=False)
    callbacks, results = [], []
    entered, release, complete = threading.Event(), threading.Event(), threading.Event()
    def work():
        entered.set()
        assert release.wait(2)
        complete.set()
    dispatch = lambda fn, *args: callbacks.append((fn, args))
    assert start_operation(owner, 'write', work, lambda *args: results.append(args), dispatch)
    assert entered.wait(1)
    assert not start_operation(owner, 'write', work, lambda *args: None, dispatch)
    owner.closed = True
    release.set()
    assert complete.wait(1)
    deadline = time.monotonic() + 1
    while not callbacks and time.monotonic() < deadline:
        time.sleep(.001)
    for fn, args in callbacks:
        fn(*args)
    assert not results and not owner._background_operations


def test_current_hungarian_release_notes_have_no_untranslated_entries():
    from tools.check_hungarian_notes import problems
    assert problems() == []


def test_invalid_repeat_container_cannot_crash_scheduler_completion(tmp_path):
    path = tmp_path / 'dvr.json'
    path.write_text(json.dumps({'jobs': [{'id': 'bad', 'status': 'scheduled', 'repeat': []}]}))
    scheduler = dvr.DVRScheduler(str(path), on_start=lambda job: 1, on_stop=lambda job: None)
    assert scheduler.list_jobs() == [] and scheduler.load_warning


def test_duplicate_saved_schedule_ids_are_not_silently_overwritten(tmp_path):
    path = tmp_path / 'dvr.json'
    path.write_text(json.dumps({'jobs': [{'id': 'same', 'status': 'scheduled', 'title': title}
                                       for title in ['first', 'second']]}))
    raw = path.read_bytes()
    scheduler = dvr.DVRScheduler(str(path), on_start=lambda job: 1, on_stop=lambda job: None)
    assert scheduler.get_job('same')['title'] == 'first'
    assert next(tmp_path.glob('dvr.json.corrupt-*')).read_bytes() == raw


def test_weekday_edit_is_durable_and_cannot_replace_a_running_rule(tmp_path, monkeypatch):
    scheduler = dvr.DVRScheduler(str(tmp_path / 'dvr.json'), on_start=lambda job: 1,
                                 on_stop=lambda job: None, clock=lambda: 1000)
    scheduler.add_job(dict(id='a', status='scheduled', start_ts=2000, stop_ts=3000))
    scheduler.set_weekdays('a', [0, 4])
    assert scheduler.get_job('a')['weekdays'] == [0, 4]
    before = scheduler.get_job('a')
    monkeypatch.setattr(scheduler, '_write_proposal', lambda *args: (_ for _ in ()).throw(OSError('full')))
    with pytest.raises(OSError):
        scheduler.set_weekdays('a', [1])
    assert scheduler.get_job('a') == before
    scheduler._jobs['a']['status'] = 'recording'
    with pytest.raises(ValueError):
        scheduler.set_weekdays('a', [2])
