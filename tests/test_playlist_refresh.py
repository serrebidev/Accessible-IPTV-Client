import types

import main


def _app(sources):
    app = types.SimpleNamespace(playlist_sources=sources, spoken=[], loads=[])
    app._speak = app.spoken.append
    app.start_playlist_load = lambda only=None: app.loads.append(only)
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
