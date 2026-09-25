# Subtitle speech: technical audit and implementation proposal

**Project:** Accessible IPTV Client  
**Reviewed release:** v1.142.1  
**Source commit:** d45e5cd50a299eb810761f136f3505c3ddeeba97  
**Review date:** 25 September 2026  
**Status:** Prepared for maintainer review; not submitted. No production code changes or subtitle speech implementation are included.

## 1. Executive assessment

The current implementation supports subtitle track selection, an Off option, cycling with S, and loading an external subtitle file. It does not contain a path that obtains timed subtitle text and delivers it to an accessibility or speech backend. Track descriptions are metadata, not the sentences currently displayed.

The maintainer's response on issue #4 states that reliable subtitle speech could not be provided with the current player. The source supports a specific architectural explanation: the application delegates subtitle decoding and rendering to libVLC, while its Python layer only manages track identifiers and media slaves. Its accessibility notifications announce player status, not subtitle cues. The public LibVLC 3.x functions used here do not supply decoded cue text. [R1, R2, S1, S2]

This review found no evidence identifying the maintainer's earlier experiments or their measured failure modes. It would therefore be inappropriate to attribute the limitation to a particular failed implementation, poor performance, or developer error. The defensible conclusion is that cue acquisition and timed speech are absent from the reviewed application path.

A useful first implementation is feasible in principle without replacing the player: explicitly selected local SRT/WebVTT files can be parsed separately, synchronized to the media clock, exposed as accessible text, and spoken through a tested output adapter. This is an engineering proposal, not an implemented or validated solution. Embedded and live broadcast subtitles require additional extraction and timing work. No claim of universal subtitle support is justified.

Several nearby reliability issues should also be addressed. Most significantly, a catch-all subtitle menu handler can consume commands that it does not own, and subtitle errors do not trigger the application's explicit alert event at the default announcement level.

## 2. Scope, evidence and limits

The review covered internal_player.py, the relevant main.py announcement and player creation paths, shortcuts.py, requirements.txt, main.spec, the English and Hungarian help additions, and tests/test_issue4_player.py. Existing audio-track restoration, playback recovery, teardown and provider connection handling were examined as integration constraints.

Evidence categories used below:

- **Source-confirmed:** directly visible in the pinned release.
- **Probe-confirmed:** executed unchanged method bodies with controlled wx/libVLC substitutes.
- **Integration inference:** predicted from source plus framework documentation; still needs a native application test.
- **Proposal:** a design to implement and validate.

Five repeatable probes are provided in subtitle_audit_probes.py. They require only the Python standard library and extract methods from the adjacent source checkout. All five passed when characterising the current behaviour. A passing probe here means that the documented limitation was reproduced; it does not mean the application passed a subtitle speech acceptance test.

The review environment has no wxPython, python-vlc, Windows desktop, JAWS or NVDA runtime. No native GUI dispatch, actual speech, provider stream, latency, resource-usage or packaging test was performed. The maintainer's published release test counts are not results of this audit.

## 3. Current execution path

| Stage | Existing implementation | Consequence |
| --- | --- | --- |
| Discover tracks | _subtitle_tracks calls video_get_spu_description | Returns identifiers and names; no cue text. |
| Select a track | _select_subtitle calls video_set_spu | Selects what VLC renders. |
| Cycle or disable | _cycle_subtitle includes track ID -1 | Controls visual subtitle selection. |
| Load an external file | _load_subtitle_file passes a file URI to add_slave | VLC receives the file; the application does not parse or retain its cue timeline. |
| Update accessibility status | _update_status_label updates wx.StaticText and may raise an alert | Announces status under a verbosity policy; it is not a timed caption pipeline. |
| Announce programme information | main._show_playing_info uses the same player status object when visible | A future subtitle implementation must avoid competing with this channel. |

The video panel is a rendering surface. Drawing subtitles into its pixels does not, by itself, create an accessible text object. Reading a track name or firing an additional alert cannot fill the missing cue-acquisition stage.

The reviewed Python binding targets the LibVLC 3.x API family. Its minimum version requirement does not establish the actual native libVLC version installed on a user's machine. Record both versions in any prototype results. Do not prescribe an unverified upgrade to VLC 4, a private VLC structure, or a hypothetical subtitle-text callback. [S1, S2]

## 4. Findings and proposed corrections

### F1 — No decoded subtitle text or timed-cue model

**Source-confirmed; architectural prerequisite.** See internal_player.py:2179–2242. No subtitle parser, decoder output adapter, cue start/end model, language-specific speech route, or subtitle speech scheduler is present.

**Recommendation:** establish an explicit CueSource boundary. For the first delivery, support a declared subset of local text subtitles. Keep the existing VLC visual rendering path. Expose source availability independently from whether VLC lists a subtitle track.

Do not substitute speech recognition for subtitle access without a separate, explicitly selected feature. Speech recognition would generate a transcript of audio, which may differ substantially from supplied subtitles.

### F2 — A catch-all subtitle menu handler consumes unowned events

**Source- and probe-confirmed at handler level; native dispatch impact is an integration inference.** _build_menu_bar binds both audio and subtitle selectors to EVT_MENU without a source or ID restriction. _on_subtitle_menu_select returns without Skip when an ID is absent from its map. The audio selector has the same missing continuation. See internal_player.py:462–505, 2224–2227 and 2262–2265.

wx stops searching for a handler unless the invoked handler calls Skip. Consequently, an unowned event reaching the subtitle handler is consumed. Its binding can interfere with audio-track selection and other earlier-bound menu commands; actual dispatch order and affected commands should be checked in native wxPython. This should be treated as a potential regression associated with the new subtitle handler, not as proof that all menu commands fail. [S3]

**Recommendation:** bind generated menu items to their own handlers, with suitable cleanup when rebuilding menus, or call event.Skip() and return for every unowned ID in both handlers. A minimal illustrative correction is:

```python
track_id = self._subtitle_menu_map.get(event.GetId())
if track_id is None:
    event.Skip()
    return
self._select_subtitle(track_id)
```

Apply the equivalent ownership rule to audio-track events. Test Play/Pause, Stop, Record, audio-device selection, both track submenus, and commands forwarded from the main window. The snippet is a proposed change, not an applied or GUI-tested patch.

### F3 — Subtitle failures are assigned the detailed-status priority

**Source- and probe-confirmed.** _update_status_label defaults to priority=3. Both subtitle-selection and external-file failures call it without an override. Announcement levels 1 and 2 therefore suppress the explicit alert event, although the status label changes. The ordinary default is level 2. The successful file-load message also uses priority 3. See internal_player.py:1735–1763, 2190–2199 and 2229–2242.

This proves suppression of this explicit notification path, not silence in every screen reader: a screen reader might separately react to a label change.

**Recommendation:** use priority 1 for failures. Use priority 2 for deliberate selection/load confirmations, or define an explicit user-command feedback policy distinct from automatic verbosity. Test that policy at every level, including None, and document whether requested feedback remains available.

### F4 — The Off announcement can use VLC's untranslated name

**Source- and probe-confirmed.** The subtitle menu constructs a translated Off choice. After selection, however, _select_subtitle first looks up ID -1 in VLC's descriptions. A returned name such as Disable wins over the translated fallback. The probe reproduces an English Off-status label despite providing a Hungarian translation.

**Recommendation:** for track ID -1, choose the application's translated Off string directly. Preserve provider-supplied track names for actual language tracks. Cover both menu and keyboard selection.

### F5 — The status label is unsuitable as a continuous subtitle speech queue

**Source-confirmed behaviour; prospective integration risk.** _update_status_label appends buffer, bitrate, volume and audio-track information, retains the last prefix, suppresses identical complete labels, and gates alerts by priority. Passing cues through this method would mix dialogue with technical status and inherit unsuitable deduplication and verbosity rules.

main._show_playing_info also targets this object and uses SetName for the player case, while ordinary status updates use SetLabel. The resulting accessible name/label interaction must be inspected on Windows; no specific JAWS or NVDA failure is asserted here.

**Recommendation:** use a dedicated, stable accessible subtitle text control plus a separate delivery adapter. A status notification is not a guarantee of speech onset, completion, cancellation or intelligibility. wx.Accessible.NotifyEvent exposes an accessibility event; it does not provide those speech lifecycle guarantees. [S4]

### F6 — Subtitle source and selection have no restoration policy

**Source-confirmed omission; reconnect outcome requires playback validation.** The external file path exists only as a local variable in _load_subtitle_file. A subsequent play operation constructs and installs a new media object. Audio selection has explicit reapplication logic; subtitle selection and external subtitle files do not have an equivalent application-owned restoration path.

**Recommendation:** store subtitle source identity and the user's selection separately from transient libVLC IDs. On a same-programme reconnect, restore only when identity and timing alignment are still valid. On a genuine channel/programme change, clear unrelated external subtitles. Never assume that a numeric track ID keeps its meaning across media instances.

### F7 — Missing speech lifecycle and timing guarantees

**Source-confirmed absence for the proposed feature.** The existing 500 ms status timer is designed for playback monitoring. A cue can begin and end between samples. get_time can be unavailable or move backwards; the existing playback watchdog already accounts for such cases. Shutdown deliberately coordinates VLC work away from the GUI thread.

**Recommendation:** implement cue scheduling and cancellation explicitly. Pause, buffering, seeking, reconnecting, track changes, stopping and destruction must each have defined behaviour. Hidden-window and video-disabled playback are distinct cases: the latter sets :no-video and must not be assumed to preserve subtitle decoding.

### F8 — Current tests do not establish usable subtitle speech

**Source-confirmed.** tests/test_issue4_player.py checks decoded track names and notification-level filtering. Its subtitle test does not exercise cue extraction, track-selection dispatch, timed speech, external-file lifecycle, or assistive-technology output.

**Recommendation:** retain those tests, add focused regressions for F2–F4, and use the acceptance matrix below for the new feature. Mocked alert counts must not be used as evidence that JAWS or NVDA actually spoke a cue.

## 5. Support boundaries by subtitle type

| Input | Suggested route | Delivery boundary |
| --- | --- | --- |
| Local SRT / standalone WebVTT | Parse the user-selected file into a normalized timeline; keep VLC rendering it | Recommended first scope; validate encodings and timing. |
| Local ASS/SSA | Use a suitable parser; preserve dialogue and remove presentation commands safely | Later or explicitly limited support; drawing and karaoke constructs need a policy. |
| Embedded text subtitles | Demux/decode the selected stream through a tested adapter | Separate engineering milestone; metadata enumeration is insufficient. |
| HLS WebVTT renditions | Fetch permitted subtitle segments and map their timestamps to the media timeline | Requires segment deduplication, discontinuity handling and live-window tests. |
| Teletext or CEA captions | Use a format-specific decoder capable of obtaining text | Handle service/page selection, character sets and incremental updates. |
| DVB/PGS/VobSub bitmap subtitles | Bitmap decoding, then optional OCR if desired | No guaranteed text extraction; OCR quality and delay must be disclosed. |
| Burned-in subtitles | Optional image-based OCR | No separate subtitle stream; keep outside the first implementation. |
| No subtitles | Report that no supported subtitle source is available | Do not claim that speech recognition is equivalent. |

FFmpeg's subtitle representation distinguishes image data, plain text and ASS data. That makes it a candidate component for an extraction adapter, not a promise that every subtitle format can be converted to text losslessly. Select and test the deployed codec/build combination. [S5]

HLS subtitle timing must account for X-TIMESTAMP-MAP, segment-spanning cues and MPEG timestamp wrap. Do not align live captions merely by adding the wall-clock time when playback started. [S6]

## 6. Recommended architecture and behaviour

### 6.1 Separate acquisition, timing, presentation and speech

Use testable components with explicit ownership:

1. **CueSource:** supplies source/track identity, capability information and timed cue records. A record should include a media-session generation, discontinuity epoch, cue identity, start/end media timestamps, language and normalized text.
2. **PlaybackClock:** reports media position, state and rate, plus seeks, source changes and discontinuities. Handle unknown positions; convert units explicitly, including VLC subtitle delay in microseconds versus playback time in milliseconds. [S2]
3. **CueScheduler:** determines active cues and schedules delivery against media time. It does not perform network I/O, parsing or speech calls inside the GUI timer.
4. **AccessibleSubtitleView:** retains current text and a bounded review history in keyboard-accessible controls. Updating it must not move focus or reset the user's reading position.
5. **SpeechAdapter:** reports availability and capabilities, and accepts bounded requests. Its support for cancellation, interruption and completion must be explicit rather than assumed.

These names describe interfaces to introduce, not modules that already exist.

### 6.2 First implementation: local text subtitles

Retain the selected absolute file path in a media-session object. Read and parse it asynchronously with bounded file/cue sizes and a documented encoding fallback. Validate timestamps, multiline cues, Unicode, overlapping intervals and malformed records. Keep original subtitle content separate from normalized text intended for speech.

For WebVTT, handle cue identifiers, settings and markup. For ASS/SSA, do not speak formatting overrides or vector drawings as dialogue. Avoid a broad regular expression that silently removes legitimate text. Preserve speaker information and meaningful sound descriptions according to a documented user preference.

Synchronize with actual playback position, including the selected subtitle offset. For valid local/VOD timelines, a short timer or deadline-based scheduler can sample the media clock; a proposed initial 100–200 ms sampling range requires measurement under load. Check cue boundaries crossed since the previous sample rather than only testing whether a cue happens to be active at the instant of polling. Discard expired material according to policy.

Do not claim arbitrary live-stream support for a local subtitle file: a reliable correspondence between the file timeline and the live media clock may not exist. If alignment cannot be established, explain that limitation.

### 6.3 Queue, deduplication and interruption

Default to opt-in speech. Keep application-side pending work bounded; a reasonable starting policy is the current cue plus at most one eligible successor. This is a proposed policy to validate with users, not an established optimum.

Deduplicate using session, track, timeline epoch and cue identity, not text alone. The same words at a later timestamp must still be spoken. Incremental live captions need a separate policy so that repeatedly extended lines are not read in full on every update.

Do not enqueue a whole subtitle file in the screen reader. Drop stale pending cues, avoid replaying a backlog after a stall, and never solve queue growth by cancelling all screen-reader speech on every tick. A bounded application queue does not bound a screen reader's internal queue if the adapter is fed faster than it can speak. When completion/busy information is unavailable, restrict outstanding delivery, use a documented conservative pacing policy, and expose that limitation; do not promise exact completion-based scheduling.

Menu navigation, dialogs and explicit user commands must remain intelligible. Define how subtitle speech yields while the user interacts. Cancellation APIs can affect speech from other applications; do not present them as cue-specific cancellation unless the backend guarantees it.

### 6.4 Media lifecycle and worker ownership

On source, track or programme changes, increment a session generation and reject delayed work from earlier generations. On seek, clear pending speech and recompute active cues. On pause or buffering, stop advancing the queue; decide explicitly whether already-started speech may finish. On resume, announce the current relevant cue without draining missed content.

On reconnect, re-establish clock alignment before resuming. On Stop and destruction, invalidate callbacks, stop timers, signal cancellation and join workers with a bounded policy. Integrate with _quiesce and the existing VLC teardown rather than making blocking speech or decoder calls on the GUI thread.

Marshal GUI updates with wx.CallAfter or an equivalent GUI-thread mechanism and check session/lifetime validity when the queued callback executes. If a speech backend uses COM, initialise and dispose its objects on the appropriate owning thread. A VLC callback must not perform GUI work or block on synthesis.

### 6.5 Live extraction and provider connection limits

Do not open a second full provider stream solely to obtain subtitles without considering account limits. The application already has exclusive-stream handling and recording-relay paths. Evaluate whether subtitle extraction can share a single demux/input or an appropriately designed local relay.

The presence of an existing relay does not prove it preserves every subtitle stream or provides synchronized multi-consumer access; inspect and test it before reuse. Preserve the necessary subtitle packets, stream IDs and timestamp relationships. Separate HLS subtitle-rendition requests have their own authentication and provider-policy implications.

Keep provider headers, cookies and redirects consistent with the authorised playback session. Use bounded buffers and backpressure so that a slow decoder cannot destabilize playback or recording. Do not attach raw subtitle text or credential-bearing URLs to new audit telemetry by default; propose any diagnostic-policy change explicitly to the maintainer.

## 7. Speech and accessibility output options

**Dedicated accessible text:** provide this regardless of speech backend. It enables reading, copying and braille review without requiring a particular synthesizer.

**Windows UI Automation notifications:** evaluate a valid provider and notification event path. UIA offers processing preferences, but consumer behaviour and actual speech timing still need testing. A bare event on an arbitrary object is not a complete integration. [S7, S8]

**NVDA controller client:** offers documented communication for speech and braille. Probe supported functions and failures in the deployed version; do not assume development-branch capabilities are present in every installed NVDA. [S9]

**JAWS and other screen readers:** evaluate a maintained adapter against the supported versions. Tolk is one public reference implementation covering JAWS and NVDA, but its documented driver matrix does not provide speaking-status support for those drivers. It therefore cannot be assumed to solve timed queue management. Validate binary architecture, redistribution requirements, thread model, interruption scope and failure reporting before adopting it. [S10]

Choose one automatic speech route at a time. Simultaneously issuing UIA speech notifications and direct controller speech risks duplicate output. A visible accessible text control should remain available without automatically announcing the same cue twice.

A standalone text-to-speech engine may be an optional fallback. Explain that it may use a different voice and audio device from JAWS/NVDA. Do not silently enable another voice. Test Hungarian accents and punctuation using the user's actual speech configuration; do not promise exact voice equivalence.

Windows-first delivery is a defensible scope if clearly labelled. Linux and macOS require their own accessibility/speech adapters and testing. A Windows-only DLL must not become an unconditional import on other platforms.

## 8. User controls and localisation

Provide keyboard-accessible controls for enabling speech, choosing its supported source, reading the current cue, repeating the previous cue, reviewing recent subtitles and stopping subtitle speech. Expose the selected language/source and a clear unsupported/unavailable state. Resolve keyboard conflicts through the existing shortcut framework.

Define whether speech follows the visible subtitle track. For the first version, following the selected track and treating Off as speech off is the simplest policy. If independent visual and spoken tracks are later supported, expose them as separate choices.

Keep automatic subtitle speech separate from the general player-status verbosity setting. Otherwise Errors only can unintentionally silence the entire feature. Distinguish automatic dialogue from requested confirmation and failure feedback.

Translate UI labels and app-generated errors through gettext. Do not translate programme dialogue automatically or force it into the UI language. A Hungarian interface can legitimately play an English or another-language subtitle track.

The accompanying Hungarian translation accurately states that subtitle text is not currently spoken. Do not remove that limitation from any guide until the feature meets its acceptance criteria. Add new interface strings and help consistently across supported languages.

## 9. Verification and acceptance matrix

| Area | Minimum scenarios | Required observation |
| --- | --- | --- |
| Existing menu regression | Audio/subtitle items, Play/Pause, Stop, Record, audio device | Exactly the intended handler runs; unowned events continue. |
| Failures and confirmations | Invalid track, missing/malformed file, successful load; all verbosity levels | Feedback matches the documented policy; no unexplained silence. |
| Parsing | UTF-8/BOM, Hungarian accents, legacy encoding, CRLF, multiline, malformed, overlap | Correct bounded cue model; readable errors; no GUI stall. |
| Timing | Short cues, consecutive cues, long gaps, changed rate, positive/negative offset | Correct cue order, explicit units, measured drift and late-cue policy. |
| Deduplication | Identical words at different times, overlapping HLS segments, rolling captions | Repeated content is handled by cue identity and update policy. |
| State changes | Pause, seek both ways, buffering, reconnect, channel/track change, Off | No old-session speech; no backlog on resume. |
| Output | JAWS and NVDA separately, both installed, reader restart/absence, muted speech | One delivery route; intelligible navigation; graceful failure. |
| Focus and visibility | Menus/dialogs open, player hidden/fullscreen, video disabled | No focus theft; clear background policy; tested source availability. |
| Source coverage | Local text, embedded text, live VTT, bitmap, no subtitles | Honest support detection; no claim that every track contains text. |
| Provider/load | Restricted account, recording relay, long session, reconnect loop | No unintended second media session; bounded memory/CPU/queue. |
| Shutdown | Close/Stop while parsing, fetching or speaking | No blocked window, use-after-destroy callback or orphan worker. |
| Packaging | Actual Windows build; other-platform startup | Matching dependencies and architectures; no mandatory unavailable backend. |

Use deterministic cue fixtures and a controllable clock for unit tests. Test source adapters independently, then run local media integration tests before live-provider trials. A real GUI test must exercise wx event dispatch rather than invoking handlers directly.

Record time from cue eligibility to adapter submission separately from audible onset and completion. Report median and tail latency, dropped/expired cues, queue size, CPU and memory. Establish performance thresholds with user testing; this audit supplies no measured latency claim.

For Hungarian acceptance testing, use JAWS 2026 with the user's Hungarian voice configuration and the user's installed NVDA version. Confirm exact versions in the test record. Speech Viewer/logs and event inspection can help diagnosis but do not replace listening and keyboard-use trials.

## 10. Delivery plan and decision gates

1. **Correct existing reliability issues:** fix event ownership, feedback priorities and the localized Off status. Add regressions and run native menu tests.
2. **Prove the smallest complete path:** one local SRT/WebVTT source, correct media-clock synchronization, an accessible text view and one selected speech backend. Test with JAWS and NVDA before broadening scope.
3. **Stabilize interaction and lifecycle:** bounded delivery, navigation coexistence, repeated cues, seeks, failures, reader restarts, shutdown and packaging.
4. **Expand by source type:** add embedded text and live sources only after extraction, timestamp mapping and provider connection constraints are demonstrated. Treat bitmap/OCR support as a separate optional project.

Each milestone should publish its support boundary. Do not make the already-completed Hungarian translation dependent on delivering universal subtitle speech. The maintainer specifically suggested a separate focused issue for this feature; this audit can form its design brief without reopening the twelve-item roadmap.

## 11. Reproducing the audit probes

From the reviewed repository root:

```text
python translation_package/subtitle_audit_probes.py
```

The script reads internal_player.py and executes selected unchanged methods with explicit substitutes for wx and libVLC. It creates no real media file, launches no GUI, sends no speech, and contacts no service. It checks:

1. An unowned subtitle-menu event is not skipped.
2. Subtitle-selection failure produces no explicit alert at levels 1 or 2.
3. External-file failure produces no explicit alert at levels 1 or 2.
4. External-file success produces no explicit alert at default level 2.
5. A VLC-provided Disable name overrides the translated Off label.

Observed result: five tests passed. These are characterization probes and should be converted into desired-behaviour regression tests when fixes are implemented. They are not a replacement for the application's native test suite.

## 12. References

Repository links are pinned to the reviewed commit. Upstream documentation was consulted on 25 September 2026; where it tracks a development branch, validate the deployed release before implementation.

- **R1:** [Maintainer response on issue #4](https://github.com/serrebidev/Accessible-IPTV-Client/issues/4#issuecomment-5824664175).
- **R2:** [Subtitle handling and adjacent player code](https://github.com/serrebidev/Accessible-IPTV-Client/blob/d45e5cd50a299eb810761f136f3505c3ddeeba97/internal_player.py#L2179-L2265).
- **R3:** [Player status and alert path](https://github.com/serrebidev/Accessible-IPTV-Client/blob/d45e5cd50a299eb810761f136f3505c3ddeeba97/internal_player.py#L1735-L1763).
- **R4:** [Menu bindings](https://github.com/serrebidev/Accessible-IPTV-Client/blob/d45e5cd50a299eb810761f136f3505c3ddeeba97/internal_player.py#L462-L505).
- **R5:** [Existing subtitle/announcement tests](https://github.com/serrebidev/Accessible-IPTV-Client/blob/d45e5cd50a299eb810761f136f3505c3ddeeba97/tests/test_issue4_player.py).
- **R6:** [Programme-information announcement target](https://github.com/serrebidev/Accessible-IPTV-Client/blob/d45e5cd50a299eb810761f136f3505c3ddeeba97/main.py#L2251-L2264).
- **S1:** [VideoLAN: LibVLC 3 video controls](https://videolan.videolan.me/vlc-3.0/group__libvlc__video.html).
- **S2:** [python-vlc: MediaPlayer API](https://python-vlc.readthedocs.io/en/latest/api/vlc/MediaPlayer.html).
- **S3:** [wxPython: event processing](https://docs.wxpython.org/events_overview.html#how-events-are-processed).
- **S4:** [wxPython: Accessible.NotifyEvent](https://docs.wxpython.org/wx.Accessible.html#wx.Accessible.NotifyEvent).
- **S5:** [FFmpeg: AVSubtitleRect](https://ffmpeg.org/doxygen/trunk/structAVSubtitleRect.html).
- **S6:** [RFC 8216, section 3.5: WebVTT timing](https://www.rfc-editor.org/rfc/rfc8216#section-3.5).
- **S7:** [Microsoft: UiaRaiseNotificationEvent](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationcoreapi/nf-uiautomationcoreapi-uiaraisenotificationevent).
- **S8:** [Microsoft: NotificationProcessing](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationcore/ne-uiautomationcore-notificationprocessing).
- **S9:** [NV Access: Controller Client API](https://github.com/nvaccess/nvda/blob/master/extras/controllerClient/readme.md).
- **S10:** [Tolk: interface and driver capabilities](https://github.com/dkager/tolk).
