from external_player import ExternalPlayerLauncher


def test_same_url_in_another_player_is_not_debounced(monkeypatch):
    launched = []
    launcher = ExternalPlayerLauncher()
    monkeypatch.setattr(launcher, "_spawn_windows", lambda argv: launched.append(argv) or (True, ""))
    monkeypatch.setattr(launcher, "_spawn_posix", lambda argv: launched.append(argv) or (True, ""))
    assert launcher.launch("Custom", "same-url", "mpv.exe") == (True, "")
    assert launcher.launch("Custom", "same-url", "mpv.exe") == (True, "")
    assert launcher.launch("Custom", "same-url", "vlc.exe") == (True, "")
    assert len(launched) == 2
