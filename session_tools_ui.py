"""Native bookmark and notification dialogs; all actions are keyboard reachable."""
import datetime

import wx

import named_bookmarks
import user_guide
from i18n import gettext as _
from media_navigation import clock_text
from modal_guard import message_box, show_modal


def _error(parent, error):
    message_box(str(error), _("Error"), wx.OK | wx.ICON_ERROR, parent=parent)


def _context(player):
    position, length = player._media_clock()
    key = getattr(player, "_resume_key", "")
    if not key or not player.player.is_seekable():
        raise ValueError(_("This stream does not support seeking."))
    return key, position, length, getattr(player, "_vlc_generation", 0)


def add_bookmark(player):
    try:
        key, position, length, generation = _context(player)
        if position >= length:
            raise ValueError(_("Choose a position before the end of the media."))
        dialog = wx.TextEntryDialog(player, _("Bookmark name:"), _("Add Named Bookmark"), clock_text(position))
        try:
            while show_modal(dialog) == wx.ID_OK:
                if generation != getattr(player, "_vlc_generation", 0) or getattr(player, "_destroyed", False):
                    return
                try:
                    player.GetParent()._save_tool_setting("named_playback_bookmarks", lambda old:
                        named_bookmarks.put(old, key, dialog.GetValue(), position))
                    player._navigation_message(_("Bookmark saved."))
                    return
                except Exception as error:
                    _error(dialog, error)
        finally:
            dialog.Destroy()
    except Exception as error:
        _error(player, error)


class BookmarksDialog(wx.Dialog):
    def __init__(self, player):
        context = _context(player)
        super().__init__(player, title=_("Named Bookmarks"), size=(620, 400),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.player = player
        self.key, _position, self.length, self.generation = context
        self.target = None
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(wx.StaticText(self, label=_("Bookmarks for the current item:")), 0, wx.ALL, 8)
        self.list = wx.ListBox(self)
        self.list.SetName(_("Bookmarks for the current item:"))
        layout.Add(self.list, 1, wx.ALL | wx.EXPAND, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, callback in ((_("Go to Bookmark"), self.go), (_("Rename..."), self.rename),
                                (_("Delete"), self.delete)):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, callback)
            row.Add(button, 0, wx.ALL, 5)
        close = wx.Button(self, wx.ID_CANCEL, label=_("Close"))
        row.Add(close, 0, wx.ALL, 5)
        layout.Add(row, 0, wx.ALIGN_RIGHT)
        self.SetSizer(layout)
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self.go)
        self.Bind(wx.EVT_CHAR_HOOK, self.key_press)
        user_guide.set_help_topic(self, "built-in-player")
        self.refresh()

    def refresh(self):
        previous = self.list.GetSelection()
        self.rows = named_bookmarks.normalize(self.player.GetParent().config.get("named_playback_bookmarks")).get(self.key, [])
        self.list.Set([row["name"] + " — " + clock_text(row["position_ms"]) for row in self.rows])
        if self.rows:
            self.list.SetSelection(max(0, min(previous, len(self.rows) - 1)))

    def selected(self):
        index = self.list.GetSelection()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def key_press(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self.list.HasFocus():
            self.go(event)
        else:
            event.Skip()

    def go(self, _event):
        row = self.selected()
        if row:
            if self.generation != getattr(self.player, "_vlc_generation", 0):
                _error(self, _("Playback changed. Reopen the bookmark list."))
                return
            if row["position_ms"] >= self.length:
                _error(self, _("Choose a position before the end of the media."))
                return
            self.target = row["position_ms"]
            self.EndModal(wx.ID_OK)

    def rename(self, _event):
        row = self.selected()
        if not row:
            return
        dialog = wx.TextEntryDialog(self, _("Bookmark name:"), _("Rename..."), row["name"])
        try:
            if show_modal(dialog) == wx.ID_OK:
                self.player.GetParent()._save_tool_setting("named_playback_bookmarks", lambda old:
                    named_bookmarks.put(old, self.key, dialog.GetValue(), row["position_ms"], identity=row["id"]))
                self.refresh()
        except Exception as error:
            _error(self, error)
        finally:
            dialog.Destroy()

    def delete(self, _event):
        row = self.selected()
        if row and message_box(_("Delete bookmark '{name}'?").format(name=row["name"]), _("Named Bookmarks"),
                               wx.YES_NO | wx.NO_DEFAULT, parent=self) == wx.YES:
            try:
                self.player.GetParent()._save_tool_setting("named_playback_bookmarks", lambda old:
                    named_bookmarks.remove(old, self.key, row["id"]))
                self.refresh()
            except Exception as error:
                _error(self, error)


def show_bookmarks(player):
    try:
        _context(player)
        dialog = BookmarksDialog(player)
        try:
            if show_modal(dialog) == wx.ID_OK and dialog.generation == getattr(player, "_vlc_generation", 0):
                player._seek_media(target=dialog.target)
        finally:
            dialog.Destroy()
    except Exception as error:
        _error(player, error)


class NotificationsDialog(wx.Dialog):
    def __init__(self, owner):
        super().__init__(owner, title=_("Notification History"), size=(720, 480),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.owner = owner
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(wx.StaticText(self, label=_("Notifications from this session:")), 0, wx.ALL, 8)
        self.list = wx.ListBox(self)
        self.list.SetName(_("Notifications from this session:"))
        layout.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        layout.Add(wx.StaticText(self, label=_("Details")), 0, wx.LEFT, 8)
        self.details = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.details.SetName(_("Details"))
        layout.Add(self.details, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, callback in ((_("Refresh"), self.refresh), (_("Copy Details"), self.copy), (_("Clear History"), self.clear)):
            button = wx.Button(self, label=label)
            row.Add(button, 0, wx.ALL, 5)
            button.Bind(wx.EVT_BUTTON, callback)
        row.Add(wx.Button(self, wx.ID_CANCEL, label=_("Close")), 0, wx.ALL, 5)
        layout.Add(row, 0, wx.ALIGN_RIGHT)
        self.SetSizer(layout)
        self.list.Bind(wx.EVT_LISTBOX, self.select)
        user_guide.set_help_topic(self, "personal-tools")
        self.refresh()

    def refresh(self, _event=None):
        self.rows = list(reversed(getattr(self.owner, "_notification_history", [])))
        self.list.Set([datetime.datetime.fromtimestamp(row["time"]).strftime("%H:%M:%S") + " — " + row["caption"]
                       for row in self.rows])
        if self.rows:
            self.list.SetSelection(0)
        self.select()

    def select(self, _event=None):
        index = self.list.GetSelection()
        self.details.SetValue(self.rows[index]["message"] if 0 <= index < len(self.rows) else "")

    def copy(self, _event):
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(self.details.GetValue()))
            finally:
                wx.TheClipboard.Close()

    def clear(self, _event):
        if message_box(_("Clear the notification history for this session?"), _("Notification History"),
                       wx.YES_NO | wx.NO_DEFAULT, parent=self) == wx.YES:
            self.owner._notification_history = []
            self.refresh()


def show_notifications(owner):
    dialog = NotificationsDialog(owner)
    try:
        show_modal(dialog)
    finally:
        dialog.Destroy()
