"""Failure-path regressions from the November 15 source review."""
import json
from types import SimpleNamespace

import pytest

import playback_resume
import providers
import recording_library as library


def recording(tmp_path):
    path = tmp_path / 'fixture.mkv'
    path.write_bytes(b'media fixture')
    return path, library.scan(tmp_path)[0]


def test_corrupt_library_index_is_preserved_before_rename(tmp_path):
    path, row = recording(tmp_path)
    index = tmp_path / '.iptv-recordings.json'
    damaged = b'{"original title": '
    index.write_bytes(damaged)
    library.rename_title(tmp_path, row, 'New title')
    backups = list(tmp_path.glob('.iptv-recordings.json.corrupt-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == damaged
    assert path.read_bytes() == b'media fixture'


def test_malformed_library_status_is_not_passed_to_the_gui(tmp_path):
    path, row = recording(tmp_path)
    (tmp_path / '.iptv-recordings.json').write_text(json.dumps({
        path.name: dict(row, status=[], duration=float('nan'))}))
    loaded = library.scan(tmp_path)[0]
    assert loaded['status'] == 'unknown' and loaded['duration'] is None


def test_local_resume_resolves_a_real_recording_only_with_the_same_signature(tmp_path):
    path, row = recording(tmp_path)
    channel = library.playback_channel(tmp_path, row)
    key = playback_resume.item_key(channel)
    entries = playback_resume.checkpoint({}, key, 60000, 180000, now=1900000000)
    resolved = library.resolve_resume(key, entries, [str(tmp_path)])
    assert resolved['local-recording'] == str(path)
    path.write_bytes(b'a replacement recording')
    assert library.resolve_resume(key, entries, [str(tmp_path)]) is None


@pytest.mark.parametrize('method', ['get_vod_streams', 'get_vod_categories', 'get_series', 'get_series_categories'])
def test_unexpected_provider_object_is_not_an_empty_catalogue(monkeypatch, method):
    client = providers.XtreamCodesClient(providers.XtreamCodesConfig(
        base_url='https://example.invalid', username='fixture', password='fixture'))
    monkeypatch.setattr(client, '_player_api', lambda *a, **kw: {'user_info': {'auth': 0}})
    with pytest.raises(providers.ProviderError):
        getattr(client, method)()


def test_failed_history_save_keeps_the_original_in_memory(monkeypatch):
    import main
    import options
    import wx
    previous = {'a' * 64: {'position_ms': 60000, 'length_ms': 180000, 'updated': 1900000000}}
    owner = SimpleNamespace(config={'playback_bookmarks': previous}, _playlist_load_token=1,
                            all_channels=[], vod_groups={}, displayed=[], provider_clients={})
    monkeypatch.setattr(options, 'load_config', lambda: dict(owner.config))
    class Dialog:
        def __init__(self, parent, config, save, resolve):
            with pytest.raises(OSError):
                save({})
        def Destroy(self):
            pass
    monkeypatch.setattr(main, 'ContinueWatchingDialog', Dialog)
    monkeypatch.setattr(main, 'save_config', lambda config: False)
    monkeypatch.setattr(main, 'show_modal', lambda dialog: wx.ID_CANCEL)
    main.IPTVClient._show_continue_watching(owner)
    assert owner.config['playback_bookmarks'] == previous
