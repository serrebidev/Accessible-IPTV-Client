"""GUI-free tests for the per-media-type recording preferences (issue #33)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import options


def test_migrate_wrapper_seeds_audio_pref_from_legacy():
    cfg = {"recording_format": "audio_flac"}
    options.migrate_recording_format_prefs(cfg)
    assert cfg["recording_format_audio"] == "audio_flac"
    assert cfg["recording_format_video"] == "provider_mkv"


def test_migrate_wrapper_seeds_video_pref_from_legacy():
    cfg = {"recording_format": "x264_mp4"}
    options.migrate_recording_format_prefs(cfg)
    assert cfg["recording_format_video"] == "x264_mp4"
    assert cfg["recording_format_audio"] == "audio_mp3_v0"


def test_migrate_wrapper_preserves_independent_prefs():
    cfg = {"recording_format": "provider_mkv",
           "recording_format_audio": "audio_opus",
           "recording_format_video": "x264_mkv"}
    options.migrate_recording_format_prefs(cfg)
    assert cfg["recording_format_audio"] == "audio_opus"
    assert cfg["recording_format_video"] == "x264_mkv"


def test_load_config_migrates_legacy_file(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"recording_format": "audio_aac_m4a"}),
                        encoding="utf-8")
    monkeypatch.setattr(options, "get_config_read_candidates",
                        lambda: [str(cfg_file)])
    cfg = options.load_config()
    assert cfg["recording_format_audio"] == "audio_aac_m4a"
    assert cfg["recording_format_video"] == "provider_mkv"


def test_load_config_preserves_explicit_buffer_settings(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(options, "get_config_read_candidates",
                        lambda: [str(cfg_file)])
    for stored, expected in ((2.0, 2.0), (4.0, 4.0), (12.0, 12.0), (5.0, 5.0)):
        cfg_file.write_text(json.dumps({"internal_player_buffer_seconds": stored}),
                            encoding="utf-8")
        assert options.load_config()["internal_player_buffer_seconds"] == expected


def test_load_config_keeps_existing_split_prefs(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "recording_format": "provider_mkv",
        "recording_format_audio": "audio_opus",
        "recording_format_video": "x264_mkv",
    }), encoding="utf-8")
    monkeypatch.setattr(options, "get_config_read_candidates",
                        lambda: [str(cfg_file)])
    cfg = options.load_config()
    assert cfg["recording_format_audio"] == "audio_opus"
    assert cfg["recording_format_video"] == "x264_mkv"
