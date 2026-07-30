import os
import re
import gzip
import time
import tracemalloc
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
import datetime
import logging
import logging.handlers
import tempfile
import random
import hashlib
import threading
from http.client import IncompleteRead
from providers import generate_provider_id
from options import get_epg_log_path
from typing import Dict, List, Optional, Tuple, Set

import sys

from i18n import gettext as _

try:
    import wx  # type: ignore
    WX_AVAILABLE = True
except ModuleNotFoundError:
    wx = None  # type: ignore
    WX_AVAILABLE = False


def _log_wx_error(message: str):
    text = str(message or "")
    if WX_AVAILABLE and hasattr(wx, "LogError"):
        try:
            # wx logging APIs treat % tokens as printf placeholders; escape them first.
            wx.LogError(text.replace("%", "%%"))
            return
        except Exception:
            _logger.debug("_log_wx_error: ignored exception", exc_info=True)
    sys.stderr.write(f"{text}\n")


if WX_AVAILABLE:
    class _FieldAccessible(wx.Accessible):  # type: ignore[misc]
        def __init__(self, label: str, description: str):
            super().__init__()
            self._label = label
            self._description = description

        def GetName(self, childId):
            if childId in (0, wx.ACC_SELF):
                return wx.ACC_OK, self._label
            return wx.ACC_NOT_IMPLEMENTED, None

        def GetDescription(self, childId):
            if childId in (0, wx.ACC_SELF):
                return wx.ACC_OK, self._description
            return wx.ACC_NOT_IMPLEMENTED, None

    def _attach_field_accessible(ctrl, label: str, description: str):
        """Give ``ctrl`` a custom MSAA accessible carrying label and description.

        wx.Accessible is the MSAA (Windows) bridge. On wxGTK a Python-derived
        accessible is called back straight from the ATK/AT-SPI bridge while the
        dialog is still being built, which can leave the dialog unmapped or wedge
        the event loop, and GTK already exposes the label through SetName() /
        SetAccessibleName(). So this is a Windows-only decoration.
        """
        if wx.Platform != "__WXMSW__" or not hasattr(ctrl, "SetAccessible"):
            return
        try:
            acc = _FieldAccessible(label, description)
            ctrl.SetAccessible(acc)
            ctrl._field_accessible = acc  # keep the Python object alive
        except Exception:
            _logger.debug("_attach_field_accessible: ignored exception", exc_info=True)

    def _nudge_off_parent(dlg):
        """Stop a nested dialog from hiding exactly inside its parent's footprint.

        Centred on its parent, a provider dialog can land wholly within the
        Playlist Manager's rectangle. Raising it normally covers that, but a window
        manager that refuses to stack a dialog above its (already modal) parent then
        leaves nothing at all on screen, which is what issue #7 looked like. Only
        wxGTK needs this insurance; MSW and macOS stack nested modals correctly, so
        they keep the nicer centred placement.
        """
        if wx.Platform != "__WXGTK__":
            return
        try:
            parent = dlg.GetParent()
            if parent is None:
                return
            rect = dlg.GetScreenRect()
            parent_rect = parent.GetScreenRect()
            if not parent_rect.Contains(rect):
                return  # already sticking out somewhere: visible either way
            index = wx.Display.GetFromWindow(dlg)
            area = wx.Display(index if index != wx.NOT_FOUND else 0).GetClientArea()
            margin = 48
            x = min(parent_rect.GetRight() - rect.GetWidth() + margin, area.GetRight() - rect.GetWidth())
            y = min(parent_rect.GetBottom() - rect.GetHeight() + margin, area.GetBottom() - rect.GetHeight())
            dlg.Move(max(area.GetLeft(), x), max(area.GetTop(), y))
        except Exception:
            _logger.debug("_nudge_off_parent: ignored exception", exc_info=True)

    def _show_modal_raised(dlg, focus_ctrl=None):
        """ShowModal a dialog, making sure it is really on top and focused.

        The provider dialogs are opened from the already-modal Playlist Manager.
        Some window managers stack such a nested dialog *behind* its parent, so it
        is invisible while still blocking input and the app looks frozen with no
        way to type credentials. Raising it once the nested event loop is running
        puts it back in front; focusing the first field also gives a screen reader
        something to announce on open.
        """
        def present():
            try:
                if not dlg.IsShown():
                    return
            except Exception:
                _logger.debug("_show_modal_raised.present: ignored exception", exc_info=True)
                return
            _nudge_off_parent(dlg)
            try:
                dlg.Raise()
                target = focus_ctrl if focus_ctrl is not None else dlg
                target.SetFocus()
            except Exception:
                _logger.debug("_show_modal_raised.present: ignored exception", exc_info=True)

        wx.CallAfter(present)
        return dlg.ShowModal()
else:
    class _FieldAccessible:  # type: ignore[misc]
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("_FieldAccessible requires wxPython. Install wxPython to use GUI dialogs.")

    def _attach_field_accessible(_ctrl, _label, _description):
        return

    def _nudge_off_parent(_dlg):
        return

    def _show_modal_raised(_dlg, _focus_ctrl=None):
        raise RuntimeError("_show_modal_raised requires wxPython. Install wxPython to use GUI dialogs.")

# =========================
# Debug logging (rotating file) + memory helpers
# =========================

DEBUG = True if os.getenv("EPG_DEBUG", "0").strip() not in {"0", "false", "False"} else False
LOG_PATH = get_epg_log_path()
_logger = logging.getLogger("EPG")
if not _logger.handlers:
    _logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    try:
        _fh = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8", delay=True)
        _fh.setFormatter(_fmt)
        _logger.addHandler(_fh)
        # Also mirror to stderr while debugging (harmless if GUI)
        if DEBUG:
            _sh = logging.StreamHandler()
            _sh.setFormatter(_fmt)
            _logger.addHandler(_sh)
        _logger.debug("EPG debug logging initialized. File: %s", LOG_PATH)
    except Exception as e:
        # If logging setup fails, don't crash the app. Print error and continue.
        print(f"FATAL: Could not initialize logger at {LOG_PATH}. Error: {e}")


def _mem_mb() -> int:
    try:
        import psutil  # optional
        p = psutil.Process(os.getpid())
        return int(p.memory_info().rss / (1024 * 1024))
    except Exception:
        try:
            import resource  # *nix
            # ru_maxrss is in kilobytes on Linux, bytes on macOS; normalize to MB best-effort
            rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if rss_kb > 1024 * 1024:  # assume bytes (macOS)
                return int(rss_kb / (1024 * 1024))
            return int(rss_kb / 1024)
        except Exception:
            return -1

def _safe(s: str, n=200) -> str:
    s = str(s or "")
    return (s[:n] + "...") if len(s) > n else s

# Redact sensitive query values when logging URLs
_SENSITIVE_QUERY_KEYS = {
    'username','user','login','u','password','pass','pwd','token','auth','apikey','api_key','key','secret'
}

def _sanitize_url(url: str) -> str:
    try:
        if not url:
            return url
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            return url
        q = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        redacted = []
        for k, v in q:
            if (k or '').lower() in _SENSITIVE_QUERY_KEYS:
                redacted.append((k, '***'))
            else:
                redacted.append((k, v))
        new_query = urllib.parse.urlencode(redacted)
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
    except Exception:
        # Fail open: never block logging; return a conservative redaction when in doubt
        try:
            return re.sub(r"(?i)(username|user|login|u|password|pass|pwd|token|auth|apikey|api_key|key|secret)=([^&\s]+)", r"\1=***", str(url))
        except Exception:
            return str(url)

# Ensure only one thread mutates a temp gzip download at a time to avoid
# truncation races when multiple imports target the same source URL.
_DOWNLOAD_LOCKS: Dict[str, threading.Lock] = {}
_DOWNLOAD_LOCKS_GUARD = threading.Lock()


def _acquire_download_lock(path_key: str) -> threading.Lock:
    with _DOWNLOAD_LOCKS_GUARD:
        lock = _DOWNLOAD_LOCKS.get(path_key)
        if lock is None:
            lock = threading.Lock()
            _DOWNLOAD_LOCKS[path_key] = lock
    lock.acquire()
    return lock

# Cross-process EPG import lock (best-effort, file-based)
def _import_lock_paths(db_path: str) -> Tuple[str, str]:
    base_dir = os.path.dirname(db_path) or tempfile.gettempdir()
    fname = os.path.splitext(os.path.basename(db_path))[0]
    return (
        os.path.join(base_dir, f"{fname}.import.lock"),
        os.path.join(base_dir, f"{fname}.import.pid"),
    )

def _try_acquire_import_lock(db_path: str, max_wait_sec: int = 90) -> bool:
    lock_path, pid_path = _import_lock_paths(db_path)
    deadline = time.time() + max_wait_sec
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, b"locked")
            finally:
                os.close(fd)
            try:
                with open(pid_path, 'w', encoding='utf-8') as pf:
                    pf.write(str(os.getpid()))
            except Exception:
                _logger.debug("_try_acquire_import_lock: ignored exception", exc_info=True)
            _logger.debug("EPG import lock acquired: %s", lock_path)
            return True
        except FileExistsError:
            try:
                age = time.time() - os.stat(lock_path).st_mtime
            except Exception:
                age = 0
            if age > 2 * 60 * 60:  # 2 hours
                try:
                    os.remove(lock_path)
                except Exception:
                    _logger.debug("_try_acquire_import_lock: ignored exception", exc_info=True)
                try:
                    if os.path.exists(pid_path):
                        os.remove(pid_path)
                except Exception:
                    _logger.debug("_try_acquire_import_lock: ignored exception", exc_info=True)
                continue
            if time.time() >= deadline:
                # Silent negative result; caller decides whether to wait/log.
                return False
            time.sleep(1.0)
        except Exception:
            return True

def _release_import_lock(db_path: str):
    lock_path, pid_path = _import_lock_paths(db_path)
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        _logger.debug("_release_import_lock: ignored exception", exc_info=True)
    try:
        if os.path.exists(pid_path):
            os.remove(pid_path)
    except Exception:
        _logger.debug("_release_import_lock: ignored exception", exc_info=True)

def _wait_for_import_lock(db_path: str, poll_sec: int = 10, log_every: int = 30):
    """Block until the cross‑process import lock can be acquired.

    No user-facing popups; emits periodic debug logs only.
    """
    waited = 0
    while True:
        if _try_acquire_import_lock(db_path, max_wait_sec=poll_sec):
            return
        waited += poll_sec
        if waited % max(log_every, poll_sec) == 0:
            try:
                _logger.debug("EPG import waiting for lock; waited=%ss", waited)
            except Exception:
                _logger.debug("_wait_for_import_lock: ignored exception", exc_info=True)

# =========================
# Normalization & Tokenizing
# =========================

# Canonical implementations live in channel_names so options.py can share them
# without importing playlist (playlist already imports options). Re-exported here
# because callers and tests import these names from playlist.
from channel_names import (
    STRIP_TAGS,
    NOISE_WORDS,
    group_synonyms,
    canonicalize_name,
    strip_noise_words,
    extract_group,
)


def tokenize_channel_name(name: str) -> set:
    return set(_ordered_channel_tokens(name))


def _ordered_channel_tokens(*names: str) -> List[str]:
    """Return stable, useful channel-name tokens for DB candidate lookups."""
    bad = set(STRIP_TAGS + NOISE_WORDS + [
        'channel', 'tv', 'the', 'and', 'for', 'with', 'on', 'in', 'f',
        'geo', 'geoblocked', 'blocked', 'not', 'only'
    ])
    out: List[str] = []
    seen: Set[str] = set()
    for name in names:
        if not name:
            continue
        paren = re.findall(r'\(([^)]*)\)', name)
        outside = re.sub(r'\(.*?\)', ' ', name)
        words = re.findall(r'\w+', outside)
        paren_words: List[str] = []
        for p in paren:
            paren_words.extend(re.findall(r'\w+', p))
        for raw in words + paren_words:
            w = raw.lower()
            if len(w) <= 1 or w in bad or w.isdigit():
                continue
            if re.fullmatch(r'\d{3,4}p', w) or re.fullmatch(r'\d+k', w):
                continue
            if w not in seen:
                seen.add(w)
                out.append(w)
    return out


def _significant_channel_numbers(*texts: str) -> Set[str]:
    numbers: Set[str] = set()
    word_numbers = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
    }
    ignored = {
        "240", "360", "480", "540", "576", "720", "1080", "1440", "2160", "4320",
        "50", "60",
    }
    for text in texts:
        s = (text or "").lower()
        if not s:
            continue
        s = re.sub(r'\b(?:au|ca|ie|uk|gb|us)\d+\b', ' ', s)
        for raw in re.findall(r'\d+', s):
            normalized = raw.lstrip("0") or "0"
            if normalized in ignored:
                continue
            if len(normalized) > 3:
                continue
            numbers.add(normalized)
        for word, value in word_numbers.items():
            if re.search(r'\b' + re.escape(word) + r'\b', s):
                numbers.add(value)
    return numbers


def _expand_tvg_id_candidates(tvg_id: str) -> List[str]:
    """Expand common XMLTV id variants such as IPTV-org channel.au@City."""
    raw = (tvg_id or "").strip()
    if not raw:
        return []
    candidates: List[str] = []
    seen: Set[str] = set()

    def add(value: str):
        value = (value or "").strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            candidates.append(value)

    add(raw)
    base, sep, suffix = raw.partition("@")
    base_for_variants = base or raw

    def add_base_variants(value: str):
        m = re.match(r'^(.+)\.([A-Za-z]{2,3}\d*)$', value or "")
        if not m:
            return
        name_part, region_part = m.groups()
        lowered_name = name_part.lower()
        for quality in ("fhd", "uhd", "hd", "sd", "4k", "8k"):
            if lowered_name.endswith(quality) and len(name_part) > len(quality):
                add(f"{name_part[:-len(quality)]}.{region_part}")
                break
        if lowered_name.endswith("sport"):
            add(f"{name_part}s.{region_part}")

    add_base_variants(base_for_variants)
    if sep and base:
        add(base)
        add_base_variants(base)
        suffix_clean = re.sub(r'[^A-Za-z0-9]+', '', suffix or "")
        if suffix_clean and suffix_clean.lower() not in {"sd", "hd", "fhd", "uhd", "4k", "8k"}:
            m = re.match(r'^(.+)\.([A-Za-z]{2,3}\d*)$', base)
            if m:
                name_part, region_part = m.groups()
                add(f"{name_part}{suffix_clean}.{region_part}")
    return candidates


def _tvg_id_has_region_hint(tvg_id: str) -> bool:
    return bool(_detect_region_from_id(tvg_id or ""))


# =========================
# Matching helpers
# =========================

MATCH_DEBUG = bool(os.environ.get("EPG_MATCH_DEBUG")) or DEBUG

ZONE_SYNONYMS = {
    "east": {"east", "e", "eastern"},
    "west": {"west", "w", "western", "pacific", "p", "pt", "pst", "pdt", "pac"},
    "central": {"central", "c", "ct", "ctr"},
    "mountain": {"mountain", "mtn"},
    "atlantic": {"atlantic", "atl"},
}

def _mk(*xs):
    return {x.lower() for x in xs if x}

# ==== HBO Variant Helpers ====
_HBO_VARIANTS = ("base", "1", "2", "family", "latino", "signature", "comedy", "hits", "zone", "plus")

def _extract_hbo_variant(raw_text: str) -> str:
    if not raw_text:
        return ""
    s = raw_text.lower()
    if re.search(r'\bfamily\b', s): return "family"
    if re.search(r'\blatino\b', s): return "latino"
    if re.search(r'\bsignature\b', s): return "signature"
    if re.search(r'\bcomedy\b', s): return "comedy"
    if re.search(r'\bhits\b', s): return "hits"
    if re.search(r'\bzone\b', s): return "zone"
    if re.search(r'\bplus\b', s): return "plus"
    if re.search(r'\bhbo[\s\-]*1\b', s) or re.search(r'\b1\b', s): return "1"
    if re.search(r'\bhbo[\s\-]*2\b', s) or re.search(r'\b2\b', s): return "2"
    if re.search(r'\bhbo\b', s): return "base"
    return ""

def _normalize_hbo_variant(country_code: str, variant: str) -> str:
    v = (variant or "").strip().lower()
    cc = (country_code or "").strip().lower()
    if not v:
        return ""
    if cc == "us" and v == "1":
        return "base"
    return v

AFFILIATE_MARKETS: Dict[str, Dict[str, Dict[str, Set[str]]]] = {
    "ca": {
        "cbc": {"vancouver-bc": _mk("vancouver","bc"), "calgary-ab": _mk("calgary","ab"), "edmonton-ab": _mk("edmonton","ab"),
                "saskatoon-sk": _mk("saskatoon","sk"), "regina-sk": _mk("regina","sk"), "winnipeg-mb": _mk("winnipeg","mb"),
                "ottawa-on": _mk("ottawa","on"), "toronto-on": _mk("toronto","on"), "montreal-qc": _mk("montreal","montréal","qc"),
                "halifax-ns": _mk("halifax","ns"), "stjohns-nl": _mk("st johns","st. johns","nl")},
        "ctv": {"vancouver-bc": _mk("vancouver","bc"), "calgary-ab": _mk("calgary","ab"), "edmonton-ab": _mk("edmonton","ab"),
                "saskatoon-sk": _mk("saskatoon","sk"), "regina-sk": _mk("regina","sk"), "winnipeg-mb": _mk("winnipeg","mb"),
                "ottawa-on": _mk("ottawa","on"), "toronto-on": _mk("toronto","on"), "london-on": _mk("london","on"),
                "montreal-qc": _mk("montreal","montréal","qc"), "halifax-ns": _mk("halifax","ns")},
        "ctv2": {"vancouver-bc": _mk("vancouver","bc"), "ottawa-on": _mk("ottawa","on"), "london-on": _mk("london","on"), "windsor-on": _mk("windsor","on")},
        "citytv": {"vancouver-bc": _mk("vancouver","bc"), "calgary-ab": _mk("calgary","ab"), "edmonton-ab": _mk("edmonton","ab"),
                   "winnipeg-mb": _mk("winnipeg","mb"), "toronto-on": _mk("toronto","on"), "montreal-qc": _mk("montreal","montréal","qc")},
        "global": {"vancouver-bc": _mk("vancouver","bc","british columbia","global bc"), "calgary-ab": _mk("calgary","ab"),
                   "edmonton-ab": _mk("edmonton","ab"), "saskatoon-sk": _mk("saskatoon","sk"), "regina-sk": _mk("regina","sk"),
                   "winnipeg-mb": _mk("winnipeg","mb"), "toronto-on": _mk("toronto","on"), "montreal-qc": _mk("montreal","montréal","qc"),
                   "halifax-ns": _mk("halifax","ns")},
        "tsn": {"tsn1-west": _mk("tsn1","west","bc","ab","pacific","mountain"), "tsn2-central": _mk("central"),
                "tsn3-prairies": _mk("prairies","mb","sk"), "tsn4-ontario": _mk("ontario","on","toronto"),
                "tsn5-east": _mk("east","ottawa","montreal","qc","atlantic")},
        "sportsnet": {"pacific": _mk("pacific","bc","vancouver"), "west": _mk("west","ab","calgary","edmonton"),
                      "prairies": _mk("prairies","sk","mb"), "ontario": _mk("ontario","on","toronto"),
                      "east": _mk("east","qc","montreal","atlantic"), "one": _mk("sn1","sportsnet one","one"),
                      "360": _mk("sportsnet 360","sn360","360")},
        "tva": {"montreal-qc": _mk("montreal","montréal","qc")},
        "noovo": {"montreal-qc": _mk("montreal","montréal","qc")},
        "hbo": {},
    },
    "us": {"abc": {}, "nbc": {}, "cbs": {}, "fox": {}, "pbs": {}, "cw": {}, "mynetwork": {}, "telemundo": {}, "univision": {}, "hbo": {}},
    "uk": {"bbc one": {}, "bbc two": {}, "itv": {}, "sky crime": {}, "sky mix": {}, "sky max": {}},
    "de": {"ard": {}, "wdr": {}, "ndr": {}, "mdr": {}, "br": {}, "hr": {}, "rbb": {}, "swr": {}},
    "au": {"abc": {}, "seven": {}, "nine": {}, "ten": {}, "sbs": {}},
    "nz": {"tvnz 1": {}, "tvnz 2": {}, "three": {}},
}

AFFILIATE_BRANDS: Set[str] = {
    "cbc","ctv","ctv2","citytv","global","tva","noovo","tsn","sportsnet",
    "abc","nbc","cbs","fox","fxx","pbs","cw","mynetwork","telemundo","univision",
    "bbc one","bbc two","itv","channel 4","channel 5","sky crime","sky mix","sky max",
    "ard","wdr","ndr","mdr","br","hr","rbb","swr","seven","nine","ten","sbs","tvnz 1","tvnz 2","three",
    "hbo",
}

def _reverse_country_lookup():
    rev = {}
    for code, variants in group_synonyms().items():
        rev[code] = code
        for v in variants:
            rev[v.lower()] = code
        rev["gb"] = "uk"
        rev["gbr"] = "uk"
    return rev

_COUNTRY_LOOKUP = _reverse_country_lookup()

def _norm_country(tok: str) -> str:
    if not tok:
        return ''
    t = tok.strip().lower().replace('.', '')
    return _COUNTRY_LOOKUP.get(t, '')

def _detect_region_from_id(ch_id: str) -> str:
    if not ch_id:
        return ''
    s = ch_id.lower()
    base = s.split('@', 1)[0]

    def _token_variants(token: str):
        token = token.strip()
        if not token:
            return []
        # Strip common wrappers like parentheses before normalization
        token_core = token.strip('()[]{}')
        cleaned = re.sub(r'[^a-z]', '', token_core)
        out = []
        if cleaned:
            out.append(cleaned)
        # Also try trimming trailing digits only (e.g., "us2" -> "us")
        trimmed = re.sub(r'\d+$', '', token_core)
        trimmed = re.sub(r'[^a-z]', '', trimmed)
        if trimmed and trimmed not in out:
            out.append(trimmed)
        return out

    base_parts = re.split(r'[.\-_:|/]+', base)
    for token in reversed(base_parts):
        for candidate in _token_variants(token):
            code = _norm_country(candidate)
            if code:
                return code

    parts = re.split(r'[.\-_:|/@]+', s)
    for token in (list(reversed(parts)) + parts):
        for candidate in _token_variants(token):
            code = _norm_country(candidate)
            if code:
                return code

    # Last resort: pull a glued-on code out of the trailing segment only (e.g. "ukhd").
    # Scanning the *whole* id here (previously `s`) is wrong: for ids with a non-country
    # suffix (e.g. brand/source tags like "PEACOCK"/"distro"/"dtvsp"), the first 2-3
    # letters of the *channel name* can coincidentally equal a real country synonym
    # (e.g. "Bravo.PEACOCK" -> "bra" -> Brazil, "Cartoon.Network.PEACOCK" -> "car" -> Canada),
    # producing a confidently wrong region instead of ''.
    last = base_parts[-1] if base_parts else ''
    m = re.search(r'([a-z]{2,3})', last)
    if m:
        code = _norm_country(m.group(1))
        if code:
            return code
    return ''

_TS_REGEXES = [
    # +1, + 1, +2h, +2 hours, etc.
    re.compile(r'(?<!\w)\+\s*(\d{1,2})\s*(?:h|hr|hour|hours)?(?!\w)', re.I),
    # plus1, plus 1
    re.compile(r'\bplus\s*(\d{1,2})\b', re.I),
]
def _detect_timeshift(text: str) -> int:
    if not text:
        return 0
    s = str(text)
    for rx in _TS_REGEXES:
        m = rx.search(s)
        if m:
            try:
                v = int(m.group(1))
                if 0 < v <= 24:
                    return v
            except Exception:
                _logger.debug("_detect_timeshift: ignored exception", exc_info=True)
    return 0

def _detect_zone(text: str) -> str:
    if not text:
        return ''
    s = text.lower()
    for zone, toks in ZONE_SYNONYMS.items():
        for t in toks:
            if re.search(r'\b' + re.escape(t) + r'\b', s):
                return zone
    return ''

_CALLSIGN_CORE_RX = re.compile(r'\b([A-Z]{3,5})(?:\s*-\s*(?:TV|DT|DT\d|HD))?\b', re.I)
_CALLSIGN_PREFIXES = ('K','W','C')
def extract_callsigns(text: str) -> Set[str]:
    out = set()
    if not text:
        return out
    s = re.sub(r'[\[\]\(\)]', ' ', str(text).upper())
    for token in re.findall(r'[A-Z0-9\-]{3,8}', s):
        parts = re.split(r'[^A-Z0-9]+', token)
        for p in parts:
            if not p:
                continue
            m = _CALLSIGN_CORE_RX.match(p)
            core = None
            if m:
                core = m.group(1)
            else:
                m2 = re.match(r'^([A-Z]{3,5})(?:DT\d?|DT|TV|HD)?$', p)
                if m2:
                    core = m2.group(1)
            if core and core[0] in _CALLSIGN_PREFIXES:
                if core not in {"NEWS","SPORT","LIVE","PLUS","MAX","WEST","EAST"} and len(core) >= 3:
                    out.add(core)
    return out

def callsign_overlap_score(pl_calls: Set[str], epg_calls: Set[str]) -> Tuple[int, str]:
    if not pl_calls or not epg_calls:
        return 0, ''
    if pl_calls & epg_calls:
        return 100, '+callsign-exact'
    for a in pl_calls:
        for b in epg_calls:
            if a == b:
                return 100, '+callsign-exact'
            if a in b or b in a:
                return 70, '+callsign-core'
    return 0, ''

def _brand_key(name: str) -> str:
    n = canonicalize_name(strip_noise_words(name or ""))
    for toks in ZONE_SYNONYMS.values():
        n = re.sub(r'\b(' + '|'.join(re.escape(t) for t in toks) + r')\b', ' ', n, flags=re.I)
    n = re.sub(r'(?<!\w)\+\d{1,2}(?!\w)', ' ', n)
    n = re.sub(r'[^a-z0-9]+', '', n.lower())
    return n

def _reverse_brand_lookup(text: str) -> str:
    t = (text or "").lower()
    if "bbc one" in t: return "bbc one"
    if "bbc two" in t: return "bbc two"
    if "itv" in t: return "itv"
    if re.search(r'\bfxx\b', t): return "fxx"
    if "citytv" in t or re.search(r'\bcity\b', t): return "citytv"
    if "ctv2" in t: return "ctv2"
    if re.search(r'\bctv\b', t): return "ctv"
    if re.search(r'\bcbc\b', t): return "cbc"
    if "global" in t: return "global"
    if re.search(r'\btsn\b', t): return "tsn"
    if "sportsnet" in t or "sn1" in t or re.search(r'\bsn\b', t): return "sportsnet"
    if re.search(r'\babc\b', t): return "abc"
    if re.search(r'\bnbc\b', t): return "nbc"
    if re.search(r'\bcbs\b', t): return "cbs"
    if re.search(r'\bfox\b', t) and "fox news" not in t: return "fox"
    if re.search(r'\bhgtv\b', t) or ("hogar" in t and "hgtv" in t): return "hgtv"
    if re.search(r'\bpbs\b', t): return "pbs"
    if re.search(r'\bcw\b', t): return "cw"
    if "my network" in t or re.search(r'\bmyn\b', t): return "mynetwork"
    if "telemundo" in t: return "telemundo"
    if "univision" in t: return "univision"
    if "wdr" in t: return "wdr"
    if "ndr" in t: return "ndr"
    if "mdr" in t: return "mdr"
    if "rbb" in t: return "rbb"
    if "swr" in t: return "swr"
    if "sky crime" in t: return "sky crime"
    if "sky mix" in t or re.search(r'\bsky\s*mix\b', t): return "sky mix"
    if "sky max" in t or re.search(r'\bsky\s*max\b', t): return "sky max"
    if re.search(r'\bbr\b', t): return "br"
    if re.search(r'\bhr\b', t): return "hr"
    if re.search(r'\bhbo\b', t):
        return "hbo"
    return ""

def _normalize_str(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip().lower())

_US_STATE_NAMES = {
    "alabama":"al","alaska":"ak","arizona":"az","arkansas":"ar","california":"ca","colorado":"co","connecticut":"ct",
    "delaware":"de","florida":"fl","georgia":"ga","hawaii":"hi","idaho":"id","illinois":"il","indiana":"in","iowa":"ia",
    "kansas":"ks","kentucky":"ky","louisiana":"la","maine":"me","maryland":"md","massachusetts":"ma","michigan":"mi",
    "minnesota":"mn","mississippi":"ms","missouri":"mo","montana":"mt","nebraska":"ne","nevada":"nv","new hampshire":"nh",
    "new jersey":"nj","new mexico":"nm","new york":"ny","north carolina":"nc","north dakota":"nd","ohio":"oh","oklahoma":"ok",
    "oregon":"or","pennsylvania":"pa","rhode island":"ri","south carolina":"sc","south dakota":"sd","tennessee":"tn",
    "texas":"tx","utah":"ut","vermont":"vt","virginia":"va","washington":"wa","west virginia":"wv","wisconsin":"wi","wyoming":"wy",
    "district of columbia":"dc","washington, dc":"dc","washington dc":"dc"
}

def _market_tokens_for(country: str, brand: str, text: str) -> Tuple[Set[str], Set[str], Set[str]]:
    markets = set()
    provinces = set()
    cities = set()
    s = _normalize_str(text)

    for tok in re.findall(r'\b[a-z]{2,3}\b', s):
        t = tok.lower()
        if country == "ca" and t in {"bc","ab","sk","mb","on","qc","ns","nl","nb","pe","yt","nt","nu"}:
            provinces.add(t)
        elif country == "us" and t in {
            "ny","nj","pa","ma","ct","ri","nh","vt","me","dc","va","md","de","nc","sc","ga","fl","al","ms","la","tx","ok","nm","az","ca","or","wa","nv","ut","co","wy","mt","id",
            "nd","sd","ne","ks","mn","ia","mo","il","in","oh","mi","wi","tn","ky","wv","ar"
        }:
            provinces.add(t)
        elif country == "uk" and t in {"ni"}:
            provinces.add("ni")

    if country == "us":
        for full, abbr in _US_STATE_NAMES.items():
            if re.search(r'\b' + re.escape(full) + r'\b', s):
                provinces.add(abbr)

    markets_map = AFFILIATE_MARKETS.get(country, {}).get((brand or "").lower(), {})
    if markets_map:
        for mk, syns in markets_map.items():
            for syn in syns:
                if re.search(r'\b' + re.escape(syn) + r'\b', s):
                    markets.add(mk)
                    if '-' in mk:
                        cities.add(mk.split('-')[0])

    if country == "us":
        calls = extract_callsigns(text)
        if calls:
            markets |= {c.lower() for c in calls}
        MAJOR_US_CITIES = {
            "new york","los angeles","chicago","philadelphia","dallas","san francisco","washington","houston",
            "atlanta","boston","phoenix","seattle","tacoma","detroit","tampa","minneapolis","miami","denver","orlando",
            "cleveland","sacramento","st louis","portland","pittsburgh","raleigh","charlotte","baltimore",
            "indianapolis","san diego","nashville","salt lake","san antonio","kansas city","columbus","milwaukee",
            "cincinnati","austin","las vegas","new orleans","memphis","oklahoma city","albuquerque","boise","anchorage",
            "birmingham","charleston","charlottesville","chattanooga","dayton","des moines","el paso","fort worth","grand rapids",
            "greensboro","greenville","hartford","jacksonville","knoxville","louisville","madison","norfolk","omaha",
            "providence","richmond","rochester","roanoke","san jose","spokane","springfield","toledo","tucson","tulsa"
        }
        for city in MAJOR_US_CITIES:
            if re.search(r'\b' + re.escape(city) + r'\b', s):
                cities.add(city)

    return markets, provinces, cities

# =========================
# XMLTV time parsing to UTC (ROBUST & EXCEPTION-SAFE)
# =========================

_XMLTV_TS_RX = re.compile(r'^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\s*([+\-]\d{4})?$')

def _parse_xmltv_to_utc_str(s: str) -> Optional[str]:
    if not s:
        return None
    s = str(s).strip()
    try:
        if 'T' in s:
            if s.endswith('Z'):
                s = s[:-1] + '+00:00'
            elif re.search(r'[+\-]\d{4}$', s):
                s = s[:-2] + ':' + s[-2:]
            dt = datetime.datetime.fromisoformat(s)
        else: # Handle formats like "YYYYMMDDHHMMSS +ZZZZ"
            m = _XMLTV_TS_RX.match(s)
            if not m: return None
            # This branch is the per-programme hot path (millions of calls on large
            # feeds); datetime.strptime's locale-aware parsing dominated EPG import
            # CPU time in profiling (~55%). The fixed-width digit groups are already
            # validated by the regex, so construct directly instead.
            y, mo, d, h, mi, sec, offset_str = m.groups()
            dt = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec))
            if offset_str:
                # Parse sign and magnitude separately; floor-division on a negative
                # combined value mishandles half-hour zones (e.g. -0330 -> -3h50m).
                sign = -1 if offset_str[0] == '-' else 1
                off_hours = int(offset_str[1:3])
                off_minutes = int(offset_str[3:5])
                tz = datetime.timezone(sign * datetime.timedelta(hours=off_hours, minutes=off_minutes))
                dt = dt.replace(tzinfo=tz)
            else:
                 dt = dt.replace(tzinfo=datetime.timezone.utc)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        dt = dt.astimezone(datetime.timezone.utc)
        # Manual zero-padded formatting avoids strftime's (locale-aware) overhead;
        # fields are plain ints so this is a straight numeric format, no locale lookup.
        return "%04d%02d%02d%02d%02d%02d" % (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    except (ValueError, TypeError):
        return None


# ---- duration helpers ----

_ISO8601_DUR_RX = re.compile(
    r'^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$',
    re.I
)

def _parse_duration_to_seconds(s: str) -> Optional[int]:
    if not s:
        return None
    s = s.strip()
    # Try integer minutes (XMLTV <length> default is minutes)
    if re.match(r'^\d+$', s):
        try:
            return int(s) * 60
        except Exception:
            return None
    m = _ISO8601_DUR_RX.match(s)
    if m:
        days = int(m.group('days') or 0)
        hours = int(m.group('hours') or 0)
        minutes = int(m.group('minutes') or 0)
        seconds = int(m.group('seconds') or 0)
        return days*86400 + hours*3600 + minutes*60 + seconds
    return None

def _calc_end_from_length_or_duration(start_utc: Optional[str], elem: ET.Element) -> Optional[str]:
    """If provider uses <length units="minutes"> or <duration>PT...,
    compute end time. Returns UTC "YYYYMMDDHHMMSS" or None."""
    if not start_utc:
        return None
    # <length units="minutes">NN</length> or units="seconds"
    length_elem = elem.find(".//length")
    dur_seconds = None
    if length_elem is not None and (length_elem.text or "").strip():
        units = (length_elem.get("units") or "").strip().lower()
        try:
            val = float(length_elem.text.strip())
        except Exception:
            val = None
        if val is not None:
            if units in {"", "minute", "minutes", "mins", "min"}:
                dur_seconds = int(val * 60)
            elif units in {"second", "seconds", "sec", "secs"}:
                dur_seconds = int(val)
    if dur_seconds is None:
        # <duration>PT1H30M</duration>
        dur_elem = elem.find(".//duration")
        if dur_elem is not None and (dur_elem.text or "").strip():
            dur_seconds = _parse_duration_to_seconds(dur_elem.text.strip())
    if dur_seconds is None:
        return None
    try:
        st = datetime.datetime.strptime(start_utc, "%Y%m%d%H%M%S")
        end_dt = st + datetime.timedelta(seconds=dur_seconds)
        return end_dt.strftime("%Y%m%d%H%M%S")
    except Exception:
        return None

# =========================
# DB PRAGMAs
# =========================

PRAGMA_IMPORT = [
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA temp_store=MEMORY;",
    "PRAGMA mmap_size=268435456;",   # 256MB
    "PRAGMA cache_size=-131072;",    # ~128MB
    "PRAGMA wal_autocheckpoint=0;",  # we'll checkpoint manually
    "PRAGMA busy_timeout=20000;",
]


# Bump this whenever `_detect_region_from_id`'s logic changes in a way that could
# flip previously-computed group_tag values. `_repair_channel_regions_prefer_id`
# persists the version it last fully scanned under into PRAGMA user_version, so a
# DB only ever pays for a full channels-table scan once per logic change instead
# of on every EPGDatabase(...) open/reopen.
_REGION_REPAIR_SCHEMA_VERSION = 1

# Same idea as _REGION_REPAIR_SCHEMA_VERSION above, but for _repair_norm_names (bump
# whenever canonicalize_name/strip_noise_words change). Uses PRAGMA application_id --
# SQLite's other free header slot -- instead of user_version, which the region-repair
# gate above already owns. Without this gate, a live production EPG DB with ~26k
# channels was observed re-running the *full* channels-table normalize-and-rewrite
# on every single writable EPGDatabase() open/reopen (every 20s-4min in one debug log,
# whenever something reopened the connection), not just once.
_NORM_REPAIR_SCHEMA_VERSION = 1

PRAGMA_READONLY = [
    "PRAGMA busy_timeout=2000;",
    "PRAGMA read_uncommitted=1;",    # let readers proceed during writer txn
]


def epg_database_has_usable_data(db_path: str, now_utc: Optional[datetime.datetime] = None) -> bool:
    """Return True when the EPG DB has current/future joined channel data."""
    if not db_path or not os.path.exists(db_path):
        return False

    conn = None
    try:
        uri = f"file:{db_path}?mode=ro&cache=shared"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
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
            return False

        if now_utc is None:
            try:
                now_utc = datetime.datetime.now(datetime.UTC)
            except AttributeError:
                now_utc = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)
        else:
            now_utc = now_utc.astimezone(datetime.timezone.utc)

        now_str = now_utc.strftime("%Y%m%d%H%M%S")
        row = cur.execute(
            """
            SELECT 1
            FROM programmes p
            JOIN channels c ON c.id = p.channel_id
            WHERE p.end > ?
            LIMIT 1
            """,
            (now_str,),
        ).fetchone()
        return bool(row)
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                _logger.debug("epg_database_has_usable_data: ignored exception", exc_info=True)

# =========================
# EPG gzip download (resumable)
# =========================
class _TempGzipStream:
    """File-like wrapper that deletes the temp gz on close."""
    def __init__(self, temp_path: str, owning_lock: Optional[threading.Lock] = None):
        self._path = temp_path
        self._lock = owning_lock
        self._lock_released = False
        self._f = gzip.open(temp_path, 'rb')
    def read(self, *a, **kw):
        return self._f.read(*a, **kw)
    def close(self):
        if getattr(self, '_f', None) is None:
            self._release_lock()
            return
        try:
            self._f.close()
        finally:
            try:
                keep = os.getenv('EPG_KEEP_TEMP_GZ', '0').strip() in {'1', 'true', 'True'}
                if not keep:
                    os.remove(self._path)
            except Exception:
                _logger.debug("_TempGzipStream.close: ignored exception", exc_info=True)
            self._f = None
            self._release_lock()
    def __getattr__(self, name):
        return getattr(self._f, name)
    def _release_lock(self):
        if self._lock and not self._lock_released:
            try:
                self._lock.release()
            except RuntimeError:
                _logger.debug("_TempGzipStream._release_lock: ignored exception", exc_info=True)
            self._lock_released = True
    def __del__(self):
        try:
            self.close()
        except Exception:
            self._release_lock()

def _http_download_gz_with_resume(url: str, max_attempts: int = 4, chunk_size: int = 1 << 16) -> _TempGzipStream:
    """Download a gzip file to a temp path with HTTP Range resume and verify integrity.

    Returns an open `_TempGzipStream` guarded by a per-source lock once
    a full, verifiable gzip is present. Raises on failure after retries.
    """
    # Stable name in temp dir so we can resume within this process
    h = hashlib.md5(url.encode('utf-8', 'ignore')).hexdigest()
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"epg_{h}.xml.gz")
    lock = _acquire_download_lock(temp_path)
    success = False

    def _quick_gzip_probe(path: str) -> bool:
        """Lightweight integrity probe (read first 16KB) to avoid double full decompression."""
        try:
            with gzip.open(path, 'rb') as gzf:
                gzf.read(1 << 14)
            return True
        except Exception:
            return False

    attempts = 0
    last_err = None
    try:
        while attempts < max_attempts:
            attempts += 1
            try:
                existing = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
                # If existing file doesn't look like gzip, start over
                if existing > 0:
                    try:
                        with open(temp_path, 'rb') as _chk:
                            sig = _chk.read(2)
                        if sig != b'\x1f\x8b':
                            os.remove(temp_path)
                            existing = 0
                    except Exception:
                        try:
                            os.remove(temp_path)
                        except Exception:
                            _logger.debug("_http_download_gz_with_resume: ignored exception", exc_info=True)
                        existing = 0
                headers_base = {
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/gzip, application/xml, text/xml, */*",
                }
                mode = 'ab' if existing > 0 else 'wb'
                use_range = existing > 0
                resp = None
                while True:
                    headers = headers_base.copy()
                    if use_range:
                        headers['Range'] = f'bytes={existing}-'
                    req = urllib.request.Request(url, headers=headers)
                    try:
                        resp = urllib.request.urlopen(req, timeout=300)
                    except urllib.error.HTTPError as he:
                        if he.code == 416 and use_range:
                            _logger.debug("EPG HTTP 416 for %s, retrying without Range", _sanitize_url(url))
                            try:
                                if os.path.exists(temp_path):
                                    os.remove(temp_path)
                            except Exception:
                                _logger.debug("_http_download_gz_with_resume: ignored exception", exc_info=True)
                            use_range = False
                            existing = 0
                            mode = 'wb'
                            continue
                        last_err = he
                        resp = None
                    if resp is None:
                        time.sleep(0.5 * attempts)
                        break
                    status = getattr(resp, 'status', None) or getattr(resp, 'code', None)
                    if status == 200 and use_range:
                        # Server ignored range request entirely; restart clean.
                        mode = 'wb'
                        use_range = False
                        existing = 0
                    break
                if resp is None:
                    continue
                # Server-declared size for this response, so completeness is
                # verified by byte count rather than trusting the gzip probe
                # alone (a truncated multi-hundred-MB download can still leave
                # a structurally valid gzip header/first block).
                expected_total = None
                try:
                    if use_range:
                        crange = resp.info().get('Content-Range')
                        total_part = crange.rsplit('/', 1)[-1].strip() if crange else ''
                        if total_part.isdigit():
                            expected_total = int(total_part)
                        else:
                            clen = resp.info().get('Content-Length')
                            if clen is not None:
                                expected_total = existing + int(clen)
                    else:
                        clen = resp.info().get('Content-Length')
                        if clen is not None:
                            expected_total = int(clen)
                except Exception:
                    expected_total = None
                with open(temp_path, mode) as out:
                    while True:
                        try:
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            out.write(chunk)
                        except IncompleteRead as ire:
                            # Partial read; keep what we have, retry and resume
                            last_err = ire
                            break
                try:
                    resp.close()
                except Exception:
                    _logger.debug("_http_download_gz_with_resume: ignored exception", exc_info=True)
                final_size = os.path.getsize(temp_path)
                if expected_total is not None and final_size < expected_total:
                    # Byte count proves truncation even though the gzip probe
                    # below only reads the first 16KB; keep the partial file so
                    # the next attempt resumes via Range instead of restarting.
                    last_err = RuntimeError(f"incomplete gzip download: {final_size}/{expected_total} bytes")
                    time.sleep(0.5 * attempts)
                    continue
                # Quick probe for gzip integrity; avoid full second pass
                if _quick_gzip_probe(temp_path):
                    stream = _TempGzipStream(temp_path, lock)
                    success = True
                    return stream
                # Not complete (or corrupt); brief backoff and retry with Range
                last_err = last_err or RuntimeError('gzip verify failed; resuming download')
                time.sleep(0.5 * attempts)
                continue
            except Exception as e:
                last_err = e
                time.sleep(0.5 * attempts)
                continue
        # Retries exhausted; bubble a helpful error
        raise last_err or RuntimeError('Failed to download gzip with resume')
    finally:
        if not success:
            try:
                lock.release()
            except RuntimeError:
                _logger.debug("_http_download_gz_with_resume: ignored exception", exc_info=True)


# =========================
# EPG Database
# =========================

class EPGDatabase:
    def __init__(self, db_path: str, readonly: bool = False, for_threading: bool = False):
        self.db_path = db_path
        self.readonly = readonly
        self.for_threading = for_threading
        self._open()

    def _open(self):
        timeout = 30.0
        if self.readonly:
            # Open as read-only, shared cache; set reader-friendly pragmas
            uri = f"file:{self.db_path}?mode=ro&cache=shared"
            self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=timeout)
            for p in PRAGMA_READONLY:
                try:
                    self.conn.execute(p)
                except Exception:
                    _logger.debug("EPGDatabase._open: ignored exception", exc_info=True)
        else:
            # Writer/normal
            self.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=not self.for_threading,
                timeout=timeout
            )
            for p in PRAGMA_IMPORT:
                try:
                    self.conn.execute(p)
                except Exception:
                    _logger.debug("EPGDatabase._open: ignored exception", exc_info=True)
        if not self.readonly:
            self._create_tables()
            # Opportunistic repair: if we can write, reconcile any region mismatches
            # caused by ambiguous display names (e.g., "CA" for California vs Canada).
            try:
                self._repair_channel_regions_prefer_id()
                self._repair_norm_names()
            except Exception:
                _logger.debug("EPGDatabase._open: ignored exception", exc_info=True)

    def _create_tables(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id TEXT PRIMARY KEY,
                display_name TEXT,
                norm_name TEXT,
                group_tag TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS programmes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT,
                title TEXT,
                start TEXT,
                end TEXT,
                FOREIGN KEY(channel_id) REFERENCES channels(id),
                UNIQUE(channel_id, start, end)
            )
        """)
        # Indexes crucial for fast lookups
        # idx_programmes_channel_start_end is a left-prefix superset of (channel_id, start),
        # so the standalone (channel_id, start) index is redundant — drop it to speed bulk
        # inserts. The old (start, end) index and the never-used title index are replaced.
        c.execute("DROP INDEX IF EXISTS idx_programmes_channel_start")
        c.execute("DROP INDEX IF EXISTS idx_programmes_start_end")
        c.execute("DROP INDEX IF EXISTS idx_programmes_title")
        c.execute("CREATE INDEX IF NOT EXISTS idx_programmes_channel_end ON programmes (channel_id, end)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_programmes_channel_start_end ON programmes (channel_id, start, end)")
        # Covering index for "what's on now": range-scan start, filter end, no row lookups.
        c.execute("CREATE INDEX IF NOT EXISTS idx_programmes_start_cover ON programmes (start, end, channel_id, title)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_channels_norm ON channels (norm_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_channels_group ON channels (group_tag)")
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            _logger.debug("EPGDatabase.close: ignored exception", exc_info=True)

    def reopen(self):
        """Close and reopen the underlying SQLite connection, reapplying pragmas."""
        try:
            if hasattr(self, "conn"):
                self.conn.close()
        except Exception:
            _logger.debug("EPGDatabase.reopen: ignored exception", exc_info=True)
        self._open()

    def insert_channel(self, channel_id: str, display_name: str):
        name_region = extract_group(display_name)
        id_region = _detect_region_from_id(channel_id or "")
        # Prefer region derived from the channel id when it contradicts the display name.
        # This avoids false positives like "… Palm Springs CA …" (California) being tagged as Canada.
        if id_region and name_region and id_region != name_region:
            group_tag = id_region
        else:
            group_tag = name_region or id_region or ''
        norm = canonicalize_name(strip_noise_words(display_name))
        c = self.conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO channels (id, display_name, norm_name, group_tag) VALUES (?, ?, ?, ?)",
            (channel_id, display_name, norm, group_tag)
        )

    def _repair_channel_regions_prefer_id(self):
        """One-time reconciliation: if a channel's id clearly encodes a region
        (e.g., ".us", ".ca", ".uk") but the stored group_tag differs, fix it.
        Safe to run multiple times; only updates mismatches.

        Gated behind a persisted PRAGMA user_version marker (_REGION_REPAIR_SCHEMA_VERSION):
        a full `SELECT id, group_tag FROM channels` + per-row regex scan is expensive on
        real-world EPG databases (tens of thousands of channel rows), so once a DB has been
        scanned under the current region-detection logic, later EPGDatabase(...) opens/reopens
        (including the reopen() retry path in import_epg_xml) skip the scan entirely instead of
        unconditionally repeating it every time. Bump _REGION_REPAIR_SCHEMA_VERSION whenever
        _detect_region_from_id's logic changes so existing databases get one more repair pass.
        """
        try:
            c = self.conn.cursor()
            current_version = c.execute("PRAGMA user_version").fetchone()[0]
            if current_version >= _REGION_REPAIR_SCHEMA_VERSION:
                return
            rows = c.execute("SELECT id, group_tag FROM channels").fetchall()
            fixes = []
            for ch_id, grp in rows:
                want = _detect_region_from_id(ch_id or "")
                if want and want != (grp or ''):
                    fixes.append((want, ch_id))
            if fixes:
                c.executemany("UPDATE channels SET group_tag = ? WHERE id = ?", fixes)
                _logger.debug("Repaired channel regions using id for %d rows", len(fixes))
            # Mark this DB as scanned under the current logic even when nothing needed fixing,
            # so a clean/already-repaired DB never pays for the full scan again.
            c.execute("PRAGMA user_version = %d" % _REGION_REPAIR_SCHEMA_VERSION)
            self.conn.commit()
        except Exception as e:
            _logger.debug("Region repair skipped/failed: %s", e)

    def _repair_norm_names(self):
        """Re-normalize all channel names in the DB to match current canonicalize_name logic.

        Gated behind a persisted PRAGMA application_id marker (_NORM_REPAIR_SCHEMA_VERSION),
        mirroring how _repair_channel_regions_prefer_id is gated behind PRAGMA user_version:
        even the 50-row sample-then-maybe-full-scan approach here means every writable
        EPGDatabase(...) open/reopen pays at least a sample query, and pays a full
        channels-table SELECT + rewrite whenever the sample finds a mismatch. On a
        real-world ~26k-channel DB this showed up as a full rescan+rewrite repeating
        every open, not just once after a genuine logic change.
        """
        try:
            c = self.conn.cursor()
            current_version = c.execute("PRAGMA application_id").fetchone()[0]
            if current_version >= _NORM_REPAIR_SCHEMA_VERSION:
                return
            # Sample check
            sample = c.execute("SELECT id, display_name, norm_name FROM channels LIMIT 50").fetchall()
            updates = []
            for ch_id, disp, old_norm in sample:
                new_norm = canonicalize_name(strip_noise_words(disp))
                if new_norm != old_norm:
                    updates.append((new_norm, ch_id))

            # If we found mismatches in the sample, do a full scan/update
            if updates:
                _logger.info("Detected stale norm_names in EPG DB. Re-normalizing all channels...")
                all_rows = c.execute("SELECT id, display_name FROM channels").fetchall()
                full_updates = []
                for ch_id, disp in all_rows:
                    nn = canonicalize_name(strip_noise_words(disp))
                    full_updates.append((nn, ch_id))

                c.executemany("UPDATE channels SET norm_name = ? WHERE id = ?", full_updates)
                _logger.info("Re-normalized %d channels.", len(full_updates))
            # Mark this DB as checked under the current logic even when nothing needed
            # fixing, so a clean/already-repaired DB never pays for the scan again.
            c.execute("PRAGMA application_id = %d" % _NORM_REPAIR_SCHEMA_VERSION)
            self.conn.commit()
        except Exception as e:
            _logger.debug("Norm-name repair failed: %s", e)

    def insert_programme(self, channel_id: str, title: str, start_utc: str, end_utc: str):
        c = self.conn.cursor()
        c.execute("INSERT OR IGNORE INTO programmes (channel_id, title, start, end) VALUES (?, ?, ?, ?)",
                  (channel_id, title, start_utc, end_utc))

    def prune_old_programmes(self, days: int = 7):
        utcnow = self._utcnow()
        cutoff = (utcnow - datetime.timedelta(days=days)).strftime("%Y%m%d%H%M%S")
        c = self.conn.cursor()
        c.execute("DELETE FROM programmes WHERE end < ?", (cutoff,))
        self.conn.commit()

    def commit(self):
        self.conn.commit()

    # ---------- Candidate selection (fast; no full table scan) ----------
    def _candidate_rows(self, c, name: str, tvg_name: str, region: str) -> List[Tuple[str, str, str]]:
        """
        Return a limited set of likely channel rows: (id, display_name, group_tag)
        Strategy:
          1) exact norm_name for tvg_name and name
          2) brand-key LIKE
          3) token LIKEs (up to 3 tokens)
          4) restrict to region/unknown region when available
        """
        out: List[Tuple[str, str, str]] = []
        seen: Set[str] = set()

        def add_rows(rows):
            for r in rows:
                if r[0] not in seen:
                    seen.add(r[0])
                    out.append(r)

        norm_name = canonicalize_name(strip_noise_words(name))
        norm_tvg = canonicalize_name(strip_noise_words(tvg_name))
        brand = _brand_key(name)
        tokens = _ordered_channel_tokens(name, tvg_name)[:5]

        # NOTE: region_clause and params_region were removed during refactoring.
        # We now rely on the scoring phase to penalize region mismatches rather than hiding candidates.

        # 1) exact norm matches
        if norm_tvg:
            rows = c.execute(
                "SELECT id, display_name, group_tag FROM channels WHERE norm_name = ? LIMIT 100",
                [norm_tvg]
            ).fetchall()
            add_rows(rows)
        if norm_name and norm_name != norm_tvg:
            rows = c.execute(
                "SELECT id, display_name, group_tag FROM channels WHERE norm_name = ? LIMIT 100",
                [norm_name]
            ).fetchall()
            add_rows(rows)

        # 2) brand-key LIKE
        if brand:
            rows = c.execute(
                "SELECT id, display_name, group_tag FROM channels WHERE norm_name LIKE ? LIMIT 200",
                [f"%{brand}%"]
            ).fetchall()
            add_rows(rows)

        # 3) token LIKEs
        for tok in tokens:
            rows = c.execute(
                "SELECT id, display_name, group_tag FROM channels WHERE norm_name LIKE ? LIMIT 200",
                [f"%{tok}%"]
            ).fetchall()
            add_rows(rows)

        # Fallback if we still have nothing and region provided: pull small regional sample
        # (This is still useful to find generic regional channels if name matching fails completely)
        if not out and region:
            rows = c.execute(
                "SELECT id, display_name, group_tag FROM channels WHERE group_tag = ? LIMIT 200",
                (region,)
            ).fetchall()
            add_rows(rows)

        # Cap result size to keep scoring cheap
        return out[:400]

    def _has_any_schedule_from_now(self, ch_id: str) -> bool:
        now = self._utcnow().strftime("%Y%m%d%H%M%S")
        c = self.conn.cursor()
        row = c.execute(
            "SELECT 1 FROM programmes WHERE channel_id = ? AND end > ? LIMIT 1",
            (ch_id, now)
        ).fetchone()
        if not row:
            # Try next few hours window
            fut = (self._utcnow() + datetime.timedelta(hours=3)).strftime("%Y%m%d%H%M%S")
            row = c.execute(
                "SELECT 1 FROM programmes WHERE channel_id = ? AND start <= ? AND end > ? LIMIT 1",
                (ch_id, fut, now)
            ).fetchone()
        return bool(row)

    def _collect_candidates_by_id_and_name(self, c, tvg_id: str, tvg_name: str, name: str):
        candidates = {}

        tvg_id_candidates = _expand_tvg_id_candidates(tvg_id)
        tvg_id_candidate_keys = {candidate.strip().lower() for candidate in tvg_id_candidates}

        for candidate_id in tvg_id_candidates:
            row = c.execute(
                "SELECT id, group_tag, display_name FROM channels WHERE id = ? COLLATE NOCASE",
                (candidate_id,)
            ).fetchone()
            if row:
                why = 'exact-id' if candidate_id == tvg_id else 'expanded-tvg-id'
                candidates[row[0]] = {
                    'id': row[0],
                    'group_tag': row[1],
                    'score': 100,
                    'display_name': row[2],
                    'why': why,
                    'ts_offset': 0
                }

        if tvg_name:
            norm_tvg_name = canonicalize_name(strip_noise_words(tvg_name))
            rows = c.execute("SELECT id, group_tag, display_name FROM channels WHERE norm_name = ?", (norm_tvg_name,)).fetchall()
            playlist_numbers = _significant_channel_numbers(tvg_id, tvg_name, name)
            for r in rows:
                candidate_numbers = _significant_channel_numbers(r[0], r[2])
                existing = candidates.get(r[0])
                score = 96
                why = 'exact-tvg-name'
                if playlist_numbers:
                    if candidate_numbers & playlist_numbers:
                        score += 12
                        why += ' +number'
                    elif candidate_numbers:
                        score = 20
                        why += ' -number-mismatch'
                    else:
                        score -= 30
                        why += ' -number-missing'
                elif candidate_numbers:
                    score -= 15
                    why += ' -extra-number'
                if existing and existing.get('score', 0) >= score:
                    # Keep the stronger match (usually an exact-id hit).
                    continue
                candidates[r[0]] = {
                    'id': r[0],
                    'group_tag': r[1],
                    'score': score,
                    'display_name': r[2],
                    'why': why,
                    'ts_offset': 0
                }

        if tvg_id and _tvg_id_has_region_hint(tvg_id):
            for k, v in list(candidates.items()):
                if (k or '').strip().lower() in tvg_id_candidate_keys:
                    continue
                adj = max(1, v.get('score', 0) - 60)
                if adj == v.get('score'):
                    continue
                v = dict(v)
                v['score'] = adj
                extra = '-tvg-id-mismatch'
                why = v.get('why', '') or ''
                if extra not in why:
                    v['why'] = f"{why} {extra}".strip()
                candidates[k] = v

        return candidates

    def get_matching_channel_ids(self, channel: Dict[str, str]) -> Tuple[List[dict], str]:
        tvg_id = (channel.get("tvg-id") or "").strip()
        tvg_name = (channel.get("tvg-name") or "").strip()
        name = (channel.get("name") or "").strip()

        playlist_region = _derive_playlist_region(channel)
        if playlist_region != "us":
            for text in (tvg_name, name, channel.get("group", "")):
                lowered = (text or "").lower()
                if not lowered:
                    continue
                if re.search(r'\bus\s*[:\-]', lowered) or 'usa' in lowered or 'united states' in lowered:
                    playlist_region = "us"
                    break
        playlist_zone = _detect_zone(" ".join([channel.get("group",""), tvg_name, name]))
        playlist_brand_key = _brand_key(name)
        playlist_ts = _detect_timeshift(" ".join([tvg_name, name]))
        playlist_numbers = _significant_channel_numbers(tvg_id, tvg_name, name)
        brand_text = canonicalize_name(strip_noise_words(name)).lower()
        playlist_brand_family = _reverse_brand_lookup(brand_text)
        pl_calls = extract_callsigns(" ".join([tvg_name, name, channel.get("group",""), tvg_id]))
        pl_tokens = tokenize_channel_name(name)

        # HBO variant extraction (playlist side)
        pl_hbo_variant_raw = _extract_hbo_variant(" ".join([tvg_name, name, channel.get("group",""), tvg_id])) if playlist_brand_family == "hbo" else ""
        pl_hbo_variant = _normalize_hbo_variant(playlist_region, pl_hbo_variant_raw)

        c = self.conn.cursor()
        candidates = self._collect_candidates_by_id_and_name(c, tvg_id, tvg_name, name)

        # Drop exact-id/name candidates from the wrong region; keep only same or unknown region
        if playlist_region:
            adjusted: Dict[str, dict] = {}
            for k, v in candidates.items():
                grp = v.get("group_tag") or ""
                if grp in ("", playlist_region):
                    adjusted[k] = v
                    continue

                # Keep strong exact matches even if the region metadata disagrees.
                if v.get("why") in {"exact-id", "exact-tvg-name"}:
                    lowered_score = max(1, v.get("score", 0) - 30)
                    v = dict(v)
                    v["score"] = lowered_score
                    extra = "-region-mismatch"
                    if extra not in v.get("why", ""):
                        v["why"] = f"{v['why']} {extra}".strip()
                    adjusted[k] = v
                    continue
            candidates = adjusted
        # FAST candidate set (no full channels scan)
        rows_all = self._candidate_rows(c, name, tvg_name, playlist_region)
        pl_markets, pl_provinces, _ = _market_tokens_for(playlist_region or "", playlist_brand_family, " ".join([tvg_name, name]))

        playlist_text_lower = " ".join(filter(None, [tvg_name, name, channel.get("group", "")])).lower()

        for ch_id, disp, grp in rows_all:
            epg_text_norm = canonicalize_name(strip_noise_words(disp)).lower()
            epg_brand_family = _reverse_brand_lookup(epg_text_norm)
            epg_calls = extract_callsigns(" ".join([disp, ch_id]))
            epg_tokens = tokenize_channel_name(disp)
            token_overlap = len(pl_tokens & epg_tokens)

            families_align = (playlist_brand_family and epg_brand_family and playlist_brand_family == epg_brand_family)
            cs_delta, cs_reason = callsign_overlap_score(pl_calls, epg_calls)

            if not (families_align or cs_delta >= 60 or token_overlap >= 1):
                strong_us_local = False
                if playlist_region == "us":
                    epg_markets_tmp, epg_provs_tmp, _ = _market_tokens_for("us", epg_brand_family, disp)
                    if (pl_markets & epg_markets_tmp) or (pl_provinces & epg_provs_tmp):
                        strong_us_local = True
                if not strong_us_local:
                    continue

            score = 0
            why = []

            if cs_delta:
                score += cs_delta
                why.append(cs_reason)

            if families_align:
                score += 40
                why.append('+brand-family')
                epg_brand_key = _brand_key(disp)
                if playlist_brand_key and epg_brand_key and playlist_brand_key == epg_brand_key:
                    score += 10
                    why.append('+brand-key')

            if playlist_region:
                if grp == playlist_region:
                    score += 18
                    why.append('+same-region')
                elif grp == '':
                    score += 6
                    why.append('+unknown-region')
                else:
                    score -= 40
                    why.append('-other-region')
                if families_align and grp and playlist_region and grp != playlist_region:
                    if playlist_brand_family == "hbo":
                        score -= 20
                        why.append('-hbo-wrong-region')
                    elif playlist_brand_family == "hgtv":
                        score -= 25
                        why.append('-hgtv-wrong-region')

            epg_zone = _detect_zone(disp)
            if playlist_zone and epg_zone:
                if playlist_zone == epg_zone:
                    score += 8
                    why.append('+zone')
                else:
                    score -= 15
                    why.append('-zone')
            elif playlist_region == 'us' and not playlist_zone and epg_zone == 'east':
                # For US channels with no zone specified, prefer "East" over generic/west
                # sufficiently to overcome exact-name match scores (~96 vs ~60).
                score += 38
                why.append('+implicit-east')

            epg_ts = _detect_timeshift(" ".join([disp, ch_id]))
            # Timeshift-aware scoring: strongly prefer exact +N matches; penalize mismatches
            if playlist_ts or epg_ts:
                if playlist_ts and epg_ts:
                    ts_delta = abs(playlist_ts - epg_ts)
                    if ts_delta == 0:
                        score += 22
                        why.append('+timeshift-match')
                    elif ts_delta == 1:
                        score += 9
                        why.append('+timeshift-close(1)')
                    elif ts_delta == 2:
                        score += 5
                        why.append('+timeshift-close(2)')
                    else:
                        score -= 10 * ts_delta
                        why.append('-timeshift-far')
                elif playlist_ts and not epg_ts:
                    # Playlist expects +N but EPG candidate looks like base; discourage
                    score -= 15
                    why.append('-timeshift-missing-epg')
                elif epg_ts and not playlist_ts:
                    # Playlist base matched to a +N channel; mild penalty
                    score -= 8
                    why.append('-timeshift-extra-epg')

            if playlist_numbers:
                epg_numbers = _significant_channel_numbers(ch_id, disp)
                if epg_numbers & playlist_numbers:
                    score += 16
                    why.append('+number')
                elif epg_numbers:
                    score -= 30
                    why.append('-number-mismatch')
                else:
                    score -= 6
                    why.append('-number-missing')

            # ---- HBO variant-aware boosting ----
            if playlist_brand_family == "hbo" and epg_brand_family == "hbo":
                epg_hbo_variant_raw = _extract_hbo_variant(" ".join([disp, ch_id]))
                epg_hbo_variant = _normalize_hbo_variant(grp, epg_hbo_variant_raw)

                if pl_hbo_variant or epg_hbo_variant:
                    if _normalize_hbo_variant(playlist_region, pl_hbo_variant or "base") == _normalize_hbo_variant(grp, epg_hbo_variant or "base"):
                        score += 40
                        why.append(f'+hbo-variant({pl_hbo_variant or "base"})')
                    else:
                        if playlist_region == "us":
                            if (pl_hbo_variant in {"", "base", "1"} and epg_hbo_variant in {"base", "1"}) or (epg_hbo_variant in {"", "base"} and pl_hbo_variant in {"base", "1"}):
                                score += 18
                                why.append('+hbo-us-base/1')
                            else:
                                score -= 10
                                why.append('-hbo-variant-mismatch')
                        else:
                            score -= 12
                            why.append('-hbo-variant-mismatch-ca')

            epg_lower = disp.lower()
            if 'sky mix' in playlist_text_lower and 'sky sports mix' in epg_lower:
                score -= 60
                why.append('-sky-mix-vs-sports-mismatch')
            elif 'sky sports mix' in playlist_text_lower and 'sky mix' in epg_lower and 'sky sports mix' not in epg_lower:
                score -= 60
                why.append('-sky-sports-vs-mix-mismatch')
            if 'sky mix' in playlist_text_lower:
                if 'sky mix' in epg_lower:
                    score += 35
                    why.append('+sky-mix-match')
                else:
                    score -= 35
                    why.append('-sky-mix-mismatch')

            # token_overlap already computed above; reuse for scoring
            score += min(20, token_overlap * 4)
            if token_overlap:
                why.append(f'+tokens({token_overlap})')

            if score > 0:
                existing = candidates.get(ch_id)
                if existing and existing.get('score', 0) >= score:
                    # Preserve stronger matches such as exact-id hits.
                    continue
                merged_why = " ".join(why)
                if existing and existing.get('why') and existing['why'] not in merged_why:
                    merged_why = f"{existing['why']} {merged_why}".strip()
                candidates[ch_id] = {
                    'id': ch_id,
                    'group_tag': grp,
                    'score': score,
                    'display_name': disp,
                    'why': merged_why,
                    'ts_offset': epg_ts if families_align else 0,
                    'token_overlap': token_overlap
                }

        out = list(candidates.values())
        if MATCH_DEBUG and DEBUG:
            _logger.debug("MATCH TRACE for '%s' (tvg-id=%s tvg-name=%s): kept=%d", _safe(name, 120), tvg_id, _safe(tvg_name, 120), len(out))
        return out, playlist_region

    def _utcnow(self):
        try:
            return datetime.datetime.now(datetime.UTC)
        except AttributeError:
            return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    def resolve_best_channel_id(self, channel: Dict[str, str]) -> Optional[str]:
        """Find the best matching DB channel ID for a playlist channel."""
        matches, playlist_region = self.get_matching_channel_ids(channel)
        if not matches:
            return None

        # Sort by score initially
        matches = sorted(matches, key=lambda m: -m.get('score', 0))

        # Probe schedule availability for top-N and reorder
        try:
            avail = []
            for m in matches[:20]:
                ch_id = m['id']
                has_any = self._has_any_schedule_from_now(ch_id)
                avail.append((m, has_any))

            # Prefer matches with data (t[1] is bool)
            # Then by total score (which includes region bonuses).
            # We no longer strictly bucket by region first, as that can hide valid channels 
            # if a "better region" candidate exists but has no data.
            ordered = sorted(
                avail,
                key=lambda t: (
                    not t[1],  # False (Has Data) < True (No Data) -> Data first
                    -(int(t[0].get('score', 0)))
                )
            )
            best = ordered[0][0]
            return best['id']
        except Exception:
            # Fallback to score-based top
            return matches[0]['id'] if matches else None

    def get_now_next_by_id(self, channel_id: str) -> Optional[tuple]:
        """Retrieve (now, next) tuple for a specific, already-resolved DB channel ID."""
        if not channel_id:
            return None
        
        c = self.conn.cursor()
        now = self._utcnow()
        now_str = now.strftime("%Y%m%d%H%M%S")
        now_int = int(now_str)

        rows = c.execute(
            "SELECT title, start, end FROM programmes WHERE channel_id = ? AND end > ? ORDER BY start ASC LIMIT 6",
            (channel_id, now_str)
        ).fetchall()

        current_shows = []
        next_shows = []
        
        for title, start, end in rows:
            st_i = int(start)
            en_i = int(end)
            payload = {
                'channel_id': channel_id,
                'title': title,
                'start': datetime.datetime.strptime(start, "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc),
                'end': datetime.datetime.strptime(end, "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            }
            
            if st_i <= now_int < en_i:
                current_shows.append(payload)
            elif st_i > now_int:
                next_shows.append(payload)

        now_show = current_shows[0] if current_shows else None
        next_show = next_shows[0] if next_shows else None
        
        # If we have nothing, return None to indicate no data
        if not now_show and not next_show:
            return None
            
        return now_show, next_show

    def get_now_next(self, channel: Dict[str, str]) -> Optional[tuple]:
        """Legacy wrapper: resolves best ID then fetches schedule."""
        cid = self.resolve_best_channel_id(channel)
        if not cid:
            if DEBUG:
                _logger.debug("NOW/NEXT: no candidates for '%s'", _safe(channel.get('name')))
            return None
        return self.get_now_next_by_id(cid)
    
    def get_channels_with_show(
        self,
        query: str,
        *,
        limit: int = 100,
        include_title_search: bool = True,
        title_hours: int = 48,
    ) -> List[Dict[str, str]]:
        limit = max(1, int(limit or 100))
        raw_query = (query or "").strip()
        normalized_query = canonicalize_name(strip_noise_words(raw_query))
        if not normalized_query:
            return []
        q = "%" + normalized_query + "%"
        title_q = "%" + raw_query.lower() + "%"
        c = self.conn.cursor()
        now = self._utcnow().strftime("%Y%m%d%H%M%S")
        rows = []

        channel_rows = c.execute(
            """
            SELECT id
            FROM channels
            WHERE norm_name LIKE ?
            LIMIT ?
            """,
            (q, limit),
        ).fetchall()
        channel_ids = [row[0] for row in channel_rows if row and row[0]]
        if channel_ids:
            placeholders = ",".join("?" for _ in channel_ids)
            rows.extend(
                c.execute(
                    f"""
                    SELECT p.channel_id, p.title, p.start, p.end, c.display_name
                    FROM programmes p
                    JOIN channels c ON c.id = p.channel_id
                    WHERE p.channel_id IN ({placeholders})
                      AND p.end >= ?
                    ORDER BY p.start ASC
                    LIMIT ?
                    """,
                    (*channel_ids, now, limit),
                ).fetchall()
            )

        if include_title_search and len(rows) < limit:
            try:
                horizon = (
                    self._utcnow() + datetime.timedelta(hours=max(1, int(title_hours or 48)))
                ).strftime("%Y%m%d%H%M%S")
            except Exception:
                horizon = now
            rows.extend(
                c.execute(
                    """
                    SELECT p.channel_id, p.title, p.start, p.end, c.display_name
                    FROM programmes p
                    JOIN channels c ON c.id = p.channel_id
                    WHERE LOWER(p.title) LIKE ?
                      AND p.end >= ?
                      AND p.start <= ?
                    ORDER BY p.start ASC
                    LIMIT ?
                    """,
                    (title_q, now, horizon, max(1, limit - len(rows))),
                ).fetchall()
            )

        result = []
        seen = set()
        for channel_id, show_title, start, end, channel_name in rows:
            key = (channel_id, show_title, start, end)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "channel_id": channel_id,
                "show_title": show_title,
                "start": start,
                "end": end,
                "channel_name": channel_name
            })
            if len(result) >= limit:
                break
        now_int = int(now)
        on_now = [r for r in result if int(r["start"]) <= now_int < int(r["end"])]
        future = [r for r in result if int(r["start"]) > now_int]
        final = []
        added = set()
        for r in on_now + future:
            key = (r["channel_id"], r["show_title"])
            if key not in added:
                added.add(key)
                final.append(r)
                if len(final) >= limit:
                    break
        return final

    def get_all_now_playing(self) -> List[Dict[str, str]]:
        """Get all currently airing programs across all channels.
        
        Returns a list of dicts with: title, channel_name, channel_id, start, end
        Sorted alphabetically by title.
        """
        c = self.conn.cursor()
        now = self._utcnow()
        now_str = now.strftime("%Y%m%d%H%M%S")
        # A programme airing *now* cannot have started more than ~a day ago; this floor lets
        # SQLite range-scan idx_programmes_start_cover instead of scanning all past programmes.
        floor_str = (now - datetime.timedelta(hours=24)).strftime("%Y%m%d%H%M%S")

        # Get all programs where start <= now < end
        rows = c.execute("""
            SELECT p.title, p.start, p.end, c.display_name, c.id
            FROM programmes p
            JOIN channels c ON c.id = p.channel_id
            WHERE p.start >= ? AND p.start <= ? AND p.end > ?
            ORDER BY p.title COLLATE NOCASE ASC
        """, (floor_str, now_str, now_str)).fetchall()
        
        result = []
        seen = set()  # Avoid duplicates (same title on same channel)
        for title, start, end, channel_name, channel_id in rows:
            key = (title.lower(), channel_name.lower() if channel_name else "")
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "title": title,
                "channel_name": channel_name or "Unknown",
                "channel_id": channel_id,
                "start": start,
                "end": end
            })
        return result

    def get_recent_programmes(self, channel: Dict[str, str], hours: int = 48, limit: int = 60) -> List[Dict[str, str]]:
        matches, _ = self.get_matching_channel_ids(channel)
        if not matches:
            return []
        now = self._utcnow()
        now_str = now.strftime("%Y%m%d%H%M%S")
        cutoff = (now - datetime.timedelta(hours=hours)).strftime("%Y%m%d%H%M%S")
        c = self.conn.cursor()
        results: List[Dict[str, str]] = []
        seen: Set[Tuple[str, str, str]] = set()
        per_match = max(1, limit // max(1, len(matches)))
        ordered = sorted(matches, key=lambda m: -m.get('score', 0))[:5]
        for m in ordered:
            ch_id = m.get('id')
            if not ch_id:
                continue
            rows = c.execute(
                """
                SELECT title, start, end
                FROM programmes
                WHERE channel_id = ? AND end <= ? AND end >= ?
                ORDER BY start DESC
                LIMIT ?
                """,
                (ch_id, now_str, cutoff, per_match)
            ).fetchall()
            for title, start, end in rows:
                key = (ch_id, start, end)
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "channel_id": ch_id,
                    "channel_name": m.get('display_name') or channel.get("name", ""),
                    "title": title,
                    "start": start,
                    "end": end
                })
        results.sort(key=lambda r: r["start"], reverse=True)
        return results[:limit]

    def get_schedule(self, channel: Dict[str, str], start_dt: datetime.datetime, end_dt: datetime.datetime) -> List[Dict[str, str]]:
        # Use the smart resolution logic (prefer data availability)
        ch_id = self.resolve_best_channel_id(channel)
        if not ch_id:
            return []
            
        start_str = start_dt.strftime("%Y%m%d%H%M%S")
        end_str = end_dt.strftime("%Y%m%d%H%M%S")
        
        c = self.conn.cursor()
        rows = c.execute("""
            SELECT title, start, end 
            FROM programmes 
            WHERE channel_id = ? AND end >= ? AND start <= ?
            ORDER BY start ASC
        """, (ch_id, start_str, end_str)).fetchall()
        
        results = []
        for title, s, e in rows:
            results.append({
                "title": title,
                "start": s,
                "end": e
            })
        return results

    # =========================
    # Streaming importer with detailed debug
    # =========================
    def import_epg_xml(self, xml_sources: List[str], progress_callback=None):
        # Block until we can import; avoid user-facing warnings.
        _wait_for_import_lock(self.db_path)
        trace_mem = DEBUG or os.getenv("EPG_TRACE_MEM", "0").strip().lower() in {"1", "true", "yes"}
        if trace_mem and tracemalloc.is_tracing():
            tracemalloc.stop()
        if trace_mem:
            tracemalloc.start()

        for p in PRAGMA_IMPORT:
            try: self.conn.execute(p)
            except Exception:
                _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)

        total = len(xml_sources)
        BATCH = 15000
        grand_prog, grand_chan = 0, 0

        def _open_stream(src):
            _logger.debug("Opening stream: %s", _sanitize_url(src))
            if src.startswith(("http://", "https://")):
                last_err = None
                for attempt in range(3):
                    try:
                        req = urllib.request.Request(src, headers={
                            "User-Agent": "Mozilla/5.0",
                            "Accept": "application/xml, text/xml, application/gzip, */*"
                        })
                        resp = urllib.request.urlopen(req, timeout=300)
                        status = getattr(resp, "status", None)
                        ctype = resp.info().get('Content-Type', '').lower()
                        _logger.debug("HTTP GET %s | status=%s ctype=%s mem=%sMB", _sanitize_url(src), status, ctype, _mem_mb())
                        # Some providers return HTML error pages when busy; sniff early and retry.
                        # Peek a small chunk without consuming the stream irreversibly.
                        try:
                            head = resp.peek(256) if hasattr(resp, 'peek') else b''
                        except Exception:
                            head = b''
                        head_txt = head.decode('utf-8', 'ignore') if head else ''
                        if 'another request' in head_txt.lower() or 'too many requests' in head_txt.lower():
                            last_err = RuntimeError("Provider is busy or blocking concurrent downloads; will retry…")
                            time.sleep(2 + attempt)
                            continue
                        is_gz = resp.info().get('Content-Encoding') == 'gzip' or src.lower().endswith('.gz') or 'application/gzip' in ctype

                        # For .gz sources, prefer robust path: download to temp with resume then parse.
                        use_robust_gz = src.lower().endswith('.gz') and os.getenv('EPG_GZ_DOWNLOAD', '1').strip() not in {'0', 'false', 'False'}
                        if is_gz and use_robust_gz:
                            try:
                                resp.close()
                            except Exception:
                                _logger.debug("EPGDatabase.import_epg_xml._open_stream: ignored exception", exc_info=True)
                            return _http_download_gz_with_resume(src)
                        if is_gz:
                            gz = gzip.GzipFile(fileobj=resp)
                            # gzip.GzipFile(fileobj=...) does NOT close the underlying HTTP
                            # response when the GzipFile is closed, leaking the connection on
                            # every error/retry. Chain the closes together.
                            _gz_close = gz.close
                            def _close_both(_gz_close=_gz_close, _resp=resp):
                                try:
                                    _gz_close()
                                finally:
                                    try:
                                        _resp.close()
                                    except Exception:
                                        _logger.debug("EPGDatabase.import_epg_xml._open_stream._close_both: ignored exception", exc_info=True)
                            gz.close = _close_both
                            return gz
                        return resp
                    except Exception as e:
                        last_err = e
                        # brief backoff on transient HTTP/server connect issues
                        time.sleep(1 + attempt)
                # Exhausted retries
                raise last_err or RuntimeError("Failed to open EPG URL")
            else: # Local file
                is_gz = src.lower().endswith('.gz')
                return gzip.open(src, 'rb') if is_gz else open(src, 'rb')

        def _is_transient_stream_error(err: Exception) -> bool:
            msg = str(err).lower()
            # gzip truncation/HTTP partials and a few common transient parse/IO issues
            hints = (
                'end-of-stream marker',
                'compressed file ended',
                'unexpected end of data',
                'crc check failed',
                'incomplete read',
                'connection reset',
                'timed out',
                'no element found',
                'unclosed token',
            )
            try:
                if isinstance(err, IncompleteRead):
                    return True
            except Exception:
                _logger.debug("EPGDatabase.import_epg_xml._is_transient_stream_error: ignored exception", exc_info=True)
            return any(h in msg for h in hints)

        for idx, src in enumerate(xml_sources):
            t0 = time.time()
            attempts_left = 3
            while attempts_left > 0:
                chan_count, prog_count, inserted_since_commit, sample_ok = 0, 0, 0, 0
                stream = None
                began_txn = False
                try:
                    stream = _open_stream(src)
                    parser = ET.XMLPullParser(['start', 'end'])
                    elem_stack: List[ET.Element] = []
                    _logger.debug("EPG START src=%s (mem=%sMB)", _sanitize_url(src), _mem_mb())
                    # Begin write transaction with retry/backoff to avoid transient lock errors
                    try:
                        self.conn.execute("PRAGMA busy_timeout=15000;")
                    except Exception:
                        _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                    for attempt in range(10):
                        try:
                            self.conn.execute("BEGIN IMMEDIATE")
                            began_txn = True
                            break
                        except sqlite3.OperationalError as e:
                            if "locked" in str(e).lower() or "busy" in str(e).lower():
                                time.sleep(0.75 * (attempt + 1))
                                continue
                            raise
                    if not began_txn:
                        _logger.warning(
                            "EPG database was locked when starting import for %s; reopening connection and retrying",
                            _sanitize_url(src)
                        )
                        try:
                            self.reopen()
                        except Exception as reopen_err:
                            _logger.debug("EPG reopen attempt failed: %s", reopen_err)
                        try:
                            self.conn.execute("PRAGMA busy_timeout=20000;")
                        except Exception:
                            _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                        for retry in range(5):
                            try:
                                self.conn.execute("BEGIN IMMEDIATE")
                                began_txn = True
                                break
                            except sqlite3.OperationalError as e:
                                if "locked" in str(e).lower() or "busy" in str(e).lower():
                                    time.sleep(1.0 * (retry + 1))
                                    continue
                                raise
                        if not began_txn:
                            raise sqlite3.OperationalError("database is locked (could not start write transaction)")

                    # Stream and parse
                    while True:
                        chunk = stream.read(262144) # 256KB chunk reduces parser churn
                        if not chunk:
                            break
                        parser.feed(chunk)
                        for event, elem in parser.read_events():
                            if event == 'start':
                                elem_stack.append(elem)
                                continue
                            # event == 'end'
                            try:
                                elem_stack.pop()
                            except IndexError:
                                elem_stack = []
                            parent = elem_stack[-1] if elem_stack else None
                            tag = elem.tag.rsplit('}', 1)[-1]
                            if tag == 'channel':
                                ch_id = elem.get("id", "")
                                dn_elem = elem.find("./display-name")
                                disp = dn_elem.text.strip() if dn_elem is not None and dn_elem.text else ""
                                if ch_id or disp:
                                    self.insert_channel(ch_id, disp)
                                    chan_count += 1
                            elif tag == 'programme':
                                ch_id = elem.get("channel", "")
                                title_elem = elem.find("./title")
                                title_txt = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                                st_raw = elem.get("start", "")
                                en_raw = elem.get("stop") or elem.get("end", "")

                                st_utc = _parse_xmltv_to_utc_str(st_raw)
                                en_utc = _parse_xmltv_to_utc_str(en_raw) if en_raw else None
                                if not en_utc and st_utc:
                                    en_utc = _calc_end_from_length_or_duration(st_utc, elem)

                                if st_utc and en_utc and ch_id:
                                    if DEBUG and sample_ok < 8:
                                        _logger.debug("EPG SAMPLE OK src=%s ...", _sanitize_url(src)); sample_ok += 1
                                    self.insert_programme(ch_id, title_txt, st_utc, en_utc)
                                    prog_count += 1
                                    inserted_since_commit += 1
                                    if inserted_since_commit >= BATCH:
                                        self.commit()
                                        _logger.debug("EPG COMMIT src=%s progs+%d total=%d mem=%sMB", _sanitize_url(src), BATCH, prog_count, _mem_mb())
                                        inserted_since_commit = 0
                            # Clear processed nodes and detach them from their parent so
                            # completed <programme>/<channel> elements don't accumulate.
                            if tag in {'channel', 'programme'}:
                                try:
                                    elem.clear()
                                    if parent is not None:
                                        parent.remove(elem)
                                except Exception:
                                    _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)

                    parser.close() # Finalize
                    self.commit()
                    try:
                        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    except Exception:
                        _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                    _logger.debug("EPG DONE src=%s channels=%d progs=%d elapsed=%.1fs mem=%sMB",
                                  _sanitize_url(src), chan_count, prog_count, time.time() - t0, _mem_mb())

                    # success; exit retry loop for this source
                    break

                except Exception as e:
                    # If the error looks like a transient/truncated gzip/HTTP read, retry a few times
                    msg_lower = str(e).lower()
                    lockish = ('locked' in msg_lower or 'busy' in msg_lower) and attempts_left > 1
                    if lockish:
                        _logger.warning(
                            "EPG database lock for %s — retrying after backoff (%d left)",
                            _sanitize_url(src), attempts_left - 1
                        )
                        try:
                            if began_txn:
                                self.conn.rollback()
                        except Exception:
                            _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                        try:
                            if stream:
                                stream.close()
                        except Exception:
                            _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                        stream = None
                        # Reopen connection to clear any lingering writer locks
                        try:
                            self.reopen()
                            try:
                                self.conn.execute("PRAGMA busy_timeout=30000;")
                            except Exception:
                                _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                        except Exception:
                            _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                        time.sleep(1.5 * (4 - attempts_left))
                        attempts_left -= 1
                        continue

                    if _is_transient_stream_error(e) and attempts_left > 1:
                        _logger.warning(
                            "EPG transient error for %s: %s — retrying (%d left)",
                            _sanitize_url(src), e, attempts_left - 1
                        )
                        try:
                            # rollback any partial transaction for a clean retry
                            if began_txn:
                                self.conn.rollback()
                        except Exception:
                            _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                        try:
                            if stream:
                                stream.close()
                        except Exception:
                            _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                        time.sleep(1.0)
                        attempts_left -= 1
                        continue
                    # Non-transient or out of retries: log and move on
                    _logger.exception("EPG ERROR src=%s : %s", _sanitize_url(src), e)
                    _log_wx_error(f"Failed to import EPG source {_sanitize_url(src)}: {e}")
                    break
                finally:
                    # Ensure no lingering transaction if an error occurred before commit
                    try:
                        if getattr(self.conn, "in_transaction", False):
                            try:
                                self.conn.rollback()
                            except sqlite3.ProgrammingError:
                                _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                            except Exception:
                                _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                    except Exception:
                        _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
                    if stream:
                        try: stream.close()
                        except Exception:
                            _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)

            grand_chan += chan_count
            grand_prog += prog_count
            if progress_callback:
                try: progress_callback(idx + 1, total)
                except Exception:
                    _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)
        
        try:
            self.prune_old_programmes(days=14)
            self.commit()
        except Exception as e:
            _logger.debug("EPG maintenance skipped due to lock or error: %s", e)
        if trace_mem:
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        else:
            _current, peak = (0, 0)
        try:
            c = self.conn.cursor()
            row_c = c.execute("SELECT COUNT(*) FROM channels").fetchone()
            row_p = c.execute("SELECT COUNT(*) FROM programmes").fetchone()
            _logger.info("EPG SUMMARY total_added ch=%d pg=%d | db_final ch=%s pg=%s | mem=%sMB peak_trace=%sKB",
                         grand_chan, grand_prog, row_c[0] if row_c else '?', row_p[0] if row_p else '?', _mem_mb(), int(peak/1024))
        except Exception as e: _logger.debug("EPG SUMMARY failed to query DB counts: %s", e)
        # Release cross-process import lock
        try:
            _release_import_lock(self.db_path)
        except Exception:
            _logger.debug("EPGDatabase.import_epg_xml: ignored exception", exc_info=True)


# =========================
# EPG Import/Manager UI
# =========================

if WX_AVAILABLE:
    class EPGImportDialog(wx.Dialog):  # type: ignore[misc]
        def __init__(self, parent, total_sources):
            super().__init__(parent, title=_("Importing EPG"), size=(400, 150))
            self.total_sources = total_sources
            self._build_ui()
            self.CenterOnParent()
            self.Layout()

        def _build_ui(self):
            panel = wx.Panel(self)
            vbox = wx.BoxSizer(wx.VERTICAL)
            self.label = wx.StaticText(panel, label=_("Importing EPG data…"))
            self.gauge = wx.Gauge(panel, range=max(1, self.total_sources))
            vbox.Add(self.label, 0, wx.ALL, 8)
            vbox.Add(self.gauge, 0, wx.EXPAND | wx.ALL, 8)
            panel.SetSizer(vbox)

        def set_progress(self, value, total):
            try:
                self.gauge.SetRange(max(1, total))
                self.gauge.SetValue(min(value, total))
            except Exception:
                _logger.debug("EPGImportDialog.set_progress: ignored exception", exc_info=True)
else:
    class EPGImportDialog:  # type: ignore[misc]
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("EPGImportDialog requires wxPython. Install wxPython to use GUI dialogs.")

        def set_progress(self, *_args, **_kwargs):
            return None

if WX_AVAILABLE:
    class EPGManagerDialog(wx.Dialog):  # type: ignore[misc]
        def __init__(self, parent, epg_sources):
            super().__init__(parent, title=_("EPG Manager"), size=(600, 300))
            self.epg_sources = epg_sources.copy()
            self._build_ui()
            self.CenterOnParent()
            self.Layout()

        def _build_ui(self):
            panel = wx.Panel(self)
            main_sizer = wx.BoxSizer(wx.VERTICAL)
            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            self.add_file_btn = wx.Button(panel, label=_("Add File"))
            self.add_url_btn = wx.Button(panel, label=_("Add URL"))
            self.remove_btn = wx.Button(panel, label=_("Remove Selected"))
            for btn in (self.add_file_btn, self.add_url_btn, self.remove_btn):
                btn_sizer.Add(btn, 0, wx.ALL, 2)
            main_sizer.Add(btn_sizer, 0, wx.EXPAND)
            self.lb = wx.ListBox(panel, style=wx.LB_SINGLE)
            for src in self.epg_sources:
                self.lb.Append(src)
            if self.epg_sources:
                self.lb.SetSelection(0)
            main_sizer.Add(self.lb, 1, wx.EXPAND | wx.ALL, 5)
            ok_sizer = wx.BoxSizer(wx.HORIZONTAL)
            ok_btn = wx.Button(panel, id=wx.ID_OK)
            cancel_btn = wx.Button(panel, id=wx.ID_CANCEL)
            ok_sizer.Add(ok_btn, 0, wx.ALL, 5)
            ok_sizer.Add(cancel_btn, 0, wx.ALL, 5)
            main_sizer.Add(ok_sizer, 0, wx.ALIGN_RIGHT)
            panel.SetSizer(main_sizer)
            self.add_file_btn.Bind(wx.EVT_BUTTON, self.OnAddFile)
            self.add_url_btn.Bind(wx.EVT_BUTTON, self.OnAddURL)
            self.remove_btn.Bind(wx.EVT_BUTTON, self.OnRemove)

        def OnAddFile(self, _event):
            wildcard = "|".join([
                _("XML files") + " (*.xml)|*.xml",
                _("GZip XML") + " (*.gz)|*.gz",
                _("All files") + " (*.*)|*.*",
            ])
            with wx.FileDialog(self, _("Choose EPG XML file"), wildcard=wildcard) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    path = dlg.GetPath()
                    self.epg_sources.append(path)
                    self.lb.Append(path)

        def OnAddURL(self, _event):
            with wx.TextEntryDialog(self, _("Enter EPG XML URL")) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    url = dlg.GetValue().strip()
                    if url:
                        self.epg_sources.append(url)
                        self.lb.Append(url)

        def OnRemove(self, _):
            i = self.lb.GetSelection()
            if i != wx.NOT_FOUND:
                self.epg_sources.pop(i)
                self.lb.Delete(i)

        def GetResult(self):
            return self.epg_sources
else:
    class EPGManagerDialog:  # type: ignore[misc]
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("EPGManagerDialog requires wxPython. Install wxPython to use GUI dialogs.")

        def GetResult(self):
            return []

if WX_AVAILABLE:
    class PlaylistManagerDialog(wx.Dialog):  # type: ignore[misc]
        def __init__(self, parent, playlist_sources):
            super().__init__(parent, title=_("Playlist Manager"), size=(600, 300))
            self.playlist_sources = playlist_sources.copy()
            self._build_ui()
            self.CenterOnParent()
            self.Layout()

        def _build_ui(self):
            panel = wx.Panel(self)
            main_sizer = wx.BoxSizer(wx.VERTICAL)
            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            self.add_file_btn = wx.Button(panel, label=_("Add File"))
            self.add_url_btn = wx.Button(panel, label=_("Add URL"))
            self.add_xtream_btn = wx.Button(panel, label=_("Add Xtream Codes"))
            self.add_stalker_btn = wx.Button(panel, label=_("Add Stalker Portal"))
            self.remove_btn = wx.Button(panel, label=_("Remove Selected"))
            for btn in (self.add_file_btn, self.add_url_btn, self.add_xtream_btn, self.add_stalker_btn, self.remove_btn):
                btn_sizer.Add(btn, 0, wx.ALL, 2)
            main_sizer.Add(btn_sizer, 0, wx.EXPAND)
            self.lb = wx.ListBox(panel, style=wx.LB_SINGLE)
            for src in self.playlist_sources:
                self.lb.Append(self._format_source_label(src))
            if self.playlist_sources:
                self.lb.SetSelection(0)
            main_sizer.Add(self.lb, 1, wx.EXPAND | wx.ALL, 5)
            ok_sizer = wx.BoxSizer(wx.HORIZONTAL)
            ok_btn = wx.Button(panel, id=wx.ID_OK)
            cancel_btn = wx.Button(panel, id=wx.ID_CANCEL)
            ok_sizer.Add(ok_btn, 0, wx.ALL, 5)
            ok_sizer.Add(cancel_btn, 0, wx.ALL, 5)
            main_sizer.Add(ok_sizer, 0, wx.ALIGN_RIGHT)
            panel.SetSizer(main_sizer)
            self.add_file_btn.Bind(wx.EVT_BUTTON, self.OnAddFile)
            self.add_url_btn.Bind(wx.EVT_BUTTON, self.OnAddURL)
            self.add_xtream_btn.Bind(wx.EVT_BUTTON, self.OnAddXtream)
            self.add_stalker_btn.Bind(wx.EVT_BUTTON, self.OnAddStalker)
            self.remove_btn.Bind(wx.EVT_BUTTON, self.OnRemove)

        def OnAddFile(self, _event):
            wildcard = "|".join([
                _("M3U files") + " (*.m3u;*.m3u8)|*.m3u;*.m3u8",
                _("All files") + " (*.*)|*.*",
            ])
            with wx.FileDialog(self, _("Choose M3U file"), wildcard=wildcard) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    path = dlg.GetPath()
                    self.playlist_sources.append(path)
                    self.lb.Append(self._format_source_label(path))

        def OnAddURL(self, _event):
            with wx.TextEntryDialog(self, _("Enter M3U URL")) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    url = dlg.GetValue().strip()
                    if url:
                        self.playlist_sources.append(url)
                        self.lb.Append(self._format_source_label(url))

        def OnAddXtream(self, _):
            self._add_provider_source(XtreamCodesDialog)

        def OnAddStalker(self, _):
            self._add_provider_source(StalkerPortalDialog)

        def _add_provider_source(self, dialog_cls):
            try:
                dlg = dialog_cls(self)
            except Exception as exc:
                # A dialog that dies half-built used to leave the manager looking
                # frozen with nothing on screen; report it and stay usable instead.
                _logger.exception("PlaylistManagerDialog._add_provider_source: %s failed to open", dialog_cls.__name__)
                _log_wx_error(f"{dialog_cls.__name__} could not be opened: {exc}")
                return
            try:
                if _show_modal_raised(dlg, getattr(dlg, "first_field", None)) == wx.ID_OK:
                    data = dlg.get_data()
                    if data:
                        data.setdefault("id", generate_provider_id())
                        self.playlist_sources.append(data)
                        self.lb.Append(self._format_source_label(data))
            finally:
                dlg.Destroy()

        def OnRemove(self, _):
            i = self.lb.GetSelection()
            if i != wx.NOT_FOUND:
                self.playlist_sources.pop(i)
                self.lb.Delete(i)

        def _format_source_label(self, src):
            if isinstance(src, dict):
                stype = (src.get("type") or "").lower()
                name = src.get("name") or src.get("username") or src.get("base_url") or _("Provider")
                if stype == "xtream":
                    return _("Xtream Codes – {name}").format(name=name)
                if stype == "stalker":
                    return _("Stalker Portal – {name}").format(name=name)
                return _("Provider – {name}").format(name=name)
            return src

        def GetResult(self):
            return self.playlist_sources
else:
    class PlaylistManagerDialog:  # type: ignore[misc]
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("PlaylistManagerDialog requires wxPython. Install wxPython to use GUI dialogs.")

        def GetResult(self):
            return []


if WX_AVAILABLE:
    class XtreamCodesDialog(wx.Dialog):
        STREAM_TYPES = ["m3u_plus", "m3u", "enigma2"]
        OUTPUT_TYPES = ["ts", "m3u8", "rtmp"]

        def __init__(self, parent):
            super().__init__(parent, title=_("Add Xtream Codes Account"))
            self._build_ui()
            self.CenterOnParent()

        def _build_ui(self):
            outer = wx.BoxSizer(wx.VERTICAL)
            panel = wx.Panel(self)
            grid = wx.FlexGridSizer(0, 2, 6, 10)
            grid.AddGrowableCol(1, 1)

            def add_row(label, ctrl, hint=None):
                text = wx.StaticText(panel, label=f"{label}:")
                text.SetName(_("{label} label").format(label=label))
                if hasattr(text, "SetAccessibleName"):
                    text.SetAccessibleName(_("{label} label").format(label=label))
                ctrl.SetName(label)
                if hasattr(ctrl, "SetAccessibleName"):
                    ctrl.SetAccessibleName(label)
                desc = hint or _("{label} field").format(label=label)
                if hasattr(ctrl, "SetAccessibleDescription"):
                    ctrl.SetAccessibleDescription(desc)
                if hint:
                    ctrl.SetToolTip(hint)
                if hasattr(ctrl, "SetHelpText") and not isinstance(ctrl, wx.ComboBox):
                    ctrl.SetHelpText(desc)
                # Only editable text controls support SetHint without assertions on Windows.
                if isinstance(ctrl, wx.TextCtrl) and hint and hasattr(ctrl, "SetHint"):
                    try:
                        ctrl.SetHint(hint)
                    except Exception:
                        _logger.debug("XtreamCodesDialog._build_ui.add_row: ignored exception", exc_info=True)
                _attach_field_accessible(ctrl, label, desc)
                grid.Add(text, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
                grid.Add(ctrl, 1, wx.EXPAND)

            self.name_ctrl = wx.TextCtrl(panel)
            self.url_ctrl = wx.TextCtrl(panel)
            self.user_ctrl = wx.TextCtrl(panel)
            self.pass_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
            self.stream_ctrl = wx.ComboBox(panel, choices=self.STREAM_TYPES, value="m3u_plus", style=wx.CB_READONLY)
            self.output_ctrl = wx.ComboBox(panel, choices=self.OUTPUT_TYPES, value="ts", style=wx.CB_READONLY)
            self.auto_epg_ctrl = wx.CheckBox(panel, label=_("Automatically add XMLTV URL"))
            self.auto_epg_ctrl.SetName(_("Automatically add XMLTV URL"))
            if hasattr(self.auto_epg_ctrl, "SetAccessibleName"):
                self.auto_epg_ctrl.SetAccessibleName(_("Automatically add XMLTV URL"))
            self.auto_epg_ctrl.SetToolTip(_("Include the provider's XMLTV guide automatically"))
            self.auto_epg_ctrl.SetValue(True)

            add_row(_("Display name"), self.name_ctrl, _("Optional nickname for this Xtream Codes account"))
            add_row(_("Portal base URL"), self.url_ctrl, _("Base URL of the Xtream Codes server"))
            add_row(_("Username"), self.user_ctrl, _("Xtream Codes username"))
            add_row(_("Password"), self.pass_ctrl, _("Xtream Codes password"))
            add_row(_("Playlist type"), self.stream_ctrl, _("Select the playlist format to download"))
            add_row(_("Stream output"), self.output_ctrl, _("Preferred stream container format"))
            grid.Add(wx.StaticText(panel, label=""))
            grid.Add(self.auto_epg_ctrl)

            panel.SetSizer(grid)
            outer.Add(panel, 1, wx.ALL | wx.EXPAND, 12)

            btn_sizer = wx.StdDialogButtonSizer()
            self.ok_btn = wx.Button(self, wx.ID_OK, _("Add"))
            self.cancel_btn = wx.Button(self, wx.ID_CANCEL)
            btn_sizer.AddButton(self.ok_btn)
            btn_sizer.AddButton(self.cancel_btn)
            btn_sizer.Realize()
            outer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

            self.ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
            self.ok_btn.SetDefault()
            self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

            self.SetSizerAndFit(outer)
            self.SetEscapeId(wx.ID_CANCEL)
            self.Bind(wx.EVT_CLOSE, self._on_close)
            # First field a screen reader should land on when the dialog opens.
            self.first_field = self.name_ctrl
            self.name_ctrl.SetFocus()

        def _on_ok(self, event):
            if not self.user_ctrl.GetValue().strip() or not self.pass_ctrl.GetValue().strip() or not self.url_ctrl.GetValue().strip():
                wx.MessageBox(_("Username, password, and URL are required."), _("Validation"), wx.OK | wx.ICON_WARNING)
                return
            self.EndModal(wx.ID_OK)

        def _on_cancel(self, event):
            if self.IsModal():
                self.EndModal(wx.ID_CANCEL)
            else:
                self.Destroy()

        def _on_close(self, event):
            self._on_cancel(event)

        def get_data(self):
            url = self.url_ctrl.GetValue().strip()
            username = self.user_ctrl.GetValue().strip()
            password = self.pass_ctrl.GetValue().strip()
            if not url or not username or not password:
                return None
            return {
                "type": "xtream",
                "name": self.name_ctrl.GetValue().strip(),
                "base_url": url,
                "username": username,
                "password": password,
                "stream_type": self.stream_ctrl.GetValue() or "m3u_plus",
                "output": self.output_ctrl.GetValue() or "ts",
                "auto_epg": self.auto_epg_ctrl.GetValue()
            }


    class StalkerPortalDialog(wx.Dialog):
        def __init__(self, parent):
            super().__init__(parent, title=_("Add Stalker Portal Account"))
            self._build_ui()
            self.CenterOnParent()

        def _build_ui(self):
            outer = wx.BoxSizer(wx.VERTICAL)
            panel = wx.Panel(self)
            grid = wx.FlexGridSizer(0, 2, 6, 10)
            grid.AddGrowableCol(1, 1)

            def add_row(label, ctrl, hint=None):
                text = wx.StaticText(panel, label=f"{label}:")
                text.SetName(_("{label} label").format(label=label))
                if hasattr(text, "SetAccessibleName"):
                    text.SetAccessibleName(_("{label} label").format(label=label))
                ctrl.SetName(label)
                if hasattr(ctrl, "SetAccessibleName"):
                    ctrl.SetAccessibleName(label)
                desc = hint or _("{label} field").format(label=label)
                if hasattr(ctrl, "SetAccessibleDescription"):
                    ctrl.SetAccessibleDescription(desc)
                if hint:
                    ctrl.SetToolTip(hint)
                if hasattr(ctrl, "SetHelpText") and not isinstance(ctrl, wx.ComboBox):
                    ctrl.SetHelpText(desc)
                if isinstance(ctrl, wx.TextCtrl) and hint and hasattr(ctrl, "SetHint"):
                    try:
                        ctrl.SetHint(hint)
                    except Exception:
                        _logger.debug("StalkerPortalDialog._build_ui.add_row: ignored exception", exc_info=True)
                _attach_field_accessible(ctrl, label, desc)
                grid.Add(text, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
                grid.Add(ctrl, 1, wx.EXPAND)

            self.name_ctrl = wx.TextCtrl(panel)
            self.url_ctrl = wx.TextCtrl(panel)
            self.user_ctrl = wx.TextCtrl(panel)
            self.pass_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
            self.mac_ctrl = wx.TextCtrl(panel)
            self.auto_epg_ctrl = wx.CheckBox(panel, label=_("Attempt to add provider XMLTV"))
            self.auto_epg_ctrl.SetName(_("Attempt to add provider XMLTV"))
            if hasattr(self.auto_epg_ctrl, "SetAccessibleName"):
                self.auto_epg_ctrl.SetAccessibleName(_("Attempt to add provider XMLTV"))
            self.auto_epg_ctrl.SetToolTip(_("Try to add the portal's XMLTV guide automatically"))
            self.auto_epg_ctrl.SetValue(True)

            self.mac_ctrl.SetValue(self._default_mac())

            self.mac_btn = wx.Button(panel, label=_("Randomise MAC"))
            self.mac_btn.Bind(wx.EVT_BUTTON, self._on_random_mac)

            add_row(_("Display name"), self.name_ctrl, _("Optional nickname for this portal account"))
            add_row(_("Portal base URL"), self.url_ctrl, _("Base URL of the Stalker/Ministra portal"))
            add_row(_("Username"), self.user_ctrl, _("Portal account username"))
            add_row(_("Password"), self.pass_ctrl, _("Portal account password"))
            add_row(_("MAC address"), self.mac_ctrl, _("MAC address presented to the portal"))
            grid.Add(wx.StaticText(panel, label=""))
            grid.Add(self.mac_btn)
            grid.Add(wx.StaticText(panel, label=""))
            grid.Add(self.auto_epg_ctrl)

            panel.SetSizer(grid)
            outer.Add(panel, 1, wx.ALL | wx.EXPAND, 12)

            btn_sizer = wx.StdDialogButtonSizer()
            self.ok_btn = wx.Button(self, wx.ID_OK, _("Add"))
            self.cancel_btn = wx.Button(self, wx.ID_CANCEL)
            btn_sizer.AddButton(self.ok_btn)
            btn_sizer.AddButton(self.cancel_btn)
            btn_sizer.Realize()
            outer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

            self.ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
            self.ok_btn.SetDefault()
            self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

            self.SetSizerAndFit(outer)
            self.SetEscapeId(wx.ID_CANCEL)
            self.Bind(wx.EVT_CLOSE, self._on_close)
            # First field a screen reader should land on when the dialog opens.
            self.first_field = self.name_ctrl
            self.name_ctrl.SetFocus()

        def _sanitize_mac(self, value: str) -> str:
            value = value.replace('-', ':').replace('.', '')
            value = value.upper()
            if ':' not in value and len(value) == 12:
                value = ':'.join(value[i:i+2] for i in range(0, 12, 2))
            return value

        def _default_mac(self) -> str:
            prefix = [0x00, 0x1A, 0x79]
            suffix = [random.randint(0x00, 0xFF) for _ in range(3)]
            return ':'.join(f"{b:02X}" for b in prefix + suffix)

        def _on_random_mac(self, _event):
            self.mac_ctrl.SetValue(self._default_mac())

        def _on_ok(self, event):
            if not self.user_ctrl.GetValue().strip() or not self.pass_ctrl.GetValue().strip() or not self.url_ctrl.GetValue().strip():
                wx.MessageBox(_("Portal URL, username, and password are required."), _("Validation"), wx.OK | wx.ICON_WARNING)
                return
            mac = self._sanitize_mac(self.mac_ctrl.GetValue().strip())
            if len(mac.split(':')) != 6:
                wx.MessageBox(_("MAC address must contain six octets (e.g., 00:1A:79:12:34:56)."), _("Validation"), wx.OK | wx.ICON_WARNING)
                return
            self.mac_ctrl.SetValue(mac)
            self.EndModal(wx.ID_OK)

        def _on_cancel(self, event):
            if self.IsModal():
                self.EndModal(wx.ID_CANCEL)
            else:
                self.Destroy()

        def _on_close(self, event):
            self._on_cancel(event)

        def get_data(self):
            url = self.url_ctrl.GetValue().strip()
            username = self.user_ctrl.GetValue().strip()
            password = self.pass_ctrl.GetValue().strip()
            if not url or not username or not password:
                return None
            return {
                "type": "stalker",
                "name": self.name_ctrl.GetValue().strip(),
                "base_url": url,
                "username": username,
                "password": password,
                "mac": self.mac_ctrl.GetValue().strip(),
                "auto_epg": self.auto_epg_ctrl.GetValue()
            }
else:
    class XtreamCodesDialog:  # type: ignore[misc]
        STREAM_TYPES: List[str] = []
        OUTPUT_TYPES: List[str] = []

        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("XtreamCodesDialog requires wxPython. Install wxPython to use GUI dialogs.")

        def get_data(self):
            return None

    class StalkerPortalDialog:  # type: ignore[misc]
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("StalkerPortalDialog requires wxPython. Install wxPython to use GUI dialogs.")

        def get_data(self):
            return None

# =========================
# Helpers for region + playlist
# =========================

def _derive_playlist_region(channel: Dict[str, str]) -> str:
    votes: Dict[str, int] = {}
    order: Dict[str, int] = {}
    order_counter = 0

    def _add_vote(code: str, weight: int):
        nonlocal order_counter
        if not code:
            return
        votes[code] = votes.get(code, 0) + weight
        if code not in order:
            order[code] = order_counter
            order_counter += 1

    def _normalize_for_prefix(text: str) -> str:
        return re.sub(r'[^a-z0-9]', '', (text or '').lower())

    def _strip_quality_prefix(remainder: str) -> str:
        # successively drop common quality/format tags so "ukfhd" -> ""
        rem = remainder
        changed = True
        while rem and changed:
            changed = False
            for tag in STRIP_TAGS:
                clean_tag = _normalize_for_prefix(tag)
                if clean_tag and rem.startswith(clean_tag):
                    rem = rem[len(clean_tag):]
                    changed = True
        return rem

    def _votes_from_prefix(text: str, weight: int):
        compact = _normalize_for_prefix(text)
        if not compact:
            return
        for code, variants in group_synonyms().items():
            for variant in variants:
                prefix = _normalize_for_prefix(variant)
                if prefix and compact.startswith(prefix):
                    remainder = _strip_quality_prefix(compact[len(prefix):])
                    if not remainder:
                        _add_vote(code, weight)
                        return

    def _votes_from_text(text: str, base_weight: int):
        if not text:
            return
        lowered = text.lower()
        m = re.match(r'\s*([a-z]{2,3})\s*[:\-]', lowered)
        if m and m.group(1) in group_synonyms():
            _add_vote(m.group(1), base_weight + 3)
        lead = re.match(r'\s*([a-z]{2,3})\b', lowered)
        if lead and lead.group(1) in group_synonyms():
            _add_vote(lead.group(1), base_weight + 2)
        if 'usa' in lowered:
            _add_vote('us', base_weight + 2)
        _votes_from_prefix(text, base_weight + 2)
        _add_vote(extract_group(text), base_weight)

    g = channel.get("group") or ""
    if g:
        _add_vote(extract_group(g), 4)
        for tok in re.findall(r'\b[a-z]{2,3}\b', g.lower()):
            if tok in group_synonyms():
                _add_vote(tok, 3)
        _votes_from_prefix(g, 5)

    tid = (channel.get("tvg-id") or "").lower()
    id_region = _detect_region_from_id(tid)
    if id_region:
        _add_vote(id_region, 8)
    for tok in re.findall(r'[.\-_:|/@]([a-z]{2,3})', tid):
        if tok in group_synonyms():
            _add_vote(tok, 4)

    _votes_from_text(channel.get("tvg-name", ""), 6)
    _votes_from_text(channel.get("name", ""), 7)

    if not votes:
        return ''

    best_score = max(votes.values())
    tied = [code for code, score in votes.items() if score == best_score]
    if len(tied) == 1:
        return tied[0]
    tied.sort(key=lambda code: order.get(code, 1_000_000))
    return tied[0]

