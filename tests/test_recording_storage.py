from types import SimpleNamespace
import threading

import pytest

import recorder
import recording_storage as storage


def test_floor_boundary_and_temporary_probe_cleanup(tmp_path,monkeypatch):
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:SimpleNamespace(free=256*storage.MIB))
    assert storage.check_destination(tmp_path)['reserve_mib']==256
    assert list(tmp_path.iterdir())==[]
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:SimpleNamespace(free=256*storage.MIB-1))
    with pytest.raises(storage.StorageError,match='Not enough'):storage.check_destination(tmp_path)
    assert list(tmp_path.iterdir())==[]


def test_unknown_space_readonly_and_file_destination_fail_closed(tmp_path,monkeypatch):
    file=tmp_path/'file';file.write_text('keep')
    with pytest.raises(storage.StorageError):storage.check_destination(file)
    assert file.read_text()=='keep'
    def fail(path):raise OSError('offline')
    monkeypatch.setattr(storage.shutil,'disk_usage',fail)
    with pytest.raises(storage.StorageError,match='determined'):storage.check_destination(tmp_path)
    monkeypatch.setattr(storage.tempfile,'TemporaryFile',lambda **kwargs:(_ for _ in ()).throw(PermissionError('readonly')))
    with pytest.raises(storage.StorageError,match='writable'):storage.check_destination(tmp_path)


@pytest.mark.parametrize('value',[None,False,'100',-1,65537,float('nan')])
def test_invalid_policy_uses_safe_default(value):
    assert storage.normalize_reserve(value)==256


def test_zero_disables_floor_but_keeps_writeability_check(tmp_path,monkeypatch):
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:SimpleNamespace(free=0))
    assert storage.check_destination(tmp_path,0)['reserve_mib']==0


def test_storage_failure_precedes_buffer_lease_file_reservation_and_ffmpeg(tmp_path,monkeypatch):
    manager=recorder.RecordingManager()
    manager.live_buffer_registry=SimpleNamespace(ingest_gate=None)
    def fail(*args):raise storage.StorageError('low space')
    monkeypatch.setattr(storage,'check_destination',fail)
    manager._start_reserved=lambda *a,**kw:pytest.fail('must not launch FFmpeg')
    with pytest.raises(storage.StorageError):manager.start('url','title','provider_mkv',{},str(tmp_path))
    assert not manager._reserved_paths and not manager._recordings


def test_concurrent_starts_are_serialized_through_storage_check_and_registration(tmp_path,monkeypatch):
    manager=recorder.RecordingManager();started=threading.Event();release=threading.Event();calls=[]
    def check(*args):
        calls.append('check')
        if len(calls)==1:
            started.set();assert release.wait(5)
        return {'path':str(tmp_path)}
    monkeypatch.setattr(storage,'check_destination',check)
    manager._start_reserved=lambda *a,**kwargs:calls.append('start')
    first=threading.Thread(target=lambda:manager.start('a','A','provider_mkv',{},str(tmp_path)))
    second=threading.Thread(target=lambda:manager.start('b','B','provider_mkv',{},str(tmp_path)))
    first.start();assert started.wait(5);second.start()
    release.set();first.join(5);second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert calls==['check','start','check','start']


def test_scheduled_storage_failure_is_failed_not_a_phantom_recording(tmp_path,monkeypatch):
    import dvr
    from tests.test_buffer_scheduled_start import client_for_schedule
    manager=recorder.RecordingManager()
    def fail(*args):raise storage.StorageError('low space')
    monkeypatch.setattr(storage,'check_destination',fail)
    client,scheduler,job=client_for_schedule(monkeypatch,tmp_path,manager=manager)
    scheduler._start_job_worker(job['id'],job)
    result=scheduler.get_job(job['id'])
    assert result['status']==dvr.STATUS_FAILED and result['recording_id'] is None
    assert not manager._recordings and not manager._reserved_paths
    assert not result.get('output_path')
