import os
import platform
import shutil
import subprocess
import json
import socket
import threading
import time
import tempfile
import uuid
from typing import Optional, Tuple

from i18n import gettext as _
import logging

try:
    from mpv_subtitle_adapter import MpvSubtitleAdapter
except Exception:  # pragma: no cover - adapter is optional at runtime
    MpvSubtitleAdapter = None

LOG = logging.getLogger(__name__)


class ExternalPlayerLauncher:
    def __init__(self):
        self._launch_guard_lock = threading.Lock()
        self._last_launch_ts = 0.0
        self._last_launch_key = None
        self._mpv_adapter = None
        # Counts the launches: a worker that belongs to an older launch must
        # not start playback after a newer one has been asked for.
        self._launch_generation = 0
        # This session's mpv pipe. A fixed name was machine-wide: any local
        # process could connect to it and drive, or watch, the session.
        self._mpv_ipc_endpoint = self._new_mpv_ipc_path()

    def launch(
        self,
        player_name: str,
        url: str,
        custom_path: str = "",
        subtitle_manager=None,
        subtitle_state_cb=None,
        subtitle_session=None,
        expected_generation=None,
        playback_result_cb=None,
    ) -> Tuple[bool, str]:
        """
        Launches the specified external player with the given URL.
        Returns (accepted, error_message). For asynchronous MPV launches,
        acceptance only schedules work. ``playback_result_cb(ok, error)``
        reports process creation/ownership, not successful media decoding.
        Owned MPV results are marshalled through the session UI dispatcher.
        Synchronous failures are returned; synchronous success also notifies
        the callback. Debounced/obsolete requests do not notify again.

        When ``subtitle_manager`` is given and the player is MPV, the launch
        goes through the application-owned MPV session adapter (issue #37) so
        subtitle text can be spoken. If the adapter cannot be established,
        the launch falls back to the plain handoff and speech is reported
        unavailable; playback itself is never blocked.
        """
        # Guard against accidental double-invocation of the same stream.
        with self._launch_guard_lock:
            if expected_generation is not None and expected_generation != self._launch_generation:
                return True, ""  # a fallback from an obsolete worker
            # A monotonic clock: the wall clock can step backwards (a manual
            # change, an NTP step, a VM restore), and a negative delta would
            # leave the debounce permanently open - the player would refuse to
            # start at all until the app was restarted.
            now = time.monotonic()
            # Same stream in the same player only: switching players is a new playback.
            key = (player_name, custom_path, url)
            if (now - self._last_launch_ts) < 0.75 and self._last_launch_key == key:
                return True, "" # Debounced
            self._last_launch_ts = now
            self._last_launch_key = key
            # Every launch supersedes the one before it.
            self._launch_generation += 1
            generation = self._launch_generation

        resolved = self._resolve_player_name(player_name, custom_path)
        token = None
        if subtitle_session is not None:
            # This is deliberately after the duplicate-launch guard. A second
            # Enter must not revoke the adapter for the still-playing stream.
            if resolved == "MPV":
                token = subtitle_session.activate_session("mpv-ipc")
                subtitle_manager = subtitle_session.bind(token)
                state_callback = subtitle_state_cb
                subtitle_state_cb = lambda state: subtitle_session.dispatch(
                    token, state_callback, state) if state_callback else None
            else:
                subtitle_session.cancel_session(stop_playback=True)
            # The controller now owns retirement of the previous adapter.
            self._mpv_adapter = None
        else:
            self.close_subtitle_adapter()

        # MPV with subtitle speech: use our own session adapter.
        if subtitle_manager is not None and MpvSubtitleAdapter is not None:
            if resolved == "MPV":
                # The adapter's handshake (connect + version) takes as long as
                # MPV answers, and it used to run on the GUI thread: pressing
                # Enter on a channel froze the window - and silenced the
                # screen reader - for the whole handshake. The launch happens on
                # a worker now; the plain handoff is its fallback, so
                # playback is never blocked.
                try:
                    self._launch_mpv_subtitled_async(url, subtitle_manager,
                                                    subtitle_state_cb, custom_path if player_name == "Custom" else "",
                                                    player_name, generation, subtitle_session, token,
                                                    playback_result_cb)
                except Exception as exc:
                    LOG.warning("could not start MPV launch worker", exc_info=True)
                    with self._launch_guard_lock:
                        if generation == self._launch_generation:
                            self._last_launch_key = None
                            self._last_launch_ts = 0.0
                    return False, str(exc)
                return True, ""

        # The application-owned MPV is playing the previous channel: another
        # player would play over it, and the old stream would keep running.
        self.close_subtitle_adapter()

        # If using mpv, try to reuse an existing instance via IPC first.
        if player_name == "MPV":
            if self._mpv_try_send(url):
                self._notify_playback_result(playback_result_cb, True, "", generation)
                return True, ""

        win_paths = {
            "VLC": [r"C:\\Program Files\\VideoLAN\\VLC\\vlc.exe", r"C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe"],
            "MPC": [r"C:\\Program Files\\MPC-HC\\mpc-hc64.exe", r"C:\\Program Files (x86)\\K-Lite Codec Pack\\MPC-HC64\\mpc-hc64.exe", r"C:\\Program Files (x86)\\MPC-HC\\mpc-hc.exe"],
            "MPC-BE": [r"C:\\Program Files\\MPC-BE\\mpc-be64.exe", r"C:\\Program Files (x86)\\MPC-BE\\mpc-be.exe", r"C:\\Program Files\\MPC-BE x64\\mpc-be64.exe", r"C:\\Program Files\\MPC-BE\\mpc-be.exe"],
            "Kodi": [r"C:\\Program Files\\Kodi\\kodi.exe"],
            "Winamp": [r"C:\\Program Files\\Winamp\\winamp.exe"],
            "Foobar2000": [r"C:\\Program Files\\foobar2000\\foobar2000.exe"],
            "MPV": [r"C:\\Program Files\\mpv\\mpv.exe", r"C:\\Program Files (x86)\\mpv\\mpv.exe"],
            "SMPlayer": [r"C:\\Program Files\\SMPlayer\\smplayer.exe", r"C:\\Program Files (x86)\\SMPlayer\\smplayer.exe"],
            "QuickTime": [r"C:\\Program Files\\QuickTime\\QuickTimePlayer.exe", r"C:\\Program Files (x86)\\QuickTime\\QuickTimePlayer.exe"],
            "iTunes/Apple Music": [r"C:\\Program Files\\iTunes\\iTunes.exe", r"C:\\Program Files (x86)\\iTunes\\iTunes.exe", r"C:\\Program Files\\Apple\\Music\\AppleMusic.exe"],
            "PotPlayer": [r"C:\\Program Files\\DAUM\\PotPlayer\\PotPlayerMini64.exe", r"C:\\Program Files\\DAUM\\PotPlayer\\PotPlayerMini.exe"],
            "KMPlayer": [r"C:\\Program Files\\KMP Media\\KMPlayer\\KMPlayer64.exe", r"C:\\Program Files (x86)\\KMP Media\\KMPlayer\\KMPlayer.exe"],
            "AIMP": [r"C:\\Program Files\\AIMP\\AIMP.exe", r"C:\\Program Files (x86)\\AIMP\\AIMP.exe"],
            "QMPlay2": [r"C:\\Program Files\\QMPlay2\\QMPlay2.exe", r"C:\\Program Files (x86)\\QMPlay2\\QMPlay2.exe"],
            "GOM Player": [r"C:\\Program Files\\GRETECH\\GomPlayer\\GOM.exe", r"C:\\Program Files (x86)\\GRETECH\\GomPlayer\\GOM.exe"],
            "Clementine": [r"C:\\Program Files\\Clementine\\clementine.exe"],
            "Strawberry": [r"C:\\Program Files\\Strawberry\\strawberry.exe"],
        }
        
        linux_players = { "VLC": "vlc", "MPV": "mpv", "Kodi": "kodi", "SMPlayer": "smplayer", "Totem": "totem", "PotPlayer": "potplayer", "KMPlayer": "kmplayer", "AIMP": "aimp", "QMPlay2": "qmplay2", "GOM Player": "gomplayer", "Audacious": "audacious", "Fauxdacious": "fauxdacious", "MPC-BE": "mpc-be", "Clementine": "clementine", "Strawberry": "strawberry", "Amarok": "amarok", "Rhythmbox": "rhythmbox", "Pragha": "pragha", "Lollypop": "lollypop", "Exaile": "exaile", "Quod Libet": "quodlibet", "Gmusicbrowser": "gmusicbrowser", "Xmms": "xmms", "Vocal": "vocal", "Haruna": "haruna", "Celluloid": "celluloid" }
        mac_paths = { "VLC": ["/Applications/VLC.app/Contents/MacOS/VLC"], "QuickTime": ["/Applications/QuickTime Player.app/Contents/MacOS/QuickTime Player"], "iTunes/Apple Music": ["/Applications/Music.app/Contents/MacOS/Music", "/Applications/iTunes.app/Contents/MacOS/iTunes"], "QMPlay2": ["/Applications/QMPlay2.app/Contents/MacOS/QMPlay2"], "Audacious": ["/Applications/Audacious.app/Contents/MacOS/Audacious"], "Fauxdacious": ["/Applications/Fauxdacious.app/Contents/MacOS/Fauxdacious"] }

        ok, err = False, ""

        if player_name == "Custom" and custom_path:
            exe = custom_path
            # Heuristically detect known players from custom path for better flags
            pname = os.path.basename(exe).lower()
            detected = player_name
            if "mpv" in pname:
                detected = "MPV"
            elif "vlc" in pname:
                detected = "VLC"
            elif "mpc-be" in pname or "mpcbe" in pname:
                detected = "MPC-BE"
            elif pname.startswith("mpc-hc") or pname.startswith("mpc"):
                detected = "MPC"
            argv = self._argv_for(detected, exe, platform.system() == "Windows", url)
            ok, err = self._spawn_windows(argv) if platform.system() == "Windows" else self._spawn_posix(argv)
        else:
            system = platform.system()
            if system == "Windows":
                choices = win_paths.get(player_name, [])
                for exe in choices:
                    if os.path.exists(exe):
                        argv = self._argv_for(player_name, exe, True, url)
                        ok, err = self._spawn_windows(argv)
                        if ok: break
                if not ok: err = err or _("Could not locate {player} executable.").format(player=player_name)
            elif system == "Darwin":
                choices = mac_paths.get(player_name, [])
                for exe in choices:
                    if os.path.exists(exe):
                        argv = self._argv_for(player_name, exe, False, url)
                        ok, err = self._spawn_posix(argv)
                        if ok: break
                if not ok: err = err or _("Could not locate {player} app.").format(player=player_name)
            else:
                cmd = linux_players.get(player_name)
                if cmd:
                    argv = self._argv_for(player_name, cmd, False, url)
                    ok, err = self._spawn_posix(argv)
                else: err = _("{player} is not configured for Linux.").format(player=player_name)
        
        if ok:
            self._notify_playback_result(playback_result_cb, True, "", generation)
        return ok, err

    def _notify_playback_result(self, callback, ok, error, generation, session=None, token=None):
        """Deliver only for the request that still owns playback.

        A callback exception is not a process-launch failure and must never
        trigger another player or fallback.
        """
        def deliver():
            with self._launch_guard_lock:
                if generation != self._launch_generation:
                    return
            if callback is not None:
                try:
                    callback(ok, error)
                except Exception:
                    LOG.exception("playback result callback failed")
        if session is not None:
            session.dispatch(token, deliver)
        else:
            deliver()

    @staticmethod
    def _resolve_player_name(player_name: str, custom_path: str = "") -> str:
        """Map a launch request (including Custom paths) to a known player."""
        if player_name == "Custom" and custom_path:
            pname = os.path.basename(custom_path).lower()
            if "mpv" in pname:
                return "MPV"
            if "vlc" in pname:
                return "VLC"
            if "mpc-be" in pname or "mpcbe" in pname:
                return "MPC-BE"
            if pname.startswith("mpc-hc") or pname.startswith("mpc"):
                return "MPC"
        return player_name

    def _find_mpv_exe(self, custom_path: str = ""):
        """Locate the MPV executable.

        Resolution order: validated custom path, shutil.which("mpv"),
        then known installation locations.
        """
        # 1. Validated custom path first.
        if custom_path:
            return custom_path if os.path.isfile(custom_path) else None
        # 2. PATH lookup on all platforms.
        found = shutil.which("mpv")
        if found:
            return found
        # 3. Known installation locations.
        system = platform.system()
        if system == "Windows":
            for exe in (r"C:\\Program Files\\mpv\\mpv.exe",
                        r"C:\\Program Files (x86)\\mpv\\mpv.exe"):
                if os.path.exists(exe):
                    return exe
            return None
        if system == "Darwin":
            return None  # no bundled macOS path known; keep honest
        return None

    def _launch_mpv_subtitled_async(self, url, manager, state_cb=None,
                                    custom_path: str = "", player_name: str = "MPV",
                                    generation: int = 0, subtitle_session=None, token=None,
                                    playback_result_cb=None) -> None:
        """Start MPV behind the subtitle adapter on a worker thread.

        The caller returns as soon as the player is asked to start; the
        adapter's handshake and, if it cannot attach, the plain MPV handoff
        happen here.
        """

        def worker():
            with self._launch_guard_lock:
                if generation != self._launch_generation:
                    return
            if subtitle_session is not None and not subtitle_session.is_current(token):
                return
            error = ""
            try:
                if self._launch_mpv_subtitled(url, manager, state_cb, custom_path,
                                              generation, subtitle_session, token):
                    self._notify_playback_result(
                        playback_result_cb, True, "", generation, subtitle_session, token)
                    return
            except Exception as exc:
                error = str(exc)
                LOG.warning("MPV playback launch failed", exc_info=True)
            if subtitle_session is not None:
                with self._launch_guard_lock:
                    if generation != self._launch_generation:
                        return
                    # A failed request must be retryable immediately.
                    self._last_launch_ts = 0.0
                    self._last_launch_key = None
                self._notify_playback_result(
                    playback_result_cb, False, error or _("No error details were reported."),
                    generation, subtitle_session, token)
                if playback_result_cb is None and state_cb:
                    state_cb("playback_failed")
                return
            # The adapter could not be attached. The plain handoff is the
            # fallback - unless a newer launch has been asked for since, which
            # would start the old channel over the new one.
            with self._launch_guard_lock:
                if generation != self._launch_generation:
                    LOG.info("MPV adapter launch superseded; no plain handoff")
                    return
                # The launch that queued this worker already used the
                # debounce, so the fallback has to be allowed through.
                self._last_launch_ts = 0.0
                self._last_launch_key = None
            try:
                ok, fallback_error = self.launch(
                    player_name, url, custom_path, expected_generation=generation,
                    playback_result_cb=playback_result_cb)
                if not ok:
                    self._notify_playback_result(
                        playback_result_cb, False, fallback_error or error, generation + 1)
            except Exception as exc:
                LOG.warning("MPV plain handoff failed", exc_info=True)
                self._notify_playback_result(playback_result_cb, False, str(exc), generation + 1)

        threading.Thread(target=worker, name="mpv-adapter-launch", daemon=True).start()

    def _launch_mpv_subtitled(self, url, manager, state_cb=None, custom_path: str = "",
                               generation: Optional[int] = None, subtitle_session=None, token=None) -> bool:
        """Launch our own MPV behind the subtitle-text session adapter."""
        exe = self._find_mpv_exe(custom_path)
        if not exe:
            LOG.info("MPV subtitle adapter: mpv executable not found")
            raise RuntimeError(_("Could not locate {player} executable.").format(player="MPV"))
        try:
            adapter = MpvSubtitleAdapter.launch(exe, url, manager, state_cb)
        except Exception:
            LOG.warning("MPV subtitle adapter: launch failed", exc_info=True)
            adapter = None
        if adapter is None:
            with self._launch_guard_lock:
                if generation is not None and generation != self._launch_generation:
                    return False
            if subtitle_session is not None and not subtitle_session.is_current(token):
                return False
            if subtitle_session is None:
                return False
            adapter = MpvSubtitleAdapter.launch_playback_only(exe, url, manager, state_cb)
            if adapter is None:
                raise RuntimeError(_("No error details were reported."))
        with self._launch_guard_lock:
            superseded = generation is not None and generation != self._launch_generation
            if not superseded:
                self._mpv_adapter = adapter
        if superseded:
            # A newer launch was asked for while this one was starting: this
            # MPV would play the old channel over it.
            LOG.info("MPV adapter launch superseded; stopping it")
            try:
                adapter.close()
            except Exception:
                LOG.debug("close of a superseded MPV adapter failed", exc_info=True)
            return False
        if subtitle_session is not None:
            return subtitle_session.set_adapter(adapter, token)
        return True

    def close_subtitle_adapter(self) -> None:
        """Retire an adapter owned by standalone launcher callers, off the UI."""
        adapter, self._mpv_adapter = self._mpv_adapter, None
        if adapter is not None:
            try:
                adapter.cancel()
                threading.Thread(target=adapter.close, name="mpv-cleanup", daemon=True).start()
            except Exception:
                LOG.debug("close_subtitle_adapter failed", exc_info=True)

    @property
    def mpv_subtitle_active(self) -> bool:
        adapter = self._mpv_adapter
        return bool(adapter is not None and adapter.available)

    def _argv_for(self, player_name: str, exe_or_cmd: str, is_windows: bool, url: str) -> list:
        # Build argv with best-effort single-instance/enqueue flags where supported.
        if player_name == "VLC":
            # Use single-instance flags, but do NOT enqueue so the new stream replaces playback.
            flags = ["--one-instance", "--one-instance-when-started-from-file"]
            return [exe_or_cmd, *flags, url]
        if player_name in ("MPC", "MPC-BE"):
            # Keep it simple and robust: let MPC's own single-instance setting
            # handle reuse; always pass the URL directly for predictable playback.
            return [exe_or_cmd, url]
        if player_name == "MPV":
            ipc = self._mpv_ipc_path()
            flags = [f"--input-ipc-server={ipc}", "--force-window=yes", "--idle=yes", "--no-terminal"]
            # On POSIX, if the IPC socket path exists but connect failed above, it's likely stale; try to remove it.
            if not is_windows and os.path.exists(ipc):
                try:
                    os.unlink(ipc)
                except Exception:
                    LOG.debug("ExternalPlayerLauncher._argv_for: ignored exception", exc_info=True)
            return [exe_or_cmd, *flags, url]
        # Default: just pass URL
        return [exe_or_cmd, url]

    def _spawn_posix(self, argv):
        try:
            subprocess.Popen(argv, close_fds=True)
            return True, ""
        except FileNotFoundError:
            return False, _("Executable not found: {path}").format(path=argv[0])
        except Exception as e:
            return False, str(e)

    def _spawn_windows(self, argv):
        """Launch player on Windows with a normal, visible window."""
        try:
            subprocess.Popen(argv)
            return True, ""
        except FileNotFoundError:
            return False, _("Executable not found: {path}").format(path=argv[0])
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _new_mpv_ipc_path() -> str:
        """A pipe name that belongs to this session only.

        The subtitle adapter builds its own endpoint the same way; this one is
        for the plain MPV handoff, which is a separate mpv process.
        """
        token = uuid.uuid4().hex[:8]
        if platform.system() == "Windows":
            return r"\\.\pipe\iptvclient-mpv-" + token
        return os.path.join(tempfile.gettempdir(), f"iptvclient-mpv-{token}.sock")

    def _mpv_ipc_path(self) -> str:
        return self._mpv_ipc_endpoint

    def _mpv_try_send(self, url: str) -> bool:
        """If an mpv instance with our IPC is running, send loadfile and return True."""
        ipc = self._mpv_ipc_path()
        payload = (json.dumps({"command": ["loadfile", url, "replace"]}) + "\n").encode("utf-8")
        if platform.system() == "Windows":
            try:
                # Minimal win32 named pipe client via ctypes
                from ctypes import wintypes
                import ctypes
                GENERIC_WRITE = 0x40000000
                OPEN_EXISTING = 3
                INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
                CreateFileW = ctypes.windll.kernel32.CreateFileW
                CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
                CreateFileW.restype = wintypes.HANDLE
                h = CreateFileW(ipc, GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
                if h == 0 or h == INVALID_HANDLE_VALUE:
                    return False
                try:
                    WriteFile = ctypes.windll.kernel32.WriteFile
                    WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
                    written = wintypes.DWORD(0)
                    ok = WriteFile(h, payload, len(payload), ctypes.byref(written), None)
                    return bool(ok and written.value == len(payload))
                finally:
                    ctypes.windll.kernel32.CloseHandle(h)
            except Exception:
                return False
        else:
            s = None
            try:
                # AF_UNIX only exists off Windows; this branch is the non-Windows one.
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # pyright: ignore[reportAttributeAccessIssue]
                s.settimeout(0.25)
                s.connect(ipc)
                s.sendall(payload)
                return True
            except Exception:
                return False
            finally:
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        LOG.debug("mpv IPC socket close failed", exc_info=True)
