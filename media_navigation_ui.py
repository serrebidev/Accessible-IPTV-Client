"""On-demand navigation using libVLC's media clock, never its playback rate."""
import time

import wx
import user_guide
from i18n import gettext as _, N_
from modal_guard import show_modal, message_box
from media_navigation import PendingSeek, clock_text, parse_position, target_position

SEEK_ACTIONS = {
    "seek_back_10": (-10000, N_("Back 10 Seconds")),
    "seek_forward_10": (10000, N_("Forward 10 Seconds")),
    "seek_back_60": (-60000, N_("Back 60 Seconds")),
    "seek_forward_60": (60000, N_("Forward 60 Seconds")),
}


class MediaNavigationMixin:
    def _add_navigation_menu(self, menu):
        self._navigation_help_items = []
        menu.AppendSeparator()
        for action, (delta, label) in SEEK_ACTIONS.items():
            item = menu.Append(wx.ID_ANY, self._shortcut_label(_(label), action))
            self.Bind(wx.EVT_MENU, lambda event, amount=delta: self._seek_media(delta=amount), item)
        for action, label, handler in (("go_to_time", _("Go to Time..."), self._go_to_media_time),
                                       ("media_time", _("Playback Time"), self._announce_media_time)):
            item = menu.Append(wx.ID_ANY, self._shortcut_label(label, action))
            self.Bind(wx.EVT_MENU, handler, item)
            user_guide.set_menu_help(self, item, 'video-on-demand')
            self._navigation_help_items.append((item, 'video-on-demand'))
        for action, label, handler in (
                ('previous_episode', _("Previous Episode"), lambda event: self._navigate_episode(-1)),
                ('next_episode', _("Next Episode"), lambda event: self._navigate_episode(1)),
                ('subtitle_timing', _("Subtitle Timing..."), lambda event: self._subtitle_timing())):
            item = menu.Append(wx.ID_ANY, self._shortcut_label(label, action))
            self.Bind(wx.EVT_MENU, handler, item)
            user_guide.set_menu_help(self, item, 'subtitle-speech' if action == 'subtitle_timing' else 'video-on-demand')
            self._navigation_help_items.append((item, 'subtitle-speech' if action == 'subtitle_timing' else 'video-on-demand'))

    def _navigate_episode(self, direction):
        import episode_continuation_ui
        episode_continuation_ui.navigate(self, direction)

    def _subtitle_timing(self, _event=None):
        if getattr(self, '_destroyed', False) or getattr(self, '_manual_stop', False):
            return
        generation = getattr(self, '_vlc_generation', 0)
        try:
            current = self.player.video_get_spu_delay() // 1000
            dialog = wx.Dialog(self, title=_("Subtitle Timing..."))
            layout = wx.BoxSizer(wx.VERTICAL)
            label = _("Subtitle delay in milliseconds (-600000 to 600000). Positive values display and read subtitles later; 0 resets timing.")
            layout.Add(wx.StaticText(dialog, label=label), 0, wx.ALL, 10)
            value = wx.SpinCtrl(dialog, min=-600000, max=600000, initial=max(-600000, min(600000, current)))
            value.SetName(label)
            value.SetIncrement(500)
            layout.Add(value, 0, wx.EXPAND | wx.ALL, 10)
            reset = wx.Button(dialog, label=_("Reset Timing"))
            reset.Bind(wx.EVT_BUTTON, lambda event: value.SetValue(0))
            layout.Add(reset, 0, wx.ALL, 10)
            layout.Add(dialog.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 10)
            dialog.SetSizerAndFit(layout)
            user_guide.set_help_topic(dialog, 'subtitle-speech')
            value.SetFocus()
            try:
                if show_modal(dialog) == wx.ID_OK and generation == getattr(self, '_vlc_generation', 0):
                    self._apply_subtitle_timing(value.GetValue())
            finally:
                dialog.Destroy()
        except Exception as error:
            self._navigation_message(str(error))

    def _apply_subtitle_timing(self, milliseconds):
        if type(milliseconds) is not int or not -600000 <= milliseconds <= 600000:
            raise ValueError(_("Invalid subtitle delay."))
        result = self.player.video_set_spu_delay(milliseconds * 1000)
        if result is not None and result < 0:
            raise ValueError(_("Subtitle timing could not be changed."))
        self._subtitle_timing_ms = milliseconds
        sink = getattr(self, '_subtitle_sink', None)
        if sink is not None:
            sink.clear()
        source = getattr(self, '_subtitle_file_source', None)
        if source is not None:
            source.seeked()
            self._subtitle_generation = source.generation
        self._cue_index = self._last_cue_index = self._review_cue_index = None
        self._subtitle_last_time = None
        label = getattr(self, 'subtitle_label', None)
        if label is not None:
            label.SetLabel('')
        self._navigation_message(_("Subtitle delay: {milliseconds} ms.").format(milliseconds=milliseconds))

    def _media_clock(self):
        if (getattr(self, "_destroyed", False) or getattr(self, "_manual_stop", False)
                or getattr(self, "_current_stream_kind", "") != "vod"):
            raise ValueError(_("This command is available during on-demand playback."))
        position, length = self.player.get_time(), self.player.get_length()
        target_position(position, length, target=position)
        return position, length

    def _navigation_message(self, text):
        self._update_status_label(text, priority=4)
        self._speak(self.status_label)  # explicitly requested information

    def _seek_media(self, *, delta=None, target=None):
        try:
            position, length = self._media_clock()
            if not self.player.is_seekable():
                raise ValueError(_("This stream does not support seeking."))
            pending = getattr(self, "_pending_media_seek", None)
            generation = getattr(self, "_vlc_generation", 0)
            origin = pending.target if pending and pending.generation == generation else position
            destination = target_position(origin, length, delta=delta, target=target)
            result = self.player.set_time(destination)
            if result is not None and result < 0:
                raise ValueError(_("The player could not seek to the requested position."))
            self._pending_media_seek = PendingSeek(generation, destination, time.monotonic(), position)
            sink = getattr(self, "_subtitle_sink", None)
            if sink is not None:
                sink.clear()
            source = getattr(self, "_subtitle_file_source", None)
            if source is not None:
                source.seeked()
                self._subtitle_generation = source.generation
            self._cue_index = self._last_cue_index = self._review_cue_index = None
            label = getattr(self, "subtitle_label", None)
            if label is not None:
                label.SetLabel("")
        except Exception as error:
            self._navigation_message(str(error))

    def _poll_media_seek(self):
        pending = getattr(self, "_pending_media_seek", None)
        if pending is None:
            return False
        try:
            position = self.player.get_time()
        except Exception:
            position = -1
        state = pending.outcome(getattr(self, "_vlc_generation", 0), position)
        if getattr(self, "_manual_stop", False):
            state = "stale"
        if state == "pending":
            return True
        self._pending_media_seek = None
        if state == "done":
            self._resume_start_ms = 0
            self._save_resume_checkpoint(force=True)
            self._announce_media_time()
        elif state == "failed":
            self._resume_last_save = time.monotonic()
            self._navigation_message(_("The player could not seek to the requested position."))
        return False

    def _go_to_media_time(self, event=None):
        try:
            position, length = self._media_clock()
        except Exception as error:
            self._navigation_message(str(error))
            return
        generation = getattr(self, "_vlc_generation", 0)
        dialog = wx.TextEntryDialog(self, _("Enter seconds, MM:SS or HH:MM:SS."),
                                    _("Go to Time..."), clock_text(position))
        try:
            while show_modal(dialog) == wx.ID_OK:
                if generation != getattr(self, "_vlc_generation", 0) or getattr(self, "_destroyed", False):
                    return
                try:
                    target = parse_position(dialog.GetValue())
                    if target >= length:
                        raise ValueError(_("Choose a position before the end of the media."))
                except ValueError as error:
                    message_box(str(error), _("Go to Time..."), wx.OK | wx.ICON_WARNING, parent=self)
                    continue
                self._seek_media(target=target)
                return
        finally:
            dialog.Destroy()

    def _announce_media_time(self, event=None):
        try:
            position, length = self._media_clock()
            text = _("Elapsed: {elapsed}. Total: {total}. Remaining: {remaining}.").format(
                elapsed=clock_text(position), total=clock_text(length), remaining=clock_text(length - position))
        except Exception as error:
            text = str(error)
        self._navigation_message(text)
