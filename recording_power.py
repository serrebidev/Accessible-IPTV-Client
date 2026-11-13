"""Optional Windows recording power requests, owned by one dedicated thread.

No display/away-mode requests and no changes to the user's power plan.
Wake timers need the app to remain open and a system that permits waking.
"""
import ctypes
import math
import sys
import threading
import time

from i18n import gettext as _


def supported():
    return sys.platform == "win32"


def desired_state(config, active, jobs, now):
    wake = config.get("wake_for_recordings") is True
    starts = [job.get("start_ts") for job in jobs if job.get("status") == "scheduled"]
    starts = [float(value) for value in starts if type(value) in (int, float) and math.isfinite(value)
              and now - 15 <= value <= now + 366 * 86400]
    next_start = min(starts) if starts and wake else None
    # Stay awake between the early wake and the scheduler's next tick.
    imminent = next_start is not None and next_start - now <= 90
    keep_awake = (config.get("prevent_sleep_while_recording", True) is True and active) or imminent
    alarm = max(now + 1, next_start - 60) if next_start is not None and next_start - now > 60 else None
    return bool(keep_awake), alarm


class WindowsBackend:
    def __init__(self):
        from ctypes import wintypes
        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self.dll.SetThreadExecutionState.argtypes = [wintypes.DWORD]
        self.dll.SetThreadExecutionState.restype = wintypes.DWORD
        self.dll.CreateWaitableTimerW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.dll.CreateWaitableTimerW.restype = wintypes.HANDLE
        self.dll.SetWaitableTimer.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong), wintypes.LONG,
                                             ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL]
        self.dll.SetWaitableTimer.restype = wintypes.BOOL
        for name in ("CancelWaitableTimer", "CloseHandle"):
            function = getattr(self.dll, name)
            function.argtypes = [wintypes.HANDLE]
            function.restype = wintypes.BOOL
        self.timer = None
        self.awake = False
        self.alarm = None

    def update(self, awake, alarm):
        if awake != self.awake:
            if not self.dll.SetThreadExecutionState(0x80000000 | (1 if awake else 0)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.awake = awake
        if alarm == self.alarm:
            return
        if self.timer is not None:
            if not self.dll.CancelWaitableTimer(self.timer):
                raise ctypes.WinError(ctypes.get_last_error())
            self.alarm = None
        if alarm is None:
            return
        if self.timer is None:
            self.timer = self.dll.CreateWaitableTimerW(None, True, None)
            if not self.timer:
                self.timer = None
                raise ctypes.WinError(ctypes.get_last_error())
        due = ctypes.c_longlong(round((alarm + 11644473600) * 10_000_000))
        ctypes.set_last_error(0)
        accepted = self.dll.SetWaitableTimer(self.timer, ctypes.byref(due), 0, None, None, True)
        error = ctypes.get_last_error()
        if not accepted or error == 50:  # ERROR_NOT_SUPPORTED can accompany success.
            self.dll.CancelWaitableTimer(self.timer)
            raise OSError(_("Windows could not enable the recording wake timer."))
        self.alarm = alarm

    def close(self):
        if self.awake:
            self.dll.SetThreadExecutionState(0x80000000)
            self.awake = False
        if self.timer is not None:
            self.dll.CancelWaitableTimer(self.timer)
            self.dll.CloseHandle(self.timer)
            self.timer = None
        self.alarm = None


class RecordingPower:
    def __init__(self, snapshot, on_error, *, backend_factory=WindowsBackend, clock=time.time):
        self.snapshot = snapshot
        self.on_error = on_error
        self.backend_factory = backend_factory
        self.clock = clock
        self.stopping = threading.Event()
        self.changed = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name="RecordingPower")
            self.thread.start()

    def refresh(self):
        self.changed.set()

    def close(self):
        self.stopping.set()
        self.changed.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def _run(self):
        backend = None
        reported = False
        try:
            backend = self.backend_factory()
            while not self.stopping.is_set():
                self.changed.clear()
                try:
                    config, active, jobs = self.snapshot()
                    backend.update(*desired_state(config, active, jobs, self.clock()))
                    reported = False
                except Exception as error:
                    if not reported:
                        self.on_error(error)
                        reported = True
                self.changed.wait(5)
        except Exception as error:
            self.on_error(error)
        finally:
            if backend is not None:
                backend.close()
