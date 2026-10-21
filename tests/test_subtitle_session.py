"""Tests for the subtitle session controller (subtitle_session.py).

GUI-free and dependency-free. The controller owns one subtitle-speech session
at a time, and the whole point of the token is that a cue from a session that
has already been replaced is never spoken.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle_session import SubtitleSessionController  # noqa: E402


class _Manager:
    def __init__(self):
        self.source = None
        self.cleared = 0

    def set_source(self, name):
        self.source = name

    def clear(self):
        self.cleared += 1


class _Adapter:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def test_a_new_session_supersedes_the_old_one():
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    first = controller.activate_session("Sky Mix")
    second = controller.activate_session("CNN")

    assert first != second
    assert controller.session_token == second
    assert controller.is_current(second)
    assert not controller.is_current(first)
    assert manager.source == "CNN"


def test_cancelling_closes_the_adapter_and_clears_the_manager():
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    controller.activate_session("Sky Mix")
    adapter = _Adapter()
    controller.set_adapter(adapter)

    controller.cancel_session()

    assert controller.session_token is None
    assert not controller.is_current("anything")
    assert adapter.closed == 1
    assert manager.cleared == 1


def test_replacing_the_adapter_closes_the_old_one():
    controller = SubtitleSessionController(_Manager())
    first = _Adapter()
    second = _Adapter()
    controller.set_adapter(first)
    controller.set_adapter(second)
    assert first.closed == 1
    assert second.closed == 0


def test_a_stale_cue_is_never_spoken():
    """A cue from the previous channel must not reach the screen reader."""
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    spoken = []
    old = controller.activate_session("Sky Mix")
    controller.activate_session("CNN")

    assert controller.speak_validated(old, "stale line", spoken.append) is False
    assert spoken == []


def test_the_current_session_is_spoken_on_the_ui_thread():
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    queued = []
    controller.set_ui_thread(queued.append)
    token = controller.activate_session("Sky Mix")
    spoken = []

    assert controller.speak_validated(token, "hello", spoken.append) is True
    assert spoken == [], "the speech must wait for the UI thread"
    queued.pop()()
    assert spoken == ["hello"]


def test_a_cue_dropped_between_the_queue_and_the_ui_thread_is_not_spoken():
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    queued = []
    controller.set_ui_thread(queued.append)
    token = controller.activate_session("Sky Mix")
    spoken = []

    controller.speak_validated(token, "hello", spoken.append)
    controller.activate_session("CNN")  # the channel changed while it was queued
    queued.pop()()
    assert spoken == []
