"""Process startup is distinct from scheduling and caption availability."""
import threading
from types import SimpleNamespace

import pytest

import external_player
from external_player import ExternalPlayerLauncher
from subtitle_session import SubtitleSessionController
from subtitle_speech import SubtitleSpeechManager
from tests.test_subtitle_integration import app


class Adapter:
    available = False

    def cancel(self):
        pass

    def close(self, terminate=True):
        pass


def inline_workers(monkeypatch):
    monkeypatch.setattr(external_player.threading, "Thread",
                        lambda target, **kwargs: SimpleNamespace(start=target))


def setup(monkeypatch, *, missing=False, fail=False, fallback=False):
    inline_workers(monkeypatch)
    launcher = ExternalPlayerLauncher()
    owner = SubtitleSessionController(SubtitleSpeechManager(lambda text: None))
    queue, results, states, attempts = [], [], [], []
    owner.set_ui_thread(queue.append)
    monkeypatch.setattr(launcher, "_find_mpv_exe", lambda path: None if missing else "mpv.exe")

    def spawn(*args):
        attempts.append("subtitled")
        return None if fail or fallback else Adapter()

    def plain(*args):
        attempts.append("playback-only")
        if fail:
            return None
        args[3]("unavailable")
        return Adapter()

    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch", spawn)
    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch_playback_only", plain)
    return launcher, owner, queue, results, states, attempts


def drain(queue):
    while queue:
        queue.pop(0)()


@pytest.mark.parametrize("player,path", [("MPV", ""), ("Custom", "missing/mpv.exe")])
def test_missing_executable_reports_startup_failure_on_ui(monkeypatch, player, path):
    launcher, owner, queue, results, states, attempts = setup(monkeypatch, missing=True)
    assert launcher.launch(player, "movie", path, subtitle_session=owner,
                           subtitle_state_cb=states.append,
                           playback_result_cb=lambda *args: results.append(args)) == (True, "")
    assert not results
    drain(queue)
    assert len(results) == 1 and results[0][0] is False
    assert "MPV" in results[0][1] and results[0][1]
    assert states == [] and attempts == []


def test_both_process_start_paths_failing_is_not_a_subtitle_outage(monkeypatch):
    launcher, owner, queue, results, states, attempts = setup(monkeypatch, fail=True)
    launcher.launch("MPV", "movie", subtitle_session=owner, subtitle_state_cb=states.append,
                    playback_result_cb=lambda *args: results.append(args))
    drain(queue)
    assert results == [(False, "No error details were reported.")]
    assert states == [] and attempts == ["subtitled", "playback-only"]


@pytest.mark.parametrize("fallback", [False, True])
def test_owned_process_success_is_independent_of_subtitle_readiness(monkeypatch, fallback):
    launcher, owner, queue, results, states, attempts = setup(monkeypatch, fallback=fallback)
    launcher.launch("MPV", "movie", subtitle_session=owner, subtitle_state_cb=states.append,
                    playback_result_cb=lambda *args: results.append(args))
    assert results == []
    drain(queue)
    assert results == [(True, "")]
    assert states == (["unavailable"] if fallback else [])
    assert attempts == (["subtitled", "playback-only"] if fallback else ["subtitled"])
    assert owner.session_token is not None


def test_unexpected_adapter_exception_still_tries_owned_playback_fallback(monkeypatch):
    launcher, owner, queue, results, states, attempts = setup(monkeypatch, fallback=True)

    def fail(*args):
        attempts.append("exception")
        raise OSError("helper unavailable")

    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch", fail)
    launcher.launch("MPV", "movie", subtitle_session=owner, subtitle_state_cb=states.append,
                    playback_result_cb=lambda *args: results.append(args))
    drain(queue)
    assert results == [(True, "")] and attempts == ["exception", "playback-only"]


@pytest.mark.parametrize("fail", [False, True])
def test_queued_old_result_cannot_change_another_player_session(monkeypatch, fail):
    launcher, owner, queue, results, _, _ = setup(monkeypatch, fail=fail)
    launcher.launch("MPV", "old", subtitle_session=owner,
                    playback_result_cb=lambda *args: results.append(args))
    token = owner.activate_session("built-in")
    drain(queue)
    assert results == [] and owner.is_current(token)


def test_failed_launch_can_be_retried_without_waiting_for_debounce(monkeypatch):
    launcher, owner, queue, results, _, attempts = setup(monkeypatch, fail=True)
    for _ in range(2):
        launcher.launch("MPV", "movie", subtitle_session=owner,
                        playback_result_cb=lambda *args: results.append(args))
        drain(queue)
    assert len(results) == 2 and all(not ok for ok, error in results)
    assert len(attempts) == 4


def test_callback_exception_does_not_start_another_process(monkeypatch):
    launcher, owner, queue, _, _, attempts = setup(monkeypatch)

    def bad_callback(*args):
        raise RuntimeError("UI callback failed")

    launcher.launch("MPV", "movie", subtitle_session=owner, playback_result_cb=bad_callback)
    drain(queue)
    assert attempts == ["subtitled"]


def test_synchronous_player_success_calls_back_once_and_failure_is_returned(monkeypatch):
    inline_workers(monkeypatch)
    launcher = ExternalPlayerLauncher()
    results = []
    monkeypatch.setattr(launcher, "_spawn_windows", lambda args: (True, ""))
    monkeypatch.setattr(launcher, "_spawn_posix", lambda args: (True, ""))
    assert launcher.launch("Custom", "one", "test-player.exe",
                           playback_result_cb=lambda *args: results.append(args)) == (True, "")
    assert results == [(True, "")]
    monkeypatch.setattr(launcher, "_spawn_windows", lambda args: (False, "denied"))
    monkeypatch.setattr(launcher, "_spawn_posix", lambda args: (False, "denied"))
    assert launcher.launch("Custom", "two", "test-player.exe",
                           playback_result_cb=lambda *args: results.append(args)) == (False, "denied")
    assert results == [(True, "")]


def client():
    instance, _, _, env = app(["_launch_stream"])
    type(instance)._single_stream_provider_has_recording = staticmethod(lambda self, url: False)
    instance.default_player = "MPV"
    instance.show_player_on_enter = False
    instance.caster = None
    instance._on_mpv_subtitle_state = lambda state: None
    remembered, errors, queue = [], [], []
    instance._remember_played_channel = remembered.append
    instance._subtitle_session.set_ui_thread(queue.append)
    env["message_box"] = lambda *args: errors.append(args)
    return instance, remembered, errors, queue


@pytest.mark.parametrize("ok", [False, True])
def test_main_history_and_error_dialog_wait_for_owned_process_result(monkeypatch, ok):
    inline_workers(monkeypatch)
    instance, remembered, errors, queue = client()
    instance.player_launcher = ExternalPlayerLauncher()
    monkeypatch.setattr(instance.player_launcher, "_find_mpv_exe", lambda path: "mpv.exe" if ok else None)
    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch", lambda *args: Adapter())
    channel = {"name": "Channel"}
    instance._launch_stream("movie", "Title", channel=channel)
    assert remembered == [] and errors == []
    drain(queue)
    assert remembered == ([channel] if ok else [])
    assert len(errors) == (0 if ok else 1)
    if not ok:
        assert errors[0][1] == "Launch Error" and "MPV" in errors[0][0]
        assert instance._subtitle_session.session_token is None


def test_catchup_launch_does_not_enter_live_history(monkeypatch):
    inline_workers(monkeypatch)
    instance, remembered, errors, queue = client()
    instance.player_launcher = ExternalPlayerLauncher()
    monkeypatch.setattr(instance.player_launcher, "_find_mpv_exe", lambda path: "mpv.exe")
    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch", lambda *args: Adapter())
    instance._launch_stream("movie", "Title", channel={"name": "Archive"}, stream_kind="catchup")
    drain(queue)
    assert remembered == [] and errors == []


def test_worker_start_failure_is_returned_synchronously(monkeypatch):
    launcher = ExternalPlayerLauncher()
    owner = SubtitleSessionController(SubtitleSpeechManager(lambda text: None))
    monkeypatch.setattr(launcher, "_launch_mpv_subtitled_async", lambda *args: (_ for _ in ()).throw(RuntimeError("thread failed")))
    results = []
    assert launcher.launch("MPV", "movie", subtitle_session=owner,
                           playback_result_cb=lambda *args: results.append(args)) == (False, "thread failed")
    assert results == []


def test_worker_failure_after_session_replacement_is_silent_and_nonblocking(monkeypatch):
    launcher = ExternalPlayerLauncher()
    owner = SubtitleSessionController(SubtitleSpeechManager(lambda text: None))
    started, release, done = threading.Event(), threading.Event(), threading.Event()
    results, fallbacks = [], []
    original_thread = threading.Thread
    def tracked_thread(target, **kwargs):
        def run():
            try:
                target()
            finally:
                done.set()
        return original_thread(target=run, **kwargs)
    monkeypatch.setattr(external_player.threading, "Thread", tracked_thread)
    monkeypatch.setattr(launcher, "_find_mpv_exe", lambda path: "mpv.exe")

    def slow_failure(*args):
        started.set()
        assert release.wait(2)
        return None

    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch", slow_failure)
    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch_playback_only", lambda *args: fallbacks.append(True))
    assert launcher.launch("MPV", "old", subtitle_session=owner,
                           playback_result_cb=lambda *args: results.append(args)) == (True, "")
    try:
        assert started.wait(1)
        fresh = owner.activate_session("built-in")
        release.set()
        assert done.wait(1)
        assert owner.is_current(fresh) and results == [] and fallbacks == []
    finally:
        release.set()
        assert done.wait(2)


def test_real_process_creation_errors_reach_ui_once(monkeypatch, tmp_path):
    inline_workers(monkeypatch)
    launcher = ExternalPlayerLauncher()
    owner = SubtitleSessionController(SubtitleSpeechManager(lambda text: None))
    queue, results, states = [], [], []
    owner.set_ui_thread(queue.append)
    missing = str(tmp_path / "nonexistent-mpv.exe")
    monkeypatch.setattr(launcher, "_find_mpv_exe", lambda path: missing)
    launcher.launch("MPV", "movie", subtitle_session=owner, subtitle_state_cb=states.append,
                    playback_result_cb=lambda *args: results.append(args))
    drain(queue)
    assert results == [(False, "No error details were reported.")]
    assert states == [] and launcher._mpv_adapter is None


def test_later_caption_handshake_failure_does_not_become_playback_failure(monkeypatch):
    launcher, owner, queue, results, states, attempts = setup(monkeypatch)
    callbacks = []
    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch",
                        lambda *args: callbacks.append(args[3]) or Adapter())
    launcher.launch("MPV", "movie", subtitle_session=owner, subtitle_state_cb=states.append,
                    playback_result_cb=lambda *args: results.append(args))
    drain(queue)
    callbacks[0]("unavailable")
    drain(queue)
    assert results == [(True, "")] and states == ["unavailable"]
