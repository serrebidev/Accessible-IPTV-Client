"""Session-only playback queue. File validation is deferred until each hand-off."""

import os

from background_tasks import LatestTask
from i18n import gettext as _
import recording_library


class RecordingQueue:
    def __init__(self, owner, dispatch):
        self.owner = owner
        self.dispatch = dispatch
        self.pending = []
        self.playing = False
        self.loading = False
        self.worker = None
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
        if self.loading and (not self.pending or self.pending[0] is not first):
            self.start(focus=False)  # discard validation of the replaced item, keeping focus in the editor
        self.notify()
        return min(index, len(self.pending) - 1)

    def stop(self):
        self.ticket = None
        self.playing = self.loading = False
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
                self.pending.pop(0)
                self.notify()

        try:
            worker.submit(resolve, ready)
        except RuntimeError as error:
            ready(None, error)
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
            self.next()


def get_queue(owner):
    import wx

    queue = getattr(owner, "_recording_queue", None)
    if queue is None:
        queue = owner._recording_queue = RecordingQueue(owner, wx.CallAfter)
    return queue


def show_editor(parent, queue):
    import wx
    from modal_guard import show_modal
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
