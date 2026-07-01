import json
from pathlib import Path

import options


def _configure_portable_windows_frozen(monkeypatch, tmp_path):
    roaming = tmp_path / "Roaming"
    temp_dir = tmp_path / "Temp"
    app_dir = tmp_path / "Portable Accessible IPTV Client"
    cwd_dir = tmp_path / "Working"
    app_dir.mkdir(parents=True)
    temp_dir.mkdir()
    cwd_dir.mkdir()
    exe_path = app_dir / "AccessibleIPTVClient.exe"
    exe_path.write_bytes(b"portable exe placeholder")

    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setattr(options, "_IS_WINDOWS", True)
    monkeypatch.setattr(options.sys, "platform", "win32")
    monkeypatch.setattr(options.sys, "frozen", True, raising=False)
    monkeypatch.setattr(options.sys, "executable", str(exe_path))
    monkeypatch.delattr(options.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(options, "get_cwd_dir", lambda: str(cwd_dir))
    monkeypatch.setattr(options.tempfile, "gettempdir", lambda: str(temp_dir))
    options._CONFIG_PATH = None
    return roaming, app_dir, cwd_dir


def _configure_installed_windows(monkeypatch, tmp_path):
    roaming = tmp_path / "Roaming"
    temp_dir = tmp_path / "Temp"
    app_dir = tmp_path / "Program Files" / "AccessibleIPTVClient"
    app_dir.mkdir(parents=True)
    temp_dir.mkdir()
    (app_dir / options.WINDOWS_INSTALL_MARKER).write_text("installed\n", encoding="utf-8")

    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setattr(options, "_IS_WINDOWS", True)
    monkeypatch.setattr(options.sys, "platform", "win32")
    monkeypatch.setattr(options.sys, "frozen", True, raising=False)
    monkeypatch.setattr(options, "get_app_dir", lambda: str(app_dir))
    monkeypatch.setattr(options.tempfile, "gettempdir", lambda: str(temp_dir))
    options._CONFIG_PATH = None
    return roaming, temp_dir, app_dir


def _configure_source_windows(monkeypatch, tmp_path):
    roaming = tmp_path / "Roaming"
    app_dir = tmp_path / "SourceCheckout"
    cwd_dir = tmp_path / "Working"
    app_dir.mkdir()
    cwd_dir.mkdir()

    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setattr(options, "_IS_WINDOWS", True)
    monkeypatch.setattr(options.sys, "platform", "win32")
    monkeypatch.setattr(options.sys, "frozen", False, raising=False)
    monkeypatch.setattr(options, "get_app_dir", lambda: str(app_dir))
    monkeypatch.setattr(options, "get_cwd_dir", lambda: str(cwd_dir))
    options._CONFIG_PATH = None
    return roaming, app_dir, cwd_dir


def test_portable_windows_frozen_prefers_executable_config_without_install_marker(monkeypatch, tmp_path):
    roaming, app_dir, cwd_dir = _configure_portable_windows_frozen(monkeypatch, tmp_path)
    user_dir = roaming / options.APP_DATA_DIR_NAME
    legacy_dir = roaming / options.LEGACY_APP_DATA_DIR_NAME
    user_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)

    (app_dir / options.CONFIG_FILE).write_text('{"playlists": ["portable"]}', encoding="utf-8")
    (cwd_dir / options.CONFIG_FILE).write_text('{"playlists": ["cwd"]}', encoding="utf-8")
    (user_dir / options.CONFIG_FILE).write_text('{"playlists": ["appdata"]}', encoding="utf-8")
    (legacy_dir / options.CONFIG_FILE).write_text('{"playlists": ["legacy"]}', encoding="utf-8")

    assert not options.is_windows_installed_build()

    candidates = [Path(candidate) for candidate in options.get_config_read_candidates()]
    assert candidates[0] == app_dir / options.CONFIG_FILE

    cfg = options.load_config()
    assert cfg["playlists"] == ["portable"]
    assert Path(options.get_loaded_config_path()) == app_dir / options.CONFIG_FILE


def test_portable_windows_frozen_writes_next_to_executable_without_install_marker(monkeypatch, tmp_path):
    roaming, app_dir, _cwd_dir = _configure_portable_windows_frozen(monkeypatch, tmp_path)
    user_config = roaming / options.APP_DATA_DIR_NAME / options.CONFIG_FILE

    assert not options.is_windows_installed_build()
    assert Path(options.get_config_write_target()) == app_dir / options.CONFIG_FILE

    options.save_config({"playlists": ["portable-save"]})

    assert (app_dir / options.CONFIG_FILE).exists()
    saved = json.loads((app_dir / options.CONFIG_FILE).read_text(encoding="utf-8"))
    assert saved["playlists"] == ["portable-save"]
    assert not user_config.exists()


def test_non_frozen_windows_keeps_appdata_config_behavior(monkeypatch, tmp_path):
    roaming, app_dir, cwd_dir = _configure_source_windows(monkeypatch, tmp_path)
    user_dir = roaming / options.APP_DATA_DIR_NAME

    assert not options.is_windows_portable_build()
    assert Path(options.get_config_write_target()) == user_dir / options.CONFIG_FILE

    candidates = [Path(candidate) for candidate in options.get_config_read_candidates()]
    assert candidates[:3] == [
        user_dir / options.CONFIG_FILE,
        app_dir / options.CONFIG_FILE,
        cwd_dir / options.CONFIG_FILE,
    ]


def test_installed_windows_runtime_paths_use_roaming_appdata(monkeypatch, tmp_path):
    roaming, _temp_dir, app_dir = _configure_installed_windows(monkeypatch, tmp_path)
    user_dir = roaming / "AccessibleIPTVClient"

    assert options.is_windows_installed_build()
    assert Path(options.get_user_config_dir(create=False)) == user_dir
    assert Path(options.get_config_write_target()) == user_dir / "iptvclient.conf"
    assert Path(options.get_db_path()) == user_dir / "epg.db"
    assert Path(options.get_cache_dir()) == user_dir / "iptv_cache"
    assert Path(options.get_dvr_schedule_path()) == user_dir / "scheduled_recordings.json"
    assert Path(options.get_epg_log_path()) == user_dir / "iptvclient_epg_debug.log"

    candidates = [Path(candidate) for candidate in options.get_config_read_candidates()]
    assert candidates[0] == user_dir / "iptvclient.conf"
    assert app_dir / "iptvclient.conf" in candidates
    assert roaming / "IPTVClient" / "iptvclient.conf" in candidates


def test_installed_windows_migrates_legacy_config_and_epg_db(monkeypatch, tmp_path):
    roaming, temp_dir, _app_dir = _configure_installed_windows(monkeypatch, tmp_path)
    legacy_dir = roaming / "IPTVClient"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "iptvclient.conf").write_text('{"playlists": ["legacy"]}', encoding="utf-8")
    (temp_dir / "epg.db").write_bytes(b"legacy-db")

    cfg = options.load_config()
    user_dir = roaming / "AccessibleIPTVClient"

    assert cfg["playlists"] == ["legacy"]
    assert (user_dir / "iptvclient.conf").read_text(encoding="utf-8") == '{"playlists": ["legacy"]}'
    assert (user_dir / "epg.db").read_bytes() == b"legacy-db"
    assert (user_dir / options.WINDOWS_INSTALL_MIGRATION_SENTINEL).exists()


def test_installed_windows_migration_does_not_overwrite_existing_user_data(monkeypatch, tmp_path):
    roaming, temp_dir, _app_dir = _configure_installed_windows(monkeypatch, tmp_path)
    user_dir = roaming / "AccessibleIPTVClient"
    legacy_dir = roaming / "IPTVClient"
    user_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    (user_dir / "iptvclient.conf").write_text('{"playlists": ["current"]}', encoding="utf-8")
    (legacy_dir / "iptvclient.conf").write_text('{"playlists": ["legacy"]}', encoding="utf-8")
    (user_dir / "epg.db").write_bytes(b"current-db")
    (temp_dir / "epg.db").write_bytes(b"legacy-db")

    options._prepare_windows_installed_data()

    assert (user_dir / "iptvclient.conf").read_text(encoding="utf-8") == '{"playlists": ["current"]}'
    assert (user_dir / "epg.db").read_bytes() == b"current-db"
