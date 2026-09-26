import types

import main


def _app(sources):
    app = types.SimpleNamespace(playlist_sources=sources, spoken=[], loads=[])
    app._speak = app.spoken.append
    app.start_playlist_load = lambda: app.loads.append(True)
    return app


def test_refresh_drops_the_downloaded_copy_and_reloads(tmp_path, monkeypatch):
    url = "http://example.com/tv.m3u"
    cached = tmp_path / "tv.m3u"
    cached.write_text("#EXTM3U", encoding="utf-8")
    monkeypatch.setattr(main, "get_cache_path_for_url", lambda _u: str(cached))
    app = _app([url])

    main.IPTVClient._refresh_playlist_source(app, url)

    assert not cached.exists()
    assert app.loads == [True]
    assert app._announce_playlists_refreshed is True


def test_refresh_of_an_unsaved_playlist_asks_for_ok_first():
    app = _app(["http://example.com/saved.m3u"])

    main.IPTVClient._refresh_playlist_source(app, "http://example.com/new.m3u")

    assert app.loads == []
    assert len(app.spoken) == 1
