"""GUI-free tests for media-type detection and per-type format prefs (issue #33)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import media_type
from media_type import (
    MEDIA_AUDIO,
    MEDIA_UNKNOWN,
    MEDIA_VIDEO,
    SOURCE_METADATA,
    SOURCE_PROBE,
    MediaTypeCache,
    channel_media_from_metadata,
    classify_media_streams,
    classify_probe_report,
    formats_for_media,
    media_hint_from_attributes,
    migrate_recording_format_prefs,
    parse_media_streams,
    remap_format_for_media,
    resolve_recording_format,
)


# -- attribute / metadata parsing --------------------------------------------


@pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE", " Yes "])
def test_radio_truthy_values_mean_audio(value):
    assert media_hint_from_attributes({"radio": value}) == MEDIA_AUDIO


@pytest.mark.parametrize("value", ["false", "0", "no", "FALSE"])
def test_radio_falsy_values_mean_video(value):
    # An explicit radio="false" is an authoritative not-radio statement.
    assert media_hint_from_attributes({"radio": value}) == MEDIA_VIDEO


def test_unrecognized_radio_values_are_not_authoritative():
    assert media_hint_from_attributes({"radio": "maybe"}) == ""
    assert media_hint_from_attributes({"radio": "on"}) == ""


@pytest.mark.parametrize("key", ["media-type", "mediatype", "media_type"])
def test_media_type_attribute_keys(key):
    assert media_hint_from_attributes({key: "audio"}) == MEDIA_AUDIO
    assert media_hint_from_attributes({key: "radio"}) == MEDIA_AUDIO
    assert media_hint_from_attributes({key: "music"}) == MEDIA_AUDIO
    assert media_hint_from_attributes({key: "Audio"}) == MEDIA_AUDIO
    assert media_hint_from_attributes({key: "video"}) == MEDIA_VIDEO
    assert media_hint_from_attributes({key: "tv"}) == MEDIA_VIDEO


@pytest.mark.parametrize("key", ["stream-type", "streamtype"])
def test_stream_type_attribute_keys(key):
    assert media_hint_from_attributes({key: "audio"}) == MEDIA_AUDIO
    assert media_hint_from_attributes({key: "radio"}) == MEDIA_AUDIO
    assert media_hint_from_attributes({key: "video"}) == MEDIA_VIDEO


@pytest.mark.parametrize("key", ["tvg-type", "tvgtype"])
def test_tvg_type_attribute_keys(key):
    assert media_hint_from_attributes({key: "radio"}) == MEDIA_AUDIO
    assert media_hint_from_attributes({key: "audio"}) == MEDIA_AUDIO
    assert media_hint_from_attributes({key: "tv"}) == MEDIA_VIDEO


def test_attribute_values_are_case_insensitive():
    # Keys arrive lowercased from the M3U parser; values are normalized here.
    assert media_hint_from_attributes({"radio": "TRUE"}) == MEDIA_AUDIO
    assert media_hint_from_attributes({"tvg-type": "RADIO"}) == MEDIA_AUDIO


def test_first_authoritative_attribute_wins():
    assert media_hint_from_attributes({"radio": "false", "media-type": "audio"}) == MEDIA_VIDEO
    assert media_hint_from_attributes({"media-type": "audio", "tvg-type": "tv"}) == MEDIA_AUDIO


def test_unrelated_attributes_give_no_hint():
    assert media_hint_from_attributes({"group-title": "Music", "tvg-id": "x"}) == ""
    assert media_hint_from_attributes({}) == ""


def test_channel_metadata_recognizes_media_hint():
    assert channel_media_from_metadata({"media_hint": "audio"}) == MEDIA_AUDIO
    assert channel_media_from_metadata({"media_hint": "video"}) == MEDIA_VIDEO


def test_channel_metadata_reads_top_level_attributes():
    assert channel_media_from_metadata({"radio": "true"}) == MEDIA_AUDIO
    assert channel_media_from_metadata({"tvg-type": "radio"}) == MEDIA_AUDIO
    assert channel_media_from_metadata({"media-type": "audio"}) == MEDIA_AUDIO
    assert channel_media_from_metadata({"radio": "false"}) == MEDIA_VIDEO


def test_channel_name_is_never_a_hint():
    # A name like "Radio Paradise" proves nothing: only playlist metadata
    # attributes may classify a channel.
    assert channel_media_from_metadata({"name": "Radio Paradise"}) is None
    assert channel_media_from_metadata({}) is None


# -- probe report classification ----------------------------------------------

AUDIO_REPORT = """\
Input #0, mp3, from 'http://example.com/stream':
  Duration: N/A, start: 0.000000, bitrate: 128 kb/s
  Stream #0:0: Audio: mp3, 44100 Hz, stereo, fltp, 128 kb/s
"""

VIDEO_REPORT = """\
Input #0, mpegts, from 'http://example.com/stream':
  Duration: N/A, start: 1.000000, bitrate: N/A
  Stream #0:0[0x100]: Video: h264 (Main), yuv420p, 1280x720, 25 fps
  Stream #0:1[0x101](eng): Audio: aac (LC), 48000 Hz, stereo, fltp
"""

RADIO_WITH_COVER_ART = """\
Input #0, mp3, from 'http://example.com/stream':
  Duration: N/A, start: 0.000000, bitrate: 128 kb/s
  Stream #0:0: Audio: mp3, 44100 Hz, stereo, fltp, 128 kb/s
  Stream #0:1: Video: mjpeg, yuvj420p(pc), 300x300 [SAR 1:1 DAR 1:1], 90k tbr, 90k tbn (attached pic)
"""


def test_probe_audio_only_classifies_audio():
    assert classify_probe_report(AUDIO_REPORT) == MEDIA_AUDIO


def test_probe_video_classifies_video():
    assert classify_probe_report(VIDEO_REPORT) == MEDIA_VIDEO


def test_probe_attached_picture_is_not_video():
    # Radio streams often carry an attached cover image: it must not make the
    # stream look like video.
    assert classify_probe_report(RADIO_WITH_COVER_ART) == MEDIA_AUDIO


def test_probe_empty_report_is_unknown():
    assert classify_probe_report("") == MEDIA_UNKNOWN
    assert classify_probe_report("Input #0, mp3: Duration: N/A\n") == MEDIA_UNKNOWN


def test_parse_media_streams_reads_kinds_and_dispositions():
    streams = parse_media_streams(RADIO_WITH_COVER_ART)
    assert [s["kind"] for s in streams] == ["audio", "video"]
    assert "attached pic" in streams[1]["dispositions"]


def test_classify_media_streams_directly():
    assert classify_media_streams([{"kind": "audio", "dispositions": set()}]) == MEDIA_AUDIO
    assert classify_media_streams([{"kind": "video", "dispositions": set()}]) == MEDIA_VIDEO
    assert classify_media_streams(
        [{"kind": "audio", "dispositions": set()},
         {"kind": "video", "dispositions": {"attached pic"}}]) == MEDIA_AUDIO
    assert classify_media_streams([]) == MEDIA_UNKNOWN


# -- cache --------------------------------------------------------------------


def test_cache_stores_and_returns_known_types():
    cache = MediaTypeCache()
    cache.store("ch1", "http://x/stream", MEDIA_AUDIO, SOURCE_PROBE)
    assert cache.lookup("ch1", "http://x/stream") == (MEDIA_AUDIO, SOURCE_PROBE)


def test_cache_never_stores_unknown():
    cache = MediaTypeCache()
    cache.store("ch1", "http://x/stream", MEDIA_UNKNOWN, SOURCE_PROBE)
    assert cache.lookup("ch1", "http://x/stream") is None


def test_cache_invalidates_when_url_changes():
    cache = MediaTypeCache()
    cache.store("ch1", "http://x/old", MEDIA_AUDIO, SOURCE_METADATA)
    assert cache.lookup("ch1", "http://x/new") is None
    # ...but the stale entry does not leak into another identity either.
    assert cache.lookup("ch2", "http://x/old") is None


def test_cache_is_keyed_by_stable_identity():
    cache = MediaTypeCache()
    cache.store("ch1", "http://x/stream", MEDIA_AUDIO, SOURCE_PROBE)
    cache.store("ch2", "http://x/stream", MEDIA_VIDEO, SOURCE_PROBE)
    assert cache.lookup("ch1", "http://x/stream") == (MEDIA_AUDIO, SOURCE_PROBE)
    assert cache.lookup("ch2", "http://x/stream") == (MEDIA_VIDEO, SOURCE_PROBE)


def test_cache_invalidate_and_clear():
    cache = MediaTypeCache()
    cache.store("ch1", "http://x/stream", MEDIA_AUDIO, SOURCE_PROBE)
    cache.invalidate("ch1")
    assert cache.lookup("ch1", "http://x/stream") is None
    cache.store("ch1", "http://x/stream", MEDIA_AUDIO, SOURCE_PROBE)
    cache.clear()
    assert cache.lookup("ch1", "http://x/stream") is None


# -- format resolution ----------------------------------------------------------


def test_audio_media_offers_audio_formats_only():
    keys = formats_for_media(MEDIA_AUDIO)
    assert "provider_mka" in keys
    assert "audio_mp3_v0" in keys
    assert "provider_mkv" not in keys
    assert "x264_mp4" not in keys


def test_video_and_unknown_media_offer_everything():
    for media in (MEDIA_VIDEO, MEDIA_UNKNOWN):
        keys = formats_for_media(media)
        assert "provider_mka" in keys
        assert "provider_mkv" in keys
        assert "audio_mp3_v0" in keys


def test_resolve_audio_media_uses_audio_preference():
    assert resolve_recording_format(MEDIA_AUDIO, "audio_flac", "provider_mkv") == "audio_flac"


def test_resolve_audio_media_repairs_wrong_kind_preference():
    # A stale/corrupt audio preference naming a video preset is replaced with
    # the safe default instead of writing an audio-only MKV.
    assert resolve_recording_format(MEDIA_AUDIO, "provider_mkv", "provider_mkv") == "audio_mp3_v0"
    assert resolve_recording_format(MEDIA_AUDIO, None, "provider_mkv") == "audio_mp3_v0"


def test_resolve_video_media_uses_video_preference():
    assert resolve_recording_format(MEDIA_VIDEO, "audio_flac", "x264_mp4") == "x264_mp4"


def test_resolve_video_media_keeps_a_soundtrack_only_choice():
    # MP3 picked on a TV channel records the soundtrack; it used to be
    # "repaired" back to MKV, so the user's choice never took effect.
    assert resolve_recording_format(MEDIA_VIDEO, "audio_flac", "audio_mp3_v0") == "audio_mp3_v0"
    assert resolve_recording_format(MEDIA_VIDEO, "audio_flac", "bogus") == "provider_mkv"


def test_resolve_unknown_media_uses_video_preference():
    assert resolve_recording_format(MEDIA_UNKNOWN, "audio_mp3_v0", "provider_mkv") == "provider_mkv"
    assert resolve_recording_format(MEDIA_UNKNOWN, None, None) == "provider_mkv"


def test_remap_video_preset_on_audio_only_stream():
    fmt, remapped = remap_format_for_media("provider_mkv", MEDIA_AUDIO,
                                           "audio_mp3_v0", "provider_mkv")
    assert (fmt, remapped) == ("audio_mp3_v0", True)


def test_remap_leaves_audio_preset_alone():
    fmt, remapped = remap_format_for_media("provider_mka", MEDIA_AUDIO,
                                           "audio_mp3_v0", "provider_mkv")
    assert (fmt, remapped) == ("provider_mka", False)


def test_remap_never_touches_video_or_unknown_streams():
    for media in (MEDIA_VIDEO, MEDIA_UNKNOWN):
        fmt, remapped = remap_format_for_media("provider_mkv", media,
                                               "audio_mp3_v0", "provider_mkv")
        assert (fmt, remapped) == ("provider_mkv", False)
        # ...including a stored audio preset on a video stream: scheduled
        # execution preserves the job's stored choice (the pre-existing
        # behaviour) and only repairs the video-preset-on-audio-stream
        # mistake above.
        fmt, remapped = remap_format_for_media("audio_flac", media,
                                               "audio_mp3_v0", "provider_mkv")
        assert (fmt, remapped) == ("audio_flac", False)


# -- preference migration -------------------------------------------------------


def test_migrate_legacy_audio_preference():
    cfg = {"recording_format": "audio_flac"}
    migrate_recording_format_prefs(cfg)
    assert cfg["recording_format_audio"] == "audio_flac"
    assert cfg["recording_format_video"] == "provider_mkv"


def test_migrate_legacy_video_preference():
    cfg = {"recording_format": "x264_mp4"}
    migrate_recording_format_prefs(cfg)
    assert cfg["recording_format_video"] == "x264_mp4"
    assert cfg["recording_format_audio"] == "audio_mp3_v0"


def test_migrate_legacy_unknown_preference_yields_defaults():
    cfg = {"recording_format": "bogus"}
    migrate_recording_format_prefs(cfg)
    assert cfg["recording_format_audio"] == "audio_mp3_v0"
    assert cfg["recording_format_video"] == "provider_mkv"


def test_migrate_preserves_independent_preferences():
    cfg = {"recording_format": "provider_mkv",
           "recording_format_audio": "audio_opus",
           "recording_format_video": "x264_mkv"}
    migrate_recording_format_prefs(cfg)
    assert cfg["recording_format_audio"] == "audio_opus"
    assert cfg["recording_format_video"] == "x264_mkv"


def test_migrate_repairs_invalid_and_wrong_kind_preferences():
    cfg = {"recording_format_audio": "provider_mkv",   # video preset: wrong kind
           "recording_format_video": "bogus"}          # unknown key
    migrate_recording_format_prefs(cfg)
    assert cfg["recording_format_audio"] == "audio_mp3_v0"
    assert cfg["recording_format_video"] == "provider_mkv"


def test_mp3_picked_on_a_tv_channel_is_the_tv_choice(monkeypatch):
    """MP3 chosen on TVP 1 HD used to be saved as the radio preference, so
    TV recordings and catch-up downloads stayed MKV."""
    import types
    import main
    saved = []
    monkeypatch.setattr(main, "save_config", saved.append)
    client = types.SimpleNamespace(
        config={"recording_format_audio": "audio_flac", "recording_format_video": "provider_mkv"},
        _classify_channel_media=lambda channel: (channel["media"], "metadata"))
    main.IPTVClient._set_recording_format(client, "audio_mp3_v0", {"media": MEDIA_VIDEO})
    assert client.config["recording_format_video"] == "audio_mp3_v0"
    assert client.config["recording_format_audio"] == "audio_flac"
    main.IPTVClient._set_recording_format(client, "audio_mp3_v0", {"media": MEDIA_AUDIO})
    assert client.config["recording_format_audio"] == "audio_mp3_v0"
