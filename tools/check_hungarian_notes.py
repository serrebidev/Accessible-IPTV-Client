"""Check manually maintained Hungarian notes without changing release policy."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import i18n_tools  # noqa: E402


def problems():
    messages = i18n_tools.extract_release_notes()
    entries = {e['msgid']: e.get('msgstr', '') for e in i18n_tools.parse_po(
        str(ROOT / 'locale/hu/LC_MESSAGES/release_notes.po')) if e.get('msgid')}
    return [message for message in messages if not entries.get(message, '').strip()]


if __name__ == '__main__':
    missing = problems()
    for message in missing:
        print('Missing Hungarian release note:', message)
    if not missing:
        print('All current Hungarian release notes are translated.')
    raise SystemExit(bool(missing))
