"""Tests for the gettext-based internationalization layer (i18n.py) and its tooling.

These are GUI-free so they run headless and fast. They cover language activation,
OS detection, English fallback, the Hungarian catalogue, placeholder integrity
(so a translation can never drop a ``{token}`` and crash ``.format()`` at runtime),
and a round-trip through the pure-Python extract/compile tooling.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import i18n  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALE = os.path.join(REPO, "locale")
HU_PO = os.path.join(LOCALE, "hu", "LC_MESSAGES", "iptvclient.po")
HU_MO = os.path.join(LOCALE, "hu", "LC_MESSAGES", "iptvclient.mo")
POT = os.path.join(LOCALE, "iptvclient.pot")

_PLACEHOLDER = re.compile(r"{[^}]*}")


def teardown_function(_func):
    # Keep tests independent of each other's language state.
    i18n.set_language("en")


# --------------------------------------------------------------------------- #
# Framework behaviour
# --------------------------------------------------------------------------- #
def test_underscore_builtin_is_installed():
    assert callable(__builtins__["_"] if isinstance(__builtins__, dict) else __builtins__._)


def test_available_languages_order_and_membership():
    codes = [code for code, _label in i18n.available_languages()]
    # Automatic + English lead; then the requested language order.
    assert codes[:14] == [
        "auto", "en", "es", "ar", "pt", "fr", "de", "ru", "tr", "it",
        "pl", "hi", "zh", "ja",
    ]
    # Hungarian remains available too.
    assert "hu" in codes
    # Every shipped catalogue is offered in the menu.
    for code in i18n.SHIPPED_CATALOGS:
        assert code in codes, code


def test_english_uses_source_strings():
    i18n.set_language("en")
    assert i18n.gettext("Restore") == "Restore"
    assert i18n.get_language() == "en"


def test_hungarian_translates_known_strings():
    i18n.set_language("hu")
    assert i18n.gettext("Restore") == "Ablak visszaállítása"
    assert i18n.gettext("Stop") == "Leállítás"
    assert i18n.gettext("Language") == "Nyelv"
    assert i18n.get_language() == "hu"


def test_hungarian_preserves_format_placeholders():
    i18n.set_language("hu")
    out = i18n.gettext("Casting to {device}...").format(device="Living Room")
    assert "Living Room" in out
    assert "{device}" not in out


def test_unknown_message_falls_back_to_source():
    i18n.set_language("hu")
    assert i18n.gettext("an utterly unknown string 12345") == "an utterly unknown string 12345"


def test_unknown_language_falls_back_without_error():
    # A language we ship no catalogue for must degrade to English, not crash.
    i18n.set_language("zz")
    assert i18n.gettext("Restore") == "Restore"


def test_auto_resolves_and_does_not_crash():
    code = i18n.set_language("auto")
    assert code == "auto"
    # Whatever the host language is, a lookup must return a non-empty string.
    assert i18n.gettext("Restore")


def test_detect_system_language_returns_short_code():
    code = i18n.detect_system_language()
    assert isinstance(code, str) and 1 <= len(code) <= 3


def test_init_from_config_activates_language():
    i18n.init_from_config({"language": "hu"})
    assert i18n.get_language() == "hu"
    assert i18n.gettext("Stop") == "Leállítás"
    i18n.init_from_config({})  # missing key -> auto, must not raise
    assert i18n.get_language() == "auto"


# --------------------------------------------------------------------------- #
# Catalogue files
# --------------------------------------------------------------------------- #
def test_locale_files_exist():
    assert os.path.exists(POT)
    assert os.path.exists(HU_PO)
    assert os.path.exists(HU_MO)


def _po_path(code):
    return os.path.join(LOCALE, code, "LC_MESSAGES", "iptvclient.po")


@pytest.mark.parametrize("code", i18n.SHIPPED_CATALOGS)
def test_shipped_catalogue_is_fully_translated(code):
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import i18n_tools

    entries = [e for e in i18n_tools.parse_po(_po_path(code)) if e.get("msgid")]
    untranslated = [e["msgid"] for e in entries if not e.get("msgstr")]
    assert not untranslated, f"Untranslated {code} strings: {untranslated[:5]}"


@pytest.mark.parametrize("code", i18n.SHIPPED_CATALOGS)
def test_shipped_catalogue_placeholders_match_source(code):
    """Every {placeholder} in a source string must survive into its translation."""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import i18n_tools

    mismatches = []
    for e in i18n_tools.parse_po(_po_path(code)):
        msgid, msgstr = e.get("msgid", ""), e.get("msgstr", "")
        if not msgid or not msgstr:
            continue
        if set(_PLACEHOLDER.findall(msgid)) != set(_PLACEHOLDER.findall(msgstr)):
            mismatches.append(msgid)
    assert not mismatches, f"Placeholder mismatch in {code}: {mismatches}"


# --------------------------------------------------------------------------- #
# Tooling round-trip (pure-Python extract + compile)
# --------------------------------------------------------------------------- #
def test_extractor_finds_wrapped_strings():
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import i18n_tools

    messages = i18n_tools.extract_messages(i18n_tools.SOURCE_FILES)
    # A representative sample of strings wrapped across the app.
    for expected in ("Restore", "Playlist Manager", "Buffering...", "Cast to Device"):
        assert expected in messages, expected


def test_compile_roundtrip(tmp_path):
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import gettext as gt

    import i18n_tools

    po = tmp_path / "x.po"
    po.write_text(
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
        'msgid "Hello"\n'
        'msgstr "Szia"\n\n'
        'msgid "Untranslated"\n'
        'msgstr ""\n',
        encoding="utf-8",
    )
    mo_path, translated = i18n_tools.compile_po(str(po))
    assert translated == 1
    with open(mo_path, "rb") as fh:
        trans = gt.GNUTranslations(fh)
    assert trans.gettext("Hello") == "Szia"
    # Empty msgstr must fall back to the source, never to "".
    assert trans.gettext("Untranslated") == "Untranslated"


def test_committed_mo_matches_po(tmp_path):
    """The committed hu.mo must reflect the current hu.po (guards against a stale .mo)."""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import gettext as gt

    import i18n_tools

    fresh = tmp_path / "iptvclient.mo"
    i18n_tools.compile_po(HU_PO, str(fresh))
    with open(fresh, "rb") as fh:
        fresh_trans = gt.GNUTranslations(fh)
    with open(HU_MO, "rb") as fh:
        committed_trans = gt.GNUTranslations(fh)
    for sample in ("Restore", "Stop", "Casting to {device}...", "Language"):
        assert fresh_trans.gettext(sample) == committed_trans.gettext(sample)
