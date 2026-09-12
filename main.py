import os
import sys
import shutil
import json
import tempfile
import urllib.request
import urllib.parse
import sqlite3
import threading
import logging
from typing import Dict, List, Optional, Tuple
import wx
import datetime
import re
import platform
import time
import subprocess
import hashlib
import concurrent.futures

# Child of the rotating-file "EPG" logger configured in playlist.py, so UI/search
# diagnostics land in the same log file and honor the same EPG_DEBUG switch.
LOG = logging.getLogger("EPG.ui")

import wx.adv

import i18n
from i18n import gettext as _
from i18n import N_

from options import (
    load_config, save_config, get_cache_path_for_url, get_cache_dir,
    get_db_path, utc_to_local,
    CustomPlayerDialog, resolve_internal_player_settings, get_app_dir,
    get_recordings_dir, get_dvr_schedule_path, get_logs_dir, get_epg_log_path,
    normalize_recording_format, coerce_channel_audio_tracks,
    coerce_channel_audio_track_indices, MAX_AUDIO_TRACKS,
    is_windows_installed_build, get_user_config_dir
)
# Same normalization the EPG database indexes with - importing it from anywhere
# else is how the UI and the database drift apart.
from channel_names import canonicalize_name, strip_noise_words
import app_meta
import updater
from playlist import (
    EPGDatabase, EPGManagerDialog, PlaylistManagerDialog,
    epg_database_has_usable_data
)
from playlist import (source_name_key, normalize_source_names,
                      _expand_tvg_id_candidates)
from providers import (
    XtreamCodesClient, XtreamCodesConfig,
    StalkerPortalClient, StalkerPortalConfig,
    ProviderError, generate_provider_id
)
import vod
import account_info
from http_headers import channel_http_headers, merge_headers, split_stream_modifiers
from audio_tracks import (
    active_audio_track_index,
    names_audio_description,
    ordered_preference_keywords,
    select_preferred_audio_track,
)
from external_player import ExternalPlayerLauncher
import recorder
from recorder import RECORDING_FORMATS
from recorder import format_duration, format_size, parse_ffmpeg_progress, written_size
from recorder import audio_stream_label, probe_audio_streams
import catchup_direct
import dvr
import favorites
import power
import user_guide

TELEGRAM_SUPPORT_URL = "https://t.me/SerrebiProjects"
PROJECT_GITHUB_URL = "https://github.com/{owner}/Accessible-IPTV-Client".format(
    owner=app_meta.GITHUB_OWNER)
SERREBI_GITHUB_URL = "https://github.com/serrebidev"

_INTERNAL_PLAYER_FRAME_CLASS = None
_INTERNAL_PLAYER_IMPORT_ATTEMPTED = False
_INTERNAL_PLAYER_IMPORT_ERROR = None

# The value stored in config["playlist_scope"] (and shown in the scope combo)
# when no single playlist is selected: categories and channels come from every
# loaded playlist.
ALL_PLAYLISTS_SCOPE = ""


def _source_scope_id(src) -> str:
    """The stable id that tags a playlist's channels for the scope filter."""
    if isinstance(src, dict):
        return str(src.get("id") or src.get("provider_id") or "")
    if isinstance(src, str) and src.strip():
        return "m3u:" + hashlib.sha256(src.encode("utf-8")).hexdigest()
    return ""


def _scope_includes_channel(ch: Dict[str, str], scope: str) -> bool:
    """True when ``ch`` belongs to the playlist selected by ``scope``.

    The "All playlists" sentinel accepts everything, including legacy channels
    that never got a playlist tag. A specific scope requires the tag to match,
    so an untagged channel (a pre-existing cache, or a source without an id)
    stays out of a single playlist's view instead of leaking into it.
    """
    if scope == ALL_PLAYLISTS_SCOPE:
        return True
    return bool(ch.get("playlist-id")) and ch.get("playlist-id") == scope


def _scoped_channels(channels, scope: str):
    """The channels of ``channels`` that belong to playlist ``scope``."""
    if scope == ALL_PLAYLISTS_SCOPE:
        return channels
    return [ch for ch in channels if _scope_includes_channel(ch, scope)]


def _client_pid_scope(pid: str, scope: str) -> bool:
    """Whether a provider client id belongs to the playlist scope.

    A provider id embeds the source's stable id; matching by containment keeps
    this tolerant of the wrapper formats without needing a second registry.
    """
    if not scope:
        return True
    return scope in str(pid or "")


def _tagged_sources(sources) -> list:
    """The playlist sources that carry a stable id, in the order given.

    Sources without one are hidden from the scope picker: selecting them would
    promise "only this playlist" and then deliver everything.
    """
    return [src for src in (sources or [])
            if _source_scope_id(src)]


_MODAL_BOX_DEPTH = 0
_MODAL_BOX_CLOSED_HOOK = None


def message_box(*args, **kwargs):
    """``wx.MessageBox`` that records, app-wide, that a modal box is on screen.

    Opening a second message box from inside the first one's message loop
    desynchronizes wxMSW's parent-enable bookkeeping and leaves the main frame
    permanently disabled - NVDA calls it "unavailable" and Alt+F4 and Escape do
    nothing. Recording finish callbacks arrive from a watcher thread and used to
    land exactly there, on top of the "Stopping recording..." box. The queueing
    guard in ``IPTVClient`` can only defer them if it knows a box is up, so
    *every* box in this module goes through here and bumps the counter.
    """
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


def _modal_dialog_is_open() -> bool:
    """True while any wx dialog is running modally."""
    try:
        return any(isinstance(window, wx.Dialog) and window.IsModal()
                   for window in wx.GetTopLevelWindows())
    except Exception:
        return False


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


class InternalPlayerUnavailableError(RuntimeError):
    """Raised when the built-in VLC player cannot be loaded."""


class AccessibleAboutDialog(wx.Dialog):
    """A keyboard-first About dialog whose support links are real tab stops."""

    help_topic = "support"

    def __init__(self, parent):
        from app_meta import APP_DISPLAY_NAME, APP_VERSION

        super().__init__(
            parent,
            title=_("About {name}").format(name=APP_DISPLAY_NAME),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(
            panel,
            label=_("{name} {version}").format(name=APP_DISPLAY_NAME, version=APP_VERSION),
        )
        heading.SetFont(heading.GetFont().Bold())
        layout.Add(heading, 0, wx.ALL, 12)

        description = wx.StaticText(
            panel,
            label=_("A screen reader accessible IPTV client for Windows and Linux.\n\n"
                    "Supports M3U/M3U Plus playlists, Stalker Portal, Xtream Codes, "
                    "built-in VLC playback, casting, and XMLTV EPG."),
        )
        description.Wrap(500)
        layout.Add(description, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        support = wx.StaticText(panel, label=_("Community and support"))
        support.SetFont(support.GetFont().Bold())
        layout.Add(support, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        for label, url in (
            (_("Join the SerrebiProjects Telegram group"), TELEGRAM_SUPPORT_URL),
            (_("Open the Accessible IPTV Client project on GitHub"), PROJECT_GITHUB_URL),
            (_("Follow Serrebi on GitHub"), SERREBI_GITHUB_URL),
        ):
            link = wx.adv.HyperlinkCtrl(panel, label=label, url=url)
            link.SetName(label)
            # wxMSW's HyperlinkCtrl has no key handling of its own: with the
            # dialog's default OK button present, Enter and Space closed the
            # About dialog instead of opening the link. Route those two keys
            # (and the click) to the browser -- and *only* those two. The
            # handler used to open the link for every key, so Tab (and every
            # arrow key) launched a browser window while merely moving through
            # the dialog; a few presses buried the screen in windows.
            def _open_link(_event=None, _url=url):
                wx.LaunchDefaultBrowser(_url)

            def _on_link_key(event, _open=_open_link):
                if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
                    _open()
                    return
                event.Skip()

            link.Bind(wx.EVT_CHAR_HOOK, _on_link_key)
            link.Bind(wx.adv.EVT_HYPERLINK, _open_link)
            link.Bind(wx.EVT_LEFT_DCLICK, _open_link)
            layout.Add(link, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Create buttons on the panel and handle both exit paths explicitly.
        # ``CreateButtonSizer`` creates children of the dialog itself; placing
        # those children in a panel sizer leaves wxMSW without a usable command
        # route, which made the original About dialog impossible to dismiss.
        button_sizer = wx.StdDialogButtonSizer()
        self.ok_btn = wx.Button(panel, id=wx.ID_OK)
        self.close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        button_sizer.AddButton(self.ok_btn)
        button_sizer.AddButton(self.close_btn)
        button_sizer.Realize()
        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        panel.SetSizerAndFit(layout)
        self.SetMinSize((540, -1))
        self.Fit()
        self.CentreOnParent()
        self.ok_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish(wx.ID_OK))
        self.close_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish(wx.ID_CANCEL))
        self.Bind(wx.EVT_CLOSE, lambda _event: self._finish(wx.ID_CANCEL))
        self.SetEscapeId(wx.ID_CANCEL)
        self.ok_btn.SetDefault()

    def _finish(self, result):
        if self.IsModal():
            self.EndModal(result)
        else:
            self.Destroy()


class UserGuideDialog(wx.Dialog):
    """The offline User Guide: its table of contents, the text, and Find.

    The whole guide sits in one read-only rich-edit box, so a screen reader can
    read straight through it and the arrow keys, selection and copying behave
    as in any document. Topics is the table of contents: arrowing through it
    moves the text to that section without taking focus away, and Enter goes
    into the text. TE_RICH2 matters here: its caret positions are Python string
    offsets, which is what section starts and Find results are. A plain EDIT
    control counts every line break twice and lands each jump a little early.
    """

    help_topic = user_guide.HELP_TOPIC

    def __init__(self, parent, topic: str = "", language: Optional[str] = None):
        super().__init__(
            parent,
            title=_("User Guide"),
            size=(820, 580),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
        )
        # OSError when not even the English guide is installed; the caller says so.
        self.guide, section = user_guide.open_topic(language or i18n.resolved_language(), topic)
        self._folded_text = self._fold(self.guide.text)
        panel = wx.Panel(self)

        # Each label is created immediately before its control: on MSW that
        # adjacent static text is what names a list or edit box aloud.
        topics_label = wx.StaticText(panel, label=_("Topics"))
        self.topics_list = wx.ListBox(
            panel, choices=[s.title for s in self.guide.sections], style=wx.LB_SINGLE)
        self.topics_list.SetName(_("Topics"))
        text_label = wx.StaticText(panel, label=_("Guide text"))
        self.text = wx.TextCtrl(
            panel, value=self.guide.text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.text.SetName(_("Guide text"))
        find_label = wx.StaticText(panel, label=_("Find"))
        self.find_box = wx.TextCtrl(panel)
        self.find_box.SetName(_("Find"))
        self.find_btn = wx.Button(panel, label=_("Find Next"))
        self.close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(topics_label, 0, wx.BOTTOM, 4)
        left.Add(self.topics_list, 1, wx.EXPAND)
        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(text_label, 0, wx.BOTTOM, 4)
        right.Add(self.text, 1, wx.EXPAND)
        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(left, 1, wx.EXPAND | wx.RIGHT, 10)
        body.Add(right, 3, wx.EXPAND)
        bottom = wx.BoxSizer(wx.HORIZONTAL)
        bottom.Add(find_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        bottom.Add(self.find_box, 1, wx.ALIGN_CENTER_VERTICAL)
        bottom.Add(self.find_btn, 0, wx.LEFT, 6)
        bottom.Add(self.close_btn, 0, wx.LEFT, 24)
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(body, 1, wx.EXPAND | wx.ALL, 10)
        layout.Add(bottom, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(layout)
        self.SetMinSize((520, 380))
        self.CentreOnParent()

        self.topics_list.Bind(wx.EVT_LISTBOX, self._on_topic_highlighted)
        self.topics_list.Bind(wx.EVT_LISTBOX_DCLICK, lambda _event: self._enter_selected_topic())
        # EVT_CHAR_HOOK: a dialog takes Enter before a list's key-down sees it.
        self.topics_list.Bind(wx.EVT_CHAR_HOOK, self._on_topics_key)
        self.topics_list.Bind(wx.EVT_SET_FOCUS, self._on_topics_focus)
        self.find_btn.Bind(wx.EVT_BUTTON, lambda _event: self.find(forward=True))
        self.close_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish())
        self.Bind(wx.EVT_CLOSE, lambda _event: self._finish())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.SetEscapeId(wx.ID_CANCEL)

        self._show_section(section, focus=False)
        # wxMSW gives a new dialog's focus to its first control once the modal
        # loop is running, so a SetFocus made here would not last.
        wx.CallAfter(self._focus_text)

    @staticmethod
    def _fold(text: str) -> str:
        """Lower-case ``text`` without changing its length, so Find offsets stay exact."""
        # str.lower() can lengthen a string (a Turkish dotted capital I becomes
        # two code points), which would shift every match after it.
        return "".join(ch.lower() if len(ch.lower()) == 1 else ch for ch in text)

    def _focus_text(self) -> None:
        if not self:
            return
        self.text.SetFocus()

    def _selected_section(self) -> Optional[user_guide.Section]:
        index = self.topics_list.GetSelection()
        if 0 <= index < len(self.guide.sections):
            return self.guide.sections[index]
        return None

    def _show_section(self, section: Optional[user_guide.Section], focus: bool) -> None:
        """Put the caret on the heading of ``section``, scrolled to the top."""
        if section is None:
            return
        try:
            index = self.guide.sections.index(section)
        except ValueError:
            index = wx.NOT_FOUND
        if index != wx.NOT_FOUND and self.topics_list.GetSelection() != index:
            self.topics_list.SetSelection(index)
        self.text.SetInsertionPoint(section.start)
        self.text.ShowPosition(section.start)
        if focus:
            self.text.SetFocus()

    def show_topic(self, topic: str) -> None:
        """Jump to ``topic`` (the start of the guide when this language lacks it)."""
        section = self.guide.find(topic) or (self.guide.sections[0] if self.guide.sections else None)
        self._show_section(section, focus=True)

    def _on_topic_highlighted(self, _event) -> None:
        # Arrowing through Topics only moves the text; focus stays in the list
        # so the next topic can be heard. Enter (or Tab) goes into the text.
        self._show_section(self._selected_section(), focus=False)

    def _enter_selected_topic(self) -> None:
        self._show_section(self._selected_section(), focus=True)

    def _on_topics_key(self, event) -> None:
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._enter_selected_topic()
            return
        event.Skip()

    def _on_topics_focus(self, event) -> None:
        # Back in Topics after reading on: highlight the section the caret is in.
        self._sync_topic_to_caret()
        event.Skip()

    def _sync_topic_to_caret(self) -> None:
        section = self.guide.section_at(self.text.GetSelection()[0])
        if section is None:
            return
        index = self.guide.sections.index(section)
        if self.topics_list.GetSelection() != index:
            self.topics_list.SetSelection(index)

    def find(self, forward: bool = True) -> bool:
        """Select the next (or previous) match of the Find text, wrapping round."""
        query = self.find_box.GetValue().strip()
        needle = self._fold(query)
        if not needle:
            self.find_box.SetFocus()
            return False
        start, end = self.text.GetSelection()
        if forward:
            index = self._folded_text.find(needle, end)
            if index == -1:
                index = self._folded_text.find(needle)
        else:
            index = self._folded_text.rfind(needle, 0, start)
            if index == -1:
                index = self._folded_text.rfind(needle)
        if index == -1:
            message_box(_("Cannot find \"{text}\".").format(text=query), _("User Guide"),
                        wx.OK | wx.ICON_INFORMATION, self)
            return False
        self.text.SetFocus()
        self.text.SetSelection(index, index + len(needle))
        self.text.ShowPosition(index)
        self._sync_topic_to_caret()
        return True

    def _on_char_hook(self, event) -> None:
        key = event.GetKeyCode()
        modifiers = event.GetModifiers()
        if key == ord("F") and modifiers == wx.MOD_CONTROL:
            self.find_box.SetFocus()
            self.find_box.SelectAll()
            return
        if key == wx.WXK_F3 and modifiers in (wx.MOD_NONE, wx.MOD_SHIFT):
            self.find(forward=not event.ShiftDown())
            return
        if (key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and wx.Window.FindFocus() is self.find_box):
            self.find(forward=True)
            return
        event.Skip()

    def _finish(self) -> None:
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


# The guide window on screen, so F1 inside it moves it instead of opening another.
_OPEN_USER_GUIDE: Optional[UserGuideDialog] = None
_LAST_HELP_REQUEST = 0.0
# One F1 press reaches us twice on Windows: as a key (the app-wide char hook)
# and as WM_HELP (wx.EVT_HELP). Whichever comes first answers it.
_HELP_REPEAT_SECONDS = 0.5


def show_user_guide(parent=None, topic: str = "") -> None:
    """Open the User Guide at ``topic``, or move the open one there."""
    global _OPEN_USER_GUIDE
    if _OPEN_USER_GUIDE is not None:
        try:
            _OPEN_USER_GUIDE.show_topic(topic or user_guide.HELP_TOPIC)
            _OPEN_USER_GUIDE.Raise()
            return
        except RuntimeError:
            LOG.debug("show_user_guide: the open guide is gone", exc_info=True)
            _OPEN_USER_GUIDE = None
    try:
        dlg = UserGuideDialog(parent, topic)
    except OSError as exc:
        LOG.warning("The user guide could not be opened: %s", exc)
        message_box(_("The user guide could not be opened: {error}").format(error=exc),
                    _("User Guide"), wx.OK | wx.ICON_ERROR, parent)
        return
    _OPEN_USER_GUIDE = dlg
    try:
        dlg.ShowModal()
    finally:
        _OPEN_USER_GUIDE = None
        dlg.Destroy()


def _help_parent(window):
    """The window the guide opens over: where F1 was pressed, when it can host it.

    Download progress windows and the shutdown countdown destroy themselves,
    which would take a guide opened over them down mid-read, so those hand the
    guide to the main window. A hidden owner would hide the guide with it.
    """
    try:
        top = wx.GetTopLevelParent(window) if window is not None else None
        if top is not None and top.IsShown() and getattr(top, "can_host_help", True):
            return top
        app = wx.GetApp()
        main = app.GetTopWindow() if isinstance(app, wx.App) else None
        if main is not None and main.IsShown():
            return main
    except (RuntimeError, TypeError):
        LOG.debug("_help_parent: no usable window", exc_info=True)
    return None


def request_context_help(window=None, menu_item_id: Optional[int] = None) -> bool:
    """F1: open the guide at the section about ``window`` or a menu item on it.

    Returns False when the request was dropped: the second half of one F1
    press, or a message box on screen (a modal opened inside a box's own loop
    leaves the main window disabled; see message_box).
    """
    global _LAST_HELP_REQUEST
    now = time.monotonic()
    if now - _LAST_HELP_REQUEST < _HELP_REPEAT_SECONDS or modal_box_is_open():
        return False
    _LAST_HELP_REQUEST = now
    topic = None
    if menu_item_id is not None:
        topic = user_guide.topic_for_menu_item(window, menu_item_id)
    if not topic:
        topic = user_guide.topic_for_window(window)
    if menu_item_id is not None:
        # A menu is open, and it has to be closed from outside this WM_HELP
        # handler: a popup menu ignores EndMenu called from inside it, keeps
        # the keyboard, and the guide opens underneath it where Escape and
        # every other key go to the menu instead.
        wx.CallAfter(_end_menu_then_show, _help_parent(window), topic)
    else:
        wx.CallAfter(show_user_guide, _help_parent(window), topic)
    return True


_MENU_WAIT_TRIES = 40  # 50 ms apart: two seconds at most


def _menu_mode_active() -> bool:
    """True while Windows has this thread in a menu (menu bar or popup)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT),
            ]

        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        if not ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return False
        return bool(info.flags & (0x4 | 0x10))  # GUI_INMENUMODE | GUI_POPUPMENUMODE
    except Exception:
        LOG.debug("_menu_mode_active: ignored exception", exc_info=True)
        return False


def _close_open_menu() -> None:
    """End the menu F1 was pressed in, so the guide does not open underneath it."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.user32.EndMenu()
    except Exception:
        LOG.debug("_close_open_menu: ignored exception", exc_info=True)


def _end_menu_then_show(parent, topic: str) -> None:
    _close_open_menu()
    _show_when_menus_closed(parent, topic)


def _show_when_menus_closed(parent, topic: str, tries: int = 0) -> None:
    """Open the guide once the menu loop is over; opened inside it, it never gets the keyboard."""
    if _menu_mode_active() and tries < _MENU_WAIT_TRIES:
        wx.CallLater(50, _show_when_menus_closed, parent, topic, tries + 1)
        return
    show_user_guide(parent, topic)


def _on_app_char_hook(event) -> None:
    # Last stop of every key press nobody handled, in any window of the app.
    if event.GetKeyCode() == wx.WXK_F1 and not event.HasAnyModifiers():
        request_context_help(wx.Window.FindFocus())
        return
    event.Skip()


def _on_app_help(event) -> None:
    # Windows sends WM_HELP for F1: to the focused control (the event's id is
    # its own), or, with a menu open, to the menu's window carrying the
    # highlighted item's id. Linux never sends it; the char hook covers F1 there.
    window = event.GetEventObject()
    item_id = None
    try:
        if window is not None and event.GetId() != window.GetId():
            item_id = event.GetId()
    except RuntimeError:
        LOG.debug("_on_app_help: window is gone", exc_info=True)
        window = None
    request_context_help(window if window is not None else wx.Window.FindFocus(), item_id)


def install_help_hooks(app) -> None:
    """Make F1 open context help anywhere in the app (idempotent)."""
    if app is None or getattr(app, "_user_guide_hooks_installed", False):
        return
    setattr(app, "_user_guide_hooks_installed", True)
    app.Bind(wx.EVT_CHAR_HOOK, _on_app_char_hook)
    app.Bind(wx.EVT_HELP, _on_app_help)


class _AccessibleCategoryTree(wx.TreeCtrl):
    """Native, NVDA-friendly category tree with ListBox-compatible helpers.

    The surrounding application stores category selection as a stable integer
    into ``_group_keys``.  Keeping that small compatibility layer lets us use
    the native tree's hierarchy, expansion state and MSAA/UIA role without
    changing category identity to a display string.
    """

    _COUNT_SUFFIX = re.compile(r" \(\d+\)$")

    def __init__(self, parent):
        super().__init__(
            parent,
            style=wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE,
            name="Categories",
        )
        self.SetName(_("Categories"))
        if hasattr(self, "SetAccessibleName"):
            self.SetAccessibleName(_("Categories"))
        self._labels: List[str] = []
        # An optional display path keeps a category's identity separate from
        # its position. In particular, two playlists may both have a "News"
        # category, but they must remain separate branches in All playlists.
        self._paths: Dict[int, List[object]] = {}
        self._selection = wx.NOT_FOUND
        self._batch_depth = 0
        self._rebuilding = False
        self._item_indexes: Dict[int, int] = {}
        self._index_items: Dict[int, object] = {}
        self.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_tree_selection)
        self._rebuild()

    @classmethod
    def _path_parts(cls, label: str) -> List[str]:
        base = cls._COUNT_SUFFIX.sub("", label or "").strip()
        # IPTV providers commonly encode a hierarchy with either slash or a
        # spaced greater-than sign. Keep all other punctuation literal: it can
        # be part of a broadcaster's actual category name.
        if " > " in base:
            parts = base.split(" > ")
        else:
            parts = base.split("/")
        return [part.strip() for part in parts if part.strip()] or [base]

    def Freeze(self):
        self._batch_depth += 1
        return super().Freeze()

    def Thaw(self):
        result = super().Thaw()
        self._batch_depth = max(0, self._batch_depth - 1)
        if not self._batch_depth:
            self._rebuild()
        return result

    def _changed(self):
        if not self._batch_depth:
            self._rebuild()

    def Clear(self):
        self._labels = []
        self._paths = {}
        self._selection = wx.NOT_FOUND
        self._changed()

    def Append(self, label: str, tree_path: Optional[List[object]] = None):
        self._labels.append(str(label))
        if tree_path:
            self._paths[len(self._labels) - 1] = list(tree_path)
        self._changed()
        return len(self._labels) - 1

    def Insert(self, label: str, index: int, tree_path: Optional[List[object]] = None):
        index = max(0, min(int(index), len(self._labels)))
        self._labels.insert(index, str(label))
        self._paths = {
            existing + 1 if existing >= index else existing: path
            for existing, path in self._paths.items()
        }
        if tree_path:
            self._paths[index] = list(tree_path)
        if self._selection >= index:
            self._selection += 1
        self._changed()
        return index

    def Delete(self, index: int):
        if not 0 <= index < len(self._labels):
            return
        self._labels.pop(index)
        self._paths = {
            existing - 1 if existing > index else existing: path
            for existing, path in self._paths.items()
            if existing != index
        }
        if self._selection == index:
            self._selection = wx.NOT_FOUND
        elif self._selection > index:
            self._selection -= 1
        self._changed()

    def SetString(self, index: int, label: str):
        if 0 <= index < len(self._labels):
            self._labels[index] = str(label)
            self._changed()

    def GetString(self, index: int) -> str:
        return self._labels[index] if 0 <= index < len(self._labels) else ""

    def GetCount(self) -> int:
        return len(self._labels)

    def GetSelection(self) -> int:
        return self._selection

    def SetSelection(self, index: int):
        if not 0 <= index < len(self._labels):
            self._selection = wx.NOT_FOUND
            return
        self._selection = index
        if self._batch_depth:
            return
        item = self._index_items.get(index)
        if item is not None and item.IsOk():
            self.SelectItem(item)
            self.EnsureVisible(item)

    def ToggleSelectedBranch(self):
        item = super().GetSelection()
        if item is not None and item.IsOk() and self.ItemHasChildren(item):
            if self.IsExpanded(item):
                self.Collapse(item)
            else:
                self.Expand(item)

    def ExpandSelectedBranch(self):
        item = super().GetSelection()
        if item is not None and item.IsOk() and self.ItemHasChildren(item):
            self.Expand(item)

    def CollapseSelectedBranch(self):
        item = super().GetSelection()
        if item is not None and item.IsOk() and self.ItemHasChildren(item):
            self.Collapse(item)

    @classmethod
    def _leaf_text(cls, label: str, leaf: object) -> str:
        """Display just the last path segment, retaining its channel count."""
        suffix_match = cls._COUNT_SUFFIX.search(label or "")
        suffix = suffix_match.group(0) if suffix_match else ""
        if isinstance(leaf, tuple):
            leaf = leaf[-1]
        return str(leaf) + suffix

    def _on_tree_selection(self, event):
        if self._rebuilding:
            event.Skip()
            return
        item = event.GetItem()
        # wxMSW returns a fresh ``sip.voidptr`` wrapper from GetID() on each
        # call, so it is not a stable dictionary key. TreeItemId comparison is.
        self._selection = next(
            (index for index, known_item in self._index_items.items() if item == known_item),
            wx.NOT_FOUND,
        )
        event.Skip()

    def _rebuild(self):
        # Rebuild only when a batched category refresh is complete. TreeCtrl
        # exposes the hierarchy to NVDA, unlike an owner-drawn replacement.
        self._rebuilding = True
        try:
            self.DeleteAllItems()
            self._index_items = {}
            root = self.AddRoot(_("Categories"))
            path_items: Dict[Tuple[object, ...], object] = {}
            for index, label in enumerate(self._labels):
                parent = root
                path: List[object] = []
                parts = self._paths.get(index) or self._path_parts(label)
                for part_index, part in enumerate(parts):
                    path.append(part)
                    path_key = tuple(path)
                    item = path_items.get(path_key)
                    if item is None:
                        text = self._leaf_text(label, part) if part_index == len(parts) - 1 else (
                            str(part[-1]) if isinstance(part, tuple) else str(part)
                        )
                        item = self.AppendItem(parent, text)
                        path_items[path_key] = item
                    elif part_index == len(parts) - 1:
                        # The category itself may also be a branch. Its own label
                        # includes its channel count, while its children stay put.
                        self.SetItemText(item, self._leaf_text(label, part))
                    parent = item
                self._index_items[index] = parent
            # A source's categories are visible immediately under its branch.
            # The user can still collapse any branch with Left; this only sets
            # the useful initial state after a playlist/category refresh.
            for item in path_items.values():
                if item.IsOk() and self.ItemHasChildren(item):
                    self.Expand(item)
        finally:
            self._rebuilding = False
        if 0 <= self._selection < len(self._labels):
            item = self._index_items.get(self._selection)
            if item is not None and item.IsOk():
                self.SelectItem(item)


def _load_internal_player_frame_class():
    global _INTERNAL_PLAYER_FRAME_CLASS
    global _INTERNAL_PLAYER_IMPORT_ATTEMPTED
    global _INTERNAL_PLAYER_IMPORT_ERROR

    if not _INTERNAL_PLAYER_IMPORT_ATTEMPTED:
        _INTERNAL_PLAYER_IMPORT_ATTEMPTED = True
        try:
            from internal_player import (  # type: ignore
                InternalPlayerFrame as frame_class,
                _VLC_IMPORT_ERROR as vlc_import_error,
            )
        except Exception as exc:  # pragma: no cover - import guard
            _INTERNAL_PLAYER_IMPORT_ERROR = exc
            _INTERNAL_PLAYER_FRAME_CLASS = None
        else:
            _INTERNAL_PLAYER_FRAME_CLASS = frame_class
            _INTERNAL_PLAYER_IMPORT_ERROR = vlc_import_error

    if _INTERNAL_PLAYER_FRAME_CLASS is None:
        detail = _INTERNAL_PLAYER_IMPORT_ERROR or _("Built-in player is unavailable.")
        raise InternalPlayerUnavailableError(str(detail))
    return _INTERNAL_PLAYER_FRAME_CLASS


_M3U_ATTR_RE = re.compile(r'([A-Za-z0-9_\-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^",\s]+))')


def _extinf_name_comma(line: str) -> int:
    """Index of the comma separating an #EXTINF's attributes from its name.

    The separator is the first comma *outside* a quoted attribute value. Real
    playlists ship values that contain commas — iptv-org, for one, emits
    http-user-agent="Mozilla/5.0 (... (KHTML, like Gecko) Chrome/145 ..." — and
    splitting on the first raw comma made the rest of the attribute list the
    channel name while truncating the attributes themselves, losing the
    channel's group and headers with it.

    Returns -1 when the line holds no comma, and falls back to the first raw
    comma when quoting is unbalanced, which is what a malformed line used to get.
    """
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in ('"', "'"):
            quote = char
        elif char == ",":
            return index
    return line.find(",")
_AUTO_UPDATE_DELAY_AFTER_PLAYLIST_MS = 5000
_AUTO_UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000  # hourly
_AUTO_UPDATE_HTTP_TIMEOUT_SECONDS = 5.0
_MANUAL_UPDATE_HTTP_TIMEOUT_SECONDS = 15.0
# How long the progress dialog stays up saying the app is about to close
# for the installer, so a screen reader has time to speak it. Must stay
# well inside the 30 seconds update_helper.ps1 waits before killing us.
_UPDATE_HANDOFF_LINGER_MS = 2500
# How long to hold the app's own progress dialog open waiting for the update
# helper to report that its status window is showing, and how often to look.
_UPDATE_HANDOFF_MAX_WAIT_SECONDS = 15.0
_UPDATE_HANDOFF_POLL_MS = 250

# Catch-up downloads: providers refuse bursts of connections with 403s and
# flaky networks drop streams, so a failed download is retried automatically
# (with the delay doubled per attempt) instead of making the user start over.
# User cancellations are never retried; the budget is small on purpose.
_CATCHUP_RETRY_MAX_ATTEMPTS = 3
_CATCHUP_RETRY_BASE_DELAY_SECONDS = 2.0
_CATCHUP_RETRYABLE_RE = re.compile(
    r"403\b|429\b|50[0-9]\b|connection (?:reset|refused|closed)|timed? ?out|"
    r"temporarily unavailable|no route to host|server returned", re.IGNORECASE)


# How far ahead View EPG looks. It starts at the programme on air now: finished
# programmes are what Catch-up is for, and cannot be recorded any more.
_CHANNEL_EPG_HORIZON = datetime.timedelta(days=7)


def _ffmpeg_error_tag(a, b, c, d) -> int:
    """FFmpeg's FFERRTAG: the negative code ffmpeg exits with for that error."""
    def byte(ch):
        return ch if isinstance(ch, int) else ord(ch)
    return -(byte(a) | (byte(b) << 8) | (byte(c) << 16) | (byte(d) << 24))


# ffmpeg exits with the AVERROR of whatever stopped it, and Windows reports that
# as an unsigned 32-bit number: a refused download read "code 3436169992", which
# is HTTP 403 Forbidden. These put the common ones into words.
_FFMPEG_EXIT_REASONS = (
    ((_ffmpeg_error_tag(0xF8, "4", "0", "3"),),
     N_("The provider refused access (HTTP 403 Forbidden). Many providers allow "
        "only one stream per account at a time: stop other playback or downloads "
        "from this account and try again.")),
    ((_ffmpeg_error_tag(0xF8, "4", "0", "1"),),
     N_("The provider asked for a login (HTTP 401 Unauthorized). Check the "
        "playlist's user name and password.")),
    ((_ffmpeg_error_tag(0xF8, "4", "0", "4"),),
     N_("The provider does not have this programme (HTTP 404 Not Found). It may "
        "be older than the provider's archive.")),
    ((_ffmpeg_error_tag(0xF8, "4", "0", "0"), _ffmpeg_error_tag(0xF8, "4", "2", "9"),
      _ffmpeg_error_tag(0xF8, "4", "X", "X")),
     N_("The provider rejected the request (HTTP 4xx error).")),
    ((_ffmpeg_error_tag(0xF8, "5", "X", "X"),),
     N_("The provider's server had an error (HTTP 5xx). Try again later.")),
    ((_ffmpeg_error_tag("I", "N", "D", "A"),),
     N_("The stream sent data that could not be read.")),
    # ETIMEDOUT / ECONNREFUSED as the Windows CRT, Linux and Winsock number them.
    ((-138, -110, -10060),
     N_("The connection to the provider timed out.")),
    ((-107, -111, -10061),
     N_("The provider's server refused the connection.")),
)


def _ffmpeg_exit_reason(rc) -> str:
    """Plain words for an ffmpeg exit code, or "" when it is not a known one."""
    try:
        code = int(rc)
    except (TypeError, ValueError):
        return ""
    if code > 0x7FFFFFFF:
        code -= 1 << 32
    for codes, reason in _FFMPEG_EXIT_REASONS:
        if code in codes:
            return _(reason)
    return ""


def _catchup_failure_is_retryable(rc: int, stderr_lines, *, stopped_by_user: bool = False) -> bool:
    """True when a finished download failed for a reason retrying can fix."""
    if stopped_by_user or not rc:
        return False
    text = "\n".join(stderr_lines or [])
    return bool(_CATCHUP_RETRYABLE_RE.search(text))


def _schedule_retry(fn, delay_seconds: float):
    """Run ``fn`` once after ``delay_seconds`` on a daemon thread."""
    timer = threading.Timer(delay_seconds, fn)
    timer.daemon = True
    timer.start()
    return timer

# EPG-style placeholders some providers embed in catchup-source templates.
# ${start}/${timestamp} (teleelevidenie), {utc}/{lutc}, and the long variants
# all appear in the wild; Kodi's IPTV Simple documents the {S} family.
_CATCHUP_TEMPLATE_TOKENS = (
    ("${start}", "start"), ("${timestamp}", "lutc"),
    ("${duration}", "duration"), ("${end}", "end"),
    ("{utc}", "start"), ("{lutc}", "lutc"),
    ("{utcstart}", "start"), ("{utcend}", "end"),
    ("{duration}", "duration"),
    ("{S}", "start"), ("{E}", "end"), ("{L}", "lutc"), ("{D}", "duration"),
    ("{Y}", "start_year"), ("{m}", "start_month"), ("{d}", "start_day"),
    ("{H}", "start_hour"), ("{M}", "start_minute"),
    ("{y}", "end_year"), ("{e}", "end_day"), ("{h}", "end_hour"), ("{i}", "end_minute"),
)


def _catchup_token_value(kind: str, start_dt, end_dt, now) -> str:
    """Render one catchup-source placeholder as a string."""
    if kind == "start":
        return str(int(start_dt.timestamp()))
    if kind == "end":
        return str(int(end_dt.timestamp()))
    if kind == "lutc":
        return str(int(now.timestamp()))
    if kind == "duration":
        return str(max(1, int((end_dt - start_dt).total_seconds())))
    if kind == "start_year":
        return start_dt.strftime("%Y")
    if kind == "start_month":
        return start_dt.strftime("%m")
    if kind == "start_day":
        return start_dt.strftime("%d")
    if kind == "start_hour":
        return start_dt.strftime("%H")
    if kind == "start_minute":
        return start_dt.strftime("%M")
    if kind == "end_year":
        return end_dt.strftime("%Y")
    if kind == "end_day":
        return end_dt.strftime("%d")
    if kind == "end_hour":
        return end_dt.strftime("%H")
    if kind == "end_minute":
        return end_dt.strftime("%M")
    return ""


def _expand_catchup_template(source: str, start_dt, end_dt, offset_hours: float = 0.0):
    """Fill an EPG-template ``catchup-source`` in, or return None if it is not one.

    Providers such as teleelevidenie ship ``catchup="append"`` plus a template
    like ``?utc=${start}&lutc=${timestamp}``. That must be appended to the
    channel's live URL with real epoch values, not treated as a static base
    path -- the old code turned it into ``<host>/<start>/<duration>/``, which
    the server answers with 403.
    """
    text = (source or "").strip()
    if not text:
        return None
    expanded = text
    matched = False
    for token, kind in _CATCHUP_TEMPLATE_TOKENS:
        if token in expanded:
            matched = True
            break
    if not matched:
        return None

    if offset_hours:
        try:
            shift = datetime.timedelta(hours=float(offset_hours))
        except (TypeError, ValueError):
            shift = datetime.timedelta(0)
        start_dt = start_dt - shift
        end_dt = end_dt - shift
    now = datetime.datetime.now(datetime.timezone.utc)
    for token, kind in _CATCHUP_TEMPLATE_TOKENS:
        while token in expanded:
            expanded = expanded.replace(
                token,
                _catchup_token_value(kind, start_dt, end_dt, now),
                1,
            )
    return expanded


def _positive_timeshift_days(channel: Dict[str, str]) -> Optional[int]:
    """Return a positive M3U ``timeshift`` window, expressed in days.

    Some providers use the older ``timeshift=\"N\"`` attribute instead of the
    newer catchup/catchup-days pair. The attribute says how much archive is
    available, but not how its URL is built, so URL inference stays
    provider-specific below.
    """
    value = channel.get("timeshift")
    try:
        days = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


def _implicit_catchup_source(channel: Dict[str, str]) -> str:
    """Infer a catch-up template when a known provider only sends timeshift.

    Teleelevidenie's current dynamic playlists mark archive-capable channels as
    ``timeshift=\"3\"`` without the ``catchup-source`` template present in its
    older playlists. Its HLS and TS endpoints both accept the same utc/lutc
    query parameters, so the live container format does not affect this rule.
    """
    if _positive_timeshift_days(channel) is None:
        return ""
    raw_url = str(channel.get("url") or "").split("|", 1)[0].strip()
    try:
        host = (urllib.parse.urlparse(raw_url).hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return ""
    if host == "teleelevidenie.com" or host.endswith(".teleelevidenie.com"):
        return "?utc=${start}&lutc=${timestamp}"
    return ""


def set_linux_env():
    if platform.system() != "Linux":
        return

    os.environ["UBUNTU_MENUPROXY"] = "0"
    distro = "unknown"
    try:
        with open("/etc/os-release") as f:
            os_release = f.read().lower()
        if "ubuntu" in os_release:
            distro = "ubuntu"
        elif "debian" in os_release:
            distro = "debian"
        elif "arch" in os_release and "manjaro" not in os_release:
            distro = "arch"
        elif "manjaro" in os_release:
            distro = "manjaro"
        elif "fedora" in os_release:
            distro = "fedora"
        elif "centos" in os_release:
            distro = "centos"
        elif "rhel" in os_release or "red hat" in os_release:
            distro = "rhel"
        elif "opensuse" in os_release or "suse" in os_release:
            distro = "opensuse"
        elif "mint" in os_release:
            distro = "mint"
        elif "pop" in os_release and "pop_os" in os_release:
            distro = "popos"
    except Exception:
        LOG.debug("set_linux_env: ignored exception", exc_info=True)

    os.environ["MYAPP_DISTRO"] = distro

    if distro == "ubuntu":
        os.environ["UBUNTU_MENUPROXY"] = "0"
        os.environ["GTK_MODULES"] = os.environ.get("GTK_MODULES", "")
    elif distro == "debian":
        os.environ["GTK_OVERLAY_SCROLLING"] = "0"
    elif distro == "arch":
        os.environ["NO_AT_BRIDGE"] = "0"
    elif distro == "manjaro":
        os.environ["NO_AT_BRIDGE"] = "0"
    elif distro == "fedora":
        os.environ["GTK_USE_PORTAL"] = "1"
    elif distro == "centos":
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    elif distro == "rhel":
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    elif distro == "opensuse":
        os.environ["XDG_CURRENT_DESKTOP"] = os.environ.get("XDG_CURRENT_DESKTOP", "KDE")
    elif distro == "mint":
        os.environ["XDG_CURRENT_DESKTOP"] = os.environ.get("XDG_CURRENT_DESKTOP", "X-Cinnamon")
    elif distro == "popos":
        os.environ["GDK_BACKEND"] = os.environ.get("GDK_BACKEND", "x11")

def _lower_current_thread_priority():
    """Best-effort: drop the OS scheduling priority of the *calling* thread only.

    Used by the background EPG import worker so a long (tens-of-minutes) import
    competes less aggressively with the UI thread and other apps, without
    touching the whole process's priority class (which would also throttle the UI
    thread). Windows-only; a harmless no-op everywhere else or if the call fails.

    Uses THREAD_MODE_BACKGROUND_BEGIN rather than a plain CPU-priority drop: a
    multi-gigabyte EPG import is dominated by disk writes and page-cache churn,
    and CPU priority alone leaves the import free to saturate the disk and evict
    the UI's working set. Background mode lowers CPU, disk-I/O, *and* memory
    priority together, which is what actually keeps the interface (and NVDA)
    responsive while an import is running.
    """
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        from ctypes import wintypes
        THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
        THREAD_PRIORITY_LOWEST = -2
        kernel32 = ctypes.windll.kernel32
        # GetCurrentThread() returns a pseudo-HANDLE (pointer-sized). Without explicit
        # argtypes/restype, ctypes' default 32-bit c_int marshaling can mangle it on
        # 64-bit Python, silently turning this into a no-op.
        kernel32.GetCurrentThread.restype = wintypes.HANDLE
        kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        kernel32.SetThreadPriority.restype = wintypes.BOOL
        # THREAD_MODE_BACKGROUND_BEGIN is only valid on the current thread's
        # pseudo-handle, which is exactly how it is used here.
        if not kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_MODE_BACKGROUND_BEGIN):
            kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_LOWEST)
    except Exception:
        LOG.debug("_lower_current_thread_priority: ignored exception", exc_info=True)

class TrayIcon(wx.adv.TaskBarIcon):
    TBMENU_RESTORE = wx.NewIdRef()
    TBMENU_EXIT = wx.NewIdRef()
    TBMENU_PLAYER_SHOW = wx.NewIdRef()
    TBMENU_PLAYER_TOGGLE = wx.NewIdRef()
    TBMENU_PLAYER_STOP = wx.NewIdRef()
    TBMENU_CAST = wx.NewIdRef()
    TBMENU_RECORD_STOP = wx.NewIdRef()

    def __init__(self, parent, on_restore, on_exit, *, on_player_show=None, on_player_toggle=None, on_player_stop=None, on_cast=None, on_record_stop=None):
        super().__init__()
        self.parent = parent
        self.on_restore = on_restore
        self.on_exit = on_exit
        self.on_player_show = on_player_show
        self.on_player_toggle = on_player_toggle
        self.on_player_stop = on_player_stop
        self.on_cast = on_cast
        self.on_record_stop = on_record_stop
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_taskbar_activate)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, self.on_taskbar_activate)
        self.Bind(wx.EVT_MENU, self.on_menu_select)
        self.set_icon()

    def set_icon(self):
        icon = wx.Icon(wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_TOOLBAR, (16, 16)))
        self.SetIcon(icon, "Accessible IPTV Client")

    def CreatePopupMenu(self):
        menu = wx.Menu()
        menu.Append(self.TBMENU_RESTORE, _("Restore"))
        player_menu = wx.Menu()
        player_items = (
            player_menu.Append(self.TBMENU_PLAYER_SHOW, _("Show Player")),
            player_menu.Append(self.TBMENU_PLAYER_TOGGLE, _("Play/Pause")),
            player_menu.Append(self.TBMENU_PLAYER_STOP, _("Stop")),
        )
        player_menu.AppendSeparator()
        player_items += (player_menu.Append(self.TBMENU_CAST, _("Cast / Connect...")),)
        # Same rule as the menu bar's Player menu: with nothing loaded in the
        # built-in player there is nothing for these to act on.
        has_media = getattr(self.parent, "_internal_player_has_media", None)
        loaded = bool(has_media()) if callable(has_media) else True
        for item in player_items:
            item.Enable(loaded)
        menu.AppendSubMenu(player_menu, _("Player Controls"))
        if self.on_record_stop is not None and self.parent and self.parent.recorder.has_active():
            menu.Append(self.TBMENU_RECORD_STOP, _("Stop Recording(s)"))
        menu.AppendSeparator()
        menu.Append(self.TBMENU_EXIT, _("Exit"))
        return menu

    def on_taskbar_activate(self, event):
        # Handle left-click, double-click, or Enter key on tray icon.
        # All these actions restore the app for accessibility (NVDA/JAWS).
        # Use CallLater to let the tray event fully complete before restoring.
        wx.CallLater(50, self.on_restore)

    def on_menu_select(self, event):
        eid = event.GetId()
        if eid == self.TBMENU_RESTORE:
            self.on_restore()
        elif eid == self.TBMENU_PLAYER_SHOW and self.on_player_show:
            self.on_player_show()
        elif eid == self.TBMENU_PLAYER_TOGGLE and self.on_player_toggle:
            self.on_player_toggle()
        elif eid == self.TBMENU_PLAYER_STOP and self.on_player_stop:
            self.on_player_stop()
        elif eid == self.TBMENU_CAST and self.on_cast:
            self.on_cast()
        elif eid == self.TBMENU_RECORD_STOP and self.on_record_stop:
            self.on_record_stop()
        elif eid == self.TBMENU_EXIT:
            self.on_exit()

class IPTVClient(wx.Frame):
    # Labels double as the stored ``media_player`` config value, so they stay
    # English here; N_() only marks the one non-brand entry for extraction and
    # the menu translates it at build time via _(label).
    PLAYER_KEYS = [
        (N_("Built-in Player"), "player_Internal"),
        ("VLC", "player_VLC"),
        ("MPC", "player_MPC"),
        ("MPC-BE", "player_MPCBE"),
        ("Kodi", "player_Kodi"),
        ("Winamp", "player_Winamp"),
        ("Foobar2000", "player_Foobar2000"),
        ("MPV", "player_MPV"),
        ("SMPlayer", "player_SMPlayer"),
        ("Totem", "player_Totem"),
        ("QuickTime", "player_QuickTime"),
        ("iTunes/Apple Music", "player_iTunes"),
        ("PotPlayer", "player_PotPlayer"),
        ("KMPlayer", "player_KMPlayer"),
        ("AIMP", "player_AIMP"),
        ("QMPlay2", "player_QMPlay2"),
        ("GOM Player", "player_GOMPlayer"),
        ("Audacious", "player_Audacious"),
        ("Fauxdacious", "player_Fauxdacious"),
        ("Clementine", "player_Clementine"),
        ("Strawberry", "player_Strawberry"),
        ("Amarok", "player_Amarok"),
        ("Rhythmbox", "player_Rhythmbox"),
        ("Pragha", "player_Pragha"),
        ("Lollypop", "player_Lollypop"),
        ("Exaile", "player_Exaile"),
        ("Quod Libet", "player_QuodLibet"),
        ("Gmusicbrowser", "player_Gmusicbrowser"),
        ("Xmms", "player_Xmms"),
        ("Vocal", "player_Vocal"),
        ("Haruna", "player_Haruna"),
        ("Celluloid", "player_Celluloid"),
    ]
    PLAYER_MENU_ATTRS = dict(PLAYER_KEYS)

    _SEARCH_LARGE_RESULT_THRESHOLD = 1500
    _SEARCH_PREVIEW_COUNT = 200
    _SEARCH_BATCH_SIZE = 800
    _SEARCH_EPG_MIN_CHARS = 3
    _SEARCH_EPG_BROAD_CHANNEL_LIMIT = 75
    _SEARCH_EPG_RESULT_LIMIT = 100

    def __init__(self):
        super().__init__(None, title="Accessible IPTV Client", size=(800, 600))
        self.config = load_config()
        # Activate the user's language preference before any UI strings are built.
        i18n.init_from_config(self.config)
        self.playlist_sources = self.config.get("playlists", [])
        self.epg_sources = self.config.get("epgs", [])
        self.channels_by_group: Dict[str, List[Dict[str, str]]] = {}
        self.all_channels: List[Dict[str, str]] = []
        self.displayed: List[Dict[str, str]] = []
        self.current_group = "All Channels"
        # Favorite channels. The keys are provider-stable identities (see
        # favorites.channel_key); the set is what the list rows are painted from,
        # so it has to stay in step with the list.
        self.favorite_keys: List[str] = favorites.normalize(self.config.get("favorites"))
        self._favorite_key_set = set(self.favorite_keys)
        self._favorites_cache: Optional[List[Dict[str, str]]] = None
        # Parallel list of real group keys, indexed like group_list, so group
        # names containing " (" round-trip correctly instead of being truncated.
        self._group_keys: List[str] = []
        # Playlist scope: which playlist the categories and channels come from.
        # Stored as the source's stable "id" (from the Playlist Manager); the
        # sentinel ALL_PLAYLISTS_SCOPE shows everything. Restored from config.
        self.playlist_scope = self.config.get("playlist_scope", ALL_PLAYLISTS_SCOPE)
        if not isinstance(self.playlist_scope, str):
            self.playlist_scope = ALL_PLAYLISTS_SCOPE
        # View mode: "live" (channels + catch-up, the default) or "vod"
        # (browsable movies & series). VOD is built lazily on first switch.
        self.view_mode = "live"
        self.vod_group_order: List[str] = []
        self.vod_groups: Dict[str, List[Dict]] = {}
        self.vod_current_group: Optional[str] = None
        self.vod_loaded = False
        self.vod_loading = False
        self._vod_load_token = 0
        # When drilled into a series, the category to return to on "Back".
        self._vod_series_return_group: Optional[str] = None
        self.default_player = self.config.get("media_player", "Built-in Player")
        self.custom_player_path = self.config.get("custom_player_path", "")
        self.show_player_on_enter = self._bool_pref(self.config.get("show_player_on_enter", True), default=True)
        # Whether the read-only stream-URL field under the channel list exists at
        # all. It is useful (the Teleelevidenie script wants the URL) but it is
        # also the only thing Tab reaches from the channel list, so it is a
        # setting rather than a fixture.
        self.show_channel_url = self._bool_pref(self.config.get("show_channel_url", True), default=True)
        self.auto_check_updates = self._bool_pref(self.config.get("auto_check_updates", True), default=True)
        self.epg_importing = False
        # True while the import that is running was asked for by hand (File >
        # Import EPG to DB). A hand-started import owes the user a "finished"
        # box; the automatic background refresh must stay silent.
        self._epg_import_notify = False
        self.refresh_timer = None
        self.minimize_to_tray = bool(self.config.get("minimize_to_tray", False))
        self.tray_icon = None
        self._tray_allow_restore = False
        self._tray_ready_timer: Optional[wx.CallLater] = None
        self.provider_clients: Dict[str, object] = {}
        self.provider_epg_sources: List[str] = []
        self._internal_player_frame: Optional[object] = None
        self._update_check_inflight = False
        self._update_install_pending = False
        # True from the moment the "Update available" prompt opens until the
        # download finishes, fails or is cancelled. A second update prompt on
        # top of the app-modal progress dialog left the main window disabled
        # with no dialog owning it - a dead app that only Task Manager could
        # close - so only one update flow is ever allowed to be on screen.
        self._update_prompt_open = False
        self._update_in_progress = False
        self._auto_update_check_scheduled = False
        self._update_check_timer: Optional[wx.Timer] = None
        self._playlist_load_token = 0
        self._pending_epg_autostart = False
        self._pending_epg_autostart_token = 0
        self._epg_autostart_timer: Optional[wx.CallLater] = None

        # Casting loads several network/media stacks and may start the local
        # stream proxy. Keep it lazy so the first window is not delayed.
        self.caster = None

        self.player_launcher = ExternalPlayerLauncher()

        # Recording Manager
        self.recorder = recorder.RecordingManager()
        self._suppress_recording_notifications = False
        self._dvr_dialog = None
        self.dvr_scheduler = None

        # Shut down the computer once recording is finished (Recordings menu).
        # ``_recorded_since_shutdown_armed`` is what stops the option powering the
        # machine off the moment it is switched on: there has to be something to
        # wait for first.
        self._shutdown_after_recordings = bool(self.config.get("shutdown_after_recordings", False))
        self._recorded_since_shutdown_armed = False
        self._shutdown_dialog = None
        # Set when we are exiting on purpose (an update, or our own shutdown), so
        # on_close does not bounce the window into the tray instead of closing.
        self._exit_forced = False
        # Flush notifications that had to wait behind a modal box as soon as the
        # last box closes, whoever opened it.
        self._modal_box_depth = 0
        set_modal_box_closed_hook(self._drain_deferred_notifications)
        # What the built-in player is currently showing, so its Record button
        # knows which channel to record.
        self._internal_player_channel: Optional[Dict[str, str]] = None
        self._internal_player_stream_kind = "live"
        # ...and which channel the audio track picked in the player belongs to.
        self._internal_player_audio_key = ""
        # Live catch-up download progress dialogs, by recorder id.
        self._catchup_downloads: Dict[int, "CatchupDownloadDialog"] = {}
        # Auto-retry bookkeeping for failed catch-up downloads, keyed by the
        # *original* recorder id so the attempt budget survives retries (each
        # retry gets a fresh recorder id).
        self._catchup_retry_state: Dict[int, int] = {}
        self._catchup_retry_timers: Dict[int, threading.Timer] = {}

        # batch-population state to avoid UI hangs
        self._populate_token = 0
        self._search_token = 0

        # Bulk on-air programme labels for the channel rows, keyed by
        # canonicalized EPG channel name; values are " — Title (HH:MM–HH:MM)"
        # suffixes appended to the row text so arrowing through the list
        # announces what is on, no Tab to a separate field required.
        self._now_playing_labels: Dict[str, str] = {}
        self._now_playing_lock = threading.Lock()
        self._now_playing_timer: Optional[wx.Timer] = None
        self._now_playing_refreshed_at = 0.0
        # On-air episode description per canonical channel name, refreshed
        # with the row labels; the episode description field reads from it.
        self._now_playing_descriptions: Dict[str, str] = {}
        
        # Caching map: canonical_name -> db_channel_id
        self._epg_match_cache: Dict[str, Optional[str]] = {}
        self._epg_match_lock = threading.Lock()
        # Dedicated executor for EPG lookups to avoid thread-spawning overhead
        self._epg_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="EPGFetch")
        self._db_tune_lock = threading.Lock()
        self._db_tune_started = False
        self._build_ui()
        install_help_hooks(wx.GetApp())
        self._start_now_playing_timer()
        threading.Thread(target=self._refresh_now_playing_labels, daemon=True).start()
        self.Centre()

        self.group_list.Append(_("Loading playlists..."))
        self.Show()

        # Defer non-UI startup work until the frame has had a chance to paint.
        wx.CallLater(50, self._run_deferred_startup_tasks)

        self.Bind(wx.EVT_ICONIZE, self.on_minimize)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def _run_deferred_startup_tasks(self):
        self._report_finished_update()
        # A successful update leaves its ~95 MB staging dir in %TEMP% (the
        # helper runs from inside it); clear old ones off the UI thread.
        threading.Thread(
            target=updater.sweep_stale_update_dirs, daemon=True, name="UpdateTempSweep"
        ).start()
        self._ensure_db_tuned_background()
        self._start_dvr_scheduler()
        self.start_playlist_load()

    def _ensure_db_tuned_background(self):
        with self._db_tune_lock:
            if self._db_tune_started:
                return
            self._db_tune_started = True

        def tune_db():
            try:
                self._ensure_db_tuned()
            except Exception:
                LOG.exception("Failed to tune EPG database during startup.")

        threading.Thread(target=tune_db, daemon=True, name="EPGDBTune").start()

    def _ensure_dvr_scheduler(self, *, start: bool = False):
        scheduler = getattr(self, "dvr_scheduler", None)
        if scheduler is None:
            scheduler = dvr.DVRScheduler(
                get_dvr_schedule_path(),
                on_start=self._start_scheduled_recording,
                on_stop=self._stop_scheduled_recording,
                on_update=self._on_dvr_schedule_updated,
                poll_seconds=10,
            )
            self.dvr_scheduler = scheduler
        if start:
            scheduler.start()
        return scheduler

    def _start_dvr_scheduler(self):
        try:
            self._ensure_dvr_scheduler(start=True)
        except Exception:
            LOG.exception("Failed to start DVR scheduler.")

    def _stop_dvr_scheduler(self, *, wait: bool = False):
        scheduler = getattr(self, "dvr_scheduler", None)
        if scheduler is not None:
            scheduler.stop(wait=wait)

    def _ensure_caster(self):
        caster = getattr(self, "caster", None)
        if caster is None:
            from casting import CastingManager

            caster = CastingManager()
            caster.start()
            self.caster = caster
        return caster

    def _schedule_auto_update_check(self):
        """Check for updates once at startup, then once every hour."""
        if getattr(self, "_auto_update_check_scheduled", False):
            return
        if not self.auto_check_updates:
            return
        self._auto_update_check_scheduled = True
        # Startup check, a few seconds in so playlist loading is not disturbed.
        wx.CallLater(
            _AUTO_UPDATE_DELAY_AFTER_PLAYLIST_MS,
            lambda: self._start_update_check(interactive=False),
        )
        # And then steady hourly checks for the rest of the session.
        self._start_update_check_timer()

    def _start_update_check_timer(self):
        try:
            if getattr(self, "_update_check_timer", None):
                return
            self._update_check_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_update_check_timer, self._update_check_timer)
            self._update_check_timer.Start(_AUTO_UPDATE_CHECK_INTERVAL_MS, wx.TIMER_CONTINUOUS)
        except Exception:
            self._update_check_timer = None

    def _stop_update_check_timer(self):
        try:
            if getattr(self, "_update_check_timer", None):
                self._update_check_timer.Stop()
                try:
                    self.Unbind(wx.EVT_TIMER, handler=self._on_update_check_timer,
                                source=self._update_check_timer)
                except Exception:
                    LOG.debug("IPTVClient._stop_update_check_timer: ignored exception", exc_info=True)
                self._update_check_timer = None
        except Exception:
            self._update_check_timer = None

    def _on_update_check_timer(self, _event):
        if self.auto_check_updates:
            self._start_update_check(interactive=False)

    def _record_auto_update_check_attempt(self):
        try:
            self.config["update_last_auto_check_epoch"] = int(time.time())
            save_config(self.config)
        except Exception:
            LOG.debug("IPTVClient._record_auto_update_check_attempt: ignored exception", exc_info=True)

    # ------------------------------------------------------------------ #
    # Favorites                                                          #
    # ------------------------------------------------------------------ #
    def _favorites_group_label(self, count: int) -> str:
        return _("Favorites") + " ({count})".format(count=count)

    def _favorite_channels(self) -> List[Dict[str, str]]:
        """The favorited channels in playlist order, rebuilt only when it changed.

        Scanning 300k channels is cheap but not free, and this is asked for on
        every category refresh, so the result is cached until the favorites or the
        playlist change.
        """
        if self._favorites_cache is None:
            self._favorites_cache = favorites.filter_channels(
                self.scoped_all_channels(), self.favorite_keys)
        return self._favorites_cache

    def _invalidate_favorites_cache(self):
        self._favorites_cache = None

    def _is_favorite(self, channel: Optional[Dict[str, str]]) -> bool:
        key = favorites.channel_key(channel)
        return bool(key) and key in self._favorite_key_set

    def _source_for_group(self, group) -> List[Dict[str, str]]:
        """The channels a category holds. "All Channels" and "Favorites" are sentinels."""
        if group == favorites.FAVORITES_GROUP:
            return self._favorite_channels()
        if group == "All Channels":
            return self.scoped_all_channels()
        if (isinstance(group, tuple) and len(group) == 3
                and group[0] == "playlist-group"):
            _marker, scope, category = group
            return [
                channel for channel in self.scoped_channels_by_group().get(category, [])
                if str(channel.get("playlist-id") or "") == scope
            ]
        if (isinstance(group, tuple) and len(group) == 2
                and group[0] == "playlist-all"):
            _marker, scope = group
            return [
                channel for channel in self.scoped_all_channels()
                if str(channel.get("playlist-id") or "") == scope
            ]
        return self.scoped_channels_by_group().get(group, [])

    # ------------------------------------------------------------------ #
    # Playlist scope (categories and channels from a single playlist)
    # ------------------------------------------------------------------ #
    def _scoped_sources(self) -> List[dict]:
        """The playlist sources visible in the scope picker, in playlist-manager order."""
        return _tagged_sources(self.playlist_sources)

    def _scope_choice_label(self, src: dict) -> str:
        """The combo label for a playlist: what the Playlist Manager shows."""
        if isinstance(src, str):
            name = normalize_source_names(self.config.get("playlist_names")).get(source_name_key(src))
            if name:
                return name
            if src.startswith(("http://", "https://")):
                parsed = urllib.parse.urlsplit(src)
                return parsed.hostname or _("Playlist")
            return os.path.basename(src)
        stype = (src.get("type") or "").lower()
        name = src.get("name") or src.get("username") or src.get("base_url") or _("Provider")
        if stype == "xtream":
            return _("Xtream Codes – {name}").format(name=name)
        if stype == "stalker":
            return _("Stalker Portal – {name}").format(name=name)
        return _("Provider – {name}").format(name=name)

    def _fill_playlist_scope_combo(self):
        """(Re)build the scope combo entries and select the stored scope.

        Safe to call before ``__init__`` state exists: ``_build_ui`` runs it
        while the frame is still being assembled.
        """
        combo = getattr(self, "playlist_scope_combo", None)
        if combo is None:
            return
        combo.Clear()
        combo.Append(_("All playlists"))
        for src in self._scoped_sources():
            combo.Append(self._scope_choice_label(src))
        combo.SetSelection(self._combo_index_for_scope(self.playlist_scope))

    def _combo_index_for_scope(self, scope: str) -> int:
        """Combo index for a stored scope; an unknown id falls back to All."""
        if scope != ALL_PLAYLISTS_SCOPE:
            for i, src in enumerate(_tagged_sources(self.playlist_sources), start=1):
                if _source_scope_id(src) == scope:
                    return i
        return 0

    def on_playlist_scope_changed(self, _event):
        """Switch the category and channel lists to the selected playlist."""
        sel = self.playlist_scope_combo.GetSelection()
        scope = ALL_PLAYLISTS_SCOPE
        if sel > 0:
            sources = _tagged_sources(self.playlist_sources)
            if 0 < sel <= len(sources):
                scope = _source_scope_id(sources[sel - 1])
        if scope == self.playlist_scope:
            return
        self.playlist_scope = scope
        self.config["playlist_scope"] = scope
        save_config(self.config)
        self._invalidate_favorites_cache()
        # Reset the category to the top so the view cannot point at a category
        # that no longer exists in this playlist.
        self.current_group = "All Channels"
        try:
            self.filter_box.ChangeValue("")
        except Exception:
            LOG.debug("IPTVClient.on_playlist_scope_changed: ignored exception", exc_info=True)
        self._refresh_group_ui()
        if hasattr(self.playlist_scope_combo, "SetFocus"):
            self.playlist_scope_combo.SetFocus()

    def scoped_all_channels(self) -> List[Dict[str, str]]:
        """``self.all_channels`` filtered to the playlist scope."""
        return _scoped_channels(self.all_channels, self.playlist_scope)

    def scoped_channels_by_group(self) -> Dict[str, List[Dict[str, str]]]:
        """``self.channels_by_group`` filtered to the playlist scope."""
        scope = self.playlist_scope
        if scope == ALL_PLAYLISTS_SCOPE:
            return self.channels_by_group
        return {
            grp: [ch for ch in lst if _scope_includes_channel(ch, scope)]
            for grp, lst in self.channels_by_group.items()
            if any(_scope_includes_channel(ch, scope) for ch in lst)
        }

    def _sync_favorites_from_config(self):
        """Re-read favorites after the config has been reloaded from disk."""
        keys = favorites.normalize(self.config.get("favorites"))
        if keys == self.favorite_keys:
            return
        self.favorite_keys = keys
        self._favorite_key_set = set(keys)
        self._invalidate_favorites_cache()

    def _decorate_channel_label(self, name: str, channel: Dict[str, str]) -> str:
        """Row text for a channel, marking favorites and the on-air programme.

        A screen reader reads the row text, so the favorite marker is a word
        rather than a star glyph: NVDA says nothing at all for most symbols at
        the default punctuation level. Inside the Favorites category every row
        would carry it, which is pure noise, so it is left off there. The
        current episode is appended at the end — like Televizo or IPTV Extreme
        Pro do — so arrowing through the list announces what is playing
        without a trip to a separate EPG field.
        """
        label = name
        favorite_set = getattr(self, "_favorite_key_set", None)
        if favorite_set and self.current_group != favorites.FAVORITES_GROUP:
            try:
                if favorites.channel_key(channel) in favorite_set:
                    label = _("{name} (Favorite)").format(name=name)
            except Exception:
                LOG.debug("IPTVClient._decorate_channel_label: ignored exception", exc_info=True)
        return label + self._now_playing_suffix(channel)

    def _now_playing_suffix(self, channel: Dict[str, str]) -> str:
        """" — Title (HH:MM–HH:MM)" for the on-air programme, from the bulk cache."""
        # getattr guards: non-GUI test doubles stand in for the frame.
        if getattr(self, "view_mode", "live") != "live":
            return ""
        if not getattr(self, "config", {}).get("epg_enabled", True):
            return ""
        with getattr(self, "_now_playing_lock", threading.Lock()):
            cache = getattr(self, "_now_playing_labels", {})
            if not cache:
                return ""
            return cache.get(canonicalize_name(channel.get("name", "")), "")

    def _refresh_now_playing_labels(self):
        """One bulk query: the on-air programme of every EPG channel, for row labels."""
        if not getattr(self, "config", {}).get("epg_enabled", True):
            return
        now = time.time()
        if now - getattr(self, "_now_playing_refreshed_at", 0.0) < 30:
            return
        self._now_playing_refreshed_at = now
        try:
            db = EPGDatabase(get_db_path(), readonly=True)
            try:
                channels = db.get_all_now_next()
            finally:
                db.close()
        except Exception:
            LOG.debug("IPTVClient._refresh_now_playing_labels: ignored exception", exc_info=True)
            return
        mapping = self._build_now_playing_labels(channels)
        descriptions = self._build_now_playing_descriptions(channels)
        with self._now_playing_lock:
            changed = mapping != self._now_playing_labels
            self._now_playing_labels = mapping
            desc_changed = descriptions != self._now_playing_descriptions
            self._now_playing_descriptions = descriptions
        if changed:
            wx.CallAfter(self._refresh_channel_row_texts)
        elif desc_changed:
            # Only the description cache moved; refresh the field for the
            # row the user is sitting on.
            wx.CallAfter(self.on_highlight)

    @staticmethod
    def _epg_channel_indexes(channels: Dict[str, Dict[str, object]]):
        """(by_id, by_id_lower, name_index, stripped_index) for EPG matching."""
        by_id = channels
        by_id_lower = {str(cid).lower(): cid for cid in channels}
        name_index: Dict[str, str] = {}
        stripped_index: Dict[str, str] = {}
        for channel_id, entry in channels.items():
            display = entry.get("display_name") or ""
            for key, index in (
                (canonicalize_name(display), name_index),
                (canonicalize_name(strip_noise_words(display)), stripped_index),
            ):
                if key and key not in index:
                    index[key] = channel_id
        return by_id, by_id_lower, name_index, stripped_index

    @staticmethod
    def _match_epg_channel(channel, by_id, by_id_lower, name_index, stripped_index):
        """The EPG entry for a playlist channel, or None.

        1) tvg-id, including the common XMLTV id variants, case-insensitive
        and tolerant of one extra dotted segment ("chan.tv" vs "chan").
        2) names: exact normalized, then noise-stripped, for the channel
        name and then the tvg-name.
        """
        raw_id = str(channel.get("tvg-id") or "").strip()
        candidates = _expand_tvg_id_candidates(raw_id)
        candidates.append(raw_id)
        if "." in raw_id:
            candidates.append(raw_id.rsplit(".", 1)[0])
        for candidate in candidates:
            channel_id = by_id_lower.get(candidate.strip().lower())
            if channel_id is not None:
                return by_id[channel_id]
        for source in (channel.get("name"), channel.get("tvg-name")):
            text = str(source or "").strip()
            if not text:
                continue
            for key, index in (
                (canonicalize_name(text), name_index),
                (canonicalize_name(strip_noise_words(text)), stripped_index),
            ):
                channel_id = index.get(key)
                if channel_id is not None:
                    return by_id[channel_id]
        return None

    def _build_now_playing_labels(self, channels: Dict[str, Dict[str, object]]) -> Dict[str, str]:
        """Match every playlist channel to its EPG channel, fuzzily.

        Exact normalized names miss a lot of channels ("TVP 1 HD" against a
        "TVP 1" guide entry, renamed feeds, ...), so the lookup walks the same
        signals the EPG view uses: tvg-id first (expanded variants included),
        then normalized names with noise words stripped. The returned map is
        keyed by the playlist channel's normalized name, which is what the row
        renderer has at hand.
        """
        by_id, by_id_lower, name_index, stripped_index = self._epg_channel_indexes(channels)

        mapping: Dict[str, str] = {}
        playlist_channels = getattr(self, "all_channels", None) or []
        for channel in playlist_channels:
            name_key = canonicalize_name(channel.get("name", ""))
            if not name_key or name_key in mapping:
                continue
            entry = self._match_epg_channel(
                channel, by_id, by_id_lower, name_index, stripped_index)
            if not entry:
                continue
            suffix = ""
            now_show = entry.get("now")
            if now_show:
                text = self._programme_label(now_show, with_end=True)
                if text:
                    suffix = " — " + text
            next_show = entry.get("next")
            if next_show:
                text = self._programme_label(next_show, with_end=False)
                if text:
                    suffix += " — " + _("Next: {programme}").format(programme=text)
            if suffix:
                mapping[name_key] = suffix
        return mapping

    def _build_now_playing_descriptions(
            self, channels: Dict[str, Dict[str, object]]) -> Dict[str, str]:
        """On-air episode description per canonical playlist channel name.

        Same fuzzy channel match as the row labels, but carries the long
        description text for the Tab-reachable description field instead of
        the short row suffix. Channels with no match or no on-air
        description are simply absent; the field shows a placeholder.
        """
        by_id, by_id_lower, name_index, stripped_index = self._epg_channel_indexes(channels)
        mapping: Dict[str, str] = {}
        playlist_channels = getattr(self, "all_channels", None) or []
        for channel in playlist_channels:
            name_key = canonicalize_name(channel.get("name", ""))
            if not name_key or name_key in mapping:
                continue
            entry = self._match_epg_channel(
                channel, by_id, by_id_lower, name_index, stripped_index)
            if not entry:
                continue
            now_show = entry.get("now")
            if not now_show:
                continue
            text = (now_show.get("description") or "").strip()
            if text:
                mapping[name_key] = text
        return mapping

    def _programme_label(self, show: Dict[str, str], *, with_end: bool) -> str:
        """"Title (HH:MM–HH:MM)" (or "Title (HH:MM)"), for the row suffixes."""
        title = (show.get("title") or "").strip()
        if not title:
            return ""
        try:
            start = utc_to_local(datetime.datetime.strptime(
                show["start"], "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc))
            if not with_end:
                return "{title} ({start})".format(title=title, start=start.strftime("%H:%M"))
            end = utc_to_local(datetime.datetime.strptime(
                show["end"], "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc))
            return "{title} ({start}–{end})".format(
                title=title, start=start.strftime("%H:%M"), end=end.strftime("%H:%M"))
        except Exception:
            LOG.debug("IPTVClient._programme_label: ignored exception", exc_info=True)
            return title

    def _refresh_channel_row_texts(self):
        """Re-render the virtual rows so the next focus reads the new labels."""
        try:
            count = self.channel_list.GetItemCount()
            if count:
                self.channel_list.RefreshItems(0, count - 1)
        except Exception:
            LOG.debug("IPTVClient._refresh_channel_row_texts: ignored exception", exc_info=True)

    def _start_now_playing_timer(self):
        try:
            if self._now_playing_timer or not self.config.get("epg_enabled", True):
                return
            self._now_playing_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_now_playing_timer, self._now_playing_timer)
            self._now_playing_timer.Start(60000, wx.TIMER_CONTINUOUS)
        except Exception:
            self._now_playing_timer = None

    def _stop_now_playing_timer(self):
        try:
            if self._now_playing_timer:
                self._now_playing_timer.Stop()
                try:
                    self.Unbind(wx.EVT_TIMER, handler=self._on_now_playing_timer,
                                source=self._now_playing_timer)
                except Exception:
                    LOG.debug("IPTVClient._stop_now_playing_timer: ignored exception", exc_info=True)
                self._now_playing_timer = None
        except Exception:
            self._now_playing_timer = None

    def _on_now_playing_timer(self, _event):
        threading.Thread(target=self._refresh_now_playing_labels, daemon=True).start()

    def _toggle_favorite_selected(self, *_args):
        channel = self._selected_channel()
        if not channel:
            message_box(_("Select a channel first."), _("Favorites"),
                          wx.OK | wx.ICON_INFORMATION)
            return
        self._toggle_favorite(channel)

    def _toggle_favorite(self, channel: Dict[str, str]):
        """Add or remove a channel, then tell the user which it was."""
        if not favorites.channel_key(channel):
            message_box(_("This entry cannot be added to Favorites."), _("Favorites"),
                          wx.OK | wx.ICON_WARNING)
            return
        was_favorite = self._is_favorite(channel)
        keys, is_favorite = favorites.toggle(self.favorite_keys, channel)
        self.favorite_keys = keys
        self._favorite_key_set = set(keys)
        self.config["favorites"] = keys
        save_config(self.config)
        self._invalidate_favorites_cache()
        self._update_favorites_group_row()
        self._sync_favorite_menu_item()
        name = self._channel_display_name(channel)
        if was_favorite and self.current_group == favorites.FAVORITES_GROUP:
            # The row this was on has just left the category being displayed.
            self._rebuild_favorites_view(name)
            return
        self._announce_channel_row()
        LOG.debug("Favorite %s: %s", "added" if is_favorite else "removed", name)

    def _announce_channel_row(self):
        """Re-fire focus on the current row so the screen reader re-reads it.

        Changing a virtual row's text does not make NVDA say anything, and the
        favorite marker is part of that text, so the focus event is the feedback
        that the channel was added or removed.
        """
        announce = getattr(self.channel_list, "announce_item", None)
        if not callable(announce):
            return
        try:
            announce(self.channel_list.GetSelection())
        except Exception:
            LOG.debug("IPTVClient._announce_channel_row: ignored exception", exc_info=True)

    def _rebuild_favorites_view(self, removed_name: str = ""):
        """Refresh the Favorites category after a channel was removed from it."""
        index = self.channel_list.GetSelection()
        entries = [{"type": "channel", "data": ch} for ch in self._favorite_channels()]
        self._populate_token += 1
        IPTVClient._replace_displayed(self, entries)
        if not entries:
            self.url_display.SetValue("")
            # Nothing left to focus here, so hand the user back to the categories.
            self._refresh_group_ui()
            message_box(_("{name} was removed. Favorites is now empty.").format(name=removed_name),
                          _("Favorites"), wx.OK | wx.ICON_INFORMATION)
            return
        self.channel_list.SetSelection(min(max(index, 0), len(entries) - 1))
        self.on_highlight()
        self._announce_channel_row()

    def _update_favorites_group_row(self):
        """Insert, relabel or drop the Favorites category without moving focus.

        A full ``_refresh_group_ui`` would repopulate the channel list and pull
        focus out of it, which is exactly what must not happen while the user is
        marking favorites from the channel list.
        """
        if getattr(self, "view_mode", "live") != "live":
            return
        keys = self._group_keys
        if not keys or keys[0] != "All Channels":
            return  # still loading, or showing the placeholder row
        count = len(self._favorite_channels())
        try:
            existing = keys.index(favorites.FAVORITES_GROUP)
        except ValueError:
            existing = -1
        selection = self.group_list.GetSelection()
        try:
            if count and existing == -1:
                self.group_list.Insert(self._favorites_group_label(count), 1)
                keys.insert(1, favorites.FAVORITES_GROUP)
                if selection != wx.NOT_FOUND and selection >= 1:
                    selection += 1
            elif count and existing != -1:
                self.group_list.SetString(existing, self._favorites_group_label(count))
            elif not count and existing != -1:
                self.group_list.Delete(existing)
                keys.pop(existing)
                if selection != wx.NOT_FOUND and selection > existing:
                    selection -= 1
                elif selection == existing:
                    selection = 0
                    self.current_group = "All Channels"
            if selection != wx.NOT_FOUND and 0 <= selection < self.group_list.GetCount():
                self.group_list.SetSelection(selection)
        except Exception:
            LOG.debug("IPTVClient._update_favorites_group_row: ignored exception", exc_info=True)

    def _favorite_action_label(self, channel: Optional[Dict[str, str]] = None) -> str:
        """Whether the favorites action would add or remove, for the channel it will hit."""
        if channel is None:
            channel = self._selected_channel()
        return _("Remove from Favorites") if self._is_favorite(channel) else _("Add to Favorites")

    def _go_to_favorites(self, *_args):
        """Move the category selection to Favorites and focus the channel list."""
        if getattr(self, "view_mode", "live") != "live":
            self._set_view_mode("live")
        if not self._favorite_channels():
            message_box(
                _("You have not added any favorites yet. Select a channel and press "
                  "Ctrl+D to add it."),
                _("Favorites"), wx.OK | wx.ICON_INFORMATION)
            return
        if favorites.FAVORITES_GROUP not in self._group_keys:
            self._refresh_group_ui()
        try:
            index = self._group_keys.index(favorites.FAVORITES_GROUP)
        except ValueError:
            LOG.debug("IPTVClient._go_to_favorites: favorites category is not listed")
            return
        self.group_list.SetSelection(index)
        self._activate_selected_group()

    def _sync_favorite_menu_item(self):
        """Keep the View menu entry saying what it will actually do."""
        item = getattr(self, "favorite_menu_item", None)
        if item is None:
            return
        try:
            item.SetItemLabel(self._favorite_action_label() + "\tCtrl+D")
        except Exception:
            LOG.debug("IPTVClient._sync_favorite_menu_item: ignored exception", exc_info=True)

    def _channel_is_epg_exempt(self, channel: Dict[str, str]) -> bool:
        """Detect channels that typically have no EPG (e.g., 24/7 loops).
        We do NOT modify names; this only avoids unnecessary DB lookups/logs.
        Rule: tvg-id empty AND name/group contains '24/7' or '24x7'.
        """
        try:
            tvg_id = (channel.get("tvg-id") or channel.get("tvg_id") or "").strip()
            if tvg_id:
                return False
            name = (channel.get("tvg-name") or channel.get("name") or "").lower()
            group = (channel.get("group-title") or channel.get("group") or "").lower()
            if "24/7" in name or "24x7" in name or "24/7" in group or "24x7" in group:
                return True
        except Exception:
            LOG.debug("IPTVClient._channel_is_epg_exempt: ignored exception", exc_info=True)
        return False

    def start_playlist_load(self):
        """Kicks off ONLY the playlist loading thread."""
        self._playlist_load_token += 1
        self._pending_epg_autostart = True
        self._pending_epg_autostart_token = self._playlist_load_token
        self._cancel_epg_autostart_timer()
        threading.Thread(
            target=self._do_playlist_refresh,
            args=(self._playlist_load_token,),
            daemon=True
        ).start()

    def _ensure_db_tuned(self):
        """Enable WAL and indices so read lookups don’t stall behind imports."""
        conn = None
        try:
            path = get_db_path()
            if not os.path.exists(path):
                return
            uri = f"file:{path}?cache=shared"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            cur = conn.cursor()
            tables = {
                row[0]
                for row in cur.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name IN ('channels', 'programmes')
                    """
                ).fetchall()
            }
            if {"channels", "programmes"} - tables:
                return
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA temp_store=MEMORY;")
            cur.execute("PRAGMA mmap_size=268435456;")
            cur.execute("PRAGMA cache_size=-65536;")
            cur.execute("PRAGMA wal_autocheckpoint=0;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_programmes_channel_end ON programmes(channel_id, end);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_programmes_channel_start_end ON programmes(channel_id, start, end);")
            conn.commit()
        except Exception:
            LOG.debug("IPTVClient._ensure_db_tuned: ignored exception", exc_info=True)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    LOG.debug("IPTVClient._ensure_db_tuned: ignored exception", exc_info=True)

    def _sync_player_menu_from_config(self):
        defplayer = self.config.get("media_player", "Built-in Player")
        self.default_player = defplayer
        for key, attr in self.PLAYER_MENU_ATTRS.items():
            if hasattr(self, attr):
                getattr(self, attr).Check(key == defplayer)
        if hasattr(self, "player_Custom"):
            self.player_Custom.Check(defplayer == "Custom")
        if hasattr(self, "_player_radio_items"):
            for label, item in self._player_radio_items.items():
                item.Check(label == defplayer)

    def on_menu_open(self, event):
        from options import load_config
        self.config = load_config()
        self._sync_player_menu_from_config()
        # The config was just replaced, so anything cached out of it is re-read.
        self._sync_favorites_from_config()
        self._update_recording_menu_state()
        self._sync_player_controls_menu()
        item = getattr(self, "show_downloads_item", None)
        if item is not None:
            try:
                item.Enable(bool(getattr(self, "_catchup_downloads", None)))
            except Exception:
                LOG.debug("IPTVClient.on_menu_open: ignored exception", exc_info=True)
        # The playlist list may have changed on disk; keep the scope picker in
        # step (its stored selection may also have been replaced or removed).
        self.playlist_scope = self.config.get("playlist_scope", ALL_PLAYLISTS_SCOPE)
        if not isinstance(self.playlist_scope, str):
            self.playlist_scope = ALL_PLAYLISTS_SCOPE
        self._fill_playlist_scope_combo()
        self._sync_favorite_menu_item()
        self._shutdown_after_recordings = self._bool_pref(
            self.config.get("shutdown_after_recordings", False))
        item = getattr(self, "_shutdown_after_item", None)
        if item is not None:
            try:
                item.Check(self._shutdown_after_recordings)
            except Exception:
                LOG.debug("IPTVClient.on_menu_open: ignored exception", exc_info=True)
        if hasattr(self, "min_to_tray_item"):
            self.minimize_to_tray = bool(self.config.get("minimize_to_tray", False))
            self.min_to_tray_item.Check(self.minimize_to_tray)
        self.show_player_on_enter = self._bool_pref(self.config.get("show_player_on_enter", True), default=True)
        if hasattr(self, "show_player_on_enter_item"):
            try:
                self.show_player_on_enter_item.Check(self.show_player_on_enter)
            except Exception:
                LOG.debug("IPTVClient.on_menu_open: ignored exception", exc_info=True)
        self.show_channel_url = self._bool_pref(self.config.get("show_channel_url", True), default=True)
        if hasattr(self, "show_channel_url_item"):
            try:
                self.show_channel_url_item.Check(self.show_channel_url)
            except Exception:
                LOG.debug("IPTVClient.on_menu_open: ignored exception", exc_info=True)
        self.auto_check_updates = self._bool_pref(self.config.get("auto_check_updates", True), default=True)
        if hasattr(self, "auto_check_updates_item"):
            try:
                self.auto_check_updates_item.Check(self.auto_check_updates)
            except Exception:
                LOG.debug("IPTVClient.on_menu_open: ignored exception", exc_info=True)
        event.Skip()

    def start_refresh_timer(self):
        if self.refresh_timer is None:
            self.refresh_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_timer_refresh, self.refresh_timer)
        else:
            self.refresh_timer.Stop()
        self.refresh_timer.Start(3 * 60 * 60 * 1000, wx.TIMER_CONTINUOUS)

    def on_timer_refresh(self, event):
        # This full cycle can be triggered by the timer.
        self.start_playlist_load()

    def _do_playlist_refresh(self, refresh_token: int):
        """
        Loads playlists from cache for a fast UI update, then refreshes from the network.
        Crucially, it only starts the EPG import *after* playlists are loaded.
        """
        playlist_sources = self.config.get("playlists", [])
        # Ensure all provider entries have persistent IDs so we can track clients.
        mutated = False
        for src in playlist_sources:
            if isinstance(src, dict) and not src.get("id"):
                src["id"] = generate_provider_id()
                mutated = True
        if mutated:
            self.config["playlists"] = playlist_sources
            save_config(self.config)

        channels_by_group: Dict[str, List[Dict[str, str]]] = {}
        all_channels: List[Dict[str, str]] = []
        valid_caches = set()
        seen_channel_keys = set()

        # Fast prefill from parsed caches (no network) so UI shows something immediately.
        prefilled_by_group: Dict[str, List[Dict[str, str]]] = {}
        prefilled_all: List[Dict[str, str]] = []
        prefill_seen = set()

        # (hash, channels) already read from a parsed-cache file during prefill, keyed by
        # that file's path. On the common "nothing changed" launch, fetch_and_process_playlist
        # below re-derives the same path and, once it has the freshly-fetched text_hash, can
        # reuse this instead of re-reading + re-decoding the same (potentially huge) JSON file.
        prefill_loaded: Dict[str, Tuple[Optional[str], List[Dict[str, str]]]] = {}

        def _cached_channels_for(parsed_cache, text_hash, provider_meta):
            entry = prefill_loaded.get(parsed_cache)
            if entry is not None:
                stored_hash, stored_channels = entry
                return stored_channels if stored_hash == text_hash else None
            return self._load_cached_playlist(parsed_cache, text_hash, provider_meta)

        def _prefill_from_cache(src) -> None:
            parsed_cache = None
            provider_meta = None
            if isinstance(src, dict):
                stype = (src.get("type") or "").lower()
                provider_id = src.get("id") or src.get("provider_id")
                if stype in ("xtream", "stalker"):
                    cache_key = provider_id or f"{stype}:{src.get('base_url') or src.get('url') or ''}:{src.get('username', '')}"
                    parsed_cache = self._parsed_cache_path_for_key(f"provider:{cache_key}")
                    provider_meta = {"provider-type": stype, "provider-id": provider_id}
            elif isinstance(src, str) and src.startswith(("http://", "https://")):
                parsed_cache = self._parsed_cache_path_for_key(src)
            elif isinstance(src, str) and os.path.exists(src):
                parsed_cache = self._parsed_cache_path_for_key(f"file:{os.path.abspath(src)}")
            if not parsed_cache or not os.path.exists(parsed_cache):
                return
            stored_hash, cached = self._read_cached_playlist_file(parsed_cache)
            if not cached:
                return
            self._apply_cached_provider_meta(cached, provider_meta)
            prefill_loaded[parsed_cache] = (stored_hash, cached)
            # Tag each channel with the playlist it came from so the playlist
            # scope combo can show a single playlist's categories.
            scope_id = _source_scope_id(src)
            for ch in cached:
                key = (scope_id, ch.get("name", ""), ch.get("url", ""), ch.get("provider-id", ""))
                if key in prefill_seen:
                    continue
                if scope_id:
                    ch["playlist-id"] = scope_id
                prefill_seen.add(key)
                grp = ch.get("group") or "Uncategorized"
                prefilled_by_group.setdefault(grp, []).append(ch)
                prefilled_all.append(ch)

        for _src in playlist_sources:
            _prefill_from_cache(_src)

        if prefilled_all:
            seen_channel_keys.update(prefill_seen)
            channels_by_group = {grp: lst.copy() for grp, lst in prefilled_by_group.items()}
            all_channels = list(prefilled_all)

            def apply_prefill(pref_by_group, pref_all):
                if refresh_token != self._playlist_load_token:
                    return
                self.channels_by_group = pref_by_group
                self.all_channels = pref_all
                self._invalidate_favorites_cache()
                self._fill_playlist_scope_combo()
                self._refresh_group_ui()

            wx.CallAfter(apply_prefill, prefilled_by_group, prefilled_all)

        # We will collect these from the workers
        provider_clients_local: Dict[str, object] = {}
        provider_epg_sources: List[str] = []

        def fetch_and_process_playlist(src):
            result = {
                "channels": [],
                "clients": {},
                "epg_sources": [],
                "valid_cache": None,
                "error": None
            }
            try:
                if isinstance(src, dict):
                    stype = (src.get("type") or "").lower()
                    provider_id = src.get("id") or src.get("provider_id")
                    if stype == "xtream":
                        cfg = XtreamCodesConfig(
                            base_url=src.get("base_url") or src.get("url") or "",
                            username=src.get("username", ""),
                            password=src.get("password", ""),
                            stream_type=src.get("stream_type", "m3u_plus"),
                            output=src.get("output", "ts"),
                            name=src.get("name"),
                            auto_epg=bool(src.get("auto_epg", True)),
                            provider_id=provider_id
                        )
                        client = XtreamCodesClient(cfg)
                        text = client.fetch_playlist()
                        text_hash = self._playlist_text_hash(text)
                        cache_key = provider_id or f"xtream:{cfg.base_url}:{cfg.username}"
                        parsed_cache = self._parsed_cache_path_for_key(f"provider:{cache_key}")
                        provider_meta = {"provider-type": "xtream", "provider-id": provider_id}
                        
                        channels = None
                        if parsed_cache and text_hash:
                            channels = _cached_channels_for(parsed_cache, text_hash, provider_meta)
                        if channels is None:
                            channels = self._parse_m3u_return(text, provider_info=provider_meta)
                            if parsed_cache and text_hash:
                                self._store_cached_playlist(parsed_cache, text_hash, channels, provider_meta)
                        
                        result["channels"] = channels or []
                        result["clients"][provider_id] = client
                        if cfg.auto_epg:
                            for epg in client.epg_urls():
                                if epg: result["epg_sources"].append(epg)

                    elif stype == "stalker":
                        cfg = StalkerPortalConfig(
                            base_url=src.get("base_url") or src.get("url") or "",
                            username=src.get("username", ""),
                            password=src.get("password", ""),
                            mac=src.get("mac", ""),
                            name=src.get("name"),
                            auto_epg=bool(src.get("auto_epg", True)),
                            provider_id=provider_id
                        )
                        client = StalkerPortalClient(cfg)
                        channels, epgs = client.fetch_channels()
                        for ch in channels:
                            ch.setdefault("provider-id", provider_id)
                            ch.setdefault("provider-type", "stalker")
                        
                        result["channels"] = channels
                        result["clients"][provider_id] = client
                        for epg in epgs:
                            if epg: result["epg_sources"].append(epg)
                    else:
                        pass # Unknown dict source
                    return result

                # Plain playlist path or URL
                if isinstance(src, str) and src.startswith(("http://", "https://")):
                    cache_path = get_cache_path_for_url(src)
                    parsed_cache = self._parsed_cache_path_for_key(src)
                    result["valid_cache"] = cache_path
                    
                    download = True
                    if os.path.exists(cache_path):
                        age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(cache_path))).total_seconds()
                        if age < 15 * 60:
                            download = False

                    text = ""
                    if download:
                        with urllib.request.urlopen(
                            urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"}), timeout=60
                        ) as resp:
                            raw = resp.read()
                            try:
                                # utf-8-sig strips a leading BOM if present; otherwise == utf-8.
                                text = raw.decode("utf-8-sig")
                            except UnicodeDecodeError:
                                text = raw.decode("latin-1", "ignore")
                        with open(cache_path, "w", encoding="utf-8") as f:
                            f.write(text)
                    else:
                        with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read()
                            
                    text_hash = self._playlist_text_hash(text)
                    
                    channels = None
                    if parsed_cache and text_hash:
                        channels = _cached_channels_for(parsed_cache, text_hash, provider_meta=None)
                    if channels is None:
                        channels = self._parse_m3u_return(text, provider_info=None)
                        if parsed_cache and text_hash:
                            self._store_cached_playlist(parsed_cache, text_hash, channels, provider_meta=None)
                    
                    result["channels"] = channels or []

                elif isinstance(src, str) and os.path.exists(src):
                    with open(src, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    text_hash = self._playlist_text_hash(text)
                    cache_key = f"file:{os.path.abspath(src)}"
                    parsed_cache = self._parsed_cache_path_for_key(cache_key)
                    
                    channels = None
                    if parsed_cache and text_hash:
                        channels = _cached_channels_for(parsed_cache, text_hash, provider_meta=None)
                    if channels is None:
                        channels = self._parse_m3u_return(text, provider_info=None)
                        if parsed_cache and text_hash:
                            self._store_cached_playlist(parsed_cache, text_hash, channels, provider_meta=None)
                            
                    result["channels"] = channels or []
                else:
                    pass # Invalid source
            except Exception as e:
                result["error"] = str(e)
                # LOG.error(f"Error fetching playlist {src}: {e}")
            
            return result

        # Execute in parallel (fetching AND parsing) with a CPU-friendly cap.
        source_count = len(playlist_sources)
        cpu_count = os.cpu_count() or 2
        worker_cap = max(2, cpu_count // 2)
        max_workers = min(source_count if source_count else 1, worker_cap, 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_and_process_playlist, src): src for src in playlist_sources}
            for future in concurrent.futures.as_completed(futures):
                src = futures[future]
                res = future.result()
                if res["error"]:
                    continue
                
                if res["valid_cache"]:
                    valid_caches.add(res["valid_cache"])
                
                provider_clients_local.update(res["clients"])
                for epg in res["epg_sources"]:
                    if epg not in provider_epg_sources:
                        provider_epg_sources.append(epg)
                
                for ch in res["channels"]:
                    scope_id = _source_scope_id(src)
                    key = (scope_id, ch.get("name", ""), ch.get("url", ""), ch.get("provider-id", ""))
                    if key in seen_channel_keys:
                        continue
                    seen_channel_keys.add(key)
                    # Remember which playlist each channel belongs to so the
                    # playlist scope combo can filter categories per playlist.
                    if scope_id:
                        ch["playlist-id"] = scope_id
                    grp = ch.get("group") or "Uncategorized"
                    channels_by_group.setdefault(grp, []).append(ch)
                    all_channels.append(ch)

        def finish_playlist_load_and_start_background_tasks():
            # A stale background load (e.g. the refresh timer firing during a slow
            # initial load) must not clobber newer channels/EPG sources.
            if refresh_token != self._playlist_load_token:
                return
            self.channels_by_group = channels_by_group
            self.all_channels = all_channels
            self._invalidate_favorites_cache()
            self.provider_clients = provider_clients_local
            self.provider_epg_sources = provider_epg_sources
            self.reload_epg_sources()
            self._pending_epg_autostart = True
            self._pending_epg_autostart_token = refresh_token
            # A reload invalidates any previously built VOD catalogue.
            self.vod_loaded = False
            self.vod_groups = {}
            self.vod_group_order = []
            self._fill_playlist_scope_combo()
            if self.view_mode == "vod":
                self._load_vod_catalog()
            else:
                self._refresh_group_ui()
            self._cleanup_cache_and_channels(valid_caches)
            # Now that playlists are loaded, start the other processes.
            self.start_refresh_timer()
            self._schedule_auto_update_check()

        wx.CallAfter(finish_playlist_load_and_start_background_tasks)


    def _cleanup_cache_and_channels(self, valid_caches):
        cache_dir = get_cache_dir()
        try:
            files = [os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if f.endswith(".m3u")]
        except Exception:
            return
        for f in files:
            if f not in valid_caches:
                try:
                    os.remove(f)
                except Exception:
                    LOG.debug("IPTVClient._cleanup_cache_and_channels: ignored exception", exc_info=True)

    def _build_ui(self):
        p = wx.Panel(self)
        hs = wx.BoxSizer(wx.HORIZONTAL)
        vs_l = wx.BoxSizer(wx.VERTICAL)
        vs_r = wx.BoxSizer(wx.VERTICAL)
        # Playlist scope picker, one Shift+Tab before the categories list. The
        # categories and channels show only the chosen playlist's entries (or
        # everything for "All playlists"). wx.Choice gets an MSAA name through
        # SetName/SetAccessibleName so screen readers announce a label.
        vs_l.Add(wx.StaticText(p, label=_("Playlist view")), 0, wx.LEFT | wx.TOP, 5)
        self.playlist_scope_combo = wx.Choice(p, choices=[])
        self.playlist_scope_combo.SetName(_("Playlist view"))
        if hasattr(self.playlist_scope_combo, "SetAccessibleName"):
            self.playlist_scope_combo.SetAccessibleName(_("Playlist view"))
        self.playlist_scope_combo.Bind(wx.EVT_CHAR_HOOK, self.on_playlist_scope_key)
        # Screen-reader names on MSW come from the static label created
        # immediately before each control: the tree/list/edit accessibles
        # ignore SetName/SetAccessibleName, but a wx.StaticText whose auto id
        # is exactly control id - 1 is announced. Verified with real MSAA/UIA
        # reads in tools/smoke_accessible_names_nvda.py; keep the pair
        # adjacent with no other window created in between.
        self.categories_label = wx.StaticText(p, label=_("Categories"))
        self.group_list = _AccessibleCategoryTree(p)
        self.group_list.Bind(wx.EVT_CHAR_HOOK, self.on_group_key)
        self.group_list.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_group_activated)
        self.playlist_scope_combo.Bind(wx.EVT_CHOICE, self.on_playlist_scope_changed)
        self._fill_playlist_scope_combo()
        vs_l.Add(self.playlist_scope_combo, 0, wx.EXPAND | wx.ALL, 5)
        vs_l.Add(self.categories_label, 0, wx.LEFT, 5)
        vs_l.Add(self.group_list, 1, wx.EXPAND | wx.ALL, 5)
        self.search_label = wx.StaticText(p, label=_("Search"))
        self.filter_box = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        # Name the field for screen readers as well: harmless on MSW and it is
        # what GTK honors for the accessible name.
        self.filter_box.SetName(_("Search"))
        if hasattr(self.filter_box, "SetAccessibleName"):
            self.filter_box.SetAccessibleName(_("Search"))
        # Virtual list control (native SysListView32) so 50k-300k channels stay responsive
        # for the UI and NVDA alike — only visible rows are realized. Backed by self.displayed.
        self.channels_label = wx.StaticText(p, label=_("Channels"))
        self.channel_list = _VirtualChannelList(p, self)
        # Key bindings (original + added robust handlers)
        self.channel_list.Bind(wx.EVT_CHAR_HOOK, self.on_channel_key)  # original
        self.channel_list.Bind(wx.EVT_KEY_DOWN, self._on_channel_key_down)  # reliable Enter on all platforms
        # Selection change (keyboard arrows + mouse) -> refresh EPG/URL panel.
        self.channel_list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _evt: self.on_highlight())
        # Activation: Enter is consumed by the key handlers above, so this fires on double-click.
        self.channel_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _evt: self.play_selected())
        self.channel_list.Bind(wx.EVT_CONTEXT_MENU, self._on_channel_context_menu)

        # Tab order after the channel list is episode description -> stream
        # URL. The description comes first because it is what a viewer
        # actually wants after hearing a channel row; the URL is a diagnostic
        # that most users keep switched off entirely. wx builds tab order from
        # creation order, so the description control is created first and the
        # sizer follows the same sequence.
        self.episode_description_field = wx.TextCtrl(
            p, size=(-1, 70), style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.episode_description_field.SetName(_("Episode description"))
        if hasattr(self.episode_description_field, "SetAccessibleName"):
            self.episode_description_field.SetAccessibleName(_("Episode description"))
        self.episode_description_field.Bind(
            wx.EVT_CHAR_HOOK, self._on_episode_description_key)
        self.url_display = wx.TextCtrl(p, style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.url_display.SetName(_("Stream URL"))
        if hasattr(self.url_display, "SetAccessibleName"):
            self.url_display.SetAccessibleName(_("Stream URL"))
        self.url_display.Bind(wx.EVT_CHAR_HOOK, self._on_url_display_key)
        # F1 opens the User Guide at the section about the focused control.
        user_guide.set_help_topic(self, "main-window")
        user_guide.set_help_topic(self.playlist_scope_combo, "playlist-view")
        user_guide.set_help_topic(self.group_list, lambda: self._list_help_topic("categories"))
        user_guide.set_help_topic(self.filter_box, "search")
        user_guide.set_help_topic(self.channel_list, lambda: self._list_help_topic("channel-list"))
        user_guide.set_help_topic(self.episode_description_field, "episode-description")
        user_guide.set_help_topic(self.url_display, "episode-description")
        vs_r.Add(self.search_label, 0, wx.LEFT | wx.TOP, 5)
        vs_r.Add(self.filter_box, 0, wx.EXPAND | wx.ALL, 5)
        vs_r.Add(self.channels_label, 0, wx.LEFT | wx.TOP, 5)
        vs_r.Add(self.channel_list, 1, wx.EXPAND | wx.ALL, 5)
        vs_r.Add(self.episode_description_field, 0, wx.EXPAND | wx.ALL, 5)
        vs_r.Add(self.url_display, 0, wx.EXPAND | wx.ALL, 5)
        self._apply_channel_url_visibility()
        hs.Add(vs_l, 1, wx.EXPAND)
        hs.Add(vs_r, 2, wx.EXPAND)

        if platform.system() == "Linux":
            self.menu_button = wx.Button(p, label=_("Menu"))
            self._player_radio_items = {}
            def on_menu_btn(evt):
                menu = wx.Menu()
                menu.Append(1001, _("Playlist Manager") + "\tCtrl+M")
                menu.Append(1002, _("EPG Manager") + "\tCtrl+E")
                menu.Append(1003, _("Import EPG to DB") + "\tCtrl+I")
                menu.Append(1007, _("Account Info") + "\tCtrl+Shift+A")
                menu.AppendSeparator()
                player_ctrl_menu = wx.Menu()
                player_ctrl_menu.Append(1201, _("Show Built-in Player"))
                player_ctrl_menu.Append(1202, _("Play/Pause"))
                player_ctrl_menu.Append(1203, _("Stop"))
                player_ctrl_menu.Append(1204, _("Cast / Connect..."))
                menu.AppendSubMenu(player_ctrl_menu, _("Player"))
                self.Bind(wx.EVT_MENU, self._menu_show_player, id=1201)
                self.Bind(wx.EVT_MENU, self._menu_toggle_player, id=1202)
                self.Bind(wx.EVT_MENU, self._menu_stop_player, id=1203)
                self.Bind(wx.EVT_MENU, self._menu_cast_from_player, id=1204)
                # View submenu: Live TV / catch-up vs Video on Demand.
                view_menu = wx.Menu()
                view_live = view_menu.AppendRadioItem(1301, _("Live TV && Catch-up"))
                view_vod = view_menu.AppendRadioItem(1302, _("Video on Demand (Movies && Series)"))
                view_live.Check(self.view_mode == "live")
                view_vod.Check(self.view_mode == "vod")
                self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("live"), id=1301)
                self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("vod"), id=1302)
                view_menu.AppendSeparator()
                view_menu.Append(1310, self._favorite_action_label() + "\tCtrl+D")
                view_menu.Append(1311, _("Go to Favorites"))
                self.Bind(wx.EVT_MENU, self._toggle_favorite_selected, id=1310)
                self.Bind(wx.EVT_MENU, self._go_to_favorites, id=1311)
                menu.AppendSubMenu(view_menu, _("View"))
                menu.AppendSeparator()
                player_menu = wx.Menu()
                for idx, (label, attr) in enumerate(self.PLAYER_KEYS):
                    itemid = 2000 + idx
                    item = player_menu.AppendRadioItem(itemid, _(label))
                    self._player_radio_items[label] = item
                    self.Bind(wx.EVT_MENU, lambda evt, pl=label: self._select_player(pl), id=itemid)
                    if self.default_player == label:
                        item.Check(True)
                customid = 2999
                customitem = player_menu.AppendRadioItem(customid, _("Custom Player..."))
                self.Bind(wx.EVT_MENU, self._select_custom_player, id=customid)
                if self.default_player == "Custom":
                    customitem.Check(True)
                menu.AppendSubMenu(player_menu, _("Media Player to Use"))
                menu.Append(1312, _("Preferred Audio Track..."))
                self.Bind(wx.EVT_MENU, self._show_audio_preference_dialog, id=1312)
                # Recordings submenu (Linux)
                rec_menu = wx.Menu()
                self._populate_recordings_menu(rec_menu)
                menu.AppendSubMenu(rec_menu, _("Recordings"))
                # Language submenu (Linux)
                lang_menu = wx.Menu()
                self._lang_menu_items = {}
                for code, label in i18n.available_languages():
                    disp = _("Automatic") if code == "auto" else label
                    li = lang_menu.AppendRadioItem(wx.ID_ANY, disp)
                    if i18n.get_language() == code:
                        li.Check(True)
                    self._lang_menu_items[li.GetId()] = code
                    self.Bind(wx.EVT_MENU, lambda evt, c=code: self._on_select_language(c), li)
                menu.AppendSubMenu(lang_menu, _("Language"))
                min_to_tray_id = 1101
                min_item = menu.AppendCheckItem(min_to_tray_id, _("Minimize to System Tray"))
                min_item.Check(self.minimize_to_tray)
                self.Bind(wx.EVT_MENU, self.on_toggle_min_to_tray, id=min_to_tray_id)
                menu.AppendSeparator()
                show_enter_id = 1102
                show_enter_item = menu.AppendCheckItem(show_enter_id, _("Show Player on Enter"))
                show_enter_item.Check(self.show_player_on_enter)
                self.Bind(wx.EVT_MENU, self.on_toggle_show_player_on_enter, id=show_enter_id)
                show_url_id = 1104
                show_url_item = menu.AppendCheckItem(show_url_id, _("Show Stream URL"))
                show_url_item.Check(self.show_channel_url)
                self.Bind(wx.EVT_MENU, self.on_toggle_show_channel_url, id=show_url_id)
                menu.AppendSeparator()

                auto_update_id = 1103
                auto_update_item = menu.AppendCheckItem(auto_update_id, _("Auto-check for Updates"))
                auto_update_item.Check(self.auto_check_updates)
                self.Bind(wx.EVT_MENU, self.on_toggle_auto_check_updates, id=auto_update_id)
                menu.Append(1006, _("Check for Updates"))
                self.Bind(wx.EVT_MENU, self.on_check_updates, id=1006)
                menu.AppendSeparator()

                help_menu = wx.Menu()
                guide_item = help_menu.Append(wx.ID_ANY, _("User Guide") + "\tF1")
                help_menu.Bind(wx.EVT_MENU, self._on_user_guide_menu, guide_item)
                logs_item = help_menu.Append(wx.ID_ANY, _("Open Logs Folder"))
                copy_debug_item = help_menu.Append(wx.ID_ANY, _("Copy Log and Debug Information"))
                about_item = help_menu.Append(wx.ID_ABOUT, _("About..."))
                help_menu.Bind(wx.EVT_MENU, self._open_logs_folder, logs_item)
                help_menu.Bind(wx.EVT_MENU, self._copy_diagnostic_information, copy_debug_item)
                help_menu.Bind(wx.EVT_MENU, self._show_about_dialog, about_item)
                menu.AppendSubMenu(help_menu, _("Help"))

                # Casting Menu Item (Linux)
                menu.Append(1005, _("Cast To..."))
                self.Bind(wx.EVT_MENU, self.show_cast_dialog, id=1005)

                menu.Append(1004, _("Exit") + "\tCtrl+Q")
                self.Bind(wx.EVT_MENU, self.show_manager, id=1001)
                self.Bind(wx.EVT_MENU, self.show_epg_manager, id=1002)
                self.Bind(wx.EVT_MENU, self.import_epg, id=1003)
                self.Bind(wx.EVT_MENU, self.show_account_info, id=1007)
                self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=1004)
                self.menu_button.PopupMenu(menu)
            self.menu_button.Bind(wx.EVT_BUTTON, on_menu_btn)
            sizer_with_menu = wx.BoxSizer(wx.VERTICAL)
            sizer_with_menu.Add(self.menu_button, 0, wx.EXPAND | wx.ALL, 5)
            sizer_with_menu.Add(hs, 1, wx.EXPAND)
            p.SetSizerAndFit(sizer_with_menu)
        else:
            p.SetSizerAndFit(hs)
            mb = wx.MenuBar()
            fm = wx.Menu()
            m_mgr = fm.Append(wx.ID_ANY, _("Playlist Manager") + "\tCtrl+M")
            m_epg = fm.Append(wx.ID_ANY, _("EPG Manager") + "\tCtrl+E")
            m_imp = fm.Append(wx.ID_ANY, _("Import EPG to DB") + "\tCtrl+I")
            m_now = fm.Append(wx.ID_ANY, _("What's on Now") + "\tCtrl+W")
            m_acct = fm.Append(wx.ID_ANY, _("Account Info") + "\tCtrl+Shift+A")
            fm.AppendSeparator()
            # Casting Menu Item (Windows/Mac)
            m_cast = fm.Append(wx.ID_ANY, _("Cast To..."))
            fm.AppendSeparator()
            m_exit = fm.Append(wx.ID_EXIT, _("Exit") + "\tCtrl+Q")
            mb.Append(fm, _("File"))
            pm = wx.Menu()
            pm_show = pm.Append(wx.ID_ANY, _("Show Built-in Player") + "\tCtrl+Shift+J")
            pm_toggle = pm.Append(wx.ID_ANY, _("Play/Pause") + "\tCtrl+Shift+P")
            pm_stop = pm.Append(wx.ID_ANY, _("Stop") + "\tCtrl+Shift+S")
            pm_cast = pm.Append(wx.ID_ANY, _("Cast / Connect...") + "\tCtrl+Shift+C")
            self._player_control_items = (pm_show, pm_toggle, pm_stop, pm_cast)
            mb.Append(pm, _("Player"))
            # View menu: switch between Live TV / catch-up and Video on Demand.
            vm = wx.Menu()
            self.view_live_item = vm.AppendRadioItem(wx.ID_ANY, _("Live TV && Catch-up"))
            self.view_vod_item = vm.AppendRadioItem(wx.ID_ANY, _("Video on Demand (Movies && Series)"))
            self.view_live_item.Check(self.view_mode == "live")
            self.view_vod_item.Check(self.view_mode == "vod")
            vm.AppendSeparator()
            # The label follows the selected channel, so it always says what
            # activating it will do (see _sync_favorite_menu_item).
            self.favorite_menu_item = vm.Append(wx.ID_ANY, _("Add to Favorites") + "\tCtrl+D")
            self.goto_favorites_item = vm.Append(wx.ID_ANY, _("Go to Favorites"))
            vm.AppendSeparator()
            # Escape hides a download window without stopping the download,
            # and a modeless window is easy to lose behind this one: this is
            # the way back to it.
            self.show_downloads_item = vm.Append(wx.ID_ANY, _("Show Downloads") + "\tCtrl+Shift+D")
            mb.Append(vm, _("View"))
            self.Bind(wx.EVT_MENU, self._show_catchup_downloads, self.show_downloads_item)
            self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("live"), self.view_live_item)
            self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("vod"), self.view_vod_item)
            self.Bind(wx.EVT_MENU, self._toggle_favorite_selected, self.favorite_menu_item)
            self.Bind(wx.EVT_MENU, self._go_to_favorites, self.goto_favorites_item)
            om = wx.Menu()
            player_menu = wx.Menu()
            self.player_menu_items = []
            for label, attr in self.PLAYER_KEYS:
                item = player_menu.AppendRadioItem(wx.ID_ANY, _(label))
                setattr(self, attr, item)
                self.player_menu_items.append((item, label))
            self.player_Custom = player_menu.AppendRadioItem(wx.ID_ANY, _("Custom Player..."))
            om.AppendSubMenu(player_menu, _("Media Player to Use"))
            self.audio_preference_item = om.Append(wx.ID_ANY, _("Preferred Audio Track..."))
            self.Bind(wx.EVT_MENU, self._show_audio_preference_dialog, self.audio_preference_item)
            # Language submenu (Windows/macOS)
            lang_menu = wx.Menu()
            self._lang_menu_items = {}
            for code, lbl in i18n.available_languages():
                disp = _("Automatic") if code == "auto" else lbl
                li = lang_menu.AppendRadioItem(wx.ID_ANY, disp)
                if i18n.get_language() == code:
                    li.Check(True)
                self._lang_menu_items[li.GetId()] = code
                self.Bind(wx.EVT_MENU, lambda evt, c=code: self._on_select_language(c), li)
            om.AppendSubMenu(lang_menu, _("Language"))
            self.min_to_tray_item = om.AppendCheckItem(wx.ID_ANY, _("Minimize to System Tray"))
            self.show_player_on_enter_item = om.AppendCheckItem(wx.ID_ANY, _("Show Player on Enter"))
            self.show_channel_url_item = om.AppendCheckItem(wx.ID_ANY, _("Show Stream URL"))
            self.auto_check_updates_item = om.AppendCheckItem(wx.ID_ANY, _("Auto-check for Updates"))
            mb.Append(om, _("Options"))
            # Recordings menu
            rm = wx.Menu()
            self._populate_recordings_menu(rm)
            mb.Append(rm, _("Recordings"))
            # Help menu
            hm = wx.Menu()
            # F1 is shown as the shortcut, but the app-wide char hook answers
            # F1 before this accelerator can, with the context topic; choosing
            # the item itself opens the guide at its beginning.
            self.user_guide_item = hm.Append(wx.ID_ANY, _("User Guide") + "\tF1")
            hm.AppendSeparator()
            self.check_updates_item = hm.Append(wx.ID_ANY, _("Check for Updates..."))
            self.open_logs_item = hm.Append(wx.ID_ANY, _("Open Logs Folder"))
            self.copy_diagnostic_item = hm.Append(wx.ID_ANY, _("Copy Log and Debug Information"))
            hm.AppendSeparator()
            m_about = hm.Append(wx.ID_ABOUT, _("About..."))
            mb.Append(hm, _("Help"))
            self.SetMenuBar(mb)
            # F1 on an open menu item opens the guide section about that item.
            # Whole menus first, then the items that have a section of their own.
            user_guide.set_menu_help(self, fm, "main-window")
            user_guide.set_menu_help(self, pm, "player-from-main-window")
            user_guide.set_menu_help(self, vm, "video-on-demand")
            user_guide.set_menu_help(self, om, "options")
            user_guide.set_menu_help(self, hm, "troubleshooting")
            user_guide.set_menu_help(self, m_mgr, "playlist-manager")
            user_guide.set_menu_help(self, m_epg, "epg-manager")
            user_guide.set_menu_help(self, m_imp, "import-epg")
            user_guide.set_menu_help(self, m_now, "whats-on-now")
            user_guide.set_menu_help(self, m_acct, "account-info")
            user_guide.set_menu_help(self, m_cast, "casting")
            user_guide.set_menu_help(self, pm_cast, "casting")
            user_guide.set_menu_help(self, self.favorite_menu_item, "favorites")
            user_guide.set_menu_help(self, self.goto_favorites_item, "favorites")
            user_guide.set_menu_help(self, self.show_downloads_item, "catch-up-downloads")
            user_guide.set_menu_help(self, player_menu, "media-player")
            user_guide.set_menu_help(self, self.audio_preference_item, "preferred-audio-track")
            user_guide.set_menu_help(self, lang_menu, "language")
            user_guide.set_menu_help(self, self.min_to_tray_item, "system-tray")
            user_guide.set_menu_help(self, self.auto_check_updates_item, "updates")
            user_guide.set_menu_help(self, self.user_guide_item, "using-help")
            user_guide.set_menu_help(self, self.check_updates_item, "updates")
            user_guide.set_menu_help(self, m_about, "support")
            self.Bind(wx.EVT_MENU, self.show_manager, m_mgr)
            self.Bind(wx.EVT_MENU, self.show_epg_manager, m_epg)
            self.Bind(wx.EVT_MENU, self.import_epg, m_imp)
            self.Bind(wx.EVT_MENU, self.show_whats_on_now, m_now)
            self.Bind(wx.EVT_MENU, self.show_account_info, m_acct)
            self.Bind(wx.EVT_MENU, self.show_cast_dialog, m_cast)
            self.Bind(wx.EVT_MENU, lambda _: self.Close(), m_exit)
            self.Bind(wx.EVT_MENU, self._menu_show_player, pm_show)
            self.Bind(wx.EVT_MENU, self._menu_toggle_player, pm_toggle)
            self.Bind(wx.EVT_MENU, self._menu_stop_player, pm_stop)
            self.Bind(wx.EVT_MENU, self._menu_cast_from_player, pm_cast)
            for item, key in self.player_menu_items:
                self.Bind(wx.EVT_MENU, lambda evt, attr=key: self._select_player(attr), item)
            self.Bind(wx.EVT_MENU, self._select_custom_player, self.player_Custom)
            self.Bind(wx.EVT_MENU, self.on_toggle_min_to_tray, self.min_to_tray_item)
            self.Bind(wx.EVT_MENU, self.on_toggle_show_player_on_enter, self.show_player_on_enter_item)
            self.Bind(wx.EVT_MENU, self.on_toggle_show_channel_url, self.show_channel_url_item)
            self.Bind(wx.EVT_MENU, self.on_toggle_auto_check_updates, self.auto_check_updates_item)
            self.Bind(wx.EVT_MENU, self.on_check_updates, self.check_updates_item)
            self.Bind(wx.EVT_MENU, self._open_logs_folder, self.open_logs_item)
            self.Bind(wx.EVT_MENU, self._copy_diagnostic_information, self.copy_diagnostic_item)
            self.Bind(wx.EVT_MENU, self._show_about_dialog, m_about)
            self.Bind(wx.EVT_MENU, self._on_user_guide_menu, self.user_guide_item)
            self.Bind(wx.EVT_MENU_OPEN, self.on_menu_open)
            self._sync_player_menu_from_config()
            self.min_to_tray_item.Check(self.minimize_to_tray)
            self.show_player_on_enter_item.Check(self.show_player_on_enter)
            self.show_channel_url_item.Check(self.show_channel_url)
            self.auto_check_updates_item.Check(self.auto_check_updates)

        self.group_list.Bind(wx.EVT_LEFT_UP, self._on_group_activated)
        self.filter_box.Bind(wx.EVT_TEXT_ENTER, lambda _: self.apply_filter())
        # Track re-focuses of the search box: stale async search results must
        # not yank focus back to the channel list while the user is editing a
        # new query (see the generation guard in apply_results).
        self._filter_focus_gen = 0
        self.filter_box.Bind(wx.EVT_SET_FOCUS, self._on_filter_focus)
        # Tab in the search box applies the filter, exactly like Enter, so a
        # screen-reader user can filter and move on without hunting for Enter.
        self.filter_box.Bind(wx.EVT_CHAR_HOOK, self._on_filter_char_hook)

        entries = [
            (wx.ACCEL_CTRL, ord('M'), 4001),
            (wx.ACCEL_CTRL, ord('E'), 4002),
            (wx.ACCEL_CTRL, ord('I'), 4003),
            (wx.ACCEL_CTRL, ord('Q'), 4004),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('P'), 4010),  # Play/Pause
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('S'), 4011),  # Stop
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('C'), 4012),  # Cast/connect
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('K'), 4013),  # Volume up
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('J'), 4014),  # Volume down
            (wx.ACCEL_CTRL, wx.WXK_UP, 4015),   # Volume up (Ctrl+Up)
            (wx.ACCEL_CTRL, wx.WXK_DOWN, 4016), # Volume down (Ctrl+Down)
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('R'), 4017),  # Start/stop recording
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('A'), 4018),  # Account info
            (wx.ACCEL_CTRL, ord('D'), 4019),  # Add/remove favorite
            # Show Downloads. Here as well as on the View menu: Windows skips a
            # menu accelerator whose item was greyed out when the menu last
            # opened, and that is exactly the state before a first download.
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('D'), 4020),
        ]
        atable = wx.AcceleratorTable(entries)
        self.SetAcceleratorTable(atable)
        self.Bind(wx.EVT_MENU, self.show_manager, id=4001)
        self.Bind(wx.EVT_MENU, self.show_epg_manager, id=4002)
        self.Bind(wx.EVT_MENU, self.import_epg, id=4003)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=4004)
        self.Bind(wx.EVT_MENU, self._menu_toggle_player, id=4010)
        self.Bind(wx.EVT_MENU, self._menu_stop_player, id=4011)
        self.Bind(wx.EVT_MENU, self._menu_cast_from_player, id=4012)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(+2), id=4013)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(-2), id=4014)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(+2), id=4015)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(-2), id=4016)
        self.Bind(wx.EVT_MENU, self._record_selected, id=4017)
        self.Bind(wx.EVT_MENU, self.show_account_info, id=4018)
        self.Bind(wx.EVT_MENU, self._toggle_favorite_selected, id=4019)
        self.Bind(wx.EVT_MENU, self._show_catchup_downloads, id=4020)

        # Intentionally do not event.Skip() to avoid duplicate handling.

    def _on_channel_key_down(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.play_selected(show_internal_player=self.show_player_on_enter)
            return  # swallow to prevent beep/focus issues
        if key in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE) and not event.HasAnyModifiers():
            if self._remove_favorite_selected():
                return
        event.Skip()

    def _remove_favorite_selected(self) -> bool:
        """Del: take the selected channel out of Favorites. False if it is not one."""
        channel = self._selected_channel()
        if not channel or not self._is_favorite(channel):
            return False
        self._toggle_favorite(channel)
        return True

    def _on_url_display_key(self, event):
        if event.GetKeyCode() == wx.WXK_TAB and event.ShiftDown():
            self.episode_description_field.SetFocus()
            return
        if event.GetKeyCode() == wx.WXK_TAB and not event.HasAnyModifiers():
            # Last control of the ring: hand Tab to normal traversal so it
            # wraps to the playlist-scope combo, which Shift+Tab undoes.
            self._navigate_forward(self.url_display)
            return
        event.Skip()

    def _on_episode_description_key(self, event):
        if event.GetKeyCode() == wx.WXK_TAB and event.ShiftDown():
            # Straight back to the channel the description belongs to. Going
            # to the stream-URL field instead was both the wrong direction
            # now that the description comes first, and a dead end whenever
            # the URL field is switched off: SetFocus on a hidden control
            # does nothing at all, so Shift+Tab simply stopped working.
            self.channel_list.SetFocus()
            return
        if event.GetKeyCode() == wx.WXK_TAB and not event.HasAnyModifiers():
            if self.show_channel_url:
                self.url_display.SetFocus()
            else:
                self._navigate_forward(self.episode_description_field)
            return
        event.Skip()

    @staticmethod
    def _navigate_forward(ctrl) -> None:
        """Hand Tab back to wx traversal from the last control in the ring."""
        ctrl.Navigate(wx.NavigationKeyEvent.IsForward
                      | wx.NavigationKeyEvent.FromTab)

    def _set_episode_description(self, text: str) -> None:
        """Update the Tab-reachable episode description field, when present.

        Empty descriptions get the shared "no description" placeholder so
        the field always reads as something deliberate, never silent.
        """
        field = getattr(self, "episode_description_field", None)
        if field is None:
            return
        text = (text or "").strip()
        if not text:
            text = _("No description available for this programme.")
        if field.GetValue() != text:
            field.SetValue(text)

    def _on_channel_context_menu(self, event):
        if not self.displayed:
            return
        pos = event.GetPosition()
        idx = self.channel_list.GetSelection()
        if pos != wx.DefaultPosition and not (pos.x == -1 and pos.y == -1):
            try:
                local = self.channel_list.ScreenToClient(pos)
                hit = self.channel_list.HitTest(local) if hasattr(self.channel_list, "HitTest") else (-1,)
                hit_idx = hit[0] if isinstance(hit, tuple) else hit
                if hit_idx not in (None, -1) and 0 <= hit_idx < len(self.displayed):
                    self.channel_list.SetSelection(hit_idx)
                    self.channel_list.SetFocus()
                    idx = hit_idx
            except Exception:
                LOG.debug("IPTVClient._on_channel_context_menu: ignored exception", exc_info=True)
        if idx == wx.NOT_FOUND and self.channel_list.GetCount():
            self.channel_list.SetSelection(0)
            idx = 0
        if idx == wx.NOT_FOUND or idx >= len(self.displayed):
            return
        item = self.displayed[idx]
        channel = None
        if item.get("type") == "channel":
            channel = item.get("data")
        elif item.get("type") == "epg":
            channel = self._find_channel_for_epg(item.get("data", {}))
        if not channel:
            return
        menu = wx.Menu()
        play_item = menu.Append(wx.ID_ANY, _("Play"))
        menu.Bind(wx.EVT_MENU, lambda evt: self.play_selected(), play_item)

        fav_item = menu.Append(wx.ID_ANY, self._favorite_action_label(channel))
        menu.Bind(wx.EVT_MENU, lambda evt, ch=channel: self._toggle_favorite(ch), fav_item)

        if self.recorder.is_recording(self._channel_record_key(channel)):
            rec_item = menu.Append(wx.ID_ANY, _("Stop Recording"))
        else:
            rec_item = menu.Append(wx.ID_ANY, _("Record"))
        menu.Bind(wx.EVT_MENU, lambda evt, ch=channel: self._record_channel(ch), rec_item)

        if item.get("type") == "epg":
            sched_item = menu.Append(wx.ID_ANY, _("Schedule Recording"))
            menu.Bind(
                wx.EVT_MENU,
                lambda evt, ch=channel, prog=item.get("data", {}): self._schedule_program_recording(ch, prog),
                sched_item,
            )
        elif not self._channel_is_epg_exempt(channel):
            # A channel row is just as useful a starting point as a search result:
            # open its upcoming guide so the user can choose the programme first.
            sched_item = menu.Append(wx.ID_ANY, _("Schedule Recording..."))
            menu.Bind(wx.EVT_MENU, lambda evt, ch=channel: self._schedule_channel_recording(ch), sched_item)

        if not self._channel_is_epg_exempt(channel):
            epg_item = menu.Append(wx.ID_ANY, _("View EPG..."))
            menu.Bind(wx.EVT_MENU, lambda evt, ch=channel: self._view_channel_epg(ch), epg_item)

        if self._channel_has_catchup(channel):
            catch_item = menu.Append(wx.ID_ANY, _("Catch-up"))
            menu.Bind(wx.EVT_MENU, lambda evt, ch=channel: self._open_catchup_dialog(ch), catch_item)
        try:
            self.channel_list.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _view_channel_epg(self, channel: Dict[str, str]):
        def fetch_and_show():
            try:
                db = EPGDatabase(get_db_path(), readonly=True)
                if getattr(db, "_missing_columns", None):
                    db.close()
                    wx.CallAfter(self._offer_epg_schema_repair)
                    return
                # From the programme on air now to as far as the guide goes.
                # Finished programmes belong to Catch-up; listed here they
                # only offered recordings that could never happen.
                now = datetime.datetime.now(datetime.timezone.utc)
                programmes = db.get_schedule(channel, now, now + _CHANNEL_EPG_HORIZON)
                db.close()
                
                wx.CallAfter(lambda: self._show_epg_dialog(channel, channel.get("name", ""), programmes))
            except Exception as e:
                wx.CallAfter(lambda err=e: message_box(_("Error fetching EPG: {error}").format(error=err), _("Error"), wx.OK | wx.ICON_ERROR))

        threading.Thread(target=fetch_and_show, daemon=True).start()

    def _offer_epg_schema_repair(self):
        """The EPG database predates this build's schema; offer to rebuild it.

        A read-only open cannot add missing columns, so an old database used
        to die with "no such column" in every EPG view until an import ran.
        One clear dialog with a working fix beats that.
        """
        answer = message_box(
            _("The EPG database was created by an older version and is missing "
              "newer fields. Import the guide again to update it?\n\n"
              "(Without this, the EPG views cannot show programme descriptions.)"),
            _("EPG Database Update Needed"), wx.YES_NO | wx.ICON_QUESTION)
        if answer != wx.YES:
            return
        # Was ``threading.Thread(target=self._refresh_epg)`` - a method that has
        # never existed, so accepting the repair raised AttributeError and did
        # nothing at all. The importer already owns its own worker thread.
        if not self.start_epg_import_background(force=True, notify=True):
            message_box(_("The EPG import could not be started."), _("Import Failed"),
                        wx.OK | wx.ICON_WARNING)

    def _schedule_channel_recording(self, channel: Dict[str, str]):
        """Let a channel-row user choose an upcoming EPG programme to record."""
        def fetch_and_show():
            try:
                db = EPGDatabase(get_db_path(), readonly=True)
                try:
                    now = datetime.datetime.now(datetime.timezone.utc)
                    programmes = db.get_schedule(channel, now, now + datetime.timedelta(days=7))
                finally:
                    db.close()
                wx.CallAfter(lambda: self._show_epg_dialog(
                    channel, self._channel_display_name(channel), programmes))
            except Exception as err:
                wx.CallAfter(lambda error=err: message_box(
                    _("Error fetching EPG: {error}").format(error=error),
                    _("Error"), wx.OK | wx.ICON_ERROR))

        threading.Thread(target=fetch_and_show, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Recording                                                          #
    # ------------------------------------------------------------------ #
    def _selected_channel(self) -> Optional[Dict[str, str]]:
        """Return the channel for the current list selection, or None."""
        i = self.channel_list.GetSelection()
        if not (0 <= i < len(self.displayed)):
            return None
        item = self.displayed[i]
        if item.get("type") == "channel":
            return item.get("data")
        if item.get("type") == "epg":
            return self._find_channel_for_epg(item.get("data", {}))
        return None

    def _channel_record_key(self, channel: Dict[str, str]) -> str:
        """Stable identity for a channel (the resolved stream URL can change per resolve)."""
        provider_data = channel.get("provider-data") or ""
        if isinstance(provider_data, dict):
            try:
                provider_data = json.dumps(provider_data, sort_keys=True, default=str)
            except Exception:
                provider_data = str(provider_data)
        parts = [
            channel.get("provider-type") or "",
            channel.get("provider-id") or "",
            channel.get("stream-id") or channel.get("stream_id") or "",
            channel.get("url") or "",
            provider_data or "",
            channel.get("name") or channel.get("tvg-name") or channel.get("tvg_name") or "",
        ]
        return "|".join(str(part) for part in parts if part)

    def _channel_display_name(self, channel: Dict[str, str]) -> str:
        return (channel.get("name")
                or channel.get("tvg-name")
                or channel.get("tvg_name")
                or channel.get("tvg-id")
                or channel.get("tvg_id")
                or _("IPTV Stream"))

    def _find_matching_channel_for_program(self, program: Dict[str, str]) -> Optional[Dict[str, str]]:
        """Find the playlist channel that best matches an EPG/search program row."""
        channel_name = program.get("channel_name", "")
        channel_id = program.get("channel_id", "")
        if not channel_name and not channel_id:
            return None

        matching_channel = None
        best_score = 0
        channel_name_lower = channel_name.lower() if channel_name else ""
        channel_name_norm = canonicalize_name(strip_noise_words(channel_name)) if channel_name else ""
        base_patterns = ["hd", "sd", "fhd", "uhd", "4k", "hevc", "h264", "h.264"]
        channel_base = channel_name_lower
        for pat in base_patterns:
            channel_base = channel_base.replace(" {pat}".format(pat=pat), "")
            channel_base = channel_base.replace("({pat})".format(pat=pat), "")
            channel_base = channel_base.replace("[{pat}]".format(pat=pat), "")
        channel_base = channel_base.strip()

        for ch in self.all_channels:
            ch_name = ch.get("name", "")
            ch_tvg_name = ch.get("tvg-name", "")
            ch_tvg_id = ch.get("tvg-id", "")
            ch_name_lower = ch_name.lower()
            score = 0

            if channel_id and ch_tvg_id:
                if channel_id.lower() == ch_tvg_id.lower():
                    score = 100
                elif channel_id.lower() in ch_tvg_id.lower() or ch_tvg_id.lower() in channel_id.lower():
                    score = max(score, 80)
            if ch_name_lower == channel_name_lower:
                score = max(score, 90)
            if ch_tvg_name and ch_tvg_name.lower() == channel_name_lower:
                score = max(score, 90)

            ch_name_norm = canonicalize_name(strip_noise_words(ch_name))
            ch_tvg_norm = canonicalize_name(strip_noise_words(ch_tvg_name)) if ch_tvg_name else ""
            if channel_name_norm and (ch_name_norm == channel_name_norm or ch_tvg_norm == channel_name_norm):
                score = max(score, 70)

            ch_base = ch_name_lower
            for pat in base_patterns:
                ch_base = ch_base.replace(" {pat}".format(pat=pat), "")
                ch_base = ch_base.replace("({pat})".format(pat=pat), "")
                ch_base = ch_base.replace("[{pat}]".format(pat=pat), "")
            ch_base = ch_base.strip()
            if channel_base and ch_base and channel_base == ch_base:
                score = max(score, 60)

            if channel_name_lower and (channel_name_lower in ch_name_lower or ch_name_lower in channel_name_lower):
                score = max(score, 40)
            if ch_tvg_name and channel_name_lower and (
                    channel_name_lower in ch_tvg_name.lower() or ch_tvg_name.lower() in channel_name_lower):
                score = max(score, 40)

            if channel_name_norm and ch_name_norm:
                words_epg = set(channel_name_norm.split())
                words_ch = set(ch_name_norm.split())
                if words_epg and words_ch:
                    overlap = len(words_epg & words_ch)
                    total = max(len(words_epg), len(words_ch))
                    if overlap > 0:
                        score = max(score, int(30 * overlap / total))

            if score > best_score:
                best_score = score
                matching_channel = ch

        if best_score < 30:
            return None
        return matching_channel

    def _recording_format_label(self, key: str) -> str:
        labels = {
            "provider_mkv": _("Provider quality (copy, MKV)"),
            "provider_mp4": _("Provider quality (copy, MP4)"),
            "x264_mkv": _("x264 re-encode (MKV)"),
            "x264_mp4": _("x264 re-encode (MP4)"),
            "audio_mp3_v0": _("Audio only (MP3 V0)"),
            "audio_flac": _("Audio only (FLAC)"),
            "audio_wav": _("Audio only (WAV)"),
            "audio_aac_m4a": _("Audio only (AAC, M4A)"),
            "audio_opus": _("Audio only (Opus)"),
        }
        return labels.get(key, labels[recorder.DEFAULT_RECORDING_FORMAT])

    def _schedule_window_label(self, job: Dict[str, object]) -> str:
        try:
            start_dt = datetime.datetime.fromtimestamp(float(job.get("start_ts") or 0), datetime.timezone.utc)
            stop_dt = datetime.datetime.fromtimestamp(float(job.get("stop_ts") or 0), datetime.timezone.utc)
            start_local = utc_to_local(start_dt)
            stop_local = utc_to_local(stop_dt)
            return "{start} - {end}".format(
                start=start_local.strftime("%Y-%m-%d %H:%M"),
                end=stop_local.strftime("%Y-%m-%d %H:%M"),
            )
        except Exception:
            return _("Unknown time")

    def _schedule_program_recording(self, channel: Dict[str, str], program: Dict[str, str]):
        if not channel:
            message_box(_("Could not identify the channel."), _("Schedule Recording"), wx.OK | wx.ICON_ERROR)
            return
        try:
            fmt = normalize_recording_format(self.config.get("recording_format"))
            job = dvr.build_job(
                channel,
                program,
                fmt,
                pre_padding_minutes=self.config.get("recording_pre_padding_minutes", 0),
                post_padding_minutes=self.config.get("recording_post_padding_minutes", 2),
            )
        except Exception as err:
            message_box(_("Could not schedule recording:\n{error}").format(error=err),
                          _("Schedule Recording"), wx.OK | wx.ICON_ERROR)
            return

        if float(job.get("stop_ts") or 0) <= time.time():
            message_box(_("This programme has already ended."), _("Schedule Recording"),
                          wx.OK | wx.ICON_INFORMATION)
            return

        duplicate = self._find_duplicate_scheduled_job(job)
        if duplicate:
            message_box(_("This programme is already scheduled to record."),
                          _("Schedule Recording"), wx.OK | wx.ICON_INFORMATION)
            return

        self._ensure_dvr_scheduler(start=True).add_job(job)
        message_box(
            _("Scheduled recording:\n{title}\n{time}").format(
                title=job.get("display_title") or job.get("title") or "",
                time=self._schedule_window_label(job),
            ),
            _("Schedule Recording"), wx.OK | wx.ICON_INFORMATION)

    def _schedule_epg_program_recording(self, program: Dict[str, str]):
        channel = self._find_matching_channel_for_program(program)
        if not channel:
            message_box(
                _("Could not find channel '{channel}' in your playlist.").format(
                    channel=program.get("channel_name", "")),
                _("Channel Not Found"),
                wx.OK | wx.ICON_WARNING,
            )
            return
        self._schedule_program_recording(channel, program)

    def _find_duplicate_scheduled_job(self, new_job: Dict[str, object]) -> Optional[Dict[str, object]]:
        new_channel = new_job.get("channel") if isinstance(new_job.get("channel"), dict) else {}
        new_key = self._channel_record_key(new_channel) if isinstance(new_channel, dict) else ""
        for job in self._ensure_dvr_scheduler().list_jobs(include_done=False):
            channel = job.get("channel") if isinstance(job.get("channel"), dict) else {}
            key = self._channel_record_key(channel) if isinstance(channel, dict) else ""
            if (key and key == new_key
                    and job.get("start_at") == new_job.get("start_at")
                    and job.get("end_at") == new_job.get("end_at")):
                return job
        return None

    def _show_scheduled_recordings(self, *_args):
        if self._dvr_dialog:
            try:
                self._dvr_dialog.refresh()
                self._dvr_dialog.Show()
                self._dvr_dialog.Raise()
                return
            except Exception:
                self._dvr_dialog = None
        self._dvr_dialog = ScheduledRecordingsDialog(self, self._ensure_dvr_scheduler(start=True))
        self._dvr_dialog.Show()

    def _on_dvr_schedule_updated(self):
        def refresh():
            dlg = getattr(self, "_dvr_dialog", None)
            if dlg:
                try:
                    dlg.refresh()
                except Exception:
                    LOG.debug("IPTVClient._on_dvr_schedule_updated.refresh: ignored exception", exc_info=True)
            # A canceled or completed job can be the last thing an armed shutdown
            # was waiting for.
            self._maybe_shutdown_after_recordings()
        wx.CallAfter(refresh)

    def _start_scheduled_recording(self, job: Dict[str, object]):
        channel = job.get("channel") if isinstance(job.get("channel"), dict) else {}
        if not channel:
            raise RuntimeError(_("Scheduled recording is missing channel data."))
        url = self._resolve_live_url(channel)
        if not url:
            raise RuntimeError(_("Could not find a stream URL for this channel."))
        fmt = normalize_recording_format(job.get("format"))
        out_dir = get_recordings_dir(self.config)
        headers = channel_http_headers(channel)
        # This runs on the scheduler's own thread, so the stream can be asked
        # here which audio tracks it carries. The player is not consulted from
        # off the UI thread: the channel's remembered track and the audio
        # preferences decide.
        choice = self._recording_audio_choice(
            url, headers, self._recording_audio_intent(channel, from_player=False))
        audio_track, audio_count = choice if choice else (None, 0)
        rec = self.recorder.start(
            url,
            str(job.get("display_title") or job.get("title") or self._channel_display_name(channel)),
            fmt,
            headers,
            out_dir,
            key="dvr:{id}".format(id=job.get("id")),
            metadata={"dvr_job_id": job.get("id")},
            on_finish=self._on_recording_finished,
            audio_track=audio_track,
            audio_track_count=audio_count,
        )
        self._note_recording_started()
        wx.CallAfter(
            message_box,
            _("Scheduled recording started:\n{title}").format(
                title=job.get("display_title") or job.get("title") or ""),
            _("Scheduled Recording"),
            wx.OK | wx.ICON_INFORMATION,
        )
        return rec

    def _stop_scheduled_recording(self, job: Dict[str, object]):
        rec_id = job.get("recording_id")
        if rec_id:
            try:
                self.recorder.stop(int(rec_id))
                return
            except Exception:
                LOG.debug("IPTVClient._stop_scheduled_recording: ignored exception", exc_info=True)
        self.recorder.stop_key("dvr:{id}".format(id=job.get("id")))

    def _cancel_scheduled_recording(self, job_id: str) -> bool:
        job = self._ensure_dvr_scheduler().get_job(job_id)
        if not job:
            return False
        if job.get("status") in {dvr.STATUS_RECORDING, dvr.STATUS_STOPPING}:
            self._stop_scheduled_recording(job)
        return self._ensure_dvr_scheduler(start=True).cancel_job(job_id)

    def _record_selected(self, *_args):
        channel = self._selected_channel()
        if not channel:
            message_box(_("Select a channel to record first."), _("Record"),
                          wx.OK | wx.ICON_INFORMATION)
            return
        self._record_channel(channel)

    def _record_channel(self, channel: Dict[str, str]):
        key = self._channel_record_key(channel)
        pending = getattr(self, "_pending_recording_starts", None)
        if pending is None:
            pending = self._pending_recording_starts = set()
        if key in pending:
            # Pressed again while the stream is still being asked for its
            # audio tracks: the toggle's "stop", just before it started.
            pending.discard(key)
            message_box(_("Stopping recording for {name}...").format(
                name=self._channel_display_name(channel)),
                _("Recording"), wx.OK | wx.ICON_INFORMATION)
            return
        # Toggle: if this channel is already recording, stop it instead.
        if self.recorder.is_recording(key):
            self._stop_recording_for_channel(channel)
            return
        try:
            url = self._resolve_live_url(channel)
        except ProviderError as err:
            message_box(_("Provider error: {error}").format(error=err),
                          _("Recording Error"), wx.OK | wx.ICON_ERROR)
            return
        except Exception as err:
            message_box(_("Could not resolve stream URL:\n{error}").format(error=err),
                          _("Recording Error"), wx.OK | wx.ICON_ERROR)
            return
        if not url:
            message_box(_("Could not find a stream URL for this channel."),
                          _("Recording Error"), wx.OK | wx.ICON_WARNING)
            return

        headers = channel_http_headers(channel)
        name = self._channel_display_name(channel)
        fmt = normalize_recording_format(self.config.get("recording_format"))
        out_dir = get_recordings_dir(self.config)
        intent = self._recording_audio_intent(channel)
        # Recording the channel the built-in player is showing takes one
        # provider connection, not two (issue #13): the player lets go of the
        # stream, the recording opens it, and the player then watches the
        # recording's own copy of it through a local relay.
        share = self._player_is_showing(channel)
        player_shown = False
        if share:
            frame = self._internal_player_frame
            try:
                player_shown = bool(frame.IsShown())
            except Exception:
                player_shown = False
            frame.stop(manual=True)
        if intent is None and not share:
            self._start_live_recording(key, url, name, fmt, headers, out_dir, None)
            return
        # Waiting for the provider, and keeping the right audio track (asking
        # the stream which tracks it carries), are network work: off the UI
        # thread, then back here.
        pending.add(key)

        def probe():
            if share:
                # The provider still counts the player's connection for a moment.
                catchup_direct.settle_media_session()
            choice = self._recording_audio_choice(url, headers, intent) if intent else None
            if share and intent:
                catchup_direct.settle_media_session()  # ...and the track probe's
            wx.CallAfter(finish, choice)

        def finish(choice):
            if key not in pending:
                # Record was pressed again: canceled before it began.
                if share:
                    self._resume_direct_playback(channel, player_shown)
                return
            pending.discard(key)
            self._start_live_recording(key, url, name, fmt, headers, out_dir, choice,
                                       share_with=channel if share else None,
                                       player_shown=player_shown)
            self._sync_internal_player_record_state()

        threading.Thread(target=probe, daemon=True).start()

    def _start_live_recording(self, key, url, name, fmt, headers, out_dir, audio_choice,
                              share_with=None, player_shown=False):
        """UI thread: start one live recording and say where it is going.

        ``share_with`` is the channel the built-in player was showing: the
        player then watches this recording's copy of the stream instead of
        keeping a second connection to the provider open.
        """
        audio_track, audio_count = audio_choice if audio_choice else (None, 0)
        try:
            rec = self.recorder.start(
                url, name, fmt, headers, out_dir,
                key=key, on_finish=self._on_recording_finished,
                audio_track=audio_track, audio_track_count=audio_count,
                share_with_player=share_with is not None,
            )
        except Exception as err:
            message_box(_("Could not start recording:\n{error}").format(error=err),
                          _("Recording Error"), wx.OK | wx.ICON_ERROR)
            if share_with is not None:
                self._resume_direct_playback(share_with, player_shown)
            return
        relay = getattr(rec, "relay", None)
        if share_with is not None and relay is not None:
            shared = getattr(self, "_shared_recordings", None)
            if shared is None:
                shared = self._shared_recordings = {}
            shared[rec.id] = {"channel": share_with, "url": relay.url, "shown": player_shown}
            self._launch_stream(relay.url, name, stream_kind="live", channel=share_with,
                                show_internal_player=player_shown, focus_player=False)
        self._note_recording_started()
        message_box(
            _("Recording started ({fmt}):\n{path}").format(
                fmt=self._recording_format_label(fmt), path=rec.out_path),
            _("Recording"), wx.OK | wx.ICON_INFORMATION)

    def _player_is_showing(self, channel: Dict[str, str]) -> bool:
        """True while the built-in player is playing this live channel."""
        current = getattr(self, "_internal_player_channel", None)
        if (not current or not channel
                or getattr(self, "_internal_player_stream_kind", "live") != "live"
                or not self._internal_player_has_media()):
            return False
        caster = getattr(self, "caster", None)
        if caster is not None and caster.is_connected():
            return False
        return self._channel_record_key(current) == self._channel_record_key(channel)

    def _end_shared_playback(self, shared: Dict[str, object]) -> None:
        """UI thread: the recording the player was watching through has ended.

        Back to the provider directly - once the recording's own connection
        has been released, and only if the player is still on that recording
        (the user may have stopped it or moved on to something else).
        """
        frame = getattr(self, "_internal_player_frame", None)
        if (frame is None or getattr(frame, "_destroyed", False)
                or getattr(frame, "_current_url", None) != shared["url"]
                or getattr(frame, "_manual_stop", False)):
            return
        frame.stop(manual=True)

        def resume():
            catchup_direct.settle_media_session()
            wx.CallAfter(self._resume_direct_playback, shared["channel"],
                         shared["shown"], shared["url"])

        threading.Thread(target=resume, daemon=True).start()

    def _resume_direct_playback(self, channel: Dict[str, str], shown: bool,
                                expected_url: Optional[str] = None) -> None:
        """UI thread: play ``channel`` straight from the provider again."""
        frame = getattr(self, "_internal_player_frame", None)
        if (frame is None or getattr(frame, "_destroyed", False)
                or getattr(self, "_suppress_recording_notifications", False)):
            return
        if expected_url is not None and getattr(frame, "_current_url", None) != expected_url:
            return  # something else was started meanwhile
        try:
            url = self._resolve_live_url(channel)
        except Exception:
            LOG.debug("IPTVClient._resume_direct_playback: could not resolve", exc_info=True)
            return
        if url:
            self._launch_stream(url, self._channel_display_name(channel), stream_kind="live",
                                channel=channel, show_internal_player=shown,
                                focus_player=False)

    def _recording_audio_intent(self, channel: Dict[str, str], *, from_player: bool = True):
        """How a recording of ``channel`` picks its audio track, or None.

        The built-in player showing this channel is the best witness: the track
        it is playing is the one the user is listening to, audio description
        or not. Otherwise the player's own rules apply - the track remembered
        for the channel, the audio-description preference, then the preferred
        tracks. None when nothing asks for a particular track, which leaves the
        choice to ffmpeg as before. ``from_player`` is False off the UI thread,
        where the player must not be touched.
        """
        key = self._channel_audio_key(channel)
        frame = getattr(self, "_internal_player_frame", None)
        if (from_player and frame is not None and key
                and key == getattr(self, "_internal_player_audio_key", "")
                and self._internal_player_has_media()):
            try:
                tracks = frame._get_audio_tracks()
                if tracks:
                    index = active_audio_track_index(
                        tracks, frame._current_audio_track_id(),
                        getattr(frame, "_wanted_audio_track_name", ""))
                    name = tracks[index][1]
                    described = names_audio_description(name)
                    # libVLC and ffmpeg name tracks differently, so the name
                    # rarely matches; the position does, and a described track
                    # is found by its flag even where the position differs.
                    return {"keywords": (["audio description"] if described else []) + [name],
                            "fallback_index": index, "prefer_ad": described}
            except Exception:
                LOG.debug("IPTVClient._recording_audio_intent: ignored exception", exc_info=True)
        prefer_ad = self._bool_pref(self.config.get("prefer_audio_description", False))
        keywords = ordered_preference_keywords(
            self._remembered_channel_audio_track(key),
            prefer_audio_description=prefer_ad,
            last_manual=self.config.get("last_audio_track") or "",
            preferred=self.config.get("preferred_audio_tracks") or [],
        )
        fallback = self._remembered_channel_audio_track_index(key)
        if not keywords and fallback is None:
            return None
        return {"keywords": keywords, "fallback_index": fallback, "prefer_ad": prefer_ad}

    @staticmethod
    def _recording_audio_choice(url, headers, intent):
        """Worker thread: (track to keep, tracks in the stream), or None.

        None - keep ffmpeg's own pick - when nothing asks for a track, when the
        stream cannot be asked, or when no track matches.
        """
        if not intent:
            return None
        fetch_url, url_headers = split_stream_modifiers(url)
        streams = probe_audio_streams(fetch_url, merge_headers(headers, url_headers))
        if not streams:
            return None
        labels = [audio_stream_label(position, stream) for position, stream in enumerate(streams)]
        index = select_preferred_audio_track(
            list(enumerate(labels)), intent.get("keywords") or [],
            fallback_index=intent.get("fallback_index"),
            prefer_ad=bool(intent.get("prefer_ad")))
        LOG.info("Recording audio tracks %s; keeping %s", labels,
                 "ffmpeg's default" if index is None else labels[index])
        if index is None:
            return None
        return index, len(streams)

    def _stop_recording_for_channel(self, channel: Dict[str, str]):
        key = self._channel_record_key(channel)
        if self.recorder.stop_key(key):
            message_box(_("Stopping recording for {name}...").format(
                name=self._channel_display_name(channel)),
                _("Recording"), wx.OK | wx.ICON_INFORMATION)
        else:
            message_box(_("This channel is not currently recording."),
                          _("Recording"), wx.OK | wx.ICON_INFORMATION)

    def _stop_selected_recording(self, *_args):
        channel = self._selected_channel()
        if channel and self.recorder.is_recording(self._channel_record_key(channel)):
            self._stop_recording_for_channel(channel)
            return
        # Fall back: if exactly one recording is active, stop it.
        active = self.recorder.list_active()
        if len(active) == 1:
            self.recorder.stop(active[0].id)
            message_box(_("Stopping recording..."), _("Recording"), wx.OK | wx.ICON_INFORMATION)
        elif not active:
            message_box(_("No recordings are currently active."),
                          _("Recording"), wx.OK | wx.ICON_INFORMATION)
        else:
            self._stop_all_recordings()

    def _stop_all_recordings(self, *_args):
        count = self.recorder.stop_all()
        if count:
            message_box(_("Stopping {count} recording(s)...").format(count=count),
                          _("Recording"), wx.OK | wx.ICON_INFORMATION)
        else:
            message_box(_("No recordings are currently active."),
                          _("Recording"), wx.OK | wx.ICON_INFORMATION)

    # ------------------------------------------------------------------ #
    # Shut down the computer when recording is finished                  #
    # ------------------------------------------------------------------ #
    def _set_shutdown_after_recordings(self, enabled: bool):
        self._shutdown_after_recordings = bool(enabled)
        self.config["shutdown_after_recordings"] = self._shutdown_after_recordings
        save_config(self.config)
        item = getattr(self, "_shutdown_after_item", None)
        if item is not None:
            try:
                item.Check(self._shutdown_after_recordings)
            except Exception:
                LOG.debug("IPTVClient._set_shutdown_after_recordings: ignored exception", exc_info=True)
        if not self._shutdown_after_recordings:
            self._recorded_since_shutdown_armed = False
            return
        # Switching this on while something is already recording or queued means
        # that work is what we wait for. Switching it on with nothing running waits
        # for the next recording to start, so the machine does not power off now.
        scheduler = getattr(self, "dvr_scheduler", None)
        jobs = scheduler.list_jobs(include_done=False) if scheduler is not None else []
        self._recorded_since_shutdown_armed = bool(
            self.recorder.list_active() or power.pending_job_count(jobs))

    def _on_toggle_shutdown_after_recordings(self, event):
        item = getattr(self, "_shutdown_after_item", None)
        if platform.system() == "Linux":
            # The Linux menu is a popup that is rebuilt on every open, and its check
            # item has no dependable state by the time this runs -- the same reason
            # on_toggle_min_to_tray branches on the platform instead of reading it.
            wanted = not self._shutdown_after_recordings
        else:
            try:
                wanted = bool(item.IsChecked()) if item is not None else not self._shutdown_after_recordings
            except Exception:
                LOG.debug("IPTVClient._on_toggle_shutdown_after_recordings: ignored exception", exc_info=True)
                wanted = not self._shutdown_after_recordings
        if wanted:
            answer = message_box(
                _("The computer will shut down once every recording that is running "
                  "or still scheduled has finished.\n\n"
                  "You get a countdown you can cancel first, and this setting turns "
                  "itself off again as soon as it has been used.\n\n"
                  "Shut down the computer when recordings finish?"),
                _("Shut Down After Recordings"), wx.YES_NO | wx.ICON_QUESTION)
            if answer != wx.YES:
                if item is not None:
                    try:
                        item.Check(False)
                    except Exception:
                        LOG.debug("IPTVClient._on_toggle_shutdown_after_recordings: ignored exception",
                                  exc_info=True)
                return
        self._set_shutdown_after_recordings(wanted)

    def _note_recording_started(self):
        """Record that there is now something for an armed shutdown to wait for."""
        if self._shutdown_after_recordings:
            self._recorded_since_shutdown_armed = True

    def _maybe_shutdown_after_recordings(self):
        """Start the shutdown countdown if nothing is recording or queued."""
        if not self._shutdown_after_recordings or self._shutdown_dialog is not None:
            return
        if getattr(self, "_suppress_recording_notifications", False):
            return  # the app is exiting; that is not what this option is for
        scheduler = getattr(self, "dvr_scheduler", None)
        jobs = scheduler.list_jobs(include_done=False) if scheduler is not None else []
        if not power.should_shutdown(
            armed=self._shutdown_after_recordings,
            recorded_something=self._recorded_since_shutdown_armed,
            active_recordings=len(self.recorder.list_active()),
            pending_jobs=power.pending_job_count(jobs),
        ):
            return
        self._begin_shutdown_countdown()

    def _begin_shutdown_countdown(self):
        LOG.info("Recordings finished; starting the shutdown countdown")
        # No parent: the main window may well be minimized to the tray at this
        # point, and a dialog owned by a hidden window never appears.
        self._shutdown_dialog = ShutdownCountdownDialog(
            None,
            on_cancel=self._cancel_pending_shutdown,
            on_shutdown=self._shutdown_computer_now,
        )
        self._shutdown_dialog.Show()
        self._shutdown_dialog.Raise()

    def _destroy_shutdown_dialog(self):
        dlg, self._shutdown_dialog = self._shutdown_dialog, None
        if dlg is None:
            return
        try:
            dlg.Destroy()
        except Exception:
            LOG.debug("IPTVClient._destroy_shutdown_dialog: ignored exception", exc_info=True)

    def _cancel_pending_shutdown(self):
        self._destroy_shutdown_dialog()
        # The option goes off with the cancel: leaving it armed would spring the
        # same countdown on the user again at the end of the next recording.
        self._set_shutdown_after_recordings(False)
        message_box(
            _("Shutdown canceled. Automatic shutdown after recordings is now off."),
            _("Shut Down After Recordings"), wx.OK | wx.ICON_INFORMATION)

    def _shutdown_computer_now(self):
        self._destroy_shutdown_dialog()
        self._set_shutdown_after_recordings(False)
        try:
            power.shutdown_computer()
        except Exception as err:
            message_box(
                _("Could not shut down the computer:\n{error}").format(error=err),
                _("Shut Down After Recordings"), wx.OK | wx.ICON_ERROR)
            return
        # Close through our own handler so the tray icon, scheduler and any
        # finalizing ffmpeg are dealt with properly rather than being cut off.
        self._exit_forced = True
        wx.CallAfter(self.Close, True)

    def _release_recordings_on_exit(self):
        """Stop every recording for shutdown without truncating the output files.

        ffmpeg is asked to quit and then left alone: finalizing a large MP4 means
        rewriting the whole file to move the moov atom to the front, which takes far
        longer than a window close should block for, and killing it partway through
        is what leaves an unplayable recording. ffmpeg is a separate process and
        finishes on its own. Anything it was told to do is therefore recorded here,
        because nothing will be left running to report it afterwards.
        """
        self._suppress_recording_notifications = True
        active = self.recorder.list_active()
        self.recorder.stop_all(wait=True, detach=True)
        scheduler = getattr(self, "dvr_scheduler", None)
        if scheduler is None:
            return
        for rec in active:
            try:
                job_id = rec.metadata.get("dvr_job_id")
            except Exception:
                job_id = None
            if not job_id:
                continue
            note = ("Stopped because the app exited; ffmpeg was left to finish writing "
                    "the file." if rec.detached else "Stopped because the app exited.")
            try:
                scheduler.mark_finished(str(job_id), success=False,
                                        output_path=rec.out_path, message=note)
            except Exception:
                LOG.debug("IPTVClient._release_recordings_on_exit: ignored exception",
                          exc_info=True)

    # -------------------------------------------------------------- #
    # Modal-box-safe notifications                                    #
    #                                                                #
    # Recording finish callbacks fire from the recorder's watcher
    # thread via wx.CallAfter, so they can land while the user is
    # still reading the "Stopping recording..." box. A second
    # wx.MessageBox opened inside a modal box's message loop
    # desynchronizes wxMSW's parent-enable bookkeeping and leaves the
    # main frame permanently disabled ("unavailable" to NVDA, dead to
    # Alt+F4 and Escape). So: never open a notification box while a
    # modal box is up - queue it and show it once the modal closes.
    # -------------------------------------------------------------- #
    _DEFERRED_NOTIFICATION_LIMIT = 8

    def _deferred_notifications(self) -> List[Tuple[str, str, int]]:
        # Must return the *stored* list, not a fresh default: callers append
        # to the return value, so a new default each call would drop entries.
        queue = getattr(self, "_deferred_notification_queue", None)
        if queue is None:
            queue = []
            self._deferred_notification_queue = queue
        return queue

    def _modal_box_is_open(self) -> bool:
        """True while any wx message box is showing in this app."""
        return bool(getattr(self, "_modal_box_depth", 0)) or modal_box_is_open()

    def _show_or_queue_message_box(self, message: str, caption: str, style: int) -> None:
        """Show a wx.MessageBox now, or queue it while a modal box is open."""
        if self._modal_box_is_open():
            queue = self._deferred_notifications()
            if len(queue) < self._DEFERRED_NOTIFICATION_LIMIT:
                queue.append((message, caption, style))
            else:
                LOG.warning("Dropping deferred notification %r: queue full", caption)
            return
        self._show_message_box(message, caption, style)

    def _show_message_box(self, message: str, caption: str, style: int) -> None:
        """Open a wx.MessageBox, tracking the modal depth it creates."""
        depth = getattr(self, "_modal_box_depth", 0)
        self._modal_box_depth = depth + 1
        try:
            message_box(message, caption, style, parent=self.frame if hasattr(self, "frame") else None)
        finally:
            self._modal_box_depth = depth

    def _drain_deferred_notifications(self) -> None:
        """Show notifications queued while a modal box was open (FIFO)."""
        queue = self._deferred_notifications()
        while queue and not self._modal_box_is_open():
            message, caption, style = queue.pop(0)
            self._show_message_box(message, caption, style)

    def _report_recording_saved(self, rec) -> None:
        """Recording finished cleanly: notify, or queue the box if one is up."""
        self._show_or_queue_message_box(
            _("Recording saved:\n{path}").format(path=rec.out_path),
            _("Recording Complete"), wx.OK | wx.ICON_INFORMATION)

    def _report_recording_warning(self, rec, rc: int) -> None:
        self._show_or_queue_message_box(
            _("Recording stopped, but ffmpeg reported code {code}.\n\n{detail}\n\nFile:\n{path}").format(
                code=rc, detail=self._recording_failure_detail(rec), path=rec.out_path),
            _("Recording Warning"), wx.OK | wx.ICON_WARNING)

    def _report_recording_error(self, rec, rc: int) -> None:
        self._show_or_queue_message_box(
            _("Recording of {name} ended unexpectedly (code {code}).\n\n{detail}").format(
                name=rec.title, code=rc, detail=self._recording_failure_detail(rec)),
            _("Recording Error"), wx.OK | wx.ICON_ERROR)

    def _on_recording_finished(self, rec, rc):
        job_id = None
        try:
            job_id = rec.metadata.get("dvr_job_id")
        except Exception:
            job_id = None
        if job_id:
            detail = "\n".join(rec.stderr_tail[-6:])
            suppressed = getattr(self, "_suppress_recording_notifications", False)
            self._ensure_dvr_scheduler(start=True).mark_finished(
                str(job_id),
                success=(rc == 0 and not suppressed),
                output_path=rec.out_path,
                message=("Stopped because the app exited." if suppressed else (detail if rc else "")),
            )
        if getattr(self, "_suppress_recording_notifications", False):
            return
        shared = (getattr(self, "_shared_recordings", None) or {}).pop(rec.id, None)
        if shared:
            # The player was watching this recording's copy of the stream.
            wx.CallAfter(self._end_shared_playback, shared)
        # Called from the recorder's watcher thread, so the check has to be
        # marshalled onto the UI thread like the report below.
        wx.CallAfter(self._maybe_shutdown_after_recordings)

        wx.CallAfter(self._sync_internal_player_record_state)

        def report():
            if rc == 0:
                self._report_recording_saved(rec)
            elif rec.stopped_by_user:
                self._report_recording_warning(rec, rc)
            else:
                self._report_recording_error(rec, rc)
            self._drain_deferred_notifications()
        wx.CallAfter(report)

    def _recording_failure_detail(self, rec) -> str:
        """What ffmpeg said, plus where the rest of what it said was written."""
        lines = list(rec.stderr_tail[-6:]) or [_("No ffmpeg details were reported.")]
        log_path = getattr(rec, "log_path", "")
        if log_path and os.path.exists(log_path):
            lines.append("")
            lines.append(_("Full ffmpeg log:\n{path}").format(path=log_path))
        return "\n".join(lines)

    def _set_recording_format(self, key: str):
        self.config["recording_format"] = normalize_recording_format(key)
        save_config(self.config)

    def _open_recordings_folder(self, *_args):
        path = get_recordings_dir(self.config)
        try:
            if platform.system() == "Windows":
                os.startfile(path)  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as err:
            message_box(_("Could not open folder:\n{error}").format(error=err),
                          _("Recordings"), wx.OK | wx.ICON_ERROR)

    def _open_logs_folder(self, *_args):
        path = get_logs_dir()
        try:
            if platform.system() == "Windows":
                os.startfile(path)  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as err:
            message_box(_("Could not open folder:\n{error}").format(error=err),
                          _("Logs"), wx.OK | wx.ICON_ERROR)

    @staticmethod
    def _read_diagnostic_log_tail(path: str, max_bytes: int = 131072) -> str:
        """Read a bounded tail so copying diagnostics cannot freeze the UI."""
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - max_bytes))
                return handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _copy_diagnostic_information(self, *_args):
        """Copy useful, privacy-safe diagnostics that can be sent to the developer."""
        from app_meta import APP_DISPLAY_NAME, APP_VERSION

        log_path = get_epg_log_path()
        lines = [
            "{name} {version}".format(name=APP_DISPLAY_NAME, version=APP_VERSION),
            _("Platform: {platform}").format(platform=sys.platform),
            _("Python: {version}").format(version=sys.version.split()[0]),
            _("wxPython: {version}").format(version=wx.version()),
            _("EPG enabled: {enabled}").format(enabled=bool(self.config.get("epg_enabled", True))),
            _("Configured playlists: {count}").format(count=len(self.config.get("playlists", []))),
            _("Active recordings: {count}").format(count=len(self.recorder.list_active())),
            "",
            _("EPG debug log (latest 128 KiB):"),
        ]
        tail = self._read_diagnostic_log_tail(log_path)
        lines.append(tail or _("(No EPG debug log has been written yet.)"))
        # Deliberately verbatim: stream URLs and provider credentials stay in the
        # report so the person receiving it can reproduce and diagnose the fault.
        report = "\n".join(lines)
        try:
            if not wx.TheClipboard.Open():
                raise RuntimeError(_("The clipboard is unavailable."))
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(report))
            finally:
                wx.TheClipboard.Close()
        except Exception as err:
            message_box(_("Could not copy diagnostic information:\n{error}").format(error=err),
                          _("Diagnostic Information"), wx.OK | wx.ICON_ERROR)
            return
        message_box(_("Diagnostic information was copied to the clipboard. You can paste it into a message to the developer."),
                      _("Diagnostic Information"), wx.OK | wx.ICON_INFORMATION)

    def _choose_recordings_folder(self, *_args):
        current = get_recordings_dir(self.config)
        dlg = wx.DirDialog(self, _("Set download folder"), defaultPath=current)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                self.config["recordings_dir"] = dlg.GetPath()
                save_config(self.config)
        finally:
            dlg.Destroy()

    def _build_recording_format_menu(self) -> wx.Menu:
        """A submenu of radio items for each recording preset (checked = active)."""
        current = normalize_recording_format(self.config.get("recording_format"))
        fmt_menu = wx.Menu()
        for key in RECORDING_FORMATS:
            item = fmt_menu.AppendRadioItem(wx.ID_ANY, self._recording_format_label(key))
            if key == current:
                item.Check(True)
            fmt_menu.Bind(wx.EVT_MENU, lambda evt, k=key: self._set_recording_format(k), item)
        return fmt_menu

    def _show_recording_padding_dialog(self, _event=None):
        """Let the user set the lead-in/lead-out used for scheduled programmes."""
        dlg = RecordingPaddingDialog(
            self,
            before_minutes=self.config.get("recording_pre_padding_minutes", 0),
            after_minutes=self.config.get("recording_post_padding_minutes", 2),
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            before, after = dlg.get_padding()
            self.config["recording_pre_padding_minutes"] = before
            self.config["recording_post_padding_minutes"] = after
            # save_config normalizes the values as well, protecting against an
            # edited config or a future caller bypassing this dialog.
            save_config(self.config)
        finally:
            dlg.Destroy()

    def _populate_recordings_menu(self, menu: wx.Menu):
        """Fill a Recordings menu (shared by the menubar and the Linux button menu)."""
        start_item = menu.Append(wx.ID_ANY, _("Start Recording") + "\tCtrl+Shift+R")
        menu.Bind(wx.EVT_MENU, self._record_selected, start_item)
        stop_item = menu.Append(wx.ID_ANY, _("Stop Recording"))
        menu.Bind(wx.EVT_MENU, self._stop_selected_recording, stop_item)
        stop_all_item = menu.Append(wx.ID_ANY, _("Stop All Recordings"))
        menu.Bind(wx.EVT_MENU, self._stop_all_recordings, stop_all_item)
        menu.AppendSeparator()
        schedule_item = menu.Append(wx.ID_ANY, _("Scheduled Recordings..."))
        menu.Bind(wx.EVT_MENU, self._show_scheduled_recordings, schedule_item)
        menu.AppendSeparator()
        format_menu = self._build_recording_format_menu()
        menu.AppendSubMenu(format_menu, _("Recording Format"))
        padding_item = menu.Append(wx.ID_ANY, _("Schedule Padding..."))
        menu.Bind(wx.EVT_MENU, self._show_recording_padding_dialog, padding_item)
        menu.AppendSeparator()
        open_item = menu.Append(wx.ID_ANY, _("Open Recordings Folder"))
        menu.Bind(wx.EVT_MENU, self._open_recordings_folder, open_item)
        folder_item = menu.Append(wx.ID_ANY, _("Set Download Folder..."))
        menu.Bind(wx.EVT_MENU, self._choose_recordings_folder, folder_item)
        menu.AppendSeparator()
        self._shutdown_after_item = menu.AppendCheckItem(
            wx.ID_ANY, _("Shut Down the Computer When Recordings Finish"))
        self._shutdown_after_item.Check(self._shutdown_after_recordings)
        menu.Bind(wx.EVT_MENU, self._on_toggle_shutdown_after_recordings, self._shutdown_after_item)
        user_guide.set_menu_help(self, menu, "recordings")
        user_guide.set_menu_help(self, format_menu, "recording-formats")
        user_guide.set_menu_help(self, schedule_item, "scheduled-recordings")
        user_guide.set_menu_help(self, padding_item, "schedule-padding")
        user_guide.set_menu_help(self, self._shutdown_after_item, "shutdown-after-recordings")
        self._recording_menu_items = (start_item, stop_item, stop_all_item)
        self._update_recording_menu_state()

    def _update_recording_menu_state(self):
        """Keep recording commands honest for the selected channel's live state."""
        # getattr rather than a direct call: the non-GUI test doubles that stand
        # in for the frame only supply the recorder and the menu items.
        sync = getattr(self, "_sync_internal_player_record_state", None)
        if callable(sync):
            sync()
        items = getattr(self, "_recording_menu_items", ())
        if len(items) != 3:
            return
        channel = self._selected_channel()
        is_recording = bool(channel and self.recorder.is_recording(self._channel_record_key(channel)))
        try:
            items[0].Enable(bool(channel) and not is_recording)
            items[1].Enable(is_recording)
            items[2].Enable(self.recorder.has_active())
        except Exception:
            LOG.debug("IPTVClient._update_recording_menu_state: ignored exception", exc_info=True)

    def _on_user_guide_menu(self, _event=None):
        """Help > User Guide: the guide from its beginning.

        F1 is the item's accelerator too. The app-wide char hook normally takes
        F1 first and opens the context topic; should a control swallow the key
        and let the accelerator fire instead, F1 is still held down right now.
        """
        if wx.GetKeyState(wx.WXK_F1):
            request_context_help(wx.Window.FindFocus())
            return
        show_user_guide(self, user_guide.DEFAULT_TOPIC)

    def _list_help_topic(self, live_topic: str) -> str:
        """F1 topic for the category and channel lists, which also browse VOD."""
        return "video-on-demand" if getattr(self, "view_mode", "live") == "vod" else live_topic

    def _show_about_dialog(self, _event=None):
        """Show the accessible, keyboard-navigable About dialog."""
        dlg = AccessibleAboutDialog(self)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _show_epg_dialog(self, channel, channel_name, programmes):
        if not programmes:
            message_box(_("No upcoming schedule found for this channel."), _("EPG"), wx.OK | wx.ICON_INFORMATION)
            return
        try:
            dlg = ChannelEPGDialog(self, channel_name, programmes, schedule_callback=self._schedule_program_recording, channel=channel)
        except Exception:
            # This runs inside a wx.CallAfter from the fetch thread, so an
            # exception here would otherwise vanish silently: the View EPG
            # item appears to do nothing at all. Surface it instead.
            LOG.exception("ChannelEPGDialog failed to build for %s", channel_name)
            message_box(
                _("Could not open the EPG window: {error}").format(error=sys.exc_info()[1]),
                _("Error"), wx.OK | wx.ICON_ERROR)
            return
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def on_toggle_min_to_tray(self, event):
        if platform.system() == "Linux":
            self.minimize_to_tray = not self.minimize_to_tray
        else:
            self.minimize_to_tray = self.min_to_tray_item.IsChecked()
        self.config["minimize_to_tray"] = self.minimize_to_tray
        save_config(self.config)

    def _apply_channel_url_visibility(self) -> None:
        """Show or hide the stream-URL field and re-lay-out its column.

        Hiding it also takes it out of tab traversal, which is the point: with
        the field off the episode description is the last control in the ring,
        and Tab from it wraps to the top instead of landing on a URL nobody
        asked to see.
        """
        ctrl = getattr(self, "url_display", None)
        if ctrl is None:
            return
        try:
            ctrl.Show(bool(self.show_channel_url))
            parent = ctrl.GetParent()
            if parent is not None:
                parent.Layout()
        except Exception:
            LOG.debug("IPTVClient._apply_channel_url_visibility: ignored exception", exc_info=True)

    def on_toggle_show_channel_url(self, event):
        self.show_channel_url = event.IsChecked()
        self.config["show_channel_url"] = self.show_channel_url
        save_config(self.config)
        self._apply_channel_url_visibility()
        if self.show_channel_url:
            self.on_highlight()

    def on_toggle_show_player_on_enter(self, event):
        self.show_player_on_enter = event.IsChecked()
        self.config["show_player_on_enter"] = self.show_player_on_enter
        save_config(self.config)
        if not self.show_player_on_enter:
            frame = getattr(self, "_internal_player_frame", None)
            if frame and frame.IsShown():
                frame.Hide()

    def _on_select_language(self, code: str):
        """Persist the chosen UI language and prompt for a restart to fully apply it."""
        if code == i18n.get_language():
            return
        self.config["language"] = code
        save_config(self.config)
        # Activate immediately so the confirmation (and any new dialogs) use the new language.
        i18n.set_language(code)
        message_box(
            _("The language has been changed. Please restart Accessible IPTV Client "
              "for the change to take full effect."),
            _("Language"),
            wx.OK | wx.ICON_INFORMATION,
        )

    def on_toggle_auto_check_updates(self, event):
        self.auto_check_updates = event.IsChecked()
        self.config["auto_check_updates"] = self.auto_check_updates
        save_config(self.config)

    def on_check_updates(self, _):
        self._start_update_check(interactive=True)

    def _update_flow_busy(self) -> bool:
        """True while an update prompt or download already owns the screen."""
        return bool(getattr(self, "_update_prompt_open", False)
                    or getattr(self, "_update_in_progress", False)
                    or getattr(self, "_update_install_pending", False)
                    or getattr(self, "_update_progress_dlg", None) is not None)

    def _start_update_check(self, interactive: bool):
        if self._update_flow_busy():
            if interactive:
                message_box(_("An update is already in progress."), _("Updates"),
                            wx.OK | wx.ICON_INFORMATION)
            return
        if self._update_check_inflight:
            if interactive:
                message_box(_("Update check is already running."), _("Updates"), wx.OK | wx.ICON_INFORMATION)
            return
        self._update_check_inflight = True
        threading.Thread(target=self._check_updates_worker, args=(interactive,), daemon=True).start()

    def _check_updates_worker(self, interactive: bool):
        try:
            if platform.system() != "Windows":
                raise updater.UpdateError(_("Updates are only supported on Windows builds."))
            if not getattr(sys, "frozen", False):
                raise updater.UpdateError(_("Updates are only available in the packaged build."))

            timeout = (
                _MANUAL_UPDATE_HTTP_TIMEOUT_SECONDS
                if interactive
                else _AUTO_UPDATE_HTTP_TIMEOUT_SECONDS
            )
            release = updater.fetch_latest_release(
                app_meta.GITHUB_OWNER,
                app_meta.GITHUB_REPO,
                timeout=timeout,
            )
            tag = release.get("tag_name") or ""
            latest_version = updater.normalize_version_tag(tag)
            if not latest_version:
                raise updater.UpdateError(_("Latest release tag is missing or invalid."))

            current_version = app_meta.APP_VERSION
            if not updater.is_newer_version(current_version, latest_version):
                if interactive:
                    wx.CallAfter(
                        message_box,
                        _("{app} is up to date (v{version}).").format(
                            app=app_meta.APP_DISPLAY_NAME, version=current_version),
                        _("Updates"),
                        wx.OK | wx.ICON_INFORMATION,
                    )
                return

            notes = release.get("body") or ""
            wx.CallAfter(self._prompt_update, latest_version, current_version, notes, release)
        except updater.UpdateError as exc:
            if interactive:
                wx.CallAfter(
                    message_box,
                    _("Update check failed: {error}").format(error=exc),
                    _("Updates"),
                    wx.OK | wx.ICON_ERROR,
                )
        finally:
            if not interactive:
                self._record_auto_update_check_attempt()
            self._update_check_inflight = False

    def _prompt_update(self, latest_version: str, current_version: str, notes: str, release: Dict):
        # The check that produced this prompt was started before the running
        # update claimed the screen (the hourly timer fires regardless of what
        # the user is doing), so the guard has to be here as well as in
        # _start_update_check. Dropping the prompt is right: the download
        # already under way is for this same release or a newer one, and the
        # next check will offer whatever is left.
        if self._update_flow_busy():
            LOG.info("Skipping update prompt for v%s: an update is already in progress",
                     latest_version)
            return
        summary = updater.summarize_release_notes(notes)
        message = (
            _("Update available: v{latest} (current v{current}).").format(
                latest=latest_version, current=current_version)
            + "\n\n" + f"{summary}" + "\n\n"
            + _("Download and install now? The app will restart after the update.")
        )
        dlg = wx.MessageDialog(self, message, _("Update Available"), wx.YES_NO | wx.ICON_INFORMATION)
        self._update_prompt_open = True
        try:
            answer = dlg.ShowModal()
        finally:
            dlg.Destroy()
            self._update_prompt_open = False
        if answer == wx.ID_YES:
            self._start_update_download(release)

    def _start_update_download(self, release: Dict):
        self._update_progress_message = None
        self._update_in_progress = True
        self._update_cancel = threading.Event()
        self._update_progress_dlg = wx.ProgressDialog(
            _("Updating {app}").format(app=app_meta.APP_DISPLAY_NAME),
            _("Starting update..."),
            maximum=100,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_SMOOTH | wx.PD_ELAPSED_TIME,
        )
        threading.Thread(target=self._download_update_worker, args=(release,), daemon=True).start()

    def _report_update_progress(self, phase: str, fraction) -> bool:
        """Progress callback for the download worker thread.

        Marshals the update to the GUI thread and returns False if the user has
        pressed Cancel so the worker can abort.
        """
        wx.CallAfter(self._apply_update_progress, phase, fraction)
        cancel = getattr(self, "_update_cancel", None)
        return not (cancel is not None and cancel.is_set())

    def _fresh_update_message(self, text: str) -> str:
        """``text`` the first time the progress dialog is given it, "" after.

        wx re-sets the dialog's text every time a message is passed, even an
        unchanged one, and every re-set cuts NVDA off and starts it reading
        from the top again. The download phase went out on each progress tick
        and the install notice four times a second, so neither was ever heard
        to the end. An empty message tells wx to keep the current one.
        """
        if text and text != getattr(self, "_update_progress_message", None):
            self._update_progress_message = text
            return text
        return ""

    def _apply_update_progress(self, phase: str, fraction):
        dlg = getattr(self, "_update_progress_dlg", None)
        if not dlg:
            return
        try:
            message = self._fresh_update_message(phase)
            if fraction is None:
                keep_going, _skip = dlg.Pulse(message)
            else:
                pct = int(max(0.0, min(1.0, float(fraction))) * 100)
                keep_going, _skip = dlg.Update(pct, message)
            if not keep_going:
                cancel = getattr(self, "_update_cancel", None)
                if cancel is not None:
                    cancel.set()
        except Exception:
            LOG.debug("IPTVClient._apply_update_progress: ignored exception", exc_info=True)

    def _destroy_update_progress(self, *, end_flow: bool = True):
        dlg = getattr(self, "_update_progress_dlg", None)
        if dlg is not None:
            try:
                dlg.Destroy()
            except Exception:
                LOG.debug("IPTVClient._destroy_update_progress: ignored exception", exc_info=True)
        self._update_progress_dlg = None
        self._update_progress_message = None
        # Failure and cancel come through here, so this is where the gate
        # reopens. The success path passes end_flow=False: the update carries
        # on in the helper after this window goes away, and reopening the gate
        # would let a queued update prompt start a second one on top of it.
        if end_flow:
            self._update_in_progress = False

    def _download_update_worker(self, release: Dict):
        temp_root = None
        progress = self._report_update_progress
        try:
            progress(_("Checking for update details..."), None)
            manifest = updater.fetch_update_manifest(
                release,
                app_meta.UPDATE_MANIFEST_NAME,
                timeout=_MANUAL_UPDATE_HTTP_TIMEOUT_SECONDS,
            )
            if not updater.is_newer_version(app_meta.APP_VERSION, manifest.version):
                raise updater.UpdateError(_("Update manifest version is not newer than the current app."))

            temp_root = tempfile.mkdtemp(prefix=updater.UPDATE_TEMP_PREFIX)
            if is_windows_installed_build():
                if not manifest.installer_asset_filename or not manifest.installer_download_url or not manifest.installer_sha256:
                    raise updater.UpdateError(_("Update manifest is missing required fields."))

                installer_filename = os.path.basename(manifest.installer_asset_filename)
                if not installer_filename or installer_filename in (".", "..") or installer_filename != manifest.installer_asset_filename:
                    raise updater.UpdateError(_("Update manifest contains an unsafe installer filename."))
                installer_path = os.path.join(temp_root, installer_filename)
                progress(_("Downloading update..."), 0.0)
                digest = updater.download_file_with_sha256(
                    manifest.installer_download_url,
                    installer_path,
                    progress_cb=lambda fraction: progress(_("Downloading update..."), fraction),
                )
                progress(_("Verifying download..."), None)
                if digest.lower() != manifest.installer_sha256.lower():
                    raise updater.UpdateError(_("Downloaded update failed SHA-256 verification."))

                progress(_("Verifying signature..."), None)
                updater.verify_authenticode(installer_path, manifest.signing_thumbprints)

                helper_source = os.path.join(get_app_dir(), "update_helper.bat")
                helper_ps1_source = os.path.join(get_app_dir(), "update_helper.ps1")
                if not os.path.exists(helper_source):
                    helper_source = os.path.join(get_app_dir(), "_internal", "update_helper.bat")
                if not os.path.exists(helper_ps1_source):
                    helper_ps1_source = os.path.join(get_app_dir(), "_internal", "update_helper.ps1")

                if not os.path.exists(helper_source) or not os.path.exists(helper_ps1_source):
                    raise updater.UpdateError(_("Update helper is missing from this build."))

                helper_dir = os.path.join(temp_root, "helper")
                os.makedirs(helper_dir, exist_ok=True)
                helper_bat = os.path.join(helper_dir, "update_helper.bat")
                helper_ps1 = os.path.join(helper_dir, "update_helper.ps1")
                shutil.copy2(helper_source, helper_bat)
                shutil.copy2(helper_ps1_source, helper_ps1)

                progress(_("Preparing to restart..."), None)
                updater.write_update_pending(get_user_config_dir(), manifest.version)
                wx.CallAfter(
                    self._launch_installer_update_helper,
                    helper_bat,
                    os.path.dirname(sys.executable),
                    installer_path,
                    os.path.basename(sys.executable),
                )
                return

            zip_filename = os.path.basename(manifest.asset_filename)
            if not zip_filename or zip_filename in (".", "..") or zip_filename != manifest.asset_filename:
                raise updater.UpdateError(_("Update manifest contains an unsafe asset filename."))
            zip_path = os.path.join(temp_root, zip_filename)
            progress(_("Downloading update..."), 0.0)
            digest = updater.download_file_with_sha256(
                manifest.download_url,
                zip_path,
                progress_cb=lambda fraction: progress(_("Downloading update..."), fraction),
            )
            progress(_("Verifying download..."), None)
            if digest.lower() != manifest.sha256.lower():
                raise updater.UpdateError(_("Downloaded update failed SHA-256 verification."))

            progress(_("Extracting update..."), None)
            extract_root = os.path.join(temp_root, "extracted")
            updater.safe_extract_zip(zip_path, extract_root)

            exe_name = os.path.basename(sys.executable)
            new_exe = updater.find_executable(extract_root, exe_name)
            if not new_exe:
                raise updater.UpdateError(_("Updated executable '{name}' not found in the package.").format(name=exe_name))

            progress(_("Verifying signature..."), None)
            updater.verify_authenticode(new_exe, manifest.signing_thumbprints)

            staging_dir = os.path.dirname(new_exe)
            install_dir = os.path.dirname(sys.executable)
            backup_dir = f"{install_dir}.bak.{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

            helper_source = os.path.join(get_app_dir(), "update_helper.bat")
            helper_ps1_source = os.path.join(get_app_dir(), "update_helper.ps1")
            
            # PyInstaller 6+ onedir layout puts datas in _internal
            if not os.path.exists(helper_source):
                helper_source = os.path.join(get_app_dir(), "_internal", "update_helper.bat")
            if not os.path.exists(helper_ps1_source):
                helper_ps1_source = os.path.join(get_app_dir(), "_internal", "update_helper.ps1")

            if not os.path.exists(helper_source) or not os.path.exists(helper_ps1_source):
                raise updater.UpdateError(_("Update helper is missing from this build."))

            helper_dir = os.path.join(temp_root, "helper")
            os.makedirs(helper_dir, exist_ok=True)
            helper_bat = os.path.join(helper_dir, "update_helper.bat")
            helper_ps1 = os.path.join(helper_dir, "update_helper.ps1")
            shutil.copy2(helper_source, helper_bat)
            shutil.copy2(helper_ps1_source, helper_ps1)

            progress(_("Preparing to restart..."), None)
            updater.write_update_pending(get_user_config_dir(), manifest.version)
            wx.CallAfter(
                self._launch_update_helper,
                helper_bat,
                install_dir,
                staging_dir,
                backup_dir,
                exe_name,
            )
        except updater.UpdateCancelled:
            wx.CallAfter(self._destroy_update_progress)
            if temp_root:
                shutil.rmtree(temp_root, ignore_errors=True)
        except updater.UpdateError as exc:
            wx.CallAfter(self._destroy_update_progress)
            wx.CallAfter(
                message_box,
                _("Update failed: {error}").format(error=exc),
                _("Update Error"),
                wx.OK | wx.ICON_ERROR,
            )
            if temp_root:
                try:
                    shutil.rmtree(temp_root, ignore_errors=True)
                except Exception:
                    LOG.debug("IPTVClient._download_update_worker: ignored exception", exc_info=True)
        except Exception as exc:
            # Never leave the modal progress dialog stuck on an unexpected
            # error (socket timeouts, subprocess failures, etc.).
            LOG.exception("Update worker failed unexpectedly: %s", exc)
            wx.CallAfter(self._destroy_update_progress)
            wx.CallAfter(
                message_box,
                _("Update failed: {error}").format(error=exc),
                _("Update Error"),
                wx.OK | wx.ICON_ERROR,
            )
            if temp_root:
                try:
                    shutil.rmtree(temp_root, ignore_errors=True)
                except Exception:
                    LOG.debug("IPTVClient._download_update_worker: ignored exception", exc_info=True)

    def _launch_installer_update_helper(
        self,
        helper_bat: str,
        install_dir: str,
        installer_path: str,
        exe_name: str,
    ):
        ready_path = self._update_handoff_ready_path(helper_bat)
        helper_language = i18n.resolved_language()
        if helper_language not in ("en", *i18n.SHIPPED_CATALOGS):
            helper_language = "en"
        cmd = [
            "cmd",
            "/d",
            "/c",
            helper_bat,
            "-ParentPid",
            str(os.getpid()),
            "-InstallDir",
            install_dir,
            "-InstallerPath",
            installer_path,
            "-ExeName",
            exe_name,
            "-ReadyFile",
            ready_path,
            "-Language",
            helper_language,
        ]
        # Say what is about to happen in the progress dialog that is already on
        # screen rather than in a box the user has to dismiss. The helper only
        # waits 30 seconds for this process to exit before killing it, and a
        # modal warning left unread used to eat that entire window.
        self._show_update_installing_progress()
        try:
            updater.popen_hidden(cmd, cwd=os.path.dirname(helper_bat))
        except OSError as exc:
            self._destroy_update_progress()
            updater.clear_update_pending(get_user_config_dir())
            message_box(
                _("Update failed to start: {error}").format(error=exc),
                _("Update Error"),
                wx.OK | wx.ICON_ERROR,
            )
            return
        self._update_install_pending = True
        self._close_for_update_install(ready_path)
    def _launch_update_helper(
        self,
        helper_bat: str,
        install_dir: str,
        staging_dir: str,
        backup_dir: str,
        exe_name: str,
    ):
        ready_path = self._update_handoff_ready_path(helper_bat)
        helper_language = i18n.resolved_language()
        if helper_language not in ("en", *i18n.SHIPPED_CATALOGS):
            helper_language = "en"
        cmd = [
            "cmd",
            "/d",
            "/c",
            helper_bat,
            "-ParentPid",
            str(os.getpid()),
            "-InstallDir",
            install_dir,
            "-StagingDir",
            staging_dir,
            "-BackupDir",
            backup_dir,
            "-ExeName",
            exe_name,
            "-ReadyFile",
            ready_path,
            "-Language",
            helper_language,
        ]
        # Say what is about to happen in the progress dialog that is already on
        # screen rather than in a box the user has to dismiss. The helper only
        # waits 30 seconds for this process to exit before killing it, and a
        # modal warning left unread used to eat that entire window.
        self._show_update_installing_progress()
        try:
            updater.popen_hidden(cmd, cwd=os.path.dirname(helper_bat))
        except OSError as exc:
            self._destroy_update_progress()
            updater.clear_update_pending(get_user_config_dir())
            message_box(
                _("Update failed to start: {error}").format(error=exc),
                _("Update Error"),
                wx.OK | wx.ICON_ERROR,
            )
            return
        self._update_install_pending = True
        self._close_for_update_install(ready_path)

    def _show_update_installing_progress(self) -> None:
        """Carry the download dialog straight into the install, no click.

        The installer deletes and rewrites the app directory, so while it runs
        the executable on disk cannot start at all - it fails with "Failed to
        load Python DLL ... python314.dll". Saying so still matters; making the
        user dismiss a box to say it does not, and that dismissal used to have
        to happen inside the 30 seconds update_helper.ps1 waits for us to quit.

        The notice goes out in a fresh progress dialog, not as new text in the
        download one: NVDA reads a progress dialog's text when the dialog
        appears and says nothing when the text of one already on screen
        changes, so the notice set on the download dialog was never spoken.
        After that the dialog is only pulsed - re-sending the text would
        restart NVDA mid-sentence.
        """
        dlg = getattr(self, "_update_progress_dlg", None)
        if dlg is None:
            return
        message = _("Installing the update. {app} will close and start again by "
                    "itself - please do not open it yourself in the "
                    "meantime.").format(app=app_meta.APP_DISPLAY_NAME)
        try:
            if self._fresh_update_message(message):
                # Built before the old one goes, so focus moves straight from
                # one to the other. No Cancel: the helper is already on its way.
                replacement = wx.ProgressDialog(
                    _("Updating {app}").format(app=app_meta.APP_DISPLAY_NAME),
                    message,
                    maximum=100,
                    parent=self,
                    style=wx.PD_APP_MODAL | wx.PD_SMOOTH | wx.PD_ELAPSED_TIME,
                )
                self._update_progress_dlg = replacement
                dlg.Destroy()
                dlg = replacement
            dlg.Pulse()
        except Exception:
            LOG.debug("IPTVClient._show_update_installing_progress: ignored exception",
                      exc_info=True)

    @staticmethod
    def _update_handoff_ready_path(helper_bat: str) -> str:
        """Where the helper reports that its own status window is on screen."""
        return os.path.join(os.path.dirname(helper_bat), "update_window_ready")

    def _close_for_update_install(self, ready_path: Optional[str] = None) -> None:
        """Quit for the installer - but not before the helper's window is up.

        The app has to exit for the install to run, so its own progress dialog
        cannot survive the update; the helper owns a status window that can.
        Closing on a fixed timer raced that window into existence: PowerShell
        needs a second or two to start and load WinForms, and for the whole of
        that gap there was nothing on screen and nothing for a screen reader to
        read. So wait for the helper to say its window is showing, then linger
        the usual moment on top of it, so the two windows overlap instead of
        leaving a hole between them. The wait is capped: a helper that never
        reports in must not strand the user in a dialog that will not close.
        """
        deadline = time.monotonic() + _UPDATE_HANDOFF_MAX_WAIT_SECONDS

        def wait_for_helper_window():
            if (ready_path and not os.path.exists(ready_path)
                    and time.monotonic() < deadline):
                # Keep pulsing: an un-updated progress dialog is the thing that
                # goes grey and stops answering while we sit here.
                self._show_update_installing_progress()
                wx.CallLater(_UPDATE_HANDOFF_POLL_MS, wait_for_helper_window)
                return
            wx.CallLater(_UPDATE_HANDOFF_LINGER_MS, self._finish_update_handoff)

        wait_for_helper_window()

    def _finish_update_handoff(self) -> None:
        # end_flow=False: the update is not over, it carries on in the helper,
        # so the gate stays shut until this process actually exits.
        self._destroy_update_progress(end_flow=False)
        self.Close()

    def _report_finished_update(self) -> None:
        """Report an update that was in progress at our last exit, if it failed."""
        config_dir = get_user_config_dir(create=False)
        pending = updater.read_update_pending(config_dir)
        if not pending:
            return
        updater.clear_update_pending(config_dir)
        target = str(pending.get("version") or "").strip()
        if not target:
            return
        current = app_meta.APP_VERSION
        if updater.is_newer_version(current, target):
            # We came back on the old version: the install did not land.
            message_box(
                _("The update to v{version} did not finish, so {app} is still "
                  "v{current}. You can try again from Help > Check for "
                  "Updates...").format(
                      version=target, app=app_meta.APP_DISPLAY_NAME, current=current),
                _("Update Not Completed"),
                wx.OK | wx.ICON_WARNING,
            )
            return
        # Success speaks for itself - the app is simply running again, on the
        # new version. Only a failed update needs to interrupt anyone.
        LOG.info("Update to v%s completed", current)

    @staticmethod
    def _bool_pref(value, default: bool = False) -> bool:
        """Coerce config values that might be stored as bools/strings/ints."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(default)

    def show_tray_icon(self):
        self._tray_allow_restore = False
        self._cancel_tray_ready_timer()
        if not self.tray_icon:
            self.tray_icon = TrayIcon(
                self,
                on_restore=self.restore_from_tray,
                on_exit=self.exit_from_tray,
                on_player_show=self._tray_show_player,
                on_player_toggle=self._tray_toggle_play_pause,
                on_player_stop=self._tray_stop_player,
                on_cast=self._tray_cast,
                on_record_stop=self._stop_all_recordings,
            )
        self.Hide()
        self._tray_ready_timer = wx.CallLater(250, self._enable_tray_restore)

    def restore_from_tray(self):
        self._tray_allow_restore = False
        self._cancel_tray_ready_timer()
        # First, destroy the tray icon completely
        if self.tray_icon:
            try:
                self.tray_icon.RemoveIcon()
            except Exception:
                LOG.debug("IPTVClient.restore_from_tray: ignored exception", exc_info=True)
            try:
                self.tray_icon.Destroy()
            except Exception:
                LOG.debug("IPTVClient.restore_from_tray: ignored exception", exc_info=True)
            self.tray_icon = None
        # Show and restore the window
        self.Show()
        self.Iconize(False)
        self.Raise()
        # Delay focus operations to let the tray icon fully release
        wx.CallLater(150, self._complete_restore_from_tray)
    
    def _complete_restore_from_tray(self):
        """Complete restore after tray icon is destroyed."""
        # Force window to foreground using Windows API for proper focus
        self._force_foreground()
        # Set focus to channel list for screen reader accessibility
        wx.CallAfter(self._restore_focus_after_tray)
        # Additional delayed attempt
        wx.CallLater(100, self._restore_focus_after_tray)

    def _force_foreground(self):
        """Force window to foreground on Windows using native API."""
        if platform.system() != "Windows":
            try:
                self.SetFocus()
            except Exception:
                LOG.debug("IPTVClient._force_foreground: ignored exception", exc_info=True)
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = self.GetHandle()
            SW_RESTORE = 9
            SW_SHOW = 5
            VK_MENU = 0x12  # Alt key
            KEYEVENTF_EXTENDEDKEY = 0x0001
            KEYEVENTF_KEYUP = 0x0002
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            HWND_TOP = 0
            
            # Get our thread ID
            current_tid = kernel32.GetCurrentThreadId()
            
            # Get the foreground window's thread
            foreground_hwnd = user32.GetForegroundWindow()
            foreground_tid = user32.GetWindowThreadProcessId(foreground_hwnd, None)
            
            # Attach our thread to the foreground thread
            attached = False
            if foreground_tid and foreground_tid != current_tid:
                attached = user32.AttachThreadInput(foreground_tid, current_tid, True)
            
            try:
                # Show and restore the window
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.ShowWindow(hwnd, SW_SHOW)
                
                # Move window to top of Z-order
                user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                
                # Simulate Alt key press to unlock foreground
                user32.keybd_event(VK_MENU, 0, KEYEVENTF_EXTENDEDKEY, 0)
                user32.keybd_event(VK_MENU, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
                
                # Set foreground and focus
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                # Detach threads if we attached
                if attached:
                    user32.AttachThreadInput(foreground_tid, current_tid, False)
        except Exception:
            # Fallback to wx method if Windows API fails
            try:
                self.SetFocus()
            except Exception:
                LOG.debug("IPTVClient._force_foreground: ignored exception", exc_info=True)

    def _restore_focus_after_tray(self):
        """Set focus to channel list - used after restore from tray."""
        try:
            if self.IsShown() and not self.IsIconized():
                # Ensure window is in foreground first
                self._force_foreground()
                # Focus the channel list control
                self.channel_list.SetFocus()
                # Set a selection to ensure something is selected
                if self.channel_list.GetCount() > 0:
                    sel = self.channel_list.GetSelection()
                    if sel == wx.NOT_FOUND:
                        self.channel_list.SetSelection(0)
                        sel = 0
                    # Notify screen readers of the focus change on the list control
                    if platform.system() == "Windows":
                        try:
                            import ctypes
                            user32 = ctypes.windll.user32
                            list_hwnd = self.channel_list.GetHandle()
                            EVENT_OBJECT_FOCUS = 0x8005
                            EVENT_OBJECT_SELECTION = 0x8006
                            OBJID_CLIENT = -4
                            CHILDID_SELF = 0
                            # Fire focus event on the list
                            user32.NotifyWinEvent(EVENT_OBJECT_FOCUS, list_hwnd, OBJID_CLIENT, CHILDID_SELF)
                            # Fire selection event on the selected item (1-indexed for MSAA)
                            user32.NotifyWinEvent(EVENT_OBJECT_SELECTION, list_hwnd, OBJID_CLIENT, sel + 1)
                        except Exception:
                            LOG.debug("IPTVClient._restore_focus_after_tray: ignored exception", exc_info=True)
        except Exception:
            LOG.debug("IPTVClient._restore_focus_after_tray: ignored exception", exc_info=True)

    def _tray_show_player(self):
        try:
            frame = self._ensure_internal_player()
        except Exception:
            return
        frame.Enable(True)
        frame.Show()
        frame.Raise()

    def _tray_toggle_play_pause(self):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            wx.CallAfter(frame._on_toggle_pause)

    def _tray_stop_player(self):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            wx.CallAfter(lambda: frame.stop(manual=True))

    def _tray_cast(self):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            wx.CallAfter(lambda: frame._on_cast())

    def _menu_show_player(self, _=None):
        try:
            frame = self._ensure_internal_player()
        except Exception:
            return
        frame.Enable(True)
        frame.Show()
        frame.Raise()

    def _internal_player_has_media(self) -> bool:
        """True while the built-in player has a stream loaded.

        Loaded means playing, paused or stopped with something to resume -
        the same test Play/Pause uses. No player window, or one with nothing
        in it, is nothing to show, pause, stop or cast.
        """
        frame = getattr(self, "_internal_player_frame", None)
        if not frame:
            return False
        try:
            if getattr(frame, "_destroyed", False):
                return False
            return bool(frame._current_url or frame._last_resolved_url)
        except Exception:
            return False

    def _sync_player_controls_menu(self) -> None:
        """Grey out the Player menu while there is nothing to control.

        A command that silently does nothing reads, to a screen reader, just
        like one that is broken; a greyed-out item is announced as
        unavailable before the user ever presses it.
        """
        loaded = self._internal_player_has_media()
        for item in getattr(self, "_player_control_items", ()):
            try:
                item.Enable(loaded)
            except Exception:
                LOG.debug("IPTVClient._sync_player_controls_menu: ignored exception", exc_info=True)

    def _show_catchup_downloads(self, _event=None) -> None:
        """Bring a catch-up download window back into view and focus.

        With several downloads running, each use moves on to the next window,
        the way Ctrl+F6 steps between documents.
        """
        dialogs = [dlg for dlg in list(getattr(self, "_catchup_downloads", {}).values()) if dlg]
        if not dialogs:
            return
        current = -1
        for index, dlg in enumerate(dialogs):
            try:
                if dlg.IsShown() and dlg.IsActive():
                    current = index
                    break
            except Exception:
                LOG.debug("IPTVClient._show_catchup_downloads: ignored exception", exc_info=True)
        dialogs[(current + 1) % len(dialogs)].reveal()

    def _on_filter_focus(self, event):
        self._filter_focus_gen = getattr(self, "_filter_focus_gen", 0) + 1
        event.Skip()

    def _on_filter_char_hook(self, event):
        """Apply the search filter on Tab from the filter box, like Enter does.

        Enter is consumed by EVT_TEXT_ENTER, so Tab is intercepted here and
        routed through the same path. apply_filter always leaves focus on the
        channel list when there is something to show, which is the natural
        Tab target after a search; with an empty box (or no results) it calls
        _focus_after_filter, which falls back to normal navigation when the
        list cannot take focus.

        Shift+Tab is the backward edge of the manual focus ring: the group
        list's Tab rule sends focus here, so Shift+Tab returns there. Without
        this, default traversal just moves the caret inside the text control
        and the search field is a trap in both directions.
        """
        if event.GetKeyCode() == wx.WXK_TAB and not event.HasAnyModifiers():
            self.apply_filter()
            self._focus_after_filter()
            return
        if event.GetKeyCode() == wx.WXK_TAB and event.ShiftDown():
            self.group_list.SetFocus()
            return
        event.Skip()

    def _focus_after_filter(self):
        """Focus the channel list after a search, falling back to normal
        navigation when it cannot take focus (no rows). Called from the
        filter box so Tab never leaves the user stuck in the search field."""
        if self.channel_list.GetCount() > 0:
            self.channel_list.SetFocus()
            return
        # Nothing to focus: let the default navigation cycle move on instead
        # of swallowing the Tab and trapping the caret in the search field.
        nav = wx.NavigationKeyEvent()
        nav.SetDirection(wx.NavigationKeyEvent.IsForward)
        nav.SetCurrentFocus(self.filter_box)
        nav.SetFromTab(True)
        self.GetEventHandler().ProcessEvent(nav)

    def _menu_toggle_player(self, _=None):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            try:
                destroyed = bool(getattr(frame, "_destroyed", False))
                has_media = bool(frame._current_url or frame._last_resolved_url)
            except Exception:
                destroyed, has_media = True, False
            if not destroyed and has_media:
                # A stream is loaded (playing, paused, or stopped, visible or
                # hidden): toggle it. _on_toggle_pause also resumes after a
                # manual stop or a stream that ended.
                frame._on_toggle_pause()
                return
            # Nothing is loaded: Play/Pause plays the selected channel, like
            # pressing Enter, instead of doing nothing.
            self.play_selected()
            return
        self.play_selected()

    def _menu_stop_player(self, _=None):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            frame.stop(manual=True)

    def _menu_cast_from_player(self, _=None):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            frame._on_cast()

    def _adjust_internal_volume(self, delta: int):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            wx.CallAfter(frame._adjust_volume, delta)

    def exit_from_tray(self):
        self._search_token += 1
        self._populate_token += 1
        self._tray_allow_restore = False
        self._cancel_tray_ready_timer()
        if self.tray_icon:
            try:
                self.tray_icon.RemoveIcon()
            except Exception:
                LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
            self.tray_icon.Destroy()
            self.tray_icon = None
        try:
            self._stop_dvr_scheduler(wait=True)
        except Exception:
            LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
        try:
            self._release_recordings_on_exit()
        except Exception:
            LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
        # Mirror on_close cleanup so the now-playing timer can't fire into a
        # destroyed frame and executor threads don't leak when exiting from the tray.
        try:
            self._stop_now_playing_timer()
        except Exception:
            LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
        try:
            self._stop_update_check_timer()
        except Exception:
            LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
        try:
            self._cancel_epg_autostart_timer()
        except Exception:
            LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
        if hasattr(self, "_epg_executor"):
            self._epg_executor.shutdown(wait=False)
        if self.caster:
            self.caster.stop()
        self.Destroy()

    def _enable_tray_restore(self):
        self._tray_ready_timer = None
        if self.tray_icon:
            self._tray_allow_restore = True

    def _cancel_tray_ready_timer(self):
        if self._tray_ready_timer:
            try:
                self._tray_ready_timer.Stop()
            except Exception:
                LOG.debug("IPTVClient._cancel_tray_ready_timer: ignored exception", exc_info=True)
            self._tray_ready_timer = None

    def on_minimize(self, event):
        if self.minimize_to_tray and event.IsIconized():
            wx.CallAfter(self.show_tray_icon)
        else:
            event.Skip()

    def on_close(self, event):
        if self.minimize_to_tray and not self._update_install_pending and not self._exit_forced:
            wx.CallAfter(self.show_tray_icon)
            event.Veto()
        else:
            # Warn before an exit that would stop a running download. The tray
            # path above keeps the app (and the download) alive, so it needs no
            # warning; recordings keep their own detached-finalize behaviour.
            if (event.CanVeto() and not self._update_install_pending
                    and self._catchup_downloads):
                answer = message_box(
                    _("A download is still in progress.\n\n"
                      "If you exit now it will stop, and only the part captured "
                      "so far is kept.\n\nExit anyway?"),
                    _("Download in progress"), wx.YES_NO | wx.ICON_QUESTION)
                if answer != wx.YES:
                    event.Veto()
                    return
            self._search_token += 1
            self._populate_token += 1
            set_modal_box_closed_hook(None)
            # Ensure poll timer stopped on exit
            try:
                self._stop_now_playing_timer()
            except Exception:
                LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
            try:
                self._stop_update_check_timer()
            except Exception:
                LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
            try:
                self._cancel_epg_autostart_timer()
            except Exception:
                LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
            if hasattr(self, "_epg_executor"):
                self._epg_executor.shutdown(wait=False)
            try:
                self._stop_dvr_scheduler(wait=True)
            except Exception:
                LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
            try:
                self._release_recordings_on_exit()
            except Exception:
                LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
            if self.caster:
                self.caster.stop()
            if self.tray_icon:
                try:
                    self.tray_icon.RemoveIcon()
                except Exception:
                    LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
                self.tray_icon.Destroy()
                self.tray_icon = None
            frame = getattr(self, "_internal_player_frame", None)
            if frame is not None:
                try:
                    frame.Destroy()
                except Exception:
                    LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
                self._internal_player_frame = None
            self.Destroy()

    def _select_player(self, player):
        self.default_player = player
        self.config["media_player"] = player
        save_config(self.config)
        self._sync_player_menu_from_config()

    def _select_custom_player(self, _):
        dlg = CustomPlayerDialog(self, self.config.get("custom_player_path", ""))
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath().strip()
            if path:
                self.custom_player_path = path
                self.default_player = "Custom"
                self.config["media_player"] = "Custom"
                self.config["custom_player_path"] = path
                save_config(self.config)
        dlg.Destroy()
        self._sync_player_menu_from_config()

    def on_channel_key(self, event):
        # Kept for compatibility; EVT_KEY_DOWN handler above is the reliable path
        key = event.GetKeyCode()
        if key == wx.WXK_TAB:
            if event.ShiftDown():
                self.filter_box.SetFocus()
            else:
                # The episode description is always present, so it is always
                # the next stop; Shift+Tab from there comes straight back
                # here. The stream-URL field, which the user can switch off,
                # sits one Tab further on.
                self.episode_description_field.SetFocus()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.play_selected()
        elif key in (wx.WXK_LEFT, wx.WXK_RIGHT):
            return
        else:
            event.Skip()

    def on_playlist_scope_key(self, event):
        # Native traversal includes search, programme information and URL.
        event.Skip()

    def on_group_key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_HOME, wx.WXK_END,
                   wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            # Navigate the category list: let the native listbox move the
            # selection (NVDA announces the tree item's level and state) but do
            # NOT repopulate the channel list or move focus. Enter/Tab activate.
            event.Skip()
            return
        if key == wx.WXK_TAB and event.ShiftDown():
            self.playlist_scope_combo.SetFocus()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_TAB):
            self._activate_selected_group()
            (self.filter_box if key == wx.WXK_TAB else self.channel_list).SetFocus()
            return
        if key == wx.WXK_LEFT:
            self.group_list.CollapseSelectedBranch()
            return
        if key == wx.WXK_RIGHT:
            self.group_list.ExpandSelectedBranch()
            return
        event.Skip()

    def _activate_selected_group(self):
        """Switch the channel list to the selected category and move focus there."""
        if self.group_list.GetSelection() == wx.NOT_FOUND:
            # A hierarchy-only parent is navigation, not a playlist category.
            # Enter/Tab expands it without unexpectedly showing All Channels.
            toggle = getattr(self.group_list, "ToggleSelectedBranch", None)
            if callable(toggle):
                toggle()
            return
        self.on_group_select()
        # An empty scope combo has no selection: repopulating would fire
        # EVT_LIST_ITEM_SELECTED on a negative selection and crash here.
        if self.playlist_scope_combo.GetSelection() == wx.NOT_FOUND:
            return
        if self.channel_list.GetCount() > 0:
            self.channel_list.SetFocus()

    def _on_group_activated(self, _event):
        # Mouse activation of a category follows the same path as Enter/Tab.
        self._activate_selected_group()

    def _append_search_results_chunked(self, channels: List[Dict[str, str]], token: int):
        # Virtual list: appending is O(1) regardless of count, so no chunking is needed.
        if token != self._populate_token:
            return
        for ch in channels:
            self.displayed.append({"type": "channel", "data": ch})
        self.channel_list.set_virtual_count()

    def _replace_search_results_chunked(
        self,
        entries: List[Dict[str, str]],
        search_token: int,
        populate_token: int,
    ):
        """Install broad search results in yielding, accessibility-safe batches."""
        if len(entries) <= self._SEARCH_LARGE_RESULT_THRESHOLD:
            IPTVClient._replace_displayed(self, entries)
            return

        preview_count = min(self._SEARCH_PREVIEW_COUNT, len(entries))
        IPTVClient._replace_displayed(self, entries[:preview_count])

        def append_batch(offset=preview_count):
            if getattr(self, "_search_token", 0) != search_token:
                return
            if getattr(self, "_populate_token", 0) != populate_token:
                return
            end = min(offset + self._SEARCH_BATCH_SIZE, len(entries))
            self.displayed.extend(entries[offset:end])
            self.channel_list.set_virtual_count()
            if end < len(entries):
                wx.CallLater(1, append_batch, end)

        wx.CallLater(1, append_batch)

    def _replace_displayed(self, entries: List[Dict[str, str]]):
        """Replace the virtual-list model without exposing an invalid row.

        A search result list is a new model, not an append. The native control
        can synchronously ask for item text while its item count changes, so
        ``_VirtualChannelList`` owns the ordering of the model/count update.
        Keep the small fallback for non-GUI test doubles.
        """
        replace_contents = getattr(self.channel_list, "replace_contents", None)
        if callable(replace_contents):
            replace_contents(entries)
        else:
            self.displayed = entries
            self.channel_list.set_virtual_count()

    def _should_run_epg_search(self, query: str, channel_match_count: int) -> bool:
        if not self.config.get("epg_enabled", True):
            return False
        if getattr(self, "current_group", "All Channels") != "All Channels":
            return False
        if self.epg_importing:
            return False
        if getattr(self, "_pending_epg_autostart", False):
            return False
        if getattr(self, "_epg_autostart_timer", None) is not None:
            return False
        if len(query) < self._SEARCH_EPG_MIN_CHARS:
            return False
        if channel_match_count > self._SEARCH_EPG_BROAD_CHANNEL_LIMIT:
            return False
        try:
            path = get_db_path()
            if not os.path.exists(path):
                return False
            conn = sqlite3.connect(f"file:{path}?mode=ro&cache=shared", uri=True, timeout=0.5)
            try:
                tables = {
                    row[0]
                    for row in conn.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table' AND name IN ('channels', 'programmes')
                        """
                    ).fetchall()
                }
                return not ({"channels", "programmes"} - tables)
            finally:
                conn.close()
        except Exception:
            return False

    def apply_filter(self):
        txt = self.filter_box.GetValue().strip().lower()
        # Remember which focus generation started this search: results that
        # land after the user has re-focused the box are stale for focus
        # purposes and must not steal the caret.
        self._filter_focus_gen_at_search = getattr(self, "_filter_focus_gen", 0)
        if getattr(self, "view_mode", "live") == "vod":
            self._vod_apply_filter(txt)
            return
        self._populate_token += 1
        populate_token = self._populate_token
        self._search_token += 1
        search_token = self._search_token
        source = self._source_for_group(self.current_group)
        LOG.debug("search start: %r group=%s source=%d", txt, self.current_group, len(source))
        self.url_display.SetValue("")

        if not txt:
            # Rebuild current group quickly without blocking the UI
            self.on_group_select()
            return

        # Snapshot on the UI thread so the worker never races a playlist reload
        # mutating the source list in place.
        source_snapshot = list(source)

        def filter_worker():
            # The match loop and entry building over 50k-300k channels run off
            # the UI thread. While an EPG import is writing gigabytes, the disk
            # and page cache are starved enough that this work on the UI thread
            # freezes the interface (and NVDA with it); a worker thread absorbs
            # those stalls while the UI keeps pumping messages.
            matching_channels = []
            for index, ch in enumerate(source_snapshot):
                if index % 256 == 0 and getattr(self, "_search_token", 0) != search_token:
                    LOG.debug("search %r: cancelled stale channel scan", txt)
                    return
                name = (ch.get("name") or "")
                if txt and txt not in name.lower():
                    continue
                matching_channels.append(ch)
            entries = [
                {"type": "channel", "data": ch}
                for ch in matching_channels
            ]

            def apply_results():
                if getattr(self, "_search_token", 0) != search_token:
                    LOG.debug("search %r: dropped stale search token", txt)
                    return
                if getattr(self, "_populate_token", 0) != populate_token:
                    LOG.debug("search %r: dropped, list was repopulated", txt)
                    return
                # Results are installed asynchronously; move focus to the list
                # now or a Tab press from the filter box would appear to do
                # nothing (the caret stays in the search field). Skip when the
                # user has re-focused the box since this search started: that
                # result is stale and stealing focus would interrupt editing.
                # getattr keeps non-GUI test doubles (no HasFocus) working.
                has_focus = getattr(self.filter_box, "HasFocus", None)
                if (
                    callable(has_focus)
                    and has_focus()
                    and getattr(self, "_filter_focus_gen", 0)
                    == getattr(self, "_filter_focus_gen_at_search", -1)
                ):
                    self._focus_after_filter()
                # Replacing search results is different from appending asynchronous
                # EPG rows. Let the virtual list order the old/new model transition
                # so NVDA never observes a stale active child during a SetItemCount
                # shrink.
                IPTVClient._replace_search_results_chunked(
                    self, entries, search_token, populate_token
                )
                LOG.debug("search %r: %d channel matches", txt, len(matching_channels))
            wx.CallAfter(apply_results)

            # Kick off bounded EPG search only for specific channel-name searches.
            # Do not search programme titles here: a leading-wildcard title query
            # scans large XMLTV databases and causes the first-run CPU spike.
            # wx.CallAfter is FIFO, so the EPG rows queued by epg_search below
            # always land after apply_results has installed the channel rows.
            if getattr(self, "_search_token", 0) != search_token:
                LOG.debug("search %r: cancelled before EPG lookup", txt)
                return
            if not self._should_run_epg_search(txt, len(matching_channels)):
                LOG.debug("search %r: EPG search skipped", txt)
                return
            LOG.debug("search %r: EPG search started (token %d)", txt, search_token)
            epg_search(search_token, populate_token)

        def epg_search(active_search_token, active_populate_token):
            db = None
            try:
                db = EPGDatabase(get_db_path(), readonly=True)
                try:
                    if hasattr(db, "conn"):
                        db.conn.execute("PRAGMA busy_timeout=2000;")
                        db.conn.execute("PRAGMA read_uncommitted=1;")
                except Exception:
                    LOG.debug("IPTVClient.apply_filter.epg_search: ignored exception", exc_info=True)
                results = db.get_channels_with_show(
                    txt,
                    limit=self._SEARCH_EPG_RESULT_LIMIT,
                    include_title_search=False,
                )
            except Exception:
                results = []
            finally:
                try:
                    if db is not None and hasattr(db, "close"):
                        db.close()
                    elif db is not None and hasattr(db, "conn"):
                        db.conn.close()
                except Exception:
                    LOG.debug("IPTVClient.apply_filter.epg_search: ignored exception", exc_info=True)
            def update_ui():
                if getattr(self, "_search_token", 0) != active_search_token:
                    LOG.debug("EPG search %r: dropped stale search token", txt)
                    return
                if getattr(self, "_populate_token", 0) != active_populate_token:
                    LOG.debug("EPG search %r: dropped, list was repopulated", txt)
                    return
                if txt != self.filter_box.GetValue().strip().lower():
                    LOG.debug("EPG search %r: dropped, query changed", txt)
                    return
                added = 0
                for r in results:
                    chan_name = r.get('channel_name') or ""
                    show_name = r.get('show_title') or ""
                    chan_lower = chan_name.lower()
                    show_lower = show_name.lower()
                    if txt and txt not in chan_lower and txt not in show_lower:
                        continue
                    label = f"{r.get('channel_name', '')} - {r.get('show_title', '')} ({self._fmt_time(r.get('start', ''))}–{self._fmt_time(r.get('end', ''))})"
                    self.displayed.append({"type": "epg", "data": r, "label": label})
                    added += 1
                if added:
                    self.channel_list.set_virtual_count()
                # Appending to the end of a virtual list never moves the existing
                # selection, so no Select/Focus/EnsureVisible here: re-firing focus
                # events while the user is typing in the filter box confuses NVDA.
                LOG.debug("EPG search %r: appended %d results", txt, added)
            wx.CallAfter(update_ui)
        threading.Thread(target=filter_worker, daemon=True).start()

    def _refresh_group_ui(self):
        scoped_channels = self.scoped_all_channels()
        scoped_groups = self.scoped_channels_by_group()
        self.group_list.Freeze()
        try:
            self.group_list.Clear()
            self.channel_list.Clear()

            if not scoped_channels:
                self.group_list.Append(_("No channels found."))
                self._group_keys = []
                self._maybe_autostart_epg_import()
                return

            self.group_list.Append(_("All Channels") + f" ({len(scoped_channels)})")
            keys = ["All Channels"]
            favorite_channels = self._favorite_channels()
            if favorite_channels:
                # Second, so it is one Down press from the top of the categories.
                self.group_list.Append(self._favorites_group_label(len(favorite_channels)))
                keys.append(favorites.FAVORITES_GROUP)
            if self.playlist_scope == ALL_PLAYLISTS_SCOPE and self._scoped_sources():
                # Each source gets a top-level provider branch. Its category
                # leaves retain a scope-aware key, so selecting "News" below
                # one provider cannot show the other providers' News channels.
                source_labels = {
                    _source_scope_id(source): self._scope_choice_label(source)
                    for source in self._scoped_sources()
                }
                source_groups: Dict[str, Dict[str, int]] = {}
                for channel in scoped_channels:
                    scope = str(channel.get("playlist-id") or "")
                    group = str(channel.get("group") or "Uncategorized")
                    groups = source_groups.setdefault(scope, {})
                    groups[group] = groups.get(group, 0) + 1

                ordered_scopes = list(source_labels)
                # Retain cached/legacy channels that do not have a source tag;
                # they belong in their own branch instead of disappearing.
                ordered_scopes.extend(scope for scope in source_groups if scope not in source_labels)
                for scope in ordered_scopes:
                    groups = source_groups.get(scope, {})
                    if not groups:
                        continue
                    source_label = source_labels.get(scope, _("Other playlists"))
                    provider_path = ("playlist", scope, source_label)
                    channel_count = sum(groups.values())
                    # "All Channels" leaf first, so every playlist branch opens
                    # with its whole channel list one Enter press away.
                    self.group_list.Append(
                        _("All Channels") + f" ({channel_count})",
                        tree_path=[provider_path, _("All Channels")],
                    )
                    keys.append(("playlist-all", scope))
                    for group in sorted(groups):
                        self.group_list.Append(
                            f"{group} ({groups[group]})",
                            tree_path=[provider_path] + _AccessibleCategoryTree._path_parts(group),
                        )
                        keys.append(("playlist-group", scope, group))
            else:
                for grp in sorted(scoped_groups):
                    self.group_list.Append(f"{grp} ({len(scoped_groups[grp])})")
                    keys.append(grp)
            self._group_keys = keys

            # Restore the selection by key, not by label: the sentinel categories
            # are stored in English and displayed translated (and with a count), so
            # matching on the visible string cannot find them.
            try:
                current_idx = keys.index(self.current_group)
            except ValueError:
                current_idx = 0
            try:
                self.group_list.SetSelection(current_idx)
            except Exception:
                LOG.debug("IPTVClient._refresh_group_ui: ignored exception", exc_info=True)
                self.group_list.SetSelection(0)
        finally:
            try:
                self.group_list.Thaw()
            except Exception:
                LOG.debug("IPTVClient._refresh_group_ui: ignored exception", exc_info=True)
        
        self.on_group_select()

    # ================================================================== #
    # Video on Demand (movies & series) view
    # ================================================================== #
    def _set_view_mode(self, mode: str):
        """Switch between the live channel view and the VOD view."""
        if mode not in ("live", "vod"):
            return
        if mode == self.view_mode:
            return
        self.view_mode = mode
        self._sync_view_menu()
        # Leaving a filter behind between modes is confusing; clear it.
        try:
            self.filter_box.ChangeValue("")
        except Exception:
            LOG.debug("IPTVClient._set_view_mode: ignored exception", exc_info=True)
        if mode == "live":
            self._refresh_group_ui()
            return
        # Switching to VOD.
        if self.vod_loaded:
            self._refresh_vod_group_ui()
        else:
            self._load_vod_catalog()

    def _sync_view_menu(self):
        for attr, wanted in (("view_live_item", "live"), ("view_vod_item", "vod")):
            item = getattr(self, attr, None)
            if item is not None:
                try:
                    item.Check(self.view_mode == wanted)
                except Exception:
                    LOG.debug("IPTVClient._sync_view_menu: ignored exception", exc_info=True)

    def _load_vod_catalog(self):
        """Build the VOD catalogue in the background, then show it."""
        if self.vod_loading:
            return
        self.vod_loading = True
        self._vod_load_token += 1
        token = self._vod_load_token

        self.group_list.Freeze()
        try:
            self.group_list.Clear()
            self.channel_list.Clear()
            self.group_list.Append(_("Loading Video on Demand…"))
            self.group_list.SetSelection(0)
        finally:
            try:
                self.group_list.Thaw()
            except Exception:
                LOG.debug("IPTVClient._load_vod_catalog: ignored exception", exc_info=True)
        self.url_display.SetValue("")

        clients = dict(self.provider_clients)
        # Honour the playlist scope: only the selected playlist's VOD entries.
        m3u_channels = [
            ch for ch in self.scoped_all_channels()
            if ch.get("provider-type") not in ("xtream", "stalker")
        ]
        scope = self.playlist_scope
        if scope != ALL_PLAYLISTS_SCOPE:
            clients = {
                pid: client for pid, client in clients.items()
                if _client_pid_scope(pid, scope)
            }

        def worker():
            catalogs = []
            try:
                for pid, client in clients.items():
                    if isinstance(client, XtreamCodesClient):
                        try:
                            catalogs.append(vod.build_xtream_catalog(client, pid))
                        except Exception:
                            continue
                if m3u_channels:
                    try:
                        catalogs.append(vod.categorize_m3u_vod(m3u_channels))
                    except Exception:
                        LOG.debug("IPTVClient._load_vod_catalog.worker: ignored exception", exc_info=True)
                order, groups = vod.merge_catalogs(catalogs)
            except Exception:
                order, groups = [], {}
            wx.CallAfter(self._on_vod_catalog_ready, token, order, groups)

        threading.Thread(target=worker, daemon=True).start()

    def _on_vod_catalog_ready(self, token: int, order: List[str], groups: Dict[str, List[Dict]]):
        if token != self._vod_load_token:
            return  # a newer load (or a switch back to live) superseded this one
        self.vod_loading = False
        self.vod_loaded = True
        self.vod_group_order = order
        self.vod_groups = groups
        if self.view_mode != "vod":
            return
        self._refresh_vod_group_ui()

    def _refresh_vod_group_ui(self):
        self.vod_current_group = None
        self._vod_series_return_group = None
        self.group_list.Freeze()
        try:
            self.group_list.Clear()
            self.channel_list.Clear()
            if not self.vod_group_order:
                self.group_list.Append(_("No Video on Demand content found."))
                self.url_display.SetValue("")
                return
            for label in self.vod_group_order:
                count = len(self.vod_groups.get(label, []))
                self.group_list.Append(f"{label} ({count})")
            self.group_list.SetSelection(0)
        finally:
            try:
                self.group_list.Thaw()
            except Exception:
                LOG.debug("IPTVClient._refresh_vod_group_ui: ignored exception", exc_info=True)
        if self.vod_group_order:
            self.on_group_select()

    def _vod_on_group_select(self):
        sel = self.group_list.GetSelection()
        if sel == wx.NOT_FOUND or sel >= len(self.vod_group_order):
            return
        label = self.vod_group_order[sel]
        self.vod_current_group = label
        self._vod_series_return_group = None
        items = self.vod_groups.get(label, [])
        self._vod_show_items(items)

    def _vod_show_items(self, items: List[Dict]):
        """Render a category listing: movies play directly, series drill in."""
        displayed = []
        for it in items:
            if it.get("kind") == vod.KIND_SERIES:
                displayed.append({"type": "vod_series", "data": it,
                                  "label": it.get("name", "")})
            else:
                displayed.append({"type": "channel", "data": it})
        self._populate_token += 1
        IPTVClient._replace_displayed(self, displayed)
        if displayed:
            self.channel_list.SetSelection(0)
            if self.IsShown() and not self.IsIconized():
                self.channel_list.SetFocus()
            self.on_highlight()
        else:
            self.url_display.SetValue("")

    def _vod_open_series(self, series: Dict):
        """Drill into a series: list its episodes (in order) with a Back entry."""
        self._vod_series_return_group = self.vod_current_group
        name = series.get("name", "")
        # M3U series carry their episodes inline; Xtream series load lazily.
        inline = series.get("episodes")
        if inline is not None:
            self._vod_show_episodes(name, inline)
            return

        client = self.provider_clients.get(series.get("provider-id"))
        series_id = series.get("series_id")
        if not isinstance(client, XtreamCodesClient) or series_id is None:
            message_box(_("Could not load episodes for this series."),
                          _("Video on Demand"), wx.OK | wx.ICON_WARNING)
            return

        # Show a placeholder while episodes are fetched.
        self._populate_token += 1
        IPTVClient._replace_displayed(self, [
            {"type": "vod_back", "label": _("◄ Back")},
            {"type": "vod_info", "label": _("Loading episodes…")},
        ])
        self.channel_list.SetSelection(0)
        self.url_display.SetValue("")
        token = self._vod_load_token

        def worker():
            try:
                episodes = vod.xtream_series_episodes(client, series_id, series.get("provider-id"))
            except Exception as e:
                wx.CallAfter(lambda err=e: message_box(
                    _("Could not load episodes:\n{error}").format(error=err),
                    _("Video on Demand"), wx.OK | wx.ICON_ERROR))
                return
            wx.CallAfter(self._on_series_episodes_ready, token, name, episodes)

        threading.Thread(target=worker, daemon=True).start()

    def _on_series_episodes_ready(self, token: int, name: str, episodes: List[Dict]):
        if token != self._vod_load_token or self.view_mode != "vod":
            return
        self._vod_show_episodes(name, episodes)

    def _vod_show_episodes(self, name: str, episodes: List[Dict]):
        displayed = [{"type": "vod_back", "label": _("◄ Back")}]
        for ep in episodes:
            displayed.append({"type": "channel", "data": ep})
        self._populate_token += 1
        IPTVClient._replace_displayed(self, displayed)
        if not episodes:
            self.channel_list.SetSelection(0)
            self.url_display.SetValue(_("No episodes found for this series."))
            return
        # Select the first episode (not the Back row) so playback is one keypress away.
        self.channel_list.SetSelection(1)
        if self.IsShown() and not self.IsIconized():
            self.channel_list.SetFocus()
        self.on_highlight()

    def _vod_go_back(self):
        label = self._vod_series_return_group or self.vod_current_group
        self._vod_series_return_group = None
        if label and label in self.vod_groups:
            self.vod_current_group = label
            self._vod_show_items(self.vod_groups.get(label, []))
        else:
            self._refresh_vod_group_ui()

    def _vod_apply_filter(self, txt: str):
        """Substring-filter the current VOD category by item name."""
        if not self.vod_current_group:
            return
        items = self.vod_groups.get(self.vod_current_group, [])
        if not txt:
            self._vod_show_items(items)
            return
        needle = txt.lower()
        filtered = [it for it in items if needle in (it.get("name", "").lower())]
        self._vod_show_items(filtered)

    def reload_epg_sources(self):
        base = list(self.config.get("epgs", []))
        for epg in getattr(self, "provider_epg_sources", []):
            if epg not in base:
                base.append(epg)
        self.epg_sources = base

    def _hash_epg_sources(self, sources: List[str]) -> str:
        normalized = []
        for src in sources:
            if isinstance(src, str):
                normalized.append(src.strip())
            else:
                try:
                    normalized.append(json.dumps(src, sort_keys=True))
                except Exception:
                    normalized.append(str(src))
        normalized.sort()
        payload = "|".join(normalized).encode("utf-8", "ignore")
        return hashlib.sha1(payload).hexdigest()

    def _get_epg_auto_interval_seconds(self) -> float:
        raw = self.config.get("epg_auto_import_interval_hours", 6.0)
        try:
            hours = float(raw)
        except Exception:
            hours = 6.0
        if hours <= 0:
            return 0.0
        return hours * 3600.0

    def _should_auto_import_epg(self, sources: List[str]) -> bool:
        interval = self._get_epg_auto_interval_seconds()
        if interval <= 0:
            return True
        try:
            last_hash = self.config.get("epg_last_sources_hash", "")
        except Exception:
            last_hash = ""
        current_hash = self._hash_epg_sources(sources)
        if current_hash and current_hash != last_hash:
            return True
        db_path = get_db_path()
        if not epg_database_has_usable_data(db_path):
            return True
        try:
            last_import = float(self.config.get("epg_last_import_epoch", 0) or 0)
        except Exception:
            last_import = 0.0
        now = time.time()
        if last_import <= 0 or last_import > now + 300:
            return True
        return (now - last_import) >= interval

    def _cancel_epg_autostart_timer(self):
        if self._epg_autostart_timer:
            try:
                self._epg_autostart_timer.Stop()
            except Exception:
                LOG.debug("IPTVClient._cancel_epg_autostart_timer: ignored exception", exc_info=True)
            self._epg_autostart_timer = None

    def _schedule_epg_autostart(self, token: int, delay_ms: int = 5000):
        def _fire():
            if token != self._playlist_load_token:
                return
            self._epg_autostart_timer = None
            self.start_epg_import_background()
        self._cancel_epg_autostart_timer()
        self._epg_autostart_timer = wx.CallLater(delay_ms, _fire)

    def _maybe_autostart_epg_import(self):
        if not self._pending_epg_autostart:
            return
        if self._pending_epg_autostart_token != self._playlist_load_token:
            return
        self._pending_epg_autostart = False
        self._schedule_epg_autostart(self._pending_epg_autostart_token)

    def start_epg_import_background(self, *, force: bool = False, notify: bool = False):
        """Kick off an EPG import on a worker thread.

        Returns True when an import was actually started. ``notify`` asks for a
        message box when it finishes - only the hand-started import from the
        File menu sets it, so the periodic automatic refresh stays quiet.
        """
        sources = list(self.epg_sources)
        if not sources or not self.config.get("epg_enabled", True):
            return False
        if self.epg_importing:
            return False
        if not force and not self._should_auto_import_epg(sources):
            return False
        self.epg_importing = True
        self._epg_import_notify = bool(notify)

        def do_import():
            _lower_current_thread_priority()
            success = False
            try:
                db = EPGDatabase(get_db_path(), for_threading=True)
                # Pass a coarse progress callback (per-source). The DB importer writes as it streams,
                # so readers can pick up newly inserted rows during import.
                db.import_epg_xml(sources)
                success = True
                try:
                    if hasattr(db, "close"):
                        db.close()
                    elif hasattr(db, "conn"):
                        db.conn.close()
                except Exception:
                    LOG.debug("IPTVClient.start_epg_import_background.do_import: ignored exception", exc_info=True)
            except Exception:
                LOG.debug("IPTVClient.start_epg_import_background.do_import: ignored exception", exc_info=True)
            finally:
                wx.CallAfter(self.finish_import_background, success)
        threading.Thread(target=do_import, daemon=True).start()
        return True

    def finish_import_background(self, success: bool = False):
        self.epg_importing = False
        notify = self._epg_import_notify
        self._epg_import_notify = False
        # Clear match cache as IDs/channels may have changed in the DB
        with self._epg_match_lock:
            self._epg_match_cache.clear()
        if success:
            try:
                self.config["epg_last_import_epoch"] = int(time.time())
                self.config["epg_last_sources_hash"] = self._hash_epg_sources(self.epg_sources)
                save_config(self.config)
            except Exception:
                LOG.debug("IPTVClient.finish_import_background: ignored exception", exc_info=True)
        # The rows read the on-air programme, so refresh the bulk labels now
        # that new EPG data may have arrived.
        threading.Thread(target=self._refresh_now_playing_labels, daemon=True).start()
        self.on_highlight()
        if notify:
            # Reported last, so the guide is already reloaded behind the box.
            self._report_epg_import_finished(success)

    def _report_epg_import_finished(self, success: bool) -> None:
        """Tell the user how the import they started by hand turned out.

        An import runs for anything from seconds to the better part of an hour
        with no window of its own, so without this the only way to know it had
        ended was to go looking for new programme data.
        """
        if success:
            self._show_or_queue_message_box(
                _("The EPG import has finished. The programme guide is up to date."),
                _("Import Complete"), wx.OK | wx.ICON_INFORMATION)
            return
        self._show_or_queue_message_box(
            _("The EPG import did not finish. The programme guide may be "
              "incomplete or unchanged.") + chr(10) + chr(10) + _(
                "Check that the EPG sources in File > EPG Manager are reachable, "
                "then try again."),
            _("Import Failed"), wx.OK | wx.ICON_WARNING)

    def show_manager(self, _):
        dlg = PlaylistManagerDialog(self, self.playlist_sources, self.config.get("playlist_names"))
        if dlg.ShowModal() == wx.ID_OK:
            self.playlist_sources = dlg.GetResult()
            self.config["playlists"] = self.playlist_sources
            self.config["playlist_names"] = dlg.GetNames()
            self._fill_playlist_scope_combo()
            save_config(self.config)
            self.start_playlist_load() # Reload everything after changes
        dlg.Destroy()

    def show_epg_manager(self, _):
        dlg = EPGManagerDialog(self, self.epg_sources, self.config.get("epg_names"))
        if dlg.ShowModal() == wx.ID_OK:
            self.epg_sources = dlg.GetResult()
            self.config["epgs"] = self.epg_sources
            self.config["epg_names"] = dlg.GetNames()
            save_config(self.config)
            self.reload_epg_sources()
            wx.CallLater(1000, lambda: self.start_epg_import_background(force=True)) # Start import after dialog closes
        dlg.Destroy()

    def show_account_info(self, _event):
        """Show subscription status for configured and autodetected accounts."""
        # Discovery walks every loaded channel URL to autodetect accounts that
        # were never added through the Xtream dialog, so keep it off the UI thread.
        sources = list(self.playlist_sources or [])
        channels = self.all_channels

        def worker():
            error = None
            accounts = []
            try:
                accounts = account_info.discover_accounts(sources, channels)
            except Exception as e:
                error = str(e)
                LOG.debug("show_account_info: discovery failed", exc_info=True)
            wx.CallAfter(self._present_account_info, accounts, error)

        threading.Thread(target=worker, daemon=True).start()

    def _present_account_info(self, accounts, error):
        if error is not None:
            message_box(
                _("Could not look for provider accounts: {error}").format(error=error),
                _("Error"), wx.OK | wx.ICON_ERROR)
            return
        if not accounts:
            message_box(
                _("No provider accounts were found.\n\n"
                  "Xtream Codes and Stalker Portal accounts added in the Playlist Manager "
                  "are listed here, along with any account detected from a playlist or "
                  "stream URL."),
                _("No Accounts"), wx.OK | wx.ICON_INFORMATION)
            return
        dlg = AccountInfoDialog(self, accounts)
        dlg.ShowModal()
        dlg.Destroy()

    def import_epg(self, _event):
        if self.epg_importing:
            message_box(_("EPG import is already in progress."), _("In Progress"), wx.OK | wx.ICON_INFORMATION)
            return

        if not self.epg_sources:
            message_box(_("No EPG sources configured. Please add one in File > EPG Manager."), _("No Sources"), wx.OK | wx.ICON_WARNING)
            return

        if not self.config.get("epg_enabled", True):
            message_box(_("EPG is not enabled."), _("EPG Not Available"), wx.OK | wx.ICON_WARNING)
            return

        # Start first, announce second: the announcement promises a completion
        # message, so it must not be shown for an import that never began.
        if not self.start_epg_import_background(force=True, notify=True):
            message_box(_("The EPG import could not be started."), _("Import Failed"),
                        wx.OK | wx.ICON_WARNING)
            return

        message_box(
            _("EPG import will start in the background. You can keep using the "
              "app; a message will tell you when the import has finished."),
            _("Import Started"), wx.OK | wx.ICON_INFORMATION)

    def show_whats_on_now(self, _event):
        """Show dialog with all currently airing programs."""
        if not self.config.get("epg_enabled", True):
            message_box(_("EPG is not enabled."), _("EPG Not Available"), wx.OK | wx.ICON_WARNING)
            return

        # Fetching every currently-airing programme can touch a lot of rows on a large EPG,
        # so do the DB work on a background thread and present the dialog when it's ready.
        def worker():
            error = None
            programs = []
            try:
                db = EPGDatabase(get_db_path(), readonly=True)
                try:
                    programs = db.get_all_now_playing()
                finally:
                    db.close()
            except Exception as e:
                error = e
            wx.CallAfter(self._present_whats_on_now, programs, error)

        threading.Thread(target=worker, daemon=True).start()

    def _present_whats_on_now(self, programs, error):
        if error is not None:
            message_box(_("Failed to fetch EPG data: {error}").format(error=error), _("Error"), wx.OK | wx.ICON_ERROR)
            return
        if not programs:
            message_box(_("No programs are currently airing, or EPG data has not been imported yet."), _("No Data"), wx.OK | wx.ICON_INFORMATION)
            return

        dlg = WhatsOnNowDialog(self, programs, schedule_callback=self._schedule_epg_program_recording)
        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.get_selection()
            if selection:
                self._play_from_whats_on_now(selection)
        dlg.Destroy()
    
    def _play_from_whats_on_now(self, program: Dict[str, str]):
        """Find and play the channel matching the selected program."""
        channel_name = program.get("channel_name", "")
        channel_id = program.get("channel_id", "")
        
        if not channel_name and not channel_id:
            message_box(_("Could not identify the channel."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        matching_channel = self._find_matching_channel_for_program(program)
        if not matching_channel:
            message_box(_("Could not find channel '{channel}' in your playlist.").format(channel=channel_name), _("Channel Not Found"), wx.OK | wx.ICON_WARNING)
            return

        # Find and select the channel in the currently displayed list
        for idx, item in enumerate(self.displayed):
            if item.get("type") == "channel":
                ch = item.get("data", {})
                if ch.get("url") == matching_channel.get("url"):
                    self.channel_list.SetSelection(idx)
                    # Use CallAfter to ensure UI updates before play
                    wx.CallAfter(self.play_selected)
                    return
        
        # Channel exists but not in current filter - switch to All Channels and try again
        self.group_list.SetSelection(0)  # "All Channels" is first
        self.on_group_select()
        wx.CallLater(100, lambda: self._select_and_play_channel(matching_channel))
    
    def _select_and_play_channel(self, channel: Dict[str, str]):
        """Helper to select and play a channel after group switch."""
        for idx, item in enumerate(self.displayed):
            if item.get("type") == "channel":
                ch = item.get("data", {})
                if ch.get("url") == channel.get("url"):
                    self.channel_list.SetSelection(idx)
                    wx.CallAfter(self.play_selected)
                    return

    def _parse_m3u_return(self, text, provider_info=None):
        provider_info = provider_info or {}
        provider_id = provider_info.get("provider-id")
        provider_type = provider_info.get("provider-type")

        out: List[Dict[str, str]] = []
        append = out.append
        stream_id_for = self._extract_stream_id
        attr_iter = _M3U_ATTR_RE.finditer

        # Per-channel metadata, reset after each URL
        name = ""
        group = ""
        tvg_id = ""
        tvg_name = ""
        tvg_logo = ""
        tvg_rec = ""
        timeshift = ""
        catchup = ""
        catchup_type = ""
        catchup_days = ""
        catchup_source = ""
        catchup_offset = ""
        http_user_agent = ""
        http_referrer = ""
        http_origin = ""
        http_cookie = ""
        http_headers: List[str] = []
        http_auth = ""
        http_accept = ""

        for raw_line in text.splitlines():
            s = raw_line.strip()
            if not s:
                continue

            if s[0] == '#':
                upper_prefix = s[:10].upper()
                if upper_prefix.startswith("#EXTINF"):
                    name = ""
                    group = ""
                    tvg_id = ""
                    tvg_name = ""
                    tvg_logo = ""
                    tvg_rec = ""
                    timeshift = ""
                    catchup = ""
                    catchup_type = ""
                    catchup_days = ""
                    catchup_source = ""
                    catchup_offset = ""
                    http_user_agent = ""
                    http_referrer = ""
                    http_origin = ""
                    http_cookie = ""
                    http_headers = []
                    http_auth = ""
                    http_accept = ""

                    comma_idx = _extinf_name_comma(s)
                    info_part = s if comma_idx == -1 else s[:comma_idx]
                    if comma_idx != -1:
                        name = s[comma_idx + 1:].strip()

                    colon_idx = info_part.find(':')
                    attr_segment = info_part[colon_idx + 1:] if colon_idx != -1 else ""
                    if attr_segment:
                        attrs: Dict[str, str] = {}
                        for match in attr_iter(attr_segment):
                            key = match.group(1).lower()
                            value = match.group(2) or match.group(3) or match.group(4) or ""
                            if key not in attrs:
                                attrs[key] = value.strip()
                        if attrs:
                            group = attrs.get("group-title", "")
                            tvg_id = attrs.get("tvg-id", "")
                            tvg_name = attrs.get("tvg-name", "")
                            tvg_logo = attrs.get("tvg-logo") or attrs.get("logo") or ""
                            tvg_rec = attrs.get("tvg-rec", "")
                            timeshift = attrs.get("timeshift", "")
                            catchup = attrs.get("catchup", "")
                            catchup_type = attrs.get("catchup-type", "")
                            catchup_days = attrs.get("catchup-days", "")
                            catchup_source = attrs.get("catchup-source", "")
                            catchup_offset = attrs.get("catchup-offset", "")
                            http_user_agent = attrs.get("http-user-agent", "")
                            http_referrer = attrs.get("http-referrer") or attrs.get("http-referer", http_referrer)
                            http_origin = attrs.get("http-origin", http_origin)
                            http_cookie = attrs.get("http-cookie", http_cookie)
                            http_auth = attrs.get("http-authorization", http_auth)
                            http_accept = attrs.get("http-accept", http_accept)
                    continue

                if upper_prefix.startswith("#EXTVLCOPT"):
                    colon_idx = s.find(':')
                    if colon_idx != -1:
                        data = s[colon_idx + 1:]
                        eq_idx = data.find('=')
                        if eq_idx != -1:
                            key = data[:eq_idx].strip().lower()
                            value = data[eq_idx + 1:].strip()
                            if key in {"catchup-source", "catchup_url"}:
                                catchup_source = value
                            elif key == "catchup-days":
                                catchup_days = value
                            elif key == "catchup-type":
                                catchup_type = value
                            elif key == "http-user-agent":
                                http_user_agent = value
                            elif key in {"http-referrer", "http-referer", "referer", "referrer"}:
                                http_referrer = value
                            elif key in {"http-origin", "origin"}:
                                http_origin = value
                            elif key in {"http-cookie", "cookie"}:
                                http_cookie = value
                            elif key in {"http-authorization", "authorization", "auth"}:
                                http_auth = value
                            elif key in {"http-accept", "accept"}:
                                http_accept = value
                            elif key.startswith("http-header"):
                                if value:
                                    http_headers.append(value)
                    continue

                if upper_prefix.startswith("#KODIPROP"):
                    colon_idx = s.find(':')
                    if colon_idx != -1:
                        data = s[colon_idx + 1:]
                        eq_idx = data.find('=')
                        if eq_idx != -1:
                            key = data[:eq_idx].strip().lower()
                            value = data[eq_idx + 1:].strip()
                            if key.endswith("catchup_days"):
                                catchup_days = value
                            elif key.endswith("catchup_source"):
                                catchup_source = value
                            elif key in {"http-referrer", "http-referer", "referer", "referrer"}:
                                http_referrer = value
                            elif key in {"http-origin", "origin"}:
                                http_origin = value
                            elif key in {"http-cookie", "cookie"}:
                                http_cookie = value
                            elif key in {"http-authorization", "authorization", "auth"}:
                                http_auth = value
                            elif key in {"http-accept", "accept"}:
                                http_accept = value
                    continue

                # Other comment/directive lines are ignored
                continue

            url = s
            # Channels with no explicit group-title fall to "Uncategorized"
            # (see the `ch.get("group") or "Uncategorized"` grouping below) rather
            # than being bucketed by a country code guessed from the name. That
            # guessing produced confusing giant "us"/"ca" groups that mixed
            # unrelated channels and swept in malformed entries.
            grp_value = group
            channel = {
                "name": name,
                "group": grp_value,
                "url": url,
                "tvg-id": tvg_id,
                "tvg-name": tvg_name,
            }
            if provider_id:
                channel["provider-id"] = provider_id
            if provider_type:
                channel["provider-type"] = provider_type
            if tvg_logo:
                channel["tvg-logo"] = tvg_logo
            if tvg_rec:
                channel["tvg-rec"] = tvg_rec
            if timeshift:
                channel["timeshift"] = timeshift
            if catchup:
                channel["catchup"] = catchup
            if catchup_type:
                channel["catchup-type"] = catchup_type
            if catchup_days:
                channel["catchup-days"] = catchup_days
            if catchup_source:
                channel["catchup-source"] = catchup_source
            if catchup_offset:
                channel["catchup-offset"] = catchup_offset
            if http_user_agent:
                channel["http-user-agent"] = http_user_agent
            if http_referrer:
                channel["http-referrer"] = http_referrer
            if http_origin:
                channel["http-origin"] = http_origin
            if http_cookie:
                channel["http-cookie"] = http_cookie
            if http_auth:
                channel["http-authorization"] = http_auth
            if http_accept:
                channel["http-accept"] = http_accept
            if http_headers:
                # Preserve header order but drop duplicates case-insensitively.
                seen_headers = set()
                unique_headers: List[str] = []
                for hdr in http_headers:
                    key_lower = hdr.split(":", 1)[0].strip().lower() if ":" in hdr else hdr.lower()
                    if key_lower in seen_headers:
                        continue
                    seen_headers.add(key_lower)
                    unique_headers.append(hdr)
                channel["http-headers"] = unique_headers

            if provider_type == "xtream" or catchup_source:
                stream_id = stream_id_for(url)
                if stream_id:
                    channel["stream-id"] = stream_id

            append(channel)

            # Clear state after emitting the channel entry
            name = ""
            group = ""
            tvg_id = ""
            tvg_name = ""
            tvg_logo = ""
            tvg_rec = ""
            timeshift = ""
            catchup = ""
            catchup_type = ""
            catchup_days = ""
            catchup_source = ""
            catchup_offset = ""
            http_user_agent = ""
            http_referrer = ""
            http_origin = ""
            http_cookie = ""
            http_headers = []
            http_auth = ""
            http_accept = ""

        return out

    def _playlist_text_hash(self, text: str) -> str:
        if not text:
            return ""
        return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()

    def _parsed_cache_path_for_key(self, key: str) -> str:
        digest = hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest()
        cache_dir = get_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"parsed_{digest}.json")

    def _read_cached_playlist_file(
        self, cache_path: str
    ) -> Tuple[Optional[str], Optional[List[Dict[str, str]]]]:
        """Raw (hash, channels) read of a parsed-cache JSON file, no hash check/mutation.
        Split out of _load_cached_playlist so callers that already have the parsed
        result (e.g. the playlist-load prefill pass) can share it instead of paying
        for the disk read + JSON decode a second time."""
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            channels = data.get("channels")
            if not isinstance(channels, list):
                return None, None
            return data.get("hash"), channels
        except Exception:
            return None, None

    def _apply_cached_provider_meta(self, channels: List[Dict[str, str]], provider_meta: Optional[Dict[str, str]]) -> None:
        if not provider_meta:
            return
        pid = provider_meta.get("provider-id")
        ptype = provider_meta.get("provider-type")
        if not pid and not ptype:
            return
        for ch in channels:
            if pid:
                ch["provider-id"] = pid
            if ptype:
                ch["provider-type"] = ptype

    def _load_cached_playlist(
        self,
        cache_path: str,
        text_hash: Optional[str],
        provider_meta: Optional[Dict[str, str]] = None,
        skip_hash: bool = False,
    ) -> Optional[List[Dict[str, str]]]:
        try:
            stored_hash, channels = self._read_cached_playlist_file(cache_path)
            if channels is None:
                return None
            if not skip_hash and text_hash is not None and stored_hash != text_hash:
                return None
            self._apply_cached_provider_meta(channels, provider_meta)
            return channels
        except Exception:
            return None

    def _store_cached_playlist(
        self,
        cache_path: str,
        text_hash: str,
        channels: List[Dict[str, str]],
        provider_meta: Optional[Dict[str, str]] = None,
    ) -> None:
        payload = {"hash": text_hash, "channels": channels}
        if provider_meta:
            payload["provider"] = provider_meta
        tmp_path = cache_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
            os.replace(tmp_path, cache_path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                LOG.debug("IPTVClient._store_cached_playlist: ignored exception", exc_info=True)

    def _extract_stream_id(self, url: str) -> str:
        try:
            path = urllib.parse.urlparse(url).path
        except Exception:
            path = ""
        if not path:
            return ""
        parts = [p for p in path.split("/") if p]
        if not parts:
            return ""
        last = parts[-1]
        m = re.match(r"(\d+)", last)
        if m:
            return m.group(1)
        if len(parts) >= 2:
            m = re.match(r"(\d+)", parts[-2])
            if m:
                return m.group(1)
        return ""

    def on_group_select(self):
        if getattr(self, "view_mode", "live") == "vod":
            self._vod_on_group_select()
            return
        sel = self.group_list.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        all_label = _("All Channels")
        label = self.group_list.GetString(sel) if sel != wx.NOT_FOUND else all_label
        # Prefer the parallel key list so group names containing " (" are not
        # truncated by label round-tripping; fall back to the label only when
        # the key list is out of sync.
        if 0 <= sel < len(self._group_keys):
            grp = self._group_keys[sel]
        elif label.startswith(all_label) or label.startswith("All Channels"):
            grp = "All Channels"
        else:
            grp = label.split(" (", 1)[0]
        self.current_group = grp

        source = self._source_for_group(grp)
        self._populate_channel_list_chunked(source)

    def _populate_channel_list_chunked(self, source: List[Dict[str, str]]):
        self._populate_token += 1

        IPTVClient._replace_displayed(self, [
            {"type": "channel", "data": ch}
            for ch in source
        ])

        if not source:
            self.url_display.SetValue("")
            self._maybe_autostart_epg_import()
            return

        self.channel_list.SetSelection(0)
        # Only set focus if window is visible (avoid stealing focus from tray).
        if self.IsShown() and not self.IsIconized():
            self.channel_list.SetFocus()
        self.on_highlight()
        self._maybe_autostart_epg_import()

    def _fmt_time(self, s):
        # s: "YYYYMMDDHHMMSS" (UTC)
        try:
            dt = datetime.datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            local = utc_to_local(dt)
            return local.strftime("%H:%M")
        except Exception:
            return "?"

    def _utc_now(self) -> datetime.datetime:
        try:
            return datetime.datetime.now(datetime.timezone.utc)
        except Exception:
            return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    def on_highlight(self):
        self._update_recording_menu_state()
        i = self.channel_list.GetSelection()
        if i < 0 or i >= len(self.displayed):
            self.url_display.SetValue("")
            self._set_episode_description("")
            return
        item = self.displayed[i]
        if item["type"] == "vod_series":
            self.url_display.SetValue("")
            self._set_episode_description("")
            return
        if item["type"] in ("vod_back", "vod_info"):
            self.url_display.SetValue("")
            self._set_episode_description("")
            return
        if item["type"] == "channel":
            ch = item["data"]
            self.url_display.SetValue(ch.get("url", ""))
            # The description field reads the on-air programme of the
            # highlighted channel from the bulk now-playing cache.
            self._set_episode_description(getattr(
                self, "_now_playing_descriptions", {}).get(
                canonicalize_name(ch.get("name", "")), ""))
        elif item["type"] == "epg":
            self.url_display.SetValue("")
            r = item["data"]
            url = ""
            target_norm = canonicalize_name(r.get("channel_name", ""))
            for ch in self.all_channels:
                if canonicalize_name(ch.get("name", "")) == target_norm:
                    url = ch.get("url", "")
                    break
            self.url_display.SetValue(url)
            self._set_episode_description(r.get("description") or "")

    def _epg_msg_from_tuple(self, now, nxt):
        def localfmt(dt):
            local = utc_to_local(dt)
            return local.strftime('%H:%M')
        def description(show):
            return (show.get('description') or "").strip() if show else ""
        msg = ""
        if now:
            msg += _("Now: {title} ({start} – {end})").format(
                title=now['title'], start=localfmt(now['start']), end=localfmt(now['end']))
            desc = description(now)
            if desc:
                msg += "\n" + desc
        elif nxt:
            msg += _("Starts at {start}: {title}").format(
                start=localfmt(nxt['start']), title=nxt['title'])
            desc = description(nxt)
            if desc:
                msg += "\n" + desc
        else:
            msg += _("No program currently airing.")
        if nxt:
            msg += "\n" + _("Next: {title} ({start} – {end})").format(
                title=nxt['title'], start=localfmt(nxt['start']), end=localfmt(nxt['end']))
            if now:
                # The description of the current show was already shown above.
                desc = description(nxt)
                if desc:
                    msg += "\n" + desc
        return msg

    def _find_channel_for_epg(self, show: Dict[str, str]) -> Optional[Dict[str, str]]:
        return self._find_matching_channel_for_program(show)

    def _channel_has_catchup(self, channel: Dict[str, str]) -> bool:
        if channel.get("catchup-source") or channel.get("catchup"):
            return True
        if _implicit_catchup_source(channel):
            return True
        if channel.get("provider-type") == "stalker":
            pdata = channel.get("provider-data") or {}
            return bool(pdata.get("allow_timeshift") or pdata.get("archive"))
        return False

    def _parse_epg_time(self, value: str) -> datetime.datetime:
        dt = datetime.datetime.strptime(value, "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=datetime.timezone.utc)

    def _resolve_show_url(self, channel: Dict[str, str], show: Dict[str, str]) -> tuple:
        start_dt = self._parse_epg_time(show.get("start"))
        end_dt = self._parse_epg_time(show.get("end"))
        now = datetime.datetime.now(datetime.timezone.utc)

        if start_dt <= now <= end_dt:
            return self._resolve_live_url(channel), False

        if end_dt < now:
            if not self._channel_has_catchup(channel):
                raise ProviderError("This channel does not provide catch-up streaming.")
            if not self._within_catchup_window(channel, start_dt):
                raise ProviderError("This programme is older than the catch-up window allows.")
            url = self._resolve_catchup_url(channel, start_dt, end_dt)
            if not url:
                raise ProviderError("Unable to construct catch-up URL for this programme.")
            return url, True

        # Future programme: return live stream so playback starts when available.
        return self._resolve_live_url(channel), False

    def _within_catchup_window(self, channel: Dict[str, str], start_dt: datetime.datetime) -> bool:
        days = channel.get("catchup-days") or _positive_timeshift_days(channel)
        if not days:
            return True
        try:
            span = int(float(days))
        except (TypeError, ValueError):
            return True
        now = datetime.datetime.now(datetime.timezone.utc)
        return start_dt >= now - datetime.timedelta(days=span)

    def _resolve_live_url(self, channel: Dict[str, str]) -> str:
        url = channel.get("url", "")
        provider_type = channel.get("provider-type")
        provider_id = channel.get("provider-id")

        if provider_type == "stalker":
            if not provider_id:
                raise ProviderError("Stalker portal entry missing provider identifier.")
            client = self.provider_clients.get(provider_id)
            if not client:
                raise ProviderError("Stalker portal client is not initialized.")
            pdata = channel.get("provider-data") or {}
            url = client.resolve_stream(pdata)
            return url

        return url

    def _resolve_catchup_url(self, channel: Dict[str, str], start_dt: datetime.datetime, end_dt: datetime.datetime) -> str:
        provider_type = channel.get("provider-type")
        provider_id = channel.get("provider-id")
        if provider_type == "stalker" and provider_id:
            client = self.provider_clients.get(provider_id)
            if not client:
                raise ProviderError("Stalker portal client is not initialized.")
            pdata = channel.get("provider-data") or {}
            start_local = utc_to_local(start_dt)
            duration = max(1, int((end_dt - start_dt).total_seconds() // 60))
            start_str = start_local.strftime("%Y-%m-%d:%H-%M")
            return client.resolve_catchup(pdata, start_str, duration)

        return self._build_generic_catchup_url(channel, start_dt, end_dt)

    def _build_generic_catchup_url(self, channel: Dict[str, str], start_dt: datetime.datetime, end_dt: datetime.datetime) -> str:
        # Explicit metadata wins. If it is absent, known providers may expose
        # the equivalent information through their legacy timeshift attribute.
        source = channel.get("catchup-source") or _implicit_catchup_source(channel)
        if not source:
            return ""

        offset = channel.get("catchup-offset")
        offset_hours = 0.0
        try:
            if offset:
                offset_hours = float(offset)
        except (TypeError, ValueError):
            offset_hours = 0.0
            LOG.debug("IPTVClient._build_generic_catchup_url: ignored exception", exc_info=True)

        # Template style (catchup="append", e.g. teleelevidenie's
        # "?utc=${start}&lutc=${timestamp}"): fill the placeholders into the
        # template and append it to the channel's live URL.
        expanded = _expand_catchup_template(source, start_dt, end_dt, offset_hours)
        if expanded is not None:
            base = (channel.get("url") or "").split("|")[0].rstrip()
            if "?" in base and expanded.startswith("?"):
                expanded = "&" + expanded[1:]
            url = base + expanded
            ua = channel.get("http-user-agent")
            if ua and "|" not in url:
                url = f"{url}|User-Agent={urllib.parse.quote(ua)}"
            return url

        # Path style (?utc=/ catchup="xc"): rebuild <base>/<start>/<duration>/.
        stream_id = channel.get("stream-id") or self._extract_stream_id(channel.get("url", ""))
        if not stream_id:
            return ""

        src = source.rstrip('/')
        if not src:
            return ""
        last_segment = src.rsplit('/', 1)[-1]
        if not last_segment.isdigit():
            src = f"{src}/{stream_id}"

        start_local = utc_to_local(start_dt)
        end_local = utc_to_local(end_dt)
        try:
            if offset_hours:
                delta = datetime.timedelta(hours=offset_hours)
                start_local -= delta
                end_local -= delta
        except (TypeError, ValueError):
            LOG.debug("IPTVClient._build_generic_catchup_url: ignored exception", exc_info=True)

        # Compute duration from the UTC instants (DST-safe); the offset shifts start and end
        # equally, so it doesn't affect duration. start_token still uses adjusted local time.
        duration = max(1, int((end_dt - start_dt).total_seconds() // 60))
        start_token = start_local.strftime("%Y-%m-%d:%H-%M")
        ctype = (channel.get("catchup-type") or channel.get("catchup") or "xc").lower()
        if ctype in {"", "xc", "default", "catchup"}:
            url = f"{src}/{start_token}/{duration}/"
        elif ctype == "flussonic":
            archive_stamp = start_local.strftime("%Y%m%d%H%M%S")
            url = f"{src}/{archive_stamp}-{duration}.m3u8"
        else:
            url = f"{src}/{start_token}/{duration}/"

        ua = channel.get("http-user-agent")
        if ua:
            if "|" in url:
                url = f"{url}&User-Agent={urllib.parse.quote(ua)}"
            else:
                url = f"{url}|User-Agent={urllib.parse.quote(ua)}"
        return url

    def play_selected(self, *, show_internal_player: Optional[bool] = None):
        i = self.channel_list.GetSelection()
        if not (0 <= i < len(self.displayed)):
            return
        item = self.displayed[i]

        # VOD navigation rows: activating them browses rather than plays.
        if item["type"] == "vod_series":
            self._vod_open_series(item["data"])
            return
        if item["type"] == "vod_back":
            self._vod_go_back()
            return
        if item["type"] == "vod_info":
            return

        channel = None
        show = None
        if item["type"] == "channel":
            channel = item["data"]
        elif item["type"] == "epg":
            show = item["data"]
            channel = self._find_channel_for_epg(show)
            if not channel:
                message_box(_("Could not match this programme to a playlist channel."),
                              _("Not Found"), wx.OK | wx.ICON_WARNING)
                return
        else:
            return

        try:
            if show:
                url, _unused = self._resolve_show_url(channel, show)
            else:
                url = self._resolve_live_url(channel)
        except ProviderError as err:
            message_box(_("Provider error: {error}").format(error=err), _("Playback Error"), wx.OK | wx.ICON_ERROR)
            return
        except Exception as err:
            message_box(_("Could not resolve stream URL:\n{error}").format(error=err), _("Playback Error"), wx.OK | wx.ICON_ERROR)
            return

        display_name = None
        if channel:
            display_name = (channel.get("name")
                            or channel.get("tvg-name")
                            or channel.get("tvg_name")
                            or channel.get("tvg-id")
                            or channel.get("tvg_id"))
        stream_kind = "catchup" if show else "live"
        if show:
            show_title = show.get("show_title") or show.get("title")
            if show_title:
                if display_name:
                    display_name = f"{show_title} - {display_name}"
                else:
                    display_name = show_title
        if not display_name:
            display_name = _("IPTV Stream")
        if show_internal_player is None:
            show_internal_player = self.show_player_on_enter

        self._launch_stream(
            url,
            display_name,
            stream_kind=stream_kind,
            channel=channel,
            show_internal_player=show_internal_player,
        )

    def _on_internal_player_closed(self) -> None:
        was_catchup = getattr(self, "_internal_player_stream_kind", "live") == "catchup"
        catchup_return = getattr(self, "_catchup_return", None)
        self._catchup_return = None
        self._internal_player_frame = None
        self._internal_player_channel = None
        self._internal_player_audio_key = ""
        self._internal_player_stream_kind = "live"
        if was_catchup and catchup_return:
            # The programme was picked from a channel's catch-up list, so
            # closing the player goes back to that list, on that programme -
            # usually the next episode is what comes next - instead of
            # dropping the user at the top of the channel list.
            wx.CallAfter(self._return_to_catchup_list, catchup_return)

    def _return_to_catchup_list(self, catchup_return: Dict) -> None:
        """Reopen the catch-up list a closed catch-up playback started from."""
        try:
            if (not self or self.IsBeingDeleted() or not self.IsShown()
                    or getattr(self, "_suppress_recording_notifications", False)
                    or self._modal_box_is_open()
                    # A catch-up list for another channel, say: a second
                    # modal dialog on top of it would stack.
                    or _modal_dialog_is_open()
                    # Something is playing: do not pull the list over it.
                    or self._internal_player_has_media()):
                return
        except RuntimeError:
            return  # the frame is already gone: the app is quitting
        self._open_catchup_dialog(catchup_return.get("channel") or {},
                                  select_start=catchup_return.get("start", ""))

    def _return_to_catchup_after_download(self, channel, start: str) -> None:
        """After a box about a catch-up download: back to that channel's list.

        Download closes the catch-up list to start, so dismissing a box about
        that download used to leave the user at the channel list instead of on
        the programme they were trying to save.
        """
        if channel:
            wx.CallAfter(self._return_to_catchup_list,
                         {"channel": channel, "start": start or ""})

    def _ensure_internal_player(self) -> object:
        frame_class = _load_internal_player_frame_class()
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            try:
                if getattr(frame, "_destroyed", False):
                    frame = None
            except Exception:
                frame = None
        if frame:
            return frame
        settings = resolve_internal_player_settings(self.config)
        frame = frame_class(
            self,
            base_buffer_seconds=settings.base_buffer_seconds,
            max_buffer_seconds=settings.max_buffer_seconds,
            variant_max_mbps=settings.variant_max_mbps,
            on_cast=self._cast_from_internal_player,
            on_record=self._record_from_internal_player,
            on_close=self._on_internal_player_closed,
            preferred_audio_tracks=list(self.config.get("preferred_audio_tracks") or []),
            prefer_audio_description=self._bool_pref(self.config.get("prefer_audio_description", False)),
            on_last_track_changed=self._on_player_last_audio_track_changed,
            last_audio_track=str(self.config.get("last_audio_track") or ""),
            channel_audio_track=self._remembered_channel_audio_track(
                getattr(self, "_internal_player_audio_key", "")),
            audio_output_device=str(self.config.get("audio_output_device") or ""),
            on_audio_device=self._on_player_audio_device,
        )
        self._internal_player_frame = frame
        return frame

    @staticmethod
    def _channel_audio_key(channel: Optional[Dict[str, str]]) -> str:
        """Identity a channel keeps its remembered audio track under.

        Deliberately not :meth:`_channel_record_key`: that one includes the
        stream URL and the whole provider-data blob, which would bloat the
        config and lose the memory whenever a provider re-issues URLs. The
        display name is what stays the same for the user, and sharing it across
        playlists is a feature - the same channel from a second provider starts
        on the track already chosen for it.
        """
        if not isinstance(channel, dict):
            return ""
        name = (channel.get("name")
                or channel.get("tvg-name")
                or channel.get("tvg_name")
                or channel.get("tvg-id")
                or channel.get("tvg_id")
                or "")
        return str(name).strip().casefold()

    def _remembered_channel_audio_track(self, key: str) -> str:
        """The audio track this channel was last watched with, or ""."""
        if not key:
            return ""
        stored = self.config.get("channel_audio_tracks")
        if not isinstance(stored, dict):
            return ""
        return str(stored.get(key) or "").strip()

    def _remembered_channel_audio_track_index(self, key: str):
        """The track *slot* this channel was last watched with, or None.

        Kept beside the name memory because providers rename or renumber
        tracks between connections: when the remembered name no longer
        matches, the slot still points at the same audio. Optional[int] on
        purpose - None means "no memory", which is not the same as slot 0.
        """
        if not key:
            return None
        stored = self.config.get("channel_audio_track_indices")
        if not isinstance(stored, dict):
            return None
        index = stored.get(key)
        if isinstance(index, bool) or not isinstance(index, int):
            return None
        if index < 0 or index >= MAX_AUDIO_TRACKS:
            return None
        return index

    def _remember_channel_audio_track(self, key: str, name: str, index=None) -> bool:
        """Store this channel's track name (and slot). True when config changed.

        The slot rides along with every write so both memories stay in step:
        the name answers "which track did I pick", the slot survives the
        provider renaming it.
        """
        if not key or not name:
            return False
        stored = self.config.get("channel_audio_tracks")
        if not isinstance(stored, dict):
            stored = {}
        slots = self.config.get("channel_audio_track_indices")
        if not isinstance(slots, dict):
            slots = {}
        name_changed = stored.get(key) != name
        index_changed = slots.get(key) != index
        if not name_changed and not index_changed:
            return False
        # Re-insert at the end so the eviction in coerce_channel_audio_tracks
        # drops the channels nobody has watched in a long time first.
        stored.pop(key, None)
        stored[key] = name
        if index is None:
            slots.pop(key, None)
        else:
            slots.pop(key, None)
            slots[key] = index
        self.config["channel_audio_tracks"] = coerce_channel_audio_tracks(stored)
        self.config["channel_audio_track_indices"] = coerce_channel_audio_track_indices(slots)
        return True

    def _on_player_last_audio_track_changed(
            self, track_name: str, track_index=None) -> None:
        """Persist the track the user last chose by hand (survives restarts).

        Stored twice: against the channel that is playing, so it comes back the
        next time that channel is opened, and globally, so a channel with no
        memory of its own still starts on the track the user last chose.
        """
        name = (track_name or "").strip()
        if not name:
            return
        changed = self._remember_channel_audio_track(
            getattr(self, "_internal_player_audio_key", ""), name,
            track_index)
        if self.config.get("last_audio_track") != name:
            self.config["last_audio_track"] = name
            changed = True
        if not changed:
            return
        save_config(self.config)
        LOG.info("Last used audio track set to %s", name)

    def _on_player_audio_device(self, device_id: str) -> None:
        """Persist the audio output device chosen in the built-in player."""
        device_id = (device_id or "").strip()
        if self.config.get("audio_output_device", "") == device_id:
            return
        self.config["audio_output_device"] = device_id
        save_config(self.config)
        LOG.info("Audio output device set to %s", device_id or "system default")

    def _show_audio_preference_dialog(self, _event=None):
        dlg = AudioTrackPreferenceDialog(
            self,
            keywords=list(self.config.get("preferred_audio_tracks") or []),
            prefer_audio_description=self._bool_pref(self.config.get("prefer_audio_description", False)),
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            keywords = dlg.get_keywords()
            prefer_audio_description = dlg.get_prefer_audio_description()
        finally:
            dlg.Destroy()
        self.config["preferred_audio_tracks"] = keywords
        self.config["prefer_audio_description"] = prefer_audio_description
        save_config(self.config)
        # An open player picks the change up for the next channel it is given.
        frame = getattr(self, "_internal_player_frame", None)
        setter = getattr(frame, "set_preferred_audio_tracks", None) if frame is not None else None
        if callable(setter):
            try:
                setter(keywords, prefer_audio_description=prefer_audio_description)
            except Exception:
                LOG.debug("IPTVClient._show_audio_preference_dialog: ignored exception", exc_info=True)

    def _launch_stream(
        self,
        url: str,
        title: Optional[str] = None,
        *,
        stream_kind: str = "live",
        channel: Optional[Dict[str, str]] = None,
        show_internal_player: Optional[bool] = None,
        focus_player: bool = True,
    ):
        LOG.info("_launch_stream called: url=%s, title=%s, player=%s", url, title, self.default_player)
        if not url:
            LOG.warning("_launch_stream: No URL provided")
            message_box(_("Could not find stream URL for this selection."), _("Not Found"),
                          wx.OK | wx.ICON_WARNING)
            return
        if show_internal_player is None:
            show_internal_player = self.show_player_on_enter

        # Check if casting
        caster = getattr(self, "caster", None)
        if caster and caster.is_connected():
            try:
                device_name = caster.active_device.display_name

                # Run async cast play in background thread
                def do_cast():
                    try:
                        caster.play(url, title or _("IPTV Stream"), channel=channel)
                    except Exception as e:
                        err_msg = str(e)
                        # The current cast device is incompatible or unreachable
                        # for this stream. Drop the session so the user is not
                        # stuck re-trying the same dead device on every channel
                        # change — they can re-select from the cast menu.
                        try:
                            caster.disconnect()
                        except Exception:
                            LOG.debug("IPTVClient._launch_stream.do_cast: ignored exception", exc_info=True)
                        wx.CallAfter(lambda: message_box(
                            _("Casting failed: {error}").format(error=err_msg) + "\n\n"
                            + _("Disconnected from the cast device. "
                                "Open the cast menu to pick another device."),
                            _("Casting Error"), wx.OK | wx.ICON_ERROR))

                threading.Thread(target=do_cast, daemon=True).start()

                message_box(_("Casting to {device}...").format(device=device_name), _("Casting"), wx.OK | wx.ICON_INFORMATION)
                return
            except Exception as e:
                message_box(_("Failed to cast: {error}").format(error=e), _("Casting Error"), wx.OK | wx.ICON_ERROR)
                # Fallback to local player? No, user expects cast.
                return

        player = self.default_player
        stream_headers = channel_http_headers(channel)
        custom_path = self.config.get("custom_player_path", "")

        if player in {"Built-in Player", "player_Internal", "internal", "Internal"}:
            player = "Built-in Player"
            try:
                frame = self._ensure_internal_player()
            except InternalPlayerUnavailableError as err:
                detail = str(err)
                message_box(_("Built-in player unavailable:\n{detail}").format(detail=detail), _("Launch Error"), wx.OK | wx.ICON_ERROR)
                return
            display_title = title or _("IPTV Stream")
            try:
                if show_internal_player:
                    frame.Enable(True)
                    frame.Show()
                    if focus_player:
                        frame.Raise()
                        frame.SetFocus()
                else:
                    # Keep frame disabled and hidden to avoid accessibility focus.
                    frame.Enable(False)
                    frame.Hide()
                # The Record button in the player acts on this channel, so the
                # player has to know which one it is now showing.
                self._internal_player_channel = channel
                self._internal_player_stream_kind = stream_kind
                # The remembered track is per channel, so it has to be handed
                # over before play() arms the preference - and handed over even
                # when it is empty, or the previous channel's track would leak
                # into this one.
                self._internal_player_audio_key = self._channel_audio_key(channel)
                setter = getattr(frame, "set_channel_audio_track", None)
                if callable(setter):
                    setter(self._remembered_channel_audio_track(
                        self._internal_player_audio_key))
                index_setter = getattr(frame, "set_channel_audio_track_index", None)
                if callable(index_setter):
                    index_setter(self._remembered_channel_audio_track_index(
                        self._internal_player_audio_key))
                frame.play(
                    url,
                    display_title,
                    stream_kind=stream_kind,
                    headers=stream_headers,
                    video_visible=show_internal_player,
                    focus_controls=focus_player,
                )
                self._sync_internal_player_record_state()
                if not show_internal_player:
                    wx.CallAfter(self._restore_main_focus)
            except Exception as err:
                message_box(_("Failed to start built-in player:\n{error}").format(error=err), _("Launch Error"), wx.OK | wx.ICON_ERROR)
            return

        # External player launch
        ok, err = self.player_launcher.launch(player, url, custom_path)
        if not ok:
            message_box(_("Failed to launch {player}:\n{error}").format(player=player, error=err), _("Launch Error"), wx.OK | wx.ICON_ERROR)

    def _restore_main_focus(self) -> None:
        """Restore focus to channel list only if this window is active."""
        try:
            if self.IsShown() and self.IsActive():
                self.channel_list.SetFocus()
        except Exception:
            LOG.debug("IPTVClient._restore_main_focus: ignored exception", exc_info=True)

    def _record_from_internal_player(self) -> None:
        """Record (or stop recording) whatever the built-in player is showing."""
        channel = getattr(self, "_internal_player_channel", None)
        if not channel:
            message_box(_("Nothing is playing in the built-in player."),
                        _("Record"), wx.OK | wx.ICON_INFORMATION)
            return
        if getattr(self, "_internal_player_stream_kind", "live") != "live":
            # Catch-up already has its own finite-window download, which knows
            # when to stop; an open-ended live recording of it would not.
            message_box(
                _("This is a catch-up stream. Use Download in the catch-up "
                  "list to save it."),
                _("Record"), wx.OK | wx.ICON_INFORMATION)
            return
        self._record_channel(channel)
        self._sync_internal_player_record_state()

    def _sync_internal_player_record_state(self) -> None:
        """Keep the player's Record button in step with the recorder."""
        frame = getattr(self, "_internal_player_frame", None)
        if frame is None or not hasattr(frame, "set_recording_state"):
            return
        channel = getattr(self, "_internal_player_channel", None)
        try:
            active = bool(channel and self.recorder.is_recording(
                self._channel_record_key(channel)))
            frame.set_recording_state(active)
        except Exception:
            LOG.debug("IPTVClient._sync_internal_player_record_state: ignored exception",
                      exc_info=True)

    def _cast_from_internal_player(self, url: str, title: str, headers: Dict[str, object]) -> None:
        if not url:
            message_box(_("No active stream to cast."), _("Casting"), wx.OK | wx.ICON_WARNING)
            return

        caster = self._ensure_caster()

        def do_cast(device):
            try:
                creds = self.config.get("cast_credentials", {}).get(device.identifier)
                caster.connect(device, credentials=creds)
                # Use the active caster directly so we can forward headers from the current stream.
                if caster.active_caster:
                    caster.dispatch(caster.active_caster.play(url, title, headers=headers))
                else:
                    raise RuntimeError("Caster not connected.")
                wx.CallAfter(self._handoff_internal_player_after_cast, url, title)
                wx.CallAfter(lambda: message_box(_("Casting to {device}...").format(device=device.display_name), _("Casting"), wx.OK | wx.ICON_INFORMATION))
            except Exception as e:
                wx.CallAfter(lambda err=e: message_box(_("Failed to cast: {error}").format(error=err), _("Casting Error"), wx.OK | wx.ICON_ERROR))

        if caster.is_connected() and caster.active_device:
            threading.Thread(target=lambda: do_cast(caster.active_device), daemon=True).start()
            return

        dlg = CastDiscoveryDialog(self, caster)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                device = dlg.get_selected_device()
                if device:
                    threading.Thread(target=lambda: do_cast(device), daemon=True).start()
        finally:
            dlg.Destroy()

    def _handoff_internal_player_after_cast(self, url=None, title=None, stream_kind=None, channel=None):
        # Stop and hide the built-in player, then (optionally) relaunch the stream
        # in the user's preferred external player. Guard all variables to avoid
        # NameErrors when called without arguments.
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            try:
                if url is None:
                    url = getattr(frame, "_current_url", None) or getattr(frame, "_last_resolved_url", None)
                if title is None:
                    title = getattr(frame, "_current_title", None)
                if stream_kind is None:
                    stream_kind = getattr(frame, "_current_stream_kind", None)
            except Exception:
                LOG.debug("IPTVClient._handoff_internal_player_after_cast: ignored exception", exc_info=True)
            try:
                frame.stop(manual=True)
            except Exception:
                LOG.debug("IPTVClient._handoff_internal_player_after_cast: ignored exception", exc_info=True)
            try:
                frame.Hide()
            except Exception:
                LOG.debug("IPTVClient._handoff_internal_player_after_cast: ignored exception", exc_info=True)

        player = self.default_player
        
        # If the user prefers the built-in player, just stop/hide and return.
        if player in {"Built-in Player", "player_Internal", "internal", "Internal"}:
            return

        # Ensure we have sane defaults.
        if not title:
            title = "IPTV Stream"
        if not stream_kind:
            stream_kind = "live"
        # If we don't have a URL, there's nothing to hand off.
        if not url:
            return

        # Use generic launch method for external player
        self._launch_stream(url, title, stream_kind=stream_kind, channel=channel, show_internal_player=False)

    def _open_catchup_dialog(self, channel: Dict[str, str], select_start: str = ""):
        programmes = self._get_catchup_programmes(channel)
        if not programmes:
            message_box(_("No catch-up programmes are available for this channel."),
                          _("Catch-up"), wx.OK | wx.ICON_INFORMATION)
            return
        dlg = CatchupDialog(self, channel.get("name", ""), programmes,
                            initial_start=select_start)
        try:
            action = dlg.ShowModal()
            if action not in (wx.ID_OK, wx.ID_SAVE):
                return
            selected = dlg.get_selection()
            if not selected:
                return
            show = {
                "channel_id": selected.get("channel_id", ""),
                "channel_name": channel.get("name", selected.get("channel_name", "")),
                "show_title": selected.get("title", ""),
                "start": selected.get("start", ""),
                "end": selected.get("end", "")
            }
            if action == wx.ID_SAVE:
                self._download_catchup_programme(channel, show)
                return
            try:
                url, _unused = self._resolve_show_url(channel, show)
            except ProviderError as err:
                message_box(_("Provider error: {error}").format(error=err), _("Catch-up"), wx.OK | wx.ICON_ERROR)
                return
            except Exception as err:
                message_box(_("Unable to prepare catch-up stream:\n{error}").format(error=err), _("Catch-up"), wx.OK | wx.ICON_ERROR)
                return
            display = (selected.get("title") or channel.get("name", "IPTV Stream"))
            self._launch_stream(url, display, stream_kind="catchup", channel=channel)
            # Read back by _on_internal_player_closed, and only for a catch-up
            # stream, so a live channel played later never reopens this list.
            self._catchup_return = {"channel": channel, "start": selected.get("start", "")}
        finally:
            dlg.Destroy()

    def _download_catchup_programme(self, channel: Dict[str, str], show: Dict[str, str]):
        """Save a completed catch-up programme using its finite EPG time window."""
        try:
            start_dt = self._parse_epg_time(show.get("start", ""))
            end_dt = self._parse_epg_time(show.get("end", ""))
            duration = max(1.0, (end_dt - start_dt).total_seconds())
            url, is_catchup = self._resolve_show_url(channel, show)
            if not is_catchup:
                raise ProviderError(_("This programme is not available as catch-up content yet."))
        except ProviderError as err:
            message_box(_("Provider error: {error}").format(error=err), _("Catch-up Download"),
                          wx.OK | wx.ICON_ERROR)
            self._return_to_catchup_after_download(channel, show.get("start", ""))
            return
        except Exception as err:
            message_box(_("Unable to prepare catch-up download:\n{error}").format(error=err),
                          _("Catch-up Download"), wx.OK | wx.ICON_ERROR)
            self._return_to_catchup_after_download(channel, show.get("start", ""))
            return

        title = show.get("show_title") or show.get("title") or self._channel_display_name(channel)
        display_name = _("{title} - {channel}").format(
            title=title, channel=self._channel_display_name(channel))
        identity = "{channel}|{start}|{end}".format(
            channel=self._channel_record_key(channel), start=show.get("start", ""), end=show.get("end", ""))
        key = "catchup:" + hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()
        if self.recorder.is_recording(key):
            message_box(_("This catch-up programme is already downloading."),
                          _("Catch-up Download"), wx.OK | wx.ICON_INFORMATION)
            self._return_to_catchup_after_download(channel, show.get("start", ""))
            return
        fmt = normalize_recording_format(self.config.get("recording_format"))
        audio_intent = self._recording_audio_intent(channel)
        # The fast direct-URL probe does network work; keep it off the GUI
        # thread. If no direct file exists we fall back to the HLS URL.
        threading.Thread(
            target=self._begin_catchup_download,
            args=(channel, url, display_name, key, show, duration, fmt, None, audio_intent),
            daemon=True,
        ).start()

    def _begin_catchup_download(self, channel, hls_url, display_name, key, show,
                                duration, fmt, retry_of: Optional[int] = None,
                                audio_intent=None):
        """Worker thread: probe for the fast direct file, then start on the UI thread.

        ``retry_of`` is the recorder id of a failed attempt this run replaces;
        the retry budget travels with it so attempts cannot multiply.
        """
        # A catch-up URL built from a ``catchup="append"`` template carries the
        # channel's M3U ``|User-Agent=...`` tail. Players understand that pipe;
        # a HEAD probe and ffmpeg do not - it goes out as part of the query
        # string, so every direct-file probe fails and the download quietly
        # falls back to the HLS playlist, which paces itself in real time.
        # Strip the tail and keep the headers it was carrying.
        fetch_url, url_headers = split_stream_modifiers(hls_url)
        headers = merge_headers(channel_http_headers(channel), url_headers)
        url = fetch_url
        try:
            start_epoch = int(self._parse_epg_time(show.get("start", "")).timestamp())
            direct = catchup_direct.direct_download_url(
                fetch_url, start_epoch, int(duration), headers)
            if direct:
                LOG.info("Catch-up: using fast direct download URL")
                url = direct
        except Exception:
            LOG.debug("Catch-up direct URL probe failed; using the HLS URL", exc_info=True)
        audio_choice = None
        if audio_intent:
            audio_choice = self._recording_audio_choice(url, headers, audio_intent)
            # Reading the tracks opened the stream. A one-stream provider holds
            # that session for a moment after it closes, and ffmpeg asking again
            # inside it is refused with 403 - on every retry, too.
            catchup_direct.settle_media_session()
        wx.CallAfter(self._start_catchup_recording, url, display_name, key, show,
                     duration, fmt, headers, channel, hls_url, retry_of,
                     audio_intent, audio_choice)

    def _start_catchup_recording(self, url, display_name, key, show, duration,
                                 fmt, headers, channel=None, hls_url=None,
                                 retry_of: Optional[int] = None,
                                 audio_intent=None, audio_choice=None):
        """UI thread: start the recorder and open the progress window."""
        if retry_of is not None and retry_of not in getattr(self, "_catchup_retry_state", {}):
            # Cancel was pressed while this retry was being prepared - the
            # "really cancel?" question easily outlasts the retry delay, and
            # the probe takes seconds. The user said stop: start nothing.
            LOG.info("Catch-up download retry for %s was cancelled", display_name)
            self._close_catchup_dialog(retry_of)
            return
        if retry_of is not None:
            # A retry replaces the previous attempt: close its progress window
            # (it is showing the error and countdown) and carry the budget over.
            self._close_catchup_dialog(retry_of)
        if self.recorder.is_recording(key):  # re-checked: the probe ran async
            if retry_of is not None:
                self._catchup_retry_state.pop(retry_of, None)
            message_box(_("This catch-up programme is already downloading."),
                          _("Catch-up Download"), wx.OK | wx.ICON_INFORMATION)
            self._return_to_catchup_after_download(channel, show.get("start", ""))
            return
        try:
            # The file is named for when the programme aired, as the EPG lists
            # it, not for whenever it happened to be downloaded.
            aired = utc_to_local(datetime.datetime.strptime(
                show.get("start", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc))
        except (TypeError, ValueError):
            aired = None
        try:
            rec = self.recorder.start(
                url, display_name, fmt, headers, get_recordings_dir(self.config),
                key=key,
                metadata={"catchup": True, "programme_start": show.get("start", ""),
                          "programme_end": show.get("end", ""),
                          "channel": dict(channel) if channel else {},
                          "hls_url": hls_url or url,
                          "duration": duration,
                          "audio_intent": audio_intent},
                on_finish=self._catchup_download_finished,
                duration=duration,
                show_stats=True,
                keep_partial=False,
                file_time=aired,
                audio_track=audio_choice[0] if audio_choice else None,
                audio_track_count=audio_choice[1] if audio_choice else 0,
            )
        except Exception as err:
            # Stream URLs go to the debug log verbatim (credentials included):
            # the log exists for troubleshooting, and the URL is the diagnosis.
            if retry_of is not None:
                self._catchup_retry_state.pop(retry_of, None)
            LOG.error("Catch-up download failed to start for %s: %s", url, err)
            message_box(_("Could not start catch-up download:\n{error}").format(error=err),
                          _("Catch-up Download"), wx.OK | wx.ICON_ERROR)
            self._return_to_catchup_after_download(channel, show.get("start", ""))
            return
        if retry_of is not None:
            # The budget belongs to the programme, not the recorder id: pass it
            # on so the next failure still counts against the original budget.
            attempts = self._catchup_retry_state.pop(retry_of, None)
            if attempts is not None:
                self._catchup_retry_state[rec.id] = attempts
        LOG.info(
            "Catch-up download started for %s -> %s",
            url, rec.out_path)
        self._note_recording_started()
        # A modeless progress window replaces the old "download started" box:
        # progress, elapsed, ETA, size and Cancel live there from now on.
        dlg = CatchupDownloadDialog(self, rec, duration=duration,
                                    on_cancel=lambda: self._cancel_catchup_download(rec.id))
        self._catchup_downloads[rec.id] = dlg
        dlg.Show()
        dlg.Raise()

    def _cancel_catchup_download(self, rec_id: int):
        """Stop one catch-up download; ffmpeg finalizes the file cleanly."""
        self._catchup_retry_state.pop(rec_id, None)
        timer = self._catchup_retry_timers.pop(rec_id, None)
        if timer is not None:
            timer.cancel()
        self._catchup_downloads.pop(rec_id, None)
        self.recorder.stop(rec_id, wait=False)

    def _catchup_download_finished(self, rec, rc):
        """Recorder watcher thread: close the progress window, then report."""
        dlg = self._catchup_downloads.pop(rec.id, None)

        def finish():
            if getattr(self, "_suppress_recording_notifications", False):
                return  # the app is exiting; nothing to report
            if rc == 0:
                state = getattr(self, "_catchup_retry_state", None)
                if state is not None:
                    state.pop(rec.id, None)
                if dlg is not None:
                    dlg.notify_recording_finished()
                if rec.stopped_by_user:
                    # The partial output was discarded by the recorder: ffmpeg
                    # cannot resume it, so it would only be unplayable junk.
                    self._show_or_queue_message_box(
                        _("Download canceled. The incomplete file was discarded."),
                        _("Catch-up Download"), wx.OK | wx.ICON_INFORMATION)
                else:
                    self._show_or_queue_message_box(
                        _("Download complete:\n{path}").format(path=rec.out_path),
                        _("Catch-up Download"), wx.OK | wx.ICON_INFORMATION)
                return
            if rec.stopped_by_user:
                if dlg is not None:
                    dlg.notify_recording_finished()
                return
            # Failure: show the error inline in the still-open window first,
            # then decide whether an automatic retry makes sense.
            if dlg is not None:
                dlg.show_failure(rc)
            detail = "\n".join(rec.stderr_tail[-6:]) or self._recording_failure_detail(rec)
            # Providers refuse bursts of downloads with 403s and flaky
            # networks drop connections: retry those a few times with a
            # growing delay instead of making the user start over.
            if self._maybe_retry_catchup_download(
                    rec, rc, channel=rec.metadata.get("channel") or {},
                    show={"start": rec.metadata.get("programme_start", ""),
                          "end": rec.metadata.get("programme_end", "")},
                    duration=rec.metadata.get("duration") or 0.0,
                    fmt=rec.fmt):
                if dlg is not None:
                    # Keep the window open: it now shows the error and the
                    # countdown, and its Cancel button aborts the waiting retry.
                    self._catchup_downloads[rec.id] = dlg
                    attempts = self._catchup_retry_state.get(rec.id, 1)
                    dlg.show_retry_pending(
                        attempts, _CATCHUP_RETRY_MAX_ATTEMPTS,
                        _CATCHUP_RETRY_BASE_DELAY_SECONDS * (2 ** (attempts - 1)))
                return
            if dlg is not None:
                dlg.notify_recording_finished()
            reason = _ffmpeg_exit_reason(rc)
            if reason:
                message = _("Download failed:\n{path}\n\n{reason}\n\n{detail}").format(
                    path=rec.out_path, reason=reason, detail=detail)
            else:
                message = _("Download failed (code {code}):\n{path}\n\n{detail}").format(
                    code=rc, path=rec.out_path, detail=detail)
            # Shown now, not queued behind another box: once it is dismissed,
            # go back to the catch-up list on this programme so it can be tried
            # again, instead of dropping the user at the channel list.
            shown_now = not self._modal_box_is_open()
            self._show_or_queue_message_box(
                message, _("Catch-up Download"), wx.OK | wx.ICON_ERROR)
            if shown_now:
                metadata = getattr(rec, "metadata", None) or {}
                self._return_to_catchup_after_download(
                    metadata.get("channel") or {}, metadata.get("programme_start", ""))

        # Everything below touches the UI: marshal onto the main thread.
        wx.CallAfter(self._maybe_shutdown_after_recordings)
        wx.CallAfter(finish)

    def _maybe_retry_catchup_download(self, rec, rc, *, channel, show, duration, fmt) -> bool:
        """Queue one more attempt for a transient failure; True when scheduled.

        The retry re-runs the whole probe flow (so a fresh direct URL is
        derived - the failed one may be provider-stale), and the progress
        window stays open showing the error and the countdown, where its
        Cancel button can still abort the waiting retry.
        """
        if not _catchup_failure_is_retryable(rc, rec.stderr_tail or [],
                                             stopped_by_user=rec.stopped_by_user):
            return False
        state = getattr(self, "_catchup_retry_state", None)
        if state is None:
            state = self._catchup_retry_state = {}
        attempts = state.get(rec.id, 0)
        if attempts >= _CATCHUP_RETRY_MAX_ATTEMPTS:
            state.pop(rec.id, None)
            return False
        state[rec.id] = attempts + 1
        delay = _CATCHUP_RETRY_BASE_DELAY_SECONDS * (2 ** attempts)
        retry_of = rec.id
        metadata = getattr(rec, "metadata", None) or {}
        hls_url = metadata.get("hls_url") or getattr(rec, "url", "")

        def retry():
            timer = self._catchup_retry_timers.pop(retry_of, None)
            if timer is not None:
                timer.cancel()
            if getattr(self, "_suppress_recording_notifications", False):
                return  # the app is exiting; do not start new work
            if retry_of not in self._catchup_retry_state:
                return  # Cancel was pressed while this retry was waiting
            LOG.info("Catch-up download retry %d for %s", attempts + 1, rec.title)
            self._begin_catchup_download(
                channel, hls_url, rec.title, rec.key, show, duration, fmt,
                retry_of=retry_of, audio_intent=metadata.get("audio_intent"))

        timer = _schedule_retry(retry, delay)
        if timer is not None:
            self._catchup_retry_timers[retry_of] = timer
        return True

    def _close_catchup_dialog(self, rec_id: int):
        """UI thread: close a catch-up progress window, if still open."""
        dlg = self._catchup_downloads.pop(rec_id, None)
        if dlg is not None:
            dlg.notify_recording_finished()

    def show_cast_dialog(self, _event):
        caster = self._ensure_caster()
        if caster.is_connected():
            msg = _("Currently connected to: {device}\n\nDisconnect?").format(
                device=caster.active_device.display_name)
            if message_box(msg, _("Casting"), wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                # Disconnect in background
                threading.Thread(target=caster.disconnect, daemon=True).start()
            return

        dlg = CastDiscoveryDialog(self, caster)
        if dlg.ShowModal() == wx.ID_OK:
            device = dlg.get_selected_device()
            if device:
                # Connect in background
                def do_connect():
                    try:
                        creds = self.config.get("cast_credentials", {}).get(device.identifier)
                        caster.connect(device, credentials=creds)
                        wx.CallAfter(lambda: message_box(_("Connected to {device}").format(device=device.display_name), _("Connected"), wx.OK))
                    except Exception as e:
                        err_msg = str(e)
                        wx.CallAfter(lambda: message_box(_("Failed to connect: {error}").format(error=err_msg), _("Error"), wx.OK | wx.ICON_ERROR))
                
                threading.Thread(target=do_connect, daemon=True).start()
        dlg.Destroy()


    def _get_catchup_programmes(self, channel: Dict[str, str]) -> List[Dict[str, str]]:
        try:
            db = EPGDatabase(get_db_path(), readonly=True)
            try:
                programmes = db.get_recent_programmes(channel, hours=72, limit=80)
            finally:
                db.close()
        except Exception:
            programmes = []
        return programmes


class CastDiscoveryDialog(wx.Dialog):
    help_topic = "casting"

    def __init__(self, parent, caster):
        super().__init__(parent, title=_("Select Device to Cast"), size=(450, 350))
        self.parent_frame = parent
        self.caster = caster
        self.devices: List[object] = []

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.status_lbl = wx.StaticText(panel, label=_("Searching for devices..."))
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.pair_btn = wx.Button(panel, label=_("Pair..."))
        self.pair_btn.Disable()

        self.ok_btn = wx.Button(panel, id=wx.ID_OK, label=_("Connect"))
        self.ok_btn.Disable()
        cancel_btn = wx.Button(panel, id=wx.ID_CANCEL)
        
        btn_sizer.Add(self.pair_btn, 0, wx.ALL, 5)
        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(self.ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        
        sizer.Add(self.status_lbl, 0, wx.ALL, 10)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        panel.SetSizer(sizer)
        
        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_dclick)
        self.pair_btn.Bind(wx.EVT_BUTTON, self._on_pair)
        
        self.CenterOnParent()
        
        # Start discovery
        self._start_discovery()

    def _start_discovery(self):
        def do_scan():
            try:
                # caster.discover_all() is synchronous and thread-safe (uses internal loop)
                devices = self.caster.discover_all()
                wx.CallAfter(self._update_list, devices)
            except Exception as e:
                wx.CallAfter(self.status_lbl.SetLabel, _("Error: {error}").format(error=e))

        threading.Thread(target=do_scan, daemon=True).start()

    def _update_list(self, devices: List[object]):
        self.devices = devices
        self.listbox.Clear()
        if not devices:
            self.status_lbl.SetLabel(_("No devices found."))
            return

        self.status_lbl.SetLabel(_("Found {count} devices:").format(count=len(devices)))
        for dev in devices:
            self.listbox.Append(dev.display_name)
        
        # Restore selection if possible (not implemented for now to keep it simple)

    def _on_select(self, event):
        sel = self.listbox.GetSelection()
        if sel != wx.NOT_FOUND and 0 <= sel < len(self.devices):
            self.ok_btn.Enable()
            dev = self.devices[sel]
            # Enable Pair button for AirPlay devices
            self.pair_btn.Enable(dev.protocol.value == "AirPlay")
        else:
            self.ok_btn.Disable()
            self.pair_btn.Disable()

    def _on_dclick(self, event):
        if self.listbox.GetSelection() != wx.NOT_FOUND:
            self.EndModal(wx.ID_OK)

    def _on_pair(self, event):
        device = self.get_selected_device()
        if not device:
            return
        
        # Disable UI
        self.pair_btn.Disable()
        self.ok_btn.Disable()
        self.status_lbl.SetLabel(_("Starting pairing with {device}...").format(device=device.name))
        
        def do_pair_flow():
            handler = None
            try:
                # Step 1: Begin Pairing
                handler = self.caster.start_pairing(device) # This is sync now
                self.caster.dispatch(handler.begin())
                
                # Step 2: Ask User for PIN
                def ask_pin():
                    dlg = wx.TextEntryDialog(self, _("Enter PIN displayed on {device}:").format(device=device.name), _("Pairing"))
                    if dlg.ShowModal() == wx.ID_OK:
                        return dlg.GetValue().strip()
                    return None
                
                # We need to run the dialog on main thread
                pin_result = [None]
                evt = threading.Event()
                def show_dialog_main():
                    pin_result[0] = ask_pin()
                    evt.set()
                
                wx.CallAfter(show_dialog_main)
                evt.wait()
                
                pin = pin_result[0]
                if not pin:
                    # User cancelled
                    self.caster.dispatch(handler.close())
                    wx.CallAfter(self.status_lbl.SetLabel, _("Pairing cancelled."))
                    return

                # Step 3: Submit PIN
                handler.pin(pin)
                
                # Step 4: Finish
                self.caster.dispatch(handler.finish())
                
                # Step 5: Save Credentials
                creds = handler.service.credentials
                if creds:
                    wx.CallAfter(self._save_creds_and_notify, device, creds)
                else:
                    wx.CallAfter(lambda: message_box(_("Pairing finished but no credentials returned."), _("Pairing Failed"), wx.OK | wx.ICON_ERROR))

            except Exception as e:
                err_msg = str(e)
                wx.CallAfter(lambda: message_box(_("Pairing error: {error}").format(error=err_msg), _("Error"), wx.OK | wx.ICON_ERROR))
                wx.CallAfter(self.status_lbl.SetLabel, _("Pairing failed: {error}").format(error=err_msg))
                if handler:
                    try:
                        self.caster.dispatch(handler.close())
                    except Exception:
                        LOG.debug("CastDiscoveryDialog._on_pair.do_pair_flow: ignored exception", exc_info=True)
            finally:
                wx.CallAfter(self._on_select, None) # Re-enable buttons
        
        threading.Thread(target=do_pair_flow, daemon=True).start()

    def _save_creds_and_notify(self, device, creds):
        # Save to main config
        cfg = self.parent_frame.config
        if "cast_credentials" not in cfg:
            cfg["cast_credentials"] = {}
        
        cfg["cast_credentials"][device.identifier] = creds
        save_config(cfg)
        
        message_box(_("Successfully paired with {device}!").format(device=device.name), _("Pairing Complete"), wx.OK)
        self.status_lbl.SetLabel(_("Paired with {device}. Ready to connect.").format(device=device.name))

    def get_selected_device(self) -> Optional[object]:
        sel = self.listbox.GetSelection()
        if sel != wx.NOT_FOUND and 0 <= sel < len(self.devices):
            return self.devices[sel]
        return None


class AccountInfoDialog(wx.Dialog):
    """Subscription status for every provider account the app can find.

    Deliberately two controls: a list of accounts and one read-only multiline
    field holding the whole report. That is the shape a screen reader handles
    best - arrow through the accounts, tab once, read the details top to bottom.
    Each lookup is a blocking HTTP request, so it runs on a worker thread and
    results are matched against a request token before being displayed.
    """

    help_topic = "account-info"

    def __init__(self, parent, accounts: List[account_info.Account]):
        super().__init__(
            parent,
            title=_("Account Info"),
            size=(700, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.accounts = accounts
        self._reports: Dict[int, str] = {}
        self._request_token = 0
        self._alive = True

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(panel, label=_("Select an account to check its status:"))
        list_label = wx.StaticText(panel, label=_("Accounts") + ":")
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._label_control(self.listbox, _("Accounts"))
        for account in accounts:
            self.listbox.Append(account_info.account_label(account))

        details_label = wx.StaticText(panel, label=_("Account details") + ":")
        self.details = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self._label_control(self.details, _("Account details"))

        self.status_lbl = wx.StaticText(panel, label="")

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(panel, label=_("Refresh"))
        self.copy_btn = wx.Button(panel, label=_("Copy Details"))
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        btn_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        btn_sizer.Add(self.copy_btn, 0, wx.ALL, 5)
        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(close_btn, 0, wx.ALL, 5)

        sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(list_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(details_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(self.details, 2, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(sizer)

        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.refresh_btn.Bind(wx.EVT_BUTTON, self._on_refresh)
        self.copy_btn.Bind(wx.EVT_BUTTON, self._on_copy)
        close_btn.Bind(wx.EVT_BUTTON, self._on_close_button)
        self.Bind(wx.EVT_CLOSE, self._on_close_window)
        self.SetEscapeId(wx.ID_CANCEL)

        self.SetMinSize((520, 420))
        self.Layout()
        self.CenterOnParent()

        if accounts:
            self.listbox.SetSelection(0)
            self.listbox.SetFocus()
            self._start_lookup(0)

    @staticmethod
    def _label_control(ctrl, label):
        ctrl.SetName(label)
        if hasattr(ctrl, "SetAccessibleName"):
            ctrl.SetAccessibleName(label)

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #
    def _start_lookup(self, index: int, force: bool = False):
        if not (0 <= index < len(self.accounts)):
            return
        self._request_token += 1
        token = self._request_token
        if not force and index in self._reports:
            self._apply_report(token, index, self._reports[index])
            return
        account = self.accounts[index]
        self.details.SetValue(_("Checking account, please wait..."))
        self.status_lbl.SetLabel(_("Checking {account}...").format(
            account=account_info.account_label(account)))
        self.refresh_btn.Disable()

        def worker():
            try:
                report = account_info.fetch_account_report(account)
            except Exception as e:
                LOG.debug("AccountInfoDialog: account lookup failed", exc_info=True)
                wx.CallAfter(self._lookup_failed, token, index, str(e))
                return
            wx.CallAfter(self._lookup_finished, token, index, report)

        threading.Thread(target=worker, daemon=True).start()

    def _lookup_finished(self, token: int, index: int, report: str):
        self._reports[index] = report
        self._apply_report(token, index, report)

    def _lookup_failed(self, token: int, index: int, error: str):
        # Errors are not cached: re-selecting the account should retry it.
        self._apply_report(
            token,
            index,
            _("Could not check this account.\n\n{error}").format(error=error),
            ok=False,
        )

    def _apply_report(self, token: int, index: int, report: str, ok: bool = True):
        if not self._alive or token != self._request_token:
            return
        try:
            self.details.SetValue(report)
            # Reading starts at the top, not wherever the previous report ended.
            self.details.SetInsertionPoint(0)
            self.status_lbl.SetLabel(_("Ready.") if ok else _("Check failed."))
            self.refresh_btn.Enable()
        except RuntimeError:
            LOG.debug("AccountInfoDialog._apply_report: dialog already gone", exc_info=True)

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    def _on_select(self, _event):
        self._start_lookup(self.listbox.GetSelection())

    def _on_refresh(self, _event):
        self._start_lookup(self.listbox.GetSelection(), force=True)

    def _on_copy(self, _event):
        text = self.details.GetValue()
        if not text:
            return
        if not wx.TheClipboard.Open():
            self.status_lbl.SetLabel(_("Could not open the clipboard."))
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        self.status_lbl.SetLabel(_("Account details copied to the clipboard."))

    def _on_close_button(self, _event):
        self._alive = False
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()

    def _on_close_window(self, event):
        self._alive = False
        event.Skip()


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


class CatchupDownloadDialog(wx.Dialog):
    """Live progress for one catch-up download.

    ffmpeg reports the media time it has written through periodic stats lines
    in the per-recording log, so the dialog tails that log once a second. All
    figures sit in one read-only text field, so a screen reader reads them as
    a single, ordered block (NVDA+B, or the arrow keys inside the field)
    instead of a scattered grid of labels. Closing the window or pressing
    Cancel asks for confirmation first, because a canceled download cannot be
    resumed. The window is deliberately modeless: the user can keep browsing
    while the download runs. Escape and Alt+F4 only hide it - the download
    carries on - and View > Show Downloads brings it back.
    """

    UPDATE_INTERVAL_MS = 1000
    help_topic = "catch-up-downloads"
    # Destroys itself when the download ends, so F1 help opens over the main window.
    can_host_help = False

    def __init__(self, parent, rec, *, duration: float, on_cancel):
        title = _("Downloading {name}").format(name=rec.title)
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE)
        self._rec = rec
        self._duration = max(1.0, float(duration))
        self._on_cancel_cb = on_cancel
        self._started = time.time()
        self._last_details = ""
        self._frozen = False  # set once the download has ended (failure/retry)
        self._timer = wx.Timer(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.status_text = wx.StaticText(self, label=_("Preparing download..."))
        self.status_text.Wrap(420)
        sizer.Add(self.status_text, 0, wx.ALL, 12)

        self.gauge = wx.Gauge(self, range=100, size=(-1, 18))
        sizer.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        # One read-only field instead of a grid of labels: the numbers are
        # announced in a fixed, meaningful order, and stay reviewable at will.
        self.details_field = wx.TextCtrl(
            self, size=(-1, 96),
            style=wx.TE_READONLY | wx.TE_MULTILINE | wx.BORDER_NONE)
        sizer.Add(self.details_field, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        hint = wx.StaticText(self, label=_(
            "Press Escape to hide this window; the download continues. "
            "View > Show Downloads (Ctrl+Shift+D) brings it back."))
        hint.Wrap(420)
        sizer.Add(hint, 0, wx.LEFT | wx.RIGHT, 12)

        # Not wx.ID_CANCEL: that id is what Escape presses, and Escape used to
        # land on "cancel the download?" - a window that could not simply be
        # closed. Escape hides the window now; this button stops the download.
        self.cancel_btn = wx.Button(self, label=_("Cancel"))
        sizer.Add(self.cancel_btn, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 12)
        self.SetSizerAndFit(sizer)
        self.CenterOnParent()

        # Every control gets a screen-reader name; labels are static text.
        self.status_text.SetName(_("Download status"))
        self.gauge.SetName(_("Download progress"))
        self.details_field.SetName(_("Download details"))

        self.cancel_btn.Bind(wx.EVT_BUTTON, lambda _evt: self._cancel_download())
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_TIMER, self._on_tick, self._timer)
        _show_on_taskbar(self)
        self._timer.Start(self.UPDATE_INTERVAL_MS)
        self._on_tick(None)
        # The title already carries the name; announce the state change so a
        # screen reader says it without waiting for the next tick.

    _ERROR_LINE_RE = re.compile(
        r"\[(?:error|fatal|panic|warning)\]|HTTP error|failed|refused|reset|timed? ?out",
        re.IGNORECASE)

    def _first_error_line(self) -> str:
        """The first diagnostic line ffmpeg wrote, for the inline error view."""
        try:
            with open(self._rec.log_path, "rb") as handle:
                data = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        for line in data.splitlines():
            line = line.strip()
            if line and self._ERROR_LINE_RE.search(line):
                return line
        return ""

    def show_failure(self, exit_code: int) -> None:
        """Freeze the live view and show the failure inline (UI thread)."""
        self._frozen = True
        self.gauge.SetValue(0)
        self.status_text.SetLabel(_("Download failed (code {code}).").format(code=exit_code))
        lines = [_("ffmpeg exit code: {code}").format(code=exit_code)]
        reason = _ffmpeg_exit_reason(exit_code)
        if reason:
            lines.insert(0, reason)
        first_error = self._first_error_line()
        if first_error:
            lines.append(first_error)
        else:
            lines.append(_("No error details were reported."))
        self.details_field.SetValue("\n".join(lines))

    def show_retry_pending(self, attempt: int, total: int, delay_seconds: float) -> None:
        """Announce an automatic retry; the window stays open for Cancel."""
        self._frozen = True
        self.gauge.Pulse()
        self.status_text.SetLabel(_(
            "Download failed - retrying (attempt {attempt} of {total}) "
            "in {seconds} seconds...").format(
                attempt=attempt, total=total, seconds=int(round(delay_seconds))))

    def _on_tick(self, _event):
        if not self or not self._rec or self._frozen:
            return
        written = parse_ffmpeg_progress(self._rec.log_path)
        elapsed = max(0.0, time.time() - self._started)
        if written is not None:
            pct = int(round(100.0 * min(written, self._duration) / self._duration))
            self.gauge.SetValue(pct)
            self.status_text.SetLabel(_("Downloading {name}").format(name=self._rec.title))
            remaining = max(0.0, self._duration - written)
        else:
            self.gauge.Pulse()
            self.status_text.SetLabel(_("Downloading {name}").format(name=self._rec.title))
            pct = None
            remaining = None
        lines = [
            _("Progress: {percent}%").format(percent="--" if pct is None else pct),
            _("Elapsed: {time}").format(time=format_duration(elapsed)),
            _("Time remaining: {time}").format(time=format_duration(remaining)),
            _("Downloaded: {size}").format(size=format_size(written_size(self._rec))),
        ]
        details = "\n".join(lines)
        if details != self._last_details:
            self._last_details = details
            self.details_field.SetValue(details)

    def _confirm_cancel(self) -> bool:
        answer = message_box(
            _("Do you really want to cancel this download? "
              "It cannot be resumed afterwards."),
            _("Cancel Download"), wx.YES_NO | wx.ICON_QUESTION)
        return answer == wx.YES

    def _cancel_download(self, confirmed: bool = False):
        if not confirmed and not self._confirm_cancel():
            return
        self._timer.Stop()
        cb, self._on_cancel_cb = self._on_cancel_cb, None
        if cb is not None:
            cb()
        self.Destroy()

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.hide_window()
            return
        event.Skip()

    def _on_close(self, event):
        # Alt+F4 and the title bar's close button hide the window and leave
        # the download running. Stopping it is the Cancel button's job, and
        # that asks first. A close that cannot be vetoed is wx tearing the
        # window down (the app is quitting), so let that one through.
        if event.CanVeto():
            event.Veto()
            self.hide_window()
            return
        self._timer.Stop()
        event.Skip()

    def hide_window(self):
        """Hide without cancelling, and hand focus back to the main window."""
        self.Hide()
        parent = self.GetParent()
        if parent:
            try:
                parent.Raise()
            except Exception:
                LOG.debug("CatchupDownloadDialog.hide_window: ignored exception", exc_info=True)

    def reveal(self):
        """Show the window again (hidden or merely behind) and focus it."""
        self.Show()
        self.Raise()
        self.details_field.SetFocus()

    def notify_recording_finished(self):
        """Stop the updates and close the window (finish callback, UI thread)."""
        try:
            self._timer.Stop()
        except Exception:
            LOG.debug("CatchupDownloadDialog.notify_recording_finished: timer stop ignored", exc_info=True)
        try:
            self.Destroy()
        except Exception:
            LOG.debug("CatchupDownloadDialog.notify_recording_finished: ignored exception", exc_info=True)


class CatchupDialog(wx.Dialog):
    """Choose one catch-up programme, then open or download it.

    The two actions live only in the list's context menu (right-click / Apps
    key) and on Enter (open): no buttons at all sit in the Tab chain. Tab from
    the list reaches a read-only description of the highlighted programme, and
    Tab again comes straight back to the list. Escape closes the dialog.
    """

    help_topic = "catch-up"

    def __init__(self, parent, channel_name: str, programmes: List[Dict[str, str]],
                 initial_start: str = ""):
        title = channel_name or _("Catch-up")
        super().__init__(parent, title=_("Catch-up: {name}").format(name=title), size=(520, 360))
        self.programmes = programmes
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(panel, label=_(
            "Select a programme, then press Enter to open it, or use the "
            "context menu to download it. Press Escape to close."))
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        for prog in programmes:
            self.listbox.Append(self._format_programme(prog))
        if programmes:
            # Back from the player, the list opens on the programme that was
            # playing rather than at the top.
            initial = next((i for i, prog in enumerate(programmes)
                            if initial_start and prog.get("start") == initial_start), 0)
            self.listbox.SetSelection(initial)
        # Tab from the list lands here: the description of the highlighted
        # programme, read-only, updated as the selection moves. Same pattern
        # as the EPG dialog, and one less reason to open the EPG by hand.
        self.description_label = wx.StaticText(panel, label=_("Description"))
        self.description_field = wx.TextCtrl(
            panel, size=(-1, 90), style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.description_field.SetName(_("Episode description"))

        # There is no Close button. It was the third stop in a three-control
        # Tab ring and did nothing Escape does not already do, so Tab from the
        # description landed on a button whose only job was to be tabbed past
        # on the way back to the list. Escape is handled below, for every
        # control in the dialog.
        sizer.Add(intro, 0, wx.ALL, 10)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.description_label, 0, wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.description_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(sizer)
        self.listbox.SetName(_("Catch-up programmes"))
        self.listbox.Bind(wx.EVT_LISTBOX, lambda _evt: self._update_description())
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_listbox_activate)
        # EVT_CHAR_HOOK, not EVT_KEY_DOWN: a dialog consumes Enter before the
        # focused control ever sees a key-down, which is why pressing Enter on
        # a catch-up programme used to do nothing at all.
        self.listbox.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.listbox.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.description_field.Bind(wx.EVT_CHAR_HOOK, self._on_description_key)
        # With no wxID_CANCEL button left, wx has nothing to click for Escape,
        # so close the dialog here. The bind is on the dialog: an unhandled
        # char hook from any child bubbles up to it.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_dialog_key)
        self.SetEscapeId(wx.ID_CANCEL)
        self.SetMinSize((420, 380))
        self.Layout()
        self.CenterOnParent()
        self._update_description()

    def _on_dialog_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def _format_programme(self, prog: Dict[str, str]) -> str:
        try:
            start = datetime.datetime.strptime(prog.get("start", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            end = datetime.datetime.strptime(prog.get("end", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            start_local = utc_to_local(start)
            end_local = utc_to_local(end)
            window = f"{start_local.strftime('%Y-%m-%d %H:%M')} – {end_local.strftime('%H:%M')}"
        except Exception:
            window = prog.get("start", "")
        title = prog.get("title", "") or _("(No title)")
        return f"{window}  |  {title}"

    def _on_listbox_activate(self, _):
        if self.programmes:
            self.EndModal(wx.ID_OK)

    def _on_description_key(self, event):
        # Both directions go back to the list: it and the description are the
        # only two controls, so Tab is a two-stop ring, not a walk past a
        # button on the way round.
        if event.GetKeyCode() == wx.WXK_TAB:
            self.listbox.SetFocus()
            return
        event.Skip()

    def _update_description(self):
        idx = self.listbox.GetSelection()
        prog = self.programmes[idx] if 0 <= idx < len(self.programmes) else None
        description = (prog.get("description") or "").strip() if prog else ""
        text = description or _("No description available for this programme.")
        if self.description_field.GetValue() != text:
            self.description_field.SetValue(text)

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_TAB:
            # Forwards to the description, backwards to it as well: the ring
            # holds two controls, so either Tab direction reaches the same
            # place and the pair stays reversible.
            self.description_field.SetFocus()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._on_listbox_activate(None)
        elif key == wx.WXK_WINDOWS_MENU:
            # The keyboard's context-menu key must work without a mouse.
            # WXK_MENU is Alt, not the Applications key; on a char hook that
            # would pop the menu open every time the user reached for Alt.
            self._show_context_menu(keyboard=True)
        else:
            event.Skip()

    def _on_context_menu(self, _event):
        self._show_context_menu(keyboard=False)

    def _show_context_menu(self, keyboard: bool):
        if self.listbox.GetSelection() == wx.NOT_FOUND and self.programmes:
            self.listbox.SetSelection(0)
        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, _("Open"))
        menu.Bind(wx.EVT_MENU, lambda _evt: self.EndModal(wx.ID_OK), open_item)
        download_item = menu.Append(wx.ID_ANY, _("Download"))
        menu.Bind(wx.EVT_MENU, lambda _evt: self.EndModal(wx.ID_SAVE), download_item)
        pos = wx.DefaultPosition
        if keyboard:
            selection = self.listbox.GetSelection()
            if selection != wx.NOT_FOUND:
                try:
                    rect = self.listbox.GetItemRect(selection)
                    if rect.width or rect.height:
                        pos = self.listbox.ClientToScreen(rect.GetBottomLeft())
                except Exception:
                    LOG.debug("CatchupDialog._show_context_menu: ignored exception", exc_info=True)
        try:
            self.listbox.PopupMenu(menu, pos)
        finally:
            menu.Destroy()

    def get_selection(self) -> Optional[Dict[str, str]]:
        idx = self.listbox.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self.programmes):
            return None
        return self.programmes[idx]


class AudioTrackPreferenceDialog(wx.Dialog):
    """Which audio track the built-in player should choose by itself.

    Channels that carry an audio description track put it beside the ordinary one
    and start on the ordinary one, so a viewer who needs the description has had to
    switch by hand on every single channel. This is the setting that stops that.
    """

    _WRAP_WIDTH = 430
    help_topic = "preferred-audio-track"

    def __init__(self, parent, keywords=None, prefer_audio_description: bool = False):
        super().__init__(parent, title=_("Preferred Audio Track"))
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(self, label=_(
            "When a channel offers more than one audio track, the built-in player can "
            "switch to the track you want on its own."))
        intro.Wrap(self._WRAP_WIDTH)
        sizer.Add(intro, 0, wx.ALL, 10)

        self.ad_check = wx.CheckBox(self, label=_(
            "Prefer an audio description track when the channel has one"))
        self.ad_check.SetValue(bool(prefer_audio_description))
        self._label_control(self.ad_check, _("Prefer an audio description track when the channel has one"))
        sizer.Add(self.ad_check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        keywords_label = _("Preferred track names or languages, most wanted first:")
        sizer.Add(wx.StaticText(self, label=keywords_label), 0, wx.LEFT | wx.RIGHT, 10)
        self.keywords_txt = wx.TextCtrl(self, value=", ".join(str(k) for k in (keywords or [])))
        self._label_control(self.keywords_txt, keywords_label)
        sizer.Add(self.keywords_txt, 0, wx.EXPAND | wx.ALL, 10)

        hint = wx.StaticText(self, label=_(
            "Separate them with commas, for example: audio description, English. A "
            "track is used when its name contains one of these words. Leave this empty "
            "to keep whatever track the channel starts on."))
        hint.Wrap(self._WRAP_WIDTH)
        sizer.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(sizer)
        self.CenterOnParent()
        wx.CallAfter(self.ad_check.SetFocus)

    @staticmethod
    def _label_control(ctrl, label):
        ctrl.SetName(label)
        if hasattr(ctrl, "SetAccessibleName"):
            ctrl.SetAccessibleName(label)

    def get_keywords(self) -> List[str]:
        from options import coerce_string_list

        return coerce_string_list(self.keywords_txt.GetValue())

    def get_prefer_audio_description(self) -> bool:
        return bool(self.ad_check.GetValue())


class RecordingPaddingDialog(wx.Dialog):
    """Accessible settings for scheduled-recording lead-in and lead-out."""

    MAX_PADDING_MINUTES = 180
    help_topic = "schedule-padding"

    def __init__(self, parent, before_minutes=0, after_minutes=2):
        super().__init__(parent, title=_("Schedule Padding"), style=wx.DEFAULT_DIALOG_STYLE)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(self, label=_(
            "Start scheduled recordings early or keep recording after the programme ends. "
            "Manual recordings are not changed."))
        intro.Wrap(430)
        sizer.Add(intro, 0, wx.ALL, 12)

        grid = wx.FlexGridSizer(2, 2, 8, 10)
        before_label = _("Minutes before programme:")
        after_label = _("Minutes after programme:")
        self.before_ctrl = wx.SpinCtrl(
            self, min=0, max=self.MAX_PADDING_MINUTES,
            initial=self._coerce_minutes(before_minutes),
        )
        self.after_ctrl = wx.SpinCtrl(
            self, min=0, max=self.MAX_PADDING_MINUTES,
            initial=self._coerce_minutes(after_minutes),
        )
        for label, control in ((before_label, self.before_ctrl), (after_label, self.after_ctrl)):
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control.SetName(label)
            if hasattr(control, "SetAccessibleName"):
                control.SetAccessibleName(label)
            grid.Add(control, 0, wx.EXPAND)
        grid.AddGrowableCol(1, 1)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        buttons = wx.StdDialogButtonSizer()
        self.ok_btn = wx.Button(self, id=wx.ID_OK)
        self.cancel_btn = wx.Button(self, id=wx.ID_CANCEL)
        buttons.AddButton(self.ok_btn)
        buttons.AddButton(self.cancel_btn)
        buttons.Realize()
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

        self.SetSizerAndFit(sizer)
        self.CentreOnParent()
        self.ok_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish(wx.ID_OK))
        self.cancel_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish(wx.ID_CANCEL))
        self.Bind(wx.EVT_CLOSE, lambda _event: self._finish(wx.ID_CANCEL))
        self.SetEscapeId(wx.ID_CANCEL)
        self.ok_btn.SetDefault()
        self.before_ctrl.SetFocus()

    @classmethod
    def _coerce_minutes(cls, value) -> int:
        try:
            return max(0, min(int(float(value)), cls.MAX_PADDING_MINUTES))
        except Exception:
            return 0

    def get_padding(self) -> Tuple[int, int]:
        return self.before_ctrl.GetValue(), self.after_ctrl.GetValue()

    def _finish(self, result):
        if self.IsModal():
            self.EndModal(result)
        else:
            self.Destroy()


class ShutdownCountdownDialog(wx.Dialog):
    """The last chance to stop the computer powering off after a recording.

    Modeless and parentless on purpose: it has to appear even when the main window
    is minimized to the tray, which is exactly where it will be at 3am.
    """

    COUNTDOWN_SECONDS = 60
    help_topic = "shutdown-after-recordings"
    # Closes itself when the countdown ends, so F1 help opens over the main window.
    can_host_help = False

    def __init__(self, parent, on_cancel, on_shutdown, seconds: Optional[int] = None):
        super().__init__(parent, title=_("Shut Down After Recordings"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
        self._on_cancel_cb = on_cancel
        self._on_shutdown_cb = on_shutdown
        self._remaining = int(self.COUNTDOWN_SECONDS if seconds is None else seconds)
        self._finished = False

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.message = wx.StaticText(self, label=self._message_text())
        self.message.Wrap(400)
        sizer.Add(self.message, 0, wx.ALL, 12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.cancel_btn = wx.Button(self, id=wx.ID_CANCEL, label=_("Cancel Shutdown"))
        self.shutdown_btn = wx.Button(self, label=_("Shut Down Now"))
        buttons.Add(self.cancel_btn, 0, wx.RIGHT, 8)
        buttons.Add(self.shutdown_btn, 0)
        sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizerAndFit(sizer)

        self.cancel_btn.Bind(wx.EVT_BUTTON, lambda _evt: self._cancel())
        self.shutdown_btn.Bind(wx.EVT_BUTTON, lambda _evt: self._shutdown())
        self.Bind(wx.EVT_CLOSE, lambda _evt: self._cancel())
        # Cancel is both the default and focused: a dialog that appeared on its own
        # must not power the machine off because Enter or Escape was already on its
        # way to something else.
        self.cancel_btn.SetDefault()
        self.cancel_btn.SetFocus()
        self.Centre()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self._timer)
        self._timer.Start(1000)

    def _message_text(self) -> str:
        # Phrased so the number never needs a plural form: the app ships no plural
        # catalogues, so "1 seconds" would be unfixable in translation.
        return _("All recordings have finished.\n\n"
                 "The computer will shut down by itself. Seconds remaining: {seconds}").format(
                     seconds=max(0, self._remaining))

    def _on_tick(self, _event):
        self._remaining -= 1
        if self._remaining <= 0:
            self._shutdown()
            return
        try:
            self.message.SetLabel(self._message_text())
        except Exception:
            LOG.debug("ShutdownCountdownDialog._on_tick: ignored exception", exc_info=True)

    def _stop_timer(self):
        try:
            self._timer.Stop()
        except Exception:
            LOG.debug("ShutdownCountdownDialog._stop_timer: ignored exception", exc_info=True)

    def _cancel(self):
        if self._finished:
            return
        self._finished = True
        self._stop_timer()
        self._on_cancel_cb()

    def _shutdown(self):
        if self._finished:
            return
        self._finished = True
        self._stop_timer()
        self._on_shutdown_cb()


class ScheduledRecordingsDialog(wx.Dialog):
    """Dialog showing all DVR schedule entries.

    Cancel and Delete live in the list's context menu (right-click or the
    keyboard's menu key); Escape and Alt+F4 close the window, so there is no
    Close button.
    """

    help_topic = "scheduled-recordings"

    def __init__(self, parent, scheduler: dvr.DVRScheduler):
        super().__init__(parent, title=_("Scheduled Recordings"), size=(850, 430))
        self.parent_frame = parent
        self.scheduler = scheduler
        self.jobs: List[Dict[str, object]] = []

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.SetName(_("Scheduled recordings"))
        self.list_ctrl.InsertColumn(0, _("Time"), width=210)
        self.list_ctrl.InsertColumn(1, _("Title"), width=230)
        self.list_ctrl.InsertColumn(2, _("Channel"), width=180)
        self.list_ctrl.InsertColumn(3, _("Status"), width=110)
        self.list_ctrl.InsertColumn(4, _("Format"), width=120)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        refresh_btn = wx.Button(panel, label=_("Refresh"))
        btn_sizer.Add(refresh_btn, 0, wx.RIGHT, 5)

        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(sizer)

        refresh_btn.Bind(wx.EVT_BUTTON, lambda _event: self.refresh())
        self.list_ctrl.Bind(wx.EVT_CONTEXT_MENU, lambda _event: self._show_context_menu(keyboard=False))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _on_char_hook(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self.Close()
        elif key == wx.WXK_DELETE:
            self._on_delete_selected(event)
        elif key == wx.WXK_MENU:
            self._show_context_menu(keyboard=True)
        else:
            event.Skip()

    def _show_context_menu(self, keyboard: bool):
        menu = wx.Menu()
        refresh_item = menu.Append(wx.ID_ANY, _("Refresh"))
        menu.Bind(wx.EVT_MENU, lambda _event: self.refresh(), refresh_item)
        menu.AppendSeparator()
        cancel_item = menu.Append(wx.ID_ANY, _("Cancel"))
        menu.Bind(wx.EVT_MENU, self._on_cancel_selected, cancel_item)
        delete_item = menu.Append(wx.ID_ANY, _("Delete") + "\tDel")
        menu.Bind(wx.EVT_MENU, self._on_delete_selected, delete_item)
        pos = wx.DefaultPosition
        if keyboard:
            idx = self.list_ctrl.GetFirstSelected()
            if idx != -1:
                try:
                    rect = self.list_ctrl.GetItemRect(idx)
                    if rect.width or rect.height:
                        pos = self.list_ctrl.ClientToScreen(rect.GetBottomLeft())
                except Exception:
                    LOG.debug("ScheduledRecordingsDialog._show_context_menu: ignored exception", exc_info=True)
        try:
            self.list_ctrl.PopupMenu(menu, pos)
        finally:
            menu.Destroy()

        self.refresh()
        self.CenterOnParent()

    def _status_label(self, status: str) -> str:
        labels = {
            dvr.STATUS_SCHEDULED: _("Scheduled"),
            dvr.STATUS_RECORDING: _("Recording"),
            dvr.STATUS_STOPPING: _("Stopping"),
            dvr.STATUS_COMPLETED: _("Completed"),
            dvr.STATUS_FAILED: _("Failed"),
            dvr.STATUS_MISSED: _("Missed"),
            dvr.STATUS_CANCELED: _("Canceled"),
        }
        return labels.get(status, status or "")

    def refresh(self):
        self.jobs = self.scheduler.list_jobs(include_done=True)
        self.list_ctrl.DeleteAllItems()
        for job in self.jobs:
            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), self.parent_frame._schedule_window_label(job))
            self.list_ctrl.SetItem(idx, 1, str(job.get("title") or ""))
            self.list_ctrl.SetItem(idx, 2, str(job.get("channel_name") or ""))
            self.list_ctrl.SetItem(idx, 3, self._status_label(str(job.get("status") or "")))
            self.list_ctrl.SetItem(idx, 4, self.parent_frame._recording_format_label(str(job.get("format") or "")))
            if job.get("status") in {dvr.STATUS_RECORDING, dvr.STATUS_STOPPING}:
                font = self.list_ctrl.GetItemFont(idx)
                font.SetWeight(wx.FONTWEIGHT_BOLD)
                self.list_ctrl.SetItemFont(idx, font)
        if self.jobs:
            self.list_ctrl.Select(0)
            self.list_ctrl.Focus(0)

    def _selected_job(self) -> Optional[Dict[str, object]]:
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1 or idx >= len(self.jobs):
            return None
        return self.jobs[idx]

    def _on_cancel_selected(self, _event):
        job = self._selected_job()
        if not job:
            message_box(_("Select a scheduled recording first."), _("Scheduled Recordings"),
                          wx.OK | wx.ICON_INFORMATION)
            return
        if self.parent_frame._cancel_scheduled_recording(str(job.get("id") or "")):
            self.refresh()

    def _on_delete_selected(self, _event):
        job = self._selected_job()
        if not job:
            message_box(_("Select a scheduled recording first."), _("Scheduled Recordings"),
                          wx.OK | wx.ICON_INFORMATION)
            return
        if job.get("status") in {dvr.STATUS_RECORDING, dvr.STATUS_STOPPING}:
            answer = message_box(
                _("This recording is active. Stop and delete it?"),
                _("Scheduled Recordings"),
                wx.YES_NO | wx.ICON_WARNING,
            )
            if answer != wx.YES:
                return
            self.parent_frame._cancel_scheduled_recording(str(job.get("id") or ""))
        self.scheduler.delete_job(str(job.get("id") or ""))
        self.refresh()

    def _on_close(self, event):
        try:
            self.parent_frame._dvr_dialog = None
        except Exception:
            LOG.debug("ScheduledRecordingsDialog._on_close: ignored exception", exc_info=True)
        self.Destroy()


class WhatsOnNowDialog(wx.Dialog):
    """Dialog showing all currently airing programs across all channels."""

    help_topic = "whats-on-now"
    
    def __init__(self, parent, programs: List[Dict[str, str]], schedule_callback=None):
        super().__init__(parent, title=_("What's on Now"), size=(700, 500))
        self.programs = programs
        self.filtered_programs = programs[:]
        self.schedule_callback = schedule_callback
        self._type_ahead_buffer = ""
        self._type_ahead_timer = None
        self._filter_timer = None
        
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Search box (for filtering, Tab to access)
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_label = wx.StaticText(panel, label=_("Filter (Tab):"))
        self.search_box = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.search_box.SetName(_("Filter programs"))
        search_sizer.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        search_sizer.Add(self.search_box, 1, wx.EXPAND)
        sizer.Add(search_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Info label
        self.count_label = wx.StaticText(panel, label=_("{count} programs").format(count=len(programs)))
        sizer.Add(self.count_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Use virtual ListCtrl for fast loading with many items
        self.listbox = _VirtualWhatsOnList(panel, self)
        self.listbox.SetName(_("Currently airing programs"))
        self.listbox.InsertColumn(0, _("Program - Channel"), width=650)
        self.listbox.SetItemCount(len(self.filtered_programs))

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        play_btn = wx.Button(panel, id=wx.ID_OK, label=_("Play"))
        schedule_btn = wx.Button(panel, label=_("Schedule Recording"))
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        btn_sizer.Add(play_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(schedule_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(close_btn, 0)
        
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        
        panel.SetSizer(sizer)
        
        self.Layout()
        self.CenterOnParent()
        
        # Bind events - use KEY_DOWN to intercept space before ListCtrl handles it
        self.listbox.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.listbox.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        # Right-click / Shift+F10 / Applications key on a programme row.
        self.listbox.Bind(wx.EVT_CONTEXT_MENU, lambda _evt: self._show_context_menu())
        play_btn.Bind(wx.EVT_BUTTON, self._on_play)
        schedule_btn.Bind(wx.EVT_BUTTON, self._on_schedule)
        self.search_box.Bind(wx.EVT_TEXT, self._on_search)
        self.search_box.Bind(wx.EVT_TEXT_ENTER, self._on_search_enter)
        
        # Focus the list initially
        if self.filtered_programs:
            self.listbox.Select(0)
            self.listbox.Focus(0)
        self.listbox.SetFocus()
    
    def _on_key_down(self, event):
        """Handle key input for type-ahead search - intercept before ListCtrl."""
        key = event.GetKeyCode()
        
        # Handle Tab to go to search box
        if key == wx.WXK_TAB:
            self.search_box.SetFocus()
            return
        
        # Handle Enter to play
        if key == wx.WXK_RETURN or key == wx.WXK_NUMPAD_ENTER:
            if self.listbox.GetSelectedItemCount() > 0:
                self.EndModal(wx.ID_OK)
            return
        
        # Handle Escape to close
        if key == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        
        # Handle Space - add to type-ahead buffer (don't activate)
        if key == wx.WXK_SPACE or key == ord(' '):
            if self._type_ahead_timer:
                self._type_ahead_timer.Stop()
            self._type_ahead_buffer += " "
            self._find_match(self._type_ahead_buffer)
            self._type_ahead_timer = wx.CallLater(1000, self._reset_type_ahead)
            return
        
        # For printable characters (excluding space which is handled above), do type-ahead search
        if 33 <= key <= 126:  # Start at 33 (!) to exclude space (32)
            char = chr(key).lower()
            
            # Reset buffer if too much time passed
            if self._type_ahead_timer:
                self._type_ahead_timer.Stop()
            
            self._type_ahead_buffer += char
            self._find_match(self._type_ahead_buffer)
            
            # Reset buffer after 1 second of no typing
            self._type_ahead_timer = wx.CallLater(1000, self._reset_type_ahead)
            return
        
        # Backspace clears type-ahead buffer
        if key == wx.WXK_BACK:
            if self._type_ahead_buffer:
                self._type_ahead_buffer = self._type_ahead_buffer[:-1]
                if self._type_ahead_buffer:
                    self._find_match(self._type_ahead_buffer)
            return
        
        event.Skip()
    
    def _reset_type_ahead(self):
        """Reset the type-ahead buffer."""
        self._type_ahead_buffer = ""
    
    def _find_match(self, prefix: str):
        """Find and select the first item starting with prefix."""
        prefix_lower = prefix.lower()
        for idx, prog in enumerate(self.filtered_programs):
            title = prog.get("title", "").lower()
            if title.startswith(prefix_lower):
                self.listbox.Select(idx)
                self.listbox.Focus(idx)
                self.listbox.EnsureVisible(idx)
                return
    
    def _on_search(self, event):
        """Debounce filtering so NVDA isn't hit with a list rebuild per keystroke."""
        if self._filter_timer:
            self._filter_timer.Stop()
        self._filter_timer = wx.CallLater(200, self._apply_search_filter)

    def _apply_search_filter(self):
        self._filter_timer = None
        try:
            if not self:  # dialog already destroyed while the timer was pending
                return
            query = self.search_box.GetValue().lower().strip()
        except RuntimeError:
            return
        if not query:
            self.filtered_programs = self.programs[:]
        else:
            self.filtered_programs = [
                p for p in self.programs
                if query in p.get("title", "").lower() or query in p.get("channel_name", "").lower()
            ]
        new_count = len(self.filtered_programs)
        # The old selection's index maps to a different program after refiltering,
        # and a focused item past the new count leaves NVDA holding a stale index.
        # Drop selection/focus state entirely before changing the count.
        old_count = self.listbox.GetItemCount()
        for idx in {self.listbox.GetFirstSelected(), self.listbox.GetFocusedItem()}:
            if idx is not None and 0 <= idx < old_count:
                try:
                    self.listbox.SetItemState(idx, 0, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
                except Exception:
                    LOG.debug("WhatsOnNowDialog._apply_search_filter: ignored exception", exc_info=True)
        self.listbox.SetItemCount(new_count)
        self.listbox.Refresh()
        self.count_label.SetLabel(_("{count} programs").format(count=new_count))
        # Only auto-select while the user is actually in the list; forcing
        # Select/Focus while they type in the search box fires focus events at NVDA.
        if self.filtered_programs and self.FindFocus() is self.listbox:
            self.listbox.Select(0)
            self.listbox.Focus(0)
        LOG.debug("whats-on filter %r: %d/%d programs", query, new_count, len(self.programs))

    def _on_search_enter(self, event):
        """Move focus to list when Enter is pressed in search box."""
        # Flush a pending debounced filter so the list matches the query.
        if self._filter_timer:
            self._filter_timer.Stop()
            self._apply_search_filter()
        if self.filtered_programs:
            self.listbox.SetFocus()
            self.listbox.Select(0)
            self.listbox.Focus(0)
    
    def _on_activate(self, event):
        """Handle double-click/Enter to play."""
        if self.listbox.GetSelectedItemCount() > 0:
            self.EndModal(wx.ID_OK)
    
    def _on_play(self, event):
        """Handle Play button click."""
        if self.listbox.GetSelectedItemCount() > 0:
            self.EndModal(wx.ID_OK)
        event.Skip()

    def _on_schedule(self, _event):
        if not self.schedule_callback:
            return
        selection = self.get_selection()
        if selection:
            self.schedule_callback(selection)

    def _show_context_menu(self):
        """Row actions for the highlighted programme, keyboard reachable."""
        if not self.filtered_programs:
            return
        if self.listbox.GetFirstSelected() == -1:
            self.listbox.Select(0)
            self.listbox.Focus(0)
        menu = wx.Menu()
        play_item = menu.Append(wx.ID_ANY, _("Play"))
        menu.Bind(wx.EVT_MENU, lambda _evt: self.EndModal(wx.ID_OK), play_item)
        schedule_item = menu.Append(wx.ID_ANY, _("Schedule Recording"))
        schedule_item.Enable(self.schedule_callback is not None)
        menu.Bind(wx.EVT_MENU, self._on_schedule, schedule_item)
        pos = wx.DefaultPosition
        index = self.listbox.GetFirstSelected()
        if index != -1:
            try:
                rect = self.listbox.GetItemRect(index)
                if rect.width or rect.height:
                    pos = self.listbox.ClientToScreen(rect.GetBottomLeft())
            except Exception:
                LOG.debug("WhatsOnNowDialog._show_context_menu: ignored exception", exc_info=True)
        try:
            self.listbox.PopupMenu(menu, pos)
        finally:
            menu.Destroy()

    
    def get_selection(self) -> Optional[Dict[str, str]]:
        """Get the selected program dict."""
        idx = self.listbox.GetFirstSelected()
        if idx == -1 or idx >= len(self.filtered_programs):
            return None
        return self.filtered_programs[idx]


class _VirtualChannelList(wx.ListCtrl):
    """Virtual, single-column list for the main channel / search-results list.

    Backed by the frame's ``displayed`` model (a list of {"type","data"[, "label"]}
    entries); only visible rows are realized, so 50k-300k entries stay responsive for the
    UI and NVDA. Exposes a small wx.ListBox-compatible API (GetSelection / SetSelection /
    GetCount / Clear) so the existing selection code did not need to change when the control
    was switched from wx.ListBox to a virtual wx.ListCtrl. This same virtual-ListCtrl pattern
    is already used (and screen-reader tested) by _VirtualWhatsOnList below.
    """

    def __init__(self, parent, frame):
        super().__init__(
            parent,
            style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL,
            name="Channels",
        )
        # The constructor's name= never reaches NVDA on SysListView32; the
        # explicit accessible name does, so the list is announced as a name
        # instead of a bare "list". Same rule as _AccessibleCategoryTree.
        self.SetName(_("Channels"))
        if hasattr(self, "SetAccessibleName"):
            self.SetAccessibleName(_("Channels"))
        self._frame = frame
        self.InsertColumn(0, "")
        self.SetItemCount(0)
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _on_size(self, event):
        # Keep the single column as wide as the control so long names aren't clipped.
        width = self.GetClientSize().width
        if width > 0:
            self.SetColumnWidth(0, width)
        event.Skip()

    def OnGetItemText(self, item, column):
        disp = self._frame.displayed
        if 0 <= item < len(disp):
            entry = disp[item]
            label = entry.get("label")
            if label is not None:
                return label
            data = entry.get("data") or {}
            name = data.get("name", "")
            # getattr rather than a direct call: the non-GUI test doubles that stand
            # in for the frame only supply displayed.
            decorate = getattr(self._frame, "_decorate_channel_label", None)
            return decorate(name, data) if callable(decorate) else name
        return ""

    def announce_item(self, index: int):
        """Re-fire focus for one row so a screen reader reads its new text.

        Only the focus state is cycled. Cycling the selection too would re-run the
        EPG lookup for the row and re-enter ``on_highlight`` for no benefit.
        """
        if index is None or not (0 <= index < self.GetItemCount()):
            return
        try:
            self.RefreshItem(index)
            self.SetItemState(index, 0, wx.LIST_STATE_FOCUSED)
            self.SetItemState(index, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)
        except Exception:
            LOG.debug("_VirtualChannelList.announce_item: ignored exception", exc_info=True)

    def _clear_active_item_state(self, minimum_index: int = 0):
        """Clear selected/focused state for active rows at or after an index."""
        old = self.GetItemCount()
        for idx in {self.GetFirstSelected(), self.GetFocusedItem()}:
            if idx is not None and minimum_index <= idx < old:
                try:
                    self.SetItemState(
                        idx,
                        0,
                        wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                    )
                except Exception:
                    LOG.debug("_VirtualChannelList._clear_active_item_state: ignored exception", exc_info=True)

    def _set_count_safe(self, count: int, *, active_state_cleared: bool = False):
        """Resync the native item count, dropping stale selection/focus first.

        Shrinking a virtual SysListView32 while its focused/selected item index
        is >= the new count leaves MSAA/UIA holding a stale index, which can
        crash NVDA. Clear those item states before the shrink.
        """
        old = self.GetItemCount()
        if count < old:
            if not active_state_cleared:
                self._clear_active_item_state(count)
            LOG.debug("channel list count %d -> %d", old, count)
        self.SetItemCount(count)

    def replace_contents(self, entries: List[Dict[str, str]]):
        """Replace the backing rows while keeping native indexes valid.

        ``SetItemCount`` can trigger synchronous MSAA/UIA item queries. On a
        shrink, reduce the native count while the old model still serves all
        remaining indexes, then swap to the new model. On a grow, install the
        new model first so every existing index remains valid. Clear active
        state for *every* replacement, even when the old index would fit the
        new count: it represents a different logical row after a search.
        """
        if not isinstance(entries, list):
            entries = list(entries)
        old_count = self.GetItemCount()
        new_count = len(entries)
        self._clear_active_item_state()

        if new_count < old_count:
            self._set_count_safe(new_count, active_state_cleared=True)
            self._frame.displayed = entries
        else:
            self._frame.displayed = entries
            self._set_count_safe(new_count, active_state_cleared=True)

        self.Refresh()

    def set_virtual_count(self):
        """Resync the control to the current length of frame.displayed."""
        self._set_count_safe(len(self._frame.displayed))
        width = self.GetClientSize().width
        if width > 0:
            self.SetColumnWidth(0, width)

    # --- wx.ListBox-compatible shims so existing call sites keep working ---
    def GetSelection(self):
        return self.GetFirstSelected()

    def SetSelection(self, index):
        if index is None or index < 0:
            return
        if index < self.GetItemCount():
            self.Select(index)
            self.Focus(index)
            self.EnsureVisible(index)

    def GetCount(self):
        return self.GetItemCount()

    def Clear(self):
        self._set_count_safe(0)


class _VirtualWhatsOnList(wx.ListCtrl):
    """Virtual list control for fast loading of What's on Now."""
    
    def __init__(self, parent, dialog):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL)
        self.dialog = dialog
    
    def OnGetItemText(self, item, column):
        if 0 <= item < len(self.dialog.filtered_programs):
            prog = self.dialog.filtered_programs[item]
            title = prog.get("title") or _("(No title)")
            channel = prog.get("channel_name") or _("Unknown")
            return f"{title} - {channel}"
        return ""


class ChannelEPGDialog(wx.Dialog):
    help_topic = "channel-epg"

    def __init__(self, parent, channel_name: str, programmes: List[Dict[str, str]],
                 schedule_callback=None, channel: Optional[Dict[str, str]] = None):
        super().__init__(parent, title=_("EPG: {channel}").format(channel=channel_name), size=(600, 450))
        self.programmes = programmes
        self.schedule_callback = schedule_callback
        self.channel = channel or {}

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.InsertColumn(0, _("Time"), width=190)
        self.list_ctrl.InsertColumn(1, _("Title"), width=360)

        self._populate_list(programmes)
        if programmes:
            self.list_ctrl.Select(0)
            self.list_ctrl.Focus(0)

        # Tab from the list lands here: the description of the highlighted
        # programme, read-only, updated as the selection moves.
        self.description_label = wx.StaticText(panel, label=_("Description"))
        self.description_field = wx.TextCtrl(
            panel, size=(-1, 110), style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.description_field.SetName(_("Episode description"))

        # No buttons: Schedule Recording lives in the row's context menu, and
        # Escape / Alt+F4 close the window, so Close was only a dead Tab stop.
        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(self.description_label, 0, wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.description_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_dialog_key)
        self.SetEscapeId(wx.ID_CANCEL)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _evt: self._update_description())
        self.list_ctrl.Bind(wx.EVT_CHAR_HOOK, self._on_list_key)
        # Right-click / Shift+F10 / Applications key on a programme row.
        self.list_ctrl.Bind(wx.EVT_CONTEXT_MENU, lambda _evt: self._show_context_menu())
        self.description_field.Bind(wx.EVT_CHAR_HOOK, self._on_description_key)
        self._update_description()
        
        self.Layout()
        self.CenterOnParent()

    def _populate_list(self, programmes):
        now = datetime.datetime.now(datetime.timezone.utc)
        today = utc_to_local(now).date()
        for prog in programmes:
            try:
                start = datetime.datetime.strptime(prog.get("start", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
                end = datetime.datetime.strptime(prog.get("end", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
                start_local = utc_to_local(start)
                end_local = utc_to_local(end)
                time_str = f"{start_local.strftime('%H:%M')} - {end_local.strftime('%H:%M')}"
                # The guide runs days ahead: date every row that is not today.
                if start_local.date() != today:
                    time_str = f"{start_local.strftime('%Y-%m-%d')} {time_str}"

                is_now = start <= now <= end
                
                idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), time_str)
                self.list_ctrl.SetItem(idx, 1, prog.get("title", ""))
                
                if is_now:
                    # Highlight current program (bold font)
                    font = self.list_ctrl.GetItemFont(idx)
                    font.SetWeight(wx.FONTWEIGHT_BOLD)
                    self.list_ctrl.SetItemFont(idx, font)
                    self.list_ctrl.EnsureVisible(idx)
            except Exception:
                LOG.debug("ChannelEPGDialog._populate_list: ignored exception", exc_info=True)

    def _selected_programme(self) -> Optional[Dict[str, str]]:
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1 or idx >= len(self.programmes):
            return None
        return self.programmes[idx]

    def _on_list_key(self, event):
        if event.GetKeyCode() == wx.WXK_TAB and not event.ShiftDown():
            self.description_field.SetFocus()
            return
        event.Skip()

    def _show_context_menu(self):
        """Row actions for the highlighted programme, keyboard reachable."""
        if not self.programmes:
            return
        if self.list_ctrl.GetFirstSelected() == -1:
            self.list_ctrl.Select(0)
            self.list_ctrl.Focus(0)
        menu = wx.Menu()
        schedule_item = menu.Append(wx.ID_ANY, _("Schedule Recording"))
        schedule_item.Enable(self.schedule_callback is not None)
        menu.Bind(wx.EVT_MENU, self._on_schedule, schedule_item)
        pos = wx.DefaultPosition
        index = self.list_ctrl.GetFirstSelected()
        if index != -1:
            try:
                rect = self.list_ctrl.GetItemRect(index)
                if rect.width or rect.height:
                    pos = self.list_ctrl.ClientToScreen(rect.GetBottomLeft())
            except Exception:
                LOG.debug("ChannelEPGDialog._show_context_menu: ignored exception", exc_info=True)
        try:
            self.list_ctrl.PopupMenu(menu, pos)
        finally:
            menu.Destroy()

    def _on_description_key(self, event):
        # Two controls, one ring: Tab either way goes back to the list.
        if event.GetKeyCode() == wx.WXK_TAB:
            self.list_ctrl.SetFocus()
            return
        event.Skip()

    def _on_dialog_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def _update_description(self):
        prog = self._selected_programme()
        description = (prog.get("description") or "").strip() if prog else ""
        text = description or _("No description available for this programme.")
        if self.description_field.GetValue() != text:
            self.description_field.SetValue(text)

    def _on_schedule(self, _event):
        if not self.schedule_callback:
            return
        prog = self._selected_programme()
        if not prog:
            message_box(_("Select a programme first."), _("Schedule Recording"),
                          wx.OK | wx.ICON_INFORMATION)
            return
        self.schedule_callback(self.channel, prog)

def _install_exception_logging():
    """Send uncaught exceptions to the debug log instead of losing them.

    wxPython routes exceptions raised inside the event loop - including
    wx.CallAfter callbacks fired from worker threads - to ``sys.excepthook``;
    without a hook they only reach stderr, so a crashed dialog callback looks
    like a menu item that silently does nothing. Worker-thread exceptions go
    through ``threading.excepthook`` the same way. Both hooks write to the
    debug log and then delegate to the default hooks so stderr stays intact.
    """
    def ui_hook(exc_type, exc_value, exc_tb):
        LOG.error("Uncaught exception in the UI event loop",
                  exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def thread_hook(args):
        name = getattr(args.thread, "name", None) or "unknown"
        LOG.error("Uncaught exception in thread %s", name,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        threading.__excepthook__(args)

    sys.excepthook = ui_hook
    threading.excepthook = thread_hook


if __name__ == "__main__":
    set_linux_env()
    # Best-effort early language activation from saved config (the frame re-applies it too).
    try:
        i18n.init_from_config(load_config())
    except Exception:
        LOG.debug("<module>: ignored exception", exc_info=True)
    _install_exception_logging()
    app = wx.App()
    app.SetAppName(app_meta.APP_NAME)
    IPTVClient()
    app.MainLoop()
