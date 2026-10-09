"""Single owner for subtitle-speech sessions (issue #45, item 6).

Every playback transition explicitly activates one session and cancels the
previous one. Sessions carry a globally monotonic token (UUID) in addition
to the source-local media generation, so a stale cue from an old session
can never be spoken after a channel/player switch.

The controller owns:
- the active SubtitleSpeechManager session token
- the MPV adapter lifetime (close on every player/source transition)
- UI-thread callback validation (queued speech revalidates the token)
"""

import logging
import threading
import uuid
from typing import Callable, Optional

LOG = logging.getLogger(__name__)


class SubtitleSessionController:
    """One active subtitle session at a time, owned by the main window."""

    def __init__(self, manager):
        self._manager = manager
        self._lock = threading.RLock()
        self._session_token: Optional[str] = None
        self._adapter = None
        self._ui_thread: Optional[Callable] = None

    def set_ui_thread(self, ui_thread: Callable) -> None:
        """Set the UI-thread marshaller (e.g. wx.CallAfter)."""
        with self._lock:
            self._ui_thread = ui_thread

    @property
    def session_token(self) -> Optional[str]:
        with self._lock:
            return self._session_token

    def activate_session(self, source_name: str = "") -> str:
        """Start a new session, cancelling the previous one.

        Returns the new session token. Clears manager state and closes
        any active adapter.
        """
        token = uuid.uuid4().hex
        with self._lock:
            old_token = self._session_token
            self._session_token = token
            if old_token:
                LOG.debug("subtitle session: %s superseded by %s",
                          old_token[:8], token[:8])
        # Cancel outside the lock: close adapter, clear manager.
        self._close_adapter()
        self._manager.set_source(source_name)
        return token

    def cancel_session(self) -> None:
        """Cancel the active session without starting a new one."""
        with self._lock:
            self._session_token = None
        self._close_adapter()
        self._manager.clear()

    def is_current(self, token: str) -> bool:
        """Check if a token is still the active session."""
        with self._lock:
            return self._session_token is not None and self._session_token == token

    def set_adapter(self, adapter) -> None:
        """Register the active MPV adapter for lifetime management."""
        with self._lock:
            old = self._adapter
            self._adapter = adapter
        if old is not None and old is not adapter:
            try:
                old.close()
            except Exception:
                LOG.debug("subtitle session: old adapter close failed",
                          exc_info=True)

    def _close_adapter(self) -> None:
        with self._lock:
            adapter, self._adapter = self._adapter, None
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                LOG.debug("subtitle session: adapter close failed",
                          exc_info=True)

    def speak_validated(self, token: str, text: str,
                        speak_fn: Callable[[str], None]) -> bool:
        """Speak text on the UI thread only if the session is still current.

        Returns True if the speech was queued (session was current).
        """
        if not self.is_current(token):
            LOG.debug("subtitle session: stale cue dropped (session changed)")
            return False

        def _do() -> None:
            # Revalidate on the UI thread: the session may have changed
            # while this callback was queued.
            if not self.is_current(token):
                LOG.debug("subtitle session: stale UI callback dropped")
                return
            try:
                speak_fn(text)
            except Exception:
                LOG.debug("subtitle session: speak failed", exc_info=True)

        ui_thread = self._ui_thread
        if ui_thread:
            try:
                ui_thread(_do)
            except Exception:
                LOG.debug("subtitle session: ui_thread marshal failed",
                          exc_info=True)
                return False
        else:
            _do()
        return True
