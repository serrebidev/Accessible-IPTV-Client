"""Periodic recording-space checks, grouped by destination filesystem."""
import os
import shutil
import threading
import time

MIB = 1024 * 1024
POLL_SECONDS = 5
MAX_PROBES = 64


def settings(config):
    def number(key, default):
        value = config.get(key)
        return value if type(value) is int and 16 <= value <= 1048576 else default
    critical = number("recording_stop_free_mib", 256)
    warning = max(critical, number("recording_warn_free_mib", 1024))
    return (config.get("recording_monitor_space", True) is not False,
            warning, critical, config.get("recording_stop_low_space", False) is True)


def _measure(directory):
    try:
        key = (os.stat(directory).st_dev, os.path.splitdrive(directory)[0].casefold())
    except OSError:
        key = (None, directory)
    try:
        free = shutil.disk_usage(directory).free
        if type(free) is not int or free < 0:
            raise OSError("Invalid free-space response")
    except OSError:
        return key, None
    return key, free


class SpaceMonitor:
    def __init__(self):
        self.notified = {}
        self._lock = threading.Lock()
        self._pending = {}
        self._next_probe = {}
        self.ready = threading.Event()

    def _start_probe(self, directory):
        def probe():
            try:
                result = _measure(directory)
            except Exception:
                result = (None, directory), None
            with self._lock:
                if self._pending.get(directory) is marker:
                    self._pending[directory] = result
                    self.ready.set()

        marker = object()
        self._pending[directory] = marker
        try:
            threading.Thread(target=probe, name="Recording disk space", daemon=True).start()
        except RuntimeError:
            self._pending[directory] = ((None, directory), None)

    def check(self, recordings, preferences, notify, stop, *, background=False):
        enabled, warning, critical, auto_stop = preferences
        if not enabled:
            self.notified.clear()
            self.ready.clear()
            return
        destinations = {}
        for rec in recordings:
            directory = os.path.dirname(os.path.abspath(rec.written_path))
            destinations.setdefault(directory, []).append(rec)

        if background:
            measurements = {}
            now = time.monotonic()
            with self._lock:
                self.ready.clear()
                for directory, probe in tuple(self._pending.items()):
                    if directory not in destinations and isinstance(probe, tuple):
                        del self._pending[directory]
                        self._next_probe.pop(directory, None)
                for directory in destinations:
                    probe = self._pending.get(directory)
                    deadline = self._next_probe.get(directory, 0)
                    if isinstance(probe, tuple) and now <= deadline + POLL_SECONDS:
                        measurements[directory] = probe
                    if (probe is None and len(self._pending) < MAX_PROBES
                            or isinstance(probe, tuple) and now >= deadline):
                        self._next_probe[directory] = now + POLL_SECONDS
                        self._start_probe(directory)
        else:
            measurements = {directory: _measure(directory) for directory in destinations}

        groups = {}
        for directory, (key, free) in measurements.items():
            if key not in groups:
                groups[key] = directory, free, []
            _, previous, rows = groups[key]
            if previous is None or free is not None and free < previous:
                groups[key] = directory, free, rows
            rows.extend(destinations[directory])
        if len(measurements) == len(destinations):
            self.notified = {key: value for key, value in self.notified.items() if key in groups}

        for key, (directory, free, rows) in groups.items():
            if free is None:
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
