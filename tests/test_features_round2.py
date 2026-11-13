import copy
import json
import threading
from types import SimpleNamespace

import pytest

import episode_continuation
import named_bookmarks
import playback_resume
import recording_library as library
import recording_limits
import recording_power


def test_concurrent_recordings_cannot_both_take_the_last_connection(tmp_path, monkeypatch):
    import recorder
    manager = recorder.RecordingManager()
    key = 'a' * 64
    config = {'recording_connection_limits': {key: 1}}
    manager.connection_policy = lambda url, metadata, active: recording_limits.check_start(config, url, metadata, active)
    monkeypatch.setattr(recorder.recording_storage, 'check_destination', lambda *args: {'path': str(tmp_path)})
    opened = []

    def start_reserved(url, *args, **kwargs):
        rec = SimpleNamespace(url=url, metadata=kwargs['metadata'], buffer_lease=None,
                              process=SimpleNamespace(poll=lambda: None), connection_key='', key=url)
        manager._recordings[url] = rec
        opened.append(url)
        return rec

    monkeypatch.setattr(manager, '_start_reserved', start_reserved)
    barrier = threading.Barrier(3)
    failures = []

    def start(number):
        barrier.wait(timeout=5)
        try:
            manager.start('https://example.invalid/' + str(number), 'Test', recorder.DEFAULT_RECORDING_FORMAT,
                          {}, str(tmp_path), metadata={'recording_account': key})
        except RuntimeError as error:
            failures.append(str(error))

    workers = [threading.Thread(target=start, args=(number,)) for number in (1, 2)]
    for worker in workers:
        worker.start()
    barrier.wait(timeout=5)
    for worker in workers:
        worker.join(timeout=5)
        assert not worker.is_alive()
    assert len(opened) == 1
    assert len(failures) == 1 and 'limit' in failures[0]
    assert len(manager.list_active()) == 1


def test_recording_trash_rejects_directory_redirection(tmp_path, monkeypatch):
    from pathlib import Path
    trash = tmp_path / '.iptv-recording-trash'
    trash.mkdir()
    original_resolve = Path.resolve
    monkeypatch.setattr(Path, 'resolve', lambda self, *a, **kw: tmp_path / 'elsewhere'
                        if self == trash else original_resolve(self, *a, **kw))
    with pytest.raises(ValueError, match='trash'):
        library.scan_trash(tmp_path)


def test_named_bookmarks_are_separate_from_resume_and_keep_multiple_positions():
    resume = {'unchanged': 123}
    key = 'a' * 64
    value = named_bookmarks.put({}, key, 'Első jelenet', 0)
    value = named_bookmarks.put(value, key, 'Második jelenet', 23000)
    assert [row['position_ms'] for row in value[key]] == [0, 23000]
    original = copy.deepcopy(value)
    renamed = named_bookmarks.put(value, key, 'Bevezető', 0, identity=value[key][0]['id'])
    assert value == original
    assert renamed[key][0]['name'] == 'Bevezető'
    assert len(named_bookmarks.remove(value, key, value[key][0]['id'])[key]) == 1
    assert resume == {'unchanged': 123}
    with pytest.raises(ValueError):
        named_bookmarks.put(value, key, 'MÁSODIK JELENET', 123)


@pytest.mark.parametrize('name,position', [('', 1), ('a\nb', 1), ('x' * 121, 1), ('a', True), ('a', -1)])
def test_bad_bookmarks_never_mutate_the_caller(name, position):
    source = {}
    with pytest.raises(ValueError):
        named_bookmarks.put(source, 'a' * 64, name, position)
    assert source == {}


def test_notification_overflow_keeps_recent_entries_and_filters_shared_secrets():
    history = []
    for index in range(205):
        history = named_bookmarks.notification(history, str(index), 'Ready\nhttps://example.invalid/private', now=index)
    assert len(history) == 200 and history[0]['caption'] == '5'
    assert history[-1]['message'] == 'Ready\n[***]'


def episode(number, **changes):
    return dict({'name': str(number), 'url': 'https://example.invalid/' + str(number), 'kind': 'movie',
                 'provider-type': 'xtream', 'provider-id': 'provider', 'series_id': '12',
                 'resume-type': 'episode', 'resume-id': str(number)}, **changes)


def test_next_episode_requires_unique_identity_and_same_account_and_series():
    a, b, c = episode(1), episode(2), episode(3)
    assert episode_continuation.following_item(a, [a, b, c]) == b
    assert episode_continuation.following_item(c, [a, b, c]) is None
    assert episode_continuation.following_item(a, [a, a, b]) is None
    assert episode_continuation.following_item(a, [a, b, b]) is None
    assert episode_continuation.following_item(a, [a, episode(2, series_id='99')]) is None
    assert episode_continuation.following_item(a, [a, episode(2, **{'provider-id': 'other'})]) is None


@pytest.mark.parametrize('kind,seen,manual,position,length,expected', [
    ('vod', True, False, 100000, 100000, True), ('live', True, False, 100000, 100000, False),
    ('vod', False, False, 100000, 100000, False), ('vod', True, True, 100000, 100000, False),
    ('vod', True, False, 100, 100000, False), ('vod', True, False, -1, 100000, False),
    ('vod', True, False, 0, 0, False),
])
def test_only_natural_completion_can_start_another_episode(kind, seen, manual, position, length, expected):
    assert episode_continuation.natural_end(kind, seen, manual, position, length) is expected


def recording(tmp_path):
    path = tmp_path / 'fixture.mkv'
    path.write_bytes(b'media fixture')
    return path, library.scan(tmp_path)[0]


def test_recording_rename_trash_restore_keeps_contents_and_resume_identity(tmp_path):
    path, row = recording(tmp_path)
    before = playback_resume.item_key(library.playback_channel(tmp_path, row))
    library.rename_title(tmp_path, row, 'Átnevezett felvétel')
    row = library.scan(tmp_path)[0]
    assert row['title'] == 'Átnevezett felvétel'
    assert playback_resume.item_key(library.playback_channel(tmp_path, row)) == before
    library.trash(tmp_path, row)
    assert not path.exists() and library.scan(tmp_path) == []
    deleted = library.scan_trash(tmp_path)
    assert len(deleted) == 1 and deleted[0]['title'] == row['title']
    library.restore(tmp_path, deleted[0])
    assert path.read_bytes() == b'media fixture'
    assert library.scan_trash(tmp_path) == []
    assert playback_resume.item_key(library.playback_channel(tmp_path, library.scan(tmp_path)[0])) == before


def test_restore_never_overwrites_another_recording(tmp_path):
    path, row = recording(tmp_path)
    library.trash(tmp_path, row)
    path.write_bytes(b'new recording')
    with pytest.raises(FileExistsError):
        library.restore(tmp_path, library.scan_trash(tmp_path)[0])
    assert path.read_bytes() == b'new recording'
    assert len(library.scan_trash(tmp_path)) == 1


@pytest.mark.parametrize('operation', ['delete', 'trash', 'rename_title'])
def test_metadata_save_failure_cannot_remove_a_recording(tmp_path, monkeypatch, operation):
    path, row = recording(tmp_path)
    def fail(*args):
        raise OSError('fixture: no disk space')
    monkeypatch.setattr(library, '_write', fail)
    args = ('New title',) if operation == 'rename_title' else ()
    with pytest.raises(OSError):
        getattr(library, operation)(tmp_path, row, *args)
    assert path.read_bytes() == b'media fixture'


def test_trash_move_failure_leaves_original_and_no_false_deleted_row(tmp_path, monkeypatch):
    path, row = recording(tmp_path)
    original_replace = library.os.replace
    def replace(a, b):
        if str(a) == str(path):
            raise PermissionError('fixture: in use')
        original_replace(a, b)
    monkeypatch.setattr(library.os, 'replace', replace)
    with pytest.raises(PermissionError):
        library.trash(tmp_path, row)
    assert path.exists() and not library.scan_trash(tmp_path)


def test_trash_cannot_move_an_active_or_replaced_file(tmp_path):
    path, row = recording(tmp_path)
    with pytest.raises(ValueError):
        library.trash(tmp_path, row, [str(path)])
    path.write_bytes(b'replacement')
    with pytest.raises(ValueError):
        library.trash(tmp_path, row)
    assert path.read_bytes() == b'replacement'


def test_permanent_deletion_of_trashed_file_is_explicit(tmp_path):
    path, row = recording(tmp_path)
    library.trash(tmp_path, row)
    library.delete_trashed(tmp_path, library.scan_trash(tmp_path)[0])
    assert not path.exists() and not library.scan_trash(tmp_path)


def test_budget_counts_peak_concurrency_not_total_overlaps():
    channel = {'url': 'https://example.invalid/live/user/fixture/123.ts'}
    other = {'url': 'https://example.invalid/live/other/fixture/123.ts'}
    key = recording_limits.channel_key(channel, {})
    config = {'recording_connection_limits': {key: 2}}
    jobs = [{'id': str(n), 'channel': channel, 'status': 'scheduled', 'start_ts': a, 'stop_ts': b}
            for n, (a, b) in enumerate(((0, 30), (30, 60), (60, 90)))]
    jobs.append({'id': 'other', 'channel': other, 'status': 'scheduled', 'start_ts': 0, 'stop_ts': 100})
    assert recording_limits.peak_demand(config, channel, 0, 100, jobs) == (2, 2)
    assert recording_limits.warning(config, channel, 0, 100, jobs) == ''
    jobs.append({'id': 'extra', 'channel': channel, 'status': 'scheduled', 'start_ts': 20, 'stop_ts': 40})
    assert recording_limits.peak_demand(config, channel, 0, 100, jobs) == (3, 2)
    assert recording_limits.warning(config, channel, 0, 100, jobs)
    assert 'fixture' not in json.dumps(config)


def test_account_budget_does_not_count_recordings_from_a_shared_buffer_twice():
    url = 'https://example.invalid/live/user/fixture/123.ts'
    key = recording_limits.channel_key({'url': url}, {})
    config = {'recording_connection_limits': {key: 1}}
    rec = SimpleNamespace(url=url, metadata={'recording_account': key}, buffer_lease=None)
    with pytest.raises(RuntimeError):
        recording_limits.check_start(config, url, {}, [rec])
    rec.buffer_lease = object()
    assert recording_limits.check_start(config, url, {}, [rec]) == key


def test_power_timer_follows_only_pending_jobs_and_guards_the_wake_interval():
    job = {'status': 'scheduled', 'start_ts': 1000}
    config = {'wake_for_recordings': True}
    assert recording_power.desired_state(config, False, [job], 100) == (False, 940)
    assert recording_power.desired_state(config, False, [job], 950) == (True, None)
    assert recording_power.desired_state(config, True, [], 100) == (True, None)
    assert recording_power.desired_state({}, False, [job], 100) == (False, None)
    assert recording_power.desired_state(config, False, [dict(job, status='canceled')], 100) == (False, None)


def test_power_backend_is_released_on_the_same_thread_after_failure():
    calls, errors = [], []
    ready = threading.Event()
    class Backend:
        def update(self, *state):
            calls.append(('update', threading.get_ident()))
            raise OSError('fixture failure')
        def close(self):
            calls.append(('close', threading.get_ident()))
    def on_error(error):
        errors.append(error)
        ready.set()
    manager = recording_power.RecordingPower(lambda: ({}, True, []), on_error, backend_factory=Backend)
    manager.start()
    assert ready.wait(2)
    manager.close()
    assert len(errors) == 1
    assert calls == [('update', calls[0][1]), ('close', calls[0][1])]
    assert calls[0][1] != threading.get_ident()
