from external_player import ExternalPlayerLauncher


def test_the_mpv_adapter_launch_does_not_block_the_caller(monkeypatch):
    """The adapter's handshake takes as long as MPV answers.

    It ran on the GUI thread, so pressing Enter on a channel froze the window
    - and silenced the screen reader - for the whole handshake.
    """
    import time

    started = []

    class SlowAdapter:
        @classmethod
        def launch(cls, *_args, **_kwargs):
            started.append(time.monotonic())
            time.sleep(1.0)
            return None

    launcher = ExternalPlayerLauncher()
    monkeypatch.setattr("external_player.MpvSubtitleAdapter", SlowAdapter)
    monkeypatch.setattr(launcher, "_find_mpv_exe", lambda custom_path="": "mpv.exe")
    monkeypatch.setattr(launcher, "close_subtitle_adapter", lambda: None)

    began = time.monotonic()
    assert launcher.launch("MPV", "https://example.test/live.ts",
                           subtitle_manager=object()) == (True, "")
    elapsed = time.monotonic() - began

    assert elapsed < 0.5, "the launch waited for the adapter handshake"
    # The adapter is started on a worker, not on the calling thread.
    deadline = time.monotonic() + 5
    while not started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert started, "the adapter was never started"


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
