"""Recording budgets for configured and autodetected provider accounts."""
import threading

import wx

import account_info
import recording_limits
import user_guide
from i18n import gettext as _
from modal_guard import message_box, show_modal


class RecordingLimitsDialog(wx.Dialog):
    def __init__(self, owner):
        super().__init__(owner, title=_("Recording Connection Limits"), size=(730, 430),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.owner, self.closed, self.accounts = owner, False, []
        layout = wx.BoxSizer(wx.VERTICAL)
        label = _("Provider accounts")
        layout.Add(wx.StaticText(self, label=label), 0, wx.ALL, 8)
        self.list = wx.ListBox(self)
        self.list.SetName(label)
        layout.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        label = _("Connections available for recordings (0 = no additional limit):")
        layout.Add(wx.StaticText(self, label=label), 0, wx.ALL, 8)
        self.limit = wx.SpinCtrl(self, min=0, max=64)
        self.limit.SetName(label)
        layout.Add(self.limit, 0, wx.ALL, 8)
        explanation = wx.StaticText(self, label=_("Allow for playback and other devices when setting this budget. Existing recordings are never stopped to free a connection."))
        explanation.Wrap(680)
        layout.Add(explanation, 0, wx.ALL | wx.EXPAND, 8)
        self.status = wx.StaticText(self, label=_("Loading accounts..."))
        layout.Add(self.status, 0, wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.save = wx.Button(self, label=_("Save"))
        self.save.Disable()
        row.Add(self.save, 0, wx.ALL, 8)
        row.Add(wx.Button(self, wx.ID_CANCEL, label=_("Close")), 0, wx.ALL, 8)
        layout.Add(row, 0, wx.ALIGN_RIGHT)
        self.SetSizer(layout)
        self.list.Bind(wx.EVT_LISTBOX, self.select)
        self.save.Bind(wx.EVT_BUTTON, self.commit)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.destroying)
        user_guide.set_help_topic(self, "scheduled-recordings")
        sources = list(owner.config.get("playlists", []))
        channels = getattr(owner, "all_channels", ())
        def worker():
            try:
                accounts, error = account_info.discover_accounts(sources, channels), ""
            except Exception as exc:
                accounts, error = [], str(exc)
            wx.CallAfter(self.loaded, accounts, error)
        threading.Thread(target=worker, daemon=True).start()

    def destroying(self, event):
        if event.GetEventObject() is self:
            self.closed = True
        event.Skip()

    def loaded(self, accounts, error):
        if self.closed:
            return
        self.accounts = accounts
        self.list.Set([account_info.account_label(account) for account in accounts])
        self.status.SetLabel(error or (_("No provider accounts found.") if not accounts else ""))
        self.save.Enable(bool(accounts))
        if accounts:
            self.list.SetSelection(0)
            self.select()

    def select(self, _event=None):
        index = self.list.GetSelection()
        if 0 <= index < len(self.accounts):
            key = recording_limits.account_key(self.accounts[index])
            self.limit.SetValue(recording_limits.normalize(self.owner.config.get("recording_connection_limits")).get(key, 0))

    def commit(self, _event):
        index = self.list.GetSelection()
        if not 0 <= index < len(self.accounts):
            return
        key, value = recording_limits.account_key(self.accounts[index]), self.limit.GetValue()
        def update(old):
            result = recording_limits.normalize(old)
            result[key] = value
            return recording_limits.normalize(result)
        try:
            self.owner._save_tool_setting("recording_connection_limits", update)
            self.status.SetLabel(_("Recording connection limit saved."))
        except Exception as error:
            message_box(str(error), _("Error"), wx.OK | wx.ICON_ERROR, parent=self)


def show_limits(owner):
    dialog = RecordingLimitsDialog(owner)
    try:
        show_modal(dialog)
    finally:
        dialog.closed = True
        dialog.Destroy()
