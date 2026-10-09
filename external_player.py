import os
import platform
import shutil
import subprocess
import json
import socket
import threading
import time
import tempfile
from typing import Tuple

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
        self._last_launch_url = ""
        self._mpv_adapter = None

    def launch(
        self,
        player_name: str,
        url: str,
        custom_path: str = "",
        subtitle_manager=None,
        subtitle_state_cb=None,
    ) -> Tuple[bool, str]:
        """
        Launches the specified external player with the given URL.
        Returns (success, error_message).

        When ``subtitle_manager`` is given and the player is MPV, the launch
        goes through the application-owned MPV session adapter (issue #37) so
        subtitle text can be spoken. If the adapter cannot be established,
        the launch falls back to the plain handoff and speech is reported
        unavailable; playback itself is never blocked.
        """
        # Guard against accidental double-invocation of the same stream.
        with self._launch_guard_lock:
            now = time.time()
            if (now - self._last_launch_ts) < 0.75 and self._last_launch_url == url:
                return True, "" # Debounced
            self._last_launch_ts = now
            self._last_launch_url = url

        # MPV with subtitle speech: use our own session adapter.
        if subtitle_manager is not None and MpvSubtitleAdapter is not None:
            resolved = self._resolve_player_name(player_name, custom_path)
            if resolved == "MPV":
                if self._launch_mpv_subtitled(url, subtitle_manager, subtitle_state_cb, custom_path):
                    return True, ""
                LOG.info("MPV subtitle adapter unavailable; plain handoff instead")

        # If using mpv, try to reuse an existing instance via IPC first.
        if player_name == "MPV":
            if self._mpv_try_send(url):
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
        
        return ok, err

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
        if custom_path and os.path.isfile(custom_path):
            return custom_path
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

    def _launch_mpv_subtitled(self, url, manager, state_cb=None, custom_path: str = "") -> bool:
        """Launch our own MPV behind the subtitle-text session adapter."""
        self.close_subtitle_adapter()
        exe = self._find_mpv_exe(custom_path)
        if not exe:
            LOG.info("MPV subtitle adapter: mpv executable not found")
            return False
        try:
            adapter = MpvSubtitleAdapter.launch(exe, url, manager, state_cb)
        except Exception:
            LOG.warning("MPV subtitle adapter: launch failed", exc_info=True)
            return False
        if adapter is None:
            return False
        self._mpv_adapter = adapter
        return True

    def close_subtitle_adapter(self) -> None:
        """Drop any active MPV subtitle session (its MPV keeps nothing)."""
        adapter, self._mpv_adapter = self._mpv_adapter, None
        if adapter is not None:
            try:
                adapter.close()
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

    def _mpv_ipc_path(self) -> str:
        if platform.system() == "Windows":
            return r"\\.\pipe\iptvclient-mpv"
        # POSIX: use a socket in temp
        return os.path.join(tempfile.gettempdir(), "iptvclient-mpv.sock")

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
