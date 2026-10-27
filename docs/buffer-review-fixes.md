# Follow-up to the two findings on PR #96

Base: main `79127e1add1c06e2e186072fe9d825095154967a` (v1.150.45), after the squash merge of #96. This follow-up addresses [scheduled recording startup](https://github.com/serrebidev/Accessible-IPTV-Client/pull/96#discussion_r4392494549) and [cold-start HLS bitrate preference](https://github.com/serrebidev/Accessible-IPTV-Client/pull/96#discussion_r4392494560). It does not replay or overwrite #94/#96.

## Scheduled buffered recording

The early-return guard for an advisory media probe was mistakenly in `_start_scheduled_recording`. DVR treats a normal callback return as success, so buffered channels and pending transitions could leave a phantom recording without an ID or output.

Move the guard to `_probe_channel_media_now`, where skipping work is intentional. A ready buffered source now continues through format classification, the local audio-probe cursor and `RecordingManager`'s existing lease path. Provider occupancy checks, output format/audio selection and recording finalization remain intact. If a source transition is already pending when a scheduled callback begins, raise a localized startup failure before probing or opening another input. The existing DVR exception path marks that occurrence failed, retains an explanation, clears its recording ID and applies the existing recurrence policy. This patch does not silently reschedule the failed occurrence or claim recovery of a missed programme.

Regression tests call the production GUI recording callback through the actual DVR worker. A real generated finite TS segment is served by `LiveBufferSession` and recorded through the actual `RecordingManager`/FFmpeg; the test verifies local probe/input URLs, DVR recording ID, returned output path, successful process exit and nonempty file. A separate pending-transition test verifies failed status, explanatory message, no recorder start and no output. Advisory-probe tests cover both pending and already-owned sources.

## Saved bitrate cap before player construction

Resolve a copy of the saved config with the existing `resolve_internal_player_settings` on the GUI thread, before starting the ingest worker. Capture that normalized cap; if a usable frame already exists, its current cap remains authoritative. Pass the captured value to the existing HLS selector. No wx/libVLC construction is introduced before buffering, and the worker does not normalize/mutate the live config.

Cold-start wiring tests start with no player frame, exercise numeric/string caps, disabled/invalid/negative values and both clamping bounds, inspect the actual session-start argument and verify that the original config is unchanged. A live-frame preference test verifies that runtime settings retain precedence. The existing HLS selection and native buffer-duration tests remain in the regression suite.

## Localization, validation and limits

One new startup-failure message is translated in all 13 shipped application catalogues, including reviewed Hungarian, with corresponding MOs rebuilt. Existing help, UI translations, playback rates, dependencies, CI exclusions and release/version files are unchanged. Local validation is documented below. Native Windows/libVLC, real-provider behavior and JAWS/NVDA acceptance remain release responsibilities; no native Windows execution is claimed here.

The regressions were first run against the unmodified #96 head: nine failed and five passed (the two recording cases and seven saved-cap cases failed). The corrected targeted selection then passed 72 tests with two existing skips, including the real scheduled-buffer recording. New test parameters have short values/IDs; no large payload is embedded in a pytest node ID.

## Recorded validation

- Broad local regression on main 701872c9 plus this fix: 2519 passed, 162 skipped, 5 deselected in 60.29 seconds (Linux, Python 3.12.14). Repository CI/test gates are unchanged.
- Targeted DVR, scheduled buffered callback, buffer ownership, cap and audio-track tests: 72 passed, 2 skipped. New regressions first failed on unchanged #96 code (9 failed, 5 passed), before applying the fix.
- Real FFmpeg regression verifies the production GUI callback through the actual DVR worker, local buffer HTTP input, actual RecordingManager recording, valid DVR ID/output path and nonempty recorded file. Pending transitions persist failed status and a message without starting a recorder or creating output.
- Cold-start cases cover numeric/string, disabled/invalid/negative and both clamping bounds, with no pre-existing frame and unchanged source config. Existing-frame runtime preference remains authoritative; existing HLS selector coverage remains in the broad suite.
- Ruff and git diff --check pass. All 13 application catalogue audits are clean; MO/PO correspondence is covered by the broad suite. Existing help and release-note files are unchanged. Upcoming release-note preparation remains the maintainer's release workflow; no completeness gate is bypassed.
- Local environment exclusions: an uncommitted headless harness skips wx_app fixtures; tests/test_player_transport_gui.py is not collected. Five local deselections concern native GUI focus, Windows config directories, Windows updater execution, unavailable host network interface and PID-namespace behavior. Remaining skips are repository platform/optional dependency conditions. No skip, harness or CI exemption is added to the repository.
- Native Windows/libVLC/JAWS/NVDA/provider acceptance and an installed/frozen build were not run here. The patch does not claim automatic retry or recovery of a failed scheduled occurrence.

- PowerShell 7 submission harness: 10 cases passed (normal draft creation, resume after branch creation, repeat, closed PR, wrong account, changed main, changed branch tree, API denial, mismatched blob, mismatched created tree), plus nonenumerated empty-array and embedded-payload integrity checks. Temporary paths include spaces/Unicode. PowerShell 5.1-compatible syntax is retained, but native Windows PowerShell was not executed here.

### Release-base reconciliation

The first submitter stopped before any upload because main advanced to the v1.150.45 release. Rebase this follow-up onto that release. Reconstruct each of the 13 conflicted application PO files from the exact new main version, adding only the one new failure message; then rebuild MOs. Preserve release notes, version, changelog and all prior translations. Neither affected runtime module changed in the release. Repeat validation and regenerate the expected tree/base guards.

### Validation after release reconciliation

- Broad local regression on v1.150.45 main 79127e1a plus this fix: 2519 passed, 162 skipped, 5 deselected in 58.09 seconds (Linux, Python 3.12.14). Repository CI/test gates are unchanged.
- Targeted DVR, scheduled buffered callback, buffer ownership, cap and audio-track tests: 72 passed, 2 skipped. New regressions first failed on unchanged #96 code (9 failed, 5 passed), before applying the fix.
- Real FFmpeg regression verifies the production GUI callback through the actual DVR worker, local buffer HTTP input, actual RecordingManager recording, valid DVR ID/output path and nonempty recorded file. Pending transitions persist failed status and a message without starting a recorder or creating output.
- Cold-start cases cover numeric/string, disabled/invalid/negative and both clamping bounds, with no pre-existing frame and unchanged source config. Existing-frame runtime preference remains authoritative; existing HLS selector coverage remains in the broad suite.
- Ruff and git diff --check pass. All 13 application catalogue audits are clean; MO/PO correspondence is covered by the broad suite. Existing help and release-note files are unchanged. Upcoming release-note preparation remains the maintainer's release workflow; no completeness gate is bypassed.
- Local environment exclusions: an uncommitted headless harness skips wx_app fixtures; tests/test_player_transport_gui.py is not collected. Five local deselections concern native GUI focus, Windows config directories, Windows updater execution, unavailable host network interface and PID-namespace behavior. Remaining skips are repository platform/optional dependency conditions. No skip, harness or CI exemption is added to the repository.
- Native Windows/libVLC/JAWS/NVDA/provider acceptance and an installed/frozen build were not run here. The patch does not claim automatic retry or recovery of a failed scheduled occurrence.
- PowerShell 7 submission harness: 10 cases passed (normal draft creation, resume after branch creation, repeat, closed PR, wrong account, changed main, changed branch tree, API denial, mismatched blob, mismatched created tree), plus nonenumerated empty-array and embedded-payload integrity checks. Temporary paths include spaces/Unicode. PowerShell 5.1-compatible syntax is retained, but native Windows PowerShell was not executed here.
- Release reconciliation: all prior application msgstr/plural forms match the exact v1.150.45 base; only the one new failure message is added. Both runtime-module diffs match the previously tested fixes exactly. Changelog, app version, release notes and template updates from the release are retained.
