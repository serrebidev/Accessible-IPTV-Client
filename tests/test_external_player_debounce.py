from external_player import ExternalPlayerLauncher


def test_the_launch_debounce_uses_a_monotonic_clock(monkeypatch):
    """A backwards wall-clock step must not block the player for good.

    The wall clock can step backwards (a manual change, an NTP step, a VM
    restore). A negative delta left the debounce permanently open, so the
    player refused to start at all until the app was restarted.
    """
    import inspect

    source = inspect.getsource(ExternalPlayerLauncher.launch)
    assert "time.monotonic()" in source
    assert "time.time()" not in source


def test_same_url_in_another_player_is_not_debounced(monkeypatch):
    launched = []
    launcher = ExternalPlayerLauncher()
    monkeypatch.setattr(launcher, "_spawn_windows", lambda argv: launched.append(argv) or (True, ""))
    monkeypatch.setattr(launcher, "_spawn_posix", lambda argv: launched.append(argv) or (True, ""))
    assert launcher.launch("Custom", "same-url", "mpv.exe") == (True, "")
    assert launcher.launch("Custom", "same-url", "mpv.exe") == (True, "")
    assert launcher.launch("Custom", "same-url", "vlc.exe") == (True, "")
    assert len(launched) == 2
