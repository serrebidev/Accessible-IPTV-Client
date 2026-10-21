import threading
import types

import main


def _app(sources):
    app = types.SimpleNamespace(playlist_sources=sources, spoken=[], loads=[])
    app._speak = app.spoken.append
    app.start_playlist_load = lambda only=None: app.loads.append(only)
    return app


def _refresh_app(sources, previous_channels=()):
    """A frame stub carrying what a playlist refresh touches."""
    app = types.SimpleNamespace()
    app.config = {"playlists": list(sources)}
    app._playlist_load_token = 1
    app.all_channels = list(previous_channels)
    app.channels_by_group = {}
    app.provider_clients = {}
    app.provider_epg_sources = []
    app.playlist_epg_by_source = {}
    app.vod_loaded = True
    app.vod_groups = {}
    app.vod_group_order = []
    app.view_mode = "live"
    app.spoken = []
    app._speak = app.spoken.append
    app._program_match_cache = None
    app._parsed_cache_path_for_key = lambda _key: ""
    app._invalidate_favorites_cache = lambda: None
    app.reload_epg_sources = lambda: None
    app._fill_playlist_scope_combo = lambda: None
    app._refresh_group_ui = lambda: None
    app._cleanup_cache_and_channels = lambda caches: None
    app.start_refresh_timer = lambda: None
    app._schedule_auto_update_check = lambda: None
    app._announce_playlists_refreshed = "Playlist refreshed: Sports"
    app._announce_playlists_refresh_failed = "Playlist refresh failed: Sports"
    return app


def test_refresh_drops_the_downloaded_copy_and_reloads_only_that_playlist(tmp_path, monkeypatch):
    url = "http://example.com/tv.m3u"
    cached = tmp_path / "tv.m3u"
    cached.write_text("#EXTM3U", encoding="utf-8")
    monkeypatch.setattr(main, "get_cache_path_for_url", lambda _u: str(cached))
    app = _app([url, "http://example.com/other.m3u"])

    main.IPTVClient._refresh_playlist_sources(app, [url], "Sports")

    assert not cached.exists()
    assert app.loads == [[url]]
    assert "Sports" in app.spoken[0]
    assert "Sports" in app._announce_playlists_refreshed


def test_refresh_after_select_all_reloads_everything(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "get_cache_path_for_url", lambda _u: str(tmp_path / "x.m3u"))
    sources = ["http://example.com/a.m3u", "http://example.com/b.m3u"]
    app = _app(sources)

    main.IPTVClient._refresh_playlist_sources(app, list(sources), None)

    assert app.loads == [None]


def test_refresh_of_an_unsaved_playlist_asks_for_ok_first():
    app = _app(["http://example.com/saved.m3u"])

    main.IPTVClient._refresh_playlist_sources(app, ["http://example.com/new.m3u"], "New")

    assert app.loads == []
    assert len(app.spoken) == 1


def test_a_failed_refresh_keeps_the_channels_and_says_it_failed(monkeypatch, tmp_path):
    """A playlist that cannot be downloaded must not disappear.

    The refresh dropped every channel of the source it failed to fetch and
    announced "Playlist refreshed", so a provider that was briefly down took
    the user's channels with it. The channels the source had are kept, and
    the failure is announced.
    """
    url = "http://example.invalid/tv.m3u"
    monkeypatch.setattr(main, "get_cache_path_for_url", lambda _u: str(tmp_path / "tv.m3u"))
    monkeypatch.setattr(main, "save_config", lambda _cfg: None)
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))

    def _boom(*_args, **_kwargs):
        raise OSError("the provider is down")

    monkeypatch.setattr(main.urllib.request, "urlopen", _boom)

    scope_id = main._source_scope_id(url)
    previous = [{"name": "Sports 1", "url": "http://example/1", "playlist-id": scope_id}]
    app = _refresh_app([url], previous)

    main.IPTVClient._do_playlist_refresh(
        app, 1, only=[url], keep=(list(previous), {}, [], {}))

    assert [ch["name"] for ch in app.all_channels] == ["Sports 1"]
    assert app.spoken == ["Playlist refresh failed: Sports"]


def test_a_failed_refresh_in_a_full_load_keeps_the_channels_too(monkeypatch, tmp_path):
    """The same holds for the full reload the refresh timer runs.

    A source that cannot be fetched keeps the channels it had, so one broken
    download cannot empty a playlist.
    """
    url = "http://example.invalid/tv.m3u"
    monkeypatch.setattr(main, "get_cache_path_for_url", lambda _u: str(tmp_path / "tv.m3u"))
    monkeypatch.setattr(main, "save_config", lambda _cfg: None)
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))

    def _boom(*_args, **_kwargs):
        raise OSError("the provider is down")

    monkeypatch.setattr(main.urllib.request, "urlopen", _boom)

    scope_id = main._source_scope_id(url)
    previous = [{"name": "Sports 1", "url": "http://example/1", "playlist-id": scope_id}]
    app = _refresh_app([url], previous)
    spoken = []
    finished = threading.Event()

    def _speak(message):
        spoken.append(message)
        finished.set()

    app._speak = _speak
    app._cancel_epg_autostart_timer = lambda: None
    app._do_playlist_refresh = types.MethodType(main.IPTVClient._do_playlist_refresh, app)
    app.start_playlist_load = types.MethodType(main.IPTVClient.start_playlist_load, app)

    app.start_playlist_load()

    assert finished.wait(10), "the refresh never finished"
    assert [ch["name"] for ch in app.all_channels] == ["Sports 1"]
