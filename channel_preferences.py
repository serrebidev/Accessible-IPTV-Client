"""Provider-scoped preferences shared by the guide and the player."""
import threading

from programme_reminders import channel_key

_lock = threading.RLock()
_epg = {}
version = 0


def configure(config):
    global _epg, version
    values = config.get("epg_channel_overrides", {})
    with _lock:
        updated = {key: value for key, value in values.items()
                if isinstance(key, str) and len(key) == 64
                and isinstance(value, str) and 0 < len(value) <= 1024} if isinstance(values, dict) else {}
        if updated != _epg:
            _epg = updated
            version += 1


def epg_id(channel):
    with _lock:
        return _epg.get(channel_key(channel), "") if _epg else ""


def volume(config, key, default):
    values = config.get("channel_volumes", {})
    value = values.get(key) if isinstance(values, dict) else None
    return value if type(value) is int and 0 <= value <= 100 else default


def remember_volume(values, key, value):
    values = dict(values) if isinstance(values, dict) else {}
    values.pop(key, None)
    values[key] = max(0, min(100, int(value)))
    return dict(list(values.items())[-5000:])
