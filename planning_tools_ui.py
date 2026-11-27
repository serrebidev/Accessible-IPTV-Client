"""Native, keyboard-accessible planning actions; file exports run on demand."""
import wx

from background_tasks import start_operation
from i18n import gettext as _
from modal_guard import message_box, show_modal
import planning_tools
import user_guide


def weekdays(parent, selected=()):
    dialog = wx.MultiChoiceDialog(parent, _("Choose repeat days. Clear all days to record only once."),
                                 _("Repeat on Weekdays..."), weekday_labels())
    dialog.SetSelections(list(selected))
    user_guide.set_help_topic(dialog, 'scheduled-recordings')
    try:
        return list(dialog.GetSelections()) if show_modal(dialog) == wx.ID_OK else None
    finally:
        dialog.Destroy()


def weekday_labels():
    return [_("Monday"), _("Tuesday"), _("Wednesday"), _("Thursday"), _("Friday"), _("Saturday"), _("Sunday")]


def export_file(parent, title, wildcard, extension, produce):
    if 'export' in getattr(parent, '_background_operations', ()):
        return
    with wx.FileDialog(parent, title, wildcard=wildcard, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
        if show_modal(dialog) != wx.ID_OK:
            return
        path = dialog.GetPath()
        if not path:
            return
        if not path.lower().endswith(extension):
            path += extension
            import os
            if os.path.exists(path) and message_box(_("Replace the existing export file?"), title,
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, parent=parent) != wx.YES:
                return
    def work():
        planning_tools.atomic_export(path, produce())
    def done(_result, error):
        message_box(_("The operation failed:\n{error}").format(error=error) if error else _("Export saved."),
                    title, wx.OK | (wx.ICON_ERROR if error else wx.ICON_INFORMATION), parent=parent)
    start_operation(parent, 'export', work, done, wx.CallAfter)


def export_recordings(parent, jobs):
    def content():
        selected = [parent.scheduler.get_job(job["id"]) for job in jobs]
        if selected != jobs:
            raise ValueError(_("The recording schedule changed. Check the times and try again."))
        return planning_tools.recording_calendar(selected)
    export_file(parent, _("Export Selected Recordings to Calendar..."),
                _("Calendar file (*.ics)") + '|*.ics', '.ics', content)


def pause_rule(parent, job):
    import datetime
    import wx.adv
    rule = parent.scheduler.get_job(job.get("series_source") or job["id"])
    if not rule:
        return
    title = _("Pause Recording Rule...")
    dialog = wx.Dialog(parent, title=title)
    user_guide.set_help_topic(dialog, "scheduled-recordings")
    layout = wx.BoxSizer(wx.VERTICAL)
    today = datetime.date.today().isoformat()
    saved = rule.get("pause_dates", (today, today))
    controls = []
    for label, day in zip((_("First day of the pause"), _("Last day of the pause")), saved):
        value = datetime.date.fromisoformat(day)
        layout.Add(wx.StaticText(dialog, label=label), 0, wx.ALL, 5)
        control = wx.adv.DatePickerCtrl(dialog, dt=wx.DateTime.FromDMY(value.day, value.month - 1, value.year))
        control.SetName(label)
        controls.append(control)
        layout.Add(control, 0, wx.EXPAND | wx.ALL, 5)
    clear = wx.CheckBox(dialog, label=_("Remove the pause"))
    clear.Enable(bool(rule.get("pause_dates")))
    layout.Add(clear, 0, wx.ALL, 5)
    layout.Add(dialog.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 5)
    dialog.SetSizerAndFit(layout)
    try:
        if show_modal(dialog) != wx.ID_OK:
            return
        period = None if clear.GetValue() else [c.GetValue().FormatISODate() for c in controls]
    finally:
        dialog.Destroy()
    def done(_result, error):
        if error:
            message_box(str(error), title, wx.OK | wx.ICON_ERROR, parent=parent)
        else:
            parent.refresh()

    def apply():
        start_operation(parent, "pause-rule", lambda: parent.scheduler.set_pause_period(rule, period), done, wx.CallAfter)
    if not period:
        apply()
        return
    import dvr
    if not dvr.valid_pause_period(period) or period[1] < today:
        message_box(_("Choose a valid pause ending today or later."), title, wx.OK | wx.ICON_INFORMATION, parent=parent)
        return

    def preview():
        bookings = parent.scheduler.list_jobs(include_done=False) if rule.get("repeat") == "series" else ()
        return planning_tools.pause_preview(rule, period, bookings)

    def confirm(times, error):
        if error:
            done(None, error)
            return
        message = _("Pause from {first} through {last}, inclusive?").format(first=period[0], last=period[1])
        skipped, following = times
        if skipped:
            message += "\n" + _("First skipped recording: {time}").format(time=skipped.strftime("%Y-%m-%d %H:%M"))
        if following:
            message += "\n" + _("Next recording after the pause: {time}").format(time=following.strftime("%Y-%m-%d %H:%M"))
        if message_box(message, title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent=parent) == wx.YES:
            apply()
    start_operation(parent, "preview-pause", preview, confirm, wx.CallAfter)


def reminder_choice(parent, rows):
    import datetime
    import dvr
    title = _("Review Guide Changes...")
    def window(a, b):
        return " – ".join(datetime.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M") for value in (a, b))
    labels = []
    for row, programme, exact in rows:
        times = [dvr.parse_epg_utc(programme[key]).timestamp() for key in ('start', 'end')]
        labels.append(_("{title}, {channel}. Previous: {old}. New: {new}.").format(
            title=row['title'], channel=row['channel'], old=window(row['start'], row['end']), new=window(*times))
            + " " + (_("Matching programme details.") if exact else _("Possible time change. Check the programme.")))
    choice = wx.SingleChoiceDialog(parent, _("Choose a time change to review:"), title, labels)
    user_guide.set_help_topic(choice, "channel-epg")
    try:
        if show_modal(choice) != wx.ID_OK or choice.GetSelection() < 0:
            return None
        i = choice.GetSelection()
    finally:
        choice.Destroy()
    if message_box(labels[i] + "\n\n" + _("Use the new time for this reminder?"), title,
                   wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent=parent) != wx.YES:
        return None
    row, programme, exact = rows[i]
    keep = False
    if 'notify_at' in row:
        answer = message_box(_("Keep the postponement relative to the new start time? Choose No to use the usual lead time."),
                             title, wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION, parent=parent)
        if answer not in (wx.YES, wx.NO):
            return None
        keep = answer == wx.YES
    return row, programme, exact, keep


def export_programme(parent, channel, program):
    import dvr
    import programme_reminders
    try:
        start = dvr.parse_epg_utc(program.get('start', '')).timestamp()
        end = dvr.parse_epg_utc(program.get('end', '')).timestamp()
        title = programme_reminders.safe_title(dvr.program_title(program))
        name = programme_reminders.safe_title(dvr.channel_name(channel or {}))
        if end <= start:
            raise ValueError(_("Invalid programme times."))
    except (ValueError, TypeError, OverflowError) as error:
        message_box(str(error), _("Export to Calendar..."), wx.OK | wx.ICON_ERROR, parent=parent)
        return
    identity = programme_reminders.channel_key(channel or {})
    export_file(parent, _("Export to Calendar..."), _("Calendar file (*.ics)") + '|*.ics', '.ics',
                lambda: planning_tools.programme_calendar(title, name, start, end, identity=identity))


class ReminderAlert(wx.Dialog):
    def __init__(self, parent, text, row, now):
        super().__init__(parent, title=_("Programme Reminder"))
        self.action = 'dismiss'
        layout = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(self, label=text)
        label.Wrap(600)
        layout.Add(label, 0, wx.ALL, 12)
        buttons = wx.WrapSizer(wx.HORIZONTAL)
        actions = [('play', _("Open Channel"))]
        if now + 300 < row['end']:
            actions.append(('snooze', _("Remind Again in 5 Minutes")))
        if now < row['start']:
            actions.append(('start', _("Remind at Programme Start")))
        for action, title in actions:
            button = wx.Button(self, label=title)
            button.Bind(wx.EVT_BUTTON, lambda event, choice=action: self.choose(choice))
            buttons.Add(button, 0, wx.ALL, 4)
        close = wx.Button(self, wx.ID_CANCEL, _("Close"))
        close.SetDefault()
        buttons.Add(close, 0, wx.ALL, 4)
        layout.Add(buttons, 0, wx.ALL, 8)
        self.SetSizerAndFit(layout)
        close.SetFocus()
        user_guide.set_help_topic(self, 'channel-epg')

    def choose(self, action):
        self.action = action
        self.EndModal(wx.ID_OK)
