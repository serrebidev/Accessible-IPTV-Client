"""Persistent DVR scheduling for Accessible IPTV Client.

The scheduler is GUI-free. It owns durable schedule entries and calls supplied
callbacks when a recording should start or stop. The GUI decides how to resolve a
stored channel snapshot into a playable URL and how to notify the user.
"""

from __future__ import annotations

import datetime
import copy
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from i18n import gettext as _
from typing import Callable, Dict, List, Optional

LOG = logging.getLogger(__name__)

STATUS_SCHEDULED = "scheduled"
STATUS_RECORDING = "recording"
STATUS_STOPPING = "stopping"
STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"
STATUS_MISSED = "missed"
STATUS_CANCELED = "canceled"
STATUS_SKIPPED = "skipped"
TIME_REPEATS = {"daily", "weekly", "weekdays"}

ACTIVE_STATUSES = {STATUS_SCHEDULED, STATUS_RECORDING, STATUS_STOPPING}
DONE_STATUSES = {STATUS_COMPLETED, STATUS_PARTIAL, STATUS_STOPPED, STATUS_FAILED, STATUS_MISSED, STATUS_CANCELED, STATUS_SKIPPED}

DEFAULT_PRE_PADDING_MINUTES = 0
DEFAULT_POST_PADDING_MINUTES = 2
# How long a job may sit in "stopping" before it is written off. This has to clear
# the time the recorder gives ffmpeg to close its container, which for a large MP4
# means rewriting the whole file to move the moov atom to the front: minutes on the
# external and network drives recordings usually live on. Two minutes declared a
# recording failed while ffmpeg was still successfully finishing it.
STOP_TIMEOUT_SECONDS = 1800.0


def utc_now_ts() -> float:
    return time.time()


def parse_epg_utc(value: str) -> datetime.datetime:
    """Parse XMLTV/EPG UTC timestamps used by the EPG database."""
    return datetime.datetime.strptime(str(value), "%Y%m%d%H%M%S").replace(
        tzinfo=datetime.timezone.utc
    )


def iso_from_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc).isoformat()


def _number(value, default: float = 0.0) -> float:
    """A number out of the schedule file, or ``default`` when it is not one.

    The file is written by the app, but it can be hand-edited or left
    half-written, and one bad value must not take the scheduler - or the
    startup that loads it - down with it.
    """
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _valid_stored_job(job):
    if (not isinstance(job, dict) or not isinstance(job.get('status'), str)
            or job['status'] not in ACTIVE_STATUSES | DONE_STATUSES
            or type(job.get('id')) not in (str, int) or not job['id']):
        return False
    repeat = job.get('repeat')
    if repeat is not None and (not isinstance(repeat, str) or repeat not in ('', 'daily', 'weekly', 'series', 'weekdays')):
        return False
    if repeat == 'weekdays':
        from planning_tools import checked_weekdays
        try:
            days = checked_weekdays(job.get('weekdays'))
        except ValueError:
            return False
        if not days:
            return False
    if repeat in TIME_REPEATS:
        return 0 <= _number(job.get('start_ts'), -1) < _number(job.get('stop_ts')) <= 253402300799
    return True


def program_title(program: Dict[str, str]) -> str:
    return (
        program.get("show_title")
        or program.get("title")
        or program.get("program")
        or "Untitled Program"
    )


def program_episode_key(program: Dict[str, str]) -> Optional[str]:
    """Stable identity of one episode of a series, or None when unknown.

    Series recordings use it for rerun suppression: two airings with the
    same key are the same episode, however the guide spells the rest.
    Preference order, strongest first: the XMLTV episode number
    (xmltv_ns "season.episode." is zero-based and becomes S<season+1>
    E<episode+1>; any other system's text is compared case-folded with
    punctuation stripped), then the sub-title, then a fingerprint of the
    description. A programme with none of the three has no identity and
    is never suppressed — a shared title alone proves nothing, as daily
    shows and news bulletins demonstrate.
    """
    episode = str(program.get("episode") or "").strip()
    if episode:
        # xmltv_ns is zero-based and written with a trailing dot
        # ("0.4." = season 1, episode 5); the S01E05 and 1x5 spellings
        # are already one-based. All three land on the same key.
        m = re.fullmatch(r"(\d+)\.(\d+)\.(?:\d+(?:/\d+)?)?", episode)
        if m:
            return "ep:{0}x{1}".format(int(m.group(1)) + 1, int(m.group(2)) + 1)
        m = re.fullmatch(r"s(\d+)\s*e(\d+)", episode, re.IGNORECASE) or \
            re.fullmatch(r"(\d+)x(\d+)", episode, re.IGNORECASE)
        if m:
            return "ep:{0}x{1}".format(int(m.group(1)), int(m.group(2)))
        compact = "".join(ch for ch in episode.casefold() if ch.isalnum())
        if compact:
            return "ep:" + compact
    subtitle = " ".join(str(program.get("subtitle") or "").split()).casefold()
    if subtitle:
        return "sub:" + subtitle
    description = " ".join(str(program.get("description") or "").split()).casefold()
    if description:
        return "desc:" + hashlib.sha1(description.encode("utf-8")).hexdigest()[:16]
    return None


def taken_episode_keys(jobs: List[Dict[str, object]], rule_id: str) -> set:
    """Episode keys a series rule already has, from its stored jobs.

    Active and successfully completed episodes suppress reruns. Failed,
    missed, partial and stopped captures remain eligible for a later airing.
    Canceling an episode retains the existing opt-in-to-reruns behavior.
    """
    taken = set()
    for job in jobs:
        if job.get("status") not in ACTIVE_STATUSES | {STATUS_COMPLETED}:
            continue
        if job.get("id") != rule_id and job.get("series_source") != rule_id:
            continue
        key = program_episode_key(job.get("program") or {})
        if key:
            taken.add(key)
    return taken


def channel_name(channel: Dict[str, str]) -> str:
    return (
        channel.get("name")
        or channel.get("tvg-name")
        or channel.get("tvg_name")
        or channel.get("tvg-id")
        or channel.get("tvg_id")
        or "IPTV Stream"
    )


def clean_channel_snapshot(channel: Dict[str, object]) -> Dict[str, object]:
    """Return a JSON-safe channel snapshot for persisted scheduled recordings."""
    try:
        return json.loads(json.dumps(channel or {}, default=str))
    except Exception:
        return {str(k): str(v) for k, v in (channel or {}).items()}


def build_job(
    channel: Dict[str, object],
    program: Dict[str, str],
    fmt: str,
    *,
    pre_padding_minutes: int = DEFAULT_PRE_PADDING_MINUTES,
    post_padding_minutes: int = DEFAULT_POST_PADDING_MINUTES,
    created_at: Optional[float] = None,
    job_id: Optional[str] = None,
    repeat: str = "",
) -> Dict[str, object]:
    try:
        start_dt = parse_epg_utc(program.get("start", ""))
        end_dt = parse_epg_utc(program.get("end", ""))
    except ValueError as err:
        raise ValueError(_("Invalid programme times.")) from err
    if end_dt <= start_dt:
        raise ValueError(_("Program end time must be after the start time."))

    pre = max(0, int(pre_padding_minutes or 0))
    post = max(0, int(post_padding_minutes or 0))
    start_ts = start_dt.timestamp() - pre * 60
    stop_ts = end_dt.timestamp() + post * 60
    now = created_at if created_at is not None else utc_now_ts()
    chan_name = channel_name(channel)
    title = program_title(program)
    display_title = "{title} - {channel}".format(title=title, channel=chan_name)
    return {
        "id": job_id or uuid.uuid4().hex,
        "status": STATUS_SCHEDULED,
        "title": title,
        "channel_name": chan_name,
        "display_title": display_title,
        "channel": clean_channel_snapshot(channel),
        "program": dict(program or {}),
        "format": fmt,
        "start_at": iso_from_ts(start_dt.timestamp()),
        "end_at": iso_from_ts(end_dt.timestamp()),
        "start_ts": start_ts,
        "stop_ts": stop_ts,
        "pre_padding_minutes": pre,
        "post_padding_minutes": post,
        "created_at": iso_from_ts(now),
        "recording_id": None,
        "output_path": "",
        "message": "",
        "repeat": repeat if repeat in {"daily", "weekly", "series"} else "",
    }


class DVRScheduler:
    """Polls persisted jobs and starts/stops scheduled recordings."""

    def __init__(
        self,
        path: str,
        *,
        on_start: Callable[[Dict[str, object]], object],
        on_stop: Callable[[Dict[str, object]], None],
        on_update: Optional[Callable[[], None]] = None,
        on_series: Optional[Callable[[], None]] = None,
        clock: Callable[[], float] = utc_now_ts,
        poll_seconds: float = 15.0,
    ):
        self.path = path
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_update = on_update
        self.on_series = on_series
        self.clock = clock
        self.poll_seconds = max(0.2, float(poll_seconds))
        self._lock = threading.RLock()
        # Serializes whole saves. The scheduler thread and the UI both save,
        # and two writers sharing one .tmp file made os.replace fail with
        # "access denied" on Windows.
        self._save_lock = threading.Lock()
        self._revision = 0
        self._save_worker = None
        self._save_requested = False
        self._jobs: Dict[str, Dict[str, object]] = {}
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._stopping_since: Dict[str, float] = {}
        self._thread: Optional[threading.Thread] = None
        self._last_series_scan = 0.0
        self._series_scan_thread: Optional[threading.Thread] = None
        self.load_warning = ""
        self._load_error = None
        self.load()

    def load(self) -> None:
        with self._lock:
            self._jobs = {}
            if not self.path or not os.path.exists(self.path):
                return
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                jobs = data.get("jobs") if isinstance(data, dict) else data
                if not isinstance(jobs, list):
                    raise ValueError("The schedule does not contain a list of jobs.")
            except Exception:
                LOG.exception("Failed to load DVR schedule: %s", self.path)
                try:
                    backup = self._preserve_corrupt_schedule()
                    self.load_warning = _("The recording schedule could not be read. The original file was preserved at {path}. Check your scheduled recordings before adding new ones.").format(path=backup)
                except OSError as exc:
                    self._load_error = exc
                    self.load_warning = _("The recording schedule could not be read or backed up. Changes are disabled to protect the original file. Check the file permissions and available disk space, then restart the application.")
                    LOG.exception("Could not preserve unreadable DVR schedule")
                return
            seen, valid_jobs, invalid = set(), [], False
            for job in jobs:
                if not _valid_stored_job(job) or str(job['id']) in seen:
                    invalid = True
                else:
                    seen.add(str(job['id']))
                    valid_jobs.append(job)
            if invalid:
                try:
                    backup = self._preserve_corrupt_schedule()
                    self.load_warning = _("The recording schedule could not be read. The original file was preserved at {path}. Check your scheduled recordings before adding new ones.").format(path=backup)
                except OSError as exc:
                    self._load_error = exc
                    self.load_warning = _("The recording schedule could not be read or backed up. Changes are disabled to protect the original file. Check the file permissions and available disk space, then restart the application.")
            interrupted = []
            for job in valid_jobs:
                if job.get("status") in {STATUS_RECORDING, STATUS_STOPPING}:
                    # The ffmpeg process died with the app, so the job is no longer
                    # running whatever the file says. Re-arm it when its window is
                    # still open (tick() restarts it, or marks it missed once the
                    # stop time passes); only call it failed when the window has
                    # already closed and there is nothing left to record.
                    job["recording_id"] = None
                    stop_ts = _number(job.get("stop_ts"))
                    if stop_ts and float(self.clock()) >= stop_ts:
                        job["status"] = STATUS_FAILED
                        if job.get("repeat") in TIME_REPEATS:
                            interrupted.append(job)
                        job["message"] = job.get("message") or "Interrupted by application restart."
                    else:
                        job["status"] = STATUS_SCHEDULED
                        job["message"] = ""
                self._jobs[str(job["id"])] = job
            for job in interrupted:
                try:
                    self._schedule_next_occurrence(job)
                except (TypeError, KeyError, OSError, OverflowError, ValueError):
                    LOG.exception("Invalid interrupted recurring recording %s", job["id"])
                    self.load_warning = _("The recording times are invalid. Check the recording schedule.")
            self._revision += 1
        if interrupted:
            try:
                self.save()
            except OSError:
                self.load_warning = _("The recovered recording schedule could not be saved. Check the recording schedule and available disk space.")
                LOG.exception("Could not persist recovered recording schedule")

    def _preserve_corrupt_schedule(self):
        """Keep the exact bytes before allowing a new schedule to replace them."""
        backup = self.path + ".corrupt-" + uuid.uuid4().hex
        try:
            with open(self.path, "rb") as source, open(backup, "xb") as target:
                import shutil
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
        except OSError:
            try:
                os.remove(backup)
            except OSError:
                LOG.debug("Could not remove incomplete schedule backup", exc_info=True)
            raise
        return backup

    def save(self) -> None:
        self._transaction()

    def _writable_job(self, job_id):
        """Detach an entry before a real-time transition. Caller holds _lock."""
        key = str(job_id)
        job = self._jobs.get(key)
        if job is not None:
            job = self._jobs[key] = dict(job)
            self._revision += 1
        return job

    def _transaction(self, change=None):
        """Write and sync a private snapshot without blocking schedule readers.

        Start/stop transitions may overtake disk I/O. Re-evaluate the edit
        against their latest state before atomically replacing the file.
        """
        with self._save_lock:
            while True:
                with self._lock:
                    revision = self._revision
                    proposal = self._jobs.copy()
                result = change(proposal) if change else None
                if change and result is False:
                    return False
                temporary = self._write_proposal(proposal)
                try:
                    with self._lock:
                        if revision != self._revision:
                            continue
                        if temporary:
                            os.replace(temporary, self.path)
                            temporary = None
                        if change:
                            self._jobs = proposal
                            self._revision += 1
                        return result
                finally:
                    if temporary:
                        os.unlink(temporary)

    def _request_save(self):
        """Coalesce clock-triggered writes, leaving the scheduler free to tick."""
        with self._lock:
            self._save_requested = True
            if self._save_worker is not None:
                return
            self._save_worker = threading.Thread(target=self._drain_saves, name="dvr-save", daemon=True)
            self._save_worker.start()

    def _drain_saves(self):
        while True:
            with self._lock:
                if not self._save_requested:
                    self._save_worker = None
                    return
                self._save_requested = False
            self._save_schedule()

    def _save_schedule(self) -> None:
        """Write the schedule, reporting a failure instead of raising it.

        The schedule file is a convenience: the jobs live in memory and the
        app keeps working without it. A write that fails (a full disk, a
        locked file) must never change a job's state - a recording marked
        "failed" because the file could not be written is never stopped by the
        scheduler, and it holds the provider's one stream slot for good.
        """
        try:
            self.save()
        except Exception:
            LOG.exception("Could not save the DVR schedule: %s", self.path)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="DVRScheduler", daemon=True)
        self._thread.start()

    def stop(self, *, wait: bool = False) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if wait and self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if wait:
            with self._lock:
                writer = self._save_worker
            if writer is not None:
                writer.join(timeout=5)

    def wake(self) -> None:
        self._wake_event.set()

    def request_series_scan(self) -> None:
        self._last_series_scan = 0.0
        self.wake()

    def list_jobs(self, *, include_done: bool = True) -> List[Dict[str, object]]:
        with self._lock:
            jobs = list(self._jobs.values())
        if not include_done:
            jobs = [j for j in jobs if j.get("status") not in DONE_STATUSES]
        return sorted(jobs, key=lambda j: _number(j.get("start_ts")))

    def get_job(self, job_id: str) -> Optional[Dict[str, object]]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            return dict(job) if job else None

    def add_job(self, job: Dict[str, object], *, channel_key=None) -> Dict[str, object]:
        job = copy.deepcopy(job)
        if not job.get("id"):
            job["id"] = uuid.uuid4().hex
        def add(proposal):
            if str(job["id"]) in proposal:
                raise ValueError(_("This recording is already scheduled."))
            if channel_key is not None:
                if _number(job.get("stop_ts")) <= self.clock():
                    raise ValueError(_("This programme has already ended."))
                key = channel_key(job["channel"])
                if any(old.get("status") in ACTIVE_STATUSES and old.get("start_at") == job.get("start_at")
                       and old.get("end_at") == job.get("end_at") and channel_key(old.get("channel") or {}) == key
                       for old in proposal.values()):
                    raise ValueError(_("This recording is already scheduled."))
            proposal[str(job["id"])] = job

        self._transaction(add)
        if job.get("repeat") == "series":
            self._last_series_scan = 0.0
        self._notify_update()
        self.wake()
        return dict(job)

    def set_repeat(self, job_id: str, repeat: str, *, expected_window=None) -> bool:
        if repeat not in {"daily", "weekly", "series"}:
            return False
        def change(proposal):
            job = proposal.get(str(job_id))
            if not job or job.get("status") not in ACTIVE_STATUSES:
                return False
            if expected_window is not None and (job.get("start_ts"), job.get("stop_ts")) != expected_window:
                return False
            proposal[str(job_id)] = dict(job, repeat=repeat)
            return True
        if not self._transaction(change):
            return False
        if repeat == "series":
            self._last_series_scan = 0.0
        self._notify_update()
        self.wake()
        return True

    def set_weekdays(self, job_id, weekdays):
        from planning_tools import checked_weekdays
        days = checked_weekdays(weekdays)
        def change(proposal):
            job = proposal.get(str(job_id))
            if not job or job.get("status") != STATUS_SCHEDULED or job.get("repeat") == "series":
                raise ValueError(_("Select one pending recording that is not a series rule."))
            proposal[str(job_id)] = dict(job, repeat="weekdays" if days else "", weekdays=days)
        self._transaction(change)
        self._notify_update()
        self.wake()

    def _write_proposal(self, proposal):
        """Prepare a complete durable file. The transaction owns its final rename."""
        if self._load_error is not None:
            raise OSError(self.load_warning) from self._load_error
        if not self.path:
            return
        import tempfile
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="schedule-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "jobs": sorted(proposal.values(), key=lambda j: _number(j.get("start_ts")))},
                          handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            return temporary
        except BaseException:
            os.unlink(temporary)
            raise

    def add_manual_job(self, job):
        """Durable, duplicate-safe insertion for the manual scheduling dialog."""
        import manual_schedule
        import programme_reminders
        manual_schedule.validate_window(job["start_ts"], job["stop_ts"], now=self.clock())
        def add(proposal):
            manual_schedule.validate_window(job["start_ts"], job["stop_ts"], now=self.clock())
            key = programme_reminders.channel_key(job.get("channel"))
            if job["id"] in proposal or any(
                    old.get("status") in ACTIVE_STATUSES
                    and programme_reminders.channel_key(old.get("channel")) == key
                    and old.get("start_ts") == job["start_ts"] and old.get("stop_ts") == job["stop_ts"]
                    for old in proposal.values()):
                raise ValueError(_("This recording is already scheduled."))
            proposal[job["id"]] = copy.deepcopy(job)
        self._transaction(add)
        self._notify_update()
        self.wake()

    def edit_timing(self, job_id, start, end, *, expected, weekdays=None):
        """Edit one pending/running occurrence, refusing stale or finishing jobs."""
        import manual_schedule
        def edit(proposal):
            old = proposal.get(str(job_id))
            if (old is None or old.get("status") not in {STATUS_SCHEDULED, STATUS_RECORDING}
                    or tuple(old.get(k) for k in ("start_ts", "stop_ts", "status")) != tuple(expected)):
                raise ValueError(_("The recording changed. Reopen its timing dialog."))
            running = old["status"] == STATUS_RECORDING
            if running and start != old["start_ts"]:
                raise ValueError(_("A running recording's start time cannot be changed."))
            manual_schedule.validate_window(start, end, now=self.clock(), allow_started=running)
            updated = copy.deepcopy(old)
            updated.update(start_ts=start, stop_ts=end, start_at=iso_from_ts(start), end_at=iso_from_ts(end),
                           pre_padding_minutes=0, post_padding_minutes=0)
            updated["program"] = dict(updated.get("program") or {},
                start=datetime.datetime.fromtimestamp(start, datetime.timezone.utc).strftime("%Y%m%d%H%M%S"),
                end=datetime.datetime.fromtimestamp(end, datetime.timezone.utc).strftime("%Y%m%d%H%M%S"))
            if weekdays is not None:
                from planning_tools import checked_weekdays
                if running or old.get('repeat') == 'series':
                    raise ValueError(_("Select one pending recording that is not a series rule."))
                days = checked_weekdays(weekdays)
                updated.update(repeat='weekdays' if days else '', weekdays=days)
            proposal[str(job_id)] = updated
            return updated
        updated = self._transaction(edit)
        self._notify_update()
        self.wake()
        return copy.deepcopy(updated)

    def cancel_job(self, job_id: str) -> bool:
        def cancel(proposal):
            job = proposal.get(str(job_id))
            if not job:
                return False
            proposal[str(job_id)] = dict(job, status=STATUS_CANCELED, message="Canceled by user.")
            if job.get("repeat") == "series":
                for key, child in list(proposal.items()):
                    if child.get("series_source") == str(job_id) and child.get("status") == STATUS_SCHEDULED:
                        proposal[key] = dict(child, status=STATUS_CANCELED, message="Series recording canceled.")
            return True
        if not self._transaction(cancel):
            return False
        self._notify_update()
        self.wake()
        return True

    def delete_job(self, job_id: str) -> bool:
        def delete(proposal):
            removed = proposal.pop(str(job_id), None)
            if removed and removed.get("repeat") == "series":
                for child_id, child in list(proposal.items()):
                    if child.get("series_source") == str(job_id) and child.get("status") == STATUS_SCHEDULED:
                        del proposal[child_id]
            return removed is not None
        existed = self._transaction(delete)
        if existed:
            self._notify_update()
            self.wake()
        return existed

    def skip_occurrence(self, job_id, *, expected_start):
        """Skip exactly one pending time-based occurrence in one durable edit."""
        def skip(proposal):
            job = proposal.get(str(job_id))
            if (not job or job.get("status") != STATUS_SCHEDULED or job.get("repeat") not in TIME_REPEATS
                    or job.get("start_ts") != expected_start):
                raise ValueError(_("Select one pending recurring recording."))
            successor = self._next_occurrence(job)
            proposal[str(job_id)] = dict(job, status=STATUS_SKIPPED, message="")
            return proposal.setdefault(successor["id"], successor)
        next_job = self._transaction(skip)
        self._notify_update()
        self.wake()
        return dict(next_job)

    def mark_finished(
        self,
        job_id: str,
        *,
        success: bool,
        output_path: str = "",
        message: str = "",
        outcome: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._stopping_since.pop(str(job_id), None)
            job = self._writable_job(job_id)
            if not job:
                return
            job["recording_id"] = None
            if output_path:
                job["output_path"] = output_path
            if job.get("status") in DONE_STATUSES and job.get("status") != STATUS_CANCELED:
                return
            # A canceled job's recording ending afterwards keeps it canceled,
            # with the user's reason, instead of turning it "completed".
            if job.get("status") != STATUS_CANCELED:
                job["status"] = (outcome if outcome in {STATUS_PARTIAL, STATUS_STOPPED}
                                 else STATUS_COMPLETED if success else STATUS_FAILED)
                job["message"] = message
                self._schedule_next_occurrence(job)
        self._save_schedule()
        self._notify_update()

    def tick(self) -> None:
        now = float(self.clock())
        for job in self.list_jobs(include_done=False):
            status = job.get("status")
            job_id = str(job.get("id") or "")
            start_ts = _number(job.get("start_ts"))
            stop_ts = _number(job.get("stop_ts"))
            if status == STATUS_SCHEDULED:
                if stop_ts and now >= stop_ts:
                    self._set_status(job_id, STATUS_MISSED, "Scheduled recording was missed.",
                                     expected_window=(start_ts, stop_ts, status))
                elif now >= start_ts:
                    self._start_job(job_id, due=True)
            elif status == STATUS_RECORDING and stop_ts and now >= stop_ts:
                self._stop_job(job_id, due=True)
            elif status == STATUS_STOPPING:
                since = self._stopping_since.get(job_id)
                if since and now - since > STOP_TIMEOUT_SECONDS:
                    self.mark_finished(job_id, success=False, message="Stop timed out.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
                now = float(self.clock())
                if self.on_series and now - self._last_series_scan >= 3600:
                    self._last_series_scan = now
                    self._start_series_scan()
            except Exception:
                LOG.exception("DVR scheduler tick failed")
            self._wake_event.wait(self.poll_seconds)
            self._wake_event.clear()

    def _start_series_scan(self) -> None:
        """Run the hourly series scan off the scheduler thread.

        The scan matches every series rule against the guide, and that takes
        seconds on a full guide. The scheduler cannot tick while it runs, so a
        recording that comes due in the meantime starts late - and one whose
        window passes while the scan runs is marked as missed and never
        recorded at all.
        """
        running = self._series_scan_thread
        if running is not None and running.is_alive():
            return

        def scan():
            try:
                self.on_series()
            except Exception:
                LOG.exception("DVR series scan failed")

        self._series_scan_thread = threading.Thread(target=scan, name="dvr-series-scan", daemon=True)
        self._series_scan_thread.start()

    def _start_job(self, job_id: str, *, due=False) -> None:
        with self._lock:
            job = self._writable_job(job_id)
            if not job or job.get("status") != STATUS_SCHEDULED:
                return
            if due and not _number(job.get("start_ts")) <= self.clock() < _number(job.get("stop_ts")):
                return
            job["status"] = STATUS_RECORDING
            job["message"] = ""
        self._request_save()
        self._notify_update()
        # Starting a recording resolves the stream URL, classifies the media
        # and probes its audio tracks, which takes seconds. On the scheduler
        # thread that stopped the tick: a job that came due started late, and
        # one whose whole window passed was marked missed and never recorded.
        # The job is claimed above, so the next tick cannot start it twice.
        threading.Thread(target=self._start_job_worker, args=(job_id, dict(job)),
                         name="dvr-start", daemon=True).start()

    def _start_job_worker(self, job_id: str, job: Dict[str, object]) -> None:
        try:
            recording = self.on_start(job)
            rec_id = getattr(recording, "id", recording)
            out_path = getattr(recording, "out_path", "")
            with self._lock:
                current = self._writable_job(job_id)
                if current:
                    current["recording_id"] = rec_id
                    if out_path:
                        current["output_path"] = out_path
                # on_start can take many seconds (it probes the stream's audio
                # tracks first). A cancel or delete in that window found no
                # recording to stop, so this one must be stopped now or it
                # runs forever: the scheduler never stops a canceled job.
                abandoned = not current or current.get("status") != STATUS_RECORDING
                snapshot = dict(current) if current else dict(job, recording_id=rec_id)
        except Exception as err:
            LOG.exception("Scheduled recording failed to start")
            with self._lock:
                current = self._writable_job(job_id)
                if current and current.get("status") != STATUS_CANCELED:
                    # A job the user canceled while it was starting stays
                    # canceled: it must not come back as "failed", and no new
                    # occurrence may be queued for it.
                    current["status"] = STATUS_FAILED
                    current["recording_id"] = None
                    current["message"] = str(err)
                    self._schedule_next_occurrence(current)
            self._save_schedule()
            self._notify_update()
            return
        # The recording is running. A schedule that cannot be written must not
        # turn it into a failed job: the scheduler would never stop it, and it
        # would hold the provider's one stream slot for good.
        if abandoned:
            LOG.info("Scheduled recording %s was canceled while starting; stopping it", job_id)
            try:
                self.on_stop(snapshot)
            except Exception:
                LOG.exception("Could not stop a recording canceled while starting")
        self._save_schedule()
        self._notify_update()

    def _stop_job(self, job_id: str, *, due=False) -> None:
        with self._lock:
            job = self._writable_job(job_id)
            if not job or job.get("status") != STATUS_RECORDING:
                return
            if due and self.clock() < _number(job.get("stop_ts")):
                return  # the user extended it after tick took its snapshot
            job["status"] = STATUS_STOPPING
            job["message"] = "Stopping at scheduled end time."
            self._stopping_since[job_id] = float(self.clock())
        self._request_save()
        self._notify_update()
        try:
            self.on_stop(dict(job))
        except Exception as err:
            LOG.exception("Scheduled recording failed to stop")
            self.mark_finished(job_id, success=False, message=str(err))

    def _set_status(self, job_id: str, status: str, message: str = "", *, expected_window=None) -> None:
        with self._lock:
            job = self._writable_job(job_id)
            if not job:
                return
            if expected_window is not None and tuple(job.get(k) for k in
                    ("start_ts", "stop_ts", "status")) != expected_window:
                return
            job["status"] = status
            job["message"] = message
            if status in {STATUS_MISSED, STATUS_FAILED}:
                self._schedule_next_occurrence(job)
        self._request_save()
        self._notify_update()

    def _schedule_next_occurrence(self, job: Dict[str, object]) -> None:
        if job.get("repeat") not in TIME_REPEATS:
            return
        successor = self._next_occurrence(job)
        self._jobs.setdefault(successor["id"], successor)

    def _next_occurrence(self, job):
        from planning_tools import next_weekday_job
        repeat = job["repeat"]
        if repeat == "daily":
            days = list(range(7))
        elif repeat == "weekly":
            start = float(job["start_ts"]) + _number(job.get("pre_padding_minutes")) * 60
            days = [datetime.datetime.fromtimestamp(start).weekday()]
        else:
            days = job["weekdays"]
        successor = next_weekday_job(job, float(self.clock()), weekdays=days)
        # Stable even if the process exits before the restored state reaches disk.
        successor["id"] = uuid.uuid5(uuid.NAMESPACE_URL, "iptv-dvr:" + str(job["id"])).hex
        return successor

    def _notify_update(self) -> None:
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                LOG.exception("DVR update callback failed")
