"""Native, keyboard-accessible controls for recording and channel tools."""
import threading

import wx

import channel_preferences
import options
import storage_monitor
import user_guide
from i18n import gettext as _
from modal_guard import message_box, show_modal


def error_box(parent, error):
    message_box(_("The operation failed:\n{error}").format(error=error), _("Error"),
                wx.OK | wx.ICON_ERROR, parent=parent)


def labeled(parent, sizer, label, control):
    sizer.Add(wx.StaticText(parent, label=label), 0, wx.LEFT | wx.TOP, 8)
    control.SetName(label)
    sizer.Add(control, 0, wx.EXPAND | wx.ALL, 8)
    return control


def standard_buttons(parent):
    row = wx.StdDialogButtonSizer()
    accept = wx.Button(parent, wx.ID_OK, label=_("OK"))
    cancel = wx.Button(parent, wx.ID_CANCEL, label=_("Cancel"))
    row.AddButton(accept)
    row.AddButton(cancel)
    row.Realize()
    accept.SetDefault()
    return row


class SpaceSettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Recording Space Monitor"))
        enabled, warning, critical, stop = storage_monitor.settings(parent.config)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.enabled = wx.CheckBox(self, label=_("Monitor free space while recording"))
        self.enabled.SetValue(enabled)
        layout.Add(self.enabled, 0, wx.ALL, 8)
        self.warning = labeled(self, layout, _("Warn below (MiB):"),
                               wx.SpinCtrl(self, min=16, max=1048576, initial=warning))
        self.stop = wx.CheckBox(self, label=_("Stop recordings safely when space is critically low"))
        self.stop.SetValue(stop)
        layout.Add(self.stop, 0, wx.ALL, 8)
        self.critical = labeled(self, layout, _("Stop below (MiB):"),
                                wx.SpinCtrl(self, min=16, max=1048576, initial=critical))
        layout.Add(standard_buttons(self), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizerAndFit(layout)
        self.Bind(wx.EVT_BUTTON, self.accept, id=wx.ID_OK)
        user_guide.set_help_topic(self, "recordings")

    def accept(self, _event):
        if self.warning.GetValue() < self.critical.GetValue():
            error_box(self, _("The warning threshold must be at least as high as the stop threshold."))
            return
        self.EndModal(wx.ID_OK)


class EpgMappingDialog(wx.Dialog):
    def __init__(self, parent, channel):
        super().__init__(parent, title=_("Assign Programme Guide"), size=(670, 480),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.value = None
        self.closed = False
        self.all_rows = []
        self.rows = []
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(wx.StaticText(self, label=_("Channel: {name}").format(name=channel.get("name", ""))), 0, wx.ALL, 8)
        self.search = labeled(self, layout, _("Search guide channels:"), wx.TextCtrl(self))
        self.search.SetValue(channel_preferences.epg_id(channel))
        self.list = wx.ListBox(self)
        self.list.SetName(_("Programme guide channels"))
        layout.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        self.status = wx.StaticText(self, label=_("Loading guide channels..."))
        layout.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        automatic = wx.Button(self, label=_("Use Automatic Matching"))
        layout.Add(automatic, 0, wx.ALL, 8)
        layout.Add(standard_buttons(self), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(layout)
        self.search.Bind(wx.EVT_TEXT, self.filter)
        self.Bind(wx.EVT_BUTTON, self.accept, id=wx.ID_OK)
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self.accept)
        automatic.Bind(wx.EVT_BUTTON, lambda event: self.accept_automatic())
        self.Bind(wx.EVT_WINDOW_DESTROY, self.destroying)
        self.search.SetFocus()
        user_guide.set_help_topic(self, "epg")
        threading.Thread(target=self.load, daemon=True).start()

    def destroying(self, event):
        if event.GetEventObject() is self:
            self.closed = True
        event.Skip()

    def load(self):
        from playlist import EPGDatabase
        db = None
        try:
            db = EPGDatabase(options.get_db_path(), readonly=True)
            rows = db.conn.execute("SELECT id, display_name FROM channels ORDER BY display_name, id").fetchall()
            error = ""
        except Exception as exc:
            rows, error = [], str(exc)
        finally:
            if db is not None:
                db.close()
        wx.CallAfter(self.loaded, rows, error)

    def loaded(self, rows, error):
        if self.closed:
            return
        self.all_rows = [(str(key), str(name or key)) for key, name in rows]
        self.filter()
        if error:
            error_box(self, error)

    def filter(self, _event=None):
        query = self.search.GetValue().strip().casefold()
        matches = [row for row in self.all_rows if query in (row[1] + " " + row[0]).casefold()]
        self.rows = matches[:500]
        self.list.Set([name + " [" + key + "]" for key, name in self.rows])
        self.status.SetLabel(_("Showing {count} of {total} matching channels. Refine the search if needed.").format(
            count=len(self.rows), total=len(matches)))

    def accept(self, _event):
        selected = self.list.GetSelection()
        if selected == wx.NOT_FOUND:
            error_box(self, _("Select a programme guide channel, or choose automatic matching."))
            return
        self.value = self.rows[selected][0]
        self.EndModal(wx.ID_OK)

    def accept_automatic(self):
        self.value = ""
        self.EndModal(wx.ID_OK)


from recording_library_ui import RecordingLibraryDialog  # noqa: E402


class AccessibleToolsMixin:
    def _add_recording_power_menu(self, menu):
        import recording_power
        for key, label, default in (
                ("prevent_sleep_while_recording", _("Prevent Automatic Sleep While Recording"), True),
                ("wake_for_recordings", _("Wake for Scheduled Recordings (Windows)"), False)):
            item = menu.AppendCheckItem(wx.ID_ANY, label)
            item.Check(self.config.get(key, default) is True)
            item.Enable(recording_power.supported())
            def toggle(event, setting=key, control=item, default_value=default):
                previous = self.config.get(setting, default_value) is True
                try:
                    self._save_tool_setting(setting, lambda old: event.IsChecked())
                    self._start_recording_power()
                    manager = getattr(self, "_recording_power", None)
                    if manager:
                        manager.refresh()
                except Exception as error:
                    control.Check(previous)
                    error_box(self, error)
            menu.Bind(wx.EVT_MENU, toggle, item)

    def _start_recording_power(self):
        import recording_power
        if not recording_power.supported() or getattr(self, "_recording_power", None):
            return
        def snapshot():
            scheduler = getattr(self, "dvr_scheduler", None)
            jobs = scheduler.list_jobs(include_done=False) if scheduler else []
            return dict(self.config), self.recorder.has_active(), jobs
        def notify(error):
            wx.CallAfter(self._recording_power_failed, str(error))
        self._recording_power = recording_power.RecordingPower(snapshot, notify)
        self._recording_power.start()

    def _recording_power_failed(self, error):
        manager = getattr(self, "_recording_power", None)
        if manager and not manager.stopping.is_set():
            self._show_or_queue_message_box(_("Recording power management failed:\n{error}").format(error=error),
                                           _("Recording"), wx.OK | wx.ICON_WARNING)

    def _add_sound_tools_menu(self, menu):
        auto_next = menu.AppendCheckItem(wx.ID_ANY, _("Automatically Play the Next Episode"))
        auto_next.Check(self.config.get("auto_next_episode") is True)
        def toggle_next(event):
            previous = self.config.get("auto_next_episode") is True
            try:
                self._save_tool_setting("auto_next_episode", lambda old: event.IsChecked())
            except Exception as error:
                auto_next.Check(previous)
                error_box(self, error)
        menu.Bind(wx.EVT_MENU, toggle_next, auto_next)
        user_guide.set_menu_help(self, auto_next, "video-on-demand")
        item = menu.Append(wx.ID_ANY, self._shortcut_label(_("Mute / Unmute"), "mute"))
        menu.Bind(wx.EVT_MENU, self._toggle_player_mute, item)
        remember = menu.AppendCheckItem(wx.ID_ANY, _("Remember Volume for Each Channel"))
        remember.Check(self.config.get("remember_channel_volume") is True)
        def toggle(event):
            value = event.IsChecked()
            try:
                self._save_tool_setting("remember_channel_volume", lambda _old: value)
                frame = getattr(self, "_internal_player_frame", None)
                if frame and not getattr(frame, "_destroyed", False):
                    if not value:
                        frame._unscoped_volume = frame._volume_value
                    self._prepare_channel_volume(frame, getattr(self, "_internal_player_channel", None))
            except Exception as error:
                remember.Check(not value)
                error_box(self, error)
        menu.Bind(wx.EVT_MENU, toggle, remember)

    def _add_channel_tools_menu(self, menu):
        import session_tools_ui
        history = menu.Append(wx.ID_ANY, _("Notification History..."))
        menu.Bind(wx.EVT_MENU, lambda event: session_tools_ui.show_notifications(self), history)
        user_guide.set_menu_help(self, history, "personal-tools")
        item = menu.Append(wx.ID_ANY, _("Assign Programme Guide..."))
        menu.Bind(wx.EVT_MENU, self._assign_programme_guide, item)

    def _toggle_player_mute(self, _event=None):
        frame = getattr(self, "_internal_player_frame", None)
        if frame and not getattr(frame, "_destroyed", False):
            frame.toggle_mute()
        else:
            message_box(_("Start playback in the built-in player first."), _("Mute / Unmute"), wx.OK, parent=self)

    def _prepare_channel_volume(self, frame, channel):
        if not callable(getattr(frame, "set_volume_context", None)):
            return
        frame._flush_channel_volume()
        if not getattr(frame, "_volume_context", ""):
            frame._unscoped_volume = frame._volume_value
        default = getattr(frame, "_unscoped_volume", frame._volume_value)
        key = channel_preferences.channel_key(channel) if self.config.get("remember_channel_volume") is True else ""
        value = channel_preferences.volume(self.config, key, default) if key else default
        frame.set_volume_context(key, value, self._remember_channel_volume)

    def _remember_channel_volume(self, key, value):
        self._save_tool_setting("channel_volumes", lambda old: channel_preferences.remember_volume(old, key, value))

    def _save_player_preferences(self):
        with options._SAVE_LOCK:
            config = options.load_config()
            for key in ("playback_bookmarks", "recording_playback_bookmarks", "sleep_fade_seconds"):
                if key in self.config:
                    config[key] = self.config[key]
            if options._save_config_locked(config) is False:
                raise OSError(_("The settings could not be saved. Check the free space and write permissions, then try again."))

    def _configure_space_monitor(self, _event=None):
        dialog = SpaceSettingsDialog(self)
        try:
            if show_modal(dialog) != wx.ID_OK:
                return
            changes = {"recording_monitor_space": dialog.enabled.GetValue(),
                       "recording_warn_free_mib": dialog.warning.GetValue(),
                       "recording_stop_free_mib": dialog.critical.GetValue(),
                       "recording_stop_low_space": dialog.stop.GetValue()}
            with options._SAVE_LOCK:
                config = options.load_config()
                config.update(changes)
                if options._save_config_locked(config) is False:
                    raise OSError(_("The settings could not be saved. Check the free space and write permissions, then try again."))
            self.config.update(changes)
            self.recorder.storage_preferences = storage_monitor.settings(self.config)
        except Exception as error:
            error_box(self, error)
        finally:
            dialog.Destroy()

    def _recording_space_warning(self, state, directory, free, count):
        def report():
            if getattr(self, "_suppress_recording_notifications", False):
                return
            if state == "unavailable":
                text = _("Free space could not be checked while recording:\n{path}").format(path=directory)
            elif state == "stopping":
                text = _("Recording space is critically low ({free} MiB). The {count} recording(s) on this drive are being stopped safely.\n{path}").format(
                    free=free, count=count, path=directory)
            else:
                text = _("Recording space is running low: {free} MiB remains.\n{path}").format(free=free, path=directory)
            self._show_or_queue_message_box(text, _("Recording Storage"), wx.OK | wx.ICON_WARNING)
        wx.CallAfter(report)

    def _assign_programme_guide(self, _event=None):
        channel = self._selected_channel()
        if not channel or channel.get("kind") == "movie":
            error_box(self, _("Select a live channel first."))
            return
        key = channel_preferences.channel_key(channel)
        generation = getattr(self, "_playlist_load_token", None)
        dialog = EpgMappingDialog(self, channel)
        try:
            if show_modal(dialog) != wx.ID_OK:
                return
            if generation != getattr(self, "_playlist_load_token", None):
                raise ValueError(_("The playlists changed. Select the channel again."))
            def update(old):
                values = dict(old) if isinstance(old, dict) else {}
                if dialog.value:
                    values[key] = dialog.value
                else:
                    values.pop(key, None)
                return values
            self._save_tool_setting("epg_channel_overrides", update)
            channel_preferences.configure(self.config)
            self._program_match_cache = None
            self._epg_match_cache.clear()
            self._refresh_now_playing_labels(force=True)
        except Exception as error:
            error_box(self, error)
        finally:
            dialog.closed = True
            dialog.Destroy()

    def _show_recording_library(self, _event=None):
        dialog = getattr(self, "_recording_library_dialog", None)
        if dialog and not dialog.closed and dialog.directories[0] != options.get_recordings_dir(self.config):
            dialog.close()
            dialog = None
        if dialog and not dialog.closed:
            dialog.Show()
            dialog.Raise()
            return
        dialog = RecordingLibraryDialog(self)
        self._recording_library_dialog = dialog
        dialog.Show()
