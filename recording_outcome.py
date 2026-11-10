"""Conservative, GUI-independent classification of completed captures."""
import math
import os


def classify(rec, returncode, *, exiting=False, planned_seconds=None):
    try:
        produced = os.path.getsize(rec.out_path) > 0
    except OSError:
        produced = False
    if not produced:
        return "failed"
    if exiting or getattr(rec, "finalize_timed_out", False) or getattr(rec, "detached", False):
        return "partial"
    reason = getattr(rec, "stop_reason", "")
    if reason == "storage":
        return "partial"
    if getattr(rec, "stopped_by_user", False) and reason != "scheduled":
        return "stopped"
    if returncode != 0:
        return "partial"
    expected = planned_seconds if planned_seconds is not None else getattr(rec, "planned_seconds", None)
    written = getattr(rec, "media_written_seconds", None)
    if written is None:
        started, ended = getattr(rec, "started_at", None), getattr(rec, "ended_at", None)
        if type(started) in (int, float) and type(ended) in (int, float):
            written = max(0, ended - started)
    if (isinstance(expected, (int, float)) and isinstance(written, (int, float))
            and math.isfinite(expected) and math.isfinite(written) and expected > 0
            and written + max(5.0, min(30.0, expected * 0.02)) < expected):
        return "partial"
    return "completed"
