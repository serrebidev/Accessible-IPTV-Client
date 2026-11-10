"""Periodic recording-space checks, grouped by destination filesystem."""
import os
import shutil

MIB = 1024 * 1024


def settings(config):
    def number(key, default):
        value = config.get(key)
        return value if type(value) is int and 16 <= value <= 1048576 else default
    critical = number("recording_stop_free_mib", 256)
    warning = max(critical, number("recording_warn_free_mib", 1024))
    return (config.get("recording_monitor_space", True) is not False,
            warning, critical, config.get("recording_stop_low_space", False) is True)


class SpaceMonitor:
    def __init__(self):
        self.notified = {}

    def check(self, recordings, preferences, notify, stop):
        enabled, warning, critical, auto_stop = preferences
        if not enabled:
            self.notified.clear()
            return
        groups = {}
        for rec in recordings:
            directory = os.path.dirname(os.path.abspath(rec.written_path))
            try:
                key = (os.stat(directory).st_dev, os.path.splitdrive(directory)[0].casefold())
            except OSError:
                key = (None, directory)
            groups.setdefault(key, (directory, []))[1].append(rec)
        self.notified = {key: value for key, value in self.notified.items() if key in groups}
        for key, (directory, rows) in groups.items():
            try:
                free = shutil.disk_usage(directory).free
                if type(free) is not int or free < 0:
                    raise OSError("Invalid free-space response")
            except OSError:
                if self.notified.get(key) != "unavailable":
                    self.notified[key] = "unavailable"
                    notify("unavailable", directory, 0, len(rows))
                continue
            state = "stopping" if auto_stop and free < critical * MIB else "warning" if free < warning * MIB else "ok"
            if state == "ok":
                if free >= warning * MIB * 1.1 or self.notified.get(key) == "unavailable":
                    self.notified.pop(key, None)
                continue
            if state == "stopping":
                for rec in rows:
                    if not rec.stopping:
                        stop(rec.id)
            if self.notified.get(key) != state:
                self.notified[key] = state
                notify(state, directory, free // MIB, len(rows))
