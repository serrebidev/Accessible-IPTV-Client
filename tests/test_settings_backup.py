import base64
import json

import pytest

import settings_backup


def test_encrypted_backup_round_trip_and_wrong_password(tmp_path):
    path = tmp_path / "settings.aiptv"
    config = {"playlists": [{"url": "https://user:secret@example.test/list"}],
              "epgs": [], "favorites": ["BBC"]}
    settings_backup.export_settings(str(path), config, "long secret phrase")
    assert b"secret@example" not in path.read_bytes()
    assert settings_backup.import_settings(str(path), "long secret phrase") == config
    with pytest.raises(ValueError, match="Wrong password"):
        settings_backup.import_settings(str(path), "wrong")


def test_a_damaged_backup_says_so_in_the_app_s_own_words(tmp_path):
    """The parser's own message tells the user nothing about what to do.

    The import box shows the error, so it has to be one of the app's
    messages, not "Expecting value: line 1 column 1 (char 0)".
    """
    not_json = tmp_path / "broken.aiptv"
    not_json.write_text("this is not json at all", encoding="utf-8")
    with pytest.raises(ValueError, match="Not an Accessible IPTV settings backup"):
        settings_backup.import_settings(str(not_json), "long secret phrase")

    # A backup whose contents are damaged, not its wrapper.
    path = tmp_path / "settings.aiptv"
    config = {"playlists": [], "epgs": []}
    settings_backup.export_settings(str(path), config, "long secret phrase")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["data"] = base64.b64encode(b"not the encrypted settings").decode("ascii")
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Wrong password or damaged backup"):
        settings_backup.import_settings(str(path), "long secret phrase")
