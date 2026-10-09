"""App-owned TTS backend: graceful degradation where SAPI is absent."""

import ctypes
import platform
import sys

import pytest

import app_tts
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


@pytest.mark.skipif(sys.platform != "win32", reason="SAPI is Windows only")
def test_real_sapi_calls_do_not_crash():
    # v1.147.0/1 died at startup (0xC0000409) in set_volume: GetIDsOfNames was
    # missing riid and VARIANT was 16 bytes instead of 24. Construction alone
    # never touched Invoke, so only real calls catch this.
    assert ctypes.sizeof(app_tts._Dispatch._Variant) == (
        24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)
    backend = AppTtsBackend()
    try:
        if not backend.available:
            pytest.skip("SAPI.SpVoice not registered")
        assert backend.set_volume(0)
        outputs = backend.list_outputs()
        if outputs:
            assert backend.set_output(outputs[0])
            assert backend.output_present()
        assert backend.reset_output()
        assert backend.speak("test")
        backend.stop()
    finally:
        backend.close()


def test_volume_clamped_without_backend():
    backend = AppTtsBackend()
    try:
        assert backend.volume == 100
    finally:
        backend.close()
