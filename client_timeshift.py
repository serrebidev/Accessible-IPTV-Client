"""GUI-side local buffer ownership; transport/setup/cleanup run in workers."""
import logging
import threading
import time

import wx
from http_headers import channel_http_headers
from i18n import gettext as _
from modal_guard import message_box
from options import save_config, resolve_internal_player_settings
import user_guide

LOG = logging.getLogger(__name__)


class LiveBufferMixin:
    def _ensure_live_buffers(self):
        if getattr(self, '_live_buffers', None) is None:
            from live_buffer import LiveBufferRegistry
            self._live_buffers = LiveBufferRegistry()
            self.recorder.live_buffer_registry = self._live_buffers
            self._live_buffer_lock = threading.Lock()
            self._live_buffer_generation = 0
            self._live_buffer_cancel = threading.Event()
            self._live_buffer_current = None
            self._live_buffer_work_done = threading.Event()
            self._live_buffer_work_done.set()
            self._live_buffer_retiring_done = threading.Event()
            self._live_buffer_retiring_done.set()
        return self._live_buffers

    def _buffer_source(self, url, headers=None):
        registry = getattr(self, '_live_buffers', None)
        return registry.find(url, headers) if registry is not None else None

    def _buffer_probe_input(self, url, headers):
        session = self._buffer_source(url, headers)
        if session is None:
            return url, headers
        return session.cursor()[0], {}

    def _configure_live_buffer(self, _event=None):
        from live_buffer import buffer_settings
        frame = getattr(self, '_internal_player_frame', None)
        if frame is None:
            return
        enabled, seconds, mib = buffer_settings(self.config)
        dlg = wx.NumberEntryDialog(frame,
            _('Keep up to this many minutes of live TV (1–30); 0 disables the local buffer.'),
            _('Minutes:'), _('Local Live Buffer'), seconds // 60 if enabled else 0, 0, 30)
        user_guide.set_help_topic(dlg, 'built-in-player')
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            minutes = dlg.GetValue()
        finally:
            dlg.Destroy()
        current = getattr(self, '_live_buffer_current', None)
        if not minutes:
            if current and current['session'].lease_count > 1:
                message_box(_('The local buffer is still feeding a recording. Stop the recording before disabling it.'),
                            _('Local Live Buffer'), wx.OK | wx.ICON_INFORMATION, parent=frame)
                return
            self.config['live_buffer_enabled'] = False
        else:
            dlg = wx.NumberEntryDialog(frame,
                _('Maximum local buffer size per session (MiB). Old data is removed when either limit is reached.'),
                _('MiB:'), _('Local Live Buffer'), mib, 64, 4096)
            user_guide.set_help_topic(dlg, 'built-in-player')
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                mib = dlg.GetValue()
            finally:
                dlg.Destroy()
            self.config.update(live_buffer_enabled=True, live_buffer_seconds=minutes * 60, live_buffer_mib=mib)
        save_config(self.config)
        channel = getattr(self, '_internal_player_channel', None)
        if channel and getattr(self, '_internal_player_stream_kind', '') == 'live':
            self._launch_stream(self._resolve_live_url(channel), self._channel_display_name(channel), channel=channel,
                                show_internal_player=frame.IsShown(), focus_player=False)

    def _intercept_live_buffer(self, url, title, kind, channel, shown, focus):
        registry = getattr(self, '_live_buffers', None)
        current = getattr(self, '_live_buffer_current', None)
        builtin = self.default_player in {'Built-in Player', 'player_Internal', 'internal', 'Internal'}
        caster = getattr(self, 'caster', None)
        casting = caster is not None and caster.is_connected()
        wants = (self.config.get('live_buffer_enabled') is True and builtin and not casting and kind == 'live'
                 and (channel or {}).get('kind') != 'movie')
        if registry is not None and registry.owns_view(url):
            return False
        previous = getattr(self, '_live_buffer_work_done', None)
        retiring = getattr(self, '_live_buffer_retiring_done', None)
        unfinished = (previous is not None and not previous.is_set()) or (retiring is not None and not retiring.is_set())
        if not wants and current is None and not getattr(self, '_live_buffer_pending', False) and not unfinished:
            return False
        if casting and current is not None:
            message_box(_('Stop local buffered playback before switching to a cast device.'),
                        _('Local Live Buffer'), wx.OK | wx.ICON_INFORMATION)
            return True
        from catchup_urls import single_stream_provider_key
        registry = self._ensure_live_buffers()
        headers = channel_http_headers(channel)
        provider = single_stream_provider_key(url)
        if provider and self.recorder.has_active_connection(provider) and registry.find(url, headers) is None:
            return False
        terminate = getattr(self, '_terminate_media_probe', None)
        if callable(terminate):
            terminate(channel)
        self._live_buffer_cancel.set()
        cancel = self._live_buffer_cancel = threading.Event()
        self._live_buffer_generation += 1
        generation = self._live_buffer_generation
        self._live_buffer_pending = True
        previous, retiring = self._live_buffer_work_done, self._live_buffer_retiring_done
        done = self._live_buffer_work_done = threading.Event()
        frame = getattr(self, '_internal_player_frame', None)
        # Resolve from a snapshot on the GUI thread, before any source starts.
        # Do not construct wx/libVLC here or mutate config on the ingest worker.
        saved_cap = resolve_internal_player_settings(dict(self.config)).variant_max_mbps
        variant_cap = (getattr(frame, '_variant_max_mbps', saved_cap)
                       if frame is not None and not getattr(frame, '_destroyed', False) else saved_cap)
        stopped = None
        if frame is not None and not getattr(frame, '_destroyed', False):
            frame._buffer_transition = True
            try:
                stopped = frame.stop(manual=True)
            finally:
                frame._buffer_transition = False
            frame._live_buffer_active = False
        old, self._live_buffer_current = self._live_buffer_current, None

        def work():
            from live_buffer import BufferLease, LiveBufferSession, buffer_settings
            from recorder import get_ffmpeg_path
            lease = None
            previous.wait()
            retiring.wait()
            with self._live_buffer_lock:
                try:
                    if stopped is not None:
                        stopped.result(timeout=20)
                    if old:
                        old['lease'].release()
                    if cancel.is_set():
                        return
                    if not wants:
                        registry.wait_provider_idle(provider, cancel)
                        wx.CallAfter(self._buffer_direct_ready, generation, url, title, kind, channel, shown, focus)
                        return
                    session = registry.find(url, headers)
                    if session is None:
                        registry.wait_provider_idle(provider, cancel)
                        import catchup_direct
                        catchup_direct.settle_media_session()
                        if cancel.is_set():
                            return
                        _, seconds, mib = buffer_settings(self.config)
                        session = LiveBufferSession(seconds=seconds, max_bytes=mib * 1024**2)
                        lease = BufferLease(session)
                        with registry.ingest_gate:
                            if provider and self.recorder.has_active_connection(provider):
                                raise RuntimeError('recording acquired provider during buffer startup')
                            registry.put(url, headers, session)
                        session.start(get_ffmpeg_path(), url, headers,
                                      cap_mbps=variant_cap)
                    else:
                        lease = session.acquire()
                    session.wait_ready(30, cancel)
                    local, row = session.cursor()
                    ack, ownership = threading.Event(), {'accepted': False}
                    def deliver():
                        try:
                            ownership['accepted'] = self._buffer_ready(generation, lease, session, local, row,
                                                                      title, channel, shown, focus)
                        finally:
                            ack.set()
                    wx.CallAfter(deliver)
                    while not ack.wait(0.1):
                        if cancel.is_set():
                            lease.release()
                            lease = None
                            return
                    if not ownership['accepted']:
                        lease.release()
                    lease = None
                except Exception:
                    LOG.exception('Could not prepare local live buffer')
                    if lease is not None:
                        lease.release()
                    wx.CallAfter(self._buffer_failed, generation)
                finally:
                    done.set()
        threading.Thread(target=work, name='live-buffer-transition', daemon=True).start()
        return True

    def _buffer_direct_ready(self, generation, url, title, kind, channel, shown, focus):
        if generation != self._live_buffer_generation or getattr(self, '_exit_requested', False):
            return
        self._live_buffer_pending = False
        self._launch_stream(url, title, stream_kind=kind, channel=channel,
                            show_internal_player=shown, focus_player=focus, _buffer_bypass=True)

    def _buffer_ready(self, generation, lease, session, url, row, title, channel, shown, focus):
        if generation != self._live_buffer_generation or getattr(self, '_exit_requested', False):
            return False
        if session.window.error:
            self._buffer_failed(generation)
            return False
        self._live_buffer_pending = False
        self._live_buffer_current = dict(lease=lease, session=session, url=url, channel=channel, title=title,
                                         position=row.start, last_clock=None)
        self._live_buffer_last_channel, self._live_buffer_last_title = channel, title
        self._live_buffer_last_view = url
        self._launch_stream(url, title, stream_kind='live', channel=channel,
                            show_internal_player=shown, focus_player=focus, _buffer_bypass=True)
        frame = getattr(self, '_internal_player_frame', None)
        if frame is not None and not getattr(frame, '_destroyed', False) and frame._current_url == url:
            frame._live_buffer_active = True
            frame._on_buffer_poll = self._poll_live_buffer
            frame._on_buffer_resume = self._resume_live_buffer
            frame._on_buffer_stop = self._close_live_buffer_player
            return True
        self._live_buffer_current = None
        return False

    def _buffer_failed(self, generation):
        if generation != self._live_buffer_generation or getattr(self, '_exit_requested', False):
            return
        self._live_buffer_pending = False
        message_box(_('The local live buffer could not start. No extra provider connection was opened. Disable the buffer to retry direct playback.'),
                    _('Local Live Buffer'), wx.OK | wx.ICON_ERROR)

    def _buffer_position(self):
        current = getattr(self, '_live_buffer_current', None)
        frame = getattr(self, '_internal_player_frame', None)
        if not current or frame is None or frame._current_url != current['url']:
            return None, None, None
        rows = current['session'].window.snapshot()
        switch = getattr(frame, '_vlc_switch', None)
        if switch is not None and not switch.done():
            return current, rows, None
        try:
            clock = frame.player.get_time()
            state = str(frame.player.get_state()).lower()
            if clock >= 0 and (state.endswith('playing') or state.endswith('paused')):
                before = current['last_clock']
                if before is not None and clock >= before:
                    current['position'] += (clock - before) / 1000
                current['last_clock'] = clock
        except Exception:
            LOG.debug('Could not sample buffer playback clock', exc_info=True)
            return current, rows, None
        return current, rows, current['position']

    def _seek_live_buffer(self):
        current, rows, _ = self._buffer_position()
        if not current or not rows:
            return self._return_live_buffer()
        dlg = wx.NumberEntryDialog(self._internal_player_frame,
            _('Seconds behind the latest buffered picture; 0 returns to live.'), _('Seconds:'),
            _('Rewind Live TV'), 0, 0, max(0, int(rows[-1].start - rows[0].start)))
        user_guide.set_help_topic(dlg, 'built-in-player')
        try:
            if dlg.ShowModal() == wx.ID_OK:
                self._jump_live_buffer(dlg.GetValue())
        finally:
            dlg.Destroy()

    def _save_recent_broadcast(self):
        import math
        import os
        import buffer_clip
        import recorder
        import recording_storage
        import storage_monitor
        from background_tasks import start_operation
        from options import get_recordings_dir
        from modal_guard import show_modal
        frame = self._internal_player_frame
        pending = getattr(self, '_buffer_clip_dialog', None)
        if pending:
            pending.Raise()
            return
        current = getattr(self, '_live_buffer_current', None)
        rows = current['session'].window.snapshot() if current else ()
        if not rows:
            message_box(_("No buffered audio or video is available."), _("Save Recent Broadcast..."), wx.OK, parent=frame)
            return
        seconds = max(1, math.ceil(rows[-1].end - rows[0].start))
        dlg = wx.NumberEntryDialog(frame, _("Available history: {seconds} seconds.").format(seconds=seconds),
                                   _("Duration (seconds)"), _("Save Recent Broadcast..."), min(300, seconds), 1, seconds)
        user_guide.set_help_topic(dlg, 'built-in-player')
        try:
            if show_modal(dlg) != wx.ID_OK:
                return
            selected = buffer_clip.select_segments(rows, dlg.GetValue())
        finally:
            dlg.Destroy()
        folder = get_recordings_dir(self.config)
        name = recorder.sanitize_filename(current.get('title') or 'IPTV') + time.strftime('-%Y%m%d-%H%M%S.ts')
        with wx.FileDialog(frame, _("Save Recent Broadcast..."), defaultDir=folder, defaultFile=name,
                           wildcard='MPEG-TS (*.ts)|*.ts', style=wx.FD_SAVE) as dialog:
            if show_modal(dialog) != wx.ID_OK:
                return
            path = dialog.GetPath()
        if not path.lower().endswith('.ts'):
            path += '.ts'
        try:
            lease = current['session'].acquire()
        except Exception as error:
            message_box(str(error), _("Save Recent Broadcast..."), wx.OK | wx.ICON_ERROR, parent=frame)
            return
        cancel = self._buffer_clip_cancel = threading.Event()
        progress = self._buffer_clip_dialog = wx.Dialog(frame, title=_("Save Recent Broadcast..."))
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(wx.StaticText(progress, label=_("Saving the broadcast excerpt...")), 0, wx.ALL, 10)
        button = wx.Button(progress, wx.ID_CANCEL, _("Cancel"))
        layout.Add(button, 0, wx.ALL, 8)
        progress.SetSizerAndFit(layout)
        def stop(event):
            cancel.set()
            button.Disable()
            if isinstance(event, wx.CloseEvent) and event.CanVeto():
                event.Veto()
        progress.Bind(wx.EVT_CLOSE, stop)
        button.Bind(wx.EVT_BUTTON, stop)
        progress.Show()
        reserve = recording_storage.normalize_reserve(self.config.get('recording_min_free_mib'))
        enabled, _warning, critical, auto_stop = storage_monitor.settings(self.config)
        if enabled and auto_stop:
            reserve = max(reserve, critical)
        def work():
            try:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                buffer_clip.save(current['session'].window, selected, path, recorder.get_ffmpeg_path(), reserve,
                                 cancel.is_set, on_staged=lease.release)
            finally:
                lease.release()
        def done(_result, error):
            lease.release()
            self._buffer_clip_dialog = None
            if progress:
                progress.Destroy()
            if not getattr(self, '_exit_requested', False) and not isinstance(error, InterruptedError):
                message_box(str(error) if error else _("Saved to {path}.").format(path=path),
                            _("Save Recent Broadcast..."), wx.OK | (wx.ICON_ERROR if error else wx.ICON_INFORMATION), parent=self)
        start_operation(self, 'save-buffer-clip', work, done, wx.CallAfter)

    def _jump_live_buffer(self, behind):
        current = getattr(self, '_live_buffer_current', None)
        if current is None:
            return False
        try:
            url, row = current['session'].cursor(behind)
        except Exception:
            LOG.debug('No retained buffer position', exc_info=True)
            return False
        current.update(url=url, position=row.start, last_clock=None)
        self._live_buffer_last_view = url
        frame = self._internal_player_frame
        self._launch_stream(url, current['title'], stream_kind='live', channel=current['channel'],
                            show_internal_player=frame.IsShown(), focus_player=False, _buffer_bypass=True)
        return True

    def _return_live_buffer(self):
        if not self._jump_live_buffer(0) and not self._resume_live_buffer():
            message_box(_('No local live history is available.'), _('Local Live Buffer'), wx.OK | wx.ICON_INFORMATION)

    def _resume_live_buffer(self):
        current, rows, position = self._buffer_position()
        frame = getattr(self, '_internal_player_frame', None)
        channel = getattr(self, '_live_buffer_last_channel', None)
        if (current is None and channel and frame is not None and getattr(frame, '_manual_stop', False)
                and frame._current_url == getattr(self, '_live_buffer_last_view', None)):
            self._launch_stream(self._resolve_live_url(channel), self._live_buffer_last_title, channel=channel,
                                show_internal_player=frame.IsShown(), focus_player=False)
            return True
        if current and rows and position is not None and position < rows[0].start:
            self._jump_live_buffer(rows[-1].start - rows[0].start)
            frame._update_status_label(_('The paused position expired. Playback resumed at the oldest retained picture.'), priority=1)
            return True
        return False

    def _poll_live_buffer(self):
        current, rows, position = self._buffer_position()
        if not current:
            return False
        frame = self._internal_player_frame
        if current['session'].window.error:
            frame.stop(manual=True)
            frame._update_status_label(_('The local buffer stopped because its storage or input failed.'), priority=1)
            return True
        if not getattr(frame, '_is_paused', False) and rows and position is not None and position < rows[0].start:
            self._jump_live_buffer(rows[-1].start - rows[0].start)
            frame._update_status_label(_('The old buffered position expired; playback moved to the retained window.'), priority=1)
            return True
        proc = current['session'].process
        if proc is not None and proc.poll() is not None and str(frame.player.get_state()).lower().endswith('ended'):
            frame._buffer_transition = True
            try:
                frame.stop(manual=True)
            finally:
                frame._buffer_transition = False
            frame._update_status_label(_('Live input ended; retained history is still available.'), priority=1)
            return True
        return False

    def _close_live_buffer_player(self):
        if getattr(self, '_live_buffers', None) is None:
            return
        self._live_buffer_generation += 1
        self._live_buffer_cancel.set()
        current, self._live_buffer_current = self._live_buffer_current, None
        self._live_buffer_pending = False
        frame = getattr(self, '_internal_player_frame', None)
        if frame is not None:
            frame._live_buffer_active = False
        if current:
            done = self._live_buffer_retiring_done = threading.Event()
            def retire():
                try:
                    with self._live_buffer_lock:
                        current['lease'].release()
                finally:
                    done.set()
            threading.Thread(target=retire, daemon=True).start()

    def _shutdown_live_buffers(self):
        cancel = getattr(self, '_buffer_clip_cancel', None)
        if cancel:
            cancel.set()
        self._close_live_buffer_player()
        registry = getattr(self, '_live_buffers', None)
        if registry is not None:
            threading.Thread(target=registry.close, daemon=True).start()
