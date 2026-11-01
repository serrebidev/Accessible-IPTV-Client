"""App-level responsiveness contract (issue #106, parent spec #105).

One shared gate for background work that publishes to the UI: playlist
publication, channel search, EPG and now-playing refresh. Each flow works
in a named *lane*. Starting work in a lane hands out a :class:`Ticket`
carrying that lane's new generation; starting newer work in the same lane
supersedes every older ticket, so stale work stops at its next checkpoint
and can never publish rows, labels, focus changes or announcements meant
for a superseded playlist, query or refresh.

Cancellation is cooperative: workers poll ``ticket.checkpoint()`` at
bounded intervals and stop when it turns False. Nothing here terminates
threads, database transactions, network requests or playback operations;
work that is already inside such an operation finishes it and simply
does not publish afterwards.

The gate also tracks interaction: the UI calls :meth:`WorkGate.note_interaction`
when the user types, navigates or starts playback, and interaction-
sensitive background work asks :meth:`WorkGate.should_yield` before each
bounded chunk, pausing while interaction is recent.

Stdlib only and wx-free, so every flow (and the tests) can use it without
a running application.
"""

import threading
import time

__all__ = ["Ticket", "WorkGate", "LANES"]

#: The lanes the spec names. Any string works as a lane; these are the
#: ones the app uses, kept together so callers share the same names.
LANES = ("playlist", "search", "epg", "now_playing")


class Ticket:
    """One unit of background work in a lane.

    A ticket is current only while no newer work has begun in its lane.
    Workers hold their ticket and consult it at bounded checkpoints.
    """

    __slots__ = ("_gate", "lane", "generation")

    def __init__(self, gate, lane, generation):
        self._gate = gate
        self.lane = lane
        self.generation = generation

    def is_current(self):
        """True while this ticket is still its lane's newest work."""
        return self._gate.generation(self.lane) == self.generation

    @property
    def cancelled(self):
        """True once newer work has superseded this ticket."""
        return not self.is_current()

    def checkpoint(self):
        """Cooperative cancellation point: True means keep going.

        Call at bounded intervals (per chunk of rows, per page of guide
        data); when it returns False the work has been superseded and
        must stop without publishing anything further.
        """
        return self.is_current()

    def __repr__(self):
        return f"Ticket(lane={self.lane!r}, generation={self.generation})"


class WorkGate:
    """Generations per lane plus the interaction-recency signal."""

    def __init__(self, clock=time.monotonic, interaction_window=0.35):
        self._clock = clock
        self._interaction_window = float(interaction_window)
        self._lock = threading.Lock()
        self._generations = {}
        self._last_interaction = None

    def begin(self, lane):
        """Start new work in ``lane``, superseding its older tickets."""
        with self._lock:
            generation = self._generations.get(lane, 0) + 1
            self._generations[lane] = generation
        return Ticket(self, lane, generation)

    def generation(self, lane):
        """The lane's current generation (0 when nothing has begun)."""
        with self._lock:
            return self._generations.get(lane, 0)

    def note_interaction(self):
        """Record that the user just typed, navigated or started playback."""
        with self._lock:
            self._last_interaction = self._clock()

    def interaction_active(self):
        """True while the last interaction is inside the yield window."""
        with self._lock:
            last = self._last_interaction
        return last is not None and (self._clock() - last) < self._interaction_window

    def should_yield(self, ticket):
        """True when background work holding ``ticket`` should pause.

        Superseded work yields permanently (it should stop, not pause);
        current work yields only while interaction is recent, so typing
        and navigation are never competing with a refresh for the UI.
        """
        return ticket.cancelled or self.interaction_active()
