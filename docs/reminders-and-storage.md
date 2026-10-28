# Programme reminders and recording-storage preflight

This independent change builds on v1.150.48 after PR #100 was merged. The VOD library is already part of the base and is not resubmitted.

## Reminders

Set Reminder is available on future EPG rows in the channel guide, What's On Now and main-window programme search results. Lead time is 0–120 minutes (default 5, zero = programme start). Records are keyed by a hash of the source/channel identity and absolute UTC start. Adding the same slot updates it rather than duplicating it. The Recordings menu opens the keyboard-operated reminder manager with local start time, title, channel, status and lead minutes, Enter/edit, Delete, confirmed Clear All and Refresh.

The independent `programme-reminders.json` store is bounded to 500 records. Atomic unique-file/fsync/replace commits update memory only after success; a failed write preserves both prior memory and disk contents. A malformed/unreadable store is reported and never automatically overwritten as empty. Stored channel identities are hashed and titles are bounded/sanitized; no media URL, credentials or whole channel snapshot is persisted. This separate store is not included in the existing encrypted settings export.

The GUI timer checks approximately every five seconds while the app is running, including the tray. It does not launch the app or wake a suspended computer. A restart/resume can deliver a due programme that has not ended; ended programmes expire without a stale-notification burst. Wall-clock changes re-evaluate absolute UTC deadlines; local date/time is presentation only. EPG changes are deliberately not fuzzy-matched: users must replace a reminder if the broadcaster changes its scheduled slot.

Delivery waits behind both the shared modal guard and other native modal dialogs, including the existing EPG dialogs. A due record is durably marked ready before showing; acknowledgement is persisted after closing. An in-process seen set prevents repeated popups if acknowledgement fails. Restarting after an interrupted/unacknowledged display may show it again while the programme is still running; exactly-once delivery across a crash is not claimed. Automatic storage errors are throttled and repeated failures in one unresolved episode are logged rather than repeatedly displayed.

The reminder dialog defaults to Close. Opening a channel requires explicit consent and one unambiguous match in the current playlist, including HTTP headers; saved URLs are never replayed. Existing playback, casting and provider connection restrictions still apply. A normal vetoable exit warns about pending reminders. Forced system/update exit bypasses the question but retains durable future entries. Reminder edits/removal do not alter DVR recording jobs or media files. No recurrence, automatic recording, automatic channel switching or provider-side schedule tracking is implied.

## Recording storage

`RecordingManager.start` performs the destination check before acquiring a live-buffer recording lease, reserving the output filename, creating recording logs or launching FFmpeg. The same entry point covers manual recordings, scheduled jobs and recorder-backed catch-up downloads. Existing upstream metadata/audio probes can still happen before this engine entry point.

The check creates/opens the actual output directory, tests a tiny write/flush/fsync in an owned temporary file, closes/removes that file and queries free bytes using the filesystem API. It fails closed for invalid/unavailable/non-directory/read-only destinations and unknown/invalid free-space results. Low space raises a translated error; no recording is registered or phantom DVR ID returned. DVR failures follow existing failure/reporting semantics; they are not silently queued for unlimited retry.

The configurable pre-start floor is 0–65536 MiB, default 256. Equality is accepted; zero disables only the numerical floor, not writeability or free-space querying. Invalid config values use the default. The manager serializes concurrent starts through preflight and registration, but this is **not a reservation of a complete recording's size**. Unknown duration/variable bitrate, unrelated writers, active captures and the live buffer make such a guarantee impossible. There is no automatic deletion, continuous free-space monitor, post-start reserved floor or bitrate-based duration prediction. The checked absolute destination is used for the actual start.

Check Recording Storage performs the same check on a worker, displays the actual directory/free MiB/policy and does not open a media stream. Late results after shutdown do not display a new popup. Native operations on a disconnected network filesystem can still be delayed by the OS; no hard I/O deadline is claimed. Direct capture startup retains its existing calling-thread behavior.

## Localization and validation

All 25 new UI strings are present in the 13 translated application catalogues with compiled MO files. Existing v1.150.48 translations are preserved. Hungarian help describes lead-time semantics, manager actions, application lifetime, crash/redelivery and storage limitations. The final Hungarian terminology uses “Értesítés kérése műsorkezdés előtt…” and “Értesítések műsorkezdés előtt”. Existing help topic IDs are retained.

The accompanying validation report records final automated results. Native Windows/frozen/JAWS/NVDA/real-provider and real external/network/removable-drive acceptance remains required. No CI exclusions, audit gates or capability checks are relaxed.
