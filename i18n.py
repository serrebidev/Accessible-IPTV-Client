"""Lightweight gettext-based internationalization for Accessible IPTV Client.

Design goals:
- Zero third-party dependencies at runtime (standard-library :mod:`gettext` only).
- A single translation function exposed as the conventional ``_()`` builtin so the
  rest of the codebase can call ``_("Some text")`` without importing anything.
- Automatic language selection from the operating system, with a manual override
  stored in the app config, and English as the always-available fallback.

The translation function is a thin wrapper that consults the *currently active*
catalogue on every call, so switching languages at runtime (or at startup, once
the config is known) takes effect without re-importing modules.

We deliberately do **not** call :func:`wx.Locale` / change the process C locale:
that would flip ``LC_NUMERIC`` and can silently break float parsing (buffer
seconds, Mbps) and the ``2.5``-style numbers we feed to libVLC options. Only the
application's own strings are translated, via gettext.
"""

from __future__ import annotations

import builtins
import gettext as _gettext
import os
import sys

# gettext domain -> locale/<lang>/LC_MESSAGES/iptvclient.mo
DOMAIN = "iptvclient"
LANG_AUTO = "auto"

# (code, native display label) shown in the Options > Language selector.
# Language names are shown as endonyms; only "Automatic" is itself translatable.
_LANGUAGE_LABELS = [
    (LANG_AUTO, "Automatic"),
    ("en", "English"),
    ("es", "Español (Spanish)"),
    ("ar", "العربية (Arabic)"),
    ("pt", "Português – Brasil (Portuguese)"),
    ("fr", "Français (French)"),
    ("de", "Deutsch (German)"),
    ("ru", "Русский (Russian)"),
    ("tr", "Türkçe (Turkish)"),
    ("it", "Italiano (Italian)"),
    ("pl", "Polski (Polish)"),
    ("hi", "हिन्दी (Hindi)"),
    ("zh", "中文（简体） (Chinese, Simplified)"),
    ("ja", "日本語 (Japanese)"),
    ("hu", "Magyar (Hungarian)"),
]

# Languages we actually ship a compiled catalogue for (source language is English).
SHIPPED_CATALOGS = ("es", "ar", "pt", "fr", "de", "ru", "tr", "it", "pl", "hi", "zh", "ja", "hu")

_translation: _gettext.NullTranslations = _gettext.NullTranslations()
_active_code: str = LANG_AUTO


def locale_dir() -> str:
    """Absolute path to the bundled ``locale`` directory (frozen or source tree)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "locale")


def available_languages():
    """Return ``[(code, label), ...]`` for building the language menu."""
    return list(_LANGUAGE_LABELS)


def detect_system_language() -> str:
    """Best-effort two-letter code for the OS UI language. Defaults to ``"en"``."""
    # 1) Environment variables (Linux/macOS, or an explicit override anywhere).
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        raw = os.environ.get(var)
        if raw:
            token = raw.split(":")[0].split(".")[0].split("@")[0].strip()
            if token:
                return token.replace("-", "_").split("_")[0].lower()
    # 2) Windows: the actual user UI language (env vars are usually unset there).
    if sys.platform.startswith("win"):
        try:
            import ctypes
            import locale as _locale

            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            name = _locale.windows_locale.get(lcid)
            if name:
                return name.split("_")[0].lower()
        except Exception:
            pass
    # 3) Generic default locale (deprecated API; guarded + warning-suppressed).
    try:
        import locale as _locale
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            loc = _locale.getdefaultlocale()[0]
        if loc:
            return loc.replace("-", "_").split("_")[0].lower()
    except Exception:
        pass
    return "en"


def _resolve_candidates(lang_code: str):
    """Map a stored preference to a gettext language list, or ``None`` for source English."""
    code = (lang_code or LANG_AUTO).strip().lower()
    if code in ("", LANG_AUTO, "automatic", "system", "default"):
        resolved = detect_system_language()
    else:
        resolved = code
    if not resolved or resolved == "en":
        return None  # Source strings are already English.
    # Always allow English as the final fallback within the catalogue chain.
    return [resolved, "en"]


def set_language(lang_code: str) -> str:
    """Activate ``lang_code`` ("auto"/"en"/"hu"/...). Returns the stored preference code."""
    global _translation, _active_code
    code = (lang_code or LANG_AUTO).strip().lower()
    if code in ("", "automatic", "system", "default"):
        code = LANG_AUTO
    _active_code = code
    candidates = _resolve_candidates(code)
    if not candidates:
        _translation = _gettext.NullTranslations()
    else:
        try:
            _translation = _gettext.translation(
                DOMAIN, locale_dir(), languages=candidates, fallback=True
            )
        except Exception:
            _translation = _gettext.NullTranslations()
    return _active_code


def get_language() -> str:
    """Return the stored language preference code ("auto"/"en"/"hu"/...)."""
    return _active_code


def gettext(message: str) -> str:
    """Translate ``message`` using the active catalogue (falls back to the source text)."""
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Plural-aware translation using the active catalogue."""
    return _translation.ngettext(singular, plural, n)


def init_from_config(config) -> str:
    """Activate the language stored under the config ``"language"`` key (default auto)."""
    try:
        pref = (config or {}).get("language", LANG_AUTO)
    except Exception:
        pref = LANG_AUTO
    return set_language(pref)


def install() -> None:
    """Expose ``_()`` and ``ngettext()`` as builtins (mirrors :func:`gettext.install`)."""
    builtins.__dict__["_"] = gettext
    builtins.__dict__["ngettext"] = ngettext


# Importing this module makes ``_()`` available everywhere immediately (as a no-op
# pass-through until a real catalogue is activated via set_language/init_from_config).
install()
