"""Pre-release translation audit for every shipped language except Hungarian.

``tools/release.py`` runs this before a release touches any file, and prints it
on ``dry-run``. A release stops while any audited language has:

* an application string (``iptvclient`` domain) that is missing, empty, a
  plain copy of the English text (unless listed in ``locale/identical_ok.json``)
  or drops a ``{placeholder}``;
* a user guide (``docs/help/<lang>.md``) whose sections, bullets or paragraphs
  differ from ``en.md``, that still contains English sentences, or that was
  last synced against an older ``en.md`` (``docs/help-sync.json``);
* an untranslated What's New bullet among the releases the new version will
  show (``release_notes`` domain), including the bullets of the release
  being built.

Hungarian is maintained by its own translator and is exempt by request.

    python tools/translation_audit.py                   # audit current state
    python tools/translation_audit.py prepare-notes     # add upcoming bullets to release_notes.po
    python tools/translation_audit.py mark-help-synced de fr   # after updating those guides
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TOOLS_DIR)
for _path in (REPO_ROOT, TOOLS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import i18n  # noqa: E402
import i18n_tools  # noqa: E402

EXEMPT_LANGUAGES = ("hu",)
AUDITED_LANGUAGES = tuple(c for c in i18n.SHIPPED_CATALOGS if c not in EXEMPT_LANGUAGES)
HELP_DIR = os.path.join(REPO_ROOT, "docs", "help")
HELP_SYNC_PATH = os.path.join(REPO_ROOT, "docs", "help-sync.json")
IDENTICAL_OK_PATH = os.path.join(i18n_tools.LOCALE_DIR, "identical_ok.json")

_HEADING = re.compile(r"^#{1,6} .*\{#([\w-]+)\}\s*$")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_WORD = re.compile(r"[A-Za-z]{3,}")


# --------------------------------------------------------------------------- #
# Application strings
# --------------------------------------------------------------------------- #
def load_identical_ok(path=IDENTICAL_OK_PATH):
    """Per-language msgids that may legitimately equal their English source."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {key: set(value) for key, value in data.items() if not key.startswith("_")}


def _placeholders(text):
    return sorted(_PLACEHOLDER.findall(text))


def audit_catalog(lang, messages, locale_dir=None, identical_ok=None):
    """Problems in ``lang``'s application catalogue against ``messages``."""
    locale_dir = locale_dir or i18n_tools.LOCALE_DIR
    identical_ok = load_identical_ok() if identical_ok is None else identical_ok
    allowed = identical_ok.get("*", set()) | identical_ok.get(lang, set())
    po = os.path.join(locale_dir, lang, "LC_MESSAGES", i18n_tools.DOMAIN + ".po")
    if not os.path.exists(po):
        return [f"{lang}: {os.path.relpath(po, REPO_ROOT)} is missing"]
    entries = {e["msgid"]: e for e in i18n_tools.parse_po(po) if e.get("msgid")}
    problems = []
    for msgid in sorted(messages):
        entry = entries.get(msgid)
        if entry is None:
            problems.append(f"{lang}: new string not in catalogue: {msgid!r}")
            continue
        if messages[msgid].get("plural"):
            forms = entry.get("plurals") or {}
            translated = [s for s in forms.values() if s]
        else:
            translated = [entry.get("msgstr", "")] if entry.get("msgstr") else []
        if not translated:
            problems.append(f"{lang}: untranslated: {msgid!r}")
            continue
        for text in translated:
            if text == msgid and msgid not in allowed and _WORD.search(_PLACEHOLDER.sub("", msgid)):
                problems.append(f"{lang}: still English: {msgid!r}")
            if _placeholders(text) != _placeholders(msgid):
                problems.append(f"{lang}: placeholders differ: {msgid!r} -> {text!r}")
    return problems


# --------------------------------------------------------------------------- #
# User guide
# --------------------------------------------------------------------------- #
def _read_lines(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n").split("\n")


def guide_structure(lines):
    """``[(anchor, bullets, paragraphs), ...]`` for each anchored section."""
    sections = []
    for line in lines:
        match = _HEADING.match(line)
        if match:
            sections.append([match.group(1), 0, 0])
        elif sections and line.strip():
            sections[-1][1 if line.lstrip().startswith("- ") else 2] += 1
    return [tuple(s) for s in sections]


def english_blob_id(help_dir=HELP_DIR):
    """Git blob id of ``en.md`` with LF endings, as stored in the repository."""
    with open(os.path.join(help_dir, "en.md"), "rb") as fh:
        data = fh.read().replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def load_help_sync(path=HELP_SYNC_PATH):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def audit_guide(lang, help_dir=HELP_DIR, sync=None):
    """Problems in ``docs/help/<lang>.md`` compared with ``en.md``."""
    path = os.path.join(help_dir, f"{lang}.md")
    if not os.path.exists(path):
        return [f"{lang}: docs/help/{lang}.md is missing"]
    en_lines = _read_lines(os.path.join(help_dir, "en.md"))
    lines = _read_lines(path)
    problems = []

    en_struct = {s[0]: s for s in guide_structure(en_lines)}
    struct = guide_structure(lines)
    anchors = [s[0] for s in struct]
    if anchors != list(en_struct):
        missing = [a for a in en_struct if a not in anchors]
        extra = [a for a in anchors if a not in en_struct]
        problems.append(f"{lang}: guide sections differ from en.md (missing {missing}, extra {extra}, or reordered)")
    else:
        for anchor, bullets, paragraphs in struct:
            _, en_bullets, en_paragraphs = en_struct[anchor]
            if (bullets, paragraphs) != (en_bullets, en_paragraphs):
                problems.append(
                    f"{lang}: guide section #{anchor} has {bullets} bullets/{paragraphs} paragraphs, "
                    f"en.md has {en_bullets}/{en_paragraphs}")

    english = {line.strip() for line in en_lines
               if len(_WORD.findall(_HEADING.sub("", line))) >= 4}
    for number, line in enumerate(lines, 1):
        if line.strip() in english:
            problems.append(f"{lang}: docs/help/{lang}.md:{number} is still English: {line.strip()[:70]}")

    sync = load_help_sync() if sync is None else sync
    current = english_blob_id(help_dir)
    synced = sync.get(lang)
    if synced != current:
        since = f"git diff {synced} {current}" if synced else "git log -p -- docs/help/en.md"
        problems.append(
            f"{lang}: en.md changed since docs/help/{lang}.md was last synced; "
            f"translate the changes ({since}), then run "
            f"'python tools/translation_audit.py mark-help-synced {lang}'")
    return problems


def mark_help_synced(languages, help_dir=HELP_DIR, path=HELP_SYNC_PATH):
    """Record that ``languages`` now match the current ``en.md``."""
    sync = load_help_sync(path)
    current = english_blob_id(help_dir)
    for lang in languages:
        structural = [p for p in audit_guide(lang, help_dir, sync={lang: current})]
        if structural:
            raise SystemExit("Refusing to mark as synced:\n  " + "\n  ".join(structural))
        sync[lang] = current
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(dict(sorted(sync.items())), fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# --------------------------------------------------------------------------- #
# Release notes
# --------------------------------------------------------------------------- #
def upcoming_notes(version=None, notes=None, changelog_path=None):
    """Release-note msgids What's New will show once ``version`` is released."""
    changelog_path = changelog_path or i18n_tools.CHANGELOG_PATH
    if version is None:
        return i18n_tools.extract_release_notes(changelog_path)
    import release  # tools/release.py; imported late, it pulls in app modules

    with tempfile.TemporaryDirectory() as tmp:
        staged = os.path.join(tmp, "CHANGELOG.md")
        shutil.copyfile(changelog_path, staged)
        release.update_changelog(version, notes, path=staged)
        return i18n_tools.extract_release_notes(staged)


def audit_notes(lang, messages, locale_dir=None):
    locale_dir = locale_dir or i18n_tools.LOCALE_DIR
    po = os.path.join(locale_dir, lang, "LC_MESSAGES", i18n_tools.NOTES_DOMAIN + ".po")
    have = {}
    if os.path.exists(po):
        have = {e["msgid"]: e.get("msgstr", "") for e in i18n_tools.parse_po(po) if e.get("msgid")}
    problems = [f"{lang}: untranslated What's New bullet: {msgid!r}"
                for msgid in sorted(messages) if not have.get(msgid)]
    # v1.145.0 shipped two bullets whose msgstr in every language was the
    # Python repr of a {lang: text} dict, which What's New then read out.
    problems += [f"{lang}: What's New bullet translated as a language table, not text: {msgid!r}"
                 for msgid in sorted(messages)
                 if _LANGUAGE_TABLE.match(have.get(msgid) or "")]
    return problems


# "{'ar': ..." / '{"de": ...': a whole per-language table pasted as one msgstr.
_LANGUAGE_TABLE = re.compile(r"""^\s*\{\s*['"][a-z]{2}(?:[_-][A-Za-z]{2})?['"]\s*:""")


def prepare_notes(messages, languages=AUDITED_LANGUAGES, locale_dir=None):
    """Add upcoming bullets to each ``release_notes.po``, keeping current ones.

    Leave the result uncommitted: the release's own sync keeps the
    translations and retires bullets that fall out of the window.
    """
    locale_dir = locale_dir or i18n_tools.LOCALE_DIR
    for lang in languages:
        po = os.path.join(locale_dir, lang, "LC_MESSAGES", i18n_tools.NOTES_DOMAIN + ".po")
        current = {e["msgid"]: {"plural": None, "locations": set()}
                   for e in i18n_tools.parse_po(po) if e.get("msgid")} if os.path.exists(po) else {}
        combined = dict(current)
        for msgid, info in messages.items():
            combined[msgid] = info
        i18n_tools.update_po(po, combined)


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def run_audit(version=None, notes=None, languages=AUDITED_LANGUAGES):
    """Every problem found, as a list of human-readable lines."""
    messages = i18n_tools.extract_messages(i18n_tools.SOURCE_FILES)
    identical_ok = load_identical_ok()
    sync = load_help_sync()
    note_ids = upcoming_notes(version, notes)
    problems = []
    for lang in languages:
        problems += audit_catalog(lang, messages, identical_ok=identical_ok)
        problems += audit_guide(lang, sync=sync)
        problems += audit_notes(lang, note_ids)
    return problems


def _utf8_stdout():
    # Messages quote translations; a legacy Windows console code page would
    # print them as replacement characters.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure and (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def report(problems, languages=AUDITED_LANGUAGES):
    _utf8_stdout()
    names = ", ".join(languages)
    if not problems:
        print(f"Translation audit passed for {names} (Hungarian exempt).")
        return
    print(f"Translation audit found {len(problems)} problem(s) in {names}:")
    for problem in problems:
        print(f"  - {problem}")


def require_complete(version=None, notes=None):
    """Raise ``SystemExit`` unless the audit passes; used by ``release.py``."""
    problems = run_audit(version, notes)
    report(problems)
    if problems:
        raise SystemExit(
            "Release stopped: finish the translations above first. "
            "For new What's New bullets run 'python tools/translation_audit.py prepare-notes', "
            "fill them in, and release without committing them.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", nargs="?", default="audit",
                        choices=["audit", "prepare-notes", "mark-help-synced"])
    parser.add_argument("languages", nargs="*")
    args = parser.parse_args(argv)
    languages = tuple(args.languages) or AUDITED_LANGUAGES
    unknown = [lang for lang in languages if lang not in AUDITED_LANGUAGES]
    if unknown:
        parser.error(f"not an audited language: {', '.join(unknown)}")

    if args.command == "mark-help-synced":
        mark_help_synced(languages)
        print(f"Marked docs/help/{{{','.join(languages)}}}.md as synced with en.md.")
        return 0

    version = notes = None
    if args.command in ("prepare-notes", "audit"):
        import release

        _tag, version, commits, _bump = release.compute_next_version()
        notes = release.build_release_notes(commits)
    if args.command == "prepare-notes":
        prepare_notes(upcoming_notes(version, notes), languages)
        print(f"Added the v{version} What's New bullets to release_notes.po; "
              "translate the empty entries and release without committing them.")
        return 0

    problems = run_audit(version, notes, languages)
    report(problems, languages)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
