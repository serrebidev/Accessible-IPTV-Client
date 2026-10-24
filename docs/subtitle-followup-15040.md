# Subtitle follow-up after v1.150.40

Review candidate based on `5a41b23a28b4c01e98558bb1cdf3dde769af1c63`.
This change has not been submitted, merged, released or tested on a physical
Windows audio device by this work session.

## Resulting behavior

The built-in player can send separately loaded ASS/SSA text through the same
file timeline, session ownership, review history and selected speech backend
already used for SRT/WebVTT. ASS event columns come from the Events Format
declaration. Dialogue text retains commas and Unicode, converts line/space
escapes, and removes override blocks, comments and vector drawing commands.
Karaoke syllables retain their words. Invalid or ambiguous events are skipped.
This is text extraction, not a replacement for libass visual typesetting.

Reloading an unchanged, previously verified file can retain its binding when
libVLC reuses that file's subtitle track ID. Both text and cue times must match,
the file URI must match and the old track must still exist. A different file,
changed cue timing, changed words, an unverified track or a stale worker cannot
inherit that proof. Freshly allocated track IDs still follow the existing
asynchronous selection checks. Ambiguous bindings remain unverified.

Python file reads stop at the existing 20 MiB limit plus one sentinel byte,
rather than reading an arbitrarily large file before rejecting it. This does
not claim to bound libVLC's independent native file handling.

Options > Subtitle Speech > Application voice speed opens a named, keyboard
accessible slider from -10 to +10, with 0 as normal. Only the private SAPI voice
changes. Successful choices persist in `subtitle_app_rate`; cancellation or a
failed COM write does not save a new value. Invalid saved values safely use
normal speed, and out-of-range integers are clamped. The next SAPI Speak stream
uses the new rate. Programme playback, JAWS/NVDA settings, independent volume,
output-device selection and missing-device policies retain their behavior.

The capability dialog translates the built-in player label without translating
its internal lookup key. New UI text is included in all 13 shipped catalogues,
with compiled MO files; all help guides describe the added formats and private
voice setting. Existing Hungarian translations outside the affected text are
preserved. No version, release workflow or CI exclusions are changed.

## Live subtitles: what the integration test proves

`tests/test_mpv_live_subtitles.py` creates a real, paced FFmpeg HTTP stream on
loopback, with chunked transfer and embedded text subtitles. Real MPV executes
the production Lua helper. Its messages traverse the actual adapter, bound
session and shared manager; a test callback records output instead of using a
physical speech device. Both SRT and styled ASS tracks are exercised.

The test asserts exactly one upstream GET, media-clock cue times, separate
history entries for identical consecutive words, collection while automatic
speech is initially off, and subsequent output after enabling it without
restarting playback. Timings allow the muxer's one-millisecond rounding. The
test has bounded process lifetimes and cleans up producers, HTTP server and
MPV. It skips explicitly when the required executables or loopback listener
are unavailable. It does not use a provider account or a second playback.

This validates and adds regression coverage for the existing MPV live-text
path. It does not implement built-in libVLC live caption decoding, prove every
provider's stream layout, or exercise production Windows named-pipe delivery.

## Validation

- Affected parser, speech, integration, pipeline, session, catalogue, help and
  translation selection: **265 passed, 12 skipped**. Both real live cases ran.
- Ruff and Python compilation passed. `git diff --check` passed.
- `tools.translation_audit.run_audit()` passed for every normally audited
  language. Hungarian catalogue consistency, placeholders and committed MO
  files are also covered by the tests. Its previously accepted extra help
  paragraphs remain; Hungarian is exempt from the release structure audit.
- Wider local regression run: **2243 passed, 157 skipped, 5 deselected** in
  54.03 seconds, with no failures in that selection. CI settings are unchanged.

The wider run excludes `tests/test_player_transport_gui.py`. An external local
harness skips fixtures named `wx_app` because the host has no native display.
The five deselected tests are:

- `test_internal_player.py::test_the_focus_leaves_the_audio_track_choice_before_it_is_disabled`
  (directly constructs native wx controls);
- `test_startup_lazy.py::test_config_read_candidates_do_not_create_user_config_dir`
  (unchanged Windows APPDATA assumption on Linux);
- `test_updater.py::test_update_helper_actually_starts_from_a_path_with_a_space`
  (the existing CI exclusion for native Windows PowerShell startup);
- `test_stream_proxy.py::test_the_proxy_handlers_are_daemon_threads`
  (unchanged listener address unavailable on this host);
- `test_epg_database.py::test_a_live_imports_lock_is_not_stolen`
  (the host PID-namespace limitation described below).

Neither the external headless harness nor those additional local exclusions
are part of this patch. Native platform/API and unavailable-device cases
account for the remaining explicit skips. Affected-suite skips were one
Windows-only language test and eleven GUI help tests.

Local host limitations include no native desktop, no AF_UNIX listener and no
Windows SAPI/named-pipe APIs. The host's PID namespace also makes
`psutil.pid_exists(os.getpid())` return false. Consequently the unchanged EPG
live-owner lock test fails here; neither its test nor `playlist.py` is changed.
This is not evidence of a subtitle regression, and it must still run in normal
Windows CI. A release build, physical endpoint delivery and screen-reader
acceptance are not covered by the local passing counts.

## Remaining boundaries and implementation requirements

| Area | Current position and required next implementation |
| --- | --- |
| Built-in embedded/live captions | Not implemented. libVLC 3's public subtitle controls do not supply decoded cue text. A decoder/bridge needs selected-track identity, a presentation clock and proven ownership. A separate upstream probe or hidden second player can break one-connection accounts. |
| Additional external players | Shared processing is reusable, but every integration still needs a reliable, documented clock/state and text interface. Player detection alone must not advertise working speech. |
| Bitmap subtitles | No OCR. DVB/PGS/VobSub pictures need a bounded OCR producer, language selection, confidence policy and frame-clock tests before being represented as text. |
| Simultaneous tracks and overlapping dialogue | The existing primary-track/latest-active-cue policy remains. ASS support does not introduce composition or simultaneous multi-voice reading. |
| Dense captions | Manual private-voice speed is implemented; automatic deadline estimation or rate adaptation is not. SAPI synthesis duration is not guaranteed by a character-count estimate. |
| MPV completeness | Idle snapshots cannot recover intermediate text that MPV has already coalesced. This is not a lossless broadcast caption recorder. |
| Audio hotplug and accessibility | Existing ownership/routing safeguards are preserved. Physical wired/USB/Bluetooth tests, JAWS/NVDA and frozen Windows builds still require native acceptance. |

Do not mark the broader subtitle backlog complete based on this patch. A useful
next built-in live implementation must demonstrate a single provider connection,
selected-track correspondence and clock alignment through buffering, pause,
seek, reconnect and discontinuities, then emit the existing SubtitleSnapshot
contract. Speech scheduling and device routing should stay centralized.

## Native acceptance before release

1. Run the repository's unchanged Windows checks on this exact revision.
2. Test Unicode ASS/SSA paths, drawing-only events, successive equal text,
   positive/negative offsets, pause, seek and late parser callbacks.
3. Reload an unchanged file on libVLC versions that reuse track IDs; then edit
   the same file's words/times, select an embedded track and reload again.
4. Use JAWS and NVDA separately to verify the rate slider's name/value, keyboard
   operation, F1 help, OK/Cancel, restored settings and unchanged reader speed.
5. Confirm rate, volume and endpoint settings remain independent, including a
   missing selected endpoint, approved fallback, reconnection and sleep/resume.
6. Test real provider live text with controlled MPV, initially disabled speech,
   track changes, buffering, reconnects and player replacement; verify no old
   caption or owned speech survives into the replacement session.

## Primary references

- [ASS file format guide](https://github.com/libass/libass/wiki/ASS-File-Format-Guide)
- [Aegisub override tags](https://aegisub.org/docs/latest/ass_tags/)
- [Microsoft SpVoice Rate](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms723606(v=vs.85))
- [libVLC 3 video/subtitle controls](https://videolan.videolan.me/vlc-3.0/group__libvlc__video.html)
- [MPV manual](https://mpv.io/manual/stable/)
