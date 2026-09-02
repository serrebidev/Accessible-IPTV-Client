"""Persistent DVR scheduling for Accessible IPTV Client.

The scheduler is GUI-free. It owns durable schedule entries and calls supplied
callbacks when a recording should start or stop. The GUI decides how to resolve a
stored channel snapshot into a playable URL and how to notify the user.
"""

from __future__ import annotations

import datetime
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
        clock: Callable[[], float] = utc_now_ts,
        poll_seconds: float = 15.0,
    ):
        self.path = path
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_update = on_update
        self.clock = clock
        self.poll_seconds = max(0.2, float(poll_seconds))
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, object]] = {}
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._stopping_since: Dict[str, float] = {}
        self._thread: Optional[threading.Thread] = None
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
                    stop_ts = float(job.get("stop_ts") or 0)
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
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: float(j.get("start_ts") or 0))
            payload = {"version": 1, "jobs": jobs}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

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

    def list_jobs(self, *, include_done: bool = True) -> List[Dict[str, object]]:
        with self._lock:
            jobs = list(self._jobs.values())
        if not include_done:
            jobs = [j for j in jobs if j.get("status") not in DONE_STATUSES]
        return sorted(jobs, key=lambda j: float(j.get("start_ts") or 0))

    def get_job(self, job_id: str) -> Optional[Dict[str, object]]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            return dict(job) if job else None

    def add_job(self, job: Dict[str, object]) -> Dict[str, object]:
        if not job.get("id"):
            job["id"] = uuid.uuid4().hex
        with self._lock:
            self._jobs[str(job["id"])] = dict(job)
        self.save()
        self._notify_update()
        self.wake()
        return dict(job)

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                return False
            job["status"] = STATUS_CANCELED
            job["message"] = "Canceled by user."
        self.save()
        self._notify_update()
        self.wake()
        return True

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            existed = self._jobs.pop(str(job_id), None) is not None
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
            job["status"] = STATUS_COMPLETED if success else STATUS_FAILED
            job["recording_id"] = None
            if output_path:
                job["output_path"] = output_path
            job["message"] = message
        self.save()
        self._notify_update()

    def tick(self) -> None:
        now = float(self.clock())
        for job in self.list_jobs(include_done=False):
            status = job.get("status")
            job_id = str(job.get("id") or "")
            start_ts = float(job.get("start_ts") or 0)
            stop_ts = float(job.get("stop_ts") or 0)
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
            except Exception:
                LOG.exception("DVR scheduler tick failed")
            self._wake_event.wait(self.poll_seconds)
            self._wake_event.clear()

    def _start_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.get("status") != STATUS_SCHEDULED:
                return
            job["status"] = STATUS_RECORDING
            job["message"] = ""
        self.save()
        self._notify_update()
        try:
            recording = self.on_start(dict(job))
            rec_id = getattr(recording, "id", recording)
            out_path = getattr(recording, "out_path", "")
            with self._lock:
                current = self._jobs.get(job_id)
                if current:
                    current["recording_id"] = rec_id
                    if out_path:
                        current["output_path"] = out_path
            self.save()
            self._notify_update()
        except Exception as err:
            LOG.exception("Scheduled recording failed to start")
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job["status"] = STATUS_FAILED
                    job["recording_id"] = None
                    job["message"] = str(err)
            self.save()
            self._notify_update()

    def _stop_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.get("status") != STATUS_RECORDING:
                return
            job["status"] = STATUS_STOPPING
            job["message"] = "Stopping at scheduled end time."
            self._stopping_since[job_id] = float(self.clock())
        self.save()
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
        self.save()
        self._notify_update()

    def _notify_update(self) -> None:
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                LOG.exception("DVR update callback failed")
