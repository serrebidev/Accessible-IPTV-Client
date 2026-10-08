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
import threading
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
    """A single subtitle cue ready for speech or review.

    ``generation`` is the source's media-generation identity (new programme,
    new file, new subtitle track). Cues are keyed on generation + track +
    timing + text, so replay after seek is intentional but reconnects and
    late events from an old stream never speak the wrong programme.
    """

    text: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    source: str = ""  # "builtin-file" or "mpv-ipc"
    track: str = ""  # subtitle track identity, when known
    generation: int = 0  # media-generation identity from the source


class SubtitleSpeechManager:
    """Central subtitle speech: cue queue, speech output, capability tracking.

    Thread ownership (issue #37): cue sources may call from any thread (the
    MPV IPC reader runs off the GUI thread). All manager state is guarded by
    a lock, and speech output plus the error callback are marshalled through
    ``ui_thread`` (e.g. ``wx.CallAfter``), which must run callables on the
    application's UI thread. The injected ``speak_fn`` itself therefore only
    ever executes on the UI thread.

    Sources call :meth:`on_cue` when a new cue becomes active. The manager
    speaks it if auto-speech is enabled, and always records it for review.
    A source switch, stop, or track change must call :meth:`clear` so stale
    cues are never spoken or reviewed.
    """

    def __init__(
        self,
        speak_fn: Callable[[str], None],
        ui_thread: Optional[Callable[..., None]] = None,
        on_speak_error: Optional[Callable[[str, Exception], None]] = None,
    ):
        self._speak = speak_fn
        # Marshals callables onto the UI thread; default runs them inline
        # (single-threaded callers such as tests).
        self._ui_thread = ui_thread or (lambda fn, *args: fn(*args))
        # Accessible failure path: called on the UI thread when the speech
        # backend raises, so the user hears the failure as text rather than
        # it dying silently in a debug log.
        self._on_speak_error = on_speak_error
        self._lock = threading.RLock()
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
        with self._lock:
            self._auto_speech = bool(enabled)

    # -- Cue intake (called by sources) ------------------------------------

    def on_cue(
        self,
        text: str,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        source: str = "",
        track: str = "",
        generation: int = 0,
    ) -> None:
        """A new cue became active. Speak it if auto-speech is on.

        Duplicate suppression is keyed on generation + track + timing + text,
        never on wording alone: two genuine consecutive cues that both say
        "Yes." are both recorded and spoken. A re-send of the *same* cue
        (sources such as MPV deliver text/start/end as separate property
        changes) only fills in the timing and track already on the current
        cue, without re-speaking or duplicating history.
        """
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            current = self._current
            if (
                current is not None
                and current.generation == generation
                and current.text == text
                and (start_ms is None or current.start_ms is None
                     or start_ms == current.start_ms)
            ):
                # Same cue, timing/track arriving separately: merge in place.
                if start_ms is not None:
                    current.start_ms = start_ms
                if end_ms is not None:
                    current.end_ms = end_ms
                if track:
                    current.track = track
                return
            event = CueEvent(
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                source=source or self._source_name,
                track=track or "",
                generation=generation,
            )
            self._previous = self._current
            self._current = event
            self._recent.append(event)
            auto = self._auto_speech
        if auto:
            self._speak_text(text)

    def update_cue_timing(
        self,
        start_ms: Optional[int],
        end_ms: Optional[int],
        generation: int = 0,
    ) -> None:
        """Fill in timing for the current cue without speaking it.

        For sources that deliver text and timing as separate events (MPV's
        sub-text vs sub-start/sub-end): the text arrival creates the cue via
        :meth:`on_cue`; later timing arrivals land here. A timing event for
        a different generation is ignored.
        """
        with self._lock:
            current = self._current
            if current is None or current.generation != generation:
                return
            if start_ms is not None:
                current.start_ms = start_ms
            if end_ms is not None:
                current.end_ms = end_ms

    def _speak_text(self, text: str) -> None:
        """Speak on the UI thread; route failures to the error callback."""

        def _do() -> None:
            try:
                self._speak(text)
            except Exception as exc:
                LOG.debug("subtitle speech: speak failed", exc_info=True)
                if self._on_speak_error is not None:
                    try:
                        self._on_speak_error(text, exc)
                    except Exception:
                        LOG.debug("subtitle speech: error callback failed",
                                  exc_info=True)

        try:
            self._ui_thread(_do)
        except Exception:
            LOG.debug("subtitle speech: ui_thread marshal failed", exc_info=True)

    def clear(self) -> None:
        """Clear all cue state (track change, stop, source switch, disconnect).

        Review history is cleared too: review must never expose cues from a
        previous channel, programme, media generation or subtitle track.
        """
        with self._lock:
            self._current = None
            self._previous = None
            self._recent.clear()

    def set_source(self, name: str) -> None:
        """Switch the active cue source, clearing stale state first."""
        with self._lock:
            self._source_name = name or ""
        self.clear()

    # -- On-demand reading --------------------------------------------------

    def read_current(self) -> bool:
        """Speak the current cue. Returns True if there was one."""
        with self._lock:
            text = self._current.text if self._current else None
        if text:
            self._speak_text(text)
            return True
        return False

    def read_previous(self) -> bool:
        """Speak the previous cue. Returns True if there was one."""
        with self._lock:
            text = self._previous.text if self._previous else None
        if text:
            self._speak_text(text)
            return True
        return False

    def get_recent(self, count: int = 10) -> List[CueEvent]:
        """Recent cues, oldest first, for review."""
        with self._lock:
            items = list(self._recent)
        return items[-count:] if count > 0 else items

    # -- Capabilities -------------------------------------------------------

    def set_capability(self, player: str, capability: str, state: str) -> None:
        """Record a capability state for a player."""
        if capability not in ALL_CAPABILITIES:
            raise ValueError(f"Unknown capability: {capability}")
        if state not in (AVAILABLE, UNAVAILABLE, UNVERIFIED):
            raise ValueError(f"Unknown state: {state}")
        with self._lock:
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

    def describe_capability(
        self,
        player: str,
        capability: str,
        gettext: Optional[Callable[[str], str]] = None,
    ) -> str:
        """Short human-readable state for UI reporting.

        User-facing descriptions go through the caller's translation
        function (issue #37) rather than staying hard-coded English.
        """
        _ = gettext or (lambda s: s)
        state = self.get_capability(player, capability)
        if state == AVAILABLE:
            return _("available")
        if state == UNAVAILABLE:
            return _("not supported by this player")
        return _("not verified yet")
