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

    def buttons(self, pairs, *, accept=False):
        row = wx.WrapSizer(wx.HORIZONTAL)
        for text, handler in pairs:
            button = wx.Button(self.panel, label=text)
            button.Bind(wx.EVT_BUTTON, handler)
            row.Add(button, 0, wx.ALL, 4)
        if accept:
            ok = wx.Button(self.panel, wx.ID_OK, _("OK"))
            ok.SetDefault()
            row.Add(ok, 0, wx.ALL, 4)
        row.Add(wx.Button(self.panel, wx.ID_CANCEL, _("Cancel") if accept else _("Close")), 0, wx.ALL, 4)
        self.layout.Add(row, 0, wx.ALL | wx.EXPAND, 4)


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
        self.buttons([], accept=True)
        self.Bind(wx.EVT_BUTTON, self._accept, id=wx.ID_OK)
        (self.end if self.running else self.start).SetFocus()

    @staticmethod
    def local(stamp):
        return dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")

    def _stamp(self, field):
        try:
            return manual_schedule.local_timestamp(field.GetValue())
        except manual_schedule.AmbiguousTime as error:
            choices = [dt.datetime.fromtimestamp(stamp).astimezone().strftime("%Y-%m-%d %H:%M %z")
                       for stamp in error.candidates]
            dialog = wx.SingleChoiceDialog(self, str(error), field.GetName(), choices)
            try:
                if show_modal(dialog) != wx.ID_OK:
                    return None
                return error.candidates[dialog.GetSelection()]
            finally:
                dialog.Destroy()

    def _accept(self, event):
        try:
            start = self.job["start_ts"] if self.running else self._stamp(self.start)
            if start is None:
                return
            end = self._stamp(self.end)
            if end is None:
                return
            manual_schedule.validate_window(start, end, allow_started=self.running)
            self.values = self.title_field.GetValue(), start, end
            self.EndModal(wx.ID_OK)
        except (ValueError, OverflowError, OSError) as error:
            error_box(self, error)


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
                      (_("Move Up"), lambda e: self._move(-1)), (_("Move Down"), lambda e: self._move(1)),
                      (_("Play"), self._play)])
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
        self.entries.Set([e["name"] or _("(No title)") for e in entries])
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
            self._change(lambda value: collections.edit(value, row["id"], add=self.channel),
                         selected=reminders.channel_key(self.channel))

    def _remove(self, event):
        row, entry = self.selected(), self.entry()
        if entry and confirm(self, _("Remove '{name}' from this list?").format(name=entry["name"])):
            self._change(lambda value: collections.edit(value, row["id"], remove=entry["key"]))

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
        finally:
            dialog.Destroy()
        try:
            overlaps = [j for j in scheduler.list_jobs(include_done=False)
                        if (not job or j["id"] != job["id"]) and j["start_ts"] < end and j["stop_ts"] > start]
            if overlaps and not confirm(self, _("This overlaps {count} recording(s). Continue?").format(count=len(overlaps))):
                return
            if job:
                expected = tuple(job[k] for k in ("start_ts", "stop_ts", "status"))
                scheduler.edit_timing(job["id"], start, end, expected=expected)
            else:
                fmt, media, source = self._recording_format_for_channel(channel)
                scheduler.add_manual_job(manual_schedule.build_manual_job(channel, title, start, end, fmt))
            self._tool_status(_("Recording schedule saved."))
        except Exception as error:
            error_box(self, error)

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
        def work():
            try:
                results = saved_searches.scan(database, rules, channels, canceled=cancel.is_set)
                seen = saved_searches.read_seen(history)
                wx.CallAfter(done, results, seen, None)
            except saved_searches.ScanCanceled:
                wx.CallAfter(done, [], {}, None)
            except Exception as error:
                LOG.exception("Saved programme search failed")
                wx.CallAfter(done, [], {}, str(error))
        def done(results, seen, error):
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
            try:
                new_seen, count = saved_searches.commit_seen(history, seen, results)
            except Exception as error:
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
        password = self._backup_password(confirm=True)
        if password is None:
            return
        with wx.FileDialog(self, _("Export Settings"), wildcard=_("Accessible IPTV backup (*.aiptv)") + "|*.aiptv",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if show_modal(dialog) != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            scheduler = self._ensure_dvr_scheduler()
            with scheduler._lock:
                jobs = copy.deepcopy(scheduler.list_jobs())
            bundle = {"config": options.load_config(), "jobs": jobs, "reminders": self._ensure_reminders().list(),
                      "search_seen": saved_searches.read_seen(full_backup.paths()["search_seen"])}
            full_backup.export_bundle(path, bundle, password)
        except Exception as error:
            error_box(self, error)
            return
        message_box(_("Encrypted backup saved, including recording schedules, reminders and saved searches."),
                    _("Settings Backup"), wx.OK | wx.ICON_INFORMATION, parent=self)

    def _import_full_settings(self, event=None):
        with wx.FileDialog(self, _("Import Settings"), wildcard=_("Accessible IPTV backup (*.aiptv)") + "|*.aiptv",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if show_modal(dialog) != wx.ID_OK:
                return
            path = dialog.GetPath()
        password = self._backup_password()
        if password is None:
            return
        try:
            bundle = full_backup.import_bundle(path, password)
            text = (_("Replace settings, {jobs} recording entries and {reminders} reminders? Started recordings will not restart.")
                    .format(jobs=len(bundle["jobs"]), reminders=len(bundle["reminders"])) if "jobs" in bundle else _(
                    "This older backup replaces settings only. Recording schedules and reminders will be kept."))
            text += "\n\n" + _("The app will close. Open it again to finish restoring the backup.")
            if not confirm(self, text):
                return
            scheduler = self._ensure_dvr_scheduler()
            scheduler.stop(wait=True)
            # A recording can start during a modal confirmation. Check again
            # after stopping the poller; starting workers already own a job.
            active = any(j["status"] in {dvr.STATUS_RECORDING, dvr.STATUS_STOPPING} for j in scheduler.list_jobs())
            if active or self.recorder.has_active() or getattr(self, "_catchup_downloads", None):
                scheduler.start()
                raise ValueError(_("Finish recordings and downloads before restoring a backup."))
            try:
                full_backup.stage_restore(bundle, full_backup.paths())
            except Exception:
                scheduler.start()
                raise
        except Exception as error:
            error_box(self, error)
            return
        self._exit_forced = self._exit_requested = True
        self.Close()
