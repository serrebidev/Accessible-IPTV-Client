# Hungarian translation review and subtitle speech audit

Prepared for maintainer review alongside the Hungarian translation changes.

## Proposed maintainer cover note

Hello,

Thank you for the additions in v1.142.1 and for clarifying the current limitation on speaking subtitle text.

This pull request contains the reviewed Hungarian translations for the new interface strings, help additions and release notes, together with a technical audit of subtitle accessibility. The translation work preserves the previously existing Hungarian text.

The application catalogue now covers 61 new strings: the 56 entries introduced in the release catalogue and five additional messages from shortcuts.py that were missing from extraction. Both new release-note entries are translated, and the Hungarian help additions have been checked against the implementation.

The audit explains the missing timed-text path, documents nearby reliability issues, and proposes a staged implementation with explicit support boundaries. It includes five reproducible probes and a test matrix. It does not claim that subtitle speech has already been implemented or verified with JAWS or NVDA.

There are also a few integration tasks for text that currently bypasses gettext. They are listed below with the completed Hungarian translations. The production Python files have not been changed.

The translation changes and the subtitle speech proposal can be reviewed separately. Subtitle speech would fit the focused follow-up issue suggested in your response to issue #4.

Thank you for considering the review.

## Pull request contents

- docs/help/hu.md: complete Hungarian guide with the reviewed additions.
- docs/help-sync.json: the Hungarian synchronization stamp is updated.
- locale/hu/LC_MESSAGES/iptvclient.po and iptvclient.mo: source and compiled application catalogue.
- locale/hu/LC_MESSAGES/release_notes.po and release_notes.mo: source and compiled release-note catalogue.
- translation_package/SUBTITLE_SPEECH_AUDIT.en.md: English technical audit, recommendations, evidence and references.
- translation_package/subtitle_audit_probes.py: standard-library characterization probes; run in a checkout of the reviewed release.
- translation_package/hu-v1.142.1-review.md: Hungarian review record.
- translation_package/README.en.md: this cover note and integration instructions.

## Applying the translations

Reviewed translation base: v1.142.1, commit d45e5cd50a299eb810761f136f3505c3ddeeba97. The pull request also includes the upstream main branch's subsequent test-only commit. For a later release, review the changes against its current catalogues and help. Do not overwrite newer translations or replace other languages' synchronization stamps.

The two MO files have been rebuilt from their corresponding PO files. Catalogue coverage, placeholders, duplicate IDs, preserved existing translations and guide structure were checked. The five subtitle probes are supplementary audit evidence; they are not a native application acceptance suite.

ffmpeg.exe and unrelated workspace changes are excluded.

## Translation integration tasks

### 1. Include shortcuts.py in extraction

The five added messages already use gettext, so their translations can be looked up in the supplied catalogue. However, shortcuts.py is missing from tools/i18n_tools.py's SOURCE_FILES list. Add it before the next catalogue regeneration, otherwise the additional entries can be dropped.

For the conflict message, {command} currently receives a transformed internal action ID such as “play pause”. Supply the corresponding localized command label, with the correct main-window/player context, instead of displaying the internal identifier.

### 2. Localize backup errors

settings_backup.py raises the following text directly. Route its own messages through gettext and include the module in extraction. The first translation already exists in the main application catalogue; the other six are supplied here for integration.

| Source text | Reviewed Hungarian text |
| --- | --- |
| A backup password is required. | Adja meg a biztonsági mentés jelszavát. |
| Settings are too large to back up. | A beállítások mérete meghaladja a biztonsági mentés megengedett felső határát. |
| Backup file is too large. | A biztonsági mentés fájlmérete meghaladja a megengedett felső határt. |
| Not an Accessible IPTV settings backup. | A kiválasztott fájl nem az Accessible IPTV Client beállításainak biztonsági mentése. |
| Invalid backup salt. | A biztonsági mentéshez tartozó kriptográfiai só érvénytelen. |
| Wrong password or damaged backup. | A jelszó hibás, vagy a biztonsági mentés sérült. |
| Backup settings are invalid. | A biztonsági mentés érvénytelen beállításokat tartalmaz. |

Underlying operating-system and dependency exceptions may still contain their own language. Translating the application's wrapper does not translate arbitrary exception detail.

### 3. Localize file-filter labels

The text labels below are currently hardcoded. Preserve all wildcard patterns and the literal vertical-bar separators.

main.py, settings export/import:

```text
Source: Accessible IPTV backup (*.aiptv)|*.aiptv
Hungarian: Accessible IPTV biztonsági mentés (*.aiptv)|*.aiptv
```

internal_player.py, external subtitle loading:

```text
Source: Subtitle files (*.srt;*.ass;*.ssa;*.vtt)|*.srt;*.ass;*.ssa;*.vtt
Hungarian: Feliratfájlok (*.srt;*.ass;*.ssa;*.vtt)|*.srt;*.ass;*.ssa;*.vtt
```

### 4. Stored DVR message

The newly added stored message “Series recording canceled.” has the reviewed translation “Az azonos című műsorok felvételi ütemezése visszavonva.”

No direct presentation site was identified for that stored message in the reviewed interface. If exposed later, localize at presentation rather than rewriting persisted job data into a language-specific value.

### 5. Two help corrections

The Hungarian additions intentionally follow the code where the English guide is imprecise:

- Load Subtitle File is a separate command in Playback, not inside the Subtitles submenu.
- Record Daily, Record Weekly and Record Series are offered on programme context menus in the guide/What's on Now, rather than the Scheduled Recordings list's context menu.

Please consider corresponding English-source corrections. The Hungarian guide's heading anchors and structural counts still match the reference.

## Subtitle audit handling

Read SUBTITLE_SPEECH_AUDIT.en.md before treating any proposal as an implementation commitment. The report distinguishes confirmed source behaviour, controlled probes, integration inferences and future designs.

The audit's small code example is illustrative. No application logic was patched, no release was built, and no live screen-reader test was performed. A separate focused issue or implementation branch would allow the subtitle work to proceed without delaying the reviewed translation.
