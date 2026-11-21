"""Preview and resolve one portable list before creating it."""

import wx

import dvr
import favorite_collections as lists
import favourite_transfer as transfer
import programme_reminders
from background_tasks import start_operation
from i18n import gettext as _
from modal_guard import show_modal
from personal_tools_ui import ToolDialog, error_box


class ImportDialog(ToolDialog):
    help_topic = "favorites"

    def __init__(self, parent, name, rows):
        super().__init__(parent, _("Import Favourite List..."))
        self.rows = rows
        self.choices = [0 if len(options) == 1 else None for item, options in rows]
        self.name_field = self.field(_("List name:"), name)
        self.channels = self.listbox(_("Channels"))
        self.aliases = {
            key: transfer.public_name(name)
            for key, name in programme_reminders.source_names(parent.owner.config).items()
        }
        self.buttons([(_("Choose Channel..."), self.choose)], accept=True)
        self.Bind(wx.EVT_BUTTON, self.accept, id=wx.ID_OK)
        self.channels.Bind(wx.EVT_LISTBOX_DCLICK, self.choose)
        self.refresh_rows(0)
        self.channels.SetFocus()

    def refresh_rows(self, index):
        labels = []
        for (item, options), selected in zip(self.rows, self.choices):
            name = item["name"] or _("(No channel name)")
            if selected is None:
                if len(options) > 1:
                    state = _("The channel cannot be identified unambiguously.")
                else:
                    state = _("Leave unresolved") if options else _("Channel Not Found")
            else:
                state = self.channel_label(options[selected][1], selected, shown_name=name)
            labels.append(name + " — " + state)
        self.channels.Set(labels)
        if labels:
            self.channels.SetSelection(index)

    def channel_label(self, channel, index, *, shown_name=""):
        alias = self.aliases.get(channel.get("provider-id") or channel.get("playlist-id"))
        name = transfer.public_name(dvr.channel_name(channel))
        parts = [] if name.casefold() == shown_name.casefold() else [name]
        if alias and alias.casefold() not in {name.casefold(), shown_name.casefold()}:
            parts.append(alias)
        parts.append(_("Source {number}").format(number=index + 1))
        return " — ".join(filter(None, parts))

    def choose(self, _event):
        i = self.channels.GetSelection()
        if i < 0 or not self.rows[i][1]:
            return
        options = self.rows[i][1]
        labels = [_("Leave unresolved")] + [self.channel_label(ch, n) for n, (_key, ch) in enumerate(options)]
        dlg = wx.SingleChoiceDialog(self, self.rows[i][0]["name"] or _("(No channel name)"), _("Choose Channel..."), labels)
        dlg.SetSelection(0 if self.choices[i] is None else self.choices[i] + 1)
        try:
            if show_modal(dlg) != wx.ID_OK:
                return
            n = dlg.GetSelection()
            self.choices[i] = n - 1 if n > 0 else None
        finally:
            dlg.Destroy()
        self.refresh_rows(i)

    def accept(self, _event):
        try:
            self.list_name = lists.clean_name(self.name_field.GetValue())
            self.entries = transfer.build_entries(self.rows, self.choices)
            lists.create(self.owner.rows, self.list_name)
        except ValueError as error:
            error_box(self, error)
            return
        self.EndModal(wx.ID_OK)


def import_list(parent):
    with wx.FileDialog(
        parent,
        _("Import Favourite List..."),
        wildcard="IPTV (*.aiptvfav)|*.aiptvfav",
        style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
    ) as dlg:
        dlg.help_topic = "favorites"
        if show_modal(dlg) != wx.ID_OK:
            return
        path = dlg.GetPath()
    owner = parent.owner
    channels = owner.all_channels

    def read():
        bundle = transfer.read_list(path)
        return bundle["name"], transfer.match(bundle["entries"], channels)

    def ready(result, error):
        if error or channels is not owner.all_channels:
            error_box(parent, error or _("The channel list changed. Try again."))
            return
        preview = ImportDialog(parent, *result)
        try:
            if show_modal(preview) != wx.ID_OK:
                return
            name, entries = preview.list_name, preview.entries
        finally:
            preview.Destroy()
        created = []

        def add(current):
            if channels is not owner.all_channels:
                raise ValueError(_("The channel list changed. Try again."))
            updated, identity = lists.create(current, name)
            updated[-1]["entries"] = entries
            created.append(identity)
            return updated

        def done(_result, failure):
            if failure:
                error_box(parent, failure)
            else:
                parent.refresh(identity=created[0])
                parent.lists.SetFocus()

        start_operation(
            parent,
            "save-imported-list",
            lambda: owner._save_tool_setting("favorite_collections", add),
            done,
            wx.CallAfter,
        )

    start_operation(parent, "preview-imported-list", read, ready, wx.CallAfter)
