"""Tests for the pre-release translation audit (every language except Hungarian)."""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import i18n  # noqa: E402
import i18n_tools  # noqa: E402
import release  # noqa: E402
import translation_audit as audit  # noqa: E402

EN_GUIDE = """# Guide {#top}

Intro text for the whole program guide.

## Recordings {#recordings}

- Press the record key to start recording now.
- Stop.

Recording keeps going while you watch another channel.
"""

DE_GUIDE = """# Anleitung {#top}

Einleitungstext für die ganze Programmanleitung.

## Aufnahmen {#recordings}

- Drücken Sie die Aufnahmetaste, um jetzt aufzunehmen.
- Stopp.

Die Aufnahme läuft weiter, während Sie einen anderen Sender ansehen.
"""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _po(path, pairs):
    body = ['msgid ""\nmsgstr ""\n"Language: xx\\n"\n']
    for msgid, msgstr in pairs:
        body.append(f'msgid "{i18n_tools._escape(msgid)}"\nmsgstr "{i18n_tools._escape(msgstr)}"\n')
    _write(path, "\n".join(body))


def _messages(*msgids):
    return {m: {"plural": None, "locations": set()} for m in msgids}


def test_hungarian_is_the_only_exempt_language():
    assert set(audit.AUDITED_LANGUAGES) == set(i18n.SHIPPED_CATALOGS) - {"hu"}


def test_committed_catalogues_pass_the_audit():
    messages = i18n_tools.extract_messages(i18n_tools.SOURCE_FILES)
    ok = audit.load_identical_ok()
    for lang in audit.AUDITED_LANGUAGES:
        assert audit.audit_catalog(lang, messages, identical_ok=ok) == [], lang


def test_catalog_flags_missing_empty_english_and_placeholders(tmp_path):
    _po(tmp_path / "de" / "LC_MESSAGES" / "iptvclient.po", [
        ("Empty", ""),
        ("Copied text", "Copied text"),
        ("Brand", "Brand"),
        ("{a} {b}", "{a} {b}"),
        ("Hello {name}", "Hallo {nme}"),
        ("Fine", "Gut"),
    ])
    messages = _messages("Empty", "Copied text", "Brand", "{a} {b}", "Hello {name}", "Fine", "New")
    problems = audit.audit_catalog("de", messages, locale_dir=str(tmp_path),
                                   identical_ok={"de": {"Brand"}})
    text = "\n".join(problems)
    assert "untranslated: 'Empty'" in text
    assert "still English: 'Copied text'" in text
    assert "new string not in catalogue: 'New'" in text
    assert "placeholders differ: 'Hello {name}'" in text
    assert "Brand" not in text and "{a} {b}" not in text and "Fine" not in text
    assert len(problems) == 4


def _guides(tmp_path, de_text=DE_GUIDE):
    _write(tmp_path / "en.md", EN_GUIDE)
    _write(tmp_path / "de.md", de_text)
    return str(tmp_path)


def test_synced_guide_passes(tmp_path):
    help_dir = _guides(tmp_path)
    sync = {"de": audit.english_blob_id(help_dir)}
    assert audit.audit_guide("de", help_dir, sync=sync) == []


def test_blob_id_matches_git_and_ignores_crlf(tmp_path):
    _write(tmp_path / "en.md", "a\nb\n")
    lf = audit.english_blob_id(str(tmp_path))
    assert lf == "422c2b7ab3b3c668038da977e4e93a5fc623169c"  # git hash-object of "a\nb\n"
    _write(tmp_path / "en.md", "a\r\nb\r\n")
    assert audit.english_blob_id(str(tmp_path)) == lf


def test_guide_flags_structure_english_and_stale_sync(tmp_path):
    de = DE_GUIDE.replace("- Stopp.\n", "").replace(
        "Einleitungstext für die ganze Programmanleitung.",
        "Intro text for the whole program guide.")
    help_dir = _guides(tmp_path, de)
    problems = audit.audit_guide("de", help_dir, sync={"de": "0" * 40})
    text = "\n".join(problems)
    assert "#recordings has 1 bullets/1 paragraphs, en.md has 2/1" in text
    assert "de.md:3 is still English" in text
    assert "git diff " + "0" * 40 in text
    assert len(problems) == 3


def test_guide_flags_missing_section(tmp_path):
    help_dir = _guides(tmp_path, DE_GUIDE.split("## Aufnahmen")[0])
    sync = {"de": audit.english_blob_id(help_dir)}
    problems = audit.audit_guide("de", help_dir, sync=sync)
    assert problems and "missing ['recordings']" in problems[0]


def test_mark_help_synced_records_current_english(tmp_path):
    help_dir = _guides(tmp_path)
    sync_path = str(tmp_path / "help-sync.json")
    audit.mark_help_synced(["de"], help_dir=help_dir, path=sync_path)
    sync = audit.load_help_sync(sync_path)
    assert audit.audit_guide("de", help_dir, sync=sync) == []

    _write(tmp_path / "en.md", EN_GUIDE + "\nOne more English paragraph to translate.\n")
    assert any("mark-help-synced de" in p for p in audit.audit_guide("de", help_dir, sync=sync))
    with pytest.raises(SystemExit):
        audit.mark_help_synced(["de"], help_dir=help_dir, path=sync_path)


def test_upcoming_notes_include_the_new_release(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    _write(changelog, release._changelog_header() + "\n".join([
        "## v1.0.3 - 2026-01-03", "", "- Third", "",
        "## v1.0.2 - 2026-01-02", "", "- Second", "",
        "## v1.0.1 - 2026-01-01", "", "- First", "",
    ]))
    notes = "## Bug fixes\n- Fourth"
    upcoming = audit.upcoming_notes("1.0.4", notes, changelog_path=str(changelog))
    assert set(upcoming) == {"Fourth", "Third", "Second"}
    # The real CHANGELOG is only copied, never written.
    assert "Fourth" not in changelog.read_text(encoding="utf-8")


def test_notes_audit_and_prepare_notes(tmp_path):
    po = tmp_path / "fr" / "LC_MESSAGES" / "release_notes.po"
    _po(po, [("Old", "Ancien"), ("Empty", "")])
    problems = audit.audit_notes("fr", _messages("Old", "Empty", "New"), locale_dir=str(tmp_path))
    assert problems == ["fr: untranslated What's New bullet: 'Empty'",
                        "fr: untranslated What's New bullet: 'New'"]

    audit.prepare_notes(_messages("New"), languages=["fr"], locale_dir=str(tmp_path))
    entries = {e["msgid"]: e["msgstr"] for e in i18n_tools.parse_po(str(po)) if e.get("msgid")}
    assert entries == {"Old": "Ancien", "Empty": "", "New": ""}


def test_notes_audit_rejects_a_pasted_language_table(tmp_path):
    """v1.145.0 shipped bullets whose msgstr was a {lang: text} dict repr."""
    po = tmp_path / "de" / "LC_MESSAGES" / "release_notes.po"
    _po(po, [("Fix", "{'ar': 'x', 'de': 'Korrektur'}"), ("Ok", "Gut {name}")])
    problems = audit.audit_notes("de", _messages("Fix", "Ok"), locale_dir=str(tmp_path))
    assert problems == ["de: What's New bullet translated as a language table, not text: 'Fix'"]


def test_committed_notes_catalogues_hold_no_language_tables():
    for lang in audit.AUDITED_LANGUAGES:
        po = os.path.join(i18n_tools.LOCALE_DIR, lang, "LC_MESSAGES", "release_notes.po")
        if not os.path.exists(po):
            continue
        for entry in i18n_tools.parse_po(po):
            assert not audit._LANGUAGE_TABLE.match(entry.get("msgstr") or ""), (lang, entry.get("msgid"))


def test_release_audits_translations_before_touching_files(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["release.py", "release"])
    monkeypatch.setattr(release, "compute_next_version", lambda: ("v1.0.0", "1.0.1", [], "patch"))

    def fail(version, _notes):
        calls.append(("audit", version))
        raise SystemExit("untranslated")

    monkeypatch.setattr(release.translation_audit, "require_complete", fail)
    monkeypatch.setattr(release, "update_version_file", lambda *_args: calls.append("version"))
    monkeypatch.setattr(release, "update_changelog", lambda *_args: calls.append("changelog"))
    with pytest.raises(SystemExit):
        release.main()
    assert calls == [("audit", "1.0.1")]
