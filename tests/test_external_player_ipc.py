import json

import external_player
from external_player import ExternalPlayerLauncher


def test_the_handoff_points_mpv_at_this_sessions_pipe(monkeypatch):
    """The name was fixed, so any local process could find and drive the pipe."""
    monkeypatch.setattr(external_player.platform, "system", lambda: "Windows")
    launcher = ExternalPlayerLauncher()

    argv = launcher._argv_for("MPV", "mpv.exe", True, "https://example.test/live.ts")

    endpoint = launcher._mpv_ipc_endpoint
    assert f"--input-ipc-server={endpoint}" in argv
    assert endpoint != r"\\.\pipe\iptvclient-mpv"


def test_a_second_channel_uses_the_same_pipe(monkeypatch):
    """Reuse only works while the name does not change between launches."""
    launcher = ExternalPlayerLauncher()
    sent = []
    monkeypatch.setattr(launcher, "_mpv_send",
                        lambda payload: sent.append(json.loads(payload)) or True)

    assert launcher._mpv_try_send("https://example.test/one.ts")
    assert launcher._mpv_try_send("https://example.test/two.ts")

    assert [entry["command"][:2] for entry in sent] == [
        ["loadfile", "https://example.test/one.ts"],
        ["loadfile", "https://example.test/two.ts"],
    ]


def test_the_players_mpv_is_quit_when_the_app_closes(monkeypatch):
    """An --idle=yes mpv outlived the app: it kept the last channel playing.

    Its pipe name belongs to the session that made it, so a restart cannot
    reach that mpv either; the app has to close it while it still can.
    """
    launcher = ExternalPlayerLauncher()
    sent = []
    monkeypatch.setattr(launcher, "_mpv_send",
                        lambda payload: sent.append(json.loads(payload)) or True)

    launcher.close_mpv()

    assert sent == [{"command": ["quit"]}]
