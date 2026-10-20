"""The app-wide record that a modal message box is on screen.

Opening a second message box from inside the first one's message loop
desynchronizes wxMSW's parent-enable bookkeeping and leaves the main frame
permanently disabled - NVDA calls it "unavailable" and Alt+F4 and Escape do
nothing. A recording that finishes while the player shows "No active stream
to cast." used to land exactly there.

The queueing guard in ``IPTVClient`` can only defer a notification if it knows
a box is up, so *every* box in the app goes through :func:`message_box`. It
lives in its own module because the player and the playlist dialogs open boxes
too, and they cannot import ``main`` (``main`` imports them).
"""

import logging

import wx

LOG = logging.getLogger(__name__)

_MODAL_BOX_DEPTH = 0
_MODAL_BOX_CLOSED_HOOK = None


def message_box(*args, **kwargs):
    """``wx.MessageBox`` that records, app-wide, that a modal box is on screen."""
    global _MODAL_BOX_DEPTH
    _MODAL_BOX_DEPTH += 1
    try:
        return wx.MessageBox(*args, **kwargs)
    finally:
        _MODAL_BOX_DEPTH = max(0, _MODAL_BOX_DEPTH - 1)
        if _MODAL_BOX_DEPTH == 0:
            _notify_modal_boxes_closed()


def modal_box_is_open() -> bool:
    """True while any box opened through :func:`message_box` is showing."""
    return _MODAL_BOX_DEPTH > 0


def set_modal_box_closed_hook(hook) -> None:
    """Register the callback that flushes notifications queued behind a box."""
    global _MODAL_BOX_CLOSED_HOOK
    _MODAL_BOX_CLOSED_HOOK = hook


def _notify_modal_boxes_closed() -> None:
    hook = _MODAL_BOX_CLOSED_HOOK
    if hook is None:
        return

    def run():
        # The hook is a bound method of the main frame; a frame torn down
        # between the box closing and this idle callback raises RuntimeError.
        try:
            hook()
        except RuntimeError:
            LOG.debug("_notify_modal_boxes_closed: frame is gone", exc_info=True)

    try:
        wx.CallAfter(run)
    except Exception:
        LOG.debug("_notify_modal_boxes_closed: ignored exception", exc_info=True)
