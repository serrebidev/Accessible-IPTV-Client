"""Player-independent subtitle speech: cue queue, speech routing, capabilities.

Per issue #37: one accessible presentation/speech layer fed by multiple cue
sources (built-in SRT/WebVTT files, the MPV IPC adapter). Each source uses the
clock and track identity of the player actually rendering the programme.

Capabilities are tracked per player: enumerate tracks, select/disable track,
load external subtitle, obtain timed text cues, control time/seek, and read
the current/previous cue. Each is available, unavailable, or unverified.

Speech output always goes through the injected ``speak`` callable, which the
application wires to either the screen reader (JAWS/NVDA keep ownership of
their voice, volume and audio endpoint) or the optional application-owned TTS
backend (which owns its own volume and output device). This module never
touches audio itself.
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, List, Optional

LOG = logging.getLogger(__name__)

# Capability states per the #37 plan.
AVAILABLE = "available"
UNAVAILABLE = "unavailable"
UNVERIFIED = "unverified"

# Capability names.
CAP_ENUMERATE_TRACKS = "enumerate_tracks"
CAP_SELECT_TRACK = "select_track"
CAP_LOAD_EXTERNAL = "load_external"
CAP_TIMED_CUES = "timed_cues"
CAP_SEEK = "seek"
CAP_READ_CURRENT = "read_current"
CAP_READ_PREVIOUS = "read_previous"

ALL_CAPABILITIES = [
    CAP_ENUMERATE_TRACKS,
    CAP_SELECT_TRACK,
    CAP_LOAD_EXTERNAL,
    CAP_TIMED_CUES,
    CAP_SEEK,
    CAP_READ_CURRENT,
    CAP_READ_PREVIOUS,
]

# Bounded recent-cue history for review (per #37: "review recent cues").
MAX_RECENT_CUES = 50

#: Honest baseline for timed caption text per player, from the #37 audit.
#: A working executable, visible subtitles, or a track-selection API does not
#: establish an API for obtaining the displayed words, so every player without
#: a documented, versioned timed-text API stays unavailable rather than
#: guessed at. Runtimes promote entries to available once actually verified.
BASELINE_CAPABILITIES: Dict[str, Dict[str, str]] = {
    # Built-in player: application-owned SRT/WebVTT parser, verified.
    "built-in": {
        CAP_ENUMERATE_TRACKS: AVAILABLE,
        CAP_SELECT_TRACK: AVAILABLE,
        CAP_LOAD_EXTERNAL: AVAILABLE,
        CAP_TIMED_CUES: AVAILABLE,
        CAP_SEEK: AVAILABLE,
        CAP_READ_CURRENT: AVAILABLE,
        CAP_READ_PREVIOUS: AVAILABLE,
    },
    # MPV: sub-text/sub-start/sub-end via JSON IPC, but only through our own
    # session adapter and only for text subtitles (bitmap stays unavailable).
    "MPV": {
        CAP_ENUMERATE_TRACKS: UNVERIFIED,
        CAP_SELECT_TRACK: UNVERIFIED,
        CAP_LOAD_EXTERNAL: UNVERIFIED,
        CAP_TIMED_CUES: UNVERIFIED,
        CAP_SEEK: UNVERIFIED,
        CAP_READ_CURRENT: UNVERIFIED,
        CAP_READ_PREVIOUS: UNVERIFIED,
    },
    # VLC: single-instance flags only; no timed-text API.
    "VLC": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
    # MPC-HC / MPC-BE: URL handoff only; no timed-text API.
    "MPC": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
    "MPC-BE": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
    # PotPlayer: URL handoff only; no timed-text API.
    "PotPlayer": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
    # Kodi: JSON-RPC documents subtitle enumeration/selection, but those
    # metadata controls alone do not provide timed caption text.
    "Kodi": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
}


@dataclass
class CueEvent:
    """A single subtitle cue ready for speech or review."""

    text: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    source: str = ""  # "builtin-file" or "mpv-ipc"
    track: str = ""  # subtitle track identity, when known


class SubtitleSpeechManager:
    """Central subtitle speech: cue queue, speech output, capability tracking.

    Sources call :meth:`on_cue` when a new cue becomes active. The manager
    speaks it if auto-speech is enabled, and always records it for review.
    A source switch, stop, or track change must call :meth:`clear` (or
    :meth:`set_source`) so stale cues are never spoken.
    """

    def __init__(self, speak_fn: Callable[[str], None]):
        self._speak = speak_fn
        self._auto_speech = False
        self._recent: Deque[CueEvent] = deque(maxlen=MAX_RECENT_CUES)
        self._current: Optional[CueEvent] = None
        self._previous: Optional[CueEvent] = None
        self._capabilities: Dict[str, Dict[str, str]] = {}
        self._source_name = ""

    # -- Configuration ----------------------------------------------------

    @property
    def auto_speech(self) -> bool:
        return self._auto_speech

    def set_auto_speech(self, enabled: bool) -> None:
        self._auto_speech = bool(enabled)

    # -- Cue intake (called by sources) ------------------------------------

    def on_cue(
        self,
        text: str,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        source: str = "",
        track: str = "",
    ) -> None:
        """A new cue became active. Speak it if auto-speech is on."""
        text = (text or "").strip()
        if not text:
            return
        # Same text as the current cue: fill in timing/track that arrived
        # separately (mpv sends sub-text/sub-start/sub-end as separate
        # property changes) without re-speaking or duplicating history.
        if self._current and self._current.text == text:
            if start_ms is not None:
                self._current.start_ms = start_ms
            if end_ms is not None:
                self._current.end_ms = end_ms
            if track:
                self._current.track = track
            return
        event = CueEvent(
            text=text,
            start_ms=start_ms,
            end_ms=end_ms,
            source=source or self._source_name,
            track=track or "",
        )
        self._previous = self._current
        self._current = event
        self._recent.append(event)
        if self._auto_speech:
            try:
                self._speak(text)
            except Exception:
                LOG.debug("subtitle speech: speak failed", exc_info=True)

    def clear(self) -> None:
        """Clear current state (e.g. on track change, stop, source switch)."""
        self._current = None
        self._previous = None

    def set_source(self, name: str) -> None:
        """Switch the active cue source, clearing stale state first."""
        self._source_name = name or ""
        self.clear()

    # -- On-demand reading --------------------------------------------------

    def read_current(self) -> bool:
        """Speak the current cue. Returns True if there was one."""
        if self._current:
            try:
                self._speak(self._current.text)
            except Exception:
                return False
            return True
        return False

    def read_previous(self) -> bool:
        """Speak the previous cue. Returns True if there was one."""
        if self._previous:
            try:
                self._speak(self._previous.text)
            except Exception:
                return False
            return True
        return False

    def get_recent(self, count: int = 10) -> List[CueEvent]:
        """Recent cues, oldest first, for review."""
        items = list(self._recent)
        return items[-count:] if count > 0 else items

    # -- Capabilities -------------------------------------------------------

    def set_capability(self, player: str, capability: str, state: str) -> None:
        """Record a capability state for a player."""
        if capability not in ALL_CAPABILITIES:
            raise ValueError(f"Unknown capability: {capability}")
        if state not in (AVAILABLE, UNAVAILABLE, UNVERIFIED):
            raise ValueError(f"Unknown state: {state}")
        self._capabilities.setdefault(player, {})[capability] = state

    def get_capability(self, player: str, capability: str) -> str:
        """Capability state: recorded value, else the honest baseline, else unverified."""
        recorded = self._capabilities.get(player, {}).get(capability)
        if recorded is not None:
            return recorded
        return BASELINE_CAPABILITIES.get(player, {}).get(capability, UNVERIFIED)

    def get_capabilities(self, player: str) -> Dict[str, str]:
        """All capability states for a player."""
        return {cap: self.get_capability(player, cap) for cap in ALL_CAPABILITIES}

    def describe_capability(self, player: str, capability: str) -> str:
        """Short human-readable state for UI reporting."""
        state = self.get_capability(player, capability)
        if state == AVAILABLE:
            return "available"
        if state == UNAVAILABLE:
            return "not supported by this player"
        return "not verified yet"
