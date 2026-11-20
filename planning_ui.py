"""Reminder and recording-storage UI, sharing the application's modal guard."""
import datetime
import logging
import os
import threading
import time

import wx

import programme_reminders as reminders
import recording_storage
from i18n import gettext as _
from modal_guard import message_box, show_modal
from options import get_dvr_schedule_path, get_recordings_dir, save_config
from background_tasks import start_operation
from planning_tools_ui import ReminderAlert

LOG = logging.getLogger(__name__)
_REMINDER_INIT_LOCK = threading.RLock()


def ask_minutes(parent, value):
    dialog = wx.NumberEntryDialog(parent, _("Notify before the programme starts (minutes):"),
                                  _("Minutes:"), _("Programme Reminders"), value, 0, 120)
    try:
        return dialog.GetValue() if show_modal(dialog) == wx.ID_OK else None
    finally:
        dialog.Destroy()


class RemindersDialog(wx.Dialog):
    help_topic = 'channel-epg'

    def __init__(self, parent, store):
        super().__init__(parent, title=_("Programme Reminders"), size=(800, 450),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.store = store
        self.owner = parent
        self.busy = False
        self.closed = False
        self.Bind(wx.EVT_WINDOW_DESTROY, self._destroyed)
        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.SetName(_("Programme Reminders"))
        for index, (label, width) in enumerate([(_("Time"), 160), (_("Title"), 250),
                                               (_("Channel"), 180), (_("Status"), 150),
                                               (_("Lead time (minutes)"), 160)]):
            self.list.InsertColumn(index, label, width=width)
        layout.Add(self.list, 1, wx.ALL | wx.EXPAND, 10)
        self.status = wx.StaticText(panel, label='')
        layout.Add(self.status, 0, wx.LEFT | wx.RIGHT, 10)
        buttons = wx.WrapSizer(wx.HORIZONTAL)
        self.edit = wx.Button(panel, label=_("Set Reminder..."))
        self.remove = wx.Button(panel, label=_("Delete"))
        self.clear = wx.Button(panel, label=_("Clear All Reminders"))
        self.calendar = wx.Button(panel, label=_("Export to Calendar..."))
        self.calendar.Bind(wx.EVT_BUTTON, self._export_calendar)
        refresh = wx.Button(panel, label=_("Refresh"))
        close = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        for button in (self.edit, self.remove, self.clear, self.calendar, refresh, close):
            buttons.Add(button, 0, wx.RIGHT, 5)
        layout.Add(buttons, 0, wx.ALL, 10)
        panel.SetSizer(layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.Bind(wx.EVT_BUTTON, self._edit, self.edit)
        self.Bind(wx.EVT_BUTTON, self._delete, self.remove)
        self.Bind(wx.EVT_BUTTON, self._clear, self.clear)
        self.Bind(wx.EVT_BUTTON, lambda event: self._refresh(), refresh)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._edit)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self._buttons())
        self.list.Bind(wx.EVT_KEY_DOWN, self._key)
        self._refresh()
        self.list.SetFocus()

    def _destroyed(self, event):
        if event.GetEventObject() is self:
            self.closed = True
        event.Skip()

    def _selected(self):
        index = self.list.GetFirstSelected()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def _buttons(self):
        row = self._selected()
        self.edit.Enable(bool(not self.busy and row and row['start'] > time.time()))
        self.remove.Enable(not self.busy and row is not None)
        self.clear.Enable(not self.busy and bool(self.rows))
        self.calendar.Enable(not self.busy and row is not None)

    def _refresh(self):
        old = self._selected() if hasattr(self, 'rows') else None
        self.rows = self.store.list()
        self.list.DeleteAllItems()
        selected = 0
        labels = {'scheduled': _("Scheduled"), 'ready': _("Pending"),
                  'notified': _("Notified"), 'expired': _("Expired")}
        for index, row in enumerate(self.rows):
            try:
                stamp = datetime.datetime.fromtimestamp(row['start']).strftime('%Y-%m-%d %H:%M')
            except (ValueError, OSError, OverflowError):
                stamp = _("Unknown time")
            self.list.InsertItem(index, stamp)
            self.list.SetItem(index, 1, row['title'] or _("(No title)"))
            self.list.SetItem(index, 2, row['channel'])
            state = 'expired' if row['end'] <= time.time() and row['status'] in {'scheduled', 'ready'} else row['status']
            if state == 'scheduled' and time.time() >= row.get('notify_at', row['start'] - row['lead'] * 60):
                state = 'ready'
            self.list.SetItem(index, 3, labels[state])
            self.list.SetItem(index, 4, str(row['lead']))
            if old and old['id'] == row['id']:
                selected = index
        if self.rows:
            self.list.Select(selected)
            self.list.Focus(selected)
            self.list.EnsureVisible(selected)
        self.status.SetLabel('' if self.rows else _("No reminders."))
        self._buttons()

    def _export_calendar(self, _event=None):
        row = self._selected()
        if row is None or self.busy:
            return
        from planning_tools_ui import export_file
        from planning_tools import programme_calendar
        export_file(self, _("Export to Calendar..."), _("Calendar file (*.ics)") + '|*.ics', '.ics',
                    lambda: programme_calendar(row['title'], row['channel'], row['start'], row['end'],
                                               identity=row['channel_key']))

    def _edit(self, event=None):
        row = self._selected()
        if row is None or row['start'] <= time.time():
            return
        lead = ask_minutes(self, row['lead'])
        if lead is not None:
            self._change(lambda: self.store.set_lead(row['id'], lead), rearm=row['id'])

    def _confirm(self, text):
        dialog = wx.MessageDialog(self, text, _("Programme Reminders"),
                                  wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        try:
            return show_modal(dialog) == wx.ID_YES
        finally:
            dialog.Destroy()

    def _delete(self, event=None):
        row = self._selected()
        if row and self._confirm(_("Remove this reminder?")):
            self._change(lambda: self.store.remove(row['id']))

    def _clear(self, event=None):
        if self.rows and self._confirm(_("Remove all reminders?")):
            self._change(self.store.remove)

    def _change(self, operation, *, rearm=None):
        if self.busy:
            return
        self.busy = True
        self._buttons()
        def done(_result, error):
            self.busy = False
            if error:
                message_box(_("The reminder operation failed:\n{error}").format(error=error),
                            _("Programme Reminders"), wx.OK | wx.ICON_ERROR,
                            parent=self.owner if self.closed else self)
            elif rearm:
                self.owner._reminder_seen.discard(rearm)
            if not self.closed:
                self._refresh()
                self.list.SetFocus()
        if not start_operation(self.owner, 'reminder-edit', operation, done, wx.CallAfter):
            self.busy = False
            self.status.SetLabel(_("In Progress"))
            self._buttons()

    def _key(self, event):
        if event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
            self._delete()
        else:
            event.Skip()


class PlanningMixin:
    def _ensure_reminders(self):
        if not hasattr(self, '_reminder_seen'):
            self._reminder_seen = set()
        store = getattr(self, '_reminder_store', None)
        if store is None:
            with _REMINDER_INIT_LOCK:
                store = getattr(self, '_reminder_store', None)
                if store is None:
                    path = os.path.join(os.path.dirname(get_dvr_schedule_path()), 'programme-reminders.json')
                    store = self._reminder_store = reminders.ReminderStore(path)
        return store

    def _start_reminders(self):
        self._reminder_generation = getattr(self, '_reminder_generation', 0) + 1
        self._reminders_stopped = False
        self._reminder_errors_after = 0
        self._reminder_error_reported = False
        self._reminder_seen = set()
        self._reminder_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._poll_reminders, self._reminder_timer)
        self._reminder_timer.Start(5000)
        wx.CallAfter(self._poll_reminders)

    def _stop_reminders(self):
        self._reminder_generation = getattr(self, '_reminder_generation', 0) + 1
        self._reminders_stopped = True
        timer = getattr(self, '_reminder_timer', None)
        if timer is not None:
            timer.Stop()

    def _reminder_modal_open(self):
        if self._modal_box_is_open():
            return True
        # Existing EPG/provider dialogs also run native modal loops; do not
        # place a reminder above one just because it is not a message box.
        windows = getattr(wx, 'GetTopLevelWindows', lambda: [])()
        for window in windows:
            modal = getattr(window, 'IsModal', None)
            if callable(modal) and modal():
                return True
        return False

    def _poll_reminders(self, event=None):
        if (getattr(self, '_reminders_stopped', False) or self._reminder_modal_open()
                or 'reminder-ack' in getattr(self, '_background_operations', ())
                or time.monotonic() < getattr(self, '_reminder_errors_after', 0)):
            return
        def work():
            store = self._ensure_reminders()
            return store.due(), store.list(), store.load_warning
        generation = getattr(self, '_reminder_generation', 0)
        def ready(result, error):
            if generation == getattr(self, '_reminder_generation', 0):
                self._reminders_ready(result, error)
        start_operation(self, 'reminder-poll', work, ready, wx.CallAfter)

    def _reminder_failed(self, error):
        self._reminder_errors_after = time.monotonic() + 60
        if not getattr(self, '_reminder_error_reported', False):
            self._reminder_error_reported = True
            self._show_or_queue_message_box(_("The reminder operation failed:\n{error}").format(error=error),
                                           _("Programme Reminders"), wx.OK | wx.ICON_ERROR)

    def _reminders_ready(self, result, error):
        if getattr(self, '_reminders_stopped', False):
            return
        if error:
            self._reminder_failed(error)
            return
        due, rows, warning = result
        self._reminder_error_reported = False
        if warning and not getattr(self, '_reminder_load_warning_shown', False):
            self._reminder_load_warning_shown = True
            self._show_or_queue_message_box(warning, _("Programme Reminders"), wx.OK | wx.ICON_WARNING)
        self._reminder_seen.intersection_update(r['id'] for r in rows)
        if self._reminder_modal_open() or 'reminder-ack' in getattr(self, '_background_operations', ()):
            return
        row = next((r for r in due if r['id'] not in self._reminder_seen and time.time() < r['end']), None)
        if row is None:
            return
        self._reminder_seen.add(row['id'])
        start = datetime.datetime.fromtimestamp(row['start']).strftime('%Y-%m-%d %H:%M')
        text = _("{title}\n{channel}\nStarts: {time}").format(
            title=row['title'] or _("(No title)"), channel=row['channel'], time=start)
        dialog = ReminderAlert(self, text, row, time.time())
        try:
            show_modal(dialog)
            action = dialog.action
        finally:
            dialog.Destroy()
        store = self._ensure_reminders()
        def commit():
            if action in {'snooze', 'start'}:
                store.snooze(row['id'], at_start=action == 'start')
            else:
                store.acknowledge(row['id'])
        def saved(_result, failure):
            if failure:
                self._reminder_failed(failure)
            elif action in {'snooze', 'start'}:
                self._reminder_seen.discard(row['id'])
            if action == 'play' and not self._reminders_stopped:
                channel = reminders.resolve_channel(row, self.all_channels)
                if channel is None:
                    message_box(_("Channel Not Found"), _("Programme Reminder"), wx.OK | wx.ICON_INFORMATION)
                else:
                    self._play_live_channel(channel)
        start_operation(self, 'reminder-ack', commit, saved, wx.CallAfter)

    def _confirm_reminder_exit(self):
        store = getattr(self, '_reminder_store', None)
        pending = [r for r in store.list() if r['status'] in {'scheduled', 'ready'}
                   and r['end'] > time.time()] if store else []
        if not pending:
            return True
        return message_box(_("Pending programme reminders: {count}.\n\nNotifications require the application "
                             "to remain running. Exit anyway?").format(count=len(pending)),
                           _("Programme Reminders"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING) == wx.YES

    def _set_programme_reminder(self, channel, program):
        try:
            reminders.build(channel, program)  # validate before opening a modal
        except (ValueError, TypeError, OverflowError, OSError):
            message_box(_("The programme has already started or its times are invalid."),
                        _("Programme Reminders"), wx.OK | wx.ICON_INFORMATION)
            return
        lead = ask_minutes(self, 5)
        if lead is None:
            return
        try:
            row = reminders.build(channel, program, lead)
        except Exception as error:
            self._reminder_failed(error)
            return
        def work():
            self._ensure_reminders().add(row)
        def done(_result, error):
            if error:
                self._reminder_failed(error)
            else:
                self._reminder_seen.discard(row['id'])
                message_box(_("Reminder set."), _("Programme Reminders"), wx.OK | wx.ICON_INFORMATION)
        start_operation(self, 'reminder-add', work, done, wx.CallAfter)

    def _set_epg_reminder(self, program):
        channel = self._find_channel_for_epg(program)
        if channel:
            self._set_programme_reminder(channel, program)
        else:
            message_box(_("Channel Not Found"), _("Programme Reminders"), wx.OK | wx.ICON_INFORMATION)

    def _show_reminders(self, event=None):
        if getattr(self, '_reminder_store', None) is None:
            def loaded(_result, error):
                if error:
                    self._reminder_failed(error)
                else:
                    self._show_reminders()
            start_operation(self, 'reminder-poll', self._ensure_reminders, loaded, wx.CallAfter)
            return
        try:
            dialog = RemindersDialog(self, self._ensure_reminders())
            try:
                show_modal(dialog)
            finally:
                dialog.Destroy()
            # Editing an already displayed future reminder explicitly re-arms
            # it. Only scheduled (not unacknowledged ready) entries reset seen.
            scheduled = {r['id'] for r in self._ensure_reminders().list() if r['status'] == 'scheduled'}
            self._reminder_seen.difference_update(scheduled)
        except Exception as error:
            message_box(_("The reminder operation failed:\n{error}").format(error=error),
                        _("Programme Reminders"), wx.OK | wx.ICON_ERROR)

    def _set_recording_reserve(self, event=None):
        old = recording_storage.normalize_reserve(self.config.get('recording_min_free_mib'))
        dialog = wx.NumberEntryDialog(
            self, _("Minimum free space to keep before starting a recording (MiB):"),
            _("MiB:"), _("Recording Storage"), old, 0, recording_storage.MAX_RESERVE_MIB)
        try:
            if show_modal(dialog) != wx.ID_OK:
                return
            value = dialog.GetValue()
        finally:
            dialog.Destroy()
        self.config['recording_min_free_mib'] = value
        self.recorder.storage_min_mib = value
        save_config(self.config)

    def _show_recording_storage(self, event=None):
        if getattr(self, '_storage_check_busy', False):
            return
        self._storage_check_busy = True
        directory = get_recordings_dir(self.config)
        reserve = recording_storage.normalize_reserve(self.config.get('recording_min_free_mib'))
        def worker():
            try:
                info = recording_storage.check_destination(directory, reserve)
                result = _("Recording folder: {path}\nFree space: {free} MiB\nRequired reserve: {reserve} MiB.\n\n"
                           "This check does not guarantee sufficient space for the entire recording.").format(
                               path=info['path'], free=info['free'] // recording_storage.MIB, reserve=reserve)
                failed = False
            except Exception as error:
                result, failed = str(error), True
            wx.CallAfter(self._storage_check_finished, result, failed)
        try:
            threading.Thread(target=worker, daemon=True).start()
        except RuntimeError:
            self._storage_check_busy = False
            raise

    def _storage_check_finished(self, result, failed):
        self._storage_check_busy = False
        if getattr(self, '_reminders_stopped', False):
            return
        self._show_or_queue_message_box(result, _("Recording Storage"),
                                       wx.OK | (wx.ICON_ERROR if failed else wx.ICON_INFORMATION))
