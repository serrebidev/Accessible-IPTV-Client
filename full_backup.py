"""Encrypted settings plus planning data, restored before background services start.

A private pending file is a redo journal: after a crash startup finishes the same
transaction before it can launch a scheduler. Paths always come from the app,
never from the imported document. Legacy backups replace settings only.
"""
import base64
import copy
import json
import os
import re
import tempfile
import time

from cryptography.fernet import InvalidToken
import dvr
import programme_reminders as reminders
import saved_searches
import settings_backup
from i18n import gettext as _

LIMIT = 16 * 1024 * 1024
FORMAT = "accessible-iptv-settings-v2"


def sync_directory(path):
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix="restore-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    if os.path.getsize(path) > LIMIT:
        raise ValueError(_("Backup file is too large."))
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def validate(bundle, *, now=None):
    now = time.time() if now is None else now
    bad = _("Backup settings are invalid.")
    if not isinstance(bundle, dict) or set(bundle) - {"config", "jobs", "reminders", "search_seen"}:
        raise ValueError(bad)
    data = copy.deepcopy(bundle)
    config = data.get("config")
    if (not isinstance(config, dict) or not isinstance(config.get("playlists"), list)
            or not isinstance(config.get("epgs"), list)):
        raise ValueError(bad)
    if set(data) not in ({"config"}, {"config", "jobs", "reminders", "search_seen"}):
        raise ValueError(bad)
    if "jobs" not in data:
        return data
    jobs = data["jobs"]
    if not isinstance(jobs, list) or len(jobs) > 10000:
        raise ValueError(bad)
    ids = set()
    for job in jobs:
        if (not isinstance(job, dict) or not isinstance(job.get("id"), str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", job["id"]) or job["id"] in ids
                or job.get("status") not in dvr.ACTIVE_STATUSES | dvr.DONE_STATUSES
                or not reminders.valid_time(job.get("start_ts"))
                or not reminders.valid_time(job.get("stop_ts"))
                or job["stop_ts"] <= job["start_ts"]
                or not isinstance(job.get("channel"), dict)
                or not isinstance(job.get("program"), dict)
                or not isinstance(job.get("format"), str)):
            raise ValueError(bad)
        ids.add(job["id"])
        if (job["status"] in {dvr.STATUS_RECORDING, dvr.STATUS_STOPPING}
                or job["status"] == dvr.STATUS_SCHEDULED and job["start_ts"] <= now):
            job.update(status=dvr.STATUS_MISSED, message="")
        job["recording_id"] = None
    rows = data["reminders"]
    if not isinstance(rows, list) or len(rows) > reminders.MAX_REMINDERS or len(reminders.normalize(rows)) != len(rows):
        raise ValueError(bad)
    data["reminders"] = reminders.normalize(rows)
    for row in data["reminders"]:
        if row["end"] <= now and row["status"] in {"scheduled", "ready"}:
            row["status"] = "expired"
    data["search_seen"] = saved_searches.normalize_seen(data["search_seen"], now=now)
    return data


def export_bundle(path, bundle, password):
    # Validate without changing live job states in the backup. Sanitization is
    # for import; an export is an honest snapshot, including what was running.
    validate(bundle)
    salt = os.urandom(16)
    payload = json.dumps(bundle, ensure_ascii=False, allow_nan=False).encode("utf-8")
    envelope = {"format": FORMAT, "salt": base64.b64encode(salt).decode("ascii"),
                "data": settings_backup._cipher(password, salt).encrypt(payload).decode("ascii")}
    if len(json.dumps(envelope).encode()) > LIMIT:
        raise ValueError(_("Settings are too large to back up."))
    atomic_json(path, envelope)


def import_bundle(path, password):
    envelope = read_json(path)
    if isinstance(envelope, dict) and envelope.get("format") == "accessible-iptv-settings-v1":
        return validate({"config": settings_backup.import_settings(path, password)})
    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT:
        raise ValueError(_("Not an Accessible IPTV settings backup."))
    try:
        salt = base64.b64decode(envelope["salt"], validate=True)
        if len(salt) != 16:
            raise ValueError("salt")
        bundle = json.loads(settings_backup._cipher(password, salt).decrypt(envelope["data"].encode("ascii")))
    except (InvalidToken, KeyError, TypeError, AttributeError, UnicodeError, ValueError) as exc:
        raise ValueError(_("Wrong password or damaged backup.")) from exc
    return validate(bundle)


def paths():
    import options
    directory = os.path.dirname(options.get_dvr_schedule_path())
    return {"config": options.get_config_write_target(), "jobs": options.get_dvr_schedule_path(),
            "reminders": os.path.join(directory, "programme-reminders.json"),
            "search_seen": os.path.join(directory, "programme-search-state.json")}


def pending_path(targets):
    return os.path.join(os.path.dirname(targets["jobs"]), "pending-restore.json")


def stage_restore(bundle, targets):
    checked = validate(bundle)
    if len(json.dumps(checked).encode()) > LIMIT:
        raise ValueError(_("Backup file is too large."))
    atomic_json(pending_path(targets), checked)


def apply_pending(targets=None):
    targets = paths() if targets is None else targets
    pending = pending_path(targets)
    if not os.path.exists(pending):
        return False
    bundle = validate(read_json(pending))
    for key, value in bundle.items():
        if key == "jobs":
            value = {"version": 1, "jobs": value}
        elif key == "reminders":
            value = {"version": 1, "reminders": value}
        atomic_json(targets[key], value)
    os.unlink(pending)
    sync_directory(os.path.dirname(os.path.abspath(pending)))
    return True
