"""Accessible planning, favourites and saved-guide-search dialogs.

Only the UI thread touches wx/configuration. Guide scans and channel resolution
use cancellable workers and reject results from replaced playlists or dialogs.
"""
import copy
import datetime as dt
import logging
import threading
import time

import wx
import dvr
import favorite_collections as collections
import full_backup
import manual_schedule
import options
import programme_reminders as reminders
import saved_searches
from i18n import gettext as _
from modal_guard import message_box, show_modal
from background_tasks import start_operation

LOG = logging.getLogger(__name__)


def error_box(parent, error):
    message_box(_("The operation failed:\n{error}").format(error=error), _("Error"),
                wx.OK | wx.ICON_ERROR, parent=parent)


def confirm(parent, text):
    return message_box(text, _("Confirm"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent=parent) == wx.YES


def text_entry(parent, title, value=""):
    dialog = wx.TextEntryDialog(parent, title, title, value)
    try:
        return dialog.GetValue() if show_modal(dialog) == wx.ID_OK else None
    finally:
        dialog.Destroy()


class ToolDialog(wx.Dialog):
    """Native labels precede their controls in both creation and tab order."""
    help_topic = "personal-tools"

    def __init__(self, parent, title, size=(740, 540)):
        super().__init__(parent, title=title, size=size, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.owner = parent
        self.closed = False
        self.panel = wx.Panel(self)
        self.layout = wx.BoxSizer(wx.VERTICAL)
        self.panel.SetSizer(self.layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.panel, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._destroyed)

    def _destroyed(self, event):
        if event.GetEventObject() is self:
            self.closed = True
        event.Skip()

    def label(self, text):
        self.layout.Add(wx.StaticText(self.panel, label=text), 0, wx.ALL, 6)

    def field(self, text, value="", readonly=False):
        self.label(text)
        field = wx.TextCtrl(self.panel, value=value, style=wx.TE_READONLY if readonly else 0)
        field.SetName(text)
        self.layout.Add(field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        return field

    def listbox(self, text, proportion=1):
        self.label(text)
        control = wx.ListBox(self.panel)
        control.SetName(text)
        self.layout.Add(control, proportion, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        return control

    def buttons(self, pairs, *, accept=False, help_topics=None):
        row = wx.WrapSizer(wx.HORIZONTAL)
        for text, handler in pairs:
            button = wx.Button(self.panel, label=text)
            if help_topics and handler in help_topics:
                button.help_topic = help_topics[handler]
            button.Bind(wx.EVT_BUTTON, handler)
            row.Add(button, 0, wx.ALL, 4)
        if accept:
            ok = wx.Button(self.panel, wx.ID_OK, _("OK"))
            ok.SetDefault()
            row.Add(ok, 0, wx.ALL, 4)
        row.Add(wx.Button(self.panel, wx.ID_CANCEL, _("Cancel") if accept else _("Close")), 0, wx.ALL, 4)
        self.layout.Add(row, 0, wx.ALL | wx.EXPAND, 4)


def field_timestamp(parent, field):
    try:
        return manual_schedule.local_timestamp(field.GetValue())
    except manual_schedule.AmbiguousTime as error:
        choices = [dt.datetime.fromtimestamp(stamp).astimezone().strftime("%Y-%m-%d %H:%M %z")
                   for stamp in error.candidates]
        dialog = wx.SingleChoiceDialog(parent, str(error), field.GetName(), choices)
        try:
            if show_modal(dialog) != wx.ID_OK:
                return None
            return error.candidates[dialog.GetSelection()]
        finally:
            dialog.Destroy()


class RecordingTimesDialog(ToolDialog):
    def __init__(self, parent, channel, job=None):
        super().__init__(parent, _("Schedule by Time"), (650, 450))
        self.job = job
        self.running = bool(job and job["status"] == dvr.STATUS_RECORDING)
        self.label(dvr.channel_name(channel))
        self.title_field = self.field(_("Title"), str(job["title"]) if job else dvr.channel_name(channel), job is not None)
        start = job["start_ts"] if job else (int(time.time()) // 60 + 5) * 60
        end = job["stop_ts"] if job else start + 3600
        self.start = self.field(_("Start (local time, YYYY-MM-DD HH:MM)"), self.local(start), self.running)
        self.end = self.field(_("End (local time, YYYY-MM-DD HH:MM)"), self.local(end))
        from planning_tools_ui import weekday_labels
        self.label(_("Repeat on selected weekdays (none: once):"))
        self.days = wx.CheckListBox(self.panel, choices=weekday_labels())
        self.days.SetName(_("Repeat on selected weekdays (none: once):"))
        self.days.SetCheckedItems(job.get('weekdays', []) if job and job.get('repeat') == 'weekdays' else [])
        self.days.Enable(not self.running and not (job and job.get('repeat') == 'series'))
        self.layout.Add(self.days, 0, wx.EXPAND | wx.ALL, 6)
        self.buttons([], accept=True)
        self.Bind(wx.EVT_BUTTON, self._accept, id=wx.ID_OK)
        best, size = self.GetBestSize(), self.GetSize()
        self.SetMinSize(best)
        self.SetSize((max(size.width, best.width), max(size.height, best.height)))
        (self.end if self.running else self.start).SetFocus()

    @staticmethod
    def local(stamp):
        return dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")

    def _stamp(self, field):
        return field_timestamp(self, field)

    def _accept(self, event):
        try:
            start = self.job["start_ts"] if self.running else self._stamp(self.start)
            if start is None:
                return
            end = self._stamp(self.end)
            if end is None:
                return
            manual_schedule.validate_window(start, end, allow_started=self.running)
            self.weekdays = list(self.days.GetCheckedItems())
            if self.weekdays and dt.datetime.fromtimestamp(start).weekday() not in self.weekdays and not self.running:
                raise ValueError(_("The first recording must start on a selected weekday."))
            self.values = self.title_field.GetValue(), start, end
            self.EndModal(wx.ID_OK)
        except (ValueError, OverflowError, OSError) as error:
            error_box(self, error)


class GuideAtDialog(ToolDialog):
    help_topic = "whats-on-now"

    def __init__(self, parent, owner):
        from background_tasks import LatestTask
        from channel_widgets import _VirtualWhatsOnList
        super().__init__(parent, _("Programme Guide by Time"), size=(780, 540))
        self.client = owner
        self.worker = LatestTask(wx.CallAfter)
        self.channels = None
        self.filtered_programs = []
        self.generation = 0
        self.time = self.field(_("Local date and time (YYYY-MM-DD HH:MM)"), RecordingTimesDialog.local(time.time()))
        self.named = collections.normalize(owner.config.get("favorite_collections"))
        label = _("Channels")
        self.label(label)
        self.scope = wx.Choice(self.panel, choices=[_("All Channels"), _("Favorites")] + [r["name"] for r in self.named])
        self.scope.SetName(label)
        self.scope.SetSelection(0)
        self.layout.Add(self.scope, 0, wx.EXPAND | wx.ALL, 6)
        load = wx.Button(self.panel, label=_("Show Programmes"))
        self.layout.Add(load, 0, wx.ALL, 6)
        self.listbox = _VirtualWhatsOnList(self.panel, self)
        self.listbox.SetName(_("Programme Guide by Time"))
        self.listbox.InsertColumn(0, _("Programme Guide by Time"), width=700)
        self.layout.Add(self.listbox, 1, wx.EXPAND | wx.ALL, 6)
        self.status = wx.StaticText(self.panel, label="")
        self.layout.Add(self.status, 0, wx.ALL, 4)
        self.buttons([(_("Programme Details..."), self.show_details), (_("Schedule Recording"), self.schedule),
                      (_("Set Reminder..."), self.remind)])
        load.Bind(wx.EVT_BUTTON, self.search)
        self.time.Bind(wx.EVT_TEXT, self.invalidate)
        self.scope.Bind(wx.EVT_CHOICE, self.invalidate)
        self.listbox.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.schedule)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.destroy_worker)
        self.time.SetFocus()

    def destroy_worker(self, event):
        if event.GetEventObject() is self:
            self.worker.close()
        event.Skip()

    def invalidate(self, _event=None):
        self.generation += 1
        self.channels = None
        self.filtered_programs = []
        self.listbox.SetItemCount(0)
        self.status.SetLabel("")

    def search(self, _event):
        import favorites
        from playlist import EPGDatabase
        self.invalidate()
        try:
            stamp = field_timestamp(self, self.time)
            if stamp is None:
                return
            when = dt.datetime.fromtimestamp(stamp, dt.timezone.utc)
        except (ValueError, OverflowError, OSError) as error:
            error_box(self, error)
            return
        generation = self.generation
        channels = self.client.all_channels
        selection = self.scope.GetSelection()
        entries = self.named[selection - 2]["entries"] if selection >= 2 else []
        keys = self.client.config.get("favorites", [])
        source_names = reminders.source_names(self.client.config)
        self.status.SetLabel(_("Loading guide channels..."))
        def work(canceled):
            def stale():
                return canceled() or self.generation != generation
            if selection == 1:
                scope = favorites.filter_channels(channels, keys)
            elif selection >= 2:
                scope = [ch for entry, ch in collections.resolve(entries, channels) if ch]
            else:
                scope = None
            db = EPGDatabase(options.get_db_path(), readonly=True)
            try:
                db.conn.set_progress_handler(lambda: int(stale()), 2000)
                rows = db.programmes_at(when, scope, source_names)
            finally:
                db.close()
            if scope is None and not stale():
                self.client._program_match_index()
            valid = []
            for row in rows:
                if stale():
                    return []
                try:
                    times = [dvr.parse_epg_utc(row[k]).astimezone() for k in ("start", "end")]
                except (ValueError, TypeError, OverflowError, OSError):
                    continue
                row["time_label"] = " – ".join(stamp.strftime("%Y-%m-%d %H:%M") for stamp in times)
                valid.append(row)
            return valid
        def done(rows, error):
            if generation != self.generation:
                return
            if error or self.client.all_channels is not channels:
                self.status.SetLabel("")
                error_box(self, error or _("The channel list changed. Try again."))
                return
            self.channels = channels
            self.filtered_programs = rows
            self.listbox.SetItemCount(len(rows))
            self.listbox.Refresh()
            self.status.SetLabel(_("{count} programs").format(count=len(rows)))
            if rows:
                self.listbox.Select(0)
                self.listbox.Focus(0)
                self.listbox.SetFocus()
            else:
                message_box(_("No programmes were found for this time and channel selection."), self.GetTitle(),
                            wx.OK | wx.ICON_INFORMATION, parent=self)
        self.worker.submit(work, done)

    def selected(self):
        index = self.listbox.GetFirstSelected()
        if not 0 <= index < len(self.filtered_programs):
            return None, None
        if self.channels is not self.client.all_channels:
            self.invalidate()
            error_box(self, _("The channel list changed. Try again."))
            return None, None
        row = self.filtered_programs[index]
        ch = row.get("playlist_channel") or self.client._find_matching_channel_for_program(row)
        if not ch:
            error_box(self, _("Channel Not Found"))
        return ch, row

    def show_details(self, _event):
        from playlist import EPGDatabase
        index = self.listbox.GetFirstSelected()
        if not 0 <= index < len(self.filtered_programs):
            return
        row = self.filtered_programs[index]
        generation = self.generation
        def read():
            db = EPGDatabase(options.get_db_path(), readonly=True)
            try:
                return db.programme_details(row)
            finally:
                db.close()
        def ready(info, error):
            if self.generation != generation or self.listbox.GetFirstSelected() != index:
                return
            if self.channels is not self.client.all_channels:
                self.invalidate()
                error_box(self, _("The channel list changed. Try again."))
                return
            if error:
                error_box(self, error)
                return
            lines = [row['title'], row.get('channel_label') or row['channel_name'], row['time_label']]
            if info['subtitle']:
                lines.append(info['subtitle'])
            if info['episode']:
                lines.append(_("Episode: {episode}").format(episode=info['episode']))
            lines.append(info['description'] or _("No description available for this programme."))
            dialog = ToolDialog(self, _("Programme Details..."))
            dialog.help_topic = 'whats-on-now'
            field = wx.TextCtrl(dialog.panel, value="\n\n".join(lines), style=wx.TE_MULTILINE | wx.TE_READONLY)
            field.SetName(_("Details"))
            dialog.layout.Add(field, 1, wx.EXPAND | wx.ALL, 8)
            dialog.buttons([])
            field.SetInsertionPoint(0)
            field.SetFocus()
            try:
                show_modal(dialog)
            finally:
                dialog.Destroy()
                self.listbox.SetFocus()
        start_operation(self, "guide-details", read, ready, wx.CallAfter)

    def schedule(self, _event):
        channel, row = self.selected()
        if channel:
            self.client._schedule_program_recording(channel, {k: v for k, v in row.items() if k != "playlist_channel"})

    def remind(self, _event):
        channel, row = self.selected()
        if channel:
            self.client._set_programme_reminder(channel, row)


class FavouriteListsDialog(ToolDialog):
    def __init__(self, parent):
        super().__init__(parent, _("Favourite Lists"))
        self.channel = copy.deepcopy(parent._selected_channel())
        self.lists = self.listbox(_("Favourite Lists"))
        self.entries = self.listbox(_("Channels"), 2)
        self.status = wx.StaticText(self.panel, label="")
        self.layout.Add(self.status, 0, wx.ALL, 6)
        self.buttons([(_("New..."), self._new), (_("Rename..."), self._rename), (_("Delete List"), self._delete),
                      (_("Add Selected Channel"), self._add), (_("Remove Channel"), self._remove),
                      (_("Relink Missing Channel..."), self._relink),
                      (_("Export Favourite List..."), self._export_list), (_("Import Favourite List..."), self._import_list),
                      (_("Move Up"), lambda e: self._move(-1)), (_("Move Down"), lambda e: self._move(1)),
                      (_("Play"), self._play)],
                     help_topics={self._export_list: "favorites", self._import_list: "favorites"})
        self.lists.Bind(wx.EVT_LISTBOX, lambda e: self._entries())
        self.entries.Bind(wx.EVT_LISTBOX_DCLICK, self._play)
        self.entries.Bind(wx.EVT_KEY_DOWN, self._key)
        self.refresh()
        self.lists.SetFocus()

    def selected(self):
        index = self.lists.GetSelection()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def entry(self):
        row, index = self.selected(), self.entries.GetSelection()
        return row["entries"][index] if row and 0 <= index < len(row["entries"]) else None

    def _export_list(self, _event):
        import favourite_transfer as transfer
        row = self.selected()
        if not row:
            return
        with wx.FileDialog(self, _("Export Favourite List..."), wildcard='IPTV (*.aiptvfav)|*.aiptvfav',
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            dialog.help_topic = "favorites"
            if show_modal(dialog) != wx.ID_OK:
                return
            path = dialog.GetPath()
        channels = self.owner.all_channels
        def done(_result, error):
            if error:
                error_box(self, error)
            else:
                self.status.SetLabel(_("Saved to {path}.").format(path=path))
        start_operation(self, 'export-list', lambda: transfer.export_list(path, row, channels), done, wx.CallAfter)

    def _import_list(self, _event):
        from favourite_transfer_ui import import_list
        import_list(self)

    def refresh(self, identity=None, entry=None):
        old = self.selected() if hasattr(self, "rows") else None
        identity = identity or (old["id"] if old else None)
        self.rows = collections.normalize(self.owner.config.get("favorite_collections"))
        self.lists.Set([row["name"] for row in self.rows])
        if self.rows:
            self.lists.SetSelection(next((i for i, row in enumerate(self.rows) if row["id"] == identity), 0))
        self._entries(entry)

    def _entries(self, selected=None):
        row = self.selected()
        entries = row["entries"] if row else []
        self.entries.Set(collections.variant_labels([e["name"] or _("(No channel name)") for e in entries]))
        if entries:
            self.entries.SetSelection(next((i for i, e in enumerate(entries) if e["key"] == selected), 0))
        self.status.SetLabel(_("Selected channel: {name}").format(name=dvr.channel_name(self.channel))
                             if self.channel else _("No channel selected."))

    def _change(self, operation, *, selected=None):
        try:
            self.owner._save_tool_setting("favorite_collections", operation)
            self.refresh(entry=selected)
        except Exception as error:
            error_box(self, error)

    def _new(self, event):
        name = text_entry(self, _("Favourite List Name"))
        if name is not None:
            created = []
            def operation(value):
                rows, identity = collections.create(value, name)
                created.append(identity)
                return rows
            self._change(operation)
            if created:
                self.refresh(created[0])

    def _rename(self, event):
        row = self.selected()
        if row:
            name = text_entry(self, _("Favourite List Name"), row["name"])
            if name is not None:
                self._change(lambda value: collections.edit(value, row["id"], name=name))

    def _delete(self, event):
        row = self.selected()
        if row and confirm(self, _("Delete favourite list '{name}'?").format(name=row["name"])):
            self._change(lambda value: collections.edit(value, row["id"], delete=True))

    def _add(self, event):
        row = self.selected()
        if row and self.channel:
            channels, candidate = self.owner.all_channels, self.channel
            def ready(entry, error):
                if error or self.owner.all_channels is not channels:
                    error_box(self, error or _("The channel list changed. Try again."))
                    return
                self._change(lambda value: collections.edit(value, row["id"], selection=entry),
                             selected=entry["key"])
            if len(channels) == 1:
                try:
                    ready(collections.selected_entry(candidate, channels), None)
                except ValueError as error:
                    error_box(self, error)
            else:
                start_operation(self, "add-favourite", lambda: collections.selected_entry(candidate, channels),
                                ready, wx.CallAfter)

    def _remove(self, event):
        row, entry = self.selected(), self.entry()
        if entry and confirm(self, _("Remove '{name}' from this list?").format(name=entry["name"])):
            self._change(lambda value: collections.edit(value, row["id"], remove=entry["key"]))

    def _relink(self, _event):
        row, entry = self.selected(), self.entry()
        if not row or not entry:
            return
        query = text_entry(self, _("Search for the replacement channel:"))
        if query is None:
            return
        channels = self.owner.all_channels
        from main import _source_scope_id
        sources = {_source_scope_id(src): self.owner._scope_choice_label(src)
                   for src in self.owner._scoped_sources()}
        def find():
            if collections.resolve([entry], channels)[0][1] is not None:
                raise ValueError(_("This favourite is already available."))
            needle = query.strip().casefold()
            found = []
            for ch in channels:
                if not ch.get("url") or ch.get("kind") in {"movie", "series"}:
                    continue
                fields = [reminders.safe_title(dvr.channel_name(ch))]
                fields.extend(reminders.safe_title(value) for value in
                              (ch.get("group") or ch.get("group-title"), ch.get("tvg-id"),
                               sources.get(ch.get("playlist-id") or ch.get("provider-id"))))
                label = " – ".join(dict.fromkeys(f for f in fields if f))
                if needle in label.casefold():
                    found.append((label, ch))
                    if len(found) > 200:
                        raise ValueError(_("Too many matches. Enter a more specific channel name."))
            return found
        def ready(found, error):
            if error or self.owner.all_channels is not channels:
                error_box(self, error or _("The channel list changed. Try again."))
                return
            if not found:
                error_box(self, _("Channel Not Found"))
                return
            labels = collections.variant_labels([label for label, ch in found])
            choose = wx.SingleChoiceDialog(self, _("Choose a replacement channel:"),
                                           _("Favourite Lists"), labels)
            try:
                if show_modal(choose) != wx.ID_OK:
                    return
                _label, candidate = found[choose.GetSelection()]
            finally:
                choose.Destroy()
            def verify():
                return collections.selected_entry(candidate, channels)
            def save(replacement, error):
                if error or self.owner.all_channels is not channels:
                    error_box(self, error or _("The channel cannot be identified unambiguously."))
                    return
                self._change(lambda value: collections.relink(value, row["id"], entry["key"], candidate,
                                                             selection=replacement), selected=replacement["key"])
                self.entries.SetFocus()
            start_operation(self, "verify-replacement", verify, save, wx.CallAfter)
        start_operation(self, "find-replacement", find, ready, wx.CallAfter)

    def _move(self, delta):
        row, entry = self.selected(), self.entry()
        if entry:
            self._change(lambda value: collections.edit(value, row["id"], move=(entry["key"], delta)),
                         selected=entry["key"])
            self.entries.SetFocus()

    def _key(self, event):
        key = event.GetKeyCode()
        if event.ControlDown() and key in (wx.WXK_UP, wx.WXK_DOWN):
            self._move(-1 if key == wx.WXK_UP else 1)
        elif key == wx.WXK_RETURN:
            self._play(event)
        else:
            event.Skip()

    def _play(self, event):
        entry = self.entry()
        if entry and not getattr(self, "resolving", False):
            self.resolving = True
            channels = self.owner.all_channels
            def work():
                resolved = collections.resolve([entry], channels)[0][1]
                wx.CallAfter(done, resolved)
            def done(channel):
                if self.closed:
                    return
                self.resolving = False
                if self.owner.all_channels is not channels:
                    error_box(self, _("The channel list changed. Try again."))
                elif channel is None:
                    error_box(self, _("Channel Not Found"))
                else:
                    self.EndModal(wx.ID_OK)
                    wx.CallAfter(self.owner._play_live_channel, channel)
            threading.Thread(target=work, name="favourite-resolve", daemon=True).start()


class SearchRuleDialog(ToolDialog):
    def __init__(self, parent, owner, rule=None):
        super().__init__(parent, _("Saved Programme Search"), (640, 410))
        self.rule = rule
        self.query = self.field(_("Search"), rule["query"] if rule else "")
        self.description = wx.CheckBox(self.panel, label=_("Search descriptions too"))
        self.description.SetValue(bool(rule and rule["description"]))
        self.layout.Add(self.description, 0, wx.ALL, 6)
        self.enabled = wx.CheckBox(self.panel, label=_("Enabled"))
        self.enabled.SetValue(rule["enabled"] if rule else True)
        self.layout.Add(self.enabled, 0, wx.ALL, 6)
        self.label(_("Channels"))
        self.scopes = [list(rule["channels"]) if rule else []]
        labels = [_("Keep chosen channels") if rule else _("All Channels")]
        if rule:
            labels.append(_("All Channels"))
            self.scopes.append([])
        channel = owner._selected_channel()
        if channel and reminders.channel_key(channel):
            labels.append(_("Selected channel: {name}").format(name=dvr.channel_name(channel)))
            self.scopes.append([reminders.channel_key(channel)])
        for collection in collections.normalize(owner.config.get("favorite_collections")):
            if collection["entries"]:
                labels.append(collection["name"])
                self.scopes.append([e["key"] for e in collection["entries"]])
        self.scope = wx.Choice(self.panel, choices=labels)
        self.scope.SetName(_("Channels"))
        self.scope.SetSelection(0)
        self.layout.Add(self.scope, 0, wx.EXPAND | wx.ALL, 6)
        self.buttons([], accept=True)
        self.Bind(wx.EVT_BUTTON, self._accept, id=wx.ID_OK)
        self.query.SetFocus()

    def _accept(self, event):
        try:
            self.value = saved_searches.new_rule(self.query.GetValue(),
                channels=self.scopes[self.scope.GetSelection()], description=self.description.GetValue())
            if self.rule:
                self.value["id"] = self.rule["id"]
            self.value["enabled"] = self.enabled.GetValue()
            self.EndModal(wx.ID_OK)
        except ValueError as error:
            error_box(self, error)


class SavedSearchesDialog(ToolDialog):
    def __init__(self, parent):
        super().__init__(parent, _("Saved Programme Searches"), (860, 650))
        self.rules = self.listbox(_("Saved Programme Searches"))
        self.matches = self.listbox(_("Search Results"), 2)
        self.details = self.field(_("Description"), readonly=True)
        self.status = wx.StaticText(self.panel, label="")
        self.layout.Add(self.status, 0, wx.ALL, 6)
        self.buttons([(_("New..."), lambda e: self._edit(new=True)), (_("Edit..."), lambda e: self._edit()),
                      (_("Delete"), self._delete), (_("Refresh"), lambda e: parent._scan_saved_searches()),
                      (_("Set Reminder..."), lambda e: self._action(False)),
                      (_("Schedule Recording..."), lambda e: self._action(True))])
        self.rules.Bind(wx.EVT_LISTBOX, lambda e: self.refresh_results())
        self.matches.Bind(wx.EVT_LISTBOX, lambda e: self._details())
        self.refresh()
        self.rules.SetFocus()

    def selected(self):
        index = self.rules.GetSelection()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def refresh(self):
        old = self.selected() if hasattr(self, "rows") else None
        self.rows = saved_searches.normalize(self.owner.config.get("saved_programme_searches"))
        self.rules.Set([r["query"] + ("" if r["enabled"] else " — " + _("Disabled")) for r in self.rows])
        if self.rows:
            self.rules.SetSelection(next((i for i, r in enumerate(self.rows) if old and r["id"] == old["id"]), 0))
        self.refresh_results()

    def refresh_results(self):
        row = self.selected()
        index = self.matches.GetSelection()
        old = self.results[index]["id"] if hasattr(self, "results") and 0 <= index < len(self.results) else None
        result = next((r for r in getattr(self.owner, "_saved_search_results", []) if row and r["rule"] == row["id"]), {})
        self.results = result.get("matches", [])
        self.matches.Set(["{0} — {1} — {2}".format(
            dvr.parse_epg_utc(r["start"]).astimezone().strftime("%Y-%m-%d %H:%M"), r["title"], r["channel"])
            for r in self.results])
        if self.results:
            self.matches.SetSelection(next((i for i, r in enumerate(self.results) if r["id"] == old), 0))
        status = getattr(self.owner, "_saved_search_status", "")
        if result.get("truncated"):
            status += " " + _("Only the first 500 matches are shown. Narrow the search.")
        self.status.SetLabel(status)
        self._details()

    def _details(self):
        index = self.matches.GetSelection()
        self.details.ChangeValue(self.results[index]["description"] if 0 <= index < len(self.results) else "")

    def _edit(self, new=False):
        old = None if new else self.selected()
        if not new and old is None:
            return
        dialog = SearchRuleDialog(self, self.owner, old)
        try:
            if show_modal(dialog) != wx.ID_OK:
                return
            value = dialog.value
        finally:
            dialog.Destroy()
        def operation(raw):
            rows = saved_searches.normalize(raw)
            if new and len(rows) >= saved_searches.MAX_RULES:
                raise ValueError(_("You can save up to 30 programme searches."))
            if old and not any(r["id"] == old["id"] for r in rows):
                raise ValueError(_("The operation could not be completed. Refresh and try again."))
            return [r for r in rows if r["id"] != value["id"]] + [value]
        self._change(operation)

    def _change(self, operation):
        try:
            self.owner._save_tool_setting("saved_programme_searches", operation)
            self.owner._invalidate_saved_searches()
            self.refresh()
            self.owner._scan_saved_searches()
        except Exception as error:
            error_box(self, error)

    def _delete(self, event):
        row = self.selected()
        if row and confirm(self, _("Delete saved search '{name}'?").format(name=row["query"])):
            self._change(lambda raw: [r for r in saved_searches.normalize(raw) if r["id"] != row["id"]])

    def _action(self, recording):
        index = self.matches.GetSelection()
        if index < 0 or getattr(self, "resolving", False):
            return
        result = copy.deepcopy(self.results[index])
        channels = self.owner.all_channels
        self.resolving = True
        def work():
            entries = [{"key": key, "name": ""} for key in result["channel_keys"]]
            found = [channel for entry, channel in collections.resolve(entries, channels) if channel]
            wx.CallAfter(done, found)
        def done(found):
            if self.closed:
                return
            self.resolving = False
            if channels is not self.owner.all_channels or not found:
                error_box(self, _("Channel Not Found"))
                return
            channel = found[0]
            if len(found) > 1:
                labels = [dvr.channel_name(c) + " — " + str(c.get("playlist-id", "")) for c in found]
                dialog = wx.SingleChoiceDialog(self, _("Channel"), _("Choose Channel"), labels)
                try:
                    if show_modal(dialog) != wx.ID_OK:
                        return
                    channel = found[dialog.GetSelection()]
                finally:
                    dialog.Destroy()
            if channels is not self.owner.all_channels:
                error_box(self, _("The channel list changed. Try again."))
                return
            callback = self.owner._schedule_program_recording if recording else self.owner._set_programme_reminder
            callback(channel, result)
        threading.Thread(target=work, name="search-channel-resolve", daemon=True).start()


class PersonalToolsMixin:
    def _show_guide_at(self, _event=None, *, parent=None):
        if not self.config.get("epg_enabled", True):
            message_box(_("EPG is not enabled."), _("EPG Not Available"), wx.OK | wx.ICON_INFORMATION, parent=self)
            return
        dialog = GuideAtDialog(parent or self, self)
        try:
            show_modal(dialog)
        finally:
            dialog.Destroy()

    def _tool_status(self, text):
        bar = getattr(self, "_info_status_bar", None)
        if bar is not None:
            bar.SetStatusText(text)

    def _save_tool_setting(self, key, operation):
        # Re-read under the existing configuration save lock: a dialog may have
        # run nested event loops while a playlist worker updated another key.
        with options._SAVE_LOCK:
            config = options.load_config()
            config[key] = operation(config.get(key))
            if options._save_config_locked(config) is False:
                raise OSError(_("The settings could not be saved. Check the free space and write permissions, then try again."))
        self.config[key] = config[key]

    def _show_favourite_lists(self, event=None):
        dialog = FavouriteListsDialog(self)
        try:
            show_modal(dialog)
        finally:
            dialog.closed = True
            dialog.Destroy()

    def _add_personal_tools_menu(self, menu):
        item = menu.Append(wx.ID_ANY, _("Favourite Lists..."))
        menu.Bind(wx.EVT_MENU, self._show_favourite_lists, item)
        item = menu.Append(wx.ID_ANY, _("Saved Programme Searches..."))
        menu.Bind(wx.EVT_MENU, self._show_saved_searches, item)
        import user_guide
        user_guide.set_menu_help(self, item, "personal-tools")

    def _schedule_by_time(self, event=None, job=None):
        if 'schedule-edit' in getattr(self, '_background_operations', ()):
            self._tool_status(_("Processing recordings..."))
            return
        channel = copy.deepcopy(job["channel"] if job else self._selected_channel())
        if not channel:
            error_box(self, _("No channel selected."))
            return
        scheduler = self._ensure_dvr_scheduler(start=True)
        dialog = RecordingTimesDialog(self, channel, job)
        try:
            if show_modal(dialog) != wx.ID_OK:
                return
            title, start, end = dialog.values
            days = dialog.weekdays
            edit_days = job is None or not dialog.running and job.get('repeat') != 'series'
        finally:
            dialog.Destroy()
        try:
            import recording_limits
            warning = recording_limits.warning(self.config, channel, start, end,
                                               scheduler.list_jobs(include_done=False), exclude=job["id"] if job else None)
            if warning:
                from recording_conflicts_ui import confirm_conflicts
                if not confirm_conflicts(self, channel, start, end, warning, exclude=job['id'] if job else None):
                    return
            if job:
                expected = tuple(job[k] for k in ("start_ts", "stop_ts", "status"))
                edit = days if edit_days and (days or job.get('repeat') == 'weekdays') else None
                operation = lambda: scheduler.edit_timing(job["id"], start, end, expected=expected, weekdays=edit)
            else:
                fmt, media, source = self._recording_format_for_channel(channel)
                proposal = manual_schedule.build_manual_job(channel, title, start, end, fmt)
                if days:
                    proposal.update(repeat='weekdays', weekdays=days)
                operation = lambda: scheduler.add_manual_job(proposal)
        except Exception as error:
            error_box(self, error)
            return
        self._tool_status(_("Processing recordings..."))
        def done(_result, failure):
            if failure:
                error_box(self, failure)
            else:
                self._tool_status(_("Recording schedule saved."))
        start_operation(self, 'schedule-edit', operation, done, wx.CallAfter)

    def _start_saved_searches(self):
        self._saved_search_stopped = False
        self._saved_search_cancel = threading.Event()
        self._saved_search_results = []
        self._saved_search_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._scan_saved_searches, self._saved_search_timer)
        self._saved_search_timer.Start(15 * 60 * 1000)
        wx.CallLater(30000, self._scan_saved_searches)

    def _invalidate_saved_searches(self):
        cancel = getattr(self, "_saved_search_cancel", None)
        if cancel:
            cancel.set()
        self._saved_search_results = []

    def _stop_saved_searches(self):
        self._saved_search_stopped = True
        self._invalidate_saved_searches()
        timer = getattr(self, "_saved_search_timer", None)
        if timer:
            timer.Stop()

    def _show_saved_searches(self, event=None):
        dialog = SavedSearchesDialog(self)
        self._saved_search_dialog = dialog
        self._scan_saved_searches()
        try:
            show_modal(dialog)
        finally:
            self._saved_search_dialog = None
            dialog.closed = True
            dialog.Destroy()

    def _search_status(self, text):
        self._saved_search_status = text
        dialog = getattr(self, "_saved_search_dialog", None)
        if dialog and not dialog.closed:
            dialog.refresh_results()

    def _scan_saved_searches(self, event=None):
        if getattr(self, "_saved_search_stopped", False):
            return
        worker = getattr(self, "_saved_search_worker", None)
        if worker and worker.is_alive():
            self._saved_search_rescan = True
            return
        rules = saved_searches.normalize(self.config.get("saved_programme_searches"))
        if not any(r["enabled"] for r in rules):
            self._saved_search_results = []
            self._search_status(_("No enabled saved searches."))
            return
        channels, signature = self.all_channels, saved_searches.signature(rules)
        cancel = self._saved_search_cancel = threading.Event()
        self._saved_search_rescan = False
        database = options.get_db_path()
        history = full_backup.paths()["search_seen"]
        self._search_status(_("Searching programmes..."))
        canceled = lambda: cancel.is_set() or channels is not self.all_channels
        def work():
            try:
                results = saved_searches.scan(database, rules, channels, canceled=canceled)
                seen = saved_searches.read_seen(history)
                if canceled():
                    raise saved_searches.ScanCanceled()
                _new_seen, count = saved_searches.commit_seen(history, seen, results, canceled=canceled)
                wx.CallAfter(done, results, count, None)
            except saved_searches.ScanCanceled:
                wx.CallAfter(done, [], {}, None)
            except Exception as error:
                LOG.exception("Saved programme search failed")
                wx.CallAfter(done, [], {}, str(error))
        def done(results, count, error):
            if getattr(self, "_saved_search_stopped", False):
                return
            self._saved_search_worker = None
            stale = (cancel.is_set() or channels is not self.all_channels
                     or signature != saved_searches.signature(self.config.get("saved_programme_searches")))
            if stale or getattr(self, "_saved_search_rescan", False):
                wx.CallAfter(self._scan_saved_searches)
                return
            if error:
                self._search_status(_("The operation failed:\n{error}").format(error=error))
                return
            self._saved_search_results = results
            text = _("New programme matches: {count}.").format(count=count)
            self._search_status(text)
            if count:
                self._tool_status(text)
                if self.config.get("announcement_level", 2) >= 1:
                    self._speak(text, "guide")
        self._saved_search_worker = threading.Thread(target=work, name="saved-programme-search", daemon=True)
        self._saved_search_worker.start()

    def _export_full_settings(self, event=None):
        if 'backup' in getattr(self, '_background_operations', ()):
            return
        password = self._backup_password(confirm=True)
        if password is None:
            return
        with wx.FileDialog(self, _("Export Settings"), wildcard=_("Accessible IPTV backup (*.aiptv)") + "|*.aiptv",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if show_modal(dialog) != wx.ID_OK:
                return
            path = dialog.GetPath()
        scheduler = self._ensure_dvr_scheduler()
        def work():
            jobs = copy.deepcopy(scheduler.list_jobs())
            bundle = {"config": options.load_config(), "jobs": jobs, "reminders": self._ensure_reminders().list(),
                      "search_seen": saved_searches.read_seen(full_backup.paths()["search_seen"])}
            full_backup.export_bundle(path, bundle, password)
        def done(_result, error):
            if error:
                error_box(self, error)
            else:
                message_box(_("Encrypted backup saved, including recording schedules, reminders and saved searches."),
                            _("Settings Backup"), wx.OK | wx.ICON_INFORMATION, parent=self)
        start_operation(self, 'backup', work, done, wx.CallAfter)

    def _import_full_settings(self, event=None):
        if 'backup' in getattr(self, '_background_operations', ()):
            return
        with wx.FileDialog(self, _("Import Settings"), wildcard=_("Accessible IPTV backup (*.aiptv)") + "|*.aiptv",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if show_modal(dialog) != wx.ID_OK:
                return
            path = dialog.GetPath()
        password = self._backup_password()
        if password is None:
            return
        start_operation(self, 'backup', lambda: full_backup.import_bundle(path, password),
                        self._backup_import_ready, wx.CallAfter)

    def _backup_import_ready(self, bundle, error):
        if error:
            error_box(self, error)
            return
        text = (_("Replace settings, {jobs} recording entries and {reminders} reminders? Started recordings will not restart.")
                .format(jobs=len(bundle["jobs"]), reminders=len(bundle["reminders"])) if "jobs" in bundle else _(
                "This older backup replaces settings only. Recording schedules and reminders will be kept."))
        text += "\n\n" + _("The app will close. Open it again to finish restoring the backup.")
        if not confirm(self, text):
            return
        scheduler = self._ensure_dvr_scheduler()
        downloads = bool(getattr(self, '_catchup_downloads', None) or getattr(self, '_pending_recording_starts', None))
        self._stop_reminders()
        self._stop_saved_searches()
        self.Enable(False)
        def work():
            scheduler.stop(wait=True)
            active = any(j["status"] in {dvr.STATUS_RECORDING, dvr.STATUS_STOPPING} for j in scheduler.list_jobs())
            if active or self.recorder.has_active() or downloads:
                raise ValueError(_("Finish recordings and downloads before restoring a backup."))
            full_backup.stage_restore(bundle, full_backup.paths())
        def done(_result, failure):
            self.Enable(True)
            if failure:
                scheduler.start()
                self._start_reminders()
                self._start_saved_searches()
                error_box(self, failure)
            else:
                self._exit_forced = self._exit_requested = True
                self.Close()
        start_operation(self, 'backup', work, done, wx.CallAfter)
