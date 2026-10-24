"""wx helpers shared by dialogs and the windows that raise them.

wx-free imports only, and nothing here imports main.py: the dialogs module and
the main frame both use these, so putting them in main would be a cycle.
"""
import logging
import sys

import wx

LOG = logging.getLogger("EPG.ui")


def _window_alive(window) -> bool:
    """True while the wx window still exists.

    A destroyed window raises on every call, so any code that keeps a window
    around for later - a queued notification, a focus restore - has to probe
    it before it uses it.
    """
    if window is None:
        return False
    try:
        window.IsShown()
    except RuntimeError:
        return False
    return True


def _context_row_index(list_ctrl, event, keep_multi_selection: bool = False) -> int:
    """The row the user right-clicked, selected so the action uses it.

    A right-click does not move the selection in a list control, so a menu
    built from the selected row acts on the wrong one: the user pointed at
    a programme and the app took another. The channel list has always
    hit-tested here; the programme lists did not.

    ``keep_multi_selection`` is for a list that allows several rows to be
    selected: a right-click on one of them keeps the selection, and on any
    other row selects that row alone.
    """
    try:
        selected = list_ctrl.GetFirstSelected()
    except Exception:
        return -1
    if event is None:
        return selected
    try:
        pos = event.GetPosition()
        if pos == wx.DefaultPosition or (pos.x == -1 and pos.y == -1):
            return selected
        local = list_ctrl.ScreenToClient(pos)
        hit = list_ctrl.HitTest(local)
        hit_idx = hit[0] if isinstance(hit, tuple) else hit
    except Exception:
        LOG.debug("_context_row_index: ignored exception", exc_info=True)
        return selected
    if hit_idx in (None, -1) or hit_idx >= list_ctrl.GetItemCount():
        return selected
    if keep_multi_selection and list_ctrl.IsItemSelected(hit_idx):
        return selected
    list_ctrl.Select(hit_idx)
    list_ctrl.Focus(hit_idx)
    ensure_visible = getattr(list_ctrl, "EnsureVisible", None)
    if callable(ensure_visible):
        ensure_visible(hit_idx)
    return hit_idx


def _show_on_taskbar(window) -> None:
    """Give an owned window its own taskbar button and Alt+Tab entry (Windows).

    wx dialogs are owned by their parent, and Windows leaves owned windows
    off the taskbar and out of Alt+Tab. For a long-running modeless window
    that means a keyboard user who steps back to the main window has no way
    back to it. WS_EX_APPWINDOW overrides that; it must be set before the
    window is first shown.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.WinDLL("user32")  # private handle: our argtypes only
        get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        set_style = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        get_style.restype = ctypes.c_ssize_t
        get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
        set_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        gwl_exstyle, ws_ex_appwindow = -20, 0x00040000
        hwnd = ctypes.c_void_p(int(window.GetHandle()))
        set_style(hwnd, gwl_exstyle, get_style(hwnd, gwl_exstyle) | ws_ex_appwindow)
    except Exception:
        LOG.debug("_show_on_taskbar: ignored exception", exc_info=True)
