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
    monkeypatch.setattr(options, "get_config_write_target",
                        lambda: str(cfg_file))
    for stored, expected in ((2.0, 2.0), (4.0, 4.0), (12.0, 12.0), (5.0, 5.0)):
        cfg_file.write_text(json.dumps({"internal_player_buffer_seconds": stored}),
                            encoding="utf-8")
        cfg = options.load_config()
        assert cfg["internal_player_buffer_seconds"] == expected
        options.save_config(cfg)
        assert options.load_config()["internal_player_buffer_seconds"] == expected


def test_missing_buffer_defaults_to_the_live_cushion(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(options, "get_config_read_candidates", lambda: [str(cfg_file)])
    cfg = options.load_config()
    # Start stays fast: the player opens on QUICK_START_SECONDS and builds this by slow play.
    assert cfg["internal_player_buffer_seconds"] == 25.0


def test_old_default_maximum_no_longer_caps_live_cushion(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(options, "get_config_read_candidates", lambda: [str(cfg_file)])
    monkeypatch.setattr(options, "get_config_write_target", lambda: str(cfg_file))
    for maximum, expected in ((18.0, 30.0), (12.0, 12.0), (45.0, 45.0)):
        cfg_file.write_text(json.dumps({"internal_player_buffer_seconds": 2.0,
                                        "internal_player_max_buffer_seconds": maximum}), encoding="utf-8")
        cfg = options.load_config()
        assert cfg["internal_player_buffer_seconds"] == 2.0
        assert cfg["internal_player_max_buffer_seconds"] == expected
        options.save_config(cfg)
        assert options.load_config()["internal_player_max_buffer_seconds"] == expected


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


def test_an_unreadable_config_is_kept_before_it_is_overwritten(tmp_path, monkeypatch):
    """A corrupt config holds the user's playlists and favourites.

    The first save overwrites it, so the unreadable file has to be kept
    before the app moves on to the next candidate location.
    """
    cfg_file = tmp_path / "iptvclient.conf"
    cfg_file.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(options, "get_config_read_candidates", lambda: [str(cfg_file)])
    monkeypatch.setattr(options, "get_config_write_target", lambda: str(tmp_path / "written.conf"))

    options.load_config()

    kept = tmp_path / "iptvclient.conf.corrupt"
    assert kept.exists()
    assert kept.read_text(encoding="utf-8") == "{ this is not json"


def test_a_read_only_config_folder_sends_the_cache_to_the_temp_folder(tmp_path, monkeypatch):
    """A read-only config folder must not take every playlist refresh down."""
    import tempfile

    read_only = tmp_path / "readonly"
    read_only.mkdir()
    monkeypatch.setattr(options, "get_user_config_dir", lambda: str(read_only))

    real_makedirs = options.os.makedirs

    def refuse(path, **kwargs):
        if str(path).startswith(str(read_only)):
            raise PermissionError(13, "Permission denied")
        return real_makedirs(path, **kwargs)

    monkeypatch.setattr(options.os, "makedirs", refuse)

    cache_dir = options.get_cache_dir()
    assert cache_dir.startswith(tempfile.gettempdir())


def test_concurrent_saves_do_not_collide(tmp_path, monkeypatch):
    """The GUI thread and the playlist worker both save the config.

    With one fixed temp name they wrote the same file, and the loser failed
    with "being used by another process" - the setting was then silently
    lost, and the user was told the config could not be saved.
    """
    import threading

    target = tmp_path / "iptvclient.conf"
    monkeypatch.setattr(options, "get_config_write_target", lambda: str(target))
    monkeypatch.setattr(options, "get_config_read_candidates", lambda: [str(target)])

    errors = []

    def save(number):
        try:
            for _ in range(20):
                options.save_config({"n": number})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert json.loads(target.read_text(encoding="utf-8"))["n"] in (0, 1, 2, 3)
    assert not list(tmp_path.glob("*.tmp"))
