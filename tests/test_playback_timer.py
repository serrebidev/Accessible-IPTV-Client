"""Countdown deadlines, stale deliveries and the actual player expiry path."""
import math
from types import SimpleNamespace

import pytest

from playback_timer import PlaybackTimer
from tests.test_subtitle_integration import extract_class


@pytest.mark.parametrize("value", [-1, 1441, True, False, 1.5, "30", None, float("nan")])
def test_invalid_input_cannot_replace_a_running_timer(value):
    timer = PlaybackTimer(lambda: 10)
    timer.set_minutes(30)
    before = timer.deadline, timer.generation
    with pytest.raises(ValueError):
        timer.set_minutes(value)
    assert (timer.deadline, timer.generation) == before


def test_countdown_can_be_replaced_cancelled_and_consumed_only_once():
    now = [100.0]
    timer = PlaybackTimer(lambda: now[0])
    old = timer.set_minutes(1)
    latest = timer.set_minutes(2)
    now[0] = 160.0
    assert not timer.take_due(old)
    assert not timer.take_due(latest)
    assert timer.remaining_minutes() == 1
    now[0] = 220.0
    assert timer.take_due(latest)
    assert not timer.take_due(latest)
    assert timer.remaining_minutes() == 0
    latest = timer.set_minutes(1)
    timer.set_minutes(0)
    now[0] += 100
    assert not timer.take_due(latest)


def test_player_expiry_stops_only_playback_and_ignores_early_stale_or_closed_callbacks():
    now, delayed, stops = [0.0], [], []
    timer = PlaybackTimer(lambda: now[0])
    cls, _ = extract_class("internal_player.py", "InternalPlayerFrame", ["_expire_sleep_timer"], {
        "math": math, "time": SimpleNamespace(monotonic=lambda: now[0]),
        "wx": SimpleNamespace(CallLater=lambda *args: delayed.append(args)),
    })
    player = cls()
    player._destroyed = False
    player._sleep_countdown = timer
    player.stop = lambda **kwargs: stops.append(kwargs)
    generation = timer.set_minutes(1)
    player._expire_sleep_timer(generation)
    assert delayed[0][0] == 60000 and stops == []
    now[0] = 60.0
    player._expire_sleep_timer(generation)
    player._expire_sleep_timer(generation)
    assert stops == [{"manual": True}]
    generation = timer.set_minutes(1)
    player._destroyed = True
    now[0] = 120.0
    player._expire_sleep_timer(generation)
    assert len(stops) == 1


@pytest.mark.parametrize('accepted,minutes', [(False, 5), (True, 0), (True, 5)])
def test_actual_timer_dialog_honours_cancellation_and_replaces_old_delivery(accepted, minutes):
    destroyed, stopped, delayed, topics = [], [], [], []
    class Dialog:
        def __init__(self, *args): pass
        def ShowModal(self): return int(accepted)
        def GetValue(self): return minutes
        def Destroy(self): destroyed.append(True)
    wx = SimpleNamespace(NumberEntryDialog=Dialog, ID_OK=1,
                         CallLater=lambda *args: delayed.append(args))
    cls, _ = extract_class('internal_player.py', 'InternalPlayerFrame', ['_configure_sleep_timer'], {
        'wx': wx, 'user_guide': SimpleNamespace(set_help_topic=lambda *args: topics.append(args[1])),
    })
    frame = cls()
    frame._sleep_countdown = PlaybackTimer(lambda: 0)
    old = frame._sleep_countdown.set_minutes(10)
    frame._sleep_call = SimpleNamespace(Stop=lambda: stopped.append(True))
    frame._expire_sleep_timer = lambda generation: None
    frame._configure_sleep_timer()
    assert destroyed == [True] * (2 if accepted and minutes else 1) and topics == ['built-in-player'] * (2 if accepted and minutes else 1)
    assert bool(stopped) == accepted
    assert bool(delayed) == (accepted and minutes > 0)
    assert (frame._sleep_countdown.generation != old) == accepted


def test_fade_gain_follows_monotonic_deadline():
    now = [0.0]
    timer = PlaybackTimer(lambda: now[0])
    generation = timer.set_minutes(1)
    now[0] = 55
    assert timer.fade_gain(10) == 0.5 and timer.fade_gain(0) == 1
    now[0] = 65
    assert timer.fade_gain(10) == 0 and timer.take_due(generation)
    assert timer.fade_gain(10) == 1


def test_fade_cancel_discards_stale_writes_and_startup_preserves_desired_volume():
    queued, volumes, later = [], [], []
    cls, _ = extract_class('internal_player.py', 'InternalPlayerFrame',
        ['_set_sleep_gain', '_cancel_sleep_timer', '_schedule_volume_apply', '_apply_volume'],
        {'wx': SimpleNamespace(CallLater=lambda delay, fn: later.append(fn))})
    frame = cls()
    frame._destroyed = False
    frame._vlc_generation = 1
    frame._sleep_countdown = PlaybackTimer(lambda: 0)
    frame._sleep_countdown.set_minutes(1)
    frame._sleep_call = None
    frame._sleep_gain = 1.0
    frame._volume_value = 80
    frame._vlc_call = queued.append
    frame._sync_volume_slider = frame._update_status_label = lambda: None
    frame.volume_slider = SimpleNamespace(GetValue=lambda: 80, SetValue=lambda value: None)
    frame.player = SimpleNamespace(audio_set_volume=volumes.append, audio_get_volume=lambda: 0,
                                   audio_set_mute=lambda value: None)
    frame._set_sleep_gain(0.5)
    queued.pop(0)()
    assert volumes == [40] and frame._volume_value == 80
    frame._apply_volume(60)
    assert volumes[-1] == 30 and frame._volume_value == 60
    frame._set_sleep_gain(0.1)
    frame._cancel_sleep_timer()
    frame._vlc_generation += 1
    for fn in queued: fn()
    frame._schedule_volume_apply()
    later.pop()()
    assert volumes[-1] == 60 and frame._volume_value == 60


def test_cancelling_second_dialog_leaves_running_timer_and_volume_untouched():
    opened, stopped = [], []
    class Dialog:
        def __init__(self, *args):
            self.index = len(opened)
            opened.append(self)
        def ShowModal(self): return 1 if self.index == 0 else 0
        def GetValue(self): return 5
        def Destroy(self): return
    cls, _ = extract_class('internal_player.py', 'InternalPlayerFrame', ['_configure_sleep_timer'], {
        'wx': SimpleNamespace(NumberEntryDialog=Dialog, ID_OK=1),
        'user_guide': SimpleNamespace(set_help_topic=lambda *a: None)})
    frame = cls()
    frame._sleep_countdown = PlaybackTimer(lambda: 0)
    generation = frame._sleep_countdown.set_minutes(10)
    frame._sleep_call = SimpleNamespace(Stop=lambda: stopped.append(True))
    frame._sleep_gain = 0.5
    frame._configure_sleep_timer()
    assert not stopped and frame._sleep_countdown.generation == generation and frame._sleep_gain == 0.5


def test_fade_announces_once_and_late_callback_stops_without_extending_deadline():
    now, gains, messages, stops = [55.0], [], [], []
    cls, _ = extract_class('internal_player.py', 'InternalPlayerFrame', ['_expire_sleep_timer'], {
        'math': math, 'time': SimpleNamespace(monotonic=lambda: now[0]),
        'wx': SimpleNamespace(CallLater=lambda *args: None)})
    frame = cls()
    frame._destroyed = False
    frame._sleep_countdown = PlaybackTimer(lambda: now[0])
    frame._sleep_countdown.deadline = 60.0
    frame._sleep_fade_seconds = 10
    frame._set_sleep_gain = gains.append
    frame._update_status_label = lambda *a, **kw: messages.append(a)
    frame.stop = lambda **kw: stops.append(kw)
    generation = frame._sleep_countdown.generation
    frame._expire_sleep_timer(generation)
    now[0] = 57.5
    frame._expire_sleep_timer(generation)
    assert gains == [0.5, 0.25] and len(messages) == 1
    now[0] = 65
    frame._expire_sleep_timer(generation)
    assert stops == [{'manual': True}]
