# Review of seven proposed features and a focused comfort/accessibility extension

Follow-up: [local-live-buffer.md](local-live-buffer.md) describes the recovered local buffer and configurable sleep fade. The no-buffer/no-fade statements below describe the original #94 only.

Base: `b93181494a383df63017cb69c3a1fe5ce60b68d6` (v1.150.44), inspected 2026-10-27.

## What already exists

| Proposal | Evidence and practical boundary |
| --- | --- |
| Recurring/series recording | `dvr.py` schedules daily/weekly recurrence and scans series off-thread; `main.py::_refresh_series_recordings` matches the title on the same channel over the next 14 days. Duplicate start/channel jobs are avoided, but this is not episode-identity-based rerun suppression. The application must stay running. |
| Persistent film/episode resume | No stored bookmark/restore path found in the baseline. Added here for the built-in player and explicitly tagged `kind=movie` catalogue entries (including resolved series episodes). |
| Live pause and rewind | The built-in player exposes libVLC pause, and provider catch-up URLs are supported. No independent local rewind buffer or seek controller was found. NOT implemented by this extension. |
| Configurable accessibility announcements | `announcement_level` is normalized to 0..3 in `options.py`, exposed on both menu variants and propagated to the player; `_update_status_label` applies the priority threshold. This is a global level, not a separate switch for every event. |
| Customizable/searchable shortcuts | `shortcuts.py` validates main/player overrides and reserves help/ordinary typing. The guide has Find. The baseline editing list omitted configurable actions and had no query. This extension searches all actual command labels and current effective bindings. |
| Accessible privacy-conscious diagnostics | The menu and clipboard report existed, but `_copy_diagnostic_information` explicitly copied logs verbatim, including URLs/credentials. The sharing path is filtered here; original logs are preserved. |
| Sleep timer | No countdown was found. Added here to the built-in player. |

## Added behavior

### Sleep timer

Playback > Sleep Timer opens an accessible numeric entry: 1..1440 minutes; 0 cancels. Its displayed value is the remaining whole minutes (0 when inactive). Cancel leaves the current timer intact. A generation and monotonic deadline reject stale and early deliveries. Closing/quiescing the player cancels the outstanding delivery. The timer follows that built-in player window through subsequent channel changes; it stops only that player's playback through the existing manual-stop path, thereby suppressing automatic reconnect and clearing owned subtitle speech. It does not stop recordings, terminate external players, shut down the computer or change saved volume. No fade is claimed.

### VOD bookmarks

The main window explicitly configures the player with the live config/save callback. Before a catalogue launch, it captures the previous VOD position and derives the next identity only for explicit `kind=movie` items. It does not infer VOD from a filename extension or apply a live bookmark. Catalogue movies/episodes are now passed as `stream_kind=vod`, rather than accidentally taking live recovery behavior.

When an existing bookmark is present, the player asks whether to resume at the formatted time; No is the safe default and clears the old bookmark. An accepted offset is supplied to libVLC's media `:start-time` option before playback. No media-player rate is changed. Runtime progress is saved roughly every 30 seconds and on stop, source transition or close. Positions before 30 seconds and the final 5%/30 seconds are not offered. Unknown/invalid duration does not discard valid progress. Store normalization accepts only bounded integer times, hashes and timestamps, retaining the 200 newest entries. Raw media addresses and titles are not stored in this bookmark map. The full address and provider identify the hash; a changed address intentionally does not match.

A start-time seek that has not reached its target cannot overwrite the saved target. After 60 seconds of failed restoration, a status message reports the limitation and normal checkpoints can subsequently continue. This is not proof that every server/container is seekable. Native provider/VLC acceptance is required. External-player resume and catch-up resume are outside this patch.

### Searchable command editing

The shortcut editor now asks for a search term (leave empty for all), then lists every command from the existing canonical `LABELS`/effective binding maps. Search is case-insensitive against translated names and actual configured keys, with built-in-player rows identified. The existing conflict validation, F1 reservation, save and restart behavior remain in force.

### Shared diagnostics

`diagnostic_privacy.sharing_excerpt` redacts entire log lines carrying a URI scheme, obvious password/user/token/API-key assignments, authorization/cookie headers, MAC assignments or bearer credentials. Whole-line removal avoids preserving credential tails at unexpected quotes/spaces. Other lines are preserved. Filtering occurs only on the copied log excerpt, never the original log/config. This is a conservative best-effort filter for recognized forms, not a guarantee for arbitrary unlabelled secrets or personal data. Review any report before publishing it.

## What remains outside this patch

A real local live rewind buffer requires a bounded disk/segment store, a presentation clock, seek/live-edge controls, one-source ownership shared with recording/casting, header/session propagation, shutdown cleanup and subtitle clock/discontinuity handling. Ordinary libVLC pause and existing provider archives do not establish those guarantees. It would be misleading to label that complete based on pure Python timer tests. A separate native playback design/test effort is required.

Likewise episode-aware rerun suppression requires trustworthy programme/episode identifiers or an explicitly reviewed fallback policy. Per-event announcement switches are beyond the existing level selector. None is claimed as newly implemented.

## Acceptance and validation

- New deterministic tests cover invalid timer values, cancellation/replacement, stale/early expiry, actual dialog/stop wiring; bookmark normalization, consent, throttling, failed seek and live exclusion; and the real clipboard command's filtered copy.
- Existing DVR, VOD, shortcut, subtitle, i18n, guide, player, config and Debian tests are included in regression selection. See the accompanying Hungarian review for final counts and environment exclusions.
- Six new UI messages are supplied for all 13 shipped non-English catalogues; existing translations remain byte-for-byte text entries, with only additions appended. MO catalogues are rebuilt.
- New modules are static imports and included by the Debian all-root-Python packaging path. No third-party runtime dependency, CI gate, version bump or release change is introduced.
- `tests/test_playback_resume_native.py` is an opt-in generated-MP4/libVLC start-time smoke test (`IPTV_RUN_NATIVE_RESUME_TEST=1`), not a JAWS/NVDA, real provider or physical-audio test. Never report a skipped smoke test as success.
- Native Windows dialog focus/names with JAWS/NVDA; app restart and same-episode resume; non-seekable/changed URL providers; closing while buffering; recording plus sleep expiry; and installed/frozen package checks remain necessary before release.

English/Hungarian user-guide integration should follow maintainer acceptance; existing guide topic anchors and old translations are not rewritten here.
