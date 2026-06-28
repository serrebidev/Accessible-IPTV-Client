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
            "main_loaded": "main" in sys.modules,
        }))
        """
    )

    assert data["main_loaded"] is True
    assert data["casting_loaded"] is False
    assert data["internal_player_loaded"] is False


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
