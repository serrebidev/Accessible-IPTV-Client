"""Readable conflict details, with account analysis outside the GUI thread."""
import copy
import contextlib
import datetime
import math

import wx

from background_tasks import LatestTask
import dvr
import recording_limits
import user_guide
from i18n import gettext as _
from modal_guard import show_modal


def local_time(value):
    try:
        return datetime.datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S')
    except (OSError, OverflowError, ValueError):
        return _("Unknown time")


def snapshot_job(job):
    value = {key: job.get(key) for key in ('id', 'title', 'status', 'start_ts', 'stop_ts',
                                          'pre_padding_minutes', 'post_padding_minutes', 'pause_dates')}
    value['channel'] = dict(job.get('channel') or {})
    return value


class ConflictList(wx.ListCtrl):
    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_SINGLE_SEL)
        self.labels = []
        self.InsertColumn(0, _("Title"), width=740)

    def OnGetItemText(self, item, column):
        return self.labels[item] if 0 <= item < len(self.labels) else ''


def conflict_rows(config, channel, start, end, jobs, *, exclude=None, canceled=lambda: False):
    limits = recording_limits.normalize(config.get('recording_connection_limits'))
    key = recording_limits.channel_key(channel, config) if limits else ''
    limit = limits.get(key)
    rows, keys = [], {}
    for job in jobs:
        if canceled():
            return []
        if job.get('id') == exclude or job.get('status') not in {'scheduled', 'recording', 'stopping'}:
            continue
        if job.get('status') == 'scheduled' and dvr.paused_occurrence(job):
            continue
        a, b = job.get('start_ts'), job.get('stop_ts')
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (a, b)) or not a < end or not b > start:
            continue
        snapshot = job.get('channel') or {}
        identity = (str(snapshot.get('provider-id', '')), str(snapshot.get('playlist-id', '')),
                    str(snapshot.get('url', '')))
        if limit and identity not in keys:
            keys[identity] = recording_limits.channel_key(snapshot, config)
        if limit and keys[identity] != key:
            continue
        # Display provider aliases only; never account URLs, usernames or keys.
        provider = snapshot.get('provider-id') or snapshot.get('playlist-id')
        name = next((str(source.get('name') or '') for source in config.get('playlists', [])
                     if isinstance(source, dict) and provider and source.get('id') == provider), '')
        rows.append(dict(job=snapshot_job(job), account=name, start=a, end=b))
    return sorted(rows, key=lambda row: (row['start'], str(row['job'].get('id'))))


class RecordingConflictsDialog(wx.Dialog):
    def __init__(self, owner, channel, start, end, *, exclude=None, question='', allow_schedule=False, proposal=None):
        super().__init__(owner, title=_("Recording Conflicts"), size=(820, 540),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.owner, self.channel, self.start, self.end = owner, copy.deepcopy(channel), start, end
        self.exclude = exclude
        self.proposal = proposal
        self.rows = []
        self.closed = False
        self.worker = LatestTask(wx.CallAfter)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.intro = wx.StaticText(self, label=question or _("Overlapping recordings, including schedule padding."))
        self.intro.Wrap(760)
        layout.Add(self.intro, 0, wx.ALL | wx.EXPAND, 10)
        self.list = ConflictList(self)
        self.list.SetName(_("Overlapping Recordings"))
        layout.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)
        self.details = wx.TextCtrl(self, style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.details.SetName(_("Details"))
        layout.Add(self.details, 1, wx.EXPAND | wx.ALL, 10)
        self.status = wx.StaticText(self, label=_("Checking recording conflicts..."))
        layout.Add(self.status, 0, wx.ALL, 10)
        buttons = wx.WrapSizer(wx.HORIZONTAL)
        self.edit = wx.Button(self, label=_("Edit Times..."))
        self.edit.Disable()
        buttons.Add(self.edit, 0, wx.ALL, 5)
        self.alternative = wx.Button(self, label=_("Find Another Airing..."))
        buttons.Add(self.alternative, 0, wx.ALL, 5)
        self.alternative.Bind(wx.EVT_BUTTON, self.find_airing)
        self.accept = None
        if allow_schedule:
            self.accept = wx.Button(self, wx.ID_OK, label=_("Schedule Anyway"))
            self.accept.Disable()
            buttons.Add(self.accept, 0, wx.ALL, 5)
        cancel = wx.Button(self, wx.ID_CANCEL, label=_("Cancel") if allow_schedule else _("Close"))
        cancel.SetDefault()
        buttons.Add(cancel, 0, wx.ALL, 5)
        layout.Add(buttons, 0, wx.ALIGN_RIGHT)
        self.SetSizer(layout)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.select)
        self.edit.Bind(wx.EVT_BUTTON, self.edit_selected)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.destroying)
        user_guide.set_help_topic(self, 'scheduled-recordings')
        self.refresh()

    def destroying(self, event):
        if event.GetEventObject() is self:
            self.closed = True
            self.worker.close()
        event.Skip()

    def find_airing(self, _event):
        from recording_edits_ui import find_airing
        identity = self.exclude
        if not identity and not self.proposal:
            index = self.list.GetFirstSelected()
            if 0 <= index < len(self.rows):
                identity = self.rows[index]['job']['id']
        job = self.proposal or self.owner._ensure_dvr_scheduler().get_job(identity)
        if job and job.get('status') == dvr.STATUS_SCHEDULED:
            done = (lambda: self.EndModal(wx.ID_CANCEL)) if self.proposal or self.exclude else self.refresh
            find_airing(self, self.owner, job, done, new=bool(self.proposal))

    def refresh(self):
        config = copy.deepcopy(self.owner.config)
        scheduler = self.owner._ensure_dvr_scheduler()
        with getattr(scheduler, '_lock', contextlib.nullcontext()):
            jobs = [snapshot_job(job) for job in scheduler.list_jobs(include_done=False)]
        if self.accept:
            self.accept.Disable()
        self.edit.Disable()
        self.status.SetLabel(_("Checking recording conflicts..."))
        def work(canceled):
            rows = conflict_rows(config, self.channel, self.start, self.end, jobs,
                                 exclude=self.exclude, canceled=canceled)
            labels = [str(row['job'].get('title') or _("(No title)")) + ' — ' + local_time(row['start'])
                      for row in rows]
            warning = recording_limits.warning(config, self.channel, self.start, self.end, jobs,
                                               exclude=self.exclude)
            return rows, labels, warning
        def completed(result, error):
            if error:
                self.status.SetLabel(_("The operation failed:\n{error}").format(error=error))
                return
            self.list.SetItemCount(0)
            self.rows, self.list.labels, warning = result
            self.list.SetItemCount(len(self.rows))
            if self.accept:
                self.intro.SetLabel(warning or _("Overlapping recordings, including schedule padding."))
                self.intro.Wrap(760)
            if self.rows:
                self.list.Select(0)
                self.list.Focus(0)
            self.list.Refresh()
            self.status.SetLabel(_("Overlapping recordings: {count}.").format(count=len(self.rows)))
            if self.accept:
                self.accept.Enable()
            self.select()
        try:
            self.worker.submit(work, completed)
        except RuntimeError as error:
            completed(None, error)

    def select(self, _event=None):
        index = self.list.GetFirstSelected()
        valid = 0 <= index < len(self.rows)
        self.edit.Enable(valid and self.rows[index]['job'].get('status') in {'scheduled', 'recording'})
        self.alternative.Enable(bool(self.proposal or self.exclude or
                                     (valid and self.rows[index]['job'].get('status') == dvr.STATUS_SCHEDULED)))
        if not valid:
            self.details.ChangeValue('')
            return
        row = self.rows[index]
        job = row['job']
        lines = [str(job.get('title') or _("(No title)")), dvr.channel_name(job.get('channel') or {}),
                 _("Account") + ': ' + (row['account'] or _("Unknown")),
                 _("Start (local time, YYYY-MM-DD HH:MM)") + ': ' + local_time(row['start']),
                 _("End (local time, YYYY-MM-DD HH:MM)") + ': ' + local_time(row['end']),
                 _("Minutes before programme:") + ' ' + str(job.get('pre_padding_minutes', 0)),
                 _("Minutes after programme:") + ' ' + str(job.get('post_padding_minutes', 0))]
        self.details.ChangeValue('\n'.join(lines))

    def edit_selected(self, _event):
        index = self.list.GetFirstSelected()
        if not 0 <= index < len(self.rows):
            return
        identity = str(self.rows[index]['job'].get('id'))
        current = self.owner._ensure_dvr_scheduler().get_job(identity)
        if current and current.get('status') in {'scheduled', 'recording'}:
            self.owner._schedule_by_time(job=current)
        self.refresh()


def confirm_conflicts(owner, channel, start, end, warning, *, exclude=None, proposal=None):
    dialog = RecordingConflictsDialog(owner, channel, start, end, exclude=exclude,
                                      question=warning, allow_schedule=True, proposal=proposal)
    try:
        return show_modal(dialog) == wx.ID_OK
    finally:
        dialog.Destroy()


def show_conflicts(owner, job):
    dialog = RecordingConflictsDialog(owner, job['channel'], job['start_ts'], job['stop_ts'], exclude=job['id'])
    try:
        show_modal(dialog)
    finally:
        dialog.Destroy()
