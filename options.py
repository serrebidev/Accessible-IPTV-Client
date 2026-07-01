import os
import sys
import json
import hashlib
import shutil
from dataclasses import dataclass
import datetime
import re
import time
import platform
import threading
import ctypes
try:
    import wx  # type: ignore
    _HAS_WX = True
except ModuleNotFoundError:  # wxPython optional for headless helpers
    wx = None  # type: ignore
    _HAS_WX = False
from typing import Dict
import tempfile

from i18n import gettext as _

CONFIG_FILE = "iptvclient.conf"
APP_DATA_DIR_NAME = "AccessibleIPTVClient"
LEGACY_APP_DATA_DIR_NAME = "IPTVClient"
WINDOWS_INSTALL_MARKER = ".windows-installed"
WINDOWS_INSTALL_MIGRATION_SENTINEL = ".windows-installed-data-migrated"
EPG_DB_FILE = "epg.db"
EPG_DEBUG_LOG_FILE = "iptvclient_epg_debug.log"
DVR_SCHEDULE_FILE = "scheduled_recordings.json"
CACHE_DIR_NAME = "iptv_cache"
_CONFIG_PATH = None  # Path of config last loaded/saved
_IS_WINDOWS = platform.system() == "Windows"
DEFAULT_INTERNAL_PLAYER_BUFFER_SECONDS = 2.0
DEFAULT_INTERNAL_PLAYER_MAX_BUFFER_SECONDS = 18.0
DEFAULT_RECORDING_FORMAT = "provider_mkv"
DEFAULT_RECORDING_PRE_PADDING_MINUTES = 0
DEFAULT_RECORDING_POST_PADDING_MINUTES = 2

_WINDOWS_TZ_RESETTER = None
_WINDOWS_TZ_LOCK = threading.Lock()
_WINDOWS_TZ_LAST_REFRESH = 0.0

if _IS_WINDOWS:
    # Prefer the Universal CRT, fall back to legacy msvcrt for older systems.
    for _dll_name in ("ucrtbase", "msvcrt"):
        try:
            _dll = ctypes.CDLL(_dll_name)
        except OSError:
            continue
        resetter = getattr(_dll, "_tzset", None)
        if resetter is not None:
            try:
                resetter.restype = None
            except Exception:
                pass
            _WINDOWS_TZ_RESETTER = resetter
            break


def _refresh_windows_timezone():
    """Ensure long-running Windows processes pick up DST/offset changes."""
    global _WINDOWS_TZ_LAST_REFRESH
    if _WINDOWS_TZ_RESETTER is None:
        return
    now = time.monotonic()
    if now - _WINDOWS_TZ_LAST_REFRESH < 300:
        return
    with _WINDOWS_TZ_LOCK:
        # Re-check inside the lock to avoid redundant tzset calls.
        now = time.monotonic()
        if now - _WINDOWS_TZ_LAST_REFRESH < 300:
            return
        try:
            _WINDOWS_TZ_RESETTER()
        except Exception:
            return
        _WINDOWS_TZ_LAST_REFRESH = now


def _log_error(message: str):
    """Log errors without requiring a wx.App (headless safe)."""
    text = str(message or "")
    app = None
    if _HAS_WX and hasattr(wx, "GetApp"):
        try:
            app = wx.GetApp()
        except Exception:
            app = None
    if _HAS_WX and app is not None:
        try:
            wx.LogError(text.replace("%", "%%"))
            return
        except Exception:
            pass
    sys.stderr.write(f"{text}\n")


def _is_writable_dir(path: str) -> bool:
    try:
        if not os.path.isdir(path):
            return False
        testfile = os.path.join(path, ".iptvclient_write_test.tmp")
        with open(testfile, "w", encoding="utf-8") as f:
            f.write("test")
        os.remove(testfile)
        return True
    except Exception:
        return False

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_cwd_dir():
    try:
        return os.getcwd()
    except Exception:
        return None

def _is_windows_platform() -> bool:
    return _IS_WINDOWS or sys.platform.startswith("win")


def _windows_roaming_base() -> str:
    return os.getenv("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")


def _legacy_user_config_dir() -> str:
    if _is_windows_platform():
        return os.path.join(_windows_roaming_base(), LEGACY_APP_DATA_DIR_NAME)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~/Library/Application Support"), LEGACY_APP_DATA_DIR_NAME)
    return os.path.join(os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), LEGACY_APP_DATA_DIR_NAME)


def is_windows_installed_build() -> bool:
    """Return True for an Inno-installed frozen Windows build."""
    if not _is_windows_platform() or not getattr(sys, "frozen", False):
        return False
    try:
        return os.path.exists(os.path.join(get_app_dir(), WINDOWS_INSTALL_MARKER))
    except Exception:
        return False


def is_windows_portable_build() -> bool:
    """Return True for a frozen Windows build that is not installer-managed."""
    return (
        _is_windows_platform()
        and getattr(sys, "frozen", False)
        and not is_windows_installed_build()
    )


def get_user_config_dir(*, create: bool = True):
    """
    Gets the user-specific config directory, creating it when requested.

    Windows deliberately uses the explicit roaming profile folder so installed
    builds keep mutable data out of Program Files and remain stable even before
    wx.App is initialized.
    """
    if _is_windows_platform():
        path = os.path.join(_windows_roaming_base(), APP_DATA_DIR_NAME)
        if not create:
            return path
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            return tempfile.gettempdir()

    app = None
    if _HAS_WX and hasattr(wx, "GetApp"):
        try:
            app = wx.GetApp()
        except Exception:
            app = None
    if _HAS_WX and app is not None:
        try:
            paths = wx.StandardPaths.Get()
            config_dir = paths.GetUserConfigDir()
            if create:
                os.makedirs(config_dir, exist_ok=True)
            return config_dir
        except Exception:
            pass

    if sys.platform == "darwin":
        path = os.path.join(os.path.expanduser("~/Library/Application Support"), LEGACY_APP_DATA_DIR_NAME)
    else:
        path = os.path.join(os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), LEGACY_APP_DATA_DIR_NAME)

    if not create:
        return path
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:
        return tempfile.gettempdir()


def _dedupe_paths(paths):
    unique = []
    seen = set()
    for candidate in paths:
        if candidate and candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def _copy_file_if_missing(src: str, dest: str) -> None:
    if not src or not dest or not os.path.isfile(src) or os.path.exists(dest):
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src, dest)


def _copy_tree_if_missing(src: str, dest: str) -> None:
    if not src or not dest or not os.path.isdir(src) or os.path.exists(dest):
        return
    shutil.copytree(src, dest)


def _prepare_windows_installed_data() -> None:
    """Copy legacy mutable files to the per-user installed-build directory."""
    if not is_windows_installed_build():
        return
    user_dir = get_user_config_dir()
    sentinel = os.path.join(user_dir, WINDOWS_INSTALL_MIGRATION_SENTINEL)
    if os.path.exists(sentinel):
        return

    old_user_dir = _legacy_user_config_dir()
    app_dir = get_app_dir()
    cwd = get_cwd_dir()
    config_dest = os.path.join(user_dir, CONFIG_FILE)
    for base in (old_user_dir, app_dir, cwd):
        if base:
            _copy_file_if_missing(os.path.join(base, CONFIG_FILE), config_dest)

    _copy_file_if_missing(
        os.path.join(old_user_dir, DVR_SCHEDULE_FILE),
        os.path.join(user_dir, DVR_SCHEDULE_FILE),
    )

    temp_dir = tempfile.gettempdir()
    for suffix in ("", "-wal", "-shm", "-journal"):
        name = EPG_DB_FILE + suffix
        _copy_file_if_missing(os.path.join(temp_dir, name), os.path.join(user_dir, name))

    _copy_file_if_missing(
        os.path.join(temp_dir, EPG_DEBUG_LOG_FILE),
        os.path.join(user_dir, EPG_DEBUG_LOG_FILE),
    )
    _copy_tree_if_missing(
        os.path.join(temp_dir, CACHE_DIR_NAME),
        os.path.join(user_dir, CACHE_DIR_NAME),
    )

    try:
        with open(sentinel, "w", encoding="utf-8") as handle:
            handle.write("ok\n")
    except Exception:
        pass


def get_config_read_candidates():
    if _is_windows_platform():
        user_config = os.path.join(get_user_config_dir(create=False), CONFIG_FILE)
        app_dir = get_app_dir()
        cwd = get_cwd_dir()
        candidates = []

        if is_windows_portable_build():
            if app_dir:
                candidates.append(os.path.join(app_dir, CONFIG_FILE))
            if cwd:
                candidates.append(os.path.join(cwd, CONFIG_FILE))
            candidates.append(user_config)
            candidates.append(os.path.join(_legacy_user_config_dir(), CONFIG_FILE))
        else:
            candidates.append(user_config)
            if app_dir:
                candidates.append(os.path.join(app_dir, CONFIG_FILE))
            if cwd:
                candidates.append(os.path.join(cwd, CONFIG_FILE))
            candidates.append(os.path.join(_legacy_user_config_dir(), CONFIG_FILE))

        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, CONFIG_FILE))
        return _dedupe_paths(candidates)

    # Revised priority to ensure the app-local config file is honored:
    # 1) App Dir (next to the code/executable)
    # 2) CWD (portable override when explicitly run from that folder)
    # 3) User Config Dir (standard per-user location)
    candidates = []

    app_dir = get_app_dir()
    if app_dir:
        candidates.append(os.path.join(app_dir, CONFIG_FILE))

    cwd = get_cwd_dir()
    if cwd:
        candidates.append(os.path.join(cwd, CONFIG_FILE))

    user_dir = get_user_config_dir(create=False)
    if user_dir:
        candidates.append(os.path.join(user_dir, CONFIG_FILE))

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, CONFIG_FILE))

    return _dedupe_paths(candidates)


def get_config_write_target():
    global _CONFIG_PATH

    if _is_windows_platform():
        if not is_windows_portable_build():
            return os.path.join(get_user_config_dir(), CONFIG_FILE)

        app_dir = get_app_dir()
        cwd = get_cwd_dir()
        if app_dir:
            if _is_writable_dir(app_dir):
                return os.path.join(app_dir, CONFIG_FILE)
        if _CONFIG_PATH:
            try:
                parent = os.path.dirname(_CONFIG_PATH)
                if parent and _is_writable_dir(parent):
                    return _CONFIG_PATH
            except Exception:
                pass
        if cwd:
            if _is_writable_dir(cwd):
                return os.path.join(cwd, CONFIG_FILE)
        return os.path.join(get_user_config_dir(), CONFIG_FILE)

    # Prefer writing back to the file that was loaded, to avoid surprises.
    if _CONFIG_PATH:
        try:
            parent = os.path.dirname(_CONFIG_PATH)
            if parent and _is_writable_dir(parent):
                return _CONFIG_PATH
        except Exception:
            pass

    # Otherwise, prefer App Dir, then CWD, then user config dir
    app_dir = get_app_dir()
    if app_dir and _is_writable_dir(app_dir):
        return os.path.join(app_dir, CONFIG_FILE)

    cwd = get_cwd_dir()
    if cwd and _is_writable_dir(cwd):
        return os.path.join(cwd, CONFIG_FILE)

    return os.path.join(get_user_config_dir(), CONFIG_FILE)


def _apply_internal_player_bounds(cfg: Dict) -> None:
    """Coerce internal player buffering settings into valid ranges."""
    max_val = cfg.get("internal_player_max_buffer_seconds", DEFAULT_INTERNAL_PLAYER_MAX_BUFFER_SECONDS)
    try:
        max_val = float(max_val)
    except Exception:
        max_val = DEFAULT_INTERNAL_PLAYER_MAX_BUFFER_SECONDS
    if max_val <= 0:
        max_val = DEFAULT_INTERNAL_PLAYER_MAX_BUFFER_SECONDS
    max_val = min(max_val, 300.0)  # Allow up to 5 mins buffer for stability
    cfg["internal_player_max_buffer_seconds"] = max_val

    base_val = cfg.get("internal_player_buffer_seconds", DEFAULT_INTERNAL_PLAYER_BUFFER_SECONDS)
    try:
        base_val = float(base_val)
    except Exception:
        base_val = DEFAULT_INTERNAL_PLAYER_BUFFER_SECONDS
    if base_val <= 0:
        base_val = DEFAULT_INTERNAL_PLAYER_BUFFER_SECONDS
    if base_val > max_val:
        base_val = max_val
    cfg["internal_player_buffer_seconds"] = base_val

    variant_cap = cfg.get("internal_player_variant_max_mbps", 0.0)
    try:
        variant_cap = float(variant_cap)
    except Exception:
        variant_cap = 0.0
    if variant_cap <= 0.0:
        variant_cap = 0.0
    else:
        variant_cap = max(0.25, min(variant_cap, 500.0))
    cfg["internal_player_variant_max_mbps"] = variant_cap


@dataclass(frozen=True)
class InternalPlayerSettings:
    base_buffer_seconds: float
    max_buffer_seconds: float
    variant_max_mbps: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "internal_player_buffer_seconds": self.base_buffer_seconds,
            "internal_player_max_buffer_seconds": self.max_buffer_seconds,
            "internal_player_variant_max_mbps": self.variant_max_mbps,
        }


def resolve_internal_player_settings(cfg: Dict) -> InternalPlayerSettings:
    """
    Normalize internal player buffer/variant settings and sync them back to cfg.
    This keeps a single place that clamps values before they reach the player.
    """
    if cfg is None:
        cfg = {}
    _apply_internal_player_bounds(cfg)
    settings = InternalPlayerSettings(
        base_buffer_seconds=float(cfg["internal_player_buffer_seconds"]),
        max_buffer_seconds=float(cfg["internal_player_max_buffer_seconds"]),
        variant_max_mbps=float(cfg["internal_player_variant_max_mbps"]),
    )
    cfg.update(settings.as_dict())
    return settings

def load_config() -> Dict:
    global _CONFIG_PATH
    _prepare_windows_installed_data()
    default = {
        "playlists": [],
        "epgs": [],
        "media_player": "VLC",
        "custom_player_path": "",
        "internal_player_buffer_seconds": DEFAULT_INTERNAL_PLAYER_BUFFER_SECONDS,
        "internal_player_max_buffer_seconds": DEFAULT_INTERNAL_PLAYER_MAX_BUFFER_SECONDS,
        "internal_player_variant_max_mbps": 0.0,
        "minimize_to_tray": False,
        "auto_check_updates": True,
        "epg_enabled": True,
        "epg_auto_import_interval_hours": 6.0,
        "show_player_on_enter": True,
        "language": "auto",
        "recordings_dir": "",
        "recording_format": DEFAULT_RECORDING_FORMAT,
        "recording_pre_padding_minutes": DEFAULT_RECORDING_PRE_PADDING_MINUTES,
        "recording_post_padding_minutes": DEFAULT_RECORDING_POST_PADDING_MINUTES,
    }
    resolve_internal_player_settings(default)
    for p in get_config_read_candidates():
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Ensure all default keys are present
                    for k, v in default.items():
                        data.setdefault(k, v)
                    if data.get("internal_player_buffer_seconds") == 12.0:
                        data["internal_player_buffer_seconds"] = DEFAULT_INTERNAL_PLAYER_BUFFER_SECONDS
                    data["recording_format"] = normalize_recording_format(data.get("recording_format"))
                    normalize_recording_padding(data)
                    resolve_internal_player_settings(data)
                    _CONFIG_PATH = p
                    return data
            except Exception as e:
                _log_error(f"Failed to load config from {p}: {e}")
                # Do not break; try the next candidate location.
    # No config found; remember where a future save should write.
    try:
        _CONFIG_PATH = get_config_write_target()
    except Exception:
        _CONFIG_PATH = None
    normalize_recording_padding(default)
    return default

def save_config(cfg: Dict):
    global _CONFIG_PATH
    cfg["recording_format"] = normalize_recording_format(cfg.get("recording_format"))
    normalize_recording_padding(cfg)
    resolve_internal_player_settings(cfg)
    path = get_config_write_target()
    try:
        # Ensure the directory exists before writing; skip if writing to CWD
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            os.rename(tmp_path, path)
        _CONFIG_PATH = path
    except Exception as e:
        _log_error(f"Failed to save config to {path}: {e}")

def get_loaded_config_path() -> str:
    """Return the config path most recently loaded or saved, if known."""
    return _CONFIG_PATH or ""

def get_cache_dir():
    if _is_windows_platform():
        cache_dir = os.path.join(get_user_config_dir(), CACHE_DIR_NAME)
    else:
        cache_dir = os.path.join(tempfile.gettempdir(), CACHE_DIR_NAME)
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_cache_path_for_url(url):
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(get_cache_dir(), f"{h}.m3u")

def normalize_recording_format(value) -> str:
    """Clamp a recording-format key to a known preset, defaulting to MKV copy."""
    try:
        from recorder import RECORDING_FORMATS
    except Exception:
        return value if value == DEFAULT_RECORDING_FORMAT else DEFAULT_RECORDING_FORMAT
    if isinstance(value, str) and value in RECORDING_FORMATS:
        return value
    return DEFAULT_RECORDING_FORMAT

def _coerce_padding_minutes(value, default: int) -> int:
    try:
        minutes = int(float(value))
    except Exception:
        minutes = default
    return max(0, min(minutes, 180))

def normalize_recording_padding(cfg: Dict) -> None:
    """Clamp DVR padding settings in minutes."""
    if cfg is None:
        return
    cfg["recording_pre_padding_minutes"] = _coerce_padding_minutes(
        cfg.get("recording_pre_padding_minutes"), DEFAULT_RECORDING_PRE_PADDING_MINUTES)
    cfg["recording_post_padding_minutes"] = _coerce_padding_minutes(
        cfg.get("recording_post_padding_minutes"), DEFAULT_RECORDING_POST_PADDING_MINUTES)

def _windows_videos_dir():
    """Resolve the Windows 'Videos' known folder, falling back to ~/Videos."""
    try:
        # FOLDERID_Videos = {18989B1D-99B5-455B-841C-AB7C74E4DDFC}
        from ctypes import wintypes
        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_byte * 8)]
        folderid = GUID(0x18989B1D, 0x99B5, 0x455B,
                        (ctypes.c_byte * 8)(0x84, 0x1C, 0xAB, 0x7C, 0x74, 0xE4, 0xDD, 0xFC))
        path_ptr = ctypes.c_void_p()
        res = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folderid), 0, None, ctypes.byref(path_ptr))
        if res == 0 and path_ptr.value:
            value = ctypes.wstring_at(path_ptr.value)
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            return value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Videos")

def get_recordings_dir(cfg: Dict) -> str:
    """Resolve the directory recordings are written to (creating it)."""
    configured = (cfg or {}).get("recordings_dir") or ""
    if configured.strip():
        target = os.path.expanduser(configured.strip())
    else:
        if _IS_WINDOWS:
            videos = _windows_videos_dir()
        else:
            videos = os.path.join(os.path.expanduser("~"), "Videos")
        target = os.path.join(videos, "Accessible IPTV Recordings")
    try:
        os.makedirs(target, exist_ok=True)
    except Exception:
        pass
    return target

def get_dvr_schedule_path() -> str:
    """Path to the persistent scheduled-recordings store."""
    return os.path.join(get_user_config_dir(), DVR_SCHEDULE_FILE)


def get_db_path():
    if _is_windows_platform():
        return os.path.join(get_user_config_dir(), EPG_DB_FILE)
    return os.path.join(tempfile.gettempdir(), EPG_DB_FILE)


def get_epg_log_path():
    if _is_windows_platform():
        return os.path.join(get_user_config_dir(), EPG_DEBUG_LOG_FILE)
    return os.path.join(tempfile.gettempdir(), EPG_DEBUG_LOG_FILE)

# Strip from names when canonicalizing (NOT used to detect country)
STRIP_TAGS = [
    'hd', 'sd', 'hevc', 'fhd', 'uhd', '4k', '8k', 'hdr', 'dash', 'hq', 'st',
    'us', 'usa', 'ca', 'canada', 'car', 'uk', 'u.k.', 'u.k', 'uk.', 'u.s.', 'u.s', 'us.',
    'au', 'aus', 'nz', 'eu', 'ukhd', 'uksd', 'fhd', 'uhd', 'h.265', 'h265', 'h.264', 'h264',
    '50fps', '60fps'
]

def group_synonyms():
    # Canonical country code -> variants
    return {
        # North America
        "us": ["us", "usa", "u.s.", "u.s", "us.", "united states", "united states of america", "america"],
        "ca": ["ca", "can", "canada", "car"],
        "mx": ["mx", "mex", "mexico", "méxico"],

        # UK + Ireland
        "uk": ["uk", "u.k.", "gb", "gbr", "great britain", "britain", "united kingdom", "england", "scotland", "wales", "northern ireland"],
        "ie": ["ie", "irl", "ireland", "eire", "éire"],

        # DACH
        "de": ["de", "ger", "deu", "germany", "deutschland"],
        "at": ["at", "aut", "austria", "österreich", "oesterreich"],
        "ch": ["ch", "che", "switzerland", "schweiz", "suisse", "svizzera"],

        # Benelux
        "nl": ["nl", "nld", "netherlands", "holland", "nederland"],
        "be": ["be", "bel", "belgium", "belgie", "belgië", "belgique"],
        "lu": ["lu", "lux", "luxembourg", "letzebuerg", "lëtzebuerg"],

        # Nordics
        "se": ["se", "swe", "sweden", "svenska", "sverige"],
        "no": ["no", "nor", "norway", "norge", "noreg"],
        "dk": ["dk", "dnk", "denmark", "danmark"],
        "fi": ["fi", "fin", "finland", "suomi"],
        "is": ["is", "isl", "iceland", "ísland"],

        # Southern Europe
        "fr": ["fr", "fra", "france", "français", "française"],
        "it": ["it", "ita", "italy", "italia"],
        "es": ["es", "esp", "spain", "españa", "espana", "español"],
        "pt": ["pt", "prt", "portugal", "português"],
        "gr": ["gr", "grc", "greece", "ελλάδα", "ellada"],
        "mt": ["mt", "mlt", "malta"],
        "cy": ["cy", "cyp", "cyprus"],

        # Central/Eastern Europe
        "pl": ["pl", "pol", "poland", "polska"],
        "cz": ["cz", "cze", "czech", "czechia", "cesko", "česko"],
        "sk": ["sk", "svk", "slovakia", "slovensko"],
        "hu": ["hu", "hun", "hungary", "magyar"],
        "si": ["si", "svn", "slovenia", "slovenija"],
        "hr": ["hr", "hrv", "croatia", "hrvatska"],
        "rs": ["rs", "srb", "serbia", "srbija"],
        "ba": ["ba", "bih", "bosnia", "bosnia and herzegovina", "bosna", "hercegovina"],
        "mk": ["mk", "mkd", "north macedonia", "macedonia"],
        "ro": ["ro", "rou", "romania", "românia"],
        "bg": ["bg", "bgr", "bulgaria", "българия", "balgariya"],
        "ua": ["ua", "ukr", "ukraine", "ukraina"],
        "by": ["by", "blr", "belarus"],
        "ru": ["ru", "rus", "russia", "россия", "rossiya"],
        "ee": ["ee", "est", "estonia", "eesti"],
        "lv": ["lv", "lva", "latvia", "latvija"],
        "lt": ["lt", "ltu", "lithuania", "lietuva"],

        # Balkans + nearby
        "al": ["al", "alb", "albania", "shqipëri", "shqiperia"],
        "me": ["me", "mne", "montenegro", "crna gora"],
        "xk": ["xk", "kosovo"],

        # MENA (subset)
        "tr": ["tr", "tur", "turkey", "türkiye", "turkiye"],
        "ma": ["ma", "mar", "morocco", "maroc"],
        "dz": ["dz", "dza", "algeria", "algérie"],
        "tn": ["tn", "tun", "tunisia", "tunisie"],
        "eg": ["eg", "egypt", "misr"],
        "il": ["il", "isr", "israel"],
        "sa": ["sa", "sau", "saudi", "saudi arabia"],
        "ae": ["ae", "are", "uae", "united arab emirates"],
        "qa": ["qa", "qat", "qatar"],
        "kw": ["kw", "kwt", "kuwait"],

        # Asia (subset)
        "in": ["in", "ind", "india", "bharat"],
        "pk": ["pk", "pak", "pakistan"],
        "bd": ["bd", "bgd", "bangladesh"],
        "lk": ["lk", "lka", "sri lanka"],
        "np": ["np", "npl", "nepal"],
        "cn": ["cn", "chn", "china"],
        "hk": ["hk", "hkg", "hong kong"],
        "tw": ["tw", "twn", "taiwan"],
        "jp": ["jp", "jpn", "japan", "日本"],
        "kr": ["kr", "kor", "korea", "south korea"],
        "sg": ["sg", "sgp", "singapore"],
        "my": ["my", "mys", "malaysia"],
        "th": ["th", "tha", "thailand"],
        "vn": ["vn", "vnm", "vietnam"],
        "ph": ["ph", "phl", "philippines"],
        "id": ["id", "idn", "indonesia"],

        # Oceania
        "au": ["au", "aus", "australia"],
        "nz": ["nz", "nzl", "new zealand", "aotearoa"],

        # Latin America (subset)
        "br": ["br", "bra", "brazil", "brasil"],
        "ar": ["ar", "arg", "argentina"],
        "cl": ["cl", "chl", "chile"],
        "co": ["co", "col", "colombia"],
        "pe": ["pe", "per", "peru", "perú"],
        "uy": ["uy", "ury", "uruguay"],
        "py": ["py", "pry", "paraguay"],
        "bo": ["bo", "bol", "bolivia"],
        "ec": ["ec", "ecu", "ecuador"],
        "ve": ["ve", "ven", "venezuela"],
        "cr": ["cr", "cri", "costa rica"],
        "pr": ["pr", "pri", "puerto rico"],

        # Africa (subset)
        "ng": ["ng", "nga", "nigeria"],
        "za": ["za", "zaf", "south africa"],
        "ke": ["ke", "ken", "kenya"],
        "gh": ["gh", "gha", "ghana"],
        "et": ["et", "eth", "ethiopia"],
        "tz": ["tz", "tza", "tanzania"],
        "ug": ["ug", "uga", "uganda"],
        "ci": ["ci", "civ", "côte d’ivoire", "ivory coast"],
        "sn": ["sn", "sen", "senegal"],
    }

def _build_reverse_country_lookup():
    lookup = {}
    for code, variants in group_synonyms().items():
        for v in variants:
            lookup[v.lower()] = code
    lookup["gb"] = "uk"
    lookup["gbr"] = "uk"
    return lookup

_COUNTRY_LOOKUP = _build_reverse_country_lookup()

def _normalize_country_token(tok: str) -> str:
    if not tok:
        return ''
    t = tok.strip().lower()
    if t in _COUNTRY_LOOKUP:
        return _COUNTRY_LOOKUP[t]
    t2 = t.replace('.', '')
    if t2 in _COUNTRY_LOOKUP:
        return _COUNTRY_LOOKUP[t2]
    return ''

def canonicalize_name(name: str) -> str:
    name = (name or "").strip().lower()
    tags = STRIP_TAGS
    pattern = r'^(?:' + '|'.join(tags) + r')\b[\s\-:()[\]]*|[\s\-:()[\]]*\b(?:' + '|'.join(tags) + r')$'
    while True:
        newname = re.sub(pattern, '', name, flags=re.I).strip()
        if newname == name:
            break
        name = newname
    name = re.sub(r'\b(?:' + '|'.join(tags) + r')\b', '', name, flags=re.I)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()

def relaxed_name(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r'[\(\[].*?[\)\]]', '', n)
    tags = r'\b(?:' + '|'.join(STRIP_TAGS) + r')\b'
    n = re.sub(tags, '', n, flags=re.I)
    n = re.sub(r'[^\w\s]', '', n)
    n = re.sub(r'\s+', ' ', n)
    return n.strip()

def _search_country_in_text(text: str) -> str:
    if not text:
        return ''
    s = text.lower()
    for m in re.findall(r'[\(\[\{]([^\)\]\}]{2,24})[\)\]\}]', s):
        for token in re.findall(r'[a-zA-ZÀ-ÿ\.]+', m):
            code = _normalize_country_token(token)
            if code:
                return code
    for token in re.split(r'[\|\-\/:,–—]+', s):
        token = token.strip()
        code = _normalize_country_token(token)
        if code:
            return code
    for word in re.findall(r'[a-zA-ZÀ-ÿ\.]+', s):
        code = _normalize_country_token(word)
        if code:
            return code
    m = re.match(r'^\s*([a-zA-Z\.]{2,4})\b', s)
    if m:
        code = _normalize_country_token(m.group(1))
        if code:
            return code
    return ''

def extract_group(title: str) -> str:
    return _search_country_in_text(title or "")

def utc_to_local(dt):
    if _IS_WINDOWS:
        _refresh_windows_timezone()
    if dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            dt = dt
    return dt.astimezone()

if _HAS_WX:
    class CustomPlayerDialog(wx.Dialog):  # type: ignore[misc]
        def __init__(self, parent, initial_path):
            super().__init__(parent, title=_("Select Custom Player"))
            self.path = initial_path or ""
            sizer = wx.BoxSizer(wx.VERTICAL)
            self.txt = wx.TextCtrl(self, value=self.path)
            browse = wx.Button(self, label=_("Browse..."))
            btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
            sizer.Add(wx.StaticText(self, label=_("Enter player executable or path:")), 0, wx.ALL, 5)
            sizer.Add(self.txt, 0, wx.EXPAND | wx.ALL, 5)
            sizer.Add(browse, 0, wx.ALL, 5)
            sizer.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 5)
            self.SetSizerAndFit(sizer)
            browse.Bind(wx.EVT_BUTTON, self.on_browse)

        def on_browse(self, _event):
            with wx.FileDialog(self, _("Select Player Executable"), style=wx.FD_OPEN) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    self.txt.SetValue(dlg.GetPath())

        def GetPath(self):
            return self.txt.GetValue()
else:
    class CustomPlayerDialog:  # type: ignore[too-many-ancestors]
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("CustomPlayerDialog requires wxPython. Install wxPython to use this dialog.")

        def GetPath(self):
            return ""
