"""Persistent DVR scheduling for Accessible IPTV Client.

The scheduler is GUI-free. It owns durable schedule entries and calls supplied
callbacks when a recording should start or stop. The GUI decides how to resolve a
stored channel snapshot into a playable URL and how to notify the user.
"""

from __future__ import annotations

import datetime
import copy
import json
import logging
import os
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

LOG = logging.getLogger(__name__)

STATUS_SCHEDULED = "scheduled"
STATUS_RECORDING = "recording"
STATUS_STOPPING = "stopping"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_MISSED = "missed"
STATUS_CANCELED = "canceled"

ACTIVE_STATUSES = {STATUS_SCHEDULED, STATUS_RECORDING, STATUS_STOPPING}
DONE_STATUSES = {STATUS_COMPLETED, STATUS_FAILED, STATUS_MISSED, STATUS_CANCELED}

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
        return float(value)
    except (TypeError, ValueError):
        return default


def program_title(program: Dict[str, str]) -> str:
    return (
        program.get("show_title")
        or program.get("title")
        or program.get("program")
        or "Untitled Program"
    )


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
    start_dt = parse_epg_utc(program.get("start", ""))
    end_dt = parse_epg_utc(program.get("end", ""))
    if end_dt <= start_dt:
        raise ValueError("Program end time must be after the start time.")

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
        self._jobs: Dict[str, Dict[str, object]] = {}
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._stopping_since: Dict[str, float] = {}
        self._thread: Optional[threading.Thread] = None
        self._last_series_scan = 0.0
        self._series_scan_thread: Optional[threading.Thread] = None
        self.load()

    def load(self) -> None:
        with self._lock:
            self._jobs = {}
            if not self.path or not os.path.exists(self.path):
                return
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                LOG.exception("Failed to load DVR schedule: %s", self.path)
                return
            jobs = data.get("jobs") if isinstance(data, dict) else data
            if not isinstance(jobs, list):
                return
            for job in jobs:
                if not isinstance(job, dict) or not job.get("id"):
                    continue
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
                        job["message"] = job.get("message") or "Interrupted by application restart."
                    else:
                        job["status"] = STATUS_SCHEDULED
                        job["message"] = ""
                self._jobs[str(job["id"])] = job

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._save_lock:
            with self._lock:
                # Serialize while holding the lock: the job dicts are live and
                # another thread may be changing them.
                jobs = sorted(self._jobs.values(), key=lambda j: _number(j.get("start_ts")))
                text = json.dumps({"version": 1, "jobs": jobs}, indent=2, sort_keys=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)

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

    def add_job(self, job: Dict[str, object]) -> Dict[str, object]:
        if not job.get("id"):
            job["id"] = uuid.uuid4().hex
        with self._lock:
            self._jobs[str(job["id"])] = dict(job)
            if job.get("repeat") == "series":
                self._last_series_scan = 0.0
        self.save()
        self._notify_update()
        self.wake()
        return dict(job)

    def set_repeat(self, job_id: str, repeat: str) -> bool:
        if repeat not in {"daily", "weekly", "series"}:
            return False
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                return False
            job["repeat"] = repeat
            if repeat == "series":
                self._last_series_scan = 0.0
        self.save()
        self._notify_update()
        self.wake()
        return True

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                return False
            job["status"] = STATUS_CANCELED
            job["message"] = "Canceled by user."
            if job.get("repeat") == "series":
                for child in self._jobs.values():
                    if child.get("series_source") == str(job_id) and child.get("status") == STATUS_SCHEDULED:
                        child["status"] = STATUS_CANCELED
                        child["message"] = "Series recording canceled."
        self.save()
        self._notify_update()
        self.wake()
        return True

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            removed = self._jobs.pop(str(job_id), None)
            existed = removed is not None
            if removed and removed.get("repeat") == "series":
                for child_id, child in list(self._jobs.items()):
                    if child.get("series_source") == str(job_id) and child.get("status") == STATUS_SCHEDULED:
                        del self._jobs[child_id]
        if existed:
            self.save()
            self._notify_update()
            self.wake()
        return existed

    def mark_finished(
        self,
        job_id: str,
        *,
        success: bool,
        output_path: str = "",
        message: str = "",
    ) -> None:
        with self._lock:
            self._stopping_since.pop(str(job_id), None)
            job = self._jobs.get(str(job_id))
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
                job["status"] = STATUS_COMPLETED if success else STATUS_FAILED
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
                    self._set_status(job_id, STATUS_MISSED, "Scheduled recording was missed.")
                elif now >= start_ts:
                    self._start_job(job_id)
            elif status == STATUS_RECORDING and stop_ts and now >= stop_ts:
                self._stop_job(job_id)
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

    def _start_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.get("status") != STATUS_SCHEDULED:
                return
            job["status"] = STATUS_RECORDING
            job["message"] = ""
        self._save_schedule()
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
                current = self._jobs.get(job_id)
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
                current = self._jobs.get(job_id)
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
        self._save_schedule()
        self._notify_update()
        if abandoned:
            LOG.info("Scheduled recording %s was canceled while starting; stopping it", job_id)
            try:
                self.on_stop(snapshot)
            except Exception:
                LOG.exception("Could not stop a recording canceled while starting")

    def _stop_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.get("status") != STATUS_RECORDING:
                return
            job["status"] = STATUS_STOPPING
            job["message"] = "Stopping at scheduled end time."
            self._stopping_since[job_id] = float(self.clock())
        self._save_schedule()
        self._notify_update()
        try:
            self.on_stop(dict(job))
        except Exception as err:
            LOG.exception("Scheduled recording failed to stop")
            self.mark_finished(job_id, success=False, message=str(err))

    def _set_status(self, job_id: str, status: str, message: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = status
            job["message"] = message
            if status in {STATUS_MISSED, STATUS_FAILED}:
                self._schedule_next_occurrence(job)
        self._save_schedule()
        self._notify_update()

    def _schedule_next_occurrence(self, job: Dict[str, object]) -> None:
        """Keep one future daily/weekly job when an occurrence has ended."""
        repeat = job.get("repeat")
        if repeat not in {"daily", "weekly"}:
            return
        days = 1 if repeat == "daily" else 7
        next_job = copy.deepcopy(job)
        next_job["id"] = uuid.uuid4().hex
        now = float(self.clock())
        for field in ("start_ts", "stop_ts"):
            next_job[field] = _number(job.get(field))
        while _number(next_job["stop_ts"]) <= now:
            for field in ("start_ts", "stop_ts"):
                local = datetime.datetime.fromtimestamp(_number(next_job[field]))
                next_job[field] = (local + datetime.timedelta(days=days)).timestamp()
        # A completed occurrence can finish before its planned stop; its next
        # occurrence still starts on the following day/week, never now.
        if _number(next_job["start_ts"]) <= _number(job.get("start_ts")):
            for field in ("start_ts", "stop_ts"):
                local = datetime.datetime.fromtimestamp(_number(next_job[field]))
                next_job[field] = (local + datetime.timedelta(days=days)).timestamp()
        next_job["start_at"] = iso_from_ts(_number(next_job["start_ts"]) + 60 * int(_number(job.get("pre_padding_minutes"))))
        next_job["end_at"] = iso_from_ts(_number(next_job["stop_ts"]) - 60 * int(_number(job.get("post_padding_minutes"))))
        next_job.update(status=STATUS_SCHEDULED, recording_id=None, output_path="",
                        message="", created_at=iso_from_ts(now))
        self._jobs[str(next_job["id"])] = next_job

    def _notify_update(self) -> None:
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                LOG.exception("DVR update callback failed")
