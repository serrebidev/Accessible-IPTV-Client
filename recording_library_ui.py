"""Virtual recording inventory; disk, filtering and file actions run on workers."""
import os
import threading

import wx

from background_tasks import LatestTask
import planning_tools
from i18n import gettext as _
from media_navigation import clock_text
from modal_guard import message_box, show_modal
import options
import recording_library as library
import user_guide


def error_box(parent, error):
    from accessible_tools_ui import error_box as show_error
    show_error(parent, error)


class RecordingList(wx.ListCtrl):
    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_VIRTUAL)
        self.cells = []

    def OnGetItemText(self, item, column):
        return self.cells[item][column] if 0 <= item < len(self.cells) else ''


class RecordingLibraryDialog(wx.Dialog):
    def __init__(self, parent):
        from accessible_tools_ui import labeled
        super().__init__(parent, title=_("Recording Library"), size=(960, 620),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.owner = parent
        self.directory = options.get_recordings_dir(parent.config)
        self.closed = self.busy = self.filter_busy = False
        self.all_rows, self.rows = [], []
        self.warnings = []
        self.worker = LatestTask(wx.CallAfter)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.search = labeled(self, layout, _("Search recordings:"), wx.TextCtrl(self))
        self.directories = library.folders(parent.config)
        self.folder = labeled(self, layout, _("Recording folder:"), wx.Choice(
            self, choices=self.directories + [_("All Recording Folders")]))
        self.folder.SetSelection(0)
        self.folder.Bind(wx.EVT_CHOICE, self.change_folder)
        folder_buttons = wx.WrapSizer(wx.HORIZONTAL)
        self.add_folder = wx.Button(self, label=_("Add Folder..."))
        self.forget_folder = wx.Button(self, label=_("Remove Folder from Library"))
        for button in (self.add_folder, self.forget_folder):
            folder_buttons.Add(button, 0, wx.ALL, 5)
        self.add_folder.Bind(wx.EVT_BUTTON, self.choose_folder)
        self.forget_folder.Bind(wx.EVT_BUTTON, self.remove_folder)
        layout.Add(folder_buttons, 0, wx.EXPAND)
        self.deleted = wx.CheckBox(self, label=_("Show Deleted Recordings"))
        self.deleted.Bind(wx.EVT_CHECKBOX, self.refresh)
        layout.Add(self.deleted, 0, wx.ALL, 8)
        self.status_values = ['', 'completed', 'partial', 'stopped', 'failed', 'unknown']
        self.state = labeled(self, layout, _("Status"), wx.Choice(self, choices=[
            _("All Recordings"), _("Completed"), _("Partial"), _("Stopped by user"), _("Failed"), _("Unknown")]))
        self.state.SetSelection(0)
        self.sort_values = ['date', 'title', 'duration', 'size']
        self.sort = labeled(self, layout, _("Sort by"), wx.Choice(self, choices=[
            _("Date"), _("Title"), _("Duration"), _("File Size")]))
        self.sort.SetSelection(0)
        self.descending = wx.CheckBox(self, label=_("Descending"))
        view = planning_tools.library_view(parent.config.get('recording_library_view'), self.directories)
        selected = len(self.directories) if view['folder'] == '*' else self.directories.index(view['folder'])
        self.folder.SetSelection(selected)
        if selected < len(self.directories):
            self.directory = self.directories[selected]
        self.search.ChangeValue(view['query'])
        self.state.SetSelection(self.status_values.index(view['status']))
        self.sort.SetSelection(self.sort_values.index(view['sort']))
        self.descending.SetValue(view['descending'])
        layout.Add(self.descending, 0, wx.ALL, 5)
        self.list = RecordingList(self)
        self.list.SetName(_("Recordings"))
        for number, label in enumerate((_("Title"), _("Channel"), _("Date"), _("Duration"),
                                         _("Status"), _("File Size"), _("Recording folder:"))):
            self.list.InsertColumn(number, label, width=220 if number in (0, 6) else 125)
        layout.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        self.status = wx.StaticText(self, label='')
        layout.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        buttons = wx.WrapSizer(wx.HORIZONTAL)
        self.play = wx.Button(self, label=_("Play / Resume"))
        self.problems = wx.Button(self, label=_("Recording Problem Times") + "...")
        self.problems.Bind(wx.EVT_BUTTON, self.show_problems)
        self.rename = wx.Button(self, label=_("Rename Title..."))
        self.remove = wx.Button(self, label=_("Move to Recording Trash..."))
        self.restore = wx.Button(self, label=_("Restore Recording"))
        self.reload = wx.Button(self, label=_("Refresh"))
        self.export = wx.Button(self, label=_("Export List to CSV..."))
        self.export.Bind(wx.EVT_BUTTON, self.export_csv)
        close = wx.Button(self, wx.ID_CLOSE, label=_("Close"))
        for button in (self.play, self.problems, self.rename, self.remove, self.restore, self.reload, self.export, close):
            buttons.Add(button, 0, wx.ALL, 5)
        layout.Add(buttons, 0, wx.ALIGN_RIGHT)
        self.SetSizer(layout)
        for control, event in ((self.search, wx.EVT_TEXT), (self.state, wx.EVT_CHOICE),
                                (self.sort, wx.EVT_CHOICE), (self.descending, wx.EVT_CHECKBOX)):
            control.Bind(event, self.filter)
        self.play.Bind(wx.EVT_BUTTON, self.play_selected)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.play_selected)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.selection_changed)
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.selection_changed)
        self.list.Bind(wx.EVT_KEY_DOWN, self.list_key)
        self.remove.Bind(wx.EVT_BUTTON, self.delete_selected)
        self.rename.Bind(wx.EVT_BUTTON, self.rename_selected)
        self.restore.Bind(wx.EVT_BUTTON, self.restore_selected)
        self.reload.Bind(wx.EVT_BUTTON, self.refresh)
        close.Bind(wx.EVT_BUTTON, self.close)
        self.Bind(wx.EVT_CLOSE, self.close)
        self.Bind(wx.EVT_CHAR_HOOK, self.key)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.destroying)
        user_guide.set_help_topic(self, 'recordings')
        self.refresh()

    def destroying(self, event):
        if event.GetEventObject() is self:
            self.closed = True
            self.worker.close()
        event.Skip()

    def key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.close()
        else:
            event.Skip()

    def list_key(self, event):
        if event.ControlDown() and event.GetKeyCode() in (ord('A'), ord('a')):
            self.list.SetItemState(-1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
            self.selection_changed()
        elif event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
            self.delete_selected(event)
        else:
            event.Skip()

    def close(self, _event=None):
        if self.closed:
            return
        selected = self.folder.GetSelection()
        view = {'folder': '*' if selected == len(self.directories) else self.directory,
                'query': self.search.GetValue(), 'status': self.status_values[max(0, self.state.GetSelection())],
                'sort': self.sort_values[max(0, self.sort.GetSelection())], 'descending': self.descending.GetValue()}
        owner = self.owner
        previous = owner.config.get('recording_library_view')
        owner.config['recording_library_view'] = view
        writer = getattr(owner, '_library_view_writer', None)
        if writer is None:
            writer = owner._library_view_writer = LatestTask(wx.CallAfter)
        def save(canceled):
            with options._SAVE_LOCK:
                if canceled():
                    return
                config = options.load_config()
                config['recording_library_view'] = view
                if options.save_config(config) is False:
                    raise OSError(_("Could not save recording library preferences."))
        def saved(_result, error):
            if error and bool(owner):
                if owner.config.get('recording_library_view') == view:
                    if previous is None:
                        owner.config.pop('recording_library_view', None)
                    else:
                        owner.config['recording_library_view'] = previous
                error_box(owner, error)
        try:
            writer.submit(save, saved)
        except RuntimeError as error:
            saved(None, error)
        self.closed = True
        self.worker.close()
        self.owner._recording_library_dialog = None
        self.Destroy()

    def active_paths(self):
        paths = [rec.written_path for rec in self.owner.recorder.list_active()]
        playing = (getattr(self.owner, '_internal_player_channel', None) or {}).get('local-recording')
        if playing:
            paths.append(playing)
        return paths

    def controls(self):
        return (self.play, self.problems, self.remove, self.rename, self.restore, self.reload,
                self.folder, self.deleted, self.add_folder, self.forget_folder, self.export)

    def change_folder(self, _event):
        if not self.busy and 0 <= self.folder.GetSelection() < len(self.directories):
            self.directory = self.directories[self.folder.GetSelection()]
        self.refresh()

    def choose_folder(self, _event):
        dialog = wx.DirDialog(self, _("Choose a recording folder"), defaultPath=self.directory,
                              style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
        try:
            if show_modal(dialog) == wx.ID_OK:
                path = os.path.abspath(dialog.GetPath())
                if path not in self.directories and len(self.directories) >= 20:
                    raise ValueError(_("The library can contain up to 20 folders."))
                self.owner._save_tool_setting('recording_library_folders', lambda old:
                    list(dict.fromkeys(self.directories[1:] + [path])))
                self.directories = library.folders(self.owner.config)
                self.folder.Set(self.directories + [_("All Recording Folders")])
                self.folder.SetSelection(self.directories.index(path) if path in self.directories else 0)
                self.change_folder(None)
        except Exception as error:
            error_box(self, error)
        finally:
            dialog.Destroy()

    def remove_folder(self, _event):
        selected = self.folder.GetSelection()
        if self.busy or not 0 < selected < len(self.directories):
            return
        try:
            self.owner._save_tool_setting('recording_library_folders', lambda old:
                [path for path in self.directories[1:] if path != self.directory])
            self.directories = library.folders(self.owner.config)
            self.folder.Set(self.directories + [_("All Recording Folders")])
            self.folder.SetSelection(0)
            self.change_folder(None)
        except Exception as error:
            error_box(self, error)

    def refresh(self, _event=None):
        if self.busy:
            return
        self.busy = True
        for button in self.controls():
            button.Disable()
        active, deleted = self.active_paths(), self.deleted.GetValue()
        directories = list(self.directories) if self.folder.GetSelection() == len(self.directories) else [self.directory]
        self.status.SetLabel(_("Loading recordings..."))
        def work(canceled):
            rows, warnings = [], []
            seen = set()
            for directory in directories:
                if canceled():
                    break
                try:
                    items = library.scan_trash(directory, canceled=canceled, warnings=warnings) if deleted else library.scan(
                        directory, active, canceled=canceled, warnings=warnings)
                    for row in items:
                        identity = os.path.normcase(os.path.realpath(row['path']))
                        if identity not in seen:
                            seen.add(identity)
                            rows.append(row)
                except OSError as error:
                    warnings.append(str(error))
            return rows, warnings
        def done(value, error):
            if error:
                self.loaded([], str(error))
            else:
                self.warnings = value[1]
                self.loaded(value[0], '')
        try:
            self.worker.submit(work, done)
        except RuntimeError as error:
            self.loaded([], str(error))

    def loaded(self, rows, error):
        if self.closed:
            return
        self.busy = False
        for button in self.controls():
            button.Enable()
        self.all_rows = rows
        self.filter()
        if error:
            error_box(self, error)

    def selected_rows(self):
        rows, index = [], self.list.GetFirstSelected()
        while index != -1:
            if index < len(self.rows):
                rows.append(self.rows[index])
            index = self.list.GetNextSelected(index)
        return rows

    def selected(self):
        rows = self.selected_rows()
        return rows[0] if len(rows) == 1 else None

    def filter(self, _event=None):
        if self.closed or self.busy:
            return
        selected = {row['path'] for row in self.selected_rows()}
        query = self.search.GetValue()
        state = self.status_values[max(0, self.state.GetSelection())]
        order = self.sort_values[max(0, self.sort.GetSelection())]
        descending = self.descending.GetValue()
        rows = self.all_rows
        self.filter_busy = True
        self.selection_changed()
        def work(canceled):
            result = library.query_rows(rows, query, state, order, descending)
            statuses = {'completed': _("Completed"), 'partial': _("Partial"), 'stopped': _("Stopped by user"),
                        'failed': _("Failed"), 'unknown': _("Unknown")}
            cells = []
            for row in result:
                if canceled():
                    return [], []
                duration = row.get('duration')
                cells.append((row['title'], row['channel'], row['date'],
                              clock_text(int(duration) * 1000) if duration is not None else _("Unknown"),
                              statuses.get(row['status'], _("Unknown")),
                              f"{row.get('size', 0) / 1048576:.2f} MiB", row.get('directory', '')))
            return result, cells
        def done(value, error):
            self.filter_busy = False
            if error:
                error_box(self, error)
                self.selection_changed()
                return
            self.list.Freeze()
            try:
                self.list.SetItemCount(0)
                self.rows, self.list.cells = value
                self.list.SetItemCount(len(self.rows))
                for index, row in enumerate(self.rows):
                    if row['path'] in selected:
                        self.list.Select(index)
                if self.rows and self.list.GetFirstSelected() == -1:
                    self.list.Select(0)
                    self.list.Focus(0)
                self.list.Refresh()
            finally:
                self.list.Thaw()
            self.selection_changed()
        try:
            self.worker.submit(work, done)
        except RuntimeError as error:
            done(None, error)

    def selection_changed(self, _event=None):
        if self.closed:
            return
        if _event is not None:
            if not getattr(self, '_selection_pending', False):
                self._selection_pending = True
                def update():
                    self._selection_pending = False
                    self.selection_changed()
                wx.CallAfter(update)
            return
        rows = self.selected_rows()
        ready = not self.busy and not self.filter_busy
        deleted = self.deleted.GetValue()
        self.play.Enable(ready and len(rows) == 1 and not deleted)
        self.problems.Enable(ready and len(rows) == 1 and not deleted)
        self.rename.Enable(ready and len(rows) == 1 and not deleted)
        self.restore.Enable(ready and bool(rows) and deleted)
        self.remove.Enable(ready and bool(rows))
        self.export.Enable(ready and bool(self.rows))
        label = _("Delete Recording File...") if deleted else _("Move to Recording Trash...")
        self.remove.SetLabel(label)
        self.remove.SetName(label)
        self.forget_folder.Enable(ready and 0 < self.folder.GetSelection() < len(self.directories))
        size = sum(row.get('size', 0) for row in rows)
        text = _("{count} recording(s). Active recordings are not listed.").format(count=len(self.rows))
        text += ' ' + _("Selected: {count}; total size: {size} MiB.").format(count=len(rows), size=f'{size / 1048576:.2f}')
        if self.warnings:
            text += '\n' + '\n'.join(dict.fromkeys(self.warnings))
        self.status.SetLabel(text)

    def export_csv(self, _event=None):
        if self.busy or self.filter_busy or not self.rows:
            return
        from planning_tools_ui import export_file
        rows = tuple(self.rows)
        export_file(self, _("Export List to CSV..."), _("CSV file (*.csv)") + '|*.csv', '.csv',
                    lambda: planning_tools.recording_csv(rows))

    def play_selected(self, _event):
        row = self.selected()
        if row is None or self.busy or self.filter_busy or self.deleted.GetValue():
            return
        directory = row.get('directory', self.directory)
        active = self.active_paths()
        self.run_operation(lambda: library.playback_channel(directory, row, active), play=True)

    def show_problems(self, _event):
        from background_tasks import start_operation
        from recorder import recording_problem_times
        row = self.selected()
        if row is None or self.busy or self.filter_busy or self.deleted.GetValue():
            return
        directory, active = row["directory"], self.active_paths()
        def read():
            return recording_problem_times(library.problem_log(directory, row, active))
        def ready(problems, error):
            if error:
                error_box(self, error)
                return
            position = self.owner._choose_recording_position(self, row["title"], problems)
            if position is None:
                return
            current_active = self.active_paths()
            def validate():
                return library.playback_channel(directory, row, current_active)
            def play(channel, error):
                if error:
                    error_box(self, error)
                else:
                    self.owner._launch_stream(channel["url"], channel["name"], stream_kind="vod", channel=channel,
                                              show_internal_player=True, force_internal=True, initial_position_ms=position)
            start_operation(self, "play-recording-position", validate, play, wx.CallAfter)
        start_operation(self, "read-recording-problems", read, ready, wx.CallAfter)

    def delete_selected(self, _event):
        rows = self.selected_rows()
        if not rows or self.busy or self.filter_busy:
            return
        permanent = self.deleted.GetValue()
        question = (_("Permanently delete {count} selected recording files? This cannot be undone.") if permanent else
                    _("Move {count} selected recordings to the recording trash?"))
        if message_box(question.format(count=len(rows)), _("Delete Recording"),
                       wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, parent=self) != wx.YES:
            return
        active = self.active_paths()
        def operation():
            errors = []
            for row in rows:
                try:
                    directory = row.get('directory', self.directory)
                    if permanent:
                        library.delete_trashed(directory, row)
                    else:
                        library.trash(directory, row, active)
                except Exception as error:
                    errors.append(row['title'] + ': ' + str(error))
            if errors:
                raise OSError('\n'.join(errors))
        self.run_operation(operation)

    def run_operation(self, operation, *, play=False):
        if self.busy or self.filter_busy:
            return
        self.busy = True
        self.status.SetLabel(_("Processing recordings..."))
        for control in self.controls():
            control.Disable()
        def worker():
            result, error = None, None
            try:
                result = operation()
            except Exception as exc:
                error = exc
            wx.CallAfter(self.operation_done, error, result, play)
        try:
            threading.Thread(target=worker, daemon=True, name='RecordingFileAction').start()
        except RuntimeError as error:
            self.operation_done(error)

    def operation_done(self, error, result=None, play=False):
        if self.closed:
            return
        self.busy = False
        if error:
            error_box(self, error)
        elif play and result:
            try:
                self.owner._launch_stream(result['url'], result['name'], stream_kind='vod', channel=result,
                                          show_internal_player=True, force_internal=True)
            except Exception as exc:
                error_box(self, exc)
        self.refresh()

    def rename_selected(self, _event):
        row = self.selected()
        if row is None or self.busy or self.filter_busy or self.deleted.GetValue():
            return
        dialog = wx.TextEntryDialog(self, _("Recording title:"), _("Rename Title..."), row['title'])
        try:
            if show_modal(dialog) == wx.ID_OK:
                title = dialog.GetValue()
                directory = row.get('directory', self.directory)
                active = self.active_paths()
                self.run_operation(lambda: library.rename_title(directory, row, title, active))
        finally:
            dialog.Destroy()

    def restore_selected(self, _event):
        rows = self.selected_rows()
        if rows and not self.busy and not self.filter_busy and self.deleted.GetValue():
            def operation():
                errors = []
                for row in rows:
                    try:
                        library.restore(row.get('directory', self.directory), row)
                    except Exception as error:
                        errors.append(row['title'] + ': ' + str(error))
                if errors:
                    raise OSError('\n'.join(errors))
            self.run_operation(operation)
