"""Make the screen reader speak a static text control's current label.

NVDA ignores EVENT_SYSTEM_ALERT unless the object's role is Alert, so the alert
alone left player status and subtitle cues silent there. A live-region change is
read as plain text. The alert stays for readers that rely on it. Either way only a
control inside the foreground window is read.
"""

import ctypes
import logging
import sys

import wx

LOG = logging.getLogger(__name__)
EVENT_OBJECT_LIVEREGIONCHANGED = 0x8019
OBJID_CLIENT = -4


def notify(ctrl: wx.Window) -> None:
    try:
        wx.Accessible.NotifyEvent(wx.ACC_EVENT_SYSTEM_ALERT, ctrl, wx.OBJID_CLIENT, 0)
    except Exception:
        LOG.debug("Could not raise alert event", exc_info=True)
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.NotifyWinEvent(
                EVENT_OBJECT_LIVEREGIONCHANGED, ctrl.GetHandle(), OBJID_CLIENT, 0)
        except Exception:
            LOG.debug("Could not raise live region event", exc_info=True)
