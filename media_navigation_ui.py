"""Keyboard-accessible media navigation and local recording playback controls."""
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


class SubtitleMatches(wx.ListCtrl):
    def __init__(self, parent, rows):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL)
        self.rows = rows
        self.SetName(_("Subtitle matches"))
        self.InsertColumn(0, _("Time"), width=100)
        self.InsertColumn(1, _("Subtitles"), width=470)
        self.SetItemCount(len(rows))
        self.Select(0)
        self.Focus(0)

    def OnGetItemText(self, index, column):
        if not 0 <= index < len(self.rows):
            return ""
        cue = self.rows[index]
        return clock_text(cue.start) if column == 0 else cue.text


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

        for label, action, topic in (
                (_("Find Text in Recording Subtitles..."), lambda e: self._find_subtitle_text(e), "subtitle-speech"),
                (_("Recording Playback Speed..."), lambda e: self._choose_recording_speed(e), "recordings"),
                (_("Normal speed"), lambda e: self._restore_normal_speed(), "recordings")):
            item = menu.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, action, item)
            self._navigation_help_items.append((item, topic))

        chapters = menu.Append(wx.ID_ANY, _("Recording Chapters..."))
        self.Bind(wx.EVT_MENU, self._recording_chapters, chapters)
        self._navigation_help_items.append((chapters, "recordings"))

    def _is_local_playback(self):
        return (not getattr(self, "_manual_stop", False) and self._current_stream_kind == "vod"
                and bool((getattr(self, "_episode_channel", None) or {}).get("local-recording")))

    def _choose_recording_speed(self, _event=None):
        if not self._is_local_playback() or not self.player.is_seekable():
            self._navigation_message(_("Open a seekable local recording first."))
            return
        rates = (0.75, 1.0, 1.25, 1.5, 2.0)
        import locale
        labels = [locale.format_string("%g", value) + "×" for value in rates]
        labels[1] = _("Normal speed")
        dialog = wx.SingleChoiceDialog(self, _("Choose the playback speed:"), _("Recording Playback Speed..."), labels)
        dialog.SetSelection(rates.index(getattr(self, "_local_playback_rate", 1.0)))
        user_guide.set_help_topic(dialog, "recordings")
        generation = self._vlc_generation
        try:
            if show_modal(dialog) == wx.ID_OK and generation == self._vlc_generation and self._is_local_playback():
                index = dialog.GetSelection()
                if index >= 0:
                    self._apply_recording_speed(rates[index], labels[index])
        finally:
            dialog.Destroy()

    def _apply_recording_speed(self, rate, label):
        if self.player.set_rate(rate) == 0:
            self._local_playback_rate = rate
            self._navigation_message(label)
        else:
            self._navigation_message(_("The playback speed could not be changed."))

    def _restore_normal_speed(self):
        if self._is_local_playback() and self.player.is_seekable():
            self._apply_recording_speed(1.0, _("Normal speed"))
        else:
            self._navigation_message(_("Open a seekable local recording first."))

    def _reset_recording_speed(self):
        if getattr(self, "_local_playback_rate", 1.0) != 1.0 and self.player.set_rate(1.0) == 0:
            self._local_playback_rate = 1.0

    def _find_subtitle_text(self, _event=None):
        if not self._is_local_playback() or not self.player.is_seekable():
            self._navigation_message(_("Open a seekable local recording first."))
            return
        source = getattr(self, "_subtitle_file_source", None)
        if source is None or not source.cues:
            self._navigation_message(_("Load a text subtitle file or select an embedded text track first."))
            return
        generation = self._vlc_generation
        title = _("Find Text in Recording Subtitles...")
        dialog = wx.TextEntryDialog(self, _("Text to find:"), title)
        user_guide.set_help_topic(dialog, "subtitle-speech")
        try:
            if show_modal(dialog) != wx.ID_OK:
                return
            query = dialog.GetValue().strip().casefold()
        finally:
            dialog.Destroy()
        if not query:
            return

        def current():
            return (not self._destroyed and generation == self._vlc_generation and self._is_local_playback()
                    and self._subtitle_file_source is source)

        def found(rows, error):
            if not current():
                return
            if error or not rows:
                self._navigation_message(str(error) if error else _("No matching subtitles."))
                return
            results = wx.Dialog(self, title=title, size=(640, 420), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            layout = wx.BoxSizer(wx.VERTICAL)
            listing = SubtitleMatches(results, rows)
            listing.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: results.EndModal(wx.ID_OK))
            layout.Add(listing, 1, wx.EXPAND | wx.ALL, 8)
            layout.Add(results.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 8)
            results.SetSizer(layout)
            user_guide.set_help_topic(results, "subtitle-speech")
            listing.SetFocus()
            try:
                if show_modal(results) == wx.ID_OK and current():
                    index = listing.GetFirstSelected()
                    if index >= 0:
                        delay = self.player.video_get_spu_delay() // 1000
                        self._seek_media(target=max(0, rows[index].start + delay))
            finally:
                results.Destroy()
        from background_tasks import start_operation
        start_operation(self, "subtitle-search", lambda: [cue for cue in source.cues if query in cue.text.casefold()],
                        found, wx.CallAfter)

    def _recording_chapters(self, _event=None):
        import recording_media
        if not (getattr(self, "_episode_channel", {}) or {}).get("local-recording") or getattr(self, "_manual_stop", False):
            self._navigation_message(_("Open a local recording to browse its chapters."))
            return
        try:
            generation = self._vlc_generation
            title = self.player.get_title()
            rows = recording_media.chapters(self.player)
            if not rows:
                self._navigation_message(_("This recording has no chapters."))
                return
            labels = [(name or _("Chapter {number}").format(number=index + 1)) + " — " + clock_text(start)
                      for index, start, name in rows]
            dialog = wx.SingleChoiceDialog(self, _("Choose a chapter:"), _("Recording Chapters..."), labels)
            dialog.SetSelection(next((i for i, row in enumerate(rows) if row[0] == self.player.get_chapter()), 0))
            user_guide.set_help_topic(dialog, "recordings")
            try:
                if show_modal(dialog) != wx.ID_OK or generation != self._vlc_generation or self.player.get_title() != title:
                    return
                selection = dialog.GetSelection()
            finally:
                dialog.Destroy()
            if selection >= 0 and self.player.is_seekable():
                self.player.set_chapter(rows[selection][0])
                self._navigation_message(labels[selection])
            elif selection >= 0:
                self._navigation_message(_("This stream does not support seeking."))
        except Exception as error:
            self._navigation_message(str(error))

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
