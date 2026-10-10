"""Media-type detection for stream recording: audio-only (radio) vs video.

GUI-free. Classification results are plain data; the UI layer (main.py)
decides what to announce and which recording presets to offer.

The detection order follows the agreed plan:

1. Authoritative playlist/provider metadata (``radio="true"`` and recognized
   equivalents) -- no network involved.
2. A lightweight asynchronous FFmpeg probe of the actual stream tracks, with
   the result cached per channel for the session.
3. Group/channel names are only ever supporting hints, never the sole source
   of truth, so they do not appear here at all.

An attached picture or static cover-art track never counts as video: only a
real video track makes a stream video-capable.
"""

from __future__ import annotations

import re
import threading
from typing import Dict, List, Mapping, Optional, Tuple

MEDIA_AUDIO = "audio"
MEDIA_VIDEO = "video"
MEDIA_UNKNOWN = "unknown"

SOURCE_METADATA = "metadata"
SOURCE_PROBE = "probe"

# Safe defaults: the pre-existing global default was the MKV provider copy.
DEFAULT_AUDIO_FORMAT = "audio_mp3_v0"
DEFAULT_VIDEO_FORMAT = "provider_mkv"

# M3U EXTINF attribute names that carry an explicit media-type statement.
# ``radio`` is the de-facto standard; the rest are the equivalents providers
# actually emit.
_AUDIO_ATTR_KEYS = (
    "radio",
    "media-type", "mediatype", "media_type",
    "stream-type", "streamtype",
    "tvg-type", "tvgtype",
)
_TRUE_VALUES = frozenset({"true", "1", "yes"})
_FALSE_VALUES = frozenset({"false", "0", "no"})
_AUDIO_TYPE_VALUES = frozenset({"audio", "radio", "music"})
_VIDEO_TYPE_VALUES = frozenset({"video", "tv", "television"})


def media_hint_from_attributes(attrs: Mapping[str, object]) -> str:
    """``"audio"``/``"video"``/``""`` from M3U EXTINF-style attributes.

    ``radio="true"`` (and the 1/yes spellings) is authoritative for radio;
    an explicit ``radio="false"`` marks the entry as not-radio. Recognized
    media-type equivalents are honored the same way. Anything else -- group
    names included -- is not consulted here.
    """
    get = lambda key: str(attrs.get(key, "") or "").strip().lower()  # noqa: E731
    radio = get("radio")
    if radio in _TRUE_VALUES:
        return MEDIA_AUDIO
    if radio in _FALSE_VALUES:
        return MEDIA_VIDEO
    for key in _AUDIO_ATTR_KEYS[1:]:
        value = get(key)
        if value in _AUDIO_TYPE_VALUES:
            return MEDIA_AUDIO
        if value in _VIDEO_TYPE_VALUES:
            return MEDIA_VIDEO
    return ""


def channel_media_from_metadata(channel: Mapping[str, object]) -> Optional[str]:
    """The media type stated by the channel's own metadata, if any.

    Prefers a precomputed ``media_hint`` (written by the M3U parser), then
    falls back to the raw attributes so channels built by other provider
    paths work too. Returns ``"audio"``/``"video"`` or None.
    """
    hint = str(channel.get("media_hint") or "").strip().lower()
    if hint in (MEDIA_AUDIO, MEDIA_VIDEO):
        return hint
    attrs = {key: channel.get(key) for key in _AUDIO_ATTR_KEYS}
    hint = media_hint_from_attributes(attrs)
    return hint or None


# ---------------------------------------------------------------------------
# Probe classification
# ---------------------------------------------------------------------------

# Mirrors recorder's stream line shape: ``Stream #0:1: Video: mjpeg ...``.
_STREAM_LINE_RE = re.compile(
    r"^\s*Stream #\d+:\d+(?:\[[^\]]*])?(?:\(([^)]*)\))?: (\w+): (.*)$")
_FLAG_RE = re.compile(r"\(([a-z][a-z ]*)\)")


def parse_media_streams(report: str) -> List[Dict[str, object]]:
    """Every stream in an ``ffmpeg -i`` report: kind + disposition flags."""
    streams: List[Dict[str, object]] = []
    for line in (report or "").splitlines():
        match = _STREAM_LINE_RE.match(line)
        if not match:
            continue
        kind = match.group(2).strip().lower()
        flags = set(_FLAG_RE.findall(match.group(3).lower()))
        streams.append({"kind": kind, "dispositions": flags})
    return streams


def classify_media_streams(streams: List[Dict[str, object]]) -> str:
    """``"audio"``/``"video"``/``"unknown"`` from probed stream kinds.

    A video track flagged ``attached pic`` (cover art on a radio stream) does
    not make the stream video-capable.
    """
    kinds = [s.get("kind") for s in streams]
    has_video = any(
        s.get("kind") == "video" and "attached pic" not in (s.get("dispositions") or ())
        for s in streams
    )
    has_audio = "audio" in kinds
    if has_video:
        return MEDIA_VIDEO
    if has_audio:
        return MEDIA_AUDIO
    return MEDIA_UNKNOWN


def classify_probe_report(report: str) -> str:
    """Classify an ``ffmpeg -i`` stderr report into audio/video/unknown."""
    return classify_media_streams(parse_media_streams(report))


# ---------------------------------------------------------------------------
# Session cache
# ---------------------------------------------------------------------------

class MediaTypeCache:
    """In-memory media-type results, keyed by stable channel identity.

    The entry is only valid while the playlist entry's URL is unchanged: a
    changed URL invalidates it, which also covers playlist refreshes that
    rewrite entries.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[str, Tuple[str, str, str]] = {}

    def lookup(self, identity: str, url: str) -> Optional[Tuple[str, str]]:
        """``(media, source)`` or None on a miss or a changed URL."""
        if not identity:
            return None
        with self._lock:
            entry = self._entries.get(identity)
        if entry is None or entry[0] != (url or ""):
            return None
        return entry[1], entry[2]

    def store(self, identity: str, url: str, media: str, source: str) -> None:
        if not identity or media not in (MEDIA_AUDIO, MEDIA_VIDEO):
            return
        with self._lock:
            self._entries[identity] = ((url or ""), media, source)

    def invalidate(self, identity: str) -> None:
        with self._lock:
            self._entries.pop(identity, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


# ---------------------------------------------------------------------------
# Format resolution
# ---------------------------------------------------------------------------

def _format_kind(fmt: object) -> str:
    from recorder import RECORDING_FORMATS, DEFAULT_RECORDING_FORMAT
    entry = RECORDING_FORMATS.get(fmt) if isinstance(fmt, str) else None
    entry = entry or RECORDING_FORMATS[DEFAULT_RECORDING_FORMAT]
    return entry[2]


def formats_for_media(media: str) -> List[str]:
    """Preset keys the Recording Format menu should offer.

    Audio-only streams get the audio presets only (including the MKA provider
    copy); video and not-yet-classified streams keep the full list, so audio
    presets stay available as a deliberate "soundtrack only" choice.
    """
    from recorder import RECORDING_FORMATS
    if media == MEDIA_AUDIO:
        return [key for key, entry in RECORDING_FORMATS.items() if entry[2] == "audio"]
    return list(RECORDING_FORMATS)


def resolve_recording_format(media: str, audio_pref: object, video_pref: object) -> str:
    """The format key to record a stream of ``media`` with.

    Audio-only streams use the audio preference (clamped to an audio preset);
    everything else -- including not-yet-classified streams -- keeps the
    long-standing behaviour of using the video preference, so existing
    television recording behaviour is unchanged unless the stream is
    positively identified as audio-only. The video preference may name an
    audio preset: MP3 picked on a TV channel records its soundtrack.
    """
    from recorder import RECORDING_FORMATS
    if media == MEDIA_AUDIO:
        if isinstance(audio_pref, str) and _format_kind(audio_pref) == "audio":
            return audio_pref
        return DEFAULT_AUDIO_FORMAT
    if isinstance(video_pref, str) and video_pref in RECORDING_FORMATS:
        return video_pref
    return DEFAULT_VIDEO_FORMAT


def remap_format_for_media(fmt: object, media: str,
                           audio_pref: object, video_pref: object) -> Tuple[str, bool]:
    """Remap a stored format key onto what ``media`` can actually hold.

    Only ever remaps a video preset to the audio preference for audio-only
    streams (scheduled jobs saved before the stream was classified, or while
    the global preference was a video preset). An audio preset on a video
    stream is an intentional "soundtrack only" choice and is left alone.
    Returns ``(format key, remapped)``.
    """
    key = fmt if isinstance(fmt, str) else ""
    if media == MEDIA_AUDIO and _format_kind(key) == "video":
        audio = (audio_pref if isinstance(audio_pref, str)
                 and _format_kind(audio_pref) == "audio" else DEFAULT_AUDIO_FORMAT)
        return audio, audio != key
    return key, False


def migrate_recording_format_prefs(cfg: Dict[str, object]) -> None:
    """Split the legacy single ``recording_format`` into per-media prefs.

    Seeds ``recording_format_audio`` / ``recording_format_video`` from the
    legacy value the first time (an audio legacy seeds the audio pref and the
    video pref falls back to the default, and vice versa). Valid stored
    preferences are never overwritten.
    """
    from recorder import RECORDING_FORMATS, DEFAULT_RECORDING_FORMAT
    legacy = cfg.get("recording_format")
    if not (isinstance(legacy, str) and legacy in RECORDING_FORMATS):
        legacy = DEFAULT_RECORDING_FORMAT
    legacy_kind = RECORDING_FORMATS[legacy][2]

    audio = cfg.get("recording_format_audio")
    if not (isinstance(audio, str) and audio in RECORDING_FORMATS
            and RECORDING_FORMATS[audio][2] == "audio"):
        cfg["recording_format_audio"] = legacy if legacy_kind == "audio" else DEFAULT_AUDIO_FORMAT
    video = cfg.get("recording_format_video")
    if not (isinstance(video, str) and video in RECORDING_FORMATS):
        cfg["recording_format_video"] = legacy if legacy_kind == "video" else DEFAULT_RECORDING_FORMAT
