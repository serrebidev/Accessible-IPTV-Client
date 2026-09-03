"""Shutting the computer down when recording is finished.

GUI-free: the decision rule and the platform commands live here so both can be tested
headlessly, and the GUI keeps only the confirmation, the countdown and the cancel.

The rule is deliberately conservative. Shutting a machine down is not undoable, so
``should_shutdown`` refuses unless a recording has actually run since the option was
armed -- otherwise arming it on an idle evening would power the machine off at once --
and it waits for scheduled jobs as well as running ones, because "after my recordings
are done" means the whole queue, not just the capture in progress.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Iterable, List, Optional, Sequence

LOG = logging.getLogger(__name__)

# Statuses that mean a scheduled job still has work to do. Kept as literals rather than
# imported from dvr so this module stays free of app dependencies.
PENDING_JOB_STATUSES = frozenset({"scheduled", "recording", "stopping"})


def shutdown_commands(system: Optional[str] = None) -> List[List[str]]:
    """Candidate shutdown commands for a platform, best first.

    Windows is asked to shut down without ``/f``: forcing would close whatever else the
    user left open without letting it save. If something does block the shutdown,
    Windows tells the user which app it was, which beats losing their work.
    """
    name = (system or platform.system() or "").strip()
    if name == "Windows":
        return [["shutdown", "/s", "/t", "0"]]
    if name == "Darwin":
        return [["osascript", "-e", 'tell application "System Events" to shut down']]
    return [
        ["systemctl", "poweroff"],
        ["shutdown", "-h", "now"],
    ]


def shutdown_computer(system: Optional[str] = None, runner=None) -> List[str]:
    """Ask the OS to shut down. Returns the command that was accepted.

    Raises ``RuntimeError`` if every candidate failed, with what each one reported --
    the caller shows that to the user, who would otherwise just see nothing happen.
    """
    run = runner or _run
    failures: List[str] = []
    for cmd in shutdown_commands(system):
        try:
            run(cmd)
            LOG.info("Shutdown requested via %s", " ".join(cmd))
            return cmd
        except Exception as err:
            LOG.warning("Shutdown command failed (%s): %s", " ".join(cmd), err)
            failures.append("{cmd}: {err}".format(cmd=" ".join(cmd), err=err))
    raise RuntimeError("; ".join(failures) or "no shutdown command available")


def _run(cmd: Sequence[str]) -> None:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        list(cmd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "exit code {code}".format(code=completed.returncode))


def pending_job_count(jobs: Optional[Iterable[dict]]) -> int:
    """How many DVR jobs are still scheduled, recording or stopping."""
    if not jobs:
        return 0
    count = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if str(job.get("status") or "") in PENDING_JOB_STATUSES:
            count += 1
    return count


def should_shutdown(
    *,
    armed: bool,
    recorded_something: bool,
    active_recordings: int,
    pending_jobs: int,
) -> bool:
    """Whether the computer may be shut down right now."""
    if not armed or not recorded_something:
        return False
    return active_recordings <= 0 and pending_jobs <= 0
