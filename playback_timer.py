"""Session-local sleep countdown; never changes clocks or playback speed."""

import math
import time


class PlaybackTimer:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.deadline = None
        self.generation = 0

    def set_minutes(self, minutes):
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= 1440:
            raise ValueError("minutes must be an integer between 0 and 1440")
        self.generation += 1
        self.deadline = self._clock() + minutes * 60 if minutes else None
        return self.generation

    def remaining_minutes(self):
        if self.deadline is None:
            return 0
        return max(1, math.ceil((self.deadline - self._clock()) / 60))

    def fade_gain(self, seconds):
        if self.deadline is None or seconds <= 0:
            return 1.0
        return max(0.0, min(1.0, (self.deadline - self._clock()) / seconds))

    def take_due(self, generation):
        if generation != self.generation or self.deadline is None or self._clock() < self.deadline:
            return False
        self.deadline = None
        self.generation += 1
        return True
