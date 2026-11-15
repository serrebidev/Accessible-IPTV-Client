"""Keyboard-first dialogs for the built-in player's VOD progress library."""
import datetime
import threading

import wx

import playback_resume
import live_announce
from i18n import gettext as _
from modal_guard import show_modal


def choose_resume(parent, position_ms):
    seconds = position_ms // 1000
    clock = "{}:{:02d}:{:02d}".format(seconds // 3600, seconds // 60 % 60, seconds % 60)
    dialog = wx.MessageDialog(parent, _("Resume playback from {time}?").format(time=clock),
                              _("Resume"), wx.YES_NO | wx.CANCEL | wx.NO_DEFAULT | wx.ICON_QUESTION)
    dialog.SetYesNoLabels(_("Resume"), _("Play from Beginning"))
    try:
        result = show_modal(dialog)
        return "resume" if result == wx.ID_YES else "beginning" if result == wx.ID_NO else "cancel"
    finally:
        dialog.Destroy()


class ContinueWatchingDialog(wx.Dialog):
    help_topic = "video-on-demand"

    def __init__(self, parent, config, save_entries, resolve):
        super().__init__(parent, title=_("Continue Watching"), size=(800, 470),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.config, self.save_entries, self.resolve = config, save_entries, resolve
        self._closed, self._generation, self._busy = False, 0, False
        self._status = {}
        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.source = wx.Choice(panel, choices=[_("Video on Demand"), _("Recordings")])
        self.source.SetName(_("Type"))
        self.source.SetSelection(0)
        layout.Add(self.source, 0, wx.EXPAND | wx.ALL, 10)
        self.source.Bind(wx.EVT_CHOICE, self._change_source)
        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.SetName(_("Saved playback positions"))
        for i, (label, width) in enumerate([(_("Title"), 290), (_("Position"), 100),
                                           (_("Last Watched"), 160), (_("Availability"), 190)]):
            self.list.InsertColumn(i, label, width=width)
        layout.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)
        self.status = wx.StaticText(panel, label="")
        layout.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        buttons = wx.WrapSizer(wx.HORIZONTAL)
        self.continue_button = wx.Button(panel, label=_("Resume"))
        self.check_button = wx.Button(panel, label=_("Check Availability"))
        self.remove_button = wx.Button(panel, label=_("Remove Saved Position"))
        self.clear_button = wx.Button(panel, label=_("Clear All Saved Positions"))
        close = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        for button in (self.continue_button, self.check_button, self.remove_button, self.clear_button, close):
            buttons.Add(button, 0, wx.RIGHT, 5)
        layout.Add(buttons, 0, wx.ALL, 10)
        panel.SetSizer(layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.Bind(wx.EVT_BUTTON, lambda event: self._start_check(True), self.continue_button)
        self.Bind(wx.EVT_BUTTON, lambda event: self._start_check(False), self.check_button)
        self.Bind(wx.EVT_BUTTON, self._remove, self.remove_button)
        self.Bind(wx.EVT_BUTTON, self._clear, self.clear_button)
        self.Bind(wx.EVT_BUTTON, self._close, close)
        self.Bind(wx.EVT_CLOSE, self._close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self._start_check(True))
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self._update_buttons())
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self._refresh()
        self.list.SetFocus()

    def _refresh(self, preferred=None):
        self.rows = list(playback_resume.normalize(self.config.get(self.store_key)).items())
        self.list.DeleteAllItems()
        selected = 0
        for index, (key, entry) in enumerate(self.rows):
            title = entry.get("metadata", {}).get("title") or _("Previously saved content (title unavailable)")
            self.list.InsertItem(index, title)
            seconds = entry["position_ms"] // 1000
            self.list.SetItem(index, 1, "{}:{:02d}:{:02d}".format(seconds // 3600, seconds // 60 % 60, seconds % 60))
            try:
                stamp = datetime.datetime.fromtimestamp(entry["updated"]).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError, OverflowError):
                stamp = _("Unknown time")
            self.list.SetItem(index, 2, stamp)
            self.list.SetItem(index, 3, self._status.get(key, _("Not checked")))
            if key == preferred:
                selected = index
        if self.rows:
            self.list.Select(selected)
            self.list.Focus(selected)
            self.list.EnsureVisible(selected)
        self.status.SetLabel("" if self.rows else _("No saved playback positions."))
        self._update_buttons()
        if not self.rows:
            live_announce.speak(_("No saved playback positions."))

    def _selected_key(self):
        index = self.list.GetFirstSelected()
        return self.rows[index][0] if 0 <= index < len(self.rows) else None

    @property
    def store_key(self):
        return 'recording_playback_bookmarks' if self.source.GetSelection() == 1 else 'playback_bookmarks'

    def _change_source(self, _event):
        self._generation += 1
        self._busy = False
        self._status.clear()
        self._refresh()

    def _update_buttons(self):
        selected = self._selected_key() is not None and not self._busy
        for button in (self.continue_button, self.check_button, self.remove_button):
            button.Enable(selected)
        self.clear_button.Enable(bool(self.rows) and not self._busy)
        self.source.Enable(not self._busy)

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
            self._remove(event)
        else:
            event.Skip()

    def _start_check(self, play):
        key = self._selected_key()
        if self._busy or key is None:
            return
        self._busy = True
        self._generation += 1
        generation = self._generation
        # Copy on the UI thread. Native playback timers may update config while
        # the provider request is running, but workers never touch wx/config.
        entries = playback_resume.normalize(self.config.get(self.store_key))
        self.status.SetLabel(_("Checking saved content…"))
        self._update_buttons()
        def worker():
            try:
                item = self.resolve(key, entries)
                failed = False
            except Exception:
                item, failed = None, True
            wx.CallAfter(self._checked, generation, key, item, failed, play)
        try:
            threading.Thread(target=worker, daemon=True).start()
        except RuntimeError:
            self._checked(generation, key, None, True, play)

    def _checked(self, generation, key, item, failed, play):
        if self._closed or generation != self._generation:
            return
        self._busy = False
        entries = playback_resume.normalize(self.config.get(self.store_key))
        if key not in entries:
            self._refresh()
            return
        status = _("Could not check availability.") if failed else _("Available") if item else _("Unavailable or ambiguous")
        self._status[key] = status
        self._refresh(key)
        self.status.SetLabel(status)
        live_announce.speak(status)
        self.list.SetFocus()
        if play and item:
            # Close this modal before asking the three-way resume question.
            self.item, self.saved_key = item, key
            self._closed = True
            self.EndModal(wx.ID_OK)

    def _write(self, entries):
        persist = getattr(self.save_entries, 'persist', None)
        if persist is not None:
            if self._busy:
                return False
            store_key = self.store_key
            self._busy = True
            self._update_buttons()
            writing = getattr(self.save_entries, 'writing', lambda *args: None)
            writing(store_key, True)
            def completed(error):
                try:
                    if error is None:
                        self.save_entries.applied(entries, store_key)
                finally:
                    writing(store_key, False)
                if self._closed:
                    return
                self._busy = False
                if error:
                    self.status.SetLabel(_("Could not save playback history changes."))
                    self._update_buttons()
                else:
                    self._generation += 1
                    self._refresh()
                    self.list.SetFocus()
            def worker():
                error = None
                try:
                    persist(entries, store_key)
                except Exception as exc:
                    error = exc
                wx.CallAfter(completed, error)
            try:
                threading.Thread(target=worker, daemon=True, name='ResumeHistoryWriter').start()
            except RuntimeError as error:
                completed(error)
            return True
        try:
            if self.store_key == 'playback_bookmarks':
                result = self.save_entries(entries)
            else:
                result = self.save_entries(entries, self.store_key)
            if result is False:
                raise OSError('history save refused')
        except Exception:
            self.status.SetLabel(_("Could not save playback history changes."))
            return False
        self._generation += 1
        self._refresh()
        self.list.SetFocus()
        return True

    def _remove(self, event=None):
        if self._busy:
            return
        key = self._selected_key()
        if key is None or not self._confirm(_("Remove this saved playback position?")):
            return
        entries = playback_resume.normalize(self.config.get(self.store_key))
        entries.pop(key, None)
        self._write(entries)

    def _clear(self, event=None):
        if self._busy or not self.rows or not self._confirm(_("Remove all saved playback positions?")):
            return
        self._write({})

    def _confirm(self, text):
        dialog = wx.MessageDialog(self, text, _("Continue Watching"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        try:
            return show_modal(dialog) == wx.ID_YES
        finally:
            dialog.Destroy()

    def _close(self, event=None):
        self._closed = True
        self._generation += 1
        self.EndModal(wx.ID_CANCEL)

    def _on_destroy(self, event):
        if event.GetEventObject() is self:
            self._closed = True
            self._generation += 1
        event.Skip()
