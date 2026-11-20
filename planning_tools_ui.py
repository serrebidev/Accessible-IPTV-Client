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
