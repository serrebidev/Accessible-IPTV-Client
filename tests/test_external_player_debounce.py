import threading
import time

from external_player import ExternalPlayerLauncher


def test_the_mpv_adapter_launch_does_not_block_the_caller(monkeypatch):
    """The adapter's handshake takes as long as MPV answers.

    It ran on the GUI thread, so pressing Enter on a channel froze the window
    - and silenced the screen reader - for the whole handshake.
    """
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


def test_launching_another_player_closes_the_application_mpv(monkeypatch):
    """The application-owned MPV is playing the previous channel.

    Launching VLC left it running, so the two players were audible at once
    and the old channel kept playing.
    """
    closed = []

    class Adapter:
        def close(self):
            closed.append(True)

    launcher = ExternalPlayerLauncher()
    launcher._mpv_adapter = Adapter()
    monkeypatch.setattr(launcher, "_spawn_windows", lambda argv: (True, ""))
    monkeypatch.setattr(launcher, "_spawn_posix", lambda argv: (True, ""))

    launcher.launch("VLC", "https://example.test/other.ts")

    assert closed, "the previous MPV session was left running"


def test_a_superseded_adapter_launch_does_not_start_the_old_channel(monkeypatch):
    """A newer launch must win over the adapter worker of the older one.

    The handshake takes as long as MPV answers. When it failed after the user
    had already picked another channel, the plain handoff started the old
    channel over the new one.
    """
    started = []
    release = threading.Event()

    class SlowAdapter:
        @classmethod
        def launch(cls, *_args, **_kwargs):
            started.append(True)
            release.wait(5)
            return None

    launcher = ExternalPlayerLauncher()
    monkeypatch.setattr("external_player.MpvSubtitleAdapter", SlowAdapter)
    monkeypatch.setattr(launcher, "_find_mpv_exe", lambda custom_path="": "mpv.exe")
    monkeypatch.setattr(launcher, "close_subtitle_adapter", lambda: None)
    # The plain handoff ends in the IPC reuse; that is where it shows up.
    handed_off = []
    monkeypatch.setattr(launcher, "_mpv_try_send",
                        lambda url: handed_off.append(url) or False)

    launcher.launch("MPV", "https://example.test/old.ts", subtitle_manager=object())
    deadline = time.monotonic() + 5
    while not started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert started, "the adapter was never started"

    # The user picks another channel while the handshake is still running.
    launcher.launch("MPV", "https://example.test/new.ts", subtitle_manager=object())
    release.set()

    deadline = time.monotonic() + 5
    while not handed_off and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.2)
    assert handed_off == ["https://example.test/new.ts"], \
        "the superseded launch started the old channel"
