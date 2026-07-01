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
            target = os.path.join(tmp, "IPTVClient")
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