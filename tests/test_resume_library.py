"""Real model and extracted production UI paths, without native VLC requirements."""
import copy
from types import SimpleNamespace

import pytest
import playback_resume as resume
import vod
from tests.test_playback_resume import frame
from tests.test_subtitle_integration import extract_class, app


def movie(**overrides):
    return dict({'kind': 'movie', 'provider-type': 'xtream', 'provider-id': 'account-A',
                 'resume-type': 'movie', 'resume-id': 12, 'name': 'Same title',
                 'url': 'https://example.invalid/movie/user/password/12.mp4'}, **overrides)


def record(item, **kwargs):
    return resume.checkpoint({}, resume.item_key(item), 60000, 600000, now=1, info=resume.metadata(item), **kwargs)


def test_stable_scoped_identity_does_not_depend_on_url_or_title():
    a = movie()
    key = resume.item_key(a)
    assert key == resume.item_key(movie(url='https://new.invalid/rotated-token', name='Renamed'))
    for changed in [{'provider-id': 'account-B'}, {'resume-id': 13},
                    {'resume-type': 'episode', 'series_id': 8}, {'kind': 'live'}]:
        assert key != resume.item_key(movie(**changed))
    episode = movie(**{'resume-type': 'episode', 'series_id': 8})
    assert resume.item_key(episode) != resume.item_key(dict(episode, series_id=9))


def test_unstructured_playlist_keeps_exact_url_and_source_no_title_guessing():
    a = {'kind': 'movie', 'url': 'one', 'name': 'Same', 'playlist-id': 'A'}
    assert resume.item_key(a) != resume.item_key(dict(a, url='two'))
    assert resume.item_key(a) != resume.item_key(dict(a, **{'playlist-id': 'B'}))
    assert resume.find_current(resume.item_key(a), record(a), [dict(a, url='two')]) is None


def test_exact_legacy_migration_is_lossless_and_cancel_does_not_apply_it():
    item = movie()
    old = resume.legacy_key(item)
    entries = resume.checkpoint({}, old, 90000, 600000, now=10)
    original = copy.deepcopy(entries)
    updated, key = resume.lookup(entries, item)
    assert entries == original
    assert old not in updated and updated[key]['position_ms'] == 90000
    # Existing new-key progress and legacy progress: preserve the newer value.
    combined = dict(updated)
    combined[old] = dict(original[old], position_ms=120000, updated=11)
    assert resume.lookup(combined, item)[0][key]['position_ms'] == 120000
    instance, _, saved, _, config = frame()
    config['playback_bookmarks'] = entries
    instance.__class__.prepare_vod_resume.__globals__['choose_resume'] = lambda *args: 'cancel'
    assert instance.prepare_vod_resume(item) is False
    assert config['playback_bookmarks'] == original and not saved


def test_unscoped_legacy_playlist_is_retained_instead_of_assigned_to_wrong_source():
    item = {'kind': 'movie', 'url': 'same', 'playlist-id': 'A'}
    old = resume.legacy_key(item)
    entries = resume.checkpoint({}, old, 60000, 600000, now=1)
    updated, key = resume.lookup(entries, item)
    assert old in updated and key not in updated


@pytest.mark.parametrize('value', [True, False, None, {}, [], 'x', '0', '01', -1, 1.2])
def test_invalid_provider_ids_fall_back_to_exact_url(value):
    assert resume.item_key(movie(**{'resume-id': value})) == resume.legacy_key(movie())


def test_metadata_whitelist_and_bounds_do_not_persist_stream_addresses_or_extra_fields():
    item = movie()
    data = record(item)
    assert 'password' not in repr(data) and 'example.invalid' not in repr(data)
    key = resume.item_key(item)
    data[key]['metadata']['url'] = item['url']
    assert 'url' not in resume.normalize(data)[key]['metadata']
    assert not resume.metadata(movie(name=item['url'])).get('title')
    assert len(resume.metadata(movie(name='x' * 1000))['title']) == 240
    assert resume.normalize(resume.normalize(data)) == resume.normalize(data)
    assert resume.checkpoint(data, key, 90000, 600000, now=False) == resume.normalize(data)


def test_new_records_keep_metadata_across_old_callers_and_clear_at_completion():
    a = movie();key = resume.item_key(a)
    data = record(a)
    updated = resume.checkpoint(data, key, 90000, 600000, now=2)
    assert updated[key]['metadata'] == data[key]['metadata']
    assert resume.checkpoint(updated, key, 590000, 600000, now=3) == {}


class Client:
    def __init__(self): self.calls = []
    def get_vod_categories(self): return []
    def get_vod_streams(self):
        self.calls.append('movies')
        return [{'stream_id': 12, 'name': 'Renamed', 'container_extension': 'mkv'}]
    def vod_stream_url(self, sid, ext): return f'https://new.invalid/movie/{sid}.{ext}'
    def get_series_info(self, sid):
        self.calls.append(('series', sid))
        return {'episodes': {'2': [{'id': 12, 'title': 'Episode', 'episode_num': 3}]}}
    def series_stream_url(self, sid, ext): return f'https://new.invalid/series/{sid}.{ext}'


def test_movie_resolves_fresh_url_from_the_correct_account_only():
    a = movie();client = Client()
    item = resume.resolve_current(resume.item_key(a), record(a), [], {'account-A': client})
    assert item['url'] == 'https://new.invalid/movie/12.mkv'
    assert resume.item_key(item) == resume.item_key(a)
    assert client.calls == ['movies']
    assert resume.resolve_current(resume.item_key(a), record(a), [], {'account-B': Client()}) is None


def test_episode_fetches_only_its_own_series_and_preserves_episode_identity():
    a = movie(**{'resume-type': 'episode', 'series_id': 8});client = Client()
    item = resume.resolve_current(resume.item_key(a), record(a), [], {'account-A': client})
    assert item['_se'] == (2, 3) and resume.item_key(item) == resume.item_key(a)
    assert client.calls == [('series', '8')]


def test_missing_ambiguous_and_network_failure_are_distinct():
    a = movie();key = resume.item_key(a)
    client = Client();client.get_vod_streams = lambda: []
    assert resume.resolve_current(key, record(a), [], {'account-A': client}) is None
    assert resume.find_current(key, record(a), [a, movie(url='different')]) is None
    def fail(): raise OSError('network')
    client.get_vod_streams = fail
    with pytest.raises(OSError): resume.resolve_current(key, record(a), [], {'account-A': client})


def test_m3u_episodes_are_playable_and_match_without_provider_requests():
    channels = [{'name': f'Show S01E0{i}', 'url': str(i), 'group': 'Series', 'playlist-id': 'A'} for i in (1, 2)]
    _, groups = vod.categorize_m3u_vod(channels)
    episodes = list(resume.playable_items(groups))
    assert len(episodes) == 2 and all(x['kind'] == 'movie' for x in episodes)
    a = episodes[0];client = Client()
    assert resume.resolve_current(resume.item_key(a), record(a), channels, {'other': client})['url'] == a['url']
    assert not client.calls


def test_cancelled_launch_preserves_current_subtitle_session_and_never_plays():
    instance, _, _, env = app(['_launch_stream'])
    instance.default_player = 'Built-in Player'
    instance.show_player_on_enter = True
    instance.__class__._single_stream_provider_has_recording = lambda self, url: False
    frame = SimpleNamespace(prepare_vod_resume=lambda channel: False)
    instance._ensure_internal_player = lambda: frame
    old = instance._subtitle_session.activate_session('builtin-file')
    instance._launch_stream('new-url', channel=movie(), stream_kind='vod')
    assert instance._subtitle_session.session_token == old


def test_modal_checkpoint_updates_to_other_items_are_not_overwritten():
    instance, _, _, _, config = frame()
    another = movie();key = resume.item_key(another)
    def question(*args):
        config['playback_bookmarks'].update(record(another))
        return 'beginning'
    instance.__class__.prepare_vod_resume.__globals__['choose_resume'] = question
    assert instance.prepare_vod_resume({'kind': 'movie', 'url': 'https://example.invalid/movie/test/1.mp4'})
    assert key in config['playback_bookmarks']


def test_deleting_progress_disables_active_checkpoint_without_stopping_playback(monkeypatch):
    import options
    item = movie();key = resume.item_key(item)
    active = SimpleNamespace(_resume_key=key, _save_resume_checkpoint=lambda **kwargs: None)
    saved = []
    monkeypatch.setattr(options, 'load_config', lambda: {'playback_bookmarks': record(item)})
    class Dialog:
        def __init__(self, parent, config, save, resolve):
            save({})
        def ShowModal(self): return 0
        def Destroy(self): pass
    cls, _ = extract_class('main.py', 'IPTVClient', ['_show_continue_watching'], {
        'playback_resume': resume, 'ContinueWatchingDialog': Dialog,
        'XtreamCodesClient': Client, 'save_config': lambda config: saved.append(dict(config)),
        'wx': SimpleNamespace(ID_OK=1), 'show_modal': lambda dialog: dialog.ShowModal(),
    })
    instance = cls();instance.config = {'playback_bookmarks': record(item)}
    instance._internal_player_frame = active
    instance._playlist_load_token = 1
    instance.all_channels = [];instance.vod_groups = {};instance.provider_clients = {}
    instance._show_continue_watching()
    assert active._resume_key == '' and instance.config['playback_bookmarks'] == {} and saved


def test_choice_dialog_maps_escape_to_cancel_and_has_explicit_beginning_label(monkeypatch):
    # Importing this UI module needs wx, but never instantiates a native window.
    import resume_dialogs
    calls = []
    class Message:
        def __init__(self, *args): pass
        def SetYesNoLabels(self, yes, no): calls.append((yes, no))
        def ShowModal(self): return 99
        def Destroy(self): calls.append('destroyed')
    monkeypatch.setattr(resume_dialogs.wx, 'MessageDialog', Message)
    assert resume_dialogs.choose_resume(None, 60000) == 'cancel'
    assert calls == [('Resume', 'Play from Beginning'), 'destroyed']


def dialog_model():
    import datetime
    cls, env = extract_class('resume_dialogs.py', 'ContinueWatchingDialog',
        ['_checked', '_remove', '_clear', '_write', '_close', '_start_check', '_on_destroy'], {
            'playback_resume': resume, 'wx': SimpleNamespace(ID_OK=1, ID_CANCEL=2),
            'datetime': datetime, 'live_announce': SimpleNamespace(speak=lambda text: None),
        })
    instance = cls();instance._closed=False;instance._generation=1;instance._busy=False;instance._status={}
    instance.store_key = 'playback_bookmarks'
    item=movie();key=resume.item_key(item)
    instance.config={'playback_bookmarks':record(item)}
    instance.rows=list(instance.config['playback_bookmarks'].items())
    instance.status=SimpleNamespace(SetLabel=lambda text: None)
    instance.list=SimpleNamespace(SetFocus=lambda: None)
    instance._refresh=lambda *args: None
    instance.EndModal=lambda value: None
    instance._selected_key=lambda: key
    return instance,env,key


def test_late_worker_result_cannot_touch_a_closed_dialog_or_deleted_entry():
    instance, _, key = dialog_model()
    instance._closed=True
    instance.status=None
    instance._checked(1,key,movie(),False,True)  # must not touch dead wx widgets
    instance._closed=False;instance.config['playback_bookmarks']={}
    instance._checked(1,key,movie(),False,True)
    assert not hasattr(instance,'item')


def test_error_and_missing_results_do_not_launch_or_delete_progress():
    instance, _, key=dialog_model()
    before=copy.deepcopy(instance.config)
    instance._checked(1,key,None,True,True)
    assert instance._status[key] == 'Could not check availability.'
    instance._checked(1,key,None,False,True)
    assert instance._status[key] == 'Unavailable or ambiguous'
    assert not hasattr(instance,'item') and instance.config==before


def test_cancelled_remove_clear_and_failed_save_keep_progress():
    instance, _, key=dialog_model()
    instance._confirm=lambda text: False
    instance.save_entries=lambda entries: pytest.fail('cancel must not write')
    instance._remove();instance._clear()
    assert key in instance.config['playback_bookmarks']
    def fail(entries): raise OSError('disk full')
    instance.save_entries=fail
    assert not instance._write({})
    assert key in instance.config['playback_bookmarks']


def test_accepted_beginning_handoff_cannot_resurrect_deleted_progress_on_session_stop():
    instance, _, saved, _, config = frame(False)
    item = {'kind': 'movie', 'url': 'https://example.invalid/movie/test/1.mp4'}
    instance._resume_key = resume.item_key(item)
    assert instance.prepare_vod_resume(item)
    assert not config['playback_bookmarks']
    count = len(saved)
    instance._save_resume_checkpoint(force=True)  # outgoing session's stop()
    assert not config['playback_bookmarks'] and len(saved) == count


def test_custom_modal_guard_remains_active_until_all_nested_dialogs_close(monkeypatch):
    import modal_guard
    seen=[]
    monkeypatch.setattr(modal_guard.wx,'CallAfter',lambda fn: None)
    class Inner:
        def ShowModal(self):
            seen.append(modal_guard.modal_box_is_open())
            raise OSError('dialog failed')
    class Outer:
        def ShowModal(self):
            with pytest.raises(OSError): modal_guard.show_modal(Inner())
            seen.append(modal_guard.modal_box_is_open())
            return 42
    assert modal_guard.show_modal(Outer()) == 42
    assert seen == [True,True] and not modal_guard.modal_box_is_open()


def test_playlist_reload_during_resume_question_preserves_saved_position():
    instance, _, saved, _, config = frame(False)
    before=copy.deepcopy(config)
    instance._resume_validate=lambda: False
    with pytest.raises(RuntimeError,match='playlists changed'):
        instance.prepare_vod_resume({'kind':'movie','url':'https://example.invalid/movie/test/1.mp4'})
    assert config==before and not saved and instance._resume_prepared is None
