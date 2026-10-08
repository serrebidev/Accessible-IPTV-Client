"""Application-owned MPV session adapter for subtitle text (issue #37).

Boundaries, as agreed on the issue:
- Launch or adopt only an explicitly identified MPV instance: we spawn MPV
  ourselves with a per-session IPC endpoint and keep the process handle. We
  never attach to the fixed shared endpoint, which could belong to another
  instance or an earlier run.
- One persistent read/write connection with JSON IPC request IDs. Property
  observations live on that connection; closing it drops them, so it stays
  open for the session.
- Missing, empty, null and disconnected are treated as different states.
- Cues are keyed on generation, track, start time and text; the queue is
  cleared on stop, source switch and track change.
- If the adapter drops, MPV keeps playing and the app reports speech as
  unavailable. Adapter failure must never interrupt playback.

Only text subtitles with real words are surfaced: MPV documents ``sub-text``
as empty for bitmap subtitles, so those stay honestly unreported.
"""

import json
import logging
import os
import platform
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Callable, Dict, Optional

LOG = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"

# Timeouts / pacing.
CONNECT_TIMEOUT_S = 5.0
CONNECT_POLL_S = 0.1
READ_POLL_S = 0.05
REQUEST_TIMEOUT_S = 4.0

# observe_property ids.
_OBS_SUB_TEXT = 2
_OBS_SUB_START = 3
_OBS_SUB_END = 4
_OBS_SID = 5

# mpv-version floor we have exercised against. Older is not refused, just noted.
_MIN_TESTED_MPV = (0, 37, 0)


def _session_endpoint() -> str:
    """A per-session IPC endpoint that cannot collide with other instances."""
    token = uuid.uuid4().hex[:8]
    if _IS_WINDOWS:
        return r"\\.\pipe\iptvclient-mpv-" + token
    return os.path.join(tempfile.gettempdir(), f"iptvclient-mpv-{token}.sock")


class _Transport:
    """Persistent read/write IPC transport. Never raises out of read/write."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._sock = None
        self._pipe = None
        self._buffer = b""

    # -- connect ---------------------------------------------------------

    def connect(self) -> bool:
        deadline = time.monotonic() + CONNECT_TIMEOUT_S
        while time.monotonic() < deadline and not self._stop.is_set():
            try:
                if _IS_WINDOWS:
                    if self._connect_pipe():
                        return True
                elif self._connect_socket():
                    return True
            except Exception:
                LOG.debug("mpv adapter: connect attempt failed", exc_info=True)
            time.sleep(CONNECT_POLL_S)
        return False

    if _IS_WINDOWS:

        def _connect_pipe(self) -> bool:  # noqa: F811 - windows only
            import ctypes
            from ctypes import wintypes

            GENERIC_READ = 0x80000000
            GENERIC_WRITE = 0x40000000
            OPEN_EXISTING = 3
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateFileW.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                wintypes.HANDLE,
            ]
            kernel32.CreateFileW.restype = wintypes.HANDLE
            handle = kernel32.CreateFileW(
                self.endpoint, GENERIC_READ | GENERIC_WRITE,
                0, None, OPEN_EXISTING, 0, None,
            )
            if not handle or handle == wintypes.HANDLE(-1).value:
                return False
            self._pipe = (ctypes, handle)
            return True

    def _connect_socket(self) -> bool:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(CONNECT_POLL_S)
            s.connect(self.endpoint)
            s.settimeout(None)
            self._sock = s
            return True
        except OSError:
            return False

    # -- write ------------------------------------------------------------

    def write_line(self, line: bytes) -> bool:
        try:
            with self._write_lock:
                if self._stop.is_set():
                    return False
                if _IS_WINDOWS:
                    return self._write_pipe(line)
                if self._sock is None:
                    return False
                self._sock.sendall(line)
                return True
        except Exception:
            LOG.debug("mpv adapter: write failed", exc_info=True)
            return False

    if _IS_WINDOWS:

        def _write_pipe(self, line: bytes) -> bool:  # noqa: F811 - windows only
            ctypes, handle = self._pipe
            from ctypes import wintypes

            written = wintypes.DWORD(0)
            ok = ctypes.windll.kernel32.WriteFile(
                handle, line, len(line), ctypes.byref(written), None)
            return bool(ok and written.value == len(line))

    # -- read --------------------------------------------------------------

    def read_line(self) -> Optional[bytes]:
        """One newline-terminated message, or None on stop/error/empty poll."""
        try:
            while not self._stop.is_set():
                if b"\n" in self._buffer:
                    line, self._buffer = self._buffer.split(b"\n", 1)
                    return line
                chunk = self._read_chunk()
                if chunk is None:
                    return None
                if chunk:
                    self._buffer += chunk
            return None
        except Exception:
            LOG.debug("mpv adapter: read failed", exc_info=True)
            return None

    def _read_chunk(self):
        if _IS_WINDOWS:
            return self._read_pipe_chunk()
        return self._read_socket_chunk()

    def _read_socket_chunk(self):
        import select

        if self._sock is None:
            return None
        ready, _, _ = select.select([self._sock], [], [], READ_POLL_S)
        if not ready:
            return b""
        try:
            data = self._sock.recv(65536)
        except OSError:
            return None
        return data if data else None  # None: peer closed

    if _IS_WINDOWS:

        def _read_pipe_chunk(self):  # noqa: F811 - windows only
            import ctypes
            from ctypes import wintypes

            ctypes_mod, handle = self._pipe
            kernel32 = ctypes_mod.windll.kernel32
            avail = wintypes.DWORD(0)
            if not kernel32.PeekNamedPipe(
                    handle, None, 0, None, ctypes.byref(avail), None):
                return None
            if avail.value == 0:
                time.sleep(READ_POLL_S)
                return b""
            buf = ctypes.create_string_buffer(min(avail.value, 65536))
            read = wintypes.DWORD(0)
            ok = kernel32.ReadFile(
                handle, buf, len(buf) - 1, ctypes.byref(read), None)
            if not ok or read.value == 0:
                return None
            return buf.raw[:read.value]

    # -- close ---------------------------------------------------------------

    def close(self) -> None:
        self._stop.set()
        with self._write_lock:
            if _IS_WINDOWS and self._pipe:
                try:
                    ctypes_mod, handle = self._pipe
                    ctypes_mod.windll.kernel32.CloseHandle(handle)
                except Exception:
                    LOG.debug("mpv adapter: CloseHandle failed", exc_info=True)
                self._pipe = None
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    LOG.debug("mpv adapter: socket close failed", exc_info=True)
                self._sock = None


class MpvSubtitleAdapter:
    """Owns one MPV process and surfaces its subtitle text as cue events.

    Use :meth:`launch`; if it returns None the adapter could not be
    established and the caller should fall back to the plain handoff.
    """

    def __init__(self, manager, on_state_change: Optional[Callable[[str], None]] = None):
        self._manager = manager
        self._on_state_change = on_state_change
        self._transport: Optional[_Transport] = None
        self._process: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._request_id = 0
        self._pending: Dict[int, dict] = {}
        self._pending_lock = threading.Lock()
        self._generation = 0
        self._sub_text = None
        self._sub_start = None
        self._sub_end = None
        self._sid = None
        self._mpv_version = ""
        self._first_cue_sent = False
        self.available = False

    # -- launch ---------------------------------------------------------------

    @classmethod
    def launch(
        cls,
        mpv_exe: str,
        url: str,
        manager,
        on_state_change: Optional[Callable[[str], None]] = None,
        extra_args: Optional[list] = None,
    ) -> "Optional[MpvSubtitleAdapter]":
        """Spawn our own MPV with a per-session endpoint and attach to it."""
        self = cls(manager, on_state_change)
        endpoint = _session_endpoint()
        argv = [
            mpv_exe,
            f"--input-ipc-server={endpoint}",
            "--force-window=yes",
            "--idle=yes",
            "--no-terminal",
            *(extra_args or []),
            url,
        ]
        try:
            # Clean a stale POSIX socket path before asking mpv to bind it.
            if not _IS_WINDOWS and os.path.exists(endpoint):
                try:
                    os.unlink(endpoint)
                except OSError:
                    LOG.debug("mpv adapter: stale socket unlink failed", exc_info=True)
            self._process = subprocess.Popen(argv)
        except Exception:
            LOG.warning("mpv adapter: could not launch %s", mpv_exe, exc_info=True)
            return None
        self._transport = _Transport(endpoint)
        if not self._transport.connect():
            LOG.warning("mpv adapter: IPC endpoint never appeared")
            self._shutdown_process()
            return None
        if not self._verify_version():
            LOG.warning("mpv adapter: version check failed")
            self.close()
            return None
        self._observe()
        self._manager.set_source("mpv-ipc")
        self._reader = threading.Thread(
            target=self._read_loop, name="mpv-ipc", daemon=True)
        self._reader.start()
        self.available = True
        self._report("available")
        return self

    def _verify_version(self) -> bool:
        resp = self._request(["get_property", "mpv-version"])
        if not resp or resp.get("error") != "success":
            return False
        self._mpv_version = str(resp.get("data") or "")
        try:
            parts = tuple(int(p) for p in self._mpv_version.split(".")[:3])
            if parts < _MIN_TESTED_MPV:
                LOG.info("mpv adapter: mpv %s older than tested %s",
                         self._mpv_version, ".".join(map(str, _MIN_TESTED_MPV)))
        except ValueError:
            LOG.debug("mpv adapter: unparseable version %r", self._mpv_version)
        return True

    def _observe(self) -> None:
        for obs_id, prop in ((_OBS_SUB_TEXT, "sub-text"),
                             (_OBS_SUB_START, "sub-start"),
                             (_OBS_SUB_END, "sub-end"),
                             (_OBS_SID, "sid")):
            self._send({"command": ["observe_property", obs_id, prop]})

    # -- protocol ----------------------------------------------------------------

    def _send(self, message: dict) -> bool:
        if self._transport is None:
            return False
        try:
            line = (json.dumps(message) + "\n").encode("utf-8")
        except (TypeError, ValueError):
            return False
        return self._transport.write_line(line)

    def _request(self, command: list, timeout: float = REQUEST_TIMEOUT_S) -> Optional[dict]:
        self._request_id += 1
        rid = self._request_id
        event = threading.Event()
        with self._pending_lock:
            self._pending[rid] = {"event": event, "response": None}
        try:
            if not self._send({"command": command, "request_id": rid}):
                return None
            # Requests are only answered while the reader loop pumps the
            # connection; during launch the loop is not running yet, so pump
            # a few messages inline here.
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                with self._pending_lock:
                    entry = self._pending.get(rid)
                if entry is None or entry["event"].is_set():
                    break
                line = self._transport.read_line() if self._transport else None
                if line:
                    self._dispatch(line)
                else:
                    time.sleep(READ_POLL_S)
            with self._pending_lock:
                entry = self._pending.pop(rid, None)
            if entry and entry["event"].is_set():
                return entry["response"]
            return None
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)

    def _read_loop(self) -> None:
        try:
            while not self._stop.is_set() and self._transport:
                line = self._transport.read_line()
                if line is None:
                    break
                if line.strip():
                    self._dispatch(line)
        except Exception:
            LOG.debug("mpv adapter: reader loop ended", exc_info=True)
        finally:
            self._on_disconnect()

    def _dispatch(self, line: bytes) -> None:
        try:
            msg = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        rid = msg.get("request_id")
        if rid is not None:
            with self._pending_lock:
                entry = self._pending.get(rid)
                if entry is not None:
                    entry["response"] = msg
                    entry["event"].set()
            return
        if msg.get("event") == "property-change":
            self._on_property_change(msg)
        elif msg.get("event") == "end-file":
            self._on_end_of_file(msg)

    # -- cue handling --------------------------------------------------------------

    def _on_property_change(self, msg: dict) -> None:
        pid = msg.get("id")
        data = msg.get("data")  # None: unavailable; "": no cue right now
        if pid == _OBS_SID:
            if data != self._sid:
                self._sid = data
                self._generation += 1
                self._manager.clear()
            return
        if pid == _OBS_SUB_TEXT:
            self._sub_text = data
            self._emit_cue_if_ready()
        elif pid == _OBS_SUB_START:
            self._sub_start = data
            self._emit_cue_if_ready()
        elif pid == _OBS_SUB_END:
            self._sub_end = data
            self._emit_cue_if_ready()

    def _emit_cue_if_ready(self) -> None:
        text = self._sub_text
        if not text:  # None (unavailable) or "" (nothing displayed)
            return
        try:
            start_ms = int(float(self._sub_start) * 1000) if self._sub_start is not None else None
        except (TypeError, ValueError):
            start_ms = None
        try:
            end_ms = int(float(self._sub_end) * 1000) if self._sub_end is not None else None
        except (TypeError, ValueError):
            end_ms = None
        track = "" if self._sid is None else str(self._sid)
        self._manager.on_cue(text, start_ms=start_ms, end_ms=end_ms,
                             source="mpv-ipc", track=track)
        if not self._first_cue_sent:
            self._first_cue_sent = True
            self._report("first_cue")

    def _on_end_of_file(self, _msg: dict) -> None:
        self._generation += 1
        self._manager.clear()

    def _on_disconnect(self) -> None:
        if self.available:
            self.available = False
            self._manager.clear()
            self._report("unavailable")

    def _report(self, state: str) -> None:
        if self._on_state_change:
            try:
                self._on_state_change(state)
            except Exception:
                LOG.debug("mpv adapter: state callback failed", exc_info=True)

    # -- lifecycle -------------------------------------------------------------------

    def close(self) -> None:
        """Drop the adapter. The MPV process we launched is terminated; a
        foreign MPV is never touched because we only ever track our own."""
        self._stop.set()
        self.available = False
        if self._transport:
            self._transport.close()
            self._transport = None
        self._shutdown_process()
        self._manager.clear()

    def _shutdown_process(self) -> None:
        proc, self._process = self._process, None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            LOG.debug("mpv adapter: process shutdown failed", exc_info=True)
