import json
import os
import subprocess
import sys
import textwrap


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_child(code: str) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(result.stdout)


def test_import_main_does_not_probe_ffmpeg_or_load_casting_player():
    data = _run_child(
        """
        import json
        import subprocess
        import sys

        def fail_run(*_args, **_kwargs):
            raise AssertionError("subprocess.run should not be called while importing main")

        subprocess.run = fail_run
        import main

        print(json.dumps({
            "casting_loaded": "casting" in sys.modules,
            "internal_player_loaded": "internal_player" in sys.modules,
            "stream_proxy_loaded": "stream_proxy" in sys.modules,
            "vlc_loaded": "vlc" in sys.modules,
            "pychromecast_loaded": "pychromecast" in sys.modules,
            "async_upnp_loaded": "async_upnp_client" in sys.modules,
            "pyatv_loaded": "pyatv" in sys.modules,
            "main_loaded": "main" in sys.modules,
        }))
        """
    )

    assert data["main_loaded"] is True
    assert data["casting_loaded"] is False
    assert data["internal_player_loaded"] is False
    assert data["stream_proxy_loaded"] is False
    assert data["vlc_loaded"] is False
    assert data["pychromecast_loaded"] is False
    assert data["async_upnp_loaded"] is False
    assert data["pyatv_loaded"] is False


def test_sitecustomize_does_not_eagerly_import_internal_player():
    data = _run_child(
        """
        import json
        import sys
        import sitecustomize

        print(json.dumps({
            "sitecustomize_loaded": "sitecustomize" in sys.modules,
            "internal_player_loaded": "internal_player" in sys.modules,
        }))
        """
    )

    assert data["sitecustomize_loaded"] is True
    assert data["internal_player_loaded"] is False


def test_import_recorder_does_not_load_stream_proxy():
    data = _run_child(
        """
        import json
        import sys

        import recorder

        print(json.dumps({
            "recorder_loaded": "recorder" in sys.modules,
            "stream_proxy_loaded": "stream_proxy" in sys.modules,
        }))
        """
    )

    assert data["recorder_loaded"] is True
    assert data["stream_proxy_loaded"] is False


def test_frame_constructor_defers_slow_startup_work():
    data = _run_child(
        """
        import inspect
        import json
        import main

        init_src = inspect.getsource(main.IPTVClient.__init__)
        deferred_src = inspect.getsource(main.IPTVClient._run_deferred_startup_tasks)
        print(json.dumps({
            "init_src": init_src,
            "deferred_src": deferred_src,
        }))
        """
    )

    assert "_ensure_db_tuned()" not in data["init_src"]
    assert "dvr.DVRScheduler" not in data["init_src"]
    assert "_run_deferred_startup_tasks" in data["init_src"]
    assert "_ensure_db_tuned_background()" in data["deferred_src"]
    assert "_start_dvr_scheduler()" in data["deferred_src"]
    assert "start_playlist_load()" in data["deferred_src"]


def test_config_read_candidates_do_not_create_user_config_dir():
    data = _run_child(
        """
        import json
        import os
        import shutil
        import tempfile

        tmp = tempfile.mkdtemp(prefix="iptv_startup_cfg_")
        os.environ["APPDATA"] = tmp
        try:
            import options
            target = os.path.join(tmp, "AccessibleIPTVClient")
            options.get_config_read_candidates()
            created_after_read = os.path.exists(target)
            options.get_user_config_dir()
            created_after_write_path = os.path.isdir(target)
            print(json.dumps({
                "created_after_read": created_after_read,
                "created_after_write_path": created_after_write_path,
            }))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        """
    )

    assert data["created_after_read"] is False
    assert data["created_after_write_path"] is True


def test_playlist_import_delays_epg_log_file_creation():
    data = _run_child(
        """
        import json
        import os
        import shutil
        import tempfile

        tmp = tempfile.mkdtemp(prefix="iptv_startup_epglog_")
        os.environ["EPG_DEBUG"] = "0"
        tempfile.tempdir = tmp
        try:
            import playlist
            log_path = os.path.join(tmp, "iptvclient_epg_debug.log")
            print(json.dumps({
                "playlist_loaded": "playlist" in globals(),
                "log_exists": os.path.exists(log_path),
            }))
        finally:
            tempfile.tempdir = None
            shutil.rmtree(tmp, ignore_errors=True)
        """
    )

    assert data["playlist_loaded"] is True
    assert data["log_exists"] is False


def test_epg_import_thread_priority_helper_lowers_real_thread_priority():
    """`_lower_current_thread_priority` runs at the top of the EPG auto-import
    worker thread (see do_import() in start_epg_import_background) so a long
    background import competes less for CPU/disk/memory with the UI thread.
    Verify it actually moves the *calling* thread's OS priority -- checked
    against the real Win32 API rather than a mock, since a mock would not have
    caught the HANDLE marshaling bug this once had (GetCurrentThread()'s
    pseudo-HANDLE getting truncated without explicit ctypes argtypes/restype).

    The helper prefers THREAD_MODE_BACKGROUND_BEGIN (GetThreadPriority then
    reports a value below THREAD_PRIORITY_LOWEST, -4 in practice) and falls
    back to THREAD_PRIORITY_LOWEST (-2), so assert on the shared bound rather
    than one exact constant.
    """
    data = _run_child(
        """
        import ctypes
        import json
        import platform

        import main

        is_windows = platform.system() == "Windows"
        before = after = None
        if is_windows:
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentThread.restype = wintypes.HANDLE
            kernel32.GetThreadPriority.argtypes = [wintypes.HANDLE]
            kernel32.GetThreadPriority.restype = ctypes.c_int
            before = kernel32.GetThreadPriority(kernel32.GetCurrentThread())

        main._lower_current_thread_priority()

        if is_windows:
            after = kernel32.GetThreadPriority(kernel32.GetCurrentThread())

        print(json.dumps({"is_windows": is_windows, "before": before, "after": after}))
        """
    )

    if data["is_windows"]:
        THREAD_PRIORITY_LOWEST = -2
        assert data["before"] > THREAD_PRIORITY_LOWEST
        assert data["after"] <= THREAD_PRIORITY_LOWEST


def test_start_epg_import_background_invokes_priority_lowering():
    """Confirms the background import worker actually calls the priority-lowering
    helper (wiring), independent of the helper's own OS-level behavior above."""
    data = _run_child(
        """
        import inspect
        import json

        import main

        src = inspect.getsource(main.IPTVClient.start_epg_import_background)
        print(json.dumps({"calls_helper": "_lower_current_thread_priority()" in src}))
        """
    )
    assert data["calls_helper"] is True