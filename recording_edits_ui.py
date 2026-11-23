"""Accessible, on-demand choices for one scheduled programme."""

import time

import wx
import user_guide

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


def _review(parent, owner, job, prepare, completed, *, new=False, future_start=None, question="", validate=None):
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

        def commit():
            if validate:
                validate()
            scheduler.apply_reviewed_edit(revision, changes, future_start=future_start)

        start_operation(
            parent,
            "save-recording-edit",
            commit,
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


def review_guide_changes(parent, owner, completed, *, notify_only=False):
    scheduler = owner._ensure_dvr_scheduler(start=True)

    def find(jobs):
        if not jobs:
            return []
        db = EPGDatabase(options.get_db_path(), readonly=True)
        try:
            db.conn.execute("BEGIN")
            return edits.changed_guide_times(db, jobs, canceled=lambda: getattr(parent, "closed", False))
        finally:
            db.close()

    def search():
        return find(scheduler.list_jobs(include_done=False))

    def ready(rows, error):
        if notify_only:
            if rows:
                owner._show_or_queue_message_box(
                    _("The guide times changed for {count} scheduled recording(s). Open Scheduled Recordings and choose Review Guide Changes.").format(
                        count=len({job["id"] for job, _, _ in rows})),
                    _("Scheduled Recordings"), wx.OK | wx.ICON_INFORMATION)
            return
        if error:
            error_box(parent, error)
            return
        if not rows:
            message_box(_("No changes were found to upcoming recording times."), _("Review Guide Changes..."), wx.OK, parent=parent)
            return

        def window(programme):
            return " – ".join(dvr.parse_epg_utc(programme[k]).astimezone().strftime("%Y-%m-%d %H:%M") for k in ("start", "end"))

        labels = []
        for job, programme, exact in rows:
            before, after = edits.padding(job)
            labels.append(_("{title} — {channel}. Previous time: {old}. New time: {new}. Padding in minutes: {before} before, {after} after.").format(
                title=job["title"], channel=job["channel_name"], old=window(job["program"]), new=window(programme),
                before=before, after=after) + " " + (_("Matching programme details.") if exact else _("Possible time change. Check the programme.")))
        dialog = wx.SingleChoiceDialog(parent, _("Choose a time change to review:"), _("Review Guide Changes..."), labels)
        user_guide.set_help_topic(dialog, "scheduled-recordings")
        try:
            if show_modal(dialog) != wx.ID_OK or dialog.GetSelection() < 0:
                return
            i = dialog.GetSelection()
        finally:
            dialog.Destroy()
        job, programme, exact = rows[i]

        def current():
            if (job, programme, exact) not in find([job]):
                raise ValueError(_("The programme guide changed. Refresh the list and try again."))

        _review(parent, owner, job, lambda jobs: edits.retime_booking(job, programme, jobs, time.time()),
                completed, future_start=dvr.parse_epg_utc(programme["start"]).timestamp() - edits.padding(job)[0] * 60,
                question=labels[i] + "\n\n" + _("Apply this time change?"), validate=current)

    start_operation(parent, "review-guide-changes", search, ready, wx.CallAfter)


def find_airing(parent, owner, job, completed, *, new=False):
    channels = owner.all_channels
    scheduler = owner._ensure_dvr_scheduler(start=True)
    config = dict(owner.config)
    aliases = programme_reminders.source_names(config)
    if hasattr(owner, "_scoped_sources"):
        from main import _source_scope_id
        for src in owner._scoped_sources():
            alias = programme_reminders.safe_title(owner._scope_choice_label(src))
            if alias:
                aliases.setdefault(_source_scope_id(src), alias)

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
            window = (start - before * 60, end + after * 60)
            demand = recording_limits.peak_demand(config, channel, *window, jobs, exclude=job["id"])
            if demand is None:
                label = _("Recording Conflicts") if recording_limits.warning(
                    config, channel, *window, jobs, exclude=job["id"]) else ""
            else:
                peak, limit = demand
                label = _("Connections needed: {count}. Account limit: {limit}.").format(count=peak, limit=limit)
                if peak > limit:
                    label += " — " + _("Recording Conflicts")
            warnings.append(label)
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
        source_numbers = {}
        for (channel, programme, exact), capacity in zip(rows, warnings):
            times = [dvr.parse_epg_utc(programme[k]).astimezone().strftime("%Y-%m-%d %H:%M") for k in ("start", "end")]
            source_id = channel.get("provider-id") or channel.get("playlist-id")
            alias = aliases.get(source_id)
            if source_id and not alias:
                alias = _("Source {number}").format(number=source_numbers.setdefault(source_id, len(source_numbers) + 1))
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
                            _("Same time, different source") if programme["start"] == job["program"]["start"] else "",
                            capacity,
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

        def validate():
            if owner.all_channels is not channels:
                raise ValueError(_("The channel list changed. Try again."))
            db = EPGDatabase(options.get_db_path(), readonly=True)
            try:
                current = db.programme_details(programme)
            finally:
                db.close()
            if any((current[k] or "") != programme[k] for k in ("episode", "subtitle", "description")):
                raise ValueError(_("The programme guide changed. Refresh the list and try again."))

        def prepare(jobs):
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
            validate=validate,
        )

    start_operation(parent, "find-alternative-airing", search, ready, wx.CallAfter)
