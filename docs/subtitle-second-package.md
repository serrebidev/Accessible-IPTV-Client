# Second subtitle package: robust files and live MPV buffering

Tested on top of PR #87 commit `62d3e1c0ccc4c4e35fbb12dd45c70ce2e93d0070`.
This is an incremental implementation; the ASS/SSA, verified same-file reload,
private SAPI rate and translated resources from the first package are retained.

## Reproduced problems and changes

1. WebVTT NOTE blocks containing timing examples were parsed as dialogue.
   Header, NOTE, STYLE and REGION blocks now stay out of spoken cues. A timing
   line must be first or follow one identifier. Header recognition is specific
   to WebVTT; an SRT identifier named NOTE still works. Legacy short fractions
   and comma/dot timing forms remain accepted. This is a speech-oriented parser,
   not a complete CSS/layout validator or a live MPEG-TS timestamp-map decoder.
2. Invalid minutes/seconds, enormous numeric components and signed-64-bit clock
   overflow are rejected per event. One malformed cue no longer discards valid
   subsequent dialogue. ASS drawing-mode numbers are checked without converting
   an arbitrarily long integer. Repeated unmatched markup openers no longer
   cause quadratic scans. An unfinished ASS override is not read as commands;
   an unclosed HTML-like fragment remains literal text, including mathematical
   comparisons. Normal styling, entities, Unicode and karaoke words remain.
3. BOM-declared UTF-16/UTF-32 files are decoded directly, without charset
   guessing; the longer UTF-32 marker is checked first. The existing bounded
   20 MiB read and legacy-codec fallback remain. This does not guess arbitrary
   BOM-less UTF-16 or guarantee recovery of damaged text.
4. Active-cue lookup used a linear backward scan with an arbitrary one-hour
   cutoff. A still-active earlier cue could disappear behind expired overlays.
   The shared file source now builds a maximum-end interval index and uses
   logarithmic time queries. Latest-started/tie selection, review, delays, gaps,
   paused input and backward-seek generation behavior stay the same; this does
   not introduce simultaneous multi-track or overlapping-dialogue composition.
5. The built-in file worker prepares sorting, validation and indexing before
   UI delivery. The GUI adopts only matching cues/generation, without rebuilding
   the index. Obsolete workers check ownership before reading, after parsing
   and before delivery. Existing late-callback and SPU-binding checks remain.
6. MPV's `paused-for-cache` state now participates in the existing shared pause
   contract. A network-induced pause suppresses new automatic speech and purges
   application-owned output through the bound session, while retaining manual
   review. Cache recovery cannot override an explicit user pause. An unchanged
   caption is not automatically repeated on recovery. Starting a new file also
   waits for `playback-restart` before accepting its current subtitle text.

No playback-rate, buffering configuration, provider connection, recording,
casting, device-selection policy, voice-volume/rate preference, translation,
version, release or repository CI configuration changes are included.

## Verification

- Final affected file/session/voice/MPV selection: **276 passed, 2 skipped**.
  Those two skips were real-player prerequisites absent from that command's
  PATH; the subsequent wider run used the available real executables.
- Final wider local Linux run: **2315 passed, 157 skipped, 5 deselected** in
  68.73 seconds, no failures in that selection.
- The three generated live HTTP/MPV cases ran: embedded SRT, styled ASS and SRT
  with a deliberately injected two-second delivery blackout. The real player
  reported a cache pause; the test checks no new speech during that pause,
  later caption output, all three timed history entries and one upstream GET.
  All three passed (also independently: **3 passed** in 22.26 seconds).
- Lua-harness tests execute the production helper, adapter, shared manager and
  bound session for cache pause, explicit pause, pending-output cancellation,
  owned-voice purge, source replacement and manual review.
- Real file tests cover declared Unicode encodings, malformed numeric fields,
  metadata examples, long broken markup, supported ASS/SSA input and two equal
  captions retaining separate history timestamps. Existing first-package
  reload, private-rate, output routing and parser regressions also ran.
- A deterministic oracle compares indexed lookup against brute force across
  1500 overlapping cues and 503 query positions; a 100,000-cue case covers a
  long-lived cue behind expired overlays. No timing threshold gates CI.
- One local synthetic benchmark at 100,000 cues measured about 13.4 ms per
  linear query versus 0.007 ms per indexed query, with an approximately 80 ms
  index build on a worker. These figures describe that adversarial fixture and
  host, not whole-application speed or a universal hardware guarantee.
- Ruff, Python compilation, the existing translation audit and whitespace
  checks passed. There are no new runtime dependencies or user-facing strings.

The wider run omits `tests/test_player_transport_gui.py`. An external local
harness skips fixtures named `wx_app` because no native desktop is available.
It deselects these unchanged host-dependent tests:

- `test_internal_player.py::test_the_focus_leaves_the_audio_track_choice_before_it_is_disabled`
  (direct native GUI construction);
- `test_startup_lazy.py::test_config_read_candidates_do_not_create_user_config_dir`
  (Windows APPDATA assumption on Linux);
- `test_updater.py::test_update_helper_actually_starts_from_a_path_with_a_space`
  (the existing Windows CI exclusion);
- `test_stream_proxy.py::test_the_proxy_handlers_are_daemon_threads`
  (unavailable local listener address);
- `test_epg_database.py::test_a_live_imports_lock_is_not_stolen`
  (this host reports `psutil.pid_exists(os.getpid()) == False`).

The harness and additional local exclusions are not committed or added to CI.
Other skips retain their explicit native API, hardware or external-tool reasons.
No Windows CI result for the first package is represented as a result for this
new commit. Native Windows GUI, JAWS/NVDA, physical SAPI/audio routing, full
production named-pipe delivery and packaged release acceptance are still needed.

## Live television support boundary

The implemented live path is the application's controlled MPV session with a
selected text subtitle track exposed by MPV. The real test source is generated
locally; it does not prove every provider, HLS rendition, teletext service or
broadcast codec. MPV idle observations can coalesce intermediate text and are
not a lossless subtitle recorder. Bitmap tracks remain explicitly unavailable
for speech. No additional provider connection or hidden playback is introduced.

Built-in VLC stream-embedded/live text extraction and bitmap OCR are still not
implemented. Python can orchestrate native decoders and OCR engines; the
missing piece is a proven producer supplying correctly owned selected-track
text or subtitle image regions with presentation timing. The current Python
libVLC interface does not itself provide that producer. This package neither
labels whole-frame OCR as exact caption decoding nor advertises universal
player support. It leaves the outstanding native integration work open.

## Delivery and release acceptance

Apply this after the exact first-package revision above. The prepared update
adds one commit to the existing PR #87, preserving the first package and its
description. It must refuse a different branch head rather than overwrite
intervening developer changes. It does not merge or release the application.

Before release, rerun the unchanged Windows gate on the updated head and check
large Unicode files, pause/manual review, seek/delay changes, same-file reload,
track replacement and late-worker retirement. For real live providers, check
buffering, track changes, reconnects, manual pause during buffering and source
switches. Include both output backends and the physical endpoint matrix from
the first package. Retaining history during a cache pause does not authorize
automatic replay of every caption that was missed while stalled.

References: [W3C WebVTT](https://www.w3.org/TR/webvtt1/),
[MPV manual](https://mpv.io/manual/stable/) (`paused-for-cache`, `playback-restart`).
