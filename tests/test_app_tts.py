"""App-owned TTS backend: graceful degradation where SAPI is absent."""

import platform

from app_tts import AppTtsBackend


def test_backend_unavailable_off_windows():
    backend = AppTtsBackend()
    try:
        if platform.system() != "Windows":
            assert backend.available is False
            assert backend.speak("hello") is False
            assert backend.list_outputs() == []
            assert backend.set_volume(80) is False
            assert backend.set_output("anything") is False
    finally:
        backend.close()


def test_volume_clamped_without_backend():
    backend = AppTtsBackend()
    try:
        assert backend.volume == 100
    finally:
        backend.close()
