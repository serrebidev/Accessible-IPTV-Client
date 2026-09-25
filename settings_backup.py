"""Password-encrypted export of the user's IPTV settings."""

import base64
import hashlib
import json
import os

from cryptography.fernet import Fernet, InvalidToken

from i18n import gettext as _

_ITERATIONS = 600_000
_MAX_BACKUP_BYTES = 16 * 1024 * 1024


def _cipher(password: str, salt: bytes) -> Fernet:
    if not password:
        raise ValueError(_("A backup password is required."))
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return Fernet(base64.urlsafe_b64encode(key))


def export_settings(path: str, config: dict, password: str) -> None:
    salt = os.urandom(16)
    contents = json.dumps(config, ensure_ascii=False).encode("utf-8")
    if len(contents) > _MAX_BACKUP_BYTES:
        raise ValueError(_("Settings are too large to back up."))
    data = {
        "format": "accessible-iptv-settings-v1",
        "salt": base64.b64encode(salt).decode("ascii"),
        "data": _cipher(password, salt).encrypt(contents).decode("ascii"),
    }
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as output:
            json.dump(data, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def import_settings(path: str, password: str) -> dict:
    if os.path.getsize(path) > _MAX_BACKUP_BYTES:
        raise ValueError(_("Backup file is too large."))
    with open(path, "r", encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict) or data.get("format") != "accessible-iptv-settings-v1":
        raise ValueError(_("Not an Accessible IPTV settings backup."))
    try:
        salt = base64.b64decode(data["salt"], validate=True)
        if len(salt) != 16:
            raise ValueError(_("Invalid backup salt."))
        contents = _cipher(password, salt).decrypt(data["data"].encode("ascii"))
        config = json.loads(contents)
    except (InvalidToken, KeyError, UnicodeError) as err:
        raise ValueError(_("Wrong password or damaged backup.")) from err
    if not isinstance(config, dict) or not isinstance(config.get("playlists"), list) or not isinstance(config.get("epgs"), list):
        raise ValueError(_("Backup settings are invalid."))
    return config
