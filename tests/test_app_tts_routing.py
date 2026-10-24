"""Routing-state tests run without native SAPI or wx.

Kept separate from the native SAPI module so the existing CI exclusion
does not skip privacy and device-selection regressions.
"""
import pytest
import app_tts
from app_tts import AppTtsBackend


class Token:
    def __init__(self, identity, name):
        self.identity, self.name = identity, name

    def get(self, key):
        assert key == "Id"
        return self.identity

    def call(self, key):
        assert key == "GetDescription"
        return self.name

    def release(self):
        pass


class Tokens:
    def __init__(self, items):
        self.items = list(items)

    def get(self, key):
        assert key == "Count"
        return len(self.items)

    def call(self, key, index):
        assert key == "Item"
        return self.items[index]

    def release(self):
        pass


class Voice:
    def __init__(self):
        self.devices = [Token("headphones-id", "Headphones"), Token("speakers-id", "Speakers")]
        self.output = "default"
        self.spoken = []
        self.flags = []
        self.fail_speak = False
        self.volume = 100
        self.rate = 0

    def call(self, key, *args):
        if key == "GetAudioOutputs":
            return Tokens(self.devices)
        assert key == "Speak"
        text, flags = args
        self.flags.append(flags)
        if text and self.fail_speak:
            raise app_tts._ComError("synthesis unavailable")
        if text:
            self.spoken.append((self.output, text))

    def put(self, key, value):
        if key == "AudioOutput":
            self.output = "default" if value is None else value.identity
        elif key == "Volume":
            self.volume = value
        elif key == "Rate":
            self.rate = value
        else:
            raise AssertionError(key)

    def release(self):
        pass


@pytest.fixture
def fake_backend(monkeypatch):
    monkeypatch.setattr(app_tts, "_IS_WINDOWS", False)
    backend = AppTtsBackend()
    backend._voice = Voice()
    yield backend
    backend.close()


def test_missing_saved_device_at_startup_never_uses_default(fake_backend):
    backend = fake_backend
    assert not backend.set_output("disconnected-id")
    assert backend.selected_output == "disconnected-id"
    assert not backend.speak("Private caption")
    assert backend.last_result == app_tts.SpeechResult.OUTPUT_MISSING
    assert backend._voice.spoken == []


def test_disconnect_pause_reconnect_keeps_id_and_drops_missed_text(fake_backend):
    backend = fake_backend
    assert backend.set_output("headphones-id")
    assert backend.speak("Before")
    headphones = backend._voice.devices.pop(0)
    assert not backend.speak("During")
    assert backend.routing_state == app_tts.RoutingState.PAUSED
    backend._voice.devices.append(headphones)
    assert backend.speak("After")
    assert backend._voice.spoken == [("headphones-id", "Before"), ("headphones-id", "After")]


def test_explicit_fallback_retains_target_and_returns_to_it(fake_backend):
    backend = fake_backend
    backend.set_output("headphones-id")
    headphones = backend._voice.devices.pop(0)
    assert backend.speak("Allowed", device_policy="default")
    assert backend.selected_output == "headphones-id"
    assert backend.routing_state == app_tts.RoutingState.FALLBACK
    backend._voice.devices.append(headphones)
    assert backend.speak("Back", device_policy="default")
    assert backend._voice.spoken == [("default", "Allowed"), ("headphones-id", "Back")]


def test_names_are_migrated_only_when_exact_and_unambiguous(fake_backend):
    backend = fake_backend
    assert backend.set_output("headphones")
    assert backend.selected_output == "headphones-id"
    assert not backend.set_output("Head")
    backend._voice.devices.append(Token("other-id", "Headphones"))
    assert not backend.set_output("Headphones")
    assert backend.set_output("other-id")
    assert backend._voice.output == "other-id"


def test_caption_is_literal_text_and_failed_synthesis_does_not_retry_elsewhere(fake_backend):
    backend = fake_backend
    assert backend.speak('<voice required="Name=other">Caption & text</voice>')
    assert backend._voice.flags[-1] & 16
    backend._voice.fail_speak = True
    assert not backend.speak("Failure", device_policy="default")
    assert backend.last_result == app_tts.SpeechResult.FAILED
    assert len(backend._voice.spoken) == 1


def test_reset_really_restores_system_default(fake_backend):
    assert fake_backend.set_output("headphones-id")
    assert fake_backend.reset_output()
    assert fake_backend.selected_output == ""
    assert fake_backend.speak("Default")
    assert fake_backend._voice.spoken == [("default", "Default")]


def test_com_cannot_be_used_from_a_reader_thread(fake_backend):
    import threading
    errors = []

    def worker():
        try:
            fake_backend.speak("Wrong thread")
        except RuntimeError as error:
            errors.append(str(error))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(1)
    assert errors and "COM thread" in errors[0]
    assert fake_backend._voice.spoken == []


@pytest.mark.parametrize("requested,expected", [(-10, -10), (0, 0), (10, 10), (-99, -10), (99, 10),
                                               ("4", 4), (None, 0), ("broken", 0), (True, 0),
                                               (float("inf"), 0), (float("nan"), 0)])
def test_application_rate_is_bounded_and_independent_of_volume(fake_backend, requested, expected):
    backend = fake_backend
    assert backend.set_volume(37)
    assert backend.set_rate(requested)
    assert backend.rate == backend._voice.rate == expected
    assert backend.volume == backend._voice.volume == 37
    assert backend.speak("Next caption")
    assert backend._voice.spoken == [("default", "Next caption")]


def test_failed_rate_change_preserves_last_successful_value(fake_backend):
    backend = fake_backend
    assert backend.set_rate(3)
    prior = backend._voice.put
    def reject_rate(key, value):
        if key == "Rate":
            raise app_tts._ComError("rate not supported")
        return prior(key, value)
    backend._voice.put = reject_rate
    assert not backend.set_rate(8)
    assert backend.rate == 3
    assert backend.speak("Still usable")


def test_rate_uses_the_same_com_thread_ownership_as_speech(fake_backend):
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(RuntimeError, match="owning COM thread"):
            executor.submit(fake_backend.set_rate, 3).result()
    assert fake_backend.rate == 0
