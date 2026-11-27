"""What is said when a recording finishes.

Split out of main.IPTVClient: the success/failure/warning reports and the
deferred-notification queue. IPTVClient inherits RecordingReportsMixin, so
every call site and main.IPTVClient.<name> still resolves.
"""

import logging
import os

import wx
import recording_outcome

from i18n import gettext as _

LOG = logging.getLogger("EPG.ui")


def _recording_produced_media(rec) -> bool:
    """True when the capture left a file with bytes in it.

    ffmpeg exits 0 when the stream closes before it writes a frame, and the
    report said "Recording saved" pointing at nothing.
    """
    try:
        return os.path.getsize(rec.out_path) > 0
    except OSError:
        return False


class RecordingReportsMixin:

    def _drain_deferred_notifications(self) -> None:
        """Show notifications queued while a modal box was open (FIFO)."""
        queue = self._deferred_notifications()
        while queue and not self._modal_box_is_open():
            message, caption, style, parent, on_dismiss = queue.pop(0)
            try:
                self._show_message_box(message, caption, style, parent=parent, on_dismiss=on_dismiss)
            except Exception:
                # One bad entry must not swallow the rest of the queue.
                LOG.exception("Deferred notification %r could not be shown", caption)

    def _configure_recording_notices(self, _event=None):
        from modal_guard import message_box, show_modal
        import user_guide

        title = _("Recording Notifications...")
        keys = ("dialog", "speech", "history")
        labels = [_("Show a dialog"), _("Announce and save in history"), _("Save in history only")]
        current = self.config.get("recording_success_notification", "dialog")
        with wx.SingleChoiceDialog(self, _("When a recording starts or finishes successfully:"),
                                    title, labels) as dialog:
            user_guide.set_help_topic(dialog, "recordings")
            dialog.SetSelection(keys.index(current) if current in keys else 0)
            if show_modal(dialog) == wx.ID_OK and dialog.GetSelection() >= 0:
                try:
                    choice = keys[dialog.GetSelection()]
                    self._save_tool_setting("recording_success_notification", lambda old: choice)
                except OSError as error:
                    message_box(str(error), title, wx.OK | wx.ICON_ERROR, parent=self)

    def _report_recording_success(self, message, caption, spoken):
        mode = getattr(self, "config", {}).get("recording_success_notification")
        if mode not in ("speech", "history"):
            self._show_or_queue_message_box(message, caption, wx.OK | wx.ICON_INFORMATION)
            return
        import named_bookmarks

        self._notification_history = named_bookmarks.notification(
            getattr(self, "_notification_history", []), caption, message)
        if mode == "speech":
            from live_announce import speak
            speak(spoken)

    def _report_recording_saved(self, rec) -> None:
        """Recording finished cleanly: notify, or queue the box if one is up."""
        message = _("Recording saved:\n{path}").format(path=rec.out_path)
        RecordingReportsMixin._report_recording_success(self, message, _("Recording Complete"),
                                                       _("Recording saved: {title}").format(title=getattr(rec, "title", "") or rec.out_path))

    def _report_nothing_recorded(self, rec) -> None:
        """ffmpeg exited 0 having written nothing: say so, do not say "saved"."""
        self._show_or_queue_message_box(
            _("Nothing was recorded: the stream ended before it wrote anything."),
            _("Recording Warning"), wx.OK | wx.ICON_WARNING)

    def _report_recording_warning(self, rec, rc: int) -> None:
        self._show_or_queue_message_box(
            _("Recording stopped, but ffmpeg reported code {code}.\n\n{detail}\n\nFile:\n{path}").format(
                code=rc, detail=self._recording_failure_detail(rec), path=rec.out_path),
            _("Recording Warning"), wx.OK | wx.ICON_WARNING)

    def _report_recording_error(self, rec, rc: int) -> None:
        detail = self._recording_failure_detail(rec)
        if getattr(rec, "fmt", "") == "provider_mka" and not rec.stopped_by_user:
            # The MKA preset copies the audio verbatim and never transcodes:
            # when the source cannot be copied into the container, say so
            # plainly and point at another audio format instead of silently
            # substituting one.
            detail = _("The audio could not be copied into an MKA container, "
                       "so nothing was recorded and nothing was transcoded. "
                       "Choose another audio format from Recordings > Recording "
                       "Format and try again.\n\n{detail}").format(detail=detail)
        self._show_or_queue_message_box(
            _("Recording of {name} ended unexpectedly (code {code}).\n\n{detail}").format(
                name=rec.title, code=rc, detail=detail),
            _("Recording Error"), wx.OK | wx.ICON_ERROR)

    def _on_recording_finished(self, rec, rc):
        suppressed = getattr(self, "_suppress_recording_notifications", False)
        outcome = recording_outcome.classify(rec, rc)
        job_id = None
        try:
            job_id = rec.metadata.get("dvr_job_id")
        except Exception:
            job_id = None
        if job_id:
            scheduler = self._ensure_dvr_scheduler(start=not suppressed)
            current = scheduler.get_job(str(job_id)) or {}
            expected = None
            if current.get("stop_ts") and type(current.get("start_ts")) in (int, float):
                expected = max(0, float(current["stop_ts"]) - current["start_ts"])
            outcome = recording_outcome.classify(
                rec, rc, planned_seconds=expected, scheduled_start=current.get("start_ts"))
            detail = "\n".join(rec.stderr_tail[-6:])
            produced = _recording_produced_media(rec)
            if suppressed and getattr(rec, "stop_reason", "") == "exit":
                message = _("Stopped because the app exited.")
            elif rc:
                message = detail
            elif outcome == "partial":
                message = _("The recording did not cover the full scheduled time.")
            else:
                message = "" if produced else _("Nothing was recorded: the stream ended before it wrote anything.")
            scheduler.mark_finished(
                str(job_id),
                success=outcome == "completed",
                output_path=rec.out_path,
                message=message,
                outcome=outcome,
            )
        rec.outcome = outcome
        if getattr(self, "_suppress_recording_notifications", False):
            return
        shared = (getattr(self, "_shared_recordings", None) or {}).pop(rec.id, None)
        if shared:
            # The player was watching this recording's copy of the stream.
            wx.CallAfter(self._end_shared_playback, shared)
        # Called from the recorder's watcher thread, so the check has to be
        # marshalled onto the UI thread like the report below.
        wx.CallAfter(self._maybe_shutdown_after_recordings)

        wx.CallAfter(self._sync_internal_player_record_state)

        def report():
            if outcome == "partial":
                self._show_or_queue_message_box(
                    _("Only part of the programme was recorded. The available file has been kept:\n{path}").format(path=rec.out_path),
                    _("Recording Warning"), wx.OK | wx.ICON_WARNING)
            elif rc == 0 and _recording_produced_media(rec):
                self._report_recording_saved(rec)
            elif rc == 0 and not rec.stopped_by_user:
                self._report_nothing_recorded(rec)
            elif rec.stopped_by_user:
                self._report_recording_warning(rec, rc)
            else:
                self._report_recording_error(rec, rc)
            self._drain_deferred_notifications()
        wx.CallAfter(report)

    def _recording_failure_detail(self, rec) -> str:
        """What ffmpeg said, plus where the rest of what it said was written."""
        lines = list(rec.stderr_tail[-6:]) or [_("No ffmpeg details were reported.")]
        counts = getattr(rec, "problem_counts", None)
        if counts and any(counts.values()):
            lines.insert(0, _(
                "{warnings} warnings, {errors} errors and {fatals} fatal "
                "errors were logged in total.").format(
                    warnings=counts.get("warnings", 0),
                    errors=counts.get("errors", 0),
                    fatals=counts.get("fatals", 0)))
        log_path = getattr(rec, "log_path", "")
        if log_path and os.path.exists(log_path):
            lines.append("")
            lines.append(_("Full ffmpeg log:\n{path}").format(path=log_path))
        return "\n".join(lines)
