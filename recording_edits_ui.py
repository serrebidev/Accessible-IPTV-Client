"""Accessible, on-demand choices for one scheduled programme."""

import time

import wx

import dvr
import options
import recording_limits
import recording_edits as edits
import programme_reminders
from background_tasks import start_operation
from i18n import gettext as _
from modal_guard import message_box, show_modal
from personal_tools_ui import ToolDialog, confirm, error_box
from playlist import EPGDatabase


def _review(parent, owner, job, prepare, completed, *, new=False, future_start=None, question=""):
    scheduler = owner._ensure_dvr_scheduler(start=True)
    config = dict(owner.config)

    def preview():
        revision, jobs = scheduler.edit_snapshot()
        if (not new and jobs.get(job["id"]) != job) or (new and job["id"] in jobs):
            raise ValueError(_("The recording schedule changed. Check the times and try again."))
        changes = prepare(jobs)
        return revision, changes, edits.warnings(config, changes, jobs)

    def reviewed(result, error):
        if error:
            error_box(parent, error)
            return
        revision, changes, warnings = result
        text = "\n\n".join(filter(None, [question, *warnings]))
        if text and not confirm(parent, text):
            return

        def saved(_result, failure):
            if failure:
                error_box(parent, failure)
            else:
                completed()

        start_operation(
            parent,
            "save-recording-edit",
            lambda: scheduler.apply_reviewed_edit(revision, changes, future_start=future_start),
            saved,
            wx.CallAfter,
        )

    start_operation(parent, "review-recording-edit", preview, reviewed, wx.CallAfter)


def padding_dialog(parent, owner, job, completed):
    from dialogs_misc import RecordingPaddingDialog

    dialog = RecordingPaddingDialog(parent, *edits.padding(job), job=job)
    try:
        if show_modal(dialog) != wx.ID_OK:
            return
        before, after = dialog.get_padding()
        future = bool(dialog.future and dialog.future.GetValue())
    finally:
        dialog.Destroy()
    _review(
        parent, owner, job, lambda jobs: edits.edit_padding(job, before, after, future, jobs, time.time()), completed
    )


def find_airing(parent, owner, job, completed, *, new=False):
    channels = owner.all_channels
    scheduler = owner._ensure_dvr_scheduler(start=True)
    config = dict(owner.config)

    def search():
        db = EPGDatabase(options.get_db_path(), readonly=True)
        try:
            rows, truncated = edits.other_airings(db, job, channels, canceled=lambda: getattr(parent, "closed", False))
        finally:
            db.close()
        jobs = scheduler.list_jobs(include_done=False)
        before, after = edits.padding(job)
        warnings = []
        for channel, programme, _exact in rows:
            start, end = (dvr.parse_epg_utc(programme[k]).timestamp() for k in ("start", "end"))
            warnings.append(
                bool(
                    recording_limits.warning(
                        config, channel, start - before * 60, end + after * 60, jobs, exclude=job["id"]
                    )
                )
            )
        return rows, truncated, warnings

    def ready(result, error):
        if error or owner.all_channels is not channels:
            error_box(parent, error or _("The channel list changed. Try again."))
            return
        rows, truncated, warnings = result
        if not rows:
            message_box(
                _("No alternative airings were found in the next 14 days."),
                _("Find Another Airing..."),
                wx.OK,
                parent=parent,
            )
            return
        labels = []
        aliases = programme_reminders.source_names(config)
        for (channel, programme, exact), conflict in zip(rows, warnings):
            times = [dvr.parse_epg_utc(programme[k]).astimezone().strftime("%Y-%m-%d %H:%M") for k in ("start", "end")]
            alias = aliases.get(channel.get("provider-id") or channel.get("playlist-id"))
            labels.append(
                " — ".join(
                    filter(
                        None,
                        [
                            programme["title"],
                            programme_reminders.safe_title(dvr.channel_name(channel)),
                            alias,
                            " – ".join(times),
                            _("Same episode") if exact else _("Possible repeat"),
                            _("Recording Conflicts") if conflict else "",
                        ],
                    )
                )
            )
        seen = {}
        for i, label in enumerate(labels):
            seen[label] = seen.get(label, 0) + 1
            if seen[label] > 1:
                labels[i] += " — " + _("Source {number}").format(number=seen[label])
        dialog = ToolDialog(parent, _("Find Another Airing..."))
        dialog.help_topic = "scheduled-recordings"
        listing = dialog.listbox(_("Programmes"))
        listing.Set(labels)
        listing.SetSelection(0)
        if truncated:
            dialog.label(_("Only the first 100 results are shown."))
        dialog.buttons([], accept=True)
        listing.SetFocus()
        try:
            if show_modal(dialog) != wx.ID_OK or listing.GetSelection() < 0:
                return
            i = listing.GetSelection()
        finally:
            dialog.Destroy()
        channel, programme, _exact = rows[i]
        when = dvr.parse_epg_utc(programme["start"]).timestamp()
        fmt = job.get("format")
        if programme_reminders.channel_key(channel) != programme_reminders.channel_key(job["channel"]):
            fmt = owner._recording_format_for_channel(channel)[0]

        def prepare(jobs):
            if owner.all_channels is not channels:
                raise ValueError(_("The channel list changed. Try again."))
            db = EPGDatabase(options.get_db_path(), readonly=True)
            try:
                current = db.programme_details(programme)
            finally:
                db.close()
            if any((current[k] or "") != programme[k] for k in ("episode", "subtitle")):
                raise ValueError(_("The programme guide changed. Refresh the list and try again."))
            changes = edits.move_airing(job, channel, programme, fmt, jobs, time.time())
            if new and not job.get("repeat"):
                changes.pop(job["id"], None)
            return changes

        _review(
            parent,
            owner,
            job,
            prepare,
            completed,
            new=new,
            future_start=when,
            question=_("Record this airing instead?") + "\n" + labels[i],
        )

    start_operation(parent, "find-alternative-airing", search, ready, wx.CallAfter)
