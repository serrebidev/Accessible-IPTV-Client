"""What is said when a recording finishes.

Split out of main.IPTVClient: the success/failure/warning reports and the
deferred-notification queue. IPTVClient inherits RecordingReportsMixin, so
every call site and main.IPTVClient.<name> still resolves.
"""

import logging
import os

import wx

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

    def _report_recording_saved(self, rec) -> None:
        """Recording finished cleanly: notify, or queue the box if one is up."""
        self._show_or_queue_message_box(
            _("Recording saved:\n{path}").format(path=rec.out_path),
            _("Recording Complete"), wx.OK | wx.ICON_INFORMATION)

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
        job_id = None
        try:
            job_id = rec.metadata.get("dvr_job_id")
        except Exception:
            job_id = None
        if job_id:
            detail = "\n".join(rec.stderr_tail[-6:])
            suppressed = getattr(self, "_suppress_recording_notifications", False)
            produced = _recording_produced_media(rec)
            if suppressed:
                message = "Stopped because the app exited."
            elif rc:
                message = detail
            else:
                message = "" if produced else _("Nothing was recorded: the stream ended before it wrote anything.")
            self._ensure_dvr_scheduler(start=True).mark_finished(
                str(job_id),
                success=(produced and not suppressed),
                output_path=rec.out_path,
                message=message,
            )
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
            if rc == 0 and _recording_produced_media(rec):
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
