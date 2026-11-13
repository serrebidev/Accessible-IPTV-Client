"""Fault-injection coverage for schedule and recording-library changes."""
import copy
import json

import pytest

import dvr
from types import SimpleNamespace
from main import IPTVClient


def scheduler(tmp_path):
    return dvr.DVRScheduler(str(tmp_path / 'schedule.json'),
                            on_start=lambda job: None, on_stop=lambda job: None,
                            clock=lambda: 1000)


@pytest.mark.parametrize('operation,args', [
    ('cancel_job', ()), ('delete_job', ()), ('set_repeat', ('weekly',)),
])
def test_failed_schedule_change_keeps_memory_and_disk(tmp_path, monkeypatch, operation, args):
    s = scheduler(tmp_path)
    s.add_job({'id': 'parent', 'status': 'scheduled', 'repeat': 'series',
               'start_ts': 2000, 'stop_ts': 3000})
    s.add_job({'id': 'child', 'status': 'scheduled', 'series_source': 'parent',
               'start_ts': 4000, 'stop_ts': 5000})
    before = copy.deepcopy(s.list_jobs())
    saved = (tmp_path / 'schedule.json').read_bytes()
    def fail(*args):
        raise PermissionError('fixture: replace refused')
    monkeypatch.setattr(dvr.os, 'replace', fail)
    with pytest.raises(PermissionError):
        getattr(s, operation)('parent', *args)
    assert s.list_jobs() == before
    assert (tmp_path / 'schedule.json').read_bytes() == saved
    assert sorted(p.name for p in tmp_path.iterdir()) == ['schedule.json']


@pytest.mark.parametrize('damaged', ['{"jobs": [', '{"jobs": "invalid"}', 'null'])
def test_unreadable_schedule_is_preserved_before_replacement(tmp_path, damaged):
    path = tmp_path / 'schedule.json'
    path.write_text(damaged)
    s = scheduler(tmp_path)
    s.add_job({'id': 'new', 'status': 'scheduled', 'start_ts': 2000, 'stop_ts': 3000})
    backups = list(tmp_path.glob('schedule.json.corrupt-*'))
    assert len(backups) == 1
    assert backups[0].read_text() == damaged
    assert s.load_warning
    assert [j['id'] for j in json.loads(path.read_text())['jobs']] == ['new']


def test_unreadable_schedule_cannot_be_replaced_if_preservation_fails(tmp_path, monkeypatch):
    path = tmp_path / 'schedule.json'
    path.write_bytes(b'damaged')
    def fail(self):
        raise OSError('fixture: backup refused')
    monkeypatch.setattr(dvr.DVRScheduler, '_preserve_corrupt_schedule', fail, raising=False)
    s = scheduler(tmp_path)
    with pytest.raises(OSError):
        s.add_job({'id': 'new', 'status': 'scheduled', 'start_ts': 2000, 'stop_ts': 3000})
    assert path.read_bytes() == b'damaged'
    assert s.list_jobs() == []


def test_cancel_stops_a_recording_that_finished_starting_during_the_request():
    job = {'id': 'fixture', 'status': 'scheduled', 'recording_id': None}
    def cancel(identity):
        job.update(status='canceled', recording_id=19)
        return True
    schedule = SimpleNamespace(get_job=lambda identity: dict(job), cancel_job=cancel)
    stopped = []
    owner = SimpleNamespace(_ensure_dvr_scheduler=lambda **kwargs: schedule, _stop_scheduled_recording=stopped.append)
    assert IPTVClient._cancel_scheduled_recording(owner, 'fixture')
    assert stopped[0]['recording_id'] == 19
