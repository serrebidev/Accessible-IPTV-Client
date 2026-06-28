"""Runtime shim to keep buffering logic canonical.

This module is auto-imported by Python if present. The internal player behavior
now lives solely in ``internal_player.py``; this shim lazily re-exports symbols
for compatibility without importing wx/VLC during interpreter startup.
"""

import importlib
import logging

LOG = logging.getLogger(__name__)

_IP = None
_IMPORT_ATTEMPTED = False
_IMPORT_ERROR = None

__all__ = [
    "InternalPlayerFrame",
    "InternalPlayerUnavailableError",
    "_prepare_vlc_runtime",
    "_VLC_IMPORT_ERROR",
    "vlc",
]


class InternalPlayerUnavailableError(RuntimeError):
    """Fallback error used when the internal player cannot be loaded."""


def _load_internal_player():
    global _IP
    global _IMPORT_ATTEMPTED
    global _IMPORT_ERROR

    if not _IMPORT_ATTEMPTED:
        _IMPORT_ATTEMPTED = True
        try:
            _IP = importlib.import_module("internal_player")
        except Exception as exc:  # pragma: no cover - import guard
            LOG.debug("sitecustomize could not import internal_player: %s", exc)
            _IMPORT_ERROR = exc
            _IP = None
    return _IP


def __getattr__(name):
    if name == "_VLC_IMPORT_ERROR":
        module = _load_internal_player()
        if module is not None:
            return getattr(module, "_VLC_IMPORT_ERROR", None)
        return _IMPORT_ERROR

    if name in __all__:
        module = _load_internal_player()
        if module is None:
            if name == "InternalPlayerUnavailableError":
                return InternalPlayerUnavailableError
            if name in {"InternalPlayerFrame", "_prepare_vlc_runtime", "vlc"}:
                return None
        return getattr(module, name)

    raise AttributeError(name)
