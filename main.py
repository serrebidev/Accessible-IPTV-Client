import os
import sys
import shutil
import json
import tempfile
import urllib.request
import urllib.parse
import sqlite3
import threading
import logging
from typing import Dict, List, Optional, Tuple
import wx
import datetime
import re
import platform
import time
import subprocess
import hashlib
import concurrent.futures

# Child of the rotating-file "EPG" logger configured in playlist.py, so UI/search
# diagnostics land in the same log file and honor the same EPG_DEBUG switch.
LOG = logging.getLogger("EPG.ui")

import wx.adv

import i18n
from i18n import gettext as _

from options import (
    load_config, save_config, get_cache_path_for_url, get_cache_dir,
    get_db_path, utc_to_local,
    CustomPlayerDialog, resolve_internal_player_settings, get_app_dir,
    get_recordings_dir, get_dvr_schedule_path, normalize_recording_format,
    is_windows_installed_build
)
# Same normalization the EPG database indexes with - importing it from anywhere
# else is how the UI and the database drift apart.
from channel_names import canonicalize_name, strip_noise_words
import app_meta
import updater
from playlist import (
    EPGDatabase, EPGManagerDialog, PlaylistManagerDialog,
    epg_database_has_usable_data
)
from providers import (
    XtreamCodesClient, XtreamCodesConfig,
    StalkerPortalClient, StalkerPortalConfig,
    ProviderError, generate_provider_id
)
import vod
import account_info
from http_headers import channel_http_headers
from external_player import ExternalPlayerLauncher
import recorder
from recorder import RECORDING_FORMATS
import dvr

_INTERNAL_PLAYER_FRAME_CLASS = None
_INTERNAL_PLAYER_IMPORT_ATTEMPTED = False
_INTERNAL_PLAYER_IMPORT_ERROR = None


class InternalPlayerUnavailableError(RuntimeError):
    """Raised when the built-in VLC player cannot be loaded."""


def _load_internal_player_frame_class():
    global _INTERNAL_PLAYER_FRAME_CLASS
    global _INTERNAL_PLAYER_IMPORT_ATTEMPTED
    global _INTERNAL_PLAYER_IMPORT_ERROR

    if not _INTERNAL_PLAYER_IMPORT_ATTEMPTED:
        _INTERNAL_PLAYER_IMPORT_ATTEMPTED = True
        try:
            from internal_player import (  # type: ignore
                InternalPlayerFrame as frame_class,
                _VLC_IMPORT_ERROR as vlc_import_error,
            )
        except Exception as exc:  # pragma: no cover - import guard
            _INTERNAL_PLAYER_IMPORT_ERROR = exc
            _INTERNAL_PLAYER_FRAME_CLASS = None
        else:
            _INTERNAL_PLAYER_FRAME_CLASS = frame_class
            _INTERNAL_PLAYER_IMPORT_ERROR = vlc_import_error

    if _INTERNAL_PLAYER_FRAME_CLASS is None:
        detail = _INTERNAL_PLAYER_IMPORT_ERROR or _("Built-in player is unavailable.")
        raise InternalPlayerUnavailableError(str(detail))
    return _INTERNAL_PLAYER_FRAME_CLASS


_M3U_ATTR_RE = re.compile(r'([A-Za-z0-9_\-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^",\s]+))')


def _extinf_name_comma(line: str) -> int:
    """Index of the comma separating an #EXTINF's attributes from its name.

    The separator is the first comma *outside* a quoted attribute value. Real
    playlists ship values that contain commas — iptv-org, for one, emits
    http-user-agent="Mozilla/5.0 (... (KHTML, like Gecko) Chrome/145 ..." — and
    splitting on the first raw comma made the rest of the attribute list the
    channel name while truncating the attributes themselves, losing the
    channel's group and headers with it.

    Returns -1 when the line holds no comma, and falls back to the first raw
    comma when quoting is unbalanced, which is what a malformed line used to get.
    """
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in ('"', "'"):
            quote = char
        elif char == ",":
            return index
    return line.find(",")
_AUTO_UPDATE_CHECK_INTERVAL_SECONDS = 12 * 60 * 60
_AUTO_UPDATE_DELAY_AFTER_PLAYLIST_MS = 5000
_AUTO_UPDATE_HTTP_TIMEOUT_SECONDS = 5.0
_MANUAL_UPDATE_HTTP_TIMEOUT_SECONDS = 15.0

def set_linux_env():
    if platform.system() != "Linux":
        return

    os.environ["UBUNTU_MENUPROXY"] = "0"
    distro = "unknown"
    try:
        with open("/etc/os-release") as f:
            os_release = f.read().lower()
        if "ubuntu" in os_release:
            distro = "ubuntu"
        elif "debian" in os_release:
            distro = "debian"
        elif "arch" in os_release and "manjaro" not in os_release:
            distro = "arch"
        elif "manjaro" in os_release:
            distro = "manjaro"
        elif "fedora" in os_release:
            distro = "fedora"
        elif "centos" in os_release:
            distro = "centos"
        elif "rhel" in os_release or "red hat" in os_release:
            distro = "rhel"
        elif "opensuse" in os_release or "suse" in os_release:
            distro = "opensuse"
        elif "mint" in os_release:
            distro = "mint"
        elif "pop" in os_release and "pop_os" in os_release:
            distro = "popos"
    except Exception:
        LOG.debug("set_linux_env: ignored exception", exc_info=True)

    os.environ["MYAPP_DISTRO"] = distro

    if distro == "ubuntu":
        os.environ["UBUNTU_MENUPROXY"] = "0"
        os.environ["GTK_MODULES"] = os.environ.get("GTK_MODULES", "")
    elif distro == "debian":
        os.environ["GTK_OVERLAY_SCROLLING"] = "0"
    elif distro == "arch":
        os.environ["NO_AT_BRIDGE"] = "0"
    elif distro == "manjaro":
        os.environ["NO_AT_BRIDGE"] = "0"
    elif distro == "fedora":
        os.environ["GTK_USE_PORTAL"] = "1"
    elif distro == "centos":
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    elif distro == "rhel":
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    elif distro == "opensuse":
        os.environ["XDG_CURRENT_DESKTOP"] = os.environ.get("XDG_CURRENT_DESKTOP", "KDE")
    elif distro == "mint":
        os.environ["XDG_CURRENT_DESKTOP"] = os.environ.get("XDG_CURRENT_DESKTOP", "X-Cinnamon")
    elif distro == "popos":
        os.environ["GDK_BACKEND"] = os.environ.get("GDK_BACKEND", "x11")

def _lower_current_thread_priority():
    """Best-effort: drop the OS scheduling priority of the *calling* thread only.

    Used by the background EPG import worker so a long (tens-of-minutes) import
    competes less aggressively with the UI thread and other apps, without
    touching the whole process's priority class (which would also throttle the UI
    thread). Windows-only; a harmless no-op everywhere else or if the call fails.

    Uses THREAD_MODE_BACKGROUND_BEGIN rather than a plain CPU-priority drop: a
    multi-gigabyte EPG import is dominated by disk writes and page-cache churn,
    and CPU priority alone leaves the import free to saturate the disk and evict
    the UI's working set. Background mode lowers CPU, disk-I/O, *and* memory
    priority together, which is what actually keeps the interface (and NVDA)
    responsive while an import is running.
    """
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        from ctypes import wintypes
        THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
        THREAD_PRIORITY_LOWEST = -2
        kernel32 = ctypes.windll.kernel32
        # GetCurrentThread() returns a pseudo-HANDLE (pointer-sized). Without explicit
        # argtypes/restype, ctypes' default 32-bit c_int marshaling can mangle it on
        # 64-bit Python, silently turning this into a no-op.
        kernel32.GetCurrentThread.restype = wintypes.HANDLE
        kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        kernel32.SetThreadPriority.restype = wintypes.BOOL
        # THREAD_MODE_BACKGROUND_BEGIN is only valid on the current thread's
        # pseudo-handle, which is exactly how it is used here.
        if not kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_MODE_BACKGROUND_BEGIN):
            kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_LOWEST)
    except Exception:
        LOG.debug("_lower_current_thread_priority: ignored exception", exc_info=True)

class TrayIcon(wx.adv.TaskBarIcon):
    TBMENU_RESTORE = wx.NewIdRef()
    TBMENU_EXIT = wx.NewIdRef()
    TBMENU_PLAYER_SHOW = wx.NewIdRef()
    TBMENU_PLAYER_TOGGLE = wx.NewIdRef()
    TBMENU_PLAYER_STOP = wx.NewIdRef()
    TBMENU_CAST = wx.NewIdRef()
    TBMENU_RECORD_STOP = wx.NewIdRef()

    def __init__(self, parent, on_restore, on_exit, *, on_player_show=None, on_player_toggle=None, on_player_stop=None, on_cast=None, on_record_stop=None):
        super().__init__()
        self.parent = parent
        self.on_restore = on_restore
        self.on_exit = on_exit
        self.on_player_show = on_player_show
        self.on_player_toggle = on_player_toggle
        self.on_player_stop = on_player_stop
        self.on_cast = on_cast
        self.on_record_stop = on_record_stop
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_taskbar_activate)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, self.on_taskbar_activate)
        self.Bind(wx.EVT_MENU, self.on_menu_select)
        self.set_icon()

    def set_icon(self):
        icon = wx.Icon(wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_TOOLBAR, (16, 16)))
        self.SetIcon(icon, "Accessible IPTV Client")

    def CreatePopupMenu(self):
        menu = wx.Menu()
        menu.Append(self.TBMENU_RESTORE, _("Restore"))
        player_menu = wx.Menu()
        player_menu.Append(self.TBMENU_PLAYER_SHOW, _("Show Player"))
        player_menu.Append(self.TBMENU_PLAYER_TOGGLE, _("Play/Pause"))
        player_menu.Append(self.TBMENU_PLAYER_STOP, _("Stop"))
        player_menu.AppendSeparator()
        player_menu.Append(self.TBMENU_CAST, _("Cast / Connect..."))
        menu.AppendSubMenu(player_menu, _("Player Controls"))
        if self.on_record_stop is not None and self.parent and self.parent.recorder.has_active():
            menu.Append(self.TBMENU_RECORD_STOP, _("Stop Recording(s)"))
        menu.AppendSeparator()
        menu.Append(self.TBMENU_EXIT, _("Exit"))
        return menu

    def on_taskbar_activate(self, event):
        # Handle left-click, double-click, or Enter key on tray icon.
        # All these actions restore the app for accessibility (NVDA/JAWS).
        # Use CallLater to let the tray event fully complete before restoring.
        wx.CallLater(50, self.on_restore)

    def on_menu_select(self, event):
        eid = event.GetId()
        if eid == self.TBMENU_RESTORE:
            self.on_restore()
        elif eid == self.TBMENU_PLAYER_SHOW and self.on_player_show:
            self.on_player_show()
        elif eid == self.TBMENU_PLAYER_TOGGLE and self.on_player_toggle:
            self.on_player_toggle()
        elif eid == self.TBMENU_PLAYER_STOP and self.on_player_stop:
            self.on_player_stop()
        elif eid == self.TBMENU_CAST and self.on_cast:
            self.on_cast()
        elif eid == self.TBMENU_RECORD_STOP and self.on_record_stop:
            self.on_record_stop()
        elif eid == self.TBMENU_EXIT:
            self.on_exit()

class IPTVClient(wx.Frame):
    PLAYER_KEYS = [
        ("Built-in Player", "player_Internal"),
        ("VLC", "player_VLC"),
        ("MPC", "player_MPC"),
        ("MPC-BE", "player_MPCBE"),
        ("Kodi", "player_Kodi"),
        ("Winamp", "player_Winamp"),
        ("Foobar2000", "player_Foobar2000"),
        ("MPV", "player_MPV"),
        ("SMPlayer", "player_SMPlayer"),
        ("Totem", "player_Totem"),
        ("QuickTime", "player_QuickTime"),
        ("iTunes/Apple Music", "player_iTunes"),
        ("PotPlayer", "player_PotPlayer"),
        ("KMPlayer", "player_KMPlayer"),
        ("AIMP", "player_AIMP"),
        ("QMPlay2", "player_QMPlay2"),
        ("GOM Player", "player_GOMPlayer"),
        ("Audacious", "player_Audacious"),
        ("Fauxdacious", "player_Fauxdacious"),
        ("Clementine", "player_Clementine"),
        ("Strawberry", "player_Strawberry"),
        ("Amarok", "player_Amarok"),
        ("Rhythmbox", "player_Rhythmbox"),
        ("Pragha", "player_Pragha"),
        ("Lollypop", "player_Lollypop"),
        ("Exaile", "player_Exaile"),
        ("Quod Libet", "player_QuodLibet"),
        ("Gmusicbrowser", "player_Gmusicbrowser"),
        ("Xmms", "player_Xmms"),
        ("Vocal", "player_Vocal"),
        ("Haruna", "player_Haruna"),
        ("Celluloid", "player_Celluloid"),
    ]
    PLAYER_MENU_ATTRS = dict(PLAYER_KEYS)

    _CACHE_SHOW_STALE_SECS = 600
    _CACHE_REFRESH_AFTER_SECS = 180
    _SEARCH_LARGE_RESULT_THRESHOLD = 1500
    _SEARCH_PREVIEW_COUNT = 200
    _SEARCH_BATCH_SIZE = 800
    _SEARCH_EPG_MIN_CHARS = 3
    _SEARCH_EPG_BROAD_CHANNEL_LIMIT = 75
    _SEARCH_EPG_RESULT_LIMIT = 100

    def __init__(self):
        super().__init__(None, title="Accessible IPTV Client", size=(800, 600))
        self.config = load_config()
        # Activate the user's language preference before any UI strings are built.
        i18n.init_from_config(self.config)
        self.playlist_sources = self.config.get("playlists", [])
        self.epg_sources = self.config.get("epgs", [])
        self.channels_by_group: Dict[str, List[Dict[str, str]]] = {}
        self.all_channels: List[Dict[str, str]] = []
        self.displayed: List[Dict[str, str]] = []
        self.current_group = "All Channels"
        # View mode: "live" (channels + catch-up, the default) or "vod"
        # (browsable movies & series). VOD is built lazily on first switch.
        self.view_mode = "live"
        self.vod_group_order: List[str] = []
        self.vod_groups: Dict[str, List[Dict]] = {}
        self.vod_current_group: Optional[str] = None
        self.vod_loaded = False
        self.vod_loading = False
        self._vod_load_token = 0
        # When drilled into a series, the category to return to on "Back".
        self._vod_series_return_group: Optional[str] = None
        self.default_player = self.config.get("media_player", "Built-in Player")
        self.custom_player_path = self.config.get("custom_player_path", "")
        self.show_player_on_enter = self._bool_pref(self.config.get("show_player_on_enter", True), default=True)
        self.auto_check_updates = self._bool_pref(self.config.get("auto_check_updates", True), default=True)
        self.epg_importing = False
        self.epg_cache = {}
        self.epg_cache_lock = threading.Lock()
        self.refresh_timer = None
        self.minimize_to_tray = bool(self.config.get("minimize_to_tray", False))
        self.tray_icon = None
        self._tray_allow_restore = False
        self._tray_ready_timer: Optional[wx.CallLater] = None
        self.provider_clients: Dict[str, object] = {}
        self.provider_epg_sources: List[str] = []
        self._internal_player_frame: Optional[object] = None
        self._update_check_inflight = False
        self._update_install_pending = False
        self._auto_update_check_scheduled = False
        self._playlist_load_token = 0
        self._pending_epg_autostart = False
        self._pending_epg_autostart_token = 0
        self._epg_autostart_timer: Optional[wx.CallLater] = None

        # Casting loads several network/media stacks and may start the local
        # stream proxy. Keep it lazy so the first window is not delayed.
        self.caster = None

        self.player_launcher = ExternalPlayerLauncher()

        # Recording Manager
        self.recorder = recorder.RecordingManager()
        self._suppress_recording_notifications = False
        self._dvr_dialog = None
        self.dvr_scheduler = None

        # batch-population state to avoid UI hangs
        self._populate_token = 0
        self._search_token = 0

        # Timer for polling DB during EPG import so UI shows incoming data.
        self._epg_poll_timer: Optional[wx.Timer] = None
        # Track in-flight EPG fetches to avoid hammering get_now_next while importer is busy
        self._epg_fetch_inflight = set()
        self._epg_inflight_lock = threading.Lock()
        
        # Caching map: canonical_name -> db_channel_id
        self._epg_match_cache: Dict[str, Optional[str]] = {}
        self._epg_match_lock = threading.Lock()
        # Dedicated executor for EPG lookups to avoid thread-spawning overhead
        self._epg_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="EPGFetch")
        self._db_tune_lock = threading.Lock()
        self._db_tune_started = False
        self._build_ui()
        self.Centre()

        self.group_list.Append(_("Loading playlists..."))
        self.Show()

        # Defer non-UI startup work until the frame has had a chance to paint.
        wx.CallLater(50, self._run_deferred_startup_tasks)

        self.Bind(wx.EVT_ICONIZE, self.on_minimize)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def _run_deferred_startup_tasks(self):
        self._ensure_db_tuned_background()
        self._start_dvr_scheduler()
        self.start_playlist_load()

    def _ensure_db_tuned_background(self):
        with self._db_tune_lock:
            if self._db_tune_started:
                return
            self._db_tune_started = True

        def tune_db():
            try:
                self._ensure_db_tuned()
            except Exception:
                LOG.exception("Failed to tune EPG database during startup.")

        threading.Thread(target=tune_db, daemon=True, name="EPGDBTune").start()

    def _ensure_dvr_scheduler(self, *, start: bool = False):
        scheduler = getattr(self, "dvr_scheduler", None)
        if scheduler is None:
            scheduler = dvr.DVRScheduler(
                get_dvr_schedule_path(),
                on_start=self._start_scheduled_recording,
                on_stop=self._stop_scheduled_recording,
                on_update=self._on_dvr_schedule_updated,
                poll_seconds=10,
            )
            self.dvr_scheduler = scheduler
        if start:
            scheduler.start()
        return scheduler

    def _start_dvr_scheduler(self):
        try:
            self._ensure_dvr_scheduler(start=True)
        except Exception:
            LOG.exception("Failed to start DVR scheduler.")

    def _stop_dvr_scheduler(self, *, wait: bool = False):
        scheduler = getattr(self, "dvr_scheduler", None)
        if scheduler is not None:
            scheduler.stop(wait=wait)

    def _ensure_caster(self):
        caster = getattr(self, "caster", None)
        if caster is None:
            from casting import CastingManager

            caster = CastingManager()
            caster.start()
            self.caster = caster
        return caster

    def _schedule_auto_update_check(self):
        if getattr(self, "_auto_update_check_scheduled", False):
            return
        if not self.auto_check_updates:
            return
        if not self._should_run_auto_update_check():
            return
        self._auto_update_check_scheduled = True
        wx.CallLater(
            _AUTO_UPDATE_DELAY_AFTER_PLAYLIST_MS,
            lambda: self._start_update_check(interactive=False),
        )

    def _should_run_auto_update_check(self) -> bool:
        try:
            last_check = float(self.config.get("update_last_auto_check_epoch", 0) or 0)
        except Exception:
            last_check = 0.0
        now = time.time()
        if last_check <= 0 or last_check > now + 300:
            return True
        return (now - last_check) >= _AUTO_UPDATE_CHECK_INTERVAL_SECONDS

    def _record_auto_update_check_attempt(self):
        try:
            self.config["update_last_auto_check_epoch"] = int(time.time())
            save_config(self.config)
        except Exception:
            LOG.debug("IPTVClient._record_auto_update_check_attempt: ignored exception", exc_info=True)

    def _channel_is_epg_exempt(self, channel: Dict[str, str]) -> bool:
        """Detect channels that typically have no EPG (e.g., 24/7 loops).
        We do NOT modify names; this only avoids unnecessary DB lookups/logs.
        Rule: tvg-id empty AND name/group contains '24/7' or '24x7'.
        """
        try:
            tvg_id = (channel.get("tvg-id") or channel.get("tvg_id") or "").strip()
            if tvg_id:
                return False
            name = (channel.get("tvg-name") or channel.get("name") or "").lower()
            group = (channel.get("group-title") or channel.get("group") or "").lower()
            if "24/7" in name or "24x7" in name or "24/7" in group or "24x7" in group:
                return True
        except Exception:
            LOG.debug("IPTVClient._channel_is_epg_exempt: ignored exception", exc_info=True)
        return False

    def start_playlist_load(self):
        """Kicks off ONLY the playlist loading thread."""
        self._playlist_load_token += 1
        self._pending_epg_autostart = True
        self._pending_epg_autostart_token = self._playlist_load_token
        self._cancel_epg_autostart_timer()
        threading.Thread(
            target=self._do_playlist_refresh,
            args=(self._playlist_load_token,),
            daemon=True
        ).start()

    def _ensure_db_tuned(self):
        """Enable WAL and indices so read lookups don’t stall behind imports."""
        conn = None
        try:
            path = get_db_path()
            if not os.path.exists(path):
                return
            uri = f"file:{path}?cache=shared"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            cur = conn.cursor()
            tables = {
                row[0]
                for row in cur.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name IN ('channels', 'programmes')
                    """
                ).fetchall()
            }
            if {"channels", "programmes"} - tables:
                return
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA temp_store=MEMORY;")
            cur.execute("PRAGMA mmap_size=268435456;")
            cur.execute("PRAGMA cache_size=-65536;")
            cur.execute("PRAGMA wal_autocheckpoint=0;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_programmes_channel_end ON programmes(channel_id, end);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_programmes_channel_start_end ON programmes(channel_id, start, end);")
            conn.commit()
        except Exception:
            LOG.debug("IPTVClient._ensure_db_tuned: ignored exception", exc_info=True)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    LOG.debug("IPTVClient._ensure_db_tuned: ignored exception", exc_info=True)

    def _sync_player_menu_from_config(self):
        defplayer = self.config.get("media_player", "Built-in Player")
        self.default_player = defplayer
        for key, attr in self.PLAYER_MENU_ATTRS.items():
            if hasattr(self, attr):
                getattr(self, attr).Check(key == defplayer)
        if hasattr(self, "player_Custom"):
            self.player_Custom.Check(defplayer == "Custom")
        if hasattr(self, "_player_radio_items"):
            for label, item in self._player_radio_items.items():
                item.Check(label == defplayer)

    def on_menu_open(self, event):
        from options import load_config
        self.config = load_config()
        self._sync_player_menu_from_config()
        if hasattr(self, "min_to_tray_item"):
            self.minimize_to_tray = bool(self.config.get("minimize_to_tray", False))
            self.min_to_tray_item.Check(self.minimize_to_tray)
        self.show_player_on_enter = self._bool_pref(self.config.get("show_player_on_enter", True), default=True)
        if hasattr(self, "show_player_on_enter_item"):
            try:
                self.show_player_on_enter_item.Check(self.show_player_on_enter)
            except Exception:
                LOG.debug("IPTVClient.on_menu_open: ignored exception", exc_info=True)
        self.auto_check_updates = self._bool_pref(self.config.get("auto_check_updates", True), default=True)
        if hasattr(self, "auto_check_updates_item"):
            try:
                self.auto_check_updates_item.Check(self.auto_check_updates)
            except Exception:
                LOG.debug("IPTVClient.on_menu_open: ignored exception", exc_info=True)
        event.Skip()

    def start_refresh_timer(self):
        if self.refresh_timer:
            self.refresh_timer.Stop()
        self.refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer_refresh, self.refresh_timer)
        self.refresh_timer.Start(3 * 60 * 60 * 1000, wx.TIMER_CONTINUOUS)

    def on_timer_refresh(self, event):
        # This full cycle can be triggered by the timer.
        self.start_playlist_load()

    def _do_playlist_refresh(self, refresh_token: int):
        """
        Loads playlists from cache for a fast UI update, then refreshes from the network.
        Crucially, it only starts the EPG import *after* playlists are loaded.
        """
        playlist_sources = self.config.get("playlists", [])
        # Ensure all provider entries have persistent IDs so we can track clients.
        mutated = False
        for src in playlist_sources:
            if isinstance(src, dict) and not src.get("id"):
                src["id"] = generate_provider_id()
                mutated = True
        if mutated:
            self.config["playlists"] = playlist_sources
            save_config(self.config)

        channels_by_group: Dict[str, List[Dict[str, str]]] = {}
        all_channels: List[Dict[str, str]] = []
        valid_caches = set()
        seen_channel_keys = set()

        # Fast prefill from parsed caches (no network) so UI shows something immediately.
        prefilled_by_group: Dict[str, List[Dict[str, str]]] = {}
        prefilled_all: List[Dict[str, str]] = []
        prefill_seen = set()

        # (hash, channels) already read from a parsed-cache file during prefill, keyed by
        # that file's path. On the common "nothing changed" launch, fetch_and_process_playlist
        # below re-derives the same path and, once it has the freshly-fetched text_hash, can
        # reuse this instead of re-reading + re-decoding the same (potentially huge) JSON file.
        prefill_loaded: Dict[str, Tuple[Optional[str], List[Dict[str, str]]]] = {}

        def _cached_channels_for(parsed_cache, text_hash, provider_meta):
            entry = prefill_loaded.get(parsed_cache)
            if entry is not None:
                stored_hash, stored_channels = entry
                return stored_channels if stored_hash == text_hash else None
            return self._load_cached_playlist(parsed_cache, text_hash, provider_meta)

        def _prefill_from_cache(src) -> None:
            parsed_cache = None
            provider_meta = None
            if isinstance(src, dict):
                stype = (src.get("type") or "").lower()
                provider_id = src.get("id") or src.get("provider_id")
                if stype in ("xtream", "stalker"):
                    cache_key = provider_id or f"{stype}:{src.get('base_url') or src.get('url') or ''}:{src.get('username', '')}"
                    parsed_cache = self._parsed_cache_path_for_key(f"provider:{cache_key}")
                    provider_meta = {"provider-type": stype, "provider-id": provider_id}
            elif isinstance(src, str) and src.startswith(("http://", "https://")):
                parsed_cache = self._parsed_cache_path_for_key(src)
            elif isinstance(src, str) and os.path.exists(src):
                parsed_cache = self._parsed_cache_path_for_key(f"file:{os.path.abspath(src)}")
            if not parsed_cache or not os.path.exists(parsed_cache):
                return
            stored_hash, cached = self._read_cached_playlist_file(parsed_cache)
            if not cached:
                return
            self._apply_cached_provider_meta(cached, provider_meta)
            prefill_loaded[parsed_cache] = (stored_hash, cached)
            for ch in cached:
                key = (ch.get("name", ""), ch.get("url", ""), ch.get("provider-id", ""))
                if key in prefill_seen:
                    continue
                prefill_seen.add(key)
                grp = ch.get("group") or "Uncategorized"
                prefilled_by_group.setdefault(grp, []).append(ch)
                prefilled_all.append(ch)

        for _src in playlist_sources:
            _prefill_from_cache(_src)

        if prefilled_all:
            seen_channel_keys.update(prefill_seen)
            channels_by_group = {grp: lst.copy() for grp, lst in prefilled_by_group.items()}
            all_channels = list(prefilled_all)

            def apply_prefill(pref_by_group, pref_all):
                self.channels_by_group = pref_by_group
                self.all_channels = pref_all
                self._refresh_group_ui()

            wx.CallAfter(apply_prefill, prefilled_by_group, prefilled_all)

        # We will collect these from the workers
        provider_clients_local: Dict[str, object] = {}
        provider_epg_sources: List[str] = []

        def fetch_and_process_playlist(src):
            result = {
                "channels": [],
                "clients": {},
                "epg_sources": [],
                "valid_cache": None,
                "error": None
            }
            try:
                if isinstance(src, dict):
                    stype = (src.get("type") or "").lower()
                    provider_id = src.get("id") or src.get("provider_id")
                    if stype == "xtream":
                        cfg = XtreamCodesConfig(
                            base_url=src.get("base_url") or src.get("url") or "",
                            username=src.get("username", ""),
                            password=src.get("password", ""),
                            stream_type=src.get("stream_type", "m3u_plus"),
                            output=src.get("output", "ts"),
                            name=src.get("name"),
                            auto_epg=bool(src.get("auto_epg", True)),
                            provider_id=provider_id
                        )
                        client = XtreamCodesClient(cfg)
                        text = client.fetch_playlist()
                        text_hash = self._playlist_text_hash(text)
                        cache_key = provider_id or f"xtream:{cfg.base_url}:{cfg.username}"
                        parsed_cache = self._parsed_cache_path_for_key(f"provider:{cache_key}")
                        provider_meta = {"provider-type": "xtream", "provider-id": provider_id}
                        
                        channels = None
                        if parsed_cache and text_hash:
                            channels = _cached_channels_for(parsed_cache, text_hash, provider_meta)
                        if channels is None:
                            channels = self._parse_m3u_return(text, provider_info=provider_meta)
                            if parsed_cache and text_hash:
                                self._store_cached_playlist(parsed_cache, text_hash, channels, provider_meta)
                        
                        result["channels"] = channels or []
                        result["clients"][provider_id] = client
                        if cfg.auto_epg:
                            for epg in client.epg_urls():
                                if epg: result["epg_sources"].append(epg)

                    elif stype == "stalker":
                        cfg = StalkerPortalConfig(
                            base_url=src.get("base_url") or src.get("url") or "",
                            username=src.get("username", ""),
                            password=src.get("password", ""),
                            mac=src.get("mac", ""),
                            name=src.get("name"),
                            auto_epg=bool(src.get("auto_epg", True)),
                            provider_id=provider_id
                        )
                        client = StalkerPortalClient(cfg)
                        channels, epgs = client.fetch_channels()
                        for ch in channels:
                            ch.setdefault("provider-id", provider_id)
                            ch.setdefault("provider-type", "stalker")
                        
                        result["channels"] = channels
                        result["clients"][provider_id] = client
                        for epg in epgs:
                            if epg: result["epg_sources"].append(epg)
                    else:
                        pass # Unknown dict source
                    return result

                # Plain playlist path or URL
                if isinstance(src, str) and src.startswith(("http://", "https://")):
                    cache_path = get_cache_path_for_url(src)
                    parsed_cache = self._parsed_cache_path_for_key(src)
                    result["valid_cache"] = cache_path
                    
                    download = True
                    if os.path.exists(cache_path):
                        age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(cache_path))).total_seconds()
                        if age < 15 * 60:
                            download = False

                    text = ""
                    if download:
                        with urllib.request.urlopen(
                            urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"}), timeout=60
                        ) as resp:
                            raw = resp.read()
                            try:
                                # utf-8-sig strips a leading BOM if present; otherwise == utf-8.
                                text = raw.decode("utf-8-sig")
                            except UnicodeDecodeError:
                                text = raw.decode("latin-1", "ignore")
                        with open(cache_path, "w", encoding="utf-8") as f:
                            f.write(text)
                    else:
                        with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read()
                            
                    text_hash = self._playlist_text_hash(text)
                    
                    channels = None
                    if parsed_cache and text_hash:
                        channels = _cached_channels_for(parsed_cache, text_hash, provider_meta=None)
                    if channels is None:
                        channels = self._parse_m3u_return(text, provider_info=None)
                        if parsed_cache and text_hash:
                            self._store_cached_playlist(parsed_cache, text_hash, channels, provider_meta=None)
                    
                    result["channels"] = channels or []

                elif isinstance(src, str) and os.path.exists(src):
                    with open(src, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    text_hash = self._playlist_text_hash(text)
                    cache_key = f"file:{os.path.abspath(src)}"
                    parsed_cache = self._parsed_cache_path_for_key(cache_key)
                    
                    channels = None
                    if parsed_cache and text_hash:
                        channels = _cached_channels_for(parsed_cache, text_hash, provider_meta=None)
                    if channels is None:
                        channels = self._parse_m3u_return(text, provider_info=None)
                        if parsed_cache and text_hash:
                            self._store_cached_playlist(parsed_cache, text_hash, channels, provider_meta=None)
                            
                    result["channels"] = channels or []
                else:
                    pass # Invalid source
            except Exception as e:
                result["error"] = str(e)
                # LOG.error(f"Error fetching playlist {src}: {e}")
            
            return result

        # Execute in parallel (fetching AND parsing) with a CPU-friendly cap.
        source_count = len(playlist_sources)
        cpu_count = os.cpu_count() or 2
        worker_cap = max(2, cpu_count // 2)
        max_workers = min(source_count if source_count else 1, worker_cap, 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch_and_process_playlist, src) for src in playlist_sources]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res["error"]:
                    continue
                
                if res["valid_cache"]:
                    valid_caches.add(res["valid_cache"])
                
                provider_clients_local.update(res["clients"])
                for epg in res["epg_sources"]:
                    if epg not in provider_epg_sources:
                        provider_epg_sources.append(epg)
                
                for ch in res["channels"]:
                    key = (ch.get("name", ""), ch.get("url", ""), ch.get("provider-id", ""))
                    if key in seen_channel_keys:
                        continue
                    seen_channel_keys.add(key)
                    grp = ch.get("group") or "Uncategorized"
                    channels_by_group.setdefault(grp, []).append(ch)
                    all_channels.append(ch)

        # Replace provider mappings atomically after successful refresh
        self.provider_clients = provider_clients_local
        self.provider_epg_sources = provider_epg_sources

        def finish_playlist_load_and_start_background_tasks():
            self.channels_by_group = channels_by_group
            self.all_channels = all_channels
            self.reload_epg_sources()
            self._pending_epg_autostart = True
            self._pending_epg_autostart_token = refresh_token
            # A reload invalidates any previously built VOD catalogue.
            self.vod_loaded = False
            self.vod_groups = {}
            self.vod_group_order = []
            if self.view_mode == "vod":
                self._load_vod_catalog()
            else:
                self._refresh_group_ui()
            self._cleanup_cache_and_channels(valid_caches)
            # Now that playlists are loaded, start the other processes.
            self.start_refresh_timer()
            self._schedule_auto_update_check()

        wx.CallAfter(finish_playlist_load_and_start_background_tasks)


    def _cleanup_cache_and_channels(self, valid_caches):
        cache_dir = get_cache_dir()
        try:
            files = [os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if f.endswith(".m3u")]
        except Exception:
            return
        for f in files:
            if f not in valid_caches:
                try:
                    os.remove(f)
                except Exception:
                    LOG.debug("IPTVClient._cleanup_cache_and_channels: ignored exception", exc_info=True)

    def _build_ui(self):
        p = wx.Panel(self)
        hs = wx.BoxSizer(wx.HORIZONTAL)
        vs_l = wx.BoxSizer(wx.VERTICAL)
        vs_r = wx.BoxSizer(wx.VERTICAL)
        self.group_list = wx.ListBox(p, style=wx.LB_SINGLE)
        self.group_list.Bind(wx.EVT_CHAR_HOOK, self.on_group_key)
        vs_l.Add(self.group_list, 1, wx.EXPAND | wx.ALL, 5)
        self.filter_box = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        # Virtual list control (native SysListView32) so 50k-300k channels stay responsive
        # for the UI and NVDA alike — only visible rows are realized. Backed by self.displayed.
        self.channel_list = _VirtualChannelList(p, self)
        # Key bindings (original + added robust handlers)
        self.channel_list.Bind(wx.EVT_CHAR_HOOK, self.on_channel_key)  # original
        self.channel_list.Bind(wx.EVT_KEY_DOWN, self._on_channel_key_down)  # reliable Enter on all platforms
        # Selection change (keyboard arrows + mouse) -> refresh EPG/URL panel.
        self.channel_list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _evt: self.on_highlight())
        # Activation: Enter is consumed by the key handlers above, so this fires on double-click.
        self.channel_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _evt: self.play_selected())
        self.channel_list.Bind(wx.EVT_CONTEXT_MENU, self._on_channel_context_menu)

        self.epg_display = wx.TextCtrl(p, style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.url_display = wx.TextCtrl(p, style=wx.TE_READONLY | wx.TE_MULTILINE)
        vs_r.Add(self.filter_box, 0, wx.EXPAND | wx.ALL, 5)
        vs_r.Add(self.channel_list, 1, wx.EXPAND | wx.ALL, 5)
        vs_r.Add(self.epg_display, 0, wx.EXPAND | wx.ALL, 5)
        vs_r.Add(self.url_display, 0, wx.EXPAND | wx.ALL, 5)
        hs.Add(vs_l, 1, wx.EXPAND)
        hs.Add(vs_r, 2, wx.EXPAND)

        if platform.system() == "Linux":
            self.menu_button = wx.Button(p, label=_("Menu"))
            self._player_radio_items = {}
            def on_menu_btn(evt):
                menu = wx.Menu()
                menu.Append(1001, _("Playlist Manager") + "\tCtrl+M")
                menu.Append(1002, _("EPG Manager") + "\tCtrl+E")
                menu.Append(1003, _("Import EPG to DB") + "\tCtrl+I")
                menu.Append(1007, _("Account Info") + "\tCtrl+Shift+A")
                menu.AppendSeparator()
                player_ctrl_menu = wx.Menu()
                player_ctrl_menu.Append(1201, _("Show Built-in Player"))
                player_ctrl_menu.Append(1202, _("Play/Pause"))
                player_ctrl_menu.Append(1203, _("Stop"))
                player_ctrl_menu.Append(1204, _("Cast / Connect..."))
                menu.AppendSubMenu(player_ctrl_menu, _("Player"))
                self.Bind(wx.EVT_MENU, self._menu_show_player, id=1201)
                self.Bind(wx.EVT_MENU, self._menu_toggle_player, id=1202)
                self.Bind(wx.EVT_MENU, self._menu_stop_player, id=1203)
                self.Bind(wx.EVT_MENU, self._menu_cast_from_player, id=1204)
                # View submenu: Live TV / catch-up vs Video on Demand.
                view_menu = wx.Menu()
                view_live = view_menu.AppendRadioItem(1301, _("Live TV && Catch-up"))
                view_vod = view_menu.AppendRadioItem(1302, _("Video on Demand (Movies && Series)"))
                view_live.Check(self.view_mode == "live")
                view_vod.Check(self.view_mode == "vod")
                self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("live"), id=1301)
                self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("vod"), id=1302)
                menu.AppendSubMenu(view_menu, _("View"))
                menu.AppendSeparator()
                player_menu = wx.Menu()
                for idx, (label, attr) in enumerate(self.PLAYER_KEYS):
                    itemid = 2000 + idx
                    item = player_menu.AppendRadioItem(itemid, _(label))
                    self._player_radio_items[label] = item
                    self.Bind(wx.EVT_MENU, lambda evt, pl=label: self._select_player(pl), id=itemid)
                    if self.default_player == label:
                        item.Check(True)
                customid = 2999
                customitem = player_menu.AppendRadioItem(customid, _("Custom Player..."))
                self.Bind(wx.EVT_MENU, self._select_custom_player, id=customid)
                if self.default_player == "Custom":
                    customitem.Check(True)
                menu.AppendSubMenu(player_menu, _("Media Player to Use"))
                # Recordings submenu (Linux)
                rec_menu = wx.Menu()
                self._populate_recordings_menu(rec_menu)
                menu.AppendSubMenu(rec_menu, _("Recordings"))
                # Language submenu (Linux)
                lang_menu = wx.Menu()
                self._lang_menu_items = {}
                for code, label in i18n.available_languages():
                    disp = _("Automatic") if code == "auto" else label
                    li = lang_menu.AppendRadioItem(wx.ID_ANY, disp)
                    if i18n.get_language() == code:
                        li.Check(True)
                    self._lang_menu_items[li.GetId()] = code
                    self.Bind(wx.EVT_MENU, lambda evt, c=code: self._on_select_language(c), li)
                menu.AppendSubMenu(lang_menu, _("Language"))
                min_to_tray_id = 1101
                min_item = menu.AppendCheckItem(min_to_tray_id, _("Minimize to System Tray"))
                min_item.Check(self.minimize_to_tray)
                self.Bind(wx.EVT_MENU, self.on_toggle_min_to_tray, id=min_to_tray_id)
                menu.AppendSeparator()
                show_enter_id = 1102
                show_enter_item = menu.AppendCheckItem(show_enter_id, _("Show Player on Enter"))
                show_enter_item.Check(self.show_player_on_enter)
                self.Bind(wx.EVT_MENU, self.on_toggle_show_player_on_enter, id=show_enter_id)
                menu.AppendSeparator()

                auto_update_id = 1103
                auto_update_item = menu.AppendCheckItem(auto_update_id, _("Auto-check for Updates"))
                auto_update_item.Check(self.auto_check_updates)
                self.Bind(wx.EVT_MENU, self.on_toggle_auto_check_updates, id=auto_update_id)
                menu.Append(1006, _("Check for Updates"))
                self.Bind(wx.EVT_MENU, self.on_check_updates, id=1006)
                menu.AppendSeparator()

                # Casting Menu Item (Linux)
                menu.Append(1005, _("Cast To..."))
                self.Bind(wx.EVT_MENU, self.show_cast_dialog, id=1005)

                menu.Append(1004, _("Exit") + "\tCtrl+Q")
                self.Bind(wx.EVT_MENU, self.show_manager, id=1001)
                self.Bind(wx.EVT_MENU, self.show_epg_manager, id=1002)
                self.Bind(wx.EVT_MENU, self.import_epg, id=1003)
                self.Bind(wx.EVT_MENU, self.show_account_info, id=1007)
                self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=1004)
                self.menu_button.PopupMenu(menu)
            self.menu_button.Bind(wx.EVT_BUTTON, on_menu_btn)
            sizer_with_menu = wx.BoxSizer(wx.VERTICAL)
            sizer_with_menu.Add(self.menu_button, 0, wx.EXPAND | wx.ALL, 5)
            sizer_with_menu.Add(hs, 1, wx.EXPAND)
            p.SetSizerAndFit(sizer_with_menu)
        else:
            p.SetSizerAndFit(hs)
            mb = wx.MenuBar()
            fm = wx.Menu()
            m_mgr = fm.Append(wx.ID_ANY, _("Playlist Manager") + "\tCtrl+M")
            m_epg = fm.Append(wx.ID_ANY, _("EPG Manager") + "\tCtrl+E")
            m_imp = fm.Append(wx.ID_ANY, _("Import EPG to DB") + "\tCtrl+I")
            m_now = fm.Append(wx.ID_ANY, _("What's on Now") + "\tCtrl+W")
            m_acct = fm.Append(wx.ID_ANY, _("Account Info") + "\tCtrl+Shift+A")
            fm.AppendSeparator()
            # Casting Menu Item (Windows/Mac)
            m_cast = fm.Append(wx.ID_ANY, _("Cast To..."))
            fm.AppendSeparator()
            m_exit = fm.Append(wx.ID_EXIT, _("Exit") + "\tCtrl+Q")
            mb.Append(fm, _("File"))
            pm = wx.Menu()
            pm_show = pm.Append(wx.ID_ANY, _("Show Built-in Player") + "\tCtrl+Shift+J")
            pm_toggle = pm.Append(wx.ID_ANY, _("Play/Pause") + "\tCtrl+Shift+P")
            pm_stop = pm.Append(wx.ID_ANY, _("Stop") + "\tCtrl+Shift+S")
            pm_cast = pm.Append(wx.ID_ANY, _("Cast / Connect...") + "\tCtrl+Shift+C")
            mb.Append(pm, _("Player"))
            # View menu: switch between Live TV / catch-up and Video on Demand.
            vm = wx.Menu()
            self.view_live_item = vm.AppendRadioItem(wx.ID_ANY, _("Live TV && Catch-up"))
            self.view_vod_item = vm.AppendRadioItem(wx.ID_ANY, _("Video on Demand (Movies && Series)"))
            self.view_live_item.Check(self.view_mode == "live")
            self.view_vod_item.Check(self.view_mode == "vod")
            mb.Append(vm, _("View"))
            self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("live"), self.view_live_item)
            self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("vod"), self.view_vod_item)
            om = wx.Menu()
            player_menu = wx.Menu()
            self.player_menu_items = []
            for label, attr in self.PLAYER_KEYS:
                item = player_menu.AppendRadioItem(wx.ID_ANY, _(label))
                setattr(self, attr, item)
                self.player_menu_items.append((item, label))
            self.player_Custom = player_menu.AppendRadioItem(wx.ID_ANY, _("Custom Player..."))
            om.AppendSubMenu(player_menu, _("Media Player to Use"))
            # Language submenu (Windows/macOS)
            lang_menu = wx.Menu()
            self._lang_menu_items = {}
            for code, lbl in i18n.available_languages():
                disp = _("Automatic") if code == "auto" else lbl
                li = lang_menu.AppendRadioItem(wx.ID_ANY, disp)
                if i18n.get_language() == code:
                    li.Check(True)
                self._lang_menu_items[li.GetId()] = code
                self.Bind(wx.EVT_MENU, lambda evt, c=code: self._on_select_language(c), li)
            om.AppendSubMenu(lang_menu, _("Language"))
            self.min_to_tray_item = om.AppendCheckItem(wx.ID_ANY, _("Minimize to System Tray"))
            self.show_player_on_enter_item = om.AppendCheckItem(wx.ID_ANY, _("Show Player on Enter"))
            self.auto_check_updates_item = om.AppendCheckItem(wx.ID_ANY, _("Auto-check for Updates"))
            mb.Append(om, _("Options"))
            # Recordings menu
            rm = wx.Menu()
            self._populate_recordings_menu(rm)
            mb.Append(rm, _("Recordings"))
            # Help menu
            hm = wx.Menu()
            self.check_updates_item = hm.Append(wx.ID_ANY, _("Check for Updates..."))
            hm.AppendSeparator()
            m_about = hm.Append(wx.ID_ABOUT, _("About..."))
            mb.Append(hm, _("Help"))
            self.SetMenuBar(mb)
            self.Bind(wx.EVT_MENU, self.show_manager, m_mgr)
            self.Bind(wx.EVT_MENU, self.show_epg_manager, m_epg)
            self.Bind(wx.EVT_MENU, self.import_epg, m_imp)
            self.Bind(wx.EVT_MENU, self.show_whats_on_now, m_now)
            self.Bind(wx.EVT_MENU, self.show_account_info, m_acct)
            self.Bind(wx.EVT_MENU, self.show_cast_dialog, m_cast)
            self.Bind(wx.EVT_MENU, lambda _: self.Close(), m_exit)
            self.Bind(wx.EVT_MENU, self._menu_show_player, pm_show)
            self.Bind(wx.EVT_MENU, self._menu_toggle_player, pm_toggle)
            self.Bind(wx.EVT_MENU, self._menu_stop_player, pm_stop)
            self.Bind(wx.EVT_MENU, self._menu_cast_from_player, pm_cast)
            for item, key in self.player_menu_items:
                self.Bind(wx.EVT_MENU, lambda evt, attr=key: self._select_player(attr), item)
            self.Bind(wx.EVT_MENU, self._select_custom_player, self.player_Custom)
            self.Bind(wx.EVT_MENU, self.on_toggle_min_to_tray, self.min_to_tray_item)
            self.Bind(wx.EVT_MENU, self.on_toggle_show_player_on_enter, self.show_player_on_enter_item)
            self.Bind(wx.EVT_MENU, self.on_toggle_auto_check_updates, self.auto_check_updates_item)
            self.Bind(wx.EVT_MENU, self.on_check_updates, self.check_updates_item)
            self.Bind(wx.EVT_MENU, self._show_about_dialog, m_about)
            self.Bind(wx.EVT_MENU_OPEN, self.on_menu_open)
            self._sync_player_menu_from_config()
            self.min_to_tray_item.Check(self.minimize_to_tray)
            self.show_player_on_enter_item.Check(self.show_player_on_enter)
            self.auto_check_updates_item.Check(self.auto_check_updates)

        self.group_list.Bind(wx.EVT_LISTBOX, lambda _: self.on_group_select())
        self.filter_box.Bind(wx.EVT_TEXT_ENTER, lambda _: self.apply_filter())

        entries = [
            (wx.ACCEL_CTRL, ord('M'), 4001),
            (wx.ACCEL_CTRL, ord('E'), 4002),
            (wx.ACCEL_CTRL, ord('I'), 4003),
            (wx.ACCEL_CTRL, ord('Q'), 4004),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('P'), 4010),  # Play/Pause
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('S'), 4011),  # Stop
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('C'), 4012),  # Cast/connect
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('K'), 4013),  # Volume up
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('J'), 4014),  # Volume down
            (wx.ACCEL_CTRL, wx.WXK_UP, 4015),   # Volume up (Ctrl+Up)
            (wx.ACCEL_CTRL, wx.WXK_DOWN, 4016), # Volume down (Ctrl+Down)
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('R'), 4017),  # Start/stop recording
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('A'), 4018),  # Account info
        ]
        atable = wx.AcceleratorTable(entries)
        self.SetAcceleratorTable(atable)
        self.Bind(wx.EVT_MENU, self.show_manager, id=4001)
        self.Bind(wx.EVT_MENU, self.show_epg_manager, id=4002)
        self.Bind(wx.EVT_MENU, self.import_epg, id=4003)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=4004)
        self.Bind(wx.EVT_MENU, self._menu_toggle_player, id=4010)
        self.Bind(wx.EVT_MENU, self._menu_stop_player, id=4011)
        self.Bind(wx.EVT_MENU, self._menu_cast_from_player, id=4012)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(+2), id=4013)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(-2), id=4014)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(+2), id=4015)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(-2), id=4016)
        self.Bind(wx.EVT_MENU, self._record_selected, id=4017)
        self.Bind(wx.EVT_MENU, self.show_account_info, id=4018)

        # Intentionally do not event.Skip() to avoid duplicate handling.

    def _on_channel_key_down(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.play_selected(show_internal_player=self.show_player_on_enter)
            return  # swallow to prevent beep/focus issues
        event.Skip()

    def _on_channel_context_menu(self, event):
        if not self.displayed:
            return
        pos = event.GetPosition()
        idx = self.channel_list.GetSelection()
        if pos != wx.DefaultPosition and not (pos.x == -1 and pos.y == -1):
            try:
                local = self.channel_list.ScreenToClient(pos)
                hit = self.channel_list.HitTest(local) if hasattr(self.channel_list, "HitTest") else (-1,)
                hit_idx = hit[0] if isinstance(hit, tuple) else hit
                if hit_idx not in (None, -1) and 0 <= hit_idx < len(self.displayed):
                    self.channel_list.SetSelection(hit_idx)
                    self.channel_list.SetFocus()
                    idx = hit_idx
            except Exception:
                LOG.debug("IPTVClient._on_channel_context_menu: ignored exception", exc_info=True)
        if idx == wx.NOT_FOUND and self.channel_list.GetCount():
            self.channel_list.SetSelection(0)
            idx = 0
        if idx == wx.NOT_FOUND or idx >= len(self.displayed):
            return
        item = self.displayed[idx]
        channel = None
        if item.get("type") == "channel":
            channel = item.get("data")
        elif item.get("type") == "epg":
            channel = self._find_channel_for_epg(item.get("data", {}))
        if not channel:
            return
        menu = wx.Menu()
        play_item = menu.Append(wx.ID_ANY, _("Play"))
        menu.Bind(wx.EVT_MENU, lambda evt: self.play_selected(), play_item)

        if self.recorder.is_recording(self._channel_record_key(channel)):
            rec_item = menu.Append(wx.ID_ANY, _("Stop Recording"))
        else:
            rec_item = menu.Append(wx.ID_ANY, _("Record"))
        menu.Bind(wx.EVT_MENU, lambda evt, ch=channel: self._record_channel(ch), rec_item)

        if item.get("type") == "epg":
            sched_item = menu.Append(wx.ID_ANY, _("Schedule Recording"))
            menu.Bind(
                wx.EVT_MENU,
                lambda evt, ch=channel, prog=item.get("data", {}): self._schedule_program_recording(ch, prog),
                sched_item,
            )

        if not self._channel_is_epg_exempt(channel):
            epg_item = menu.Append(wx.ID_ANY, _("View EPG..."))
            menu.Bind(wx.EVT_MENU, lambda evt, ch=channel: self._view_channel_epg(ch), epg_item)

        if self._channel_has_catchup(channel):
            catch_item = menu.Append(wx.ID_ANY, _("Play Catch-up…"))
            menu.Bind(wx.EVT_MENU, lambda evt, ch=channel: self._open_catchup_dialog(ch), catch_item)
        try:
            self.channel_list.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _view_channel_epg(self, channel: Dict[str, str]):
        def fetch_and_show():
            try:
                db = EPGDatabase(get_db_path(), readonly=True)
                now = datetime.datetime.now(datetime.timezone.utc)
                start_dt = now - datetime.timedelta(hours=4)
                end_dt = now + datetime.timedelta(hours=24)
                programmes = db.get_schedule(channel, start_dt, end_dt)
                db.close()
                
                wx.CallAfter(lambda: self._show_epg_dialog(channel, channel.get("name", ""), programmes))
            except Exception as e:
                wx.CallAfter(lambda err=e: wx.MessageBox(_("Error fetching EPG: {error}").format(error=err), _("Error"), wx.OK | wx.ICON_ERROR))

        threading.Thread(target=fetch_and_show, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Recording                                                          #
    # ------------------------------------------------------------------ #
    def _selected_channel(self) -> Optional[Dict[str, str]]:
        """Return the channel for the current list selection, or None."""
        i = self.channel_list.GetSelection()
        if not (0 <= i < len(self.displayed)):
            return None
        item = self.displayed[i]
        if item.get("type") == "channel":
            return item.get("data")
        if item.get("type") == "epg":
            return self._find_channel_for_epg(item.get("data", {}))
        return None

    def _channel_record_key(self, channel: Dict[str, str]) -> str:
        """Stable identity for a channel (the resolved stream URL can change per resolve)."""
        provider_data = channel.get("provider-data") or ""
        if isinstance(provider_data, dict):
            try:
                provider_data = json.dumps(provider_data, sort_keys=True, default=str)
            except Exception:
                provider_data = str(provider_data)
        parts = [
            channel.get("provider-type") or "",
            channel.get("provider-id") or "",
            channel.get("stream-id") or channel.get("stream_id") or "",
            channel.get("url") or "",
            provider_data or "",
            channel.get("name") or channel.get("tvg-name") or channel.get("tvg_name") or "",
        ]
        return "|".join(str(part) for part in parts if part)

    def _channel_display_name(self, channel: Dict[str, str]) -> str:
        return (channel.get("name")
                or channel.get("tvg-name")
                or channel.get("tvg_name")
                or channel.get("tvg-id")
                or channel.get("tvg_id")
                or _("IPTV Stream"))

    def _find_matching_channel_for_program(self, program: Dict[str, str]) -> Optional[Dict[str, str]]:
        """Find the playlist channel that best matches an EPG/search program row."""
        channel_name = program.get("channel_name", "")
        channel_id = program.get("channel_id", "")
        if not channel_name and not channel_id:
            return None

        matching_channel = None
        best_score = 0
        channel_name_lower = channel_name.lower() if channel_name else ""
        channel_name_norm = canonicalize_name(strip_noise_words(channel_name)) if channel_name else ""
        base_patterns = ["hd", "sd", "fhd", "uhd", "4k", "hevc", "h264", "h.264"]
        channel_base = channel_name_lower
        for pat in base_patterns:
            channel_base = channel_base.replace(" {pat}".format(pat=pat), "")
            channel_base = channel_base.replace("({pat})".format(pat=pat), "")
            channel_base = channel_base.replace("[{pat}]".format(pat=pat), "")
        channel_base = channel_base.strip()

        for ch in self.all_channels:
            ch_name = ch.get("name", "")
            ch_tvg_name = ch.get("tvg-name", "")
            ch_tvg_id = ch.get("tvg-id", "")
            ch_name_lower = ch_name.lower()
            score = 0

            if channel_id and ch_tvg_id:
                if channel_id.lower() == ch_tvg_id.lower():
                    score = 100
                elif channel_id.lower() in ch_tvg_id.lower() or ch_tvg_id.lower() in channel_id.lower():
                    score = max(score, 80)
            if ch_name_lower == channel_name_lower:
                score = max(score, 90)
            if ch_tvg_name and ch_tvg_name.lower() == channel_name_lower:
                score = max(score, 90)

            ch_name_norm = canonicalize_name(strip_noise_words(ch_name))
            ch_tvg_norm = canonicalize_name(strip_noise_words(ch_tvg_name)) if ch_tvg_name else ""
            if channel_name_norm and (ch_name_norm == channel_name_norm or ch_tvg_norm == channel_name_norm):
                score = max(score, 70)

            ch_base = ch_name_lower
            for pat in base_patterns:
                ch_base = ch_base.replace(" {pat}".format(pat=pat), "")
                ch_base = ch_base.replace("({pat})".format(pat=pat), "")
                ch_base = ch_base.replace("[{pat}]".format(pat=pat), "")
            ch_base = ch_base.strip()
            if channel_base and ch_base and channel_base == ch_base:
                score = max(score, 60)

            if channel_name_lower and (channel_name_lower in ch_name_lower or ch_name_lower in channel_name_lower):
                score = max(score, 40)
            if ch_tvg_name and channel_name_lower and (
                    channel_name_lower in ch_tvg_name.lower() or ch_tvg_name.lower() in channel_name_lower):
                score = max(score, 40)

            if channel_name_norm and ch_name_norm:
                words_epg = set(channel_name_norm.split())
                words_ch = set(ch_name_norm.split())
                if words_epg and words_ch:
                    overlap = len(words_epg & words_ch)
                    total = max(len(words_epg), len(words_ch))
                    if overlap > 0:
                        score = max(score, int(30 * overlap / total))

            if score > best_score:
                best_score = score
                matching_channel = ch

        if best_score < 30:
            return None
        return matching_channel

    def _recording_format_label(self, key: str) -> str:
        labels = {
            "provider_mkv": _("Provider quality (copy, MKV)"),
            "provider_mp4": _("Provider quality (copy, MP4)"),
            "x264_mkv": _("x264 re-encode (MKV)"),
            "x264_mp4": _("x264 re-encode (MP4)"),
            "audio_mp3_v0": _("Audio only (MP3 V0)"),
            "audio_flac": _("Audio only (FLAC)"),
            "audio_wav": _("Audio only (WAV)"),
            "audio_aac_m4a": _("Audio only (AAC, M4A)"),
            "audio_opus": _("Audio only (Opus)"),
        }
        return labels.get(key, labels[recorder.DEFAULT_RECORDING_FORMAT])

    def _schedule_window_label(self, job: Dict[str, object]) -> str:
        try:
            start_dt = datetime.datetime.fromtimestamp(float(job.get("start_ts") or 0), datetime.timezone.utc)
            stop_dt = datetime.datetime.fromtimestamp(float(job.get("stop_ts") or 0), datetime.timezone.utc)
            start_local = utc_to_local(start_dt)
            stop_local = utc_to_local(stop_dt)
            return "{start} - {end}".format(
                start=start_local.strftime("%Y-%m-%d %H:%M"),
                end=stop_local.strftime("%Y-%m-%d %H:%M"),
            )
        except Exception:
            return _("Unknown time")

    def _schedule_program_recording(self, channel: Dict[str, str], program: Dict[str, str]):
        if not channel:
            wx.MessageBox(_("Could not identify the channel."), _("Schedule Recording"), wx.OK | wx.ICON_ERROR)
            return
        try:
            fmt = normalize_recording_format(self.config.get("recording_format"))
            job = dvr.build_job(
                channel,
                program,
                fmt,
                pre_padding_minutes=self.config.get("recording_pre_padding_minutes", 0),
                post_padding_minutes=self.config.get("recording_post_padding_minutes", 2),
            )
        except Exception as err:
            wx.MessageBox(_("Could not schedule recording:\n{error}").format(error=err),
                          _("Schedule Recording"), wx.OK | wx.ICON_ERROR)
            return

        if float(job.get("stop_ts") or 0) <= time.time():
            wx.MessageBox(_("This programme has already ended."), _("Schedule Recording"),
                          wx.OK | wx.ICON_INFORMATION)
            return

        duplicate = self._find_duplicate_scheduled_job(job)
        if duplicate:
            wx.MessageBox(_("This programme is already scheduled to record."),
                          _("Schedule Recording"), wx.OK | wx.ICON_INFORMATION)
            return

        self._ensure_dvr_scheduler(start=True).add_job(job)
        wx.MessageBox(
            _("Scheduled recording:\n{title}\n{time}").format(
                title=job.get("display_title") or job.get("title") or "",
                time=self._schedule_window_label(job),
            ),
            _("Schedule Recording"), wx.OK | wx.ICON_INFORMATION)

    def _schedule_epg_program_recording(self, program: Dict[str, str]):
        channel = self._find_matching_channel_for_program(program)
        if not channel:
            wx.MessageBox(
                _("Could not find channel '{channel}' in your playlist.").format(
                    channel=program.get("channel_name", "")),
                _("Channel Not Found"),
                wx.OK | wx.ICON_WARNING,
            )
            return
        self._schedule_program_recording(channel, program)

    def _find_duplicate_scheduled_job(self, new_job: Dict[str, object]) -> Optional[Dict[str, object]]:
        new_channel = new_job.get("channel") if isinstance(new_job.get("channel"), dict) else {}
        new_key = self._channel_record_key(new_channel) if isinstance(new_channel, dict) else ""
        for job in self._ensure_dvr_scheduler().list_jobs(include_done=False):
            channel = job.get("channel") if isinstance(job.get("channel"), dict) else {}
            key = self._channel_record_key(channel) if isinstance(channel, dict) else ""
            if (key and key == new_key
                    and job.get("start_at") == new_job.get("start_at")
                    and job.get("end_at") == new_job.get("end_at")):
                return job
        return None

    def _show_scheduled_recordings(self, *_args):
        if self._dvr_dialog:
            try:
                self._dvr_dialog.refresh()
                self._dvr_dialog.Show()
                self._dvr_dialog.Raise()
                return
            except Exception:
                self._dvr_dialog = None
        self._dvr_dialog = ScheduledRecordingsDialog(self, self._ensure_dvr_scheduler(start=True))
        self._dvr_dialog.Show()

    def _on_dvr_schedule_updated(self):
        def refresh():
            dlg = getattr(self, "_dvr_dialog", None)
            if dlg:
                try:
                    dlg.refresh()
                except Exception:
                    LOG.debug("IPTVClient._on_dvr_schedule_updated.refresh: ignored exception", exc_info=True)
        wx.CallAfter(refresh)

    def _start_scheduled_recording(self, job: Dict[str, object]):
        channel = job.get("channel") if isinstance(job.get("channel"), dict) else {}
        if not channel:
            raise RuntimeError(_("Scheduled recording is missing channel data."))
        url = self._resolve_live_url(channel)
        if not url:
            raise RuntimeError(_("Could not find a stream URL for this channel."))
        fmt = normalize_recording_format(job.get("format"))
        out_dir = get_recordings_dir(self.config)
        rec = self.recorder.start(
            url,
            str(job.get("display_title") or job.get("title") or self._channel_display_name(channel)),
            fmt,
            channel_http_headers(channel),
            out_dir,
            key="dvr:{id}".format(id=job.get("id")),
            metadata={"dvr_job_id": job.get("id")},
            on_finish=self._on_recording_finished,
        )
        wx.CallAfter(
            wx.MessageBox,
            _("Scheduled recording started:\n{title}").format(
                title=job.get("display_title") or job.get("title") or ""),
            _("Scheduled Recording"),
            wx.OK | wx.ICON_INFORMATION,
        )
        return rec

    def _stop_scheduled_recording(self, job: Dict[str, object]):
        rec_id = job.get("recording_id")
        if rec_id:
            try:
                self.recorder.stop(int(rec_id))
                return
            except Exception:
                LOG.debug("IPTVClient._stop_scheduled_recording: ignored exception", exc_info=True)
        self.recorder.stop_key("dvr:{id}".format(id=job.get("id")))

    def _cancel_scheduled_recording(self, job_id: str) -> bool:
        job = self._ensure_dvr_scheduler().get_job(job_id)
        if not job:
            return False
        if job.get("status") in {dvr.STATUS_RECORDING, dvr.STATUS_STOPPING}:
            self._stop_scheduled_recording(job)
        return self._ensure_dvr_scheduler(start=True).cancel_job(job_id)

    def _record_selected(self, *_args):
        channel = self._selected_channel()
        if not channel:
            wx.MessageBox(_("Select a channel to record first."), _("Record"),
                          wx.OK | wx.ICON_INFORMATION)
            return
        self._record_channel(channel)

    def _record_channel(self, channel: Dict[str, str]):
        key = self._channel_record_key(channel)
        # Toggle: if this channel is already recording, stop it instead.
        if self.recorder.is_recording(key):
            self._stop_recording_for_channel(channel)
            return
        try:
            url = self._resolve_live_url(channel)
        except ProviderError as err:
            wx.MessageBox(_("Provider error: {error}").format(error=err),
                          _("Recording Error"), wx.OK | wx.ICON_ERROR)
            return
        except Exception as err:
            wx.MessageBox(_("Could not resolve stream URL:\n{error}").format(error=err),
                          _("Recording Error"), wx.OK | wx.ICON_ERROR)
            return
        if not url:
            wx.MessageBox(_("Could not find a stream URL for this channel."),
                          _("Recording Error"), wx.OK | wx.ICON_WARNING)
            return

        headers = channel_http_headers(channel)
        name = self._channel_display_name(channel)
        fmt = normalize_recording_format(self.config.get("recording_format"))
        out_dir = get_recordings_dir(self.config)
        try:
            rec = self.recorder.start(
                url, name, fmt, headers, out_dir,
                key=key, on_finish=self._on_recording_finished,
            )
        except Exception as err:
            wx.MessageBox(_("Could not start recording:\n{error}").format(error=err),
                          _("Recording Error"), wx.OK | wx.ICON_ERROR)
            return
        wx.MessageBox(
            _("Recording started ({fmt}):\n{path}").format(
                fmt=self._recording_format_label(fmt), path=rec.out_path),
            _("Recording"), wx.OK | wx.ICON_INFORMATION)

    def _stop_recording_for_channel(self, channel: Dict[str, str]):
        key = self._channel_record_key(channel)
        if self.recorder.stop_key(key):
            wx.MessageBox(_("Stopping recording for {name}...").format(
                name=self._channel_display_name(channel)),
                _("Recording"), wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(_("This channel is not currently recording."),
                          _("Recording"), wx.OK | wx.ICON_INFORMATION)

    def _stop_selected_recording(self, *_args):
        channel = self._selected_channel()
        if channel and self.recorder.is_recording(self._channel_record_key(channel)):
            self._stop_recording_for_channel(channel)
            return
        # Fall back: if exactly one recording is active, stop it.
        active = self.recorder.list_active()
        if len(active) == 1:
            self.recorder.stop(active[0].id)
            wx.MessageBox(_("Stopping recording..."), _("Recording"), wx.OK | wx.ICON_INFORMATION)
        elif not active:
            wx.MessageBox(_("No recordings are currently active."),
                          _("Recording"), wx.OK | wx.ICON_INFORMATION)
        else:
            self._stop_all_recordings()

    def _stop_all_recordings(self, *_args):
        count = self.recorder.stop_all()
        if count:
            wx.MessageBox(_("Stopping {count} recording(s)...").format(count=count),
                          _("Recording"), wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(_("No recordings are currently active."),
                          _("Recording"), wx.OK | wx.ICON_INFORMATION)

    def _on_recording_finished(self, rec, rc):
        job_id = None
        try:
            job_id = rec.metadata.get("dvr_job_id")
        except Exception:
            job_id = None
        if job_id:
            detail = "\n".join(rec.stderr_tail[-6:])
            suppressed = getattr(self, "_suppress_recording_notifications", False)
            self._ensure_dvr_scheduler(start=True).mark_finished(
                str(job_id),
                success=(rc == 0 and not suppressed),
                output_path=rec.out_path,
                message=("Stopped because the app exited." if suppressed else (detail if rc else "")),
            )
        if getattr(self, "_suppress_recording_notifications", False):
            return
        def report():
            if rc == 0:
                wx.MessageBox(_("Recording saved:\n{path}").format(path=rec.out_path),
                              _("Recording Complete"), wx.OK | wx.ICON_INFORMATION)
            elif rec.stopped_by_user:
                detail = "\n".join(rec.stderr_tail[-6:]) or _("No ffmpeg details were reported.")
                wx.MessageBox(
                    _("Recording stopped, but ffmpeg reported code {code}.\n\n{detail}\n\nFile:\n{path}").format(
                        code=rc, detail=detail, path=rec.out_path),
                    _("Recording Warning"), wx.OK | wx.ICON_WARNING)
            else:
                detail = "\n".join(rec.stderr_tail[-6:]) or _("No ffmpeg details were reported.")
                wx.MessageBox(
                    _("Recording of {name} ended unexpectedly (code {code}).\n\n{detail}").format(
                        name=rec.title, code=rc, detail=detail),
                    _("Recording Error"), wx.OK | wx.ICON_ERROR)
        wx.CallAfter(report)

    def _set_recording_format(self, key: str):
        self.config["recording_format"] = normalize_recording_format(key)
        save_config(self.config)

    def _open_recordings_folder(self, *_args):
        path = get_recordings_dir(self.config)
        try:
            if platform.system() == "Windows":
                os.startfile(path)  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as err:
            wx.MessageBox(_("Could not open folder:\n{error}").format(error=err),
                          _("Recordings"), wx.OK | wx.ICON_ERROR)

    def _choose_recordings_folder(self, *_args):
        current = get_recordings_dir(self.config)
        dlg = wx.DirDialog(self, _("Choose recordings folder"), defaultPath=current)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                self.config["recordings_dir"] = dlg.GetPath()
                save_config(self.config)
        finally:
            dlg.Destroy()

    def _build_recording_format_menu(self) -> wx.Menu:
        """A submenu of radio items for each recording preset (checked = active)."""
        current = normalize_recording_format(self.config.get("recording_format"))
        fmt_menu = wx.Menu()
        for key in RECORDING_FORMATS:
            item = fmt_menu.AppendRadioItem(wx.ID_ANY, self._recording_format_label(key))
            if key == current:
                item.Check(True)
            fmt_menu.Bind(wx.EVT_MENU, lambda evt, k=key: self._set_recording_format(k), item)
        return fmt_menu

    def _populate_recordings_menu(self, menu: wx.Menu):
        """Fill a Recordings menu (shared by the menubar and the Linux button menu)."""
        start_item = menu.Append(wx.ID_ANY, _("Start Recording") + "\tCtrl+Shift+R")
        menu.Bind(wx.EVT_MENU, self._record_selected, start_item)
        stop_item = menu.Append(wx.ID_ANY, _("Stop Recording"))
        menu.Bind(wx.EVT_MENU, self._stop_selected_recording, stop_item)
        stop_all_item = menu.Append(wx.ID_ANY, _("Stop All Recordings"))
        menu.Bind(wx.EVT_MENU, self._stop_all_recordings, stop_all_item)
        menu.AppendSeparator()
        schedule_item = menu.Append(wx.ID_ANY, _("Scheduled Recordings..."))
        menu.Bind(wx.EVT_MENU, self._show_scheduled_recordings, schedule_item)
        menu.AppendSeparator()
        menu.AppendSubMenu(self._build_recording_format_menu(), _("Recording Format"))
        menu.AppendSeparator()
        open_item = menu.Append(wx.ID_ANY, _("Open Recordings Folder"))
        menu.Bind(wx.EVT_MENU, self._open_recordings_folder, open_item)
        folder_item = menu.Append(wx.ID_ANY, _("Recordings Folder..."))
        menu.Bind(wx.EVT_MENU, self._choose_recordings_folder, folder_item)

    def _show_about_dialog(self, _event=None):
        """Show About dialog with app info and links."""
        from app_meta import APP_DISPLAY_NAME, APP_VERSION, GITHUB_OWNER
        
        info = wx.adv.AboutDialogInfo()
        info.SetName(APP_DISPLAY_NAME)
        info.SetVersion(APP_VERSION)
        info.SetDescription(_("A screen reader accessible IPTV client for Windows and Linux.\n\n"
                           "Supports M3U/M3U Plus playlists, Stalker Portal, XtreamCodes,\n"
                           "built-in VLC player, casting, and XMLTV EPG."))
        info.SetCopyright("© 2025-2026 Serrebi and contributors")
        info.SetWebSite(f"https://github.com/{GITHUB_OWNER}", _("GitHub Profile"))
        info.AddDeveloper("Serrebi")
        info.SetLicense(_("MIT License\n\nSee LICENSE file for details."))
        
        wx.adv.AboutBox(info)

    def _show_epg_dialog(self, channel, channel_name, programmes):
        if not programmes:
            wx.MessageBox(_("No upcoming schedule found for this channel."), _("EPG"), wx.OK | wx.ICON_INFORMATION)
            return
        dlg = ChannelEPGDialog(self, channel_name, programmes, schedule_callback=self._schedule_program_recording, channel=channel)
        dlg.ShowModal()
        dlg.Destroy()

    def on_toggle_min_to_tray(self, event):
        if platform.system() == "Linux":
            self.minimize_to_tray = not self.minimize_to_tray
        else:
            self.minimize_to_tray = self.min_to_tray_item.IsChecked()
        self.config["minimize_to_tray"] = self.minimize_to_tray
        save_config(self.config)

    def on_toggle_show_player_on_enter(self, event):
        self.show_player_on_enter = event.IsChecked()
        self.config["show_player_on_enter"] = self.show_player_on_enter
        save_config(self.config)
        if not self.show_player_on_enter:
            frame = getattr(self, "_internal_player_frame", None)
            if frame and frame.IsShown():
                frame.Hide()

    def _on_select_language(self, code: str):
        """Persist the chosen UI language and prompt for a restart to fully apply it."""
        if code == i18n.get_language():
            return
        self.config["language"] = code
        save_config(self.config)
        # Activate immediately so the confirmation (and any new dialogs) use the new language.
        i18n.set_language(code)
        wx.MessageBox(
            _("The language has been changed. Please restart Accessible IPTV Client "
              "for the change to take full effect."),
            _("Language"),
            wx.OK | wx.ICON_INFORMATION,
        )

    def on_toggle_auto_check_updates(self, event):
        self.auto_check_updates = event.IsChecked()
        self.config["auto_check_updates"] = self.auto_check_updates
        save_config(self.config)

    def on_check_updates(self, _):
        self._start_update_check(interactive=True)

    def _start_update_check(self, interactive: bool):
        if self._update_check_inflight:
            if interactive:
                wx.MessageBox(_("Update check is already running."), _("Updates"), wx.OK | wx.ICON_INFORMATION)
            return
        self._update_check_inflight = True
        threading.Thread(target=self._check_updates_worker, args=(interactive,), daemon=True).start()

    def _check_updates_worker(self, interactive: bool):
        try:
            if platform.system() != "Windows":
                raise updater.UpdateError(_("Updates are only supported on Windows builds."))
            if not getattr(sys, "frozen", False):
                raise updater.UpdateError(_("Updates are only available in the packaged build."))

            timeout = (
                _MANUAL_UPDATE_HTTP_TIMEOUT_SECONDS
                if interactive
                else _AUTO_UPDATE_HTTP_TIMEOUT_SECONDS
            )
            release = updater.fetch_latest_release(
                app_meta.GITHUB_OWNER,
                app_meta.GITHUB_REPO,
                timeout=timeout,
            )
            tag = release.get("tag_name") or ""
            latest_version = updater.normalize_version_tag(tag)
            if not latest_version:
                raise updater.UpdateError(_("Latest release tag is missing or invalid."))

            current_version = app_meta.APP_VERSION
            if not updater.is_newer_version(current_version, latest_version):
                if interactive:
                    wx.CallAfter(
                        wx.MessageBox,
                        _("{app} is up to date (v{version}).").format(
                            app=app_meta.APP_DISPLAY_NAME, version=current_version),
                        _("Updates"),
                        wx.OK | wx.ICON_INFORMATION,
                    )
                return

            notes = release.get("body") or ""
            wx.CallAfter(self._prompt_update, latest_version, current_version, notes, release)
        except updater.UpdateError as exc:
            if interactive:
                wx.CallAfter(
                    wx.MessageBox,
                    _("Update check failed: {error}").format(error=exc),
                    _("Updates"),
                    wx.OK | wx.ICON_ERROR,
                )
        finally:
            if not interactive:
                self._record_auto_update_check_attempt()
            self._update_check_inflight = False

    def _prompt_update(self, latest_version: str, current_version: str, notes: str, release: Dict):
        summary = updater.summarize_release_notes(notes)
        message = (
            _("Update available: v{latest} (current v{current}).").format(
                latest=latest_version, current=current_version)
            + "\n\n" + f"{summary}" + "\n\n"
            + _("Download and install now? The app will restart after the update.")
        )
        dlg = wx.MessageDialog(self, message, _("Update Available"), wx.YES_NO | wx.ICON_INFORMATION)
        try:
            if dlg.ShowModal() == wx.ID_YES:
                self._start_update_download(release)
        finally:
            dlg.Destroy()

    def _start_update_download(self, release: Dict):
        self._update_cancel = threading.Event()
        self._update_progress_dlg = wx.ProgressDialog(
            _("Updating {app}").format(app=app_meta.APP_DISPLAY_NAME),
            _("Starting update..."),
            maximum=100,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_SMOOTH | wx.PD_ELAPSED_TIME,
        )
        threading.Thread(target=self._download_update_worker, args=(release,), daemon=True).start()

    def _report_update_progress(self, phase: str, fraction) -> bool:
        """Progress callback for the download worker thread.

        Marshals the update to the GUI thread and returns False if the user has
        pressed Cancel so the worker can abort.
        """
        wx.CallAfter(self._apply_update_progress, phase, fraction)
        cancel = getattr(self, "_update_cancel", None)
        return not (cancel is not None and cancel.is_set())

    def _apply_update_progress(self, phase: str, fraction):
        dlg = getattr(self, "_update_progress_dlg", None)
        if not dlg:
            return
        try:
            if fraction is None:
                keep_going, _skip = dlg.Pulse(phase)
            else:
                pct = int(max(0.0, min(1.0, float(fraction))) * 100)
                keep_going, _skip = dlg.Update(pct, phase)
            if not keep_going:
                cancel = getattr(self, "_update_cancel", None)
                if cancel is not None:
                    cancel.set()
        except Exception:
            LOG.debug("IPTVClient._apply_update_progress: ignored exception", exc_info=True)

    def _destroy_update_progress(self):
        dlg = getattr(self, "_update_progress_dlg", None)
        if dlg is not None:
            try:
                dlg.Destroy()
            except Exception:
                LOG.debug("IPTVClient._destroy_update_progress: ignored exception", exc_info=True)
        self._update_progress_dlg = None

    def _download_update_worker(self, release: Dict):
        temp_root = None
        progress = self._report_update_progress
        try:
            progress(_("Checking for update details..."), None)
            manifest = updater.fetch_update_manifest(
                release,
                app_meta.UPDATE_MANIFEST_NAME,
                timeout=_MANUAL_UPDATE_HTTP_TIMEOUT_SECONDS,
            )
            if not updater.is_newer_version(app_meta.APP_VERSION, manifest.version):
                raise updater.UpdateError(_("Update manifest version is not newer than the current app."))

            temp_root = tempfile.mkdtemp(prefix="iptvclient_update_")
            if is_windows_installed_build():
                if not manifest.installer_asset_filename or not manifest.installer_download_url or not manifest.installer_sha256:
                    raise updater.UpdateError(_("Update manifest is missing required fields."))

                installer_path = os.path.join(temp_root, manifest.installer_asset_filename)
                progress(_("Downloading update..."), 0.0)
                digest = updater.download_file_with_sha256(
                    manifest.installer_download_url,
                    installer_path,
                    progress_cb=lambda fraction: progress(_("Downloading update..."), fraction),
                )
                progress(_("Verifying download..."), None)
                if digest.lower() != manifest.installer_sha256.lower():
                    raise updater.UpdateError(_("Downloaded update failed SHA-256 verification."))

                progress(_("Verifying signature..."), None)
                updater.verify_authenticode(installer_path, manifest.signing_thumbprints)

                helper_source = os.path.join(get_app_dir(), "update_helper.bat")
                helper_ps1_source = os.path.join(get_app_dir(), "update_helper.ps1")
                if not os.path.exists(helper_source):
                    helper_source = os.path.join(get_app_dir(), "_internal", "update_helper.bat")
                if not os.path.exists(helper_ps1_source):
                    helper_ps1_source = os.path.join(get_app_dir(), "_internal", "update_helper.ps1")

                if not os.path.exists(helper_source) or not os.path.exists(helper_ps1_source):
                    raise updater.UpdateError(_("Update helper is missing from this build."))

                helper_dir = os.path.join(temp_root, "helper")
                os.makedirs(helper_dir, exist_ok=True)
                helper_bat = os.path.join(helper_dir, "update_helper.bat")
                helper_ps1 = os.path.join(helper_dir, "update_helper.ps1")
                shutil.copy2(helper_source, helper_bat)
                shutil.copy2(helper_ps1_source, helper_ps1)

                progress(_("Preparing to restart..."), None)
                wx.CallAfter(
                    self._launch_installer_update_helper,
                    helper_bat,
                    os.path.dirname(sys.executable),
                    installer_path,
                    os.path.basename(sys.executable),
                )
                return

            zip_path = os.path.join(temp_root, manifest.asset_filename)
            progress(_("Downloading update..."), 0.0)
            digest = updater.download_file_with_sha256(
                manifest.download_url,
                zip_path,
                progress_cb=lambda fraction: progress(_("Downloading update..."), fraction),
            )
            progress(_("Verifying download..."), None)
            if digest.lower() != manifest.sha256.lower():
                raise updater.UpdateError(_("Downloaded update failed SHA-256 verification."))

            progress(_("Extracting update..."), None)
            extract_root = os.path.join(temp_root, "extracted")
            updater.safe_extract_zip(zip_path, extract_root)

            exe_name = os.path.basename(sys.executable)
            new_exe = updater.find_executable(extract_root, exe_name)
            if not new_exe:
                raise updater.UpdateError(_("Updated executable '{name}' not found in the package.").format(name=exe_name))

            progress(_("Verifying signature..."), None)
            updater.verify_authenticode(new_exe, manifest.signing_thumbprints)

            staging_dir = os.path.dirname(new_exe)
            install_dir = os.path.dirname(sys.executable)
            backup_dir = f"{install_dir}.bak.{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

            helper_source = os.path.join(get_app_dir(), "update_helper.bat")
            helper_ps1_source = os.path.join(get_app_dir(), "update_helper.ps1")
            
            # PyInstaller 6+ onedir layout puts datas in _internal
            if not os.path.exists(helper_source):
                helper_source = os.path.join(get_app_dir(), "_internal", "update_helper.bat")
            if not os.path.exists(helper_ps1_source):
                helper_ps1_source = os.path.join(get_app_dir(), "_internal", "update_helper.ps1")

            if not os.path.exists(helper_source) or not os.path.exists(helper_ps1_source):
                raise updater.UpdateError(_("Update helper is missing from this build."))

            helper_dir = os.path.join(temp_root, "helper")
            os.makedirs(helper_dir, exist_ok=True)
            helper_bat = os.path.join(helper_dir, "update_helper.bat")
            helper_ps1 = os.path.join(helper_dir, "update_helper.ps1")
            shutil.copy2(helper_source, helper_bat)
            shutil.copy2(helper_ps1_source, helper_ps1)

            progress(_("Preparing to restart..."), None)
            wx.CallAfter(
                self._launch_update_helper,
                helper_bat,
                install_dir,
                staging_dir,
                backup_dir,
                exe_name,
            )
        except updater.UpdateCancelled:
            wx.CallAfter(self._destroy_update_progress)
            if temp_root:
                shutil.rmtree(temp_root, ignore_errors=True)
        except updater.UpdateError as exc:
            wx.CallAfter(self._destroy_update_progress)
            wx.CallAfter(
                wx.MessageBox,
                _("Update failed: {error}").format(error=exc),
                _("Update Error"),
                wx.OK | wx.ICON_ERROR,
            )
            if temp_root:
                try:
                    shutil.rmtree(temp_root, ignore_errors=True)
                except Exception:
                    LOG.debug("IPTVClient._download_update_worker: ignored exception", exc_info=True)

    def _launch_installer_update_helper(
        self,
        helper_bat: str,
        install_dir: str,
        installer_path: str,
        exe_name: str,
    ):
        cmd = [
            "cmd",
            "/d",
            "/c",
            helper_bat,
            "-ParentPid",
            str(os.getpid()),
            "-InstallDir",
            install_dir,
            "-InstallerPath",
            installer_path,
            "-ExeName",
            exe_name,
        ]
        try:
            updater.popen_hidden(cmd, cwd=os.path.dirname(helper_bat))
        except OSError as exc:
            self._destroy_update_progress()
            wx.MessageBox(
                _("Update failed to start: {error}").format(error=exc),
                _("Update Error"),
                wx.OK | wx.ICON_ERROR,
            )
            return
        self._update_install_pending = True
        self._destroy_update_progress()
        self.Close()
    def _launch_update_helper(
        self,
        helper_bat: str,
        install_dir: str,
        staging_dir: str,
        backup_dir: str,
        exe_name: str,
    ):
        cmd = [
            "cmd",
            "/d",
            "/c",
            helper_bat,
            "-ParentPid",
            str(os.getpid()),
            "-InstallDir",
            install_dir,
            "-StagingDir",
            staging_dir,
            "-BackupDir",
            backup_dir,
            "-ExeName",
            exe_name,
        ]
        try:
            updater.popen_hidden(cmd, cwd=os.path.dirname(helper_bat))
        except OSError as exc:
            self._destroy_update_progress()
            wx.MessageBox(
                _("Update failed to start: {error}").format(error=exc),
                _("Update Error"),
                wx.OK | wx.ICON_ERROR,
            )
            return
        self._update_install_pending = True
        self._destroy_update_progress()
        self.Close()

    @staticmethod
    def _bool_pref(value, default: bool = False) -> bool:
        """Coerce config values that might be stored as bools/strings/ints."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(default)

    def show_tray_icon(self):
        self._tray_allow_restore = False
        self._cancel_tray_ready_timer()
        if not self.tray_icon:
            self.tray_icon = TrayIcon(
                self,
                on_restore=self.restore_from_tray,
                on_exit=self.exit_from_tray,
                on_player_show=self._tray_show_player,
                on_player_toggle=self._tray_toggle_play_pause,
                on_player_stop=self._tray_stop_player,
                on_cast=self._tray_cast,
                on_record_stop=self._stop_all_recordings,
            )
        self.Hide()
        self._tray_ready_timer = wx.CallLater(250, self._enable_tray_restore)

    def restore_from_tray(self):
        self._tray_allow_restore = False
        self._cancel_tray_ready_timer()
        # First, destroy the tray icon completely
        if self.tray_icon:
            try:
                self.tray_icon.RemoveIcon()
            except Exception:
                LOG.debug("IPTVClient.restore_from_tray: ignored exception", exc_info=True)
            try:
                self.tray_icon.Destroy()
            except Exception:
                LOG.debug("IPTVClient.restore_from_tray: ignored exception", exc_info=True)
            self.tray_icon = None
        # Show and restore the window
        self.Show()
        self.Iconize(False)
        self.Raise()
        # Delay focus operations to let the tray icon fully release
        wx.CallLater(150, self._complete_restore_from_tray)
    
    def _complete_restore_from_tray(self):
        """Complete restore after tray icon is destroyed."""
        # Force window to foreground using Windows API for proper focus
        self._force_foreground()
        # Set focus to channel list for screen reader accessibility
        wx.CallAfter(self._focus_channel_list)
        # Additional delayed attempt
        wx.CallLater(100, self._focus_channel_list)

    def _force_foreground(self):
        """Force window to foreground on Windows using native API."""
        if platform.system() != "Windows":
            try:
                self.SetFocus()
            except Exception:
                LOG.debug("IPTVClient._force_foreground: ignored exception", exc_info=True)
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = self.GetHandle()
            SW_RESTORE = 9
            SW_SHOW = 5
            VK_MENU = 0x12  # Alt key
            KEYEVENTF_EXTENDEDKEY = 0x0001
            KEYEVENTF_KEYUP = 0x0002
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            HWND_TOP = 0
            
            # Get our thread ID
            current_tid = kernel32.GetCurrentThreadId()
            
            # Get the foreground window's thread
            foreground_hwnd = user32.GetForegroundWindow()
            foreground_tid = user32.GetWindowThreadProcessId(foreground_hwnd, None)
            
            # Attach our thread to the foreground thread
            attached = False
            if foreground_tid and foreground_tid != current_tid:
                attached = user32.AttachThreadInput(foreground_tid, current_tid, True)
            
            # Show and restore the window
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.ShowWindow(hwnd, SW_SHOW)
            
            # Move window to top of Z-order
            user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
            
            # Simulate Alt key press to unlock foreground
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_EXTENDEDKEY, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
            
            # Set foreground and focus
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
            
            # Detach threads if we attached
            if attached:
                user32.AttachThreadInput(foreground_tid, current_tid, False)
        except Exception:
            # Fallback to wx method if Windows API fails
            try:
                self.SetFocus()
            except Exception:
                LOG.debug("IPTVClient._force_foreground: ignored exception", exc_info=True)

    def _focus_channel_list(self):
        """Set focus to channel list - used after restore from tray."""
        try:
            if self.IsShown() and not self.IsIconized():
                # Ensure window is in foreground first
                self._force_foreground()
                # Focus the channel list control
                self.channel_list.SetFocus()
                # Set a selection to ensure something is selected
                if self.channel_list.GetCount() > 0:
                    sel = self.channel_list.GetSelection()
                    if sel == wx.NOT_FOUND:
                        self.channel_list.SetSelection(0)
                        sel = 0
                    # Notify screen readers of the focus change on the list control
                    if platform.system() == "Windows":
                        try:
                            import ctypes
                            user32 = ctypes.windll.user32
                            list_hwnd = self.channel_list.GetHandle()
                            EVENT_OBJECT_FOCUS = 0x8005
                            EVENT_OBJECT_SELECTION = 0x8006
                            OBJID_CLIENT = -4
                            CHILDID_SELF = 0
                            # Fire focus event on the list
                            user32.NotifyWinEvent(EVENT_OBJECT_FOCUS, list_hwnd, OBJID_CLIENT, CHILDID_SELF)
                            # Fire selection event on the selected item (1-indexed for MSAA)
                            user32.NotifyWinEvent(EVENT_OBJECT_SELECTION, list_hwnd, OBJID_CLIENT, sel + 1)
                        except Exception:
                            LOG.debug("IPTVClient._focus_channel_list: ignored exception", exc_info=True)
        except Exception:
            LOG.debug("IPTVClient._focus_channel_list: ignored exception", exc_info=True)

    def _tray_show_player(self):
        try:
            frame = self._ensure_internal_player()
        except Exception:
            return
        frame.Enable(True)
        frame.Show()
        frame.Raise()

    def _tray_toggle_play_pause(self):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            wx.CallAfter(frame._on_toggle_pause)

    def _tray_stop_player(self):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            wx.CallAfter(lambda: frame.stop(manual=True))

    def _tray_cast(self):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            wx.CallAfter(lambda: frame._on_cast())

    def _menu_show_player(self, _=None):
        try:
            frame = self._ensure_internal_player()
        except Exception:
            return
        frame.Enable(True)
        frame.Show()
        frame.Raise()

    def _menu_toggle_player(self, _=None):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            frame._on_toggle_pause()

    def _menu_stop_player(self, _=None):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            frame.stop(manual=True)

    def _menu_cast_from_player(self, _=None):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            frame._on_cast()

    def _adjust_internal_volume(self, delta: int):
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            wx.CallAfter(frame._adjust_volume, delta)

    def exit_from_tray(self):
        self._search_token += 1
        self._populate_token += 1
        self._tray_allow_restore = False
        self._cancel_tray_ready_timer()
        if self.tray_icon:
            try:
                self.tray_icon.RemoveIcon()
            except Exception:
                LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
            self.tray_icon.Destroy()
            self.tray_icon = None
        try:
            self._stop_dvr_scheduler(wait=True)
        except Exception:
            LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
        try:
            self._suppress_recording_notifications = True
            self.recorder.stop_all(wait=True)
        except Exception:
            LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
        # Mirror on_close cleanup so the EPG poll timer can't fire into a destroyed frame
        # and executor threads don't leak when exiting from the tray.
        try:
            self._stop_epg_poll_timer()
        except Exception:
            LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
        try:
            self._cancel_epg_autostart_timer()
        except Exception:
            LOG.debug("IPTVClient.exit_from_tray: ignored exception", exc_info=True)
        if hasattr(self, "_epg_executor"):
            self._epg_executor.shutdown(wait=False)
        if self.caster:
            self.caster.stop()
        self.Destroy()

    def _enable_tray_restore(self):
        self._tray_ready_timer = None
        if self.tray_icon:
            self._tray_allow_restore = True

    def _cancel_tray_ready_timer(self):
        if self._tray_ready_timer:
            try:
                self._tray_ready_timer.Stop()
            except Exception:
                LOG.debug("IPTVClient._cancel_tray_ready_timer: ignored exception", exc_info=True)
            self._tray_ready_timer = None

    def on_minimize(self, event):
        if self.minimize_to_tray and event.IsIconized():
            wx.CallAfter(self.show_tray_icon)
        else:
            event.Skip()

    def on_close(self, event):
        if self.minimize_to_tray and not self._update_install_pending:
            wx.CallAfter(self.show_tray_icon)
            event.Veto()
        else:
            self._search_token += 1
            self._populate_token += 1
            # Ensure poll timer stopped on exit
            try:
                self._stop_epg_poll_timer()
            except Exception:
                LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
            try:
                self._cancel_epg_autostart_timer()
            except Exception:
                LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
            if hasattr(self, "_epg_executor"):
                self._epg_executor.shutdown(wait=False)
            try:
                self._stop_dvr_scheduler(wait=True)
            except Exception:
                LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
            try:
                self._suppress_recording_notifications = True
                self.recorder.stop_all(wait=True)
            except Exception:
                LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
            if self.caster:
                self.caster.stop()
            if self.tray_icon:
                try:
                    self.tray_icon.RemoveIcon()
                except Exception:
                    LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
                self.tray_icon.Destroy()
                self.tray_icon = None
            frame = getattr(self, "_internal_player_frame", None)
            if frame is not None:
                try:
                    frame.Destroy()
                except Exception:
                    LOG.debug("IPTVClient.on_close: ignored exception", exc_info=True)
                self._internal_player_frame = None
            self.Destroy()

    def _select_player(self, player):
        self.default_player = player
        self.config["media_player"] = player
        save_config(self.config)
        self._sync_player_menu_from_config()

    def _select_custom_player(self, _):
        dlg = CustomPlayerDialog(self, self.config.get("custom_player_path", ""))
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath().strip()
            if path:
                self.custom_player_path = path
                self.default_player = "Custom"
                self.config["media_player"] = "Custom"
                self.config["custom_player_path"] = path
                save_config(self.config)
        dlg.Destroy()
        self._sync_player_menu_from_config()

    def on_channel_key(self, event):
        # Kept for compatibility; EVT_KEY_DOWN handler above is the reliable path
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.play_selected()
        elif key in (wx.WXK_LEFT, wx.WXK_RIGHT):
            return
        else:
            event.Skip()

    def on_group_key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_LEFT, wx.WXK_RIGHT):
            return
        else:
            event.Skip()

    def _append_search_results_chunked(self, channels: List[Dict[str, str]], token: int):
        # Virtual list: appending is O(1) regardless of count, so no chunking is needed.
        if token != self._populate_token:
            return
        for ch in channels:
            self.displayed.append({"type": "channel", "data": ch})
        self.channel_list.set_virtual_count()
        self.epg_display.SetValue("")

    def _replace_search_results_chunked(
        self,
        entries: List[Dict[str, str]],
        search_token: int,
        populate_token: int,
    ):
        """Install broad search results in yielding, accessibility-safe batches."""
        if len(entries) <= self._SEARCH_LARGE_RESULT_THRESHOLD:
            IPTVClient._replace_displayed(self, entries)
            return

        preview_count = min(self._SEARCH_PREVIEW_COUNT, len(entries))
        IPTVClient._replace_displayed(self, entries[:preview_count])

        def append_batch(offset=preview_count):
            if getattr(self, "_search_token", 0) != search_token:
                return
            if getattr(self, "_populate_token", 0) != populate_token:
                return
            end = min(offset + self._SEARCH_BATCH_SIZE, len(entries))
            self.displayed.extend(entries[offset:end])
            self.channel_list.set_virtual_count()
            if end < len(entries):
                wx.CallLater(1, append_batch, end)

        wx.CallLater(1, append_batch)

    def _replace_displayed(self, entries: List[Dict[str, str]]):
        """Replace the virtual-list model without exposing an invalid row.

        A search result list is a new model, not an append. The native control
        can synchronously ask for item text while its item count changes, so
        ``_VirtualChannelList`` owns the ordering of the model/count update.
        Keep the small fallback for non-GUI test doubles.
        """
        replace_contents = getattr(self.channel_list, "replace_contents", None)
        if callable(replace_contents):
            replace_contents(entries)
        else:
            self.displayed = entries
            self.channel_list.set_virtual_count()

    def _should_run_epg_search(self, query: str, channel_match_count: int) -> bool:
        if not self.config.get("epg_enabled", True):
            return False
        if getattr(self, "current_group", "All Channels") != "All Channels":
            return False
        if self.epg_importing:
            return False
        if getattr(self, "_pending_epg_autostart", False):
            return False
        if getattr(self, "_epg_autostart_timer", None) is not None:
            return False
        if len(query) < self._SEARCH_EPG_MIN_CHARS:
            return False
        if channel_match_count > self._SEARCH_EPG_BROAD_CHANNEL_LIMIT:
            return False
        try:
            path = get_db_path()
            if not os.path.exists(path):
                return False
            conn = sqlite3.connect(f"file:{path}?mode=ro&cache=shared", uri=True, timeout=0.5)
            try:
                tables = {
                    row[0]
                    for row in conn.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table' AND name IN ('channels', 'programmes')
                        """
                    ).fetchall()
                }
                return not ({"channels", "programmes"} - tables)
            finally:
                conn.close()
        except Exception:
            return False

    def apply_filter(self):
        txt = self.filter_box.GetValue().strip().lower()
        if getattr(self, "view_mode", "live") == "vod":
            self._vod_apply_filter(txt)
            return
        self._populate_token += 1
        populate_token = self._populate_token
        self._search_token += 1
        search_token = self._search_token
        source = (self.all_channels if self.current_group == "All Channels"
                  else self.channels_by_group.get(self.current_group, []))
        LOG.debug("search start: %r group=%s source=%d", txt, self.current_group, len(source))
        self.epg_display.SetValue("")
        self.url_display.SetValue("")

        if not txt:
            # Rebuild current group quickly without blocking the UI
            self.on_group_select()
            return

        # Snapshot on the UI thread so the worker never races a playlist reload
        # mutating the source list in place.
        source_snapshot = list(source)

        def filter_worker():
            # The match loop and entry building over 50k-300k channels run off
            # the UI thread. While an EPG import is writing gigabytes, the disk
            # and page cache are starved enough that this work on the UI thread
            # freezes the interface (and NVDA with it); a worker thread absorbs
            # those stalls while the UI keeps pumping messages.
            matching_channels = []
            for index, ch in enumerate(source_snapshot):
                if index % 256 == 0 and getattr(self, "_search_token", 0) != search_token:
                    LOG.debug("search %r: cancelled stale channel scan", txt)
                    return
                name = (ch.get("name") or "")
                if txt and txt not in name.lower():
                    continue
                matching_channels.append(ch)
            entries = [
                {"type": "channel", "data": ch}
                for ch in matching_channels
            ]

            def apply_results():
                if getattr(self, "_search_token", 0) != search_token:
                    LOG.debug("search %r: dropped stale search token", txt)
                    return
                if getattr(self, "_populate_token", 0) != populate_token:
                    LOG.debug("search %r: dropped, list was repopulated", txt)
                    return
                # Replacing search results is different from appending asynchronous
                # EPG rows. Let the virtual list order the old/new model transition
                # so NVDA never observes a stale active child during a SetItemCount
                # shrink.
                IPTVClient._replace_search_results_chunked(
                    self, entries, search_token, populate_token
                )
                LOG.debug("search %r: %d channel matches", txt, len(matching_channels))
            wx.CallAfter(apply_results)

            # Kick off bounded EPG search only for specific channel-name searches.
            # Do not search programme titles here: a leading-wildcard title query
            # scans large XMLTV databases and causes the first-run CPU spike.
            # wx.CallAfter is FIFO, so the EPG rows queued by epg_search below
            # always land after apply_results has installed the channel rows.
            if getattr(self, "_search_token", 0) != search_token:
                LOG.debug("search %r: cancelled before EPG lookup", txt)
                return
            if not self._should_run_epg_search(txt, len(matching_channels)):
                LOG.debug("search %r: EPG search skipped", txt)
                return
            LOG.debug("search %r: EPG search started (token %d)", txt, search_token)
            epg_search(search_token, populate_token)

        def epg_search(active_search_token, active_populate_token):
            db = None
            try:
                db = EPGDatabase(get_db_path(), readonly=True)
                try:
                    if hasattr(db, "conn"):
                        db.conn.execute("PRAGMA busy_timeout=2000;")
                        db.conn.execute("PRAGMA read_uncommitted=1;")
                except Exception:
                    LOG.debug("IPTVClient.apply_filter.epg_search: ignored exception", exc_info=True)
                results = db.get_channels_with_show(
                    txt,
                    limit=self._SEARCH_EPG_RESULT_LIMIT,
                    include_title_search=False,
                )
            except Exception:
                results = []
            finally:
                try:
                    if db is not None and hasattr(db, "close"):
                        db.close()
                    elif db is not None and hasattr(db, "conn"):
                        db.conn.close()
                except Exception:
                    LOG.debug("IPTVClient.apply_filter.epg_search: ignored exception", exc_info=True)
            def update_ui():
                if getattr(self, "_search_token", 0) != active_search_token:
                    LOG.debug("EPG search %r: dropped stale search token", txt)
                    return
                if getattr(self, "_populate_token", 0) != active_populate_token:
                    LOG.debug("EPG search %r: dropped, list was repopulated", txt)
                    return
                if txt != self.filter_box.GetValue().strip().lower():
                    LOG.debug("EPG search %r: dropped, query changed", txt)
                    return
                added = 0
                for r in results:
                    chan_name = r.get('channel_name') or ""
                    show_name = r.get('show_title') or ""
                    chan_lower = chan_name.lower()
                    show_lower = show_name.lower()
                    if txt and txt not in chan_lower and txt not in show_lower:
                        continue
                    label = f"{r['channel_name']} - {r['show_title']} ({self._fmt_time(r['start'])}–{self._fmt_time(r['end'])})"
                    self.displayed.append({"type": "epg", "data": r, "label": label})
                    added += 1
                if added:
                    self.channel_list.set_virtual_count()
                # Appending to the end of a virtual list never moves the existing
                # selection, so no Select/Focus/EnsureVisible here: re-firing focus
                # events while the user is typing in the filter box confuses NVDA.
                LOG.debug("EPG search %r: appended %d results", txt, added)
            wx.CallAfter(update_ui)
        threading.Thread(target=filter_worker, daemon=True).start()

    def _refresh_group_ui(self):
        self.group_list.Freeze()
        try:
            self.group_list.Clear()
            self.channel_list.Clear()

            if not self.all_channels:
                self.group_list.Append(_("No channels found."))
                self._maybe_autostart_epg_import()
                return

            self.group_list.Append(_("All Channels") + f" ({len(self.all_channels)})")
            for grp in sorted(self.channels_by_group):
                self.group_list.Append(f"{grp} ({len(self.channels_by_group[grp])})")
            
            try:
                current_idx = self.group_list.FindString(self.current_group)
                if current_idx != wx.NOT_FOUND and self.current_group != "All Channels":
                    for i in range(self.group_list.GetCount()):
                        if self.group_list.GetString(i).startswith(f"{self.current_group} ("):
                            current_idx = i
                            break
                self.group_list.SetSelection(current_idx if current_idx != wx.NOT_FOUND else 0)
            except Exception:
                self.group_list.SetSelection(0)
        finally:
            try:
                self.group_list.Thaw()
            except Exception:
                LOG.debug("IPTVClient._refresh_group_ui: ignored exception", exc_info=True)
        
        self.on_group_select()

    # ================================================================== #
    # Video on Demand (movies & series) view
    # ================================================================== #
    def _set_view_mode(self, mode: str):
        """Switch between the live channel view and the VOD view."""
        if mode not in ("live", "vod"):
            return
        if mode == self.view_mode:
            return
        self.view_mode = mode
        self._sync_view_menu()
        # Leaving a filter behind between modes is confusing; clear it.
        try:
            self.filter_box.ChangeValue("")
        except Exception:
            LOG.debug("IPTVClient._set_view_mode: ignored exception", exc_info=True)
        if mode == "live":
            self._refresh_group_ui()
            return
        # Switching to VOD.
        if self.vod_loaded:
            self._refresh_vod_group_ui()
        else:
            self._load_vod_catalog()

    def _sync_view_menu(self):
        for attr, wanted in (("view_live_item", "live"), ("view_vod_item", "vod")):
            item = getattr(self, attr, None)
            if item is not None:
                try:
                    item.Check(self.view_mode == wanted)
                except Exception:
                    LOG.debug("IPTVClient._sync_view_menu: ignored exception", exc_info=True)

    def _load_vod_catalog(self):
        """Build the VOD catalogue in the background, then show it."""
        if self.vod_loading:
            return
        self.vod_loading = True
        self._vod_load_token += 1
        token = self._vod_load_token

        self.group_list.Freeze()
        try:
            self.group_list.Clear()
            self.channel_list.Clear()
            self.group_list.Append(_("Loading Video on Demand…"))
            self.group_list.SetSelection(0)
        finally:
            try:
                self.group_list.Thaw()
            except Exception:
                LOG.debug("IPTVClient._load_vod_catalog: ignored exception", exc_info=True)
        self.epg_display.SetValue("")
        self.url_display.SetValue("")

        clients = dict(self.provider_clients)
        m3u_channels = [
            ch for ch in self.all_channels
            if ch.get("provider-type") not in ("xtream", "stalker")
        ]

        def worker():
            catalogs = []
            try:
                for pid, client in clients.items():
                    if isinstance(client, XtreamCodesClient):
                        try:
                            catalogs.append(vod.build_xtream_catalog(client, pid))
                        except Exception:
                            continue
                if m3u_channels:
                    try:
                        catalogs.append(vod.categorize_m3u_vod(m3u_channels))
                    except Exception:
                        LOG.debug("IPTVClient._load_vod_catalog.worker: ignored exception", exc_info=True)
                order, groups = vod.merge_catalogs(catalogs)
            except Exception:
                order, groups = [], {}
            wx.CallAfter(self._on_vod_catalog_ready, token, order, groups)

        threading.Thread(target=worker, daemon=True).start()

    def _on_vod_catalog_ready(self, token: int, order: List[str], groups: Dict[str, List[Dict]]):
        if token != self._vod_load_token:
            return  # a newer load (or a switch back to live) superseded this one
        self.vod_loading = False
        self.vod_loaded = True
        self.vod_group_order = order
        self.vod_groups = groups
        if self.view_mode != "vod":
            return
        self._refresh_vod_group_ui()

    def _refresh_vod_group_ui(self):
        self.vod_current_group = None
        self._vod_series_return_group = None
        self.group_list.Freeze()
        try:
            self.group_list.Clear()
            self.channel_list.Clear()
            if not self.vod_group_order:
                self.group_list.Append(_("No Video on Demand content found."))
                self.epg_display.SetValue("")
                self.url_display.SetValue("")
                return
            for label in self.vod_group_order:
                count = len(self.vod_groups.get(label, []))
                self.group_list.Append(f"{label} ({count})")
            self.group_list.SetSelection(0)
        finally:
            try:
                self.group_list.Thaw()
            except Exception:
                LOG.debug("IPTVClient._refresh_vod_group_ui: ignored exception", exc_info=True)
        if self.vod_group_order:
            self.on_group_select()

    def _vod_on_group_select(self):
        sel = self.group_list.GetSelection()
        if sel == wx.NOT_FOUND or sel >= len(self.vod_group_order):
            return
        label = self.vod_group_order[sel]
        self.vod_current_group = label
        self._vod_series_return_group = None
        items = self.vod_groups.get(label, [])
        self._vod_show_items(items)

    def _vod_show_items(self, items: List[Dict]):
        """Render a category listing: movies play directly, series drill in."""
        displayed = []
        for it in items:
            if it.get("kind") == vod.KIND_SERIES:
                displayed.append({"type": "vod_series", "data": it,
                                  "label": it.get("name", "")})
            else:
                displayed.append({"type": "channel", "data": it})
        self._populate_token += 1
        IPTVClient._replace_displayed(self, displayed)
        if displayed:
            self.channel_list.SetSelection(0)
            if self.IsShown() and not self.IsIconized():
                self.channel_list.SetFocus()
            self.on_highlight()
        else:
            self.epg_display.SetValue("")
            self.url_display.SetValue("")

    def _vod_open_series(self, series: Dict):
        """Drill into a series: list its episodes (in order) with a Back entry."""
        self._vod_series_return_group = self.vod_current_group
        name = series.get("name", "")
        # M3U series carry their episodes inline; Xtream series load lazily.
        inline = series.get("episodes")
        if inline is not None:
            self._vod_show_episodes(name, inline)
            return

        client = self.provider_clients.get(series.get("provider-id"))
        series_id = series.get("series_id")
        if not isinstance(client, XtreamCodesClient) or series_id is None:
            wx.MessageBox(_("Could not load episodes for this series."),
                          _("Video on Demand"), wx.OK | wx.ICON_WARNING)
            return

        # Show a placeholder while episodes are fetched.
        self._populate_token += 1
        IPTVClient._replace_displayed(self, [
            {"type": "vod_back", "label": _("◄ Back")},
            {"type": "vod_info", "label": _("Loading episodes…")},
        ])
        self.channel_list.SetSelection(0)
        self.url_display.SetValue("")
        self.epg_display.SetValue("")
        token = self._vod_load_token

        def worker():
            try:
                episodes = vod.xtream_series_episodes(client, series_id, series.get("provider-id"))
            except Exception as e:
                wx.CallAfter(lambda err=e: wx.MessageBox(
                    _("Could not load episodes:\n{error}").format(error=err),
                    _("Video on Demand"), wx.OK | wx.ICON_ERROR))
                return
            wx.CallAfter(self._on_series_episodes_ready, token, name, episodes)

        threading.Thread(target=worker, daemon=True).start()

    def _on_series_episodes_ready(self, token: int, name: str, episodes: List[Dict]):
        if token != self._vod_load_token or self.view_mode != "vod":
            return
        self._vod_show_episodes(name, episodes)

    def _vod_show_episodes(self, name: str, episodes: List[Dict]):
        displayed = [{"type": "vod_back", "label": _("◄ Back")}]
        for ep in episodes:
            displayed.append({"type": "channel", "data": ep})
        self._populate_token += 1
        IPTVClient._replace_displayed(self, displayed)
        if not episodes:
            self.channel_list.SetSelection(0)
            self.epg_display.SetValue(_("No episodes found for this series."))
            self.url_display.SetValue("")
            return
        # Select the first episode (not the Back row) so playback is one keypress away.
        self.channel_list.SetSelection(1)
        if self.IsShown() and not self.IsIconized():
            self.channel_list.SetFocus()
        self.on_highlight()

    def _vod_go_back(self):
        label = self._vod_series_return_group or self.vod_current_group
        self._vod_series_return_group = None
        if label and label in self.vod_groups:
            self.vod_current_group = label
            self._vod_show_items(self.vod_groups.get(label, []))
        else:
            self._refresh_vod_group_ui()

    def _vod_apply_filter(self, txt: str):
        """Substring-filter the current VOD category by item name."""
        if not self.vod_current_group:
            return
        items = self.vod_groups.get(self.vod_current_group, [])
        if not txt:
            self._vod_show_items(items)
            return
        needle = txt.lower()
        filtered = [it for it in items if needle in (it.get("name", "").lower())]
        self._vod_show_items(filtered)

    def reload_epg_sources(self):
        base = list(self.config.get("epgs", []))
        for epg in getattr(self, "provider_epg_sources", []):
            if epg not in base:
                base.append(epg)
        self.epg_sources = base

    def _hash_epg_sources(self, sources: List[str]) -> str:
        normalized = []
        for src in sources:
            if isinstance(src, str):
                normalized.append(src.strip())
            else:
                try:
                    normalized.append(json.dumps(src, sort_keys=True))
                except Exception:
                    normalized.append(str(src))
        normalized.sort()
        payload = "|".join(normalized).encode("utf-8", "ignore")
        return hashlib.sha1(payload).hexdigest()

    def _get_epg_auto_interval_seconds(self) -> float:
        raw = self.config.get("epg_auto_import_interval_hours", 6.0)
        try:
            hours = float(raw)
        except Exception:
            hours = 6.0
        if hours <= 0:
            return 0.0
        return hours * 3600.0

    def _should_auto_import_epg(self, sources: List[str]) -> bool:
        interval = self._get_epg_auto_interval_seconds()
        if interval <= 0:
            return True
        try:
            last_hash = self.config.get("epg_last_sources_hash", "")
        except Exception:
            last_hash = ""
        current_hash = self._hash_epg_sources(sources)
        if current_hash and current_hash != last_hash:
            return True
        db_path = get_db_path()
        if not epg_database_has_usable_data(db_path):
            return True
        try:
            last_import = float(self.config.get("epg_last_import_epoch", 0) or 0)
        except Exception:
            last_import = 0.0
        now = time.time()
        if last_import <= 0 or last_import > now + 300:
            return True
        return (now - last_import) >= interval

    def _cancel_epg_autostart_timer(self):
        if self._epg_autostart_timer:
            try:
                self._epg_autostart_timer.Stop()
            except Exception:
                LOG.debug("IPTVClient._cancel_epg_autostart_timer: ignored exception", exc_info=True)
            self._epg_autostart_timer = None

    def _schedule_epg_autostart(self, token: int, delay_ms: int = 5000):
        def _fire():
            if token != self._playlist_load_token:
                return
            self._epg_autostart_timer = None
            self.start_epg_import_background()
        self._cancel_epg_autostart_timer()
        self._epg_autostart_timer = wx.CallLater(delay_ms, _fire)

    def _maybe_autostart_epg_import(self):
        if not self._pending_epg_autostart:
            return
        if self._pending_epg_autostart_token != self._playlist_load_token:
            return
        self._pending_epg_autostart = False
        self._schedule_epg_autostart(self._pending_epg_autostart_token)

    def start_epg_import_background(self, *, force: bool = False):
        sources = list(self.epg_sources)
        if not sources or not self.config.get("epg_enabled", True):
            return
        if self.epg_importing:
            return
        if not force and not self._should_auto_import_epg(sources):
            return
        self.epg_importing = True

        # Start a short poll timer so UI can show EPG as it arrives for the selected channel.
        wx.CallAfter(self._start_epg_poll_timer)

        def do_import():
            _lower_current_thread_priority()
            success = False
            try:
                db = EPGDatabase(get_db_path(), for_threading=True)
                # Pass a coarse progress callback (per-source). The DB importer writes as it streams,
                # so readers can pick up newly inserted rows during import.
                db.import_epg_xml(sources)
                success = True
                try:
                    if hasattr(db, "close"):
                        db.close()
                    elif hasattr(db, "conn"):
                        db.conn.close()
                except Exception:
                    LOG.debug("IPTVClient.start_epg_import_background.do_import: ignored exception", exc_info=True)
            except Exception:
                LOG.debug("IPTVClient.start_epg_import_background.do_import: ignored exception", exc_info=True)
            finally:
                wx.CallAfter(self.finish_import_background, success)
        threading.Thread(target=do_import, daemon=True).start()

    def finish_import_background(self, success: bool = False):
        self.epg_importing = False
        # Stop import-specific polling and restart steady refresh timer
        self._stop_epg_poll_timer()
        with self.epg_cache_lock:
            self.epg_cache.clear()
        # Clear match cache as IDs/channels may have changed in the DB
        with self._epg_match_lock:
            self._epg_match_cache.clear()
        if success:
            try:
                self.config["epg_last_import_epoch"] = int(time.time())
                self.config["epg_last_sources_hash"] = self._hash_epg_sources(self.epg_sources)
                save_config(self.config)
            except Exception:
                LOG.debug("IPTVClient.finish_import_background: ignored exception", exc_info=True)
        self.on_highlight()
        self._start_epg_poll_timer()

    def show_manager(self, _):
        dlg = PlaylistManagerDialog(self, self.playlist_sources)
        if dlg.ShowModal() == wx.ID_OK:
            self.playlist_sources = dlg.GetResult()
            self.config["playlists"] = self.playlist_sources
            save_config(self.config)
            self.start_playlist_load() # Reload everything after changes
        dlg.Destroy()

    def show_epg_manager(self, _):
        dlg = EPGManagerDialog(self, self.epg_sources)
        if dlg.ShowModal() == wx.ID_OK:
            self.epg_sources = dlg.GetResult()
            self.config["epgs"] = self.epg_sources
            save_config(self.config)
            self.reload_epg_sources()
            wx.CallLater(1000, lambda: self.start_epg_import_background(force=True)) # Start import after dialog closes
        dlg.Destroy()

    def show_account_info(self, _event):
        """Show subscription status for configured and autodetected accounts."""
        # Discovery walks every loaded channel URL to autodetect accounts that
        # were never added through the Xtream dialog, so keep it off the UI thread.
        sources = list(self.playlist_sources or [])
        channels = self.all_channels

        def worker():
            error = None
            accounts = []
            try:
                accounts = account_info.discover_accounts(sources, channels)
            except Exception as e:
                error = str(e)
                LOG.debug("show_account_info: discovery failed", exc_info=True)
            wx.CallAfter(self._present_account_info, accounts, error)

        threading.Thread(target=worker, daemon=True).start()

    def _present_account_info(self, accounts, error):
        if error is not None:
            wx.MessageBox(
                _("Could not look for provider accounts: {error}").format(error=error),
                _("Error"), wx.OK | wx.ICON_ERROR)
            return
        if not accounts:
            wx.MessageBox(
                _("No provider accounts were found.\n\n"
                  "Xtream Codes and Stalker Portal accounts added in the Playlist Manager "
                  "are listed here, along with any account detected from a playlist or "
                  "stream URL."),
                _("No Accounts"), wx.OK | wx.ICON_INFORMATION)
            return
        dlg = AccountInfoDialog(self, accounts)
        dlg.ShowModal()
        dlg.Destroy()

    def import_epg(self, _event):
        if self.epg_importing:
            wx.MessageBox(_("EPG import is already in progress."), _("In Progress"), wx.OK | wx.ICON_INFORMATION)
            return

        if not self.epg_sources:
            wx.MessageBox(_("No EPG sources configured. Please add one in File > EPG Manager."), _("No Sources"), wx.OK | wx.ICON_WARNING)
            return

        wx.MessageBox(_("EPG import will start in the background."), _("Import Started"), wx.OK | wx.ICON_INFORMATION)
        self.start_epg_import_background(force=True)

    def show_whats_on_now(self, _event):
        """Show dialog with all currently airing programs."""
        if not self.config.get("epg_enabled", True):
            wx.MessageBox(_("EPG is not enabled."), _("EPG Not Available"), wx.OK | wx.ICON_WARNING)
            return

        # Fetching every currently-airing programme can touch a lot of rows on a large EPG,
        # so do the DB work on a background thread and present the dialog when it's ready.
        def worker():
            error = None
            programs = []
            try:
                db = EPGDatabase(get_db_path(), readonly=True)
                try:
                    programs = db.get_all_now_playing()
                finally:
                    db.close()
            except Exception as e:
                error = e
            wx.CallAfter(self._present_whats_on_now, programs, error)

        threading.Thread(target=worker, daemon=True).start()

    def _present_whats_on_now(self, programs, error):
        if error is not None:
            wx.MessageBox(_("Failed to fetch EPG data: {error}").format(error=error), _("Error"), wx.OK | wx.ICON_ERROR)
            return
        if not programs:
            wx.MessageBox(_("No programs are currently airing, or EPG data has not been imported yet."), _("No Data"), wx.OK | wx.ICON_INFORMATION)
            return

        dlg = WhatsOnNowDialog(self, programs, schedule_callback=self._schedule_epg_program_recording)
        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.get_selection()
            if selection:
                self._play_from_whats_on_now(selection)
        dlg.Destroy()
    
    def _play_from_whats_on_now(self, program: Dict[str, str]):
        """Find and play the channel matching the selected program."""
        channel_name = program.get("channel_name", "")
        channel_id = program.get("channel_id", "")
        
        if not channel_name and not channel_id:
            wx.MessageBox(_("Could not identify the channel."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        matching_channel = self._find_matching_channel_for_program(program)
        if not matching_channel:
            wx.MessageBox(_("Could not find channel '{channel}' in your playlist.").format(channel=channel_name), _("Channel Not Found"), wx.OK | wx.ICON_WARNING)
            return

        # Find and select the channel in the currently displayed list
        for idx, item in enumerate(self.displayed):
            if item.get("type") == "channel":
                ch = item.get("data", {})
                if ch.get("url") == matching_channel.get("url"):
                    self.channel_list.SetSelection(idx)
                    # Use CallAfter to ensure UI updates before play
                    wx.CallAfter(self.play_selected)
                    return
        
        # Channel exists but not in current filter - switch to All Channels and try again
        self.group_list.SetSelection(0)  # "All Channels" is first
        self.on_group_select()
        wx.CallLater(100, lambda: self._select_and_play_channel(matching_channel))
    
    def _select_and_play_channel(self, channel: Dict[str, str]):
        """Helper to select and play a channel after group switch."""
        for idx, item in enumerate(self.displayed):
            if item.get("type") == "channel":
                ch = item.get("data", {})
                if ch.get("url") == channel.get("url"):
                    self.channel_list.SetSelection(idx)
                    wx.CallAfter(self.play_selected)
                    return

    def _parse_m3u_return(self, text, provider_info=None):
        provider_info = provider_info or {}
        provider_id = provider_info.get("provider-id")
        provider_type = provider_info.get("provider-type")

        out: List[Dict[str, str]] = []
        append = out.append
        stream_id_for = self._extract_stream_id
        attr_iter = _M3U_ATTR_RE.finditer

        # Per-channel metadata, reset after each URL
        name = ""
        group = ""
        tvg_id = ""
        tvg_name = ""
        tvg_logo = ""
        tvg_rec = ""
        timeshift = ""
        catchup = ""
        catchup_type = ""
        catchup_days = ""
        catchup_source = ""
        catchup_offset = ""
        http_user_agent = ""
        http_referrer = ""
        http_origin = ""
        http_cookie = ""
        http_headers: List[str] = []
        http_auth = ""
        http_accept = ""

        for raw_line in text.splitlines():
            s = raw_line.strip()
            if not s:
                continue

            if s[0] == '#':
                upper_prefix = s[:10].upper()
                if upper_prefix.startswith("#EXTINF"):
                    name = ""
                    group = ""
                    tvg_id = ""
                    tvg_name = ""
                    tvg_logo = ""
                    tvg_rec = ""
                    timeshift = ""
                    catchup = ""
                    catchup_type = ""
                    catchup_days = ""
                    catchup_source = ""
                    catchup_offset = ""
                    http_user_agent = ""
                    http_referrer = ""
                    http_origin = ""
                    http_cookie = ""
                    http_headers = []
                    http_auth = ""
                    http_accept = ""

                    comma_idx = _extinf_name_comma(s)
                    info_part = s if comma_idx == -1 else s[:comma_idx]
                    if comma_idx != -1:
                        name = s[comma_idx + 1:].strip()

                    colon_idx = info_part.find(':')
                    attr_segment = info_part[colon_idx + 1:] if colon_idx != -1 else ""
                    if attr_segment:
                        attrs: Dict[str, str] = {}
                        for match in attr_iter(attr_segment):
                            key = match.group(1).lower()
                            value = match.group(2) or match.group(3) or match.group(4) or ""
                            if key not in attrs:
                                attrs[key] = value.strip()
                        if attrs:
                            group = attrs.get("group-title", "")
                            tvg_id = attrs.get("tvg-id", "")
                            tvg_name = attrs.get("tvg-name", "")
                            tvg_logo = attrs.get("tvg-logo") or attrs.get("logo") or ""
                            tvg_rec = attrs.get("tvg-rec", "")
                            timeshift = attrs.get("timeshift", "")
                            catchup = attrs.get("catchup", "")
                            catchup_type = attrs.get("catchup-type", "")
                            catchup_days = attrs.get("catchup-days", "")
                            catchup_source = attrs.get("catchup-source", "")
                            catchup_offset = attrs.get("catchup-offset", "")
                            http_user_agent = attrs.get("http-user-agent", "")
                            http_referrer = attrs.get("http-referrer") or attrs.get("http-referer", http_referrer)
                            http_origin = attrs.get("http-origin", http_origin)
                            http_cookie = attrs.get("http-cookie", http_cookie)
                            http_auth = attrs.get("http-authorization", http_auth)
                            http_accept = attrs.get("http-accept", http_accept)
                    continue

                if upper_prefix.startswith("#EXTVLCOPT"):
                    colon_idx = s.find(':')
                    if colon_idx != -1:
                        data = s[colon_idx + 1:]
                        eq_idx = data.find('=')
                        if eq_idx != -1:
                            key = data[:eq_idx].strip().lower()
                            value = data[eq_idx + 1:].strip()
                            if key in {"catchup-source", "catchup_url"}:
                                catchup_source = value
                            elif key == "catchup-days":
                                catchup_days = value
                            elif key == "catchup-type":
                                catchup_type = value
                            elif key == "http-user-agent":
                                http_user_agent = value
                            elif key in {"http-referrer", "http-referer", "referer", "referrer"}:
                                http_referrer = value
                            elif key in {"http-origin", "origin"}:
                                http_origin = value
                            elif key in {"http-cookie", "cookie"}:
                                http_cookie = value
                            elif key in {"http-authorization", "authorization", "auth"}:
                                http_auth = value
                            elif key in {"http-accept", "accept"}:
                                http_accept = value
                            elif key.startswith("http-header"):
                                if value:
                                    http_headers.append(value)
                    continue

                if upper_prefix.startswith("#KODIPROP"):
                    colon_idx = s.find(':')
                    if colon_idx != -1:
                        data = s[colon_idx + 1:]
                        eq_idx = data.find('=')
                        if eq_idx != -1:
                            key = data[:eq_idx].strip().lower()
                            value = data[eq_idx + 1:].strip()
                            if key.endswith("catchup_days"):
                                catchup_days = value
                            elif key.endswith("catchup_source"):
                                catchup_source = value
                            elif key in {"http-referrer", "http-referer", "referer", "referrer"}:
                                http_referrer = value
                            elif key in {"http-origin", "origin"}:
                                http_origin = value
                            elif key in {"http-cookie", "cookie"}:
                                http_cookie = value
                            elif key in {"http-authorization", "authorization", "auth"}:
                                http_auth = value
                            elif key in {"http-accept", "accept"}:
                                http_accept = value
                    continue

                # Other comment/directive lines are ignored
                continue

            url = s
            # Channels with no explicit group-title fall to "Uncategorized"
            # (see the `ch.get("group") or "Uncategorized"` grouping below) rather
            # than being bucketed by a country code guessed from the name. That
            # guessing produced confusing giant "us"/"ca" groups that mixed
            # unrelated channels and swept in malformed entries.
            grp_value = group
            channel = {
                "name": name,
                "group": grp_value,
                "url": url,
                "tvg-id": tvg_id,
                "tvg-name": tvg_name,
            }
            if provider_id:
                channel["provider-id"] = provider_id
            if provider_type:
                channel["provider-type"] = provider_type
            if tvg_logo:
                channel["tvg-logo"] = tvg_logo
            if tvg_rec:
                channel["tvg-rec"] = tvg_rec
            if timeshift:
                channel["timeshift"] = timeshift
            if catchup:
                channel["catchup"] = catchup
            if catchup_type:
                channel["catchup-type"] = catchup_type
            if catchup_days:
                channel["catchup-days"] = catchup_days
            if catchup_source:
                channel["catchup-source"] = catchup_source
            if catchup_offset:
                channel["catchup-offset"] = catchup_offset
            if http_user_agent:
                channel["http-user-agent"] = http_user_agent
            if http_referrer:
                channel["http-referrer"] = http_referrer
            if http_origin:
                channel["http-origin"] = http_origin
            if http_cookie:
                channel["http-cookie"] = http_cookie
            if http_auth:
                channel["http-authorization"] = http_auth
            if http_accept:
                channel["http-accept"] = http_accept
            if http_headers:
                # Preserve header order but drop duplicates case-insensitively.
                seen_headers = set()
                unique_headers: List[str] = []
                for hdr in http_headers:
                    key_lower = hdr.split(":", 1)[0].strip().lower() if ":" in hdr else hdr.lower()
                    if key_lower in seen_headers:
                        continue
                    seen_headers.add(key_lower)
                    unique_headers.append(hdr)
                channel["http-headers"] = unique_headers

            if provider_type == "xtream" or catchup_source:
                stream_id = stream_id_for(url)
                if stream_id:
                    channel["stream-id"] = stream_id

            append(channel)

            # Clear state after emitting the channel entry
            name = ""
            group = ""
            tvg_id = ""
            tvg_name = ""
            tvg_logo = ""
            tvg_rec = ""
            timeshift = ""
            catchup = ""
            catchup_type = ""
            catchup_days = ""
            catchup_source = ""
            catchup_offset = ""
            http_user_agent = ""
            http_referrer = ""
            http_origin = ""
            http_cookie = ""
            http_headers = []
            http_auth = ""
            http_accept = ""

        return out

    def _playlist_text_hash(self, text: str) -> str:
        if not text:
            return ""
        return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()

    def _parsed_cache_path_for_key(self, key: str) -> str:
        digest = hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest()
        cache_dir = get_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"parsed_{digest}.json")

    def _read_cached_playlist_file(
        self, cache_path: str
    ) -> Tuple[Optional[str], Optional[List[Dict[str, str]]]]:
        """Raw (hash, channels) read of a parsed-cache JSON file, no hash check/mutation.
        Split out of _load_cached_playlist so callers that already have the parsed
        result (e.g. the playlist-load prefill pass) can share it instead of paying
        for the disk read + JSON decode a second time."""
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            channels = data.get("channels")
            if not isinstance(channels, list):
                return None, None
            return data.get("hash"), channels
        except Exception:
            return None, None

    def _apply_cached_provider_meta(self, channels: List[Dict[str, str]], provider_meta: Optional[Dict[str, str]]) -> None:
        if not provider_meta:
            return
        pid = provider_meta.get("provider-id")
        ptype = provider_meta.get("provider-type")
        if not pid and not ptype:
            return
        for ch in channels:
            if pid:
                ch["provider-id"] = pid
            if ptype:
                ch["provider-type"] = ptype

    def _load_cached_playlist(
        self,
        cache_path: str,
        text_hash: Optional[str],
        provider_meta: Optional[Dict[str, str]] = None,
        skip_hash: bool = False,
    ) -> Optional[List[Dict[str, str]]]:
        try:
            stored_hash, channels = self._read_cached_playlist_file(cache_path)
            if channels is None:
                return None
            if not skip_hash and text_hash is not None and stored_hash != text_hash:
                return None
            self._apply_cached_provider_meta(channels, provider_meta)
            return channels
        except Exception:
            return None

    def _store_cached_playlist(
        self,
        cache_path: str,
        text_hash: str,
        channels: List[Dict[str, str]],
        provider_meta: Optional[Dict[str, str]] = None,
    ) -> None:
        payload = {"hash": text_hash, "channels": channels}
        if provider_meta:
            payload["provider"] = provider_meta
        tmp_path = cache_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
            os.replace(tmp_path, cache_path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                LOG.debug("IPTVClient._store_cached_playlist: ignored exception", exc_info=True)

    def _extract_stream_id(self, url: str) -> str:
        try:
            path = urllib.parse.urlparse(url).path
        except Exception:
            path = ""
        if not path:
            return ""
        parts = [p for p in path.split("/") if p]
        if not parts:
            return ""
        last = parts[-1]
        m = re.match(r"(\d+)", last)
        if m:
            return m.group(1)
        if len(parts) >= 2:
            m = re.match(r"(\d+)", parts[-2])
            if m:
                return m.group(1)
        return ""

    def on_group_select(self):
        if getattr(self, "view_mode", "live") == "vod":
            self._vod_on_group_select()
            return
        sel = self.group_list.GetSelection()
        all_label = _("All Channels")
        label = self.group_list.GetString(sel) if sel != wx.NOT_FOUND else all_label
        # "All Channels" is the internal sentinel; match either the translated label
        # (current UI language) or the English source (e.g. config from another locale).
        if label.startswith(all_label) or label.startswith("All Channels"):
            grp = "All Channels"
        else:
            grp = label.split(" (", 1)[0]
        self.current_group = grp

        source = self.all_channels if grp == "All Channels" else self.channels_by_group.get(grp, [])
        self._populate_channel_list_chunked(source)

    def _populate_channel_list_chunked(self, source: List[Dict[str, str]]):
        self._populate_token += 1

        IPTVClient._replace_displayed(self, [
            {"type": "channel", "data": ch}
            for ch in source
        ])

        if not source:
            self.epg_display.SetValue("")
            self.url_display.SetValue("")
            self._maybe_autostart_epg_import()
            return

        self.channel_list.SetSelection(0)
        # Only set focus if window is visible (avoid stealing focus from tray)
        if self.IsShown() and not self.IsIconized():
            self.channel_list.SetFocus()
        self.on_highlight()
        self._maybe_autostart_epg_import()

    def _fmt_time(self, s):
        # s: "YYYYMMDDHHMMSS" (UTC)
        try:
            dt = datetime.datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            local = utc_to_local(dt)
            return local.strftime("%H:%M")
        except Exception:
            return "?"

    def _utc_now(self) -> datetime.datetime:
        try:
            return datetime.datetime.now(datetime.timezone.utc)
        except Exception:
            return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    def _ensure_utc_dt(self, value: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
        if not isinstance(value, datetime.datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc)

    def _epg_cache_needs_refresh(self, now_show, next_show, cached_at: Optional[datetime.datetime]) -> bool:
        now_utc = self._utc_now()

        cached_utc = None
        if isinstance(cached_at, datetime.datetime):
            if cached_at.tzinfo is None:
                try:
                    # Assume legacy entries were stored as local time; best-effort convert to UTC.
                    cached_utc = cached_at.replace(tzinfo=datetime.timezone.utc)
                except Exception:
                    cached_utc = None
            else:
                cached_utc = cached_at.astimezone(datetime.timezone.utc)

        if cached_utc is None:
            return True

        if (now_utc - cached_utc).total_seconds() >= self._CACHE_REFRESH_AFTER_SECS:
            return True

        if not now_show and not next_show:
            # No guide yet; re-query soon so a subsequent provider import can populate it.
            if (now_utc - cached_utc).total_seconds() >= 30:
                return True

        if now_show:
            end_utc = self._ensure_utc_dt(now_show.get('end'))
            if end_utc and now_utc >= end_utc - datetime.timedelta(seconds=15):
                return True
        if not now_show and next_show:
            start_utc = self._ensure_utc_dt(next_show.get('start'))
            if start_utc and now_utc >= start_utc - datetime.timedelta(seconds=15):
                return True

        return False

    def on_highlight(self):
        # Allow viewing cached or currently available EPG even while an import is running.
        i = self.channel_list.GetSelection()
        if i < 0 or i >= len(self.displayed):
            self.url_display.SetValue("")
            return
        item = self.displayed[i]
        if item["type"] == "vod_series":
            self.url_display.SetValue("")
            self.epg_display.SetValue(
                _("Series: {name} — press Enter to browse episodes.").format(
                    name=item["data"].get("name", "")))
            return
        if item["type"] == "vod_back":
            self.url_display.SetValue("")
            self.epg_display.SetValue(_("Press Enter to go back."))
            return
        if item["type"] == "vod_info":
            self.url_display.SetValue("")
            return
        if item["type"] == "channel":
            ch = item["data"]
            self.url_display.SetValue(ch.get("url", ""))
            cname = ch.get("name", "")

            # VOD movie/episode rows have no live EPG; skip the DB lookups.
            if getattr(self, "view_mode", "live") == "vod":
                self.epg_display.SetValue("")
                return

            if not self.config.get("epg_enabled", True):
                self.epg_display.SetValue("EPG is disabled in configuration.")
                return

            self._start_epg_poll_timer()

            # If this channel is exempt (likely has no EPG), show a clear message and do not fetch.
            if self._channel_is_epg_exempt(ch):
                self.epg_display.SetValue("No EPG data for this channel.")
                return

            key = canonicalize_name(cname)
            with self.epg_cache_lock:
                cached = self.epg_cache.get(key)
            if cached:
                now_show, next_show, ts = cached
                needs_refresh = self._epg_cache_needs_refresh(now_show, next_show, ts)
                if needs_refresh:
                    with self._epg_inflight_lock:
                        if key not in self._epg_fetch_inflight:
                            threading.Thread(target=self._fetch_and_cache_epg, args=(ch, cname), daemon=True).start()
                msg = self._epg_msg_from_tuple(now_show, next_show)
                if needs_refresh:
                    msg += "\n\nUpdating EPG..."
                # If an import is running, indicate that data may still be arriving.
                if self.epg_importing:
                    msg = msg + "\n\nNote: EPG import in progress — newer program data may still arrive."
                self.epg_display.SetValue(msg)
            else:
                # No cached entry: fetch what exists now (reader connection to DB).
                with self._epg_inflight_lock:
                    already = canonicalize_name(cname) in self._epg_fetch_inflight
                    if not already:
                        threading.Thread(target=self._fetch_and_cache_epg, args=(ch, cname), daemon=True).start()
                # Provide placeholder while we wait for DB read.
                placeholder = "Loading EPG for this channel…"
                if self.epg_importing:
                    placeholder += "\n\nEPG import in progress — displaying available data as it arrives."
                self.epg_display.SetValue(placeholder)
        elif item["type"] == "epg":
            self.url_display.SetValue("")
            r = item["data"]
            url = ""
            target_norm = canonicalize_name(r.get("channel_name", ""))
            for ch in self.all_channels:
                if canonicalize_name(ch.get("name", "")) == target_norm:
                    url = ch.get("url", "")
                    break
            msg = (
                f"Show: {r.get('show_title', '')} | Channel: {r.get('channel_name', '')} | "
                f"Start: {self._fmt_time(r.get('start', ''))} | End: {self._fmt_time(r.get('end', ''))}"
            )
            if self.epg_importing:
                msg = msg + "\n\nNote: EPG import in progress — data may still be updating."
            self.epg_display.SetValue(msg)
            self.url_display.SetValue(url)

    def _epg_msg_from_tuple(self, now, nxt):
        def localfmt(dt):
            local = utc_to_local(dt)
            return local.strftime('%H:%M')
        msg = ""
        if now:
            msg += f"Now: {now['title']} ({localfmt(now['start'])} – {localfmt(now['end'])})"
        elif nxt:
            msg += f"Starts at {localfmt(nxt['start'])}: {nxt['title']}"
        else:
            msg += "No program currently airing."
        if nxt:
            msg += f"\nNext: {nxt['title']} ({localfmt(nxt['start'])} – {localfmt(nxt['end'])})"
        return msg

    def _fetch_and_cache_epg(self, channel, cname):
        key = canonicalize_name(cname)
        with self._epg_inflight_lock:
            if key in self._epg_fetch_inflight:
                return
            self._epg_fetch_inflight.add(key)

        def _do_work():
            try:
                if self._channel_is_epg_exempt(channel):
                    return None, None
                
                db = EPGDatabase(get_db_path(), readonly=True)
                try:
                    # Check match cache first
                    with self._epg_match_lock:
                        cached_id = self._epg_match_cache.get(key)
                    if cached_id is None:
                        # Resolve outside the lock so workers don't serialize on DB I/O
                        cached_id = db.resolve_best_channel_id(channel)
                        # Cache even if None to avoid repeated expensive misses
                        with self._epg_match_lock:
                            self._epg_match_cache[key] = cached_id or ""
                    
                    # If we have a valid ID (and it's not the empty string marker for 'no match')
                    if cached_id:
                        return db.get_now_next_by_id(cached_id)
                    return None
                finally:
                    db.close()
            except Exception:
                return None

        def _on_done(future):
            try:
                now_next = future.result()
            except Exception:
                now_next = None
            
            with self._epg_inflight_lock:
                try:
                    self._epg_fetch_inflight.discard(key)
                except Exception:
                    LOG.debug("IPTVClient._fetch_and_cache_epg._on_done: ignored exception", exc_info=True)

            if not now_next:
                now_show, next_show = None, None
            else:
                now_show, next_show = now_next

            with self.epg_cache_lock:
                self.epg_cache[key] = (now_show, next_show, self._utc_now())
            
            wx.CallAfter(self._update_epg_display_if_selected, channel, now_show, next_show)

        # Submit to executor instead of spawning raw thread
        self._epg_executor.submit(_do_work).add_done_callback(_on_done)

    def _update_epg_display_if_selected(self, channel, now_show, next_show):
        i = self.channel_list.GetSelection()
        if 0 <= i < len(self.displayed):
            item = self.displayed[i]
            if item["type"] == "channel" and canonicalize_name(item["data"].get("name", "")) == canonicalize_name(channel.get("name", "")):
                if self._channel_is_epg_exempt(channel) and not (now_show or next_show):
                    msg = "No EPG data for this channel."
                else:
                    msg = self._epg_msg_from_tuple(now_show, next_show)
                if self.epg_importing:
                    msg = msg + "\n\nNote: EPG import in progress — newer program data may still arrive."
                self.epg_display.SetValue(msg)

    def _start_epg_poll_timer(self):
        try:
            if self._epg_poll_timer:
                return
            self._epg_poll_timer = wx.Timer(self)
            # Bind with timer as source so we can unbind cleanly later
            self.Bind(wx.EVT_TIMER, self._on_epg_poll_timer, self._epg_poll_timer)
            # Poll less aggressively to avoid repeated expensive matching while importer churns.
            self._epg_poll_timer.Start(8000, wx.TIMER_CONTINUOUS)  # 8s
        except Exception:
            self._epg_poll_timer = None

    def _stop_epg_poll_timer(self):
        try:
            if self._epg_poll_timer:
                try:
                    self._epg_poll_timer.Stop()
                except Exception:
                    LOG.debug("IPTVClient._stop_epg_poll_timer: ignored exception", exc_info=True)
                # Unbind the specific handler for this timer source to avoid removing other EVT_TIMER bindings.
                try:
                    # Unbind signature: Unbind(event, source=timer, handler=callable)
                    self.Unbind(wx.EVT_TIMER, handler=self._on_epg_poll_timer, source=self._epg_poll_timer)
                except Exception:
                    # Fallback: attempt to unbind by event only (best-effort)
                    try:
                        self.Unbind(wx.EVT_TIMER, handler=self._on_epg_poll_timer)
                    except Exception:
                        LOG.debug("IPTVClient._stop_epg_poll_timer: ignored exception", exc_info=True)
                self._epg_poll_timer = None
        except Exception:
            self._epg_poll_timer = None

    def _on_epg_poll_timer(self, event):
        # Only refresh the currently highlighted channel (cheap, targeted).
        try:
            # Skip background polling when the window is hidden/minimised to avoid idle CPU use.
            if not self.IsShownOnScreen() or self.IsIconized():
                return
            i = self.channel_list.GetSelection()
            if i < 0 or i >= len(self.displayed):
                return
            item = self.displayed[i]
            if item["type"] != "channel":
                return
            ch = item["data"]
            # Skip channels that likely have no EPG to avoid repeated DB probes/log spam.
            if self._channel_is_epg_exempt(ch):
                return
            cname = ch.get("name", "")
            key = canonicalize_name(cname)
            with self.epg_cache_lock:
                cached = self.epg_cache.get(key)
            if cached:
                now_show, next_show, ts = cached
                if not self._epg_cache_needs_refresh(now_show, next_show, ts):
                    return
            else:
                now_show = next_show = ts = None
            # Only spawn a refresh if one isn't already running for this channel.
            with self._epg_inflight_lock:
                already = key in self._epg_fetch_inflight
            if not already:
                threading.Thread(target=self._fetch_and_cache_epg, args=(ch, cname), daemon=True).start()
        except Exception:
            LOG.debug("IPTVClient._on_epg_poll_timer: ignored exception", exc_info=True)

    def _find_channel_for_epg(self, show: Dict[str, str]) -> Optional[Dict[str, str]]:
        return self._find_matching_channel_for_program(show)

    def _channel_has_catchup(self, channel: Dict[str, str]) -> bool:
        if channel.get("catchup-source") or channel.get("catchup"):
            return True
        if channel.get("provider-type") == "stalker":
            pdata = channel.get("provider-data") or {}
            return bool(pdata.get("allow_timeshift") or pdata.get("archive"))
        return False

    def _parse_epg_time(self, value: str) -> datetime.datetime:
        dt = datetime.datetime.strptime(value, "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=datetime.timezone.utc)

    def _resolve_show_url(self, channel: Dict[str, str], show: Dict[str, str]) -> tuple:
        start_dt = self._parse_epg_time(show.get("start"))
        end_dt = self._parse_epg_time(show.get("end"))
        now = datetime.datetime.now(datetime.timezone.utc)

        if start_dt <= now <= end_dt:
            return self._resolve_live_url(channel), False

        if end_dt < now:
            if not self._channel_has_catchup(channel):
                raise ProviderError("This channel does not provide catch-up streaming.")
            if not self._within_catchup_window(channel, start_dt):
                raise ProviderError("This programme is older than the catch-up window allows.")
            url = self._resolve_catchup_url(channel, start_dt, end_dt)
            if not url:
                raise ProviderError("Unable to construct catch-up URL for this programme.")
            return url, True

        # Future programme: return live stream so playback starts when available.
        return self._resolve_live_url(channel), False

    def _within_catchup_window(self, channel: Dict[str, str], start_dt: datetime.datetime) -> bool:
        days = channel.get("catchup-days")
        if not days:
            return True
        try:
            span = int(float(days))
        except (TypeError, ValueError):
            return True
        now = datetime.datetime.now(datetime.timezone.utc)
        return start_dt >= now - datetime.timedelta(days=span)

    def _resolve_live_url(self, channel: Dict[str, str]) -> str:
        url = channel.get("url", "")
        provider_type = channel.get("provider-type")
        provider_id = channel.get("provider-id")

        if provider_type == "stalker":
            if not provider_id:
                raise ProviderError("Stalker portal entry missing provider identifier.")
            client = self.provider_clients.get(provider_id)
            if not client:
                raise ProviderError("Stalker portal client is not initialized.")
            pdata = channel.get("provider-data") or {}
            url = client.resolve_stream(pdata)
            return url

        return url

    def _resolve_catchup_url(self, channel: Dict[str, str], start_dt: datetime.datetime, end_dt: datetime.datetime) -> str:
        provider_type = channel.get("provider-type")
        provider_id = channel.get("provider-id")
        if provider_type == "stalker" and provider_id:
            client = self.provider_clients.get(provider_id)
            if not client:
                raise ProviderError("Stalker portal client is not initialized.")
            pdata = channel.get("provider-data") or {}
            start_local = utc_to_local(start_dt)
            duration = max(1, int((end_dt - start_dt).total_seconds() // 60))
            start_str = start_local.strftime("%Y-%m-%d:%H-%M")
            return client.resolve_catchup(pdata, start_str, duration)

        return self._build_generic_catchup_url(channel, start_dt, end_dt)

    def _build_generic_catchup_url(self, channel: Dict[str, str], start_dt: datetime.datetime, end_dt: datetime.datetime) -> str:
        source = channel.get("catchup-source") or ""
        if not source:
            return ""
        stream_id = channel.get("stream-id") or self._extract_stream_id(channel.get("url", ""))
        if not stream_id:
            return ""

        src = source.rstrip('/')
        if not src:
            return ""
        last_segment = src.rsplit('/', 1)[-1]
        if not last_segment.isdigit():
            src = f"{src}/{stream_id}"

        start_local = utc_to_local(start_dt)
        end_local = utc_to_local(end_dt)
        offset = channel.get("catchup-offset")
        try:
            if offset:
                hours = float(offset)
                delta = datetime.timedelta(hours=hours)
                start_local -= delta
                end_local -= delta
        except (TypeError, ValueError):
            LOG.debug("IPTVClient._build_generic_catchup_url: ignored exception", exc_info=True)

        # Compute duration from the UTC instants (DST-safe); the offset shifts start and end
        # equally, so it doesn't affect duration. start_token still uses adjusted local time.
        duration = max(1, int((end_dt - start_dt).total_seconds() // 60))
        start_token = start_local.strftime("%Y-%m-%d:%H-%M")
        ctype = (channel.get("catchup-type") or channel.get("catchup") or "xc").lower()
        if ctype in {"", "xc", "default", "catchup"}:
            url = f"{src}/{start_token}/{duration}/"
        elif ctype == "flussonic":
            archive_stamp = start_local.strftime("%Y%m%d%H%M%S")
            url = f"{src}/{archive_stamp}-{duration}.m3u8"
        else:
            url = f"{src}/{start_token}/{duration}/"

        ua = channel.get("http-user-agent")
        if ua:
            if "|" in url:
                url = f"{url}&User-Agent={urllib.parse.quote(ua)}"
            else:
                url = f"{url}|User-Agent={urllib.parse.quote(ua)}"
        return url

    def play_selected(self, *, show_internal_player: Optional[bool] = None):
        i = self.channel_list.GetSelection()
        if not (0 <= i < len(self.displayed)):
            return
        item = self.displayed[i]

        # VOD navigation rows: activating them browses rather than plays.
        if item["type"] == "vod_series":
            self._vod_open_series(item["data"])
            return
        if item["type"] == "vod_back":
            self._vod_go_back()
            return
        if item["type"] == "vod_info":
            return

        channel = None
        show = None
        if item["type"] == "channel":
            channel = item["data"]
        elif item["type"] == "epg":
            show = item["data"]
            channel = self._find_channel_for_epg(show)
            if not channel:
                wx.MessageBox(_("Could not match this programme to a playlist channel."),
                              _("Not Found"), wx.OK | wx.ICON_WARNING)
                return
        else:
            return

        try:
            if show:
                url, _unused = self._resolve_show_url(channel, show)
            else:
                url = self._resolve_live_url(channel)
        except ProviderError as err:
            wx.MessageBox(_("Provider error: {error}").format(error=err), _("Playback Error"), wx.OK | wx.ICON_ERROR)
            return
        except Exception as err:
            wx.MessageBox(_("Could not resolve stream URL:\n{error}").format(error=err), _("Playback Error"), wx.OK | wx.ICON_ERROR)
            return

        display_name = None
        if channel:
            display_name = (channel.get("name")
                            or channel.get("tvg-name")
                            or channel.get("tvg_name")
                            or channel.get("tvg-id")
                            or channel.get("tvg_id"))
        stream_kind = "catchup" if show else "live"
        if show:
            show_title = show.get("show_title") or show.get("title")
            if show_title:
                if display_name:
                    display_name = f"{show_title} - {display_name}"
                else:
                    display_name = show_title
        if not display_name:
            display_name = _("IPTV Stream")
        if show_internal_player is None:
            show_internal_player = self.show_player_on_enter

        self._launch_stream(
            url,
            display_name,
            stream_kind=stream_kind,
            channel=channel,
            show_internal_player=show_internal_player,
        )

    def _on_internal_player_closed(self) -> None:
        self._internal_player_frame = None

    def _ensure_internal_player(self) -> object:
        frame_class = _load_internal_player_frame_class()
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            try:
                if getattr(frame, "_destroyed", False):
                    frame = None
            except Exception:
                frame = None
        if frame:
            return frame
        settings = resolve_internal_player_settings(self.config)
        frame = frame_class(
            self,
            base_buffer_seconds=settings.base_buffer_seconds,
            max_buffer_seconds=settings.max_buffer_seconds,
            variant_max_mbps=settings.variant_max_mbps,
            on_cast=self._cast_from_internal_player,
            on_close=self._on_internal_player_closed,
        )
        self._internal_player_frame = frame
        return frame

    def _launch_stream(
        self,
        url: str,
        title: Optional[str] = None,
        *,
        stream_kind: str = "live",
        channel: Optional[Dict[str, str]] = None,
        show_internal_player: Optional[bool] = None,
    ):
        LOG.info("_launch_stream called: url=%s, title=%s, player=%s", url, title, self.default_player)
        if not url:
            LOG.warning("_launch_stream: No URL provided")
            wx.MessageBox(_("Could not find stream URL for this selection."), _("Not Found"),
                          wx.OK | wx.ICON_WARNING)
            return
        if show_internal_player is None:
            show_internal_player = self.show_player_on_enter

        # Check if casting
        caster = getattr(self, "caster", None)
        if caster and caster.is_connected():
            try:
                device_name = caster.active_device.display_name

                # Run async cast play in background thread
                def do_cast():
                    try:
                        caster.play(url, title or _("IPTV Stream"), channel=channel)
                    except Exception as e:
                        err_msg = str(e)
                        # The current cast device is incompatible or unreachable
                        # for this stream. Drop the session so the user is not
                        # stuck re-trying the same dead device on every channel
                        # change — they can re-select from the cast menu.
                        try:
                            caster.disconnect()
                        except Exception:
                            LOG.debug("IPTVClient._launch_stream.do_cast: ignored exception", exc_info=True)
                        wx.CallAfter(lambda: wx.MessageBox(
                            _("Casting failed: {error}").format(error=err_msg) + "\n\n"
                            + _("Disconnected from the cast device. "
                                "Open the cast menu to pick another device."),
                            _("Casting Error"), wx.OK | wx.ICON_ERROR))

                threading.Thread(target=do_cast, daemon=True).start()

                wx.MessageBox(_("Casting to {device}...").format(device=device_name), _("Casting"), wx.OK | wx.ICON_INFORMATION)
                return
            except Exception as e:
                wx.MessageBox(_("Failed to cast: {error}").format(error=e), _("Casting Error"), wx.OK | wx.ICON_ERROR)
                # Fallback to local player? No, user expects cast.
                return

        player = self.default_player
        stream_headers = channel_http_headers(channel)
        custom_path = self.config.get("custom_player_path", "")

        if player in {"Built-in Player", "player_Internal", "internal", "Internal"}:
            player = "Built-in Player"
            try:
                frame = self._ensure_internal_player()
            except InternalPlayerUnavailableError as err:
                detail = str(err)
                wx.MessageBox(_("Built-in player unavailable:\n{detail}").format(detail=detail), _("Launch Error"), wx.OK | wx.ICON_ERROR)
                return
            display_title = title or _("IPTV Stream")
            try:
                if show_internal_player:
                    frame.Enable(True)
                    frame.Show()
                    frame.Raise()
                    frame.SetFocus()
                else:
                    # Keep frame disabled and hidden to avoid accessibility focus.
                    frame.Enable(False)
                    frame.Hide()
                frame.play(
                    url,
                    display_title,
                    stream_kind=stream_kind,
                    headers=stream_headers,
                    video_visible=show_internal_player,
                )
                if not show_internal_player:
                    wx.CallAfter(self._restore_main_focus)
            except Exception as err:
                wx.MessageBox(_("Failed to start built-in player:\n{error}").format(error=err), _("Launch Error"), wx.OK | wx.ICON_ERROR)
            return

        # External player launch
        ok, err = self.player_launcher.launch(player, url, custom_path)
        if not ok:
            wx.MessageBox(_("Failed to launch {player}:\n{error}").format(player=player, error=err), _("Launch Error"), wx.OK | wx.ICON_ERROR)

    def _restore_main_focus(self) -> None:
        """Restore focus to channel list only if this window is active."""
        try:
            if self.IsShown() and self.IsActive():
                self.channel_list.SetFocus()
        except Exception:
            LOG.debug("IPTVClient._restore_main_focus: ignored exception", exc_info=True)

    def _cast_from_internal_player(self, url: str, title: str, headers: Dict[str, object]) -> None:
        if not url:
            wx.MessageBox(_("No active stream to cast."), _("Casting"), wx.OK | wx.ICON_WARNING)
            return

        caster = self._ensure_caster()

        def do_cast(device):
            try:
                creds = self.config.get("cast_credentials", {}).get(device.identifier)
                caster.connect(device, credentials=creds)
                # Use the active caster directly so we can forward headers from the current stream.
                if caster.active_caster:
                    caster.dispatch(caster.active_caster.play(url, title, headers=headers))
                else:
                    raise RuntimeError("Caster not connected.")
                wx.CallAfter(self._handoff_internal_player_after_cast, url, title)
                wx.CallAfter(lambda: wx.MessageBox(_("Casting to {device}...").format(device=device.display_name), _("Casting"), wx.OK | wx.ICON_INFORMATION))
            except Exception as e:
                wx.CallAfter(lambda err=e: wx.MessageBox(_("Failed to cast: {error}").format(error=err), _("Casting Error"), wx.OK | wx.ICON_ERROR))

        if caster.is_connected() and caster.active_device:
            threading.Thread(target=lambda: do_cast(caster.active_device), daemon=True).start()
            return

        dlg = CastDiscoveryDialog(self, caster)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                device = dlg.get_selected_device()
                if device:
                    threading.Thread(target=lambda: do_cast(device), daemon=True).start()
        finally:
            dlg.Destroy()

    def _handoff_internal_player_after_cast(self, url=None, title=None, stream_kind=None, channel=None):
        # Stop and hide the built-in player, then (optionally) relaunch the stream
        # in the user's preferred external player. Guard all variables to avoid
        # NameErrors when called without arguments.
        frame = getattr(self, "_internal_player_frame", None)
        if frame:
            try:
                if url is None:
                    url = getattr(frame, "_current_url", None) or getattr(frame, "_last_resolved_url", None)
                if title is None:
                    title = getattr(frame, "_current_title", None)
                if stream_kind is None:
                    stream_kind = getattr(frame, "_current_stream_kind", None)
            except Exception:
                LOG.debug("IPTVClient._handoff_internal_player_after_cast: ignored exception", exc_info=True)
            try:
                frame.stop(manual=True)
            except Exception:
                LOG.debug("IPTVClient._handoff_internal_player_after_cast: ignored exception", exc_info=True)
            try:
                frame.Hide()
            except Exception:
                LOG.debug("IPTVClient._handoff_internal_player_after_cast: ignored exception", exc_info=True)

        player = self.default_player
        
        # If the user prefers the built-in player, just stop/hide and return.
        if player in {"Built-in Player", "player_Internal", "internal", "Internal"}:
            return

        # Ensure we have sane defaults.
        if not title:
            title = "IPTV Stream"
        if not stream_kind:
            stream_kind = "live"
        # If we don't have a URL, there's nothing to hand off.
        if not url:
            return

        # Use generic launch method for external player
        self._launch_stream(url, title, stream_kind=stream_kind, channel=channel, show_internal_player=False)

    def _open_catchup_dialog(self, channel: Dict[str, str]):
        programmes = self._get_catchup_programmes(channel)
        if not programmes:
            wx.MessageBox(_("No catch-up programmes are available for this channel."),
                          _("Catch-up"), wx.OK | wx.ICON_INFORMATION)
            return
        dlg = CatchupDialog(self, channel.get("name", ""), programmes)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                selected = dlg.get_selection()
                if not selected:
                    return
                show = {
                    "channel_id": selected.get("channel_id", ""),
                    "channel_name": channel.get("name", selected.get("channel_name", "")),
                    "show_title": selected.get("title", ""),
                    "start": selected.get("start", ""),
                    "end": selected.get("end", "")
                }
                try:
                    url, _unused = self._resolve_show_url(channel, show)
                except ProviderError as err:
                    wx.MessageBox(_("Provider error: {error}").format(error=err), _("Catch-up"), wx.OK | wx.ICON_ERROR)
                    return
                except Exception as err:
                    wx.MessageBox(_("Unable to prepare catch-up stream:\n{error}").format(error=err), _("Catch-up"), wx.OK | wx.ICON_ERROR)
                    return
                display = (selected.get("title") or channel.get("name", "IPTV Stream"))
                self._launch_stream(url, display, stream_kind="catchup", channel=channel)
        finally:
            dlg.Destroy()

    def show_cast_dialog(self, _event):
        caster = self._ensure_caster()
        if caster.is_connected():
            msg = _("Currently connected to: {device}\n\nDisconnect?").format(
                device=caster.active_device.display_name)
            if wx.MessageBox(msg, _("Casting"), wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                # Disconnect in background
                threading.Thread(target=caster.disconnect, daemon=True).start()
            return

        dlg = CastDiscoveryDialog(self, caster)
        if dlg.ShowModal() == wx.ID_OK:
            device = dlg.get_selected_device()
            if device:
                # Connect in background
                def do_connect():
                    try:
                        creds = self.config.get("cast_credentials", {}).get(device.identifier)
                        caster.connect(device, credentials=creds)
                        wx.CallAfter(lambda: wx.MessageBox(_("Connected to {device}").format(device=device.display_name), _("Connected"), wx.OK))
                    except Exception as e:
                        err_msg = str(e)
                        wx.CallAfter(lambda: wx.MessageBox(_("Failed to connect: {error}").format(error=err_msg), _("Error"), wx.OK | wx.ICON_ERROR))
                
                threading.Thread(target=do_connect, daemon=True).start()
        dlg.Destroy()


    def _get_catchup_programmes(self, channel: Dict[str, str]) -> List[Dict[str, str]]:
        try:
            db = EPGDatabase(get_db_path(), readonly=True)
            try:
                programmes = db.get_recent_programmes(channel, hours=72, limit=80)
            finally:
                db.close()
        except Exception:
            programmes = []
        return programmes


class CastDiscoveryDialog(wx.Dialog):
    def __init__(self, parent, caster):
        super().__init__(parent, title=_("Select Device to Cast"), size=(450, 350))
        self.parent_frame = parent
        self.caster = caster
        self.devices: List[object] = []

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.status_lbl = wx.StaticText(panel, label=_("Searching for devices..."))
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.pair_btn = wx.Button(panel, label=_("Pair..."))
        self.pair_btn.Disable()

        self.ok_btn = wx.Button(panel, id=wx.ID_OK, label=_("Connect"))
        self.ok_btn.Disable()
        cancel_btn = wx.Button(panel, id=wx.ID_CANCEL)
        
        btn_sizer.Add(self.pair_btn, 0, wx.ALL, 5)
        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(self.ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        
        sizer.Add(self.status_lbl, 0, wx.ALL, 10)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        panel.SetSizer(sizer)
        
        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_dclick)
        self.pair_btn.Bind(wx.EVT_BUTTON, self._on_pair)
        
        self.CenterOnParent()
        
        # Start discovery
        self._start_discovery()

    def _start_discovery(self):
        def do_scan():
            try:
                # caster.discover_all() is synchronous and thread-safe (uses internal loop)
                devices = self.caster.discover_all()
                wx.CallAfter(self._update_list, devices)
            except Exception as e:
                wx.CallAfter(self.status_lbl.SetLabel, _("Error: {error}").format(error=e))

        threading.Thread(target=do_scan, daemon=True).start()

    def _update_list(self, devices: List[object]):
        self.devices = devices
        self.listbox.Clear()
        if not devices:
            self.status_lbl.SetLabel(_("No devices found."))
            return

        self.status_lbl.SetLabel(_("Found {count} devices:").format(count=len(devices)))
        for dev in devices:
            self.listbox.Append(dev.display_name)
        
        # Restore selection if possible (not implemented for now to keep it simple)

    def _on_select(self, event):
        sel = self.listbox.GetSelection()
        if sel != wx.NOT_FOUND and 0 <= sel < len(self.devices):
            self.ok_btn.Enable()
            dev = self.devices[sel]
            # Enable Pair button for AirPlay devices
            self.pair_btn.Enable(dev.protocol.value == "AirPlay")
        else:
            self.ok_btn.Disable()
            self.pair_btn.Disable()

    def _on_dclick(self, event):
        if self.listbox.GetSelection() != wx.NOT_FOUND:
            self.EndModal(wx.ID_OK)

    def _on_pair(self, event):
        device = self.get_selected_device()
        if not device:
            return
        
        # Disable UI
        self.pair_btn.Disable()
        self.ok_btn.Disable()
        self.status_lbl.SetLabel(_("Starting pairing with {device}...").format(device=device.name))
        
        def do_pair_flow():
            handler = None
            try:
                # Step 1: Begin Pairing
                handler = self.caster.start_pairing(device) # This is sync now
                self.caster.dispatch(handler.begin())
                
                # Step 2: Ask User for PIN
                def ask_pin():
                    dlg = wx.TextEntryDialog(self, _("Enter PIN displayed on {device}:").format(device=device.name), _("Pairing"))
                    if dlg.ShowModal() == wx.ID_OK:
                        return dlg.GetValue().strip()
                    return None
                
                # We need to run the dialog on main thread
                pin_result = [None]
                evt = threading.Event()
                def show_dialog_main():
                    pin_result[0] = ask_pin()
                    evt.set()
                
                wx.CallAfter(show_dialog_main)
                evt.wait()
                
                pin = pin_result[0]
                if not pin:
                    # User cancelled
                    self.caster.dispatch(handler.close())
                    wx.CallAfter(self.status_lbl.SetLabel, _("Pairing cancelled."))
                    return

                # Step 3: Submit PIN
                handler.pin(pin)
                
                # Step 4: Finish
                self.caster.dispatch(handler.finish())
                
                # Step 5: Save Credentials
                creds = handler.service.credentials
                if creds:
                    wx.CallAfter(self._save_creds_and_notify, device, creds)
                else:
                    wx.CallAfter(lambda: wx.MessageBox(_("Pairing finished but no credentials returned."), _("Pairing Failed"), wx.OK | wx.ICON_ERROR))

            except Exception as e:
                err_msg = str(e)
                wx.CallAfter(lambda: wx.MessageBox(_("Pairing error: {error}").format(error=err_msg), _("Error"), wx.OK | wx.ICON_ERROR))
                wx.CallAfter(self.status_lbl.SetLabel, _("Pairing failed: {error}").format(error=err_msg))
                if handler:
                    try:
                        self.caster.dispatch(handler.close())
                    except Exception:
                        LOG.debug("CastDiscoveryDialog._on_pair.do_pair_flow: ignored exception", exc_info=True)
            finally:
                wx.CallAfter(self._on_select, None) # Re-enable buttons
        
        threading.Thread(target=do_pair_flow, daemon=True).start()

    def _save_creds_and_notify(self, device, creds):
        # Save to main config
        cfg = self.parent_frame.config
        if "cast_credentials" not in cfg:
            cfg["cast_credentials"] = {}
        
        cfg["cast_credentials"][device.identifier] = creds
        save_config(cfg)
        
        wx.MessageBox(_("Successfully paired with {device}!").format(device=device.name), _("Pairing Complete"), wx.OK)
        self.status_lbl.SetLabel(_("Paired with {device}. Ready to connect.").format(device=device.name))

    def get_selected_device(self) -> Optional[object]:
        sel = self.listbox.GetSelection()
        if sel != wx.NOT_FOUND and 0 <= sel < len(self.devices):
            return self.devices[sel]
        return None


class AccountInfoDialog(wx.Dialog):
    """Subscription status for every provider account the app can find.

    Deliberately two controls: a list of accounts and one read-only multiline
    field holding the whole report. That is the shape a screen reader handles
    best - arrow through the accounts, tab once, read the details top to bottom.
    Each lookup is a blocking HTTP request, so it runs on a worker thread and
    results are matched against a request token before being displayed.
    """

    def __init__(self, parent, accounts: List[account_info.Account]):
        super().__init__(
            parent,
            title=_("Account Info"),
            size=(700, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.accounts = accounts
        self._reports: Dict[int, str] = {}
        self._request_token = 0
        self._alive = True

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(panel, label=_("Select an account to check its status:"))
        list_label = wx.StaticText(panel, label=_("Accounts") + ":")
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._label_control(self.listbox, _("Accounts"))
        for account in accounts:
            self.listbox.Append(account_info.account_label(account))

        details_label = wx.StaticText(panel, label=_("Account details") + ":")
        self.details = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self._label_control(self.details, _("Account details"))

        self.status_lbl = wx.StaticText(panel, label="")

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(panel, label=_("Refresh"))
        self.copy_btn = wx.Button(panel, label=_("Copy Details"))
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        btn_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        btn_sizer.Add(self.copy_btn, 0, wx.ALL, 5)
        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(close_btn, 0, wx.ALL, 5)

        sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(list_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(details_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(self.details, 2, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(sizer)

        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.refresh_btn.Bind(wx.EVT_BUTTON, self._on_refresh)
        self.copy_btn.Bind(wx.EVT_BUTTON, self._on_copy)
        close_btn.Bind(wx.EVT_BUTTON, self._on_close_button)
        self.Bind(wx.EVT_CLOSE, self._on_close_window)
        self.SetEscapeId(wx.ID_CANCEL)

        self.SetMinSize((520, 420))
        self.Layout()
        self.CenterOnParent()

        if accounts:
            self.listbox.SetSelection(0)
            self.listbox.SetFocus()
            self._start_lookup(0)

    @staticmethod
    def _label_control(ctrl, label):
        ctrl.SetName(label)
        if hasattr(ctrl, "SetAccessibleName"):
            ctrl.SetAccessibleName(label)

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #
    def _start_lookup(self, index: int, force: bool = False):
        if not (0 <= index < len(self.accounts)):
            return
        self._request_token += 1
        token = self._request_token
        if not force and index in self._reports:
            self._apply_report(token, index, self._reports[index])
            return
        account = self.accounts[index]
        self.details.SetValue(_("Checking account, please wait..."))
        self.status_lbl.SetLabel(_("Checking {account}...").format(
            account=account_info.account_label(account)))
        self.refresh_btn.Disable()

        def worker():
            try:
                report = account_info.fetch_account_report(account)
            except Exception as e:
                LOG.debug("AccountInfoDialog: account lookup failed", exc_info=True)
                wx.CallAfter(self._lookup_failed, token, index, str(e))
                return
            wx.CallAfter(self._lookup_finished, token, index, report)

        threading.Thread(target=worker, daemon=True).start()

    def _lookup_finished(self, token: int, index: int, report: str):
        self._reports[index] = report
        self._apply_report(token, index, report)

    def _lookup_failed(self, token: int, index: int, error: str):
        # Errors are not cached: re-selecting the account should retry it.
        self._apply_report(
            token,
            index,
            _("Could not check this account.\n\n{error}").format(error=error),
            ok=False,
        )

    def _apply_report(self, token: int, index: int, report: str, ok: bool = True):
        if not self._alive or token != self._request_token:
            return
        try:
            self.details.SetValue(report)
            # Reading starts at the top, not wherever the previous report ended.
            self.details.SetInsertionPoint(0)
            self.status_lbl.SetLabel(_("Ready.") if ok else _("Check failed."))
            self.refresh_btn.Enable()
        except RuntimeError:
            LOG.debug("AccountInfoDialog._apply_report: dialog already gone", exc_info=True)

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    def _on_select(self, _event):
        self._start_lookup(self.listbox.GetSelection())

    def _on_refresh(self, _event):
        self._start_lookup(self.listbox.GetSelection(), force=True)

    def _on_copy(self, _event):
        text = self.details.GetValue()
        if not text:
            return
        if not wx.TheClipboard.Open():
            self.status_lbl.SetLabel(_("Could not open the clipboard."))
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        self.status_lbl.SetLabel(_("Account details copied to the clipboard."))

    def _on_close_button(self, _event):
        self._alive = False
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()

    def _on_close_window(self, event):
        self._alive = False
        event.Skip()


class CatchupDialog(wx.Dialog):
    def __init__(self, parent, channel_name: str, programmes: List[Dict[str, str]]):
        title = channel_name or _("Catch-up")
        super().__init__(parent, title=_("Catch-up: {name}").format(name=title), size=(520, 360))
        self.programmes = programmes
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(panel, label=_("Select a programme to play from catch-up:"))
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        for prog in programmes:
            self.listbox.Append(self._format_programme(prog))
        if programmes:
            self.listbox.SetSelection(0)
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, id=wx.ID_OK, label=_("Play"))
        cancel_btn = wx.Button(panel, id=wx.ID_CANCEL)
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        sizer.Add(intro, 0, wx.ALL, 10)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        panel.SetSizer(sizer)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_listbox_activate)
        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        self.SetMinSize((420, 320))
        self.Layout()
        self.CenterOnParent()

    def _format_programme(self, prog: Dict[str, str]) -> str:
        try:
            start = datetime.datetime.strptime(prog.get("start", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            end = datetime.datetime.strptime(prog.get("end", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            start_local = utc_to_local(start)
            end_local = utc_to_local(end)
            window = f"{start_local.strftime('%Y-%m-%d %H:%M')} – {end_local.strftime('%H:%M')}"
        except Exception:
            window = prog.get("start", "")
        title = prog.get("title", "") or _("(No title)")
        return f"{window}  |  {title}"

    def _on_listbox_activate(self, _):
        if self.programmes:
            self.EndModal(wx.ID_OK)

    def _on_ok(self, event):
        if self.listbox.GetSelection() == wx.NOT_FOUND and self.programmes:
            self.listbox.SetSelection(0)
        if self.listbox.GetSelection() == wx.NOT_FOUND:
            return
        self.EndModal(wx.ID_OK)

    def get_selection(self) -> Optional[Dict[str, str]]:
        idx = self.listbox.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self.programmes):
            return None
        return self.programmes[idx]


class ScheduledRecordingsDialog(wx.Dialog):
    """Dialog showing all DVR schedule entries."""

    def __init__(self, parent, scheduler: dvr.DVRScheduler):
        super().__init__(parent, title=_("Scheduled Recordings"), size=(850, 430))
        self.parent_frame = parent
        self.scheduler = scheduler
        self.jobs: List[Dict[str, object]] = []

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.SetName(_("Scheduled recordings"))
        self.list_ctrl.InsertColumn(0, _("Time"), width=210)
        self.list_ctrl.InsertColumn(1, _("Title"), width=230)
        self.list_ctrl.InsertColumn(2, _("Channel"), width=180)
        self.list_ctrl.InsertColumn(3, _("Status"), width=110)
        self.list_ctrl.InsertColumn(4, _("Format"), width=120)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        refresh_btn = wx.Button(panel, label=_("Refresh"))
        cancel_btn = wx.Button(panel, label=_("Cancel Selected"))
        delete_btn = wx.Button(panel, label=_("Delete Selected"))
        close_btn = wx.Button(panel, id=wx.ID_CLOSE, label=_("Close"))
        btn_sizer.Add(refresh_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(cancel_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(delete_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(close_btn, 0)

        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(sizer)

        refresh_btn.Bind(wx.EVT_BUTTON, lambda _event: self.refresh())
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel_selected)
        delete_btn.Bind(wx.EVT_BUTTON, self._on_delete_selected)
        close_btn.Bind(wx.EVT_BUTTON, lambda _event: self.Close())
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self.refresh()
        self.CenterOnParent()

    def _status_label(self, status: str) -> str:
        labels = {
            dvr.STATUS_SCHEDULED: _("Scheduled"),
            dvr.STATUS_RECORDING: _("Recording"),
            dvr.STATUS_STOPPING: _("Stopping"),
            dvr.STATUS_COMPLETED: _("Completed"),
            dvr.STATUS_FAILED: _("Failed"),
            dvr.STATUS_MISSED: _("Missed"),
            dvr.STATUS_CANCELED: _("Canceled"),
        }
        return labels.get(status, status or "")

    def refresh(self):
        self.jobs = self.scheduler.list_jobs(include_done=True)
        self.list_ctrl.DeleteAllItems()
        for job in self.jobs:
            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), self.parent_frame._schedule_window_label(job))
            self.list_ctrl.SetItem(idx, 1, str(job.get("title") or ""))
            self.list_ctrl.SetItem(idx, 2, str(job.get("channel_name") or ""))
            self.list_ctrl.SetItem(idx, 3, self._status_label(str(job.get("status") or "")))
            self.list_ctrl.SetItem(idx, 4, self.parent_frame._recording_format_label(str(job.get("format") or "")))
            if job.get("status") in {dvr.STATUS_RECORDING, dvr.STATUS_STOPPING}:
                font = self.list_ctrl.GetItemFont(idx)
                font.SetWeight(wx.FONTWEIGHT_BOLD)
                self.list_ctrl.SetItemFont(idx, font)
        if self.jobs:
            self.list_ctrl.Select(0)
            self.list_ctrl.Focus(0)

    def _selected_job(self) -> Optional[Dict[str, object]]:
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1 or idx >= len(self.jobs):
            return None
        return self.jobs[idx]

    def _on_cancel_selected(self, _event):
        job = self._selected_job()
        if not job:
            wx.MessageBox(_("Select a scheduled recording first."), _("Scheduled Recordings"),
                          wx.OK | wx.ICON_INFORMATION)
            return
        if self.parent_frame._cancel_scheduled_recording(str(job.get("id") or "")):
            self.refresh()

    def _on_delete_selected(self, _event):
        job = self._selected_job()
        if not job:
            wx.MessageBox(_("Select a scheduled recording first."), _("Scheduled Recordings"),
                          wx.OK | wx.ICON_INFORMATION)
            return
        if job.get("status") in {dvr.STATUS_RECORDING, dvr.STATUS_STOPPING}:
            answer = wx.MessageBox(
                _("This recording is active. Stop and delete it?"),
                _("Scheduled Recordings"),
                wx.YES_NO | wx.ICON_WARNING,
            )
            if answer != wx.YES:
                return
            self.parent_frame._cancel_scheduled_recording(str(job.get("id") or ""))
        self.scheduler.delete_job(str(job.get("id") or ""))
        self.refresh()

    def _on_close(self, event):
        try:
            self.parent_frame._dvr_dialog = None
        except Exception:
            LOG.debug("ScheduledRecordingsDialog._on_close: ignored exception", exc_info=True)
        self.Destroy()


class WhatsOnNowDialog(wx.Dialog):
    """Dialog showing all currently airing programs across all channels."""
    
    def __init__(self, parent, programs: List[Dict[str, str]], schedule_callback=None):
        super().__init__(parent, title=_("What's on Now"), size=(700, 500))
        self.programs = programs
        self.filtered_programs = programs[:]
        self.schedule_callback = schedule_callback
        self._type_ahead_buffer = ""
        self._type_ahead_timer = None
        self._filter_timer = None
        
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Search box (for filtering, Tab to access)
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_label = wx.StaticText(panel, label=_("Filter (Tab):"))
        self.search_box = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.search_box.SetName(_("Filter programs"))
        search_sizer.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        search_sizer.Add(self.search_box, 1, wx.EXPAND)
        sizer.Add(search_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Info label
        self.count_label = wx.StaticText(panel, label=_("{count} programs").format(count=len(programs)))
        sizer.Add(self.count_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Use virtual ListCtrl for fast loading with many items
        self.listbox = _VirtualWhatsOnList(panel, self)
        self.listbox.SetName(_("Currently airing programs"))
        self.listbox.InsertColumn(0, _("Program - Channel"), width=650)
        self.listbox.SetItemCount(len(self.filtered_programs))

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        play_btn = wx.Button(panel, id=wx.ID_OK, label=_("Play"))
        schedule_btn = wx.Button(panel, label=_("Schedule Recording"))
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        btn_sizer.Add(play_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(schedule_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(close_btn, 0)
        
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        
        panel.SetSizer(sizer)
        
        self.Layout()
        self.CenterOnParent()
        
        # Bind events - use KEY_DOWN to intercept space before ListCtrl handles it
        self.listbox.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.listbox.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        play_btn.Bind(wx.EVT_BUTTON, self._on_play)
        schedule_btn.Bind(wx.EVT_BUTTON, self._on_schedule)
        self.search_box.Bind(wx.EVT_TEXT, self._on_search)
        self.search_box.Bind(wx.EVT_TEXT_ENTER, self._on_search_enter)
        
        # Focus the list initially
        if self.filtered_programs:
            self.listbox.Select(0)
            self.listbox.Focus(0)
        self.listbox.SetFocus()
    
    def _on_key_down(self, event):
        """Handle key input for type-ahead search - intercept before ListCtrl."""
        key = event.GetKeyCode()
        
        # Handle Tab to go to search box
        if key == wx.WXK_TAB:
            self.search_box.SetFocus()
            return
        
        # Handle Enter to play
        if key == wx.WXK_RETURN or key == wx.WXK_NUMPAD_ENTER:
            if self.listbox.GetSelectedItemCount() > 0:
                self.EndModal(wx.ID_OK)
            return
        
        # Handle Escape to close
        if key == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        
        # Handle Space - add to type-ahead buffer (don't activate)
        if key == wx.WXK_SPACE or key == ord(' '):
            if self._type_ahead_timer:
                self._type_ahead_timer.Stop()
            self._type_ahead_buffer += " "
            self._find_match(self._type_ahead_buffer)
            self._type_ahead_timer = wx.CallLater(1000, self._reset_type_ahead)
            return
        
        # For printable characters (excluding space which is handled above), do type-ahead search
        if 33 <= key <= 126:  # Start at 33 (!) to exclude space (32)
            char = chr(key).lower()
            
            # Reset buffer if too much time passed
            if self._type_ahead_timer:
                self._type_ahead_timer.Stop()
            
            self._type_ahead_buffer += char
            self._find_match(self._type_ahead_buffer)
            
            # Reset buffer after 1 second of no typing
            self._type_ahead_timer = wx.CallLater(1000, self._reset_type_ahead)
            return
        
        # Backspace clears type-ahead buffer
        if key == wx.WXK_BACK:
            if self._type_ahead_buffer:
                self._type_ahead_buffer = self._type_ahead_buffer[:-1]
                if self._type_ahead_buffer:
                    self._find_match(self._type_ahead_buffer)
            return
        
        event.Skip()
    
    def _reset_type_ahead(self):
        """Reset the type-ahead buffer."""
        self._type_ahead_buffer = ""
    
    def _find_match(self, prefix: str):
        """Find and select the first item starting with prefix."""
        prefix_lower = prefix.lower()
        for idx, prog in enumerate(self.filtered_programs):
            title = prog.get("title", "").lower()
            if title.startswith(prefix_lower):
                self.listbox.Select(idx)
                self.listbox.Focus(idx)
                self.listbox.EnsureVisible(idx)
                return
    
    def _on_search(self, event):
        """Debounce filtering so NVDA isn't hit with a list rebuild per keystroke."""
        if self._filter_timer:
            self._filter_timer.Stop()
        self._filter_timer = wx.CallLater(200, self._apply_search_filter)

    def _apply_search_filter(self):
        self._filter_timer = None
        try:
            if not self:  # dialog already destroyed while the timer was pending
                return
            query = self.search_box.GetValue().lower().strip()
        except RuntimeError:
            return
        if not query:
            self.filtered_programs = self.programs[:]
        else:
            self.filtered_programs = [
                p for p in self.programs
                if query in p.get("title", "").lower() or query in p.get("channel_name", "").lower()
            ]
        new_count = len(self.filtered_programs)
        # The old selection's index maps to a different program after refiltering,
        # and a focused item past the new count leaves NVDA holding a stale index.
        # Drop selection/focus state entirely before changing the count.
        old_count = self.listbox.GetItemCount()
        for idx in {self.listbox.GetFirstSelected(), self.listbox.GetFocusedItem()}:
            if idx is not None and 0 <= idx < old_count:
                try:
                    self.listbox.SetItemState(idx, 0, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
                except Exception:
                    LOG.debug("WhatsOnNowDialog._apply_search_filter: ignored exception", exc_info=True)
        self.listbox.SetItemCount(new_count)
        self.listbox.Refresh()
        self.count_label.SetLabel(_("{count} programs").format(count=new_count))
        # Only auto-select while the user is actually in the list; forcing
        # Select/Focus while they type in the search box fires focus events at NVDA.
        if self.filtered_programs and self.FindFocus() is self.listbox:
            self.listbox.Select(0)
            self.listbox.Focus(0)
        LOG.debug("whats-on filter %r: %d/%d programs", query, new_count, len(self.programs))

    def _on_search_enter(self, event):
        """Move focus to list when Enter is pressed in search box."""
        # Flush a pending debounced filter so the list matches the query.
        if self._filter_timer:
            self._filter_timer.Stop()
            self._apply_search_filter()
        if self.filtered_programs:
            self.listbox.SetFocus()
            self.listbox.Select(0)
            self.listbox.Focus(0)
    
    def _on_activate(self, event):
        """Handle double-click/Enter to play."""
        if self.listbox.GetSelectedItemCount() > 0:
            self.EndModal(wx.ID_OK)
    
    def _on_play(self, event):
        """Handle Play button click."""
        if self.listbox.GetSelectedItemCount() > 0:
            self.EndModal(wx.ID_OK)
        event.Skip()

    def _on_schedule(self, _event):
        if not self.schedule_callback:
            return
        selection = self.get_selection()
        if selection:
            self.schedule_callback(selection)
    
    def get_selection(self) -> Optional[Dict[str, str]]:
        """Get the selected program dict."""
        idx = self.listbox.GetFirstSelected()
        if idx == -1 or idx >= len(self.filtered_programs):
            return None
        return self.filtered_programs[idx]


class _VirtualChannelList(wx.ListCtrl):
    """Virtual, single-column list for the main channel / search-results list.

    Backed by the frame's ``displayed`` model (a list of {"type","data"[, "label"]}
    entries); only visible rows are realized, so 50k-300k entries stay responsive for the
    UI and NVDA. Exposes a small wx.ListBox-compatible API (GetSelection / SetSelection /
    GetCount / Clear) so the existing selection code did not need to change when the control
    was switched from wx.ListBox to a virtual wx.ListCtrl. This same virtual-ListCtrl pattern
    is already used (and screen-reader tested) by _VirtualWhatsOnList below.
    """

    def __init__(self, parent, frame):
        super().__init__(
            parent,
            style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL,
            name="Channels",
        )
        self._frame = frame
        self.InsertColumn(0, "")
        self.SetItemCount(0)
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _on_size(self, event):
        # Keep the single column as wide as the control so long names aren't clipped.
        width = self.GetClientSize().width
        if width > 0:
            self.SetColumnWidth(0, width)
        event.Skip()

    def OnGetItemText(self, item, column):
        disp = self._frame.displayed
        if 0 <= item < len(disp):
            entry = disp[item]
            label = entry.get("label")
            if label is not None:
                return label
            data = entry.get("data") or {}
            return data.get("name", "")
        return ""

    def _clear_active_item_state(self, minimum_index: int = 0):
        """Clear selected/focused state for active rows at or after an index."""
        old = self.GetItemCount()
        for idx in {self.GetFirstSelected(), self.GetFocusedItem()}:
            if idx is not None and minimum_index <= idx < old:
                try:
                    self.SetItemState(
                        idx,
                        0,
                        wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                    )
                except Exception:
                    LOG.debug("_VirtualChannelList._clear_active_item_state: ignored exception", exc_info=True)

    def _set_count_safe(self, count: int, *, active_state_cleared: bool = False):
        """Resync the native item count, dropping stale selection/focus first.

        Shrinking a virtual SysListView32 while its focused/selected item index
        is >= the new count leaves MSAA/UIA holding a stale index, which can
        crash NVDA. Clear those item states before the shrink.
        """
        old = self.GetItemCount()
        if count < old:
            if not active_state_cleared:
                self._clear_active_item_state(count)
            LOG.debug("channel list count %d -> %d", old, count)
        self.SetItemCount(count)

    def replace_contents(self, entries: List[Dict[str, str]]):
        """Replace the backing rows while keeping native indexes valid.

        ``SetItemCount`` can trigger synchronous MSAA/UIA item queries. On a
        shrink, reduce the native count while the old model still serves all
        remaining indexes, then swap to the new model. On a grow, install the
        new model first so every existing index remains valid. Clear active
        state for *every* replacement, even when the old index would fit the
        new count: it represents a different logical row after a search.
        """
        if not isinstance(entries, list):
            entries = list(entries)
        old_count = self.GetItemCount()
        new_count = len(entries)
        self._clear_active_item_state()

        if new_count < old_count:
            self._set_count_safe(new_count, active_state_cleared=True)
            self._frame.displayed = entries
        else:
            self._frame.displayed = entries
            self._set_count_safe(new_count, active_state_cleared=True)

        self.Refresh()

    def set_virtual_count(self):
        """Resync the control to the current length of frame.displayed."""
        self._set_count_safe(len(self._frame.displayed))
        width = self.GetClientSize().width
        if width > 0:
            self.SetColumnWidth(0, width)

    # --- wx.ListBox-compatible shims so existing call sites keep working ---
    def GetSelection(self):
        return self.GetFirstSelected()

    def SetSelection(self, index):
        if index is None or index < 0:
            return
        if index < self.GetItemCount():
            self.Select(index)
            self.Focus(index)
            self.EnsureVisible(index)

    def GetCount(self):
        return self.GetItemCount()

    def Clear(self):
        self._set_count_safe(0)


class _VirtualWhatsOnList(wx.ListCtrl):
    """Virtual list control for fast loading of What's on Now."""
    
    def __init__(self, parent, dialog):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL)
        self.dialog = dialog
    
    def OnGetItemText(self, item, column):
        if 0 <= item < len(self.dialog.filtered_programs):
            prog = self.dialog.filtered_programs[item]
            title = prog.get("title") or _("(No title)")
            channel = prog.get("channel_name") or _("Unknown")
            return f"{title} - {channel}"
        return ""


class ChannelEPGDialog(wx.Dialog):
    def __init__(self, parent, channel_name: str, programmes: List[Dict[str, str]],
                 schedule_callback=None, channel: Optional[Dict[str, str]] = None):
        super().__init__(parent, title=_("EPG: {channel}").format(channel=channel_name), size=(600, 450))
        self.programmes = programmes
        self.schedule_callback = schedule_callback
        self.channel = channel or {}

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.InsertColumn(0, _("Time"), width=140)
        self.list_ctrl.InsertColumn(1, _("Title"), width=400)

        self._populate_list(programmes)
        if programmes:
            self.list_ctrl.Select(0)
            self.list_ctrl.Focus(0)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        schedule_btn = wx.Button(panel, label=_("Schedule Recording"))
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        btn_sizer.Add(schedule_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(close_btn, 0)
        
        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        
        panel.SetSizer(sizer)
        schedule_btn.Bind(wx.EVT_BUTTON, self._on_schedule)
        
        self.Layout()
        self.CenterOnParent()

    def _populate_list(self, programmes):
        for prog in programmes:
            try:
                start = datetime.datetime.strptime(prog.get("start", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
                end = datetime.datetime.strptime(prog.get("end", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
                start_local = utc_to_local(start)
                end_local = utc_to_local(end)
                time_str = f"{start_local.strftime('%H:%M')} - {end_local.strftime('%H:%M')}"
                
                # Check if this program is currently airing
                now = datetime.datetime.now(datetime.timezone.utc)
                is_now = start <= now <= end
                
                idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), time_str)
                self.list_ctrl.SetItem(idx, 1, prog.get("title", ""))
                
                if is_now:
                    # Highlight current program (bold font)
                    font = self.list_ctrl.GetItemFont(idx)
                    font.SetWeight(wx.FONTWEIGHT_BOLD)
                    self.list_ctrl.SetItemFont(idx, font)
                    self.list_ctrl.EnsureVisible(idx)
            except Exception:
                LOG.debug("ChannelEPGDialog._populate_list: ignored exception", exc_info=True)

    def _selected_programme(self) -> Optional[Dict[str, str]]:
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1 or idx >= len(self.programmes):
            return None
        return self.programmes[idx]

    def _on_schedule(self, _event):
        if not self.schedule_callback:
            return
        prog = self._selected_programme()
        if not prog:
            wx.MessageBox(_("Select a programme first."), _("Schedule Recording"),
                          wx.OK | wx.ICON_INFORMATION)
            return
        self.schedule_callback(self.channel, prog)

if __name__ == "__main__":
    set_linux_env()
    # Best-effort early language activation from saved config (the frame re-applies it too).
    try:
        i18n.init_from_config(load_config())
    except Exception:
        LOG.debug("<module>: ignored exception", exc_info=True)
    app = wx.App()
    app.SetAppName(app_meta.APP_NAME)
    IPTVClient()
    app.MainLoop()
