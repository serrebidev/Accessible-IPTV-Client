"""Playback queues for local recordings. File validation is deferred until each hand-off."""

import os
from pathlib import Path

from background_tasks import LatestTask
from i18n import gettext as _
import recording_library


MAX_SAVED_QUEUES = 30
MAX_QUEUE_ENTRIES = 500


def saved_queues(value):
    result = {}
    if not isinstance(value, dict):
        return result
    used_names = set()
    for name, entries in value.items():
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
                or not name.isprintable() or not isinstance(entries, list)):
            continue
        name = name.strip()
        if name.casefold() in used_names:
            continue
        rows = []
        for entry in entries[:MAX_QUEUE_ENTRIES]:
            if not isinstance(entry, dict):
                continue
            path, directory, title = (entry.get(k) for k in ("path", "directory", "title"))
            size, modified = (entry.get(k) for k in ("size", "modified_ns"))
            if (not all(isinstance(v, str) and v and "\0" not in v for v in (path, directory, title))
                    or not Path(path).is_absolute() or not Path(directory).is_absolute()
                    or Path(path).parent != Path(directory) or type(size) is not int or size < 0
                    or type(modified) is not int):
                continue
            rows.append(dict(path=path, directory=directory, title=title, size=size, modified_ns=modified))
        if rows:
            result[name] = rows
            used_names.add(name.casefold())
        if len(result) >= MAX_SAVED_QUEUES:
            break
    return result


def save_named(value, name, rows, *, replace=False):
    entries = saved_queues({name: rows})
    if not entries:
        raise ValueError(_("Enter a queue name of 1 to 80 characters and include a recording."))
    count = len(rows)
    name, rows = next(iter(entries.items()))
    queues = saved_queues(value)
    existing = next((key for key in queues if key.casefold() == name.casefold()), None)
    if existing is not None:
        if not replace:
            raise ValueError(_("A saved queue with this name already exists."))
        del queues[existing]
    elif len(queues) >= MAX_SAVED_QUEUES:
        raise ValueError(_("The saved queue limit has been reached."))
    if len(rows) != count:
        raise ValueError(_("The queue could not be saved."))
    queues[name] = rows
    return queues


class RecordingQueue:
    def __init__(self, owner, dispatch):
        self.owner = owner
        self.dispatch = dispatch
        self.pending = []
        self.playing = False
        self.loading = False
        self.worker = None
        self.opening = None
        self.ticket = None
        self.changed = None

    def notify(self):
        if self.changed:
            self.changed()

    def add(self, rows):
        known = {os.path.normcase(row["path"]) for row in self.pending}
        for row in rows:
            key = os.path.normcase(row["path"])
            if key not in known:
                self.pending.append(dict(row))
                known.add(key)
        self.notify()

    def edit(self, index, delta=None):
        if not 0 <= index < len(self.pending):
            return index
        first = self.pending[0]
        if delta is None:
            self.pending.pop(index)
        elif delta in (-1, 1) and 0 <= index + delta < len(self.pending):
            self.pending[index], self.pending[index + delta] = self.pending[index + delta], self.pending[index]
            index += delta
        else:
            return index
        if (self.loading or self.opening is not None) and (not self.pending or self.pending[0] is not first):
            self.start(focus=False)  # discard validation of the replaced item, keeping focus in the editor
        self.notify()
        return min(index, len(self.pending) - 1)

    def stop(self):
        self.ticket = None
        self.playing = self.loading = False
        self.opening = None
        if self.worker is not None:
            self.worker.close()
            self.worker = None
        self.notify()

    def start(self, *, focus=True):
        self.stop()
        if self.pending:
            self.playing = True
            self.ticket = object()
            frame = getattr(self.owner, "_internal_player_frame", None)
            if frame is not None:
                frame._recording_queue = self
            self.next(focus=focus)

    def next(self, *, focus=False):
        if not self.pending or getattr(self.owner, "_exit_requested", False):
            self.stop()
            return
        self.loading = True
        row, ticket = self.pending[0], self.ticket
        active = [rec.written_path for rec in self.owner.recorder.list_active()]
        worker = self.worker = LatestTask(self.dispatch)

        def resolve(canceled):
            if not canceled():
                return recording_library.playback_channel(row["directory"], row, active)

        def ready(channel, error):
            worker.close()
            if ticket is not self.ticket or getattr(self.owner, "_exit_requested", False):
                return
            self.worker = None
            self.loading = False
            if error is None:
                try:
                    player = getattr(self.owner, "_internal_player_frame", None)
                    visible = focus or player is None or player.IsShown()
                    started = self.owner._launch_stream(
                        channel["url"],
                        channel["name"],
                        stream_kind="vod",
                        channel=channel,
                        show_internal_player=visible,
                        focus_player=focus,
                        force_internal=True,
                        initial_position_ms=0,
                        _queue_ticket=ticket,
                    )
                except Exception as exc:
                    error = exc
                else:
                    if not started:
                        self.stop()
                        return
            if error is not None:
                import wx

                self.stop()
                self.owner._show_or_queue_message_box(
                    _("Playback queue stopped at {title}. {reason}").format(title=row["title"], reason=error),
                    _("Recording Playback Queue"),
                    wx.OK | wx.ICON_INFORMATION,
                )
                return
            if self.ticket is ticket:
                self.opening = row
                self.notify()

        try:
            worker.submit(resolve, ready)
        except RuntimeError as error:
            ready(None, error)
        self.notify()

    def started(self, frame, generation, ticket):
        row = self.opening
        if (row is not None and self.ticket is ticket and frame._vlc_generation == generation
                and self.pending and self.pending[0] is row):
            self.pending.pop(0)
            self.opening = None
            self.notify()

    def ended(self, frame, generation, ticket):
        if (
            ticket is not None
            and self.ticket is ticket
            and self.playing
            and not self.loading
            and frame._vlc_generation == generation
            and not frame._destroyed
            and not frame._manual_stop
        ):
            self.started(frame, generation, ticket)
            self.next()


def get_queue(owner):
    import wx

    queue = getattr(owner, "_recording_queue", None)
    if queue is None:
        queue = owner._recording_queue = RecordingQueue(owner, wx.CallAfter)
    return queue


def show_editor(parent, queue):
    import wx
    from modal_guard import message_box, show_modal
    from personal_tools_ui import ToolDialog
    import user_guide

    dialog = ToolDialog(parent, _("Recording Playback Queue"))
    user_guide.set_help_topic(dialog, "recordings")
    listing = dialog.listbox(_("Upcoming recordings"))
    controls = wx.WrapSizer(wx.HORIZONTAL)
    dialog.layout.Add(controls, 0, wx.EXPAND | wx.ALL, 4)

    def refresh(preferred=None):
        index = listing.GetSelection() if preferred is None else preferred
        count = len(queue.pending)
        listing.Set(
            [
                _("{position} of {count}: {title}").format(position=i, count=count, title=row["title"])
                for i, row in enumerate(queue.pending, 1)
            ]
        )
        if count:
            listing.SetSelection(max(0, min(index, count - 1)))
        index = listing.GetSelection()
        up.Enable(index > 0)
        down.Enable(0 <= index < count - 1)
        remove.Enable(index >= 0)
        play.Enable(bool(count) and not queue.playing)
        halt.Enable(queue.playing)
        saved = saved_queues(getattr(queue.owner, "config", {}).get("saved_recording_queues"))
        save.Enable(bool(count) and not queue.playing and hasattr(queue.owner, "_save_tool_setting"))
        load.Enable(bool(saved) and not queue.playing)
        delete.Enable(bool(saved) and not queue.playing)

    def manage(mode):
        key = "saved_recording_queues"
        queues = saved_queues(getattr(queue.owner, "config", {}).get(key))
        title = _("Saved Playback Queues")
        try:
            if mode == "save":
                with wx.TextEntryDialog(dialog, _("Name for this queue:"), title) as choice:
                    if show_modal(choice) != wx.ID_OK:
                        return
                    name = choice.GetValue().strip()
                replace = any(n.casefold() == name.casefold() for n in queues)
                if replace and message_box(_("Replace the saved queue with this name?"), title,
                        wx.YES_NO | wx.NO_DEFAULT, parent=dialog) != wx.YES:
                    return
                queue.owner._save_tool_setting(key, lambda old: save_named(old, name, queue.pending, replace=replace))
            else:
                names = sorted(queues, key=str.casefold)
                if not names:
                    return
                with wx.SingleChoiceDialog(dialog, _("Choose a saved queue:"), title, names) as choice:
                    if show_modal(choice) != wx.ID_OK or choice.GetSelection() < 0:
                        return
                    name = names[choice.GetSelection()]
                if mode == "delete":
                    if message_box(_("Delete this saved queue?"), title, wx.YES_NO | wx.NO_DEFAULT,
                                   parent=dialog) != wx.YES:
                        return
                    queue.owner._save_tool_setting(key, lambda old: {
                        n: rows for n, rows in saved_queues(old).items() if n != name})
                else:
                    if queue.pending and message_box(_("Replace the current playback queue?"), title,
                            wx.YES_NO | wx.NO_DEFAULT, parent=dialog) != wx.YES:
                        return
                    queue.pending[:] = queues[name]
        except (OSError, ValueError) as error:
            message_box(str(error), title, wx.OK | wx.ICON_ERROR, parent=dialog)
        finally:
            refresh()

    def edit(delta):
        index = queue.edit(listing.GetSelection(), delta)
        refresh(index)
        listing.SetFocus()

    def start(event):
        dialog.EndModal(wx.ID_OK)

    def button(label, handler):
        item = wx.Button(dialog.panel, label=label)
        item.Bind(wx.EVT_BUTTON, handler)
        controls.Add(item, 0, wx.ALL, 4)
        return item

    up = button(_("Move Up"), lambda evt: edit(-1))
    down = button(_("Move Down"), lambda evt: edit(1))
    remove = button(_("Remove from Queue"), lambda evt: edit(None))
    play = button(_("Play Queue"), start)
    halt = button(_("Stop after Current Recording"), lambda evt: queue.stop())
    save = button(_("Save Queue..."), lambda evt: manage("save"))
    load = button(_("Load Saved Queue..."), lambda evt: manage("load"))
    delete = button(_("Delete Saved Queue..."), lambda evt: manage("delete"))
    dialog.buttons([])
    listing.Bind(wx.EVT_LISTBOX, lambda evt: refresh(listing.GetSelection()))

    def keyboard(event):
        key = event.GetKeyCode()
        if event.ControlDown() and key in (wx.WXK_UP, wx.WXK_DOWN):
            edit(-1 if key == wx.WXK_UP else 1)
        elif key in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
            edit(None)
        else:
            event.Skip()

    listing.Bind(wx.EVT_KEY_DOWN, keyboard)
    queue.changed = refresh
    try:
        refresh()
        listing.SetFocus()
        return show_modal(dialog) == wx.ID_OK
    finally:
        queue.changed = None
        dialog.Destroy()
