"""Player-neutral subtitle input and file timeline.

A player bridge supplies media-clock samples or complete native subtitle
snapshots. Parsing, file scheduling and speech processing are shared. This
module does not open a player, a network connection, a timer or an audio device.
Times are media milliseconds, never wall-clock timestamps. Bridges must start
new sessions for replacement producers and increase generation on track/seek
boundaries; sequence increases within a generation.
"""

from dataclasses import dataclass
from typing import Optional

import subtitle_cues


def _integer(value, name, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError(f"{name} must be an integer" + (f" >= {minimum}" if minimum is not None else ""))


@dataclass(frozen=True)
class PlaybackPosition:
    """An observed player clock; negative/unknown positions are not extrapolated.

    A positive subtitle delay displays a cue later. Position already reflects
    playback speed and buffering; guessing progress from a wall clock would
    speak ahead of paused or stalled video.
    """

    position_ms: Optional[int]
    paused: bool = False
    subtitle_delay_ms: int = 0

    def __post_init__(self):
        if self.position_ms is not None:
            _integer(self.position_ms, "position_ms")
        _integer(self.subtitle_delay_ms, "subtitle_delay_ms")
        if type(self.paused) is not bool:
            raise ValueError("paused must be a boolean")

    @property
    def subtitle_time_ms(self):
        if self.position_ms is None or self.position_ms < 0:
            return None
        return self.position_ms - self.subtitle_delay_ms


@dataclass(frozen=True)
class SubtitleSnapshot:
    """Complete input consumed by the same speech manager for every bridge.

    An empty/disabled/unsupported cue clears the current text, not the review
    history. A generation or track change clears the whole old timeline.
    Sequence guards delayed deliveries in addition to session ownership.
    """

    text: str
    source: str
    generation: int
    sequence: int
    track: str = ""
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    paused: bool = False
    active: bool = True
    text_supported: bool = True

    def __post_init__(self):
        if not isinstance(self.text, str) or not isinstance(self.source, str) or not self.source:
            raise ValueError("text and non-empty source must be strings")
        if not isinstance(self.track, str):
            raise ValueError("track must be a string")
        _integer(self.generation, "generation", 0)
        _integer(self.sequence, "sequence", 1)
        for name in ("start_ms", "end_ms"):
            if getattr(self, name) is not None:
                _integer(getattr(self, name), name)
        if self.start_ms is not None and self.end_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be later than start_ms")
        for name in ("paused", "active", "text_supported"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True)
class FileSubtitleSample:
    snapshot: SubtitleSnapshot
    index: Optional[int]
    latest_index: Optional[int]
    rewound: bool


class TimedTextSource:
    """One reusable timed-text timeline for any bridge with a media clock.

    Called serially by its owner. The bridge owns clock acquisition, file/track
    selection and the timer; it does not implement subtitle scheduling. Reuse
    this source for a separately supplied file even when a player cannot expose
    its own native caption text. Loading stays on the caller's worker thread.
    """

    def __init__(self, cues, generation=0):
        _integer(generation, "generation", 0)
        self.cues = tuple(sorted(cues))
        for cue in self.cues:
            _integer(cue.start, "cue.start")
            _integer(cue.end, "cue.end")
            if cue.end <= cue.start or not isinstance(cue.text, str):
                raise ValueError("invalid timed text cue")
        self.generation = generation
        self._sequence = 0
        self._last_time = None
        self._latest_index = None
        self._track = None

    @classmethod
    def from_file(cls, path, generation=0):
        return cls(subtitle_cues.load(path), generation)

    def sample(self, position, *, track="", source="file", enabled=True):
        if not isinstance(position, PlaybackPosition):
            raise TypeError("position must be a PlaybackPosition")
        if type(enabled) is not bool or not isinstance(track, str) or not isinstance(source, str) or not source:
            raise ValueError("invalid file source identity or enabled state")
        identity = (source, track)
        if self._track is not None and identity != self._track:
            self.generation += 1
            self._last_time = self._latest_index = None
        self._track = identity
        ms = position.subtitle_time_ms
        rewound = bool(enabled and ms is not None and self._last_time is not None and ms < self._last_time)
        if rewound:
            self.generation += 1
        index = None
        if enabled and ms is not None:
            self._last_time = ms
            index = subtitle_cues.active(self.cues, ms) if ms >= 0 else None
            self._latest_index = subtitle_cues.started(self.cues, ms) if ms >= 0 else None
        cue = self.cues[index] if index is not None else None
        self._sequence += 1
        snapshot = SubtitleSnapshot(
            text=cue.text if cue else "", source=source, track=track,
            generation=self.generation, sequence=self._sequence,
            start_ms=cue.start if cue else None, end_ms=cue.end if cue else None,
            paused=position.paused, active=enabled and ms is not None,
        )
        return FileSubtitleSample(snapshot, index, self._latest_index, rewound)
