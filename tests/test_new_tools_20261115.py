"""Functional and responsiveness contracts for the four November 15 tools."""
import copy
import threading
import time
from types import SimpleNamespace

import pytest
import wx

from background_tasks import LatestTask
import episode_continuation as episodes
import episode_continuation_ui as episode_ui
from media_navigation_ui import MediaNavigationMixin
import recording_conflicts_ui as conflicts
import recording_library as library
from recording_library_ui import RecordingLibraryDialog
import shortcuts


def test_latest_worker_keeps_only_one_pending_request_and_never_delivers_stale_data():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    dispatched, results, ran = [], [], []
    main_thread = threading.get_ident()
    worker = LatestTask(dispatched.append)
    def blocked(canceled):
        assert threading.get_ident() != main_thread
        entered.set()
        assert release.wait(5)
        assert canceled()
        return 'stale'
    def latest(canceled):
        ran.append('latest')
        finished.set()
        return 'latest'
    try:
        worker.submit(blocked, lambda value, error: results.append(value))
        assert entered.wait(2)
        for index in range(100):
            worker.submit(lambda cancel: ran.append('superseded'), lambda *args: None)
        worker.submit(latest, lambda value, error: results.append(value))
        release.set()
        assert finished.wait(2)
        deadline = time.monotonic() + 2
        while not dispatched and time.monotonic() < deadline:
            time.sleep(.001)
        assert ran == ['latest']
        for callback in dispatched:
            callback()
        assert results == ['latest']
    finally:
        release.set()
        worker.close()


def test_closing_worker_suppresses_already_dispatched_callbacks():
    dispatched, called = [], []
    worker = LatestTask(dispatched.append)
    try:
        worker.submit(lambda canceled: 1, lambda *args: called.append(args))
        deadline = time.monotonic() + 2
        while not dispatched and time.monotonic() < deadline:
            time.sleep(.001)
        assert dispatched
        worker.close()
        dispatched[0]()
        assert called == []
    finally:
        worker.close()


def test_a_library_lock_on_one_directory_does_not_block_another(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir(); b.mkdir()
    (b / 'fixture.mkv').write_bytes(b'media')
    row = library.scan(b)[0]
    complete = threading.Event()
    errors = []
    def rename():
        try:
            library.rename_title(b, row, 'New title')
        except Exception as error:
            errors.append(error)
        finally:
            complete.set()
    with library._lock_for(a):
        thread = threading.Thread(target=rename)
        thread.start()
        assert complete.wait(2), 'unrelated library shared the locked drive gate'
    thread.join(2)
    assert not errors and library.scan(b)[0]['title'] == 'New title'


def test_query_rows_sorts_filters_and_does_not_mutate_its_input():
    rows = [dict(path=str(i), title=title, channel='TV', date='2026', status=state,
                 size=size, duration=duration, modified_ns=i)
            for i, title, state, size, duration in (
                (1, 'Árvíz', 'partial', 300, None), (2, 'Esti film', 'completed', 100, 60),
                (3, 'Híradó', 'partial', 200, 120))]
    before = copy.deepcopy(rows)
    assert [r['size'] for r in library.query_rows(rows, status='partial', sort='size')] == [300, 200]
    assert library.query_rows(rows, query='ÁRVÍZ')[0]['title'] == 'Árvíz'
    assert [r['path'] for r in library.query_rows(rows, sort='duration', descending=False)] == ['1', '2', '3']
    assert rows == before


def item(number, **changes):
    return dict({'kind':'movie','url':f'https://example.invalid/{number}','name':str(number),
                 'provider-type':'xtream','provider-id':'fixture','series_id':'7',
                 'resume-type':'episode','resume-id':str(number)}, **changes)


def test_manual_episode_navigation_rejects_boundaries_duplicates_and_other_series():
    a, b, c = item(1), item(2), item(3)
    assert episodes.adjacent_item(b, [a,b,c], -1) == a
    assert episodes.adjacent_item(b, [a,b,c], 1) == c
    assert episodes.adjacent_item(a, [a,b,c], -1) is None
    assert episodes.adjacent_item(c, [a,b,c], 1) is None
    assert episodes.adjacent_item(b, [a,b,b,c], -1) is None
    assert episodes.adjacent_item(b, [item(1,series_id='8'),b], -1) is None


def test_manual_episode_lookup_stays_in_background_and_discards_a_newer_playback(monkeypatch):
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    calls, delivered = [], []
    class Client:
        def get_series_info(self, series_id):
            entered.set()
            assert release.wait(5)
            return {'episodes': {'1':[{'id':1,'episode_num':1}, {'id':2,'episode_num':2}]}}
        def series_stream_url(self, identity, extension):
            return f'https://example.invalid/{identity}'
    owner = SimpleNamespace(provider_clients={'fixture':Client()}, _continuation_request=1,
                            _playlist_load_token=1, _launch_stream=lambda *a, **k: calls.append(a))
    player = SimpleNamespace(_current_stream_kind='vod', _episode_channel=item(1), _episode_queue=[],
                             _vlc_generation=1, GetParent=lambda:owner,
                             _navigation_message=lambda text:calls.append(text))
    def dispatch(callback,*args):
        delivered.append((callback,args))
        done.set()
    monkeypatch.setattr(episode_ui.wx,'CallAfter',dispatch)
    episode_ui.navigate(player,1)
    assert entered.wait(2) and player._episode_navigation_busy
    assert calls == []
    player._vlc_generation=2
    release.set()
    assert done.wait(2)
    for callback,args in delivered: callback(*args)
    assert calls == [] and not player._episode_navigation_busy


def test_subtitle_timing_uses_microseconds_and_invalidates_old_speech():
    calls=[]
    class Source:
        generation=3
        def seeked(self): self.generation+=1
    frame=SimpleNamespace(player=SimpleNamespace(video_set_spu_delay=lambda value:calls.append(value) or 0),
        _subtitle_sink=SimpleNamespace(clear=lambda:calls.append('clear')), _subtitle_file_source=Source(),
        subtitle_label=SimpleNamespace(SetLabel=lambda value:calls.append(value)),
        _navigation_message=lambda text:calls.append(text))
    MediaNavigationMixin._apply_subtitle_timing(frame,1500)
    assert calls[:2] == [1500000,'clear']
    assert frame._subtitle_generation == 4 and frame._review_cue_index is None
    before=list(calls)
    with pytest.raises(ValueError): MediaNavigationMixin._apply_subtitle_timing(frame,600001)
    assert calls==before
    frame.player.video_set_spu_delay=lambda value:-1
    with pytest.raises(ValueError): MediaNavigationMixin._apply_subtitle_timing(frame,0)
    assert calls==before


def test_new_defaults_preserve_existing_personal_shortcuts():
    config={'shortcuts':{'player.audio_track':'Ctrl+PageUp'}}
    effective=shortcuts.effective(config,'player')
    expected=shortcuts.parse('Ctrl+PageUp')[:2]
    assert shortcuts.parse(effective['audio_track'])[:2]==expected
    assert shortcuts.parse(effective['previous_episode'])[:2]!=expected
    assert len({shortcuts.parse(value)[:2] for value in effective.values()})==len(effective)


def test_conflict_details_include_padding_and_filter_the_account_budget():
    a={'url':'https://example.invalid/live/a/pass/1.ts'}
    b={'url':'https://example.invalid/live/b/pass/1.ts'}
    key=conflicts.recording_limits.channel_key(a,{})
    config={'recording_connection_limits':{key:1}}
    jobs=[dict(id=str(i), channel=channel, title='Title', start_ts=start, stop_ts=end,
               status=status, pre_padding_minutes=2, post_padding_minutes=3)
          for i,channel,start,end,status in [(1,a,90,200,'scheduled'),(2,b,100,180,'scheduled'),
                                            (3,a,200,300,'scheduled'),(4,a,100,180,'completed')]]
    rows=conflicts.conflict_rows(config,a,100,200,jobs)
    assert [r['job']['id'] for r in rows]==['1']
    assert rows[0]['start']==90 and rows[0]['job']['pre_padding_minutes']==2
    assert conflicts.conflict_rows(config,a,100,200,jobs,exclude='1')==[]
    assert len(conflicts.conflict_rows({},a,100,200,jobs))==2


@pytest.fixture
def gui_owner(tmp_path):
    app=wx.GetApp() or wx.App(False)
    wx.Log.SetActiveTarget(wx.LogStderr())
    frame=wx.Frame(None)
    frame.config={'recordings_dir':str(tmp_path)}
    frame.recorder=SimpleNamespace(list_active=lambda:[])
    frame._launch_stream=lambda *args,**kwargs:None
    yield app,frame
    frame.Destroy()
    app.Yield()


def drain(app,ready):
    deadline=time.monotonic()+5
    while not ready() and time.monotonic()<deadline:
        app.Yield()
        time.sleep(.005)
    assert ready(), 'native dialog worker did not finish'


def test_real_virtual_library_combines_folders_and_preserves_multiple_selection(gui_owner,tmp_path):
    app,owner=gui_owner
    other=tmp_path/'other';other.mkdir()
    (tmp_path/'first.mkv').write_bytes(b'first')
    (other/'second.mkv').write_bytes(b'second')
    owner.config['recording_library_folders']=[str(other)]
    dialog=RecordingLibraryDialog(owner)
    try:
        drain(app,lambda:not dialog.busy and not dialog.filter_busy)
        dialog.folder.SetSelection(len(dialog.directories));dialog.change_folder(None)
        drain(app,lambda:not dialog.busy and not dialog.filter_busy)
        assert len(dialog.rows)==2 and dialog.list.GetItemCount()==2
        assert dialog.list.HasFlag(wx.LC_VIRTUAL) and not dialog.list.HasFlag(wx.LC_SINGLE_SEL)
        dialog.list.SetItemState(-1,wx.LIST_STATE_SELECTED,wx.LIST_STATE_SELECTED)
        dialog.selection_changed()
        assert len(dialog.selected_rows())==2
        assert dialog.remove.IsEnabled() and not dialog.play.IsEnabled()
        assert '2' in dialog.status.GetLabel()
        dialog.search.ChangeValue('second');dialog.filter()
        drain(app,lambda:not dialog.filter_busy)
        assert len(dialog.rows)==1 and dialog.rows[0]['title']=='second'
        assert dialog.play.IsEnabled()
    finally:
        dialog.Destroy();app.Yield()


def test_subtitle_timing_dialog_has_native_controls_and_cancel_preserves_the_delay(gui_owner,monkeypatch):
    import media_navigation_ui
    app,frame=gui_owner
    changes=[]
    frame._vlc_generation=1
    frame.player=SimpleNamespace(video_get_spu_delay=lambda:1500000)
    frame._apply_subtitle_timing=changes.append
    frame._navigation_message=lambda text:pytest.fail(text)
    def inspect(dialog):
        fields=[child for child in dialog.GetChildren() if isinstance(child,wx.SpinCtrl)]
        assert len(fields)==1 and fields[0].GetValue()==1500
        assert fields[0].GetIncrement()==500
        return wx.ID_CANCEL
    monkeypatch.setattr(media_navigation_ui,'show_modal',inspect)
    MediaNavigationMixin._subtitle_timing(frame)
    assert changes==[]
    app.Yield()


def test_real_conflict_dialog_displays_padded_windows_and_account_alias(gui_owner):
    app,owner=gui_owner
    channel={'url':'https://example.invalid/live/user/pass/1.ts','name':'TV','provider-id':'p'}
    owner.config['playlists']=[{'id':'p','name':'My provider'}]
    job=dict(id='one',channel=channel,title='News',start_ts=1900000000,stop_ts=1900003600,
             pre_padding_minutes=2,post_padding_minutes=3,status='scheduled')
    owner._ensure_dvr_scheduler=lambda:SimpleNamespace(list_jobs=lambda **kw:[job])
    dialog=conflicts.RecordingConflictsDialog(owner,channel,1900000100,1900000200)
    try:
        drain(app,lambda:dialog.list.GetItemCount()==1)
        dialog.select()
        assert 'My provider' in dialog.details.GetValue()
        assert '2' in dialog.details.GetValue() and dialog.edit.IsEnabled()
        assert dialog.list.HasFlag(wx.LC_VIRTUAL)
        assert 'pass' not in dialog.details.GetValue()
    finally:
        dialog.Destroy();app.Yield()


def test_local_positions_have_a_separate_continue_watching_store(gui_owner):
    from resume_dialogs import ContinueWatchingDialog
    app,owner=gui_owner
    vod_key,local_key='a'*64,'b'*64
    entry={'position_ms':60000,'length_ms':180000,'updated':1900000000}
    owner.config.update(playback_bookmarks={vod_key:dict(entry)},recording_playback_bookmarks={local_key:dict(entry)})
    written=[]
    def save(entries,store='playback_bookmarks'):
        written.append(store);owner.config[store]=entries
    dialog=ContinueWatchingDialog(owner,owner.config,save,lambda *args:None)
    try:
        assert dialog.rows[0][0]==vod_key
        dialog.source.SetSelection(1);dialog._change_source(None)
        assert dialog.rows[0][0]==local_key
        assert dialog._write({})
        assert written==['recording_playback_bookmarks']
        assert local_key not in owner.config['recording_playback_bookmarks']
        assert vod_key in owner.config['playback_bookmarks']
    finally:
        dialog.Destroy();app.Yield()


@pytest.mark.parametrize('fail', [False, True])
def test_history_writer_returns_before_disk_finishes_and_publishes_only_success(gui_owner,fail):
    from resume_dialogs import ContinueWatchingDialog
    app,owner=gui_owner
    key='a'*64
    previous={key:{'position_ms':60000,'length_ms':180000,'updated':1900000000}}
    owner.config['playback_bookmarks']=copy.deepcopy(previous)
    entered,release,finished=threading.Event(),threading.Event(),threading.Event()
    main_thread=threading.get_ident()
    changes=[]
    def save(*args): pytest.fail('the disk save ran synchronously')
    def persist(entries,store):
        assert threading.get_ident()!=main_thread
        entered.set()
        assert release.wait(5)
        finished.set()
        if fail: raise OSError('fixture: full disk')
    def applied(entries,store):
        assert threading.get_ident()==main_thread
        owner.config[store]=entries
    save.persist=persist;save.applied=applied
    save.writing=lambda store,active:changes.append(active)
    dialog=ContinueWatchingDialog(owner,owner.config,save,lambda *args:None)
    try:
        assert dialog._write({})
        assert entered.wait(2)
        assert dialog._busy and owner.config['playback_bookmarks']==previous
        assert changes==[True]
        release.set()
        drain(app,lambda:not dialog._busy)
        assert finished.is_set() and changes==[True,False]
        assert owner.config['playback_bookmarks']==(previous if fail else {})
    finally:
        release.set();dialog.Destroy();app.Yield()


def test_pending_history_write_prevents_an_old_checkpoint_from_recreating_deleted_progress():
    import internal_player
    frame=SimpleNamespace(_resume_history_write_pending=True)
    # No player/config attributes: returning must precede all native and disk work.
    internal_player.InternalPlayerFrame._save_resume_checkpoint(frame,force=True)
