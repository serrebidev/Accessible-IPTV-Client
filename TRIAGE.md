# Bug Triage Report

**Date**: 2026-10-20
**Repository**: Accessible-IPTV-Client
**Scope**: the whole application, not one module.

The previous report (2026-02-01) is gone. Every finding in it had been fixed
long ago - the lambda closure over `e`, the unbound `conn`, the optional
casting imports, the unused variables - and its "no formal test suite found"
was already wrong: the suite has ~1970 tests.

## First pass: the update and casting paths

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| BLOCKER | `updater.py` | the Authenticode pin was read from the update manifest, which travels with the release | a release signed with *any* certificate was accepted, so whoever could publish one could install and elevate their own code |
| SEVERE | `stream_proxy.py` | the header gateway sent the channel's credentials to whatever host the request named | the provider's cookie went to any host that reused the token from a cast URL |
| SEVERE | `update_helper.ps1` | the rollback only restored the backup when the install directory was gone | a failed move left the app uninstalled and the working version sitting in the `.bak` folder |
| SEVERE | `main.py`, `internal_player.py` | a queued notification could outlive its window, and a destroyed wx object raises on every call | the Cast error box could take the app down with `RuntimeError: wrapped C/C++ object of type Frame has been deleted` |
| MINOR | `update_helper.ps1` | a timed-out installer was left running | the app restarted into the directory the installer was still writing to |
| MINOR | `internal_player.py` | the HLS variant probe was a blocking HTTP GET on the GUI thread | up to two seconds of frozen window and silent screen reader when opening a channel |
| MINOR | `recorder.py`, `main.py` | `stop()` did nothing when the recording id no longer resolved | a scheduled recording kept running past its end and was reported as a stop timeout |

## Second pass: the rest of the application

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `main.py` | the "Speak subtitles" toggle called `self.save_config()`, which is not a method of the frame | the menu item popped a Python error dialog, the setting was never written and the toggle did nothing |
| SEVERE | `main.py`, `internal_player.py`, `playlist.py` | the boxes the player and the playlist dialogs opened bypassed the modal guard | a recording that finished during one of them opened a second box inside the first one's message loop, and the main window stayed disabled for good |
| SEVERE | `playlist.py` | a date whose UTC conversion overflows raised `OverflowError`, which the parse did not catch | one bad programme aborted the whole source: a five programme guide imported as zero channels |
| SEVERE | `options.py` | every config writer used the same fixed temp name | the GUI thread and the playlist worker saved over each other, the loser failed with "being used by another process", and the setting was silently lost |
| MINOR | `main.py` | the catch-up lookup swallowed every database error | a locked or corrupt EPG database was reported as "no catch-up programmes are available" |
| MINOR | `providers.py` | a rejected portal token stayed cached for 25 minutes | playlist, stream, catch-up and account info all failed with 401 until the app was restarted |
| MINOR | `providers.py` | a wrong Xtream password answers with HTTP 200 and a body that is not a playlist | the playlist loaded empty, with no message at all |
| MINOR | `options.py` | an unreadable config was not kept before the first save overwrote it | the user's playlists and favourites were unrecoverable |
| MINOR | `options.py` | the cache folder was created without a guard | a read-only config folder failed every playlist refresh with a raw "Permission denied" |

## Third pass: the scheduler and the interface

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `dvr.py` | the hourly series scan ran inside the scheduler tick | the scheduler could not tick while it ran: a recording that came due started late, and one whose window passed was marked as missed and never recorded |
| SEVERE | `main.py` | a failed or missed scheduled recording was never reported | the job record kept the reason and nobody saw it: the recording simply never appeared |
| MINOR | `main.py` | quitting waited for the recorder on the GUI thread | the still-visible window froze for up to half a minute per recording ("Not Responding") |
| MINOR | `main.py` | the Scheduled Recordings dialog selected row 0 and took the focus on every refresh | a screen-reader user browsing the schedule lost their place whenever a recording started or finished |
| MINOR | `main.py` | the EPG import's refresh of the row labels was swallowed by the 30 s throttle | the app said the guide was up to date while the rows still showed the previous programme |
| MINOR | `main.py` | the "is the EPG database usable" check scanned the whole programme index on the GUI thread | a fraction of a second of silent window every time the check ran |

### The EPG usability check, measured

The check is `SELECT 1 FROM programmes p JOIN channels c ON c.id = p.channel_id
WHERE p.end > ? LIMIT 1`, and no index can seek `end`: the covering index leads
with `start`. Measured on a synthetic guide (400 000 programmes, the indexes the
app creates):

| | bulk insert | database | the check |
|---|---|---|---|
| as it is | 19.9 s | 77.3 MB | 0.078 s |
| with an index on `end` | 20.2 s | 86.2 MB (+11%) | 0.000 s |

So the finding is real but smaller than it looked: at the size of a real guide
it is a fraction of a second, not a multi-second freeze - and an index would
buy that fraction for eleven percent more disk on a database that is already
large, plus a slower import. The check is therefore not indexed; its answer is
cached against the database file's size and mtime instead, so it runs once per
guide change and every later call is free.

Every fix has a regression test that fails without it.

## Fourth pass: the capture, subtitle and support modules

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `main.py`, `internal_player.py` | the built-in player's cues never reached the speech manager, and they carried no timing | "Read current subtitle" and "Review recent subtitles" always answered "No subtitle text available yet." for the app's own player, and two consecutive lines with the same text were merged - the second was never spoken |
| SEVERE | `account_info.py` | the report printed the server URL as it stood | a pasted Xtream URL can carry the password in it, and the report is read aloud, copied to the clipboard and pasted into issue trackers |
| SEVERE | `catchup_direct.py` | the direct-file probe followed redirects, and the channel's credentials followed the redirect target | the probe fetched the programme's stream as media and held the account's one stream, and the provider's cookie went to whatever host the server named |
| SEVERE | `i18n.py` | the language value from the config was used as a string without checking | `"language": 5` in a hand-edited config raised `AttributeError` while the frame was starting: no window at all, and in the windowed build, silence |
| SEVERE | `mpv_subtitle_adapter.py` | the adapter's connect and version request allowed five and four seconds, on the GUI thread | pressing Enter with MPV selected froze the window - and silenced the screen reader - for as long as the handshake took |
| MINOR | `external_player.py` | the launch debounce used the wall clock | a backwards clock step left the debounce permanently open: the player refused to start until the app was restarted |
| MINOR | `power.py` | the shutdown command was the bare name | Windows resolves the current directory before System32, so a `shutdown.exe` next to the app was executed instead of the real one, with the user's privileges |

## Fifth pass: the locks, the recorder and the subtitle session

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| BLOCKER | `stream_proxy.py` | the cleanup loop held the proxy's lock and called the gateway expiry, which took that same non-reentrant lock again | ten seconds after the proxy started, the cleanup thread wedged for good with the lock held, and every converter, playlist and segment request blocked: casting died |
| SEVERE | `providers.py` | the portal token lock was taken twice by the same thread when the portal answered 401 or 403 | a wrong MAC or an expired trial hung the thread for good instead of reporting that the portal could not be reached |
| SEVERE | `playlist.py` | `<length units="minutes">inf</length>` raised `OverflowError` out of the per-programme handler | one bad programme aborted the whole source, so every programme after it in that feed was dropped |
| SEVERE | `main.py` | the deferred cast-failure box used the player frame without probing it first | the player was closed while the box waited, and the callback raised `RuntimeError: wrapped C/C++ object of type Frame has been deleted` |
| SEVERE | `recorder.py` | the shutdown path killed ffmpeg after a flat five seconds instead of the size-derived finalize budget | quitting during a multi-gigabyte MP4 left `ftyp` + one enormous `mdat` and no moov atom: unplayable, with the whole capture stranded inside it |
| MINOR | `main.py`, `subtitle_speech.py` | the built-in player never cleared the shared subtitle manager, and a speech queued before the switch was still spoken | "Read current subtitle" and "Review recent subtitles" answered with the last line of the channel the user had just left |
| MINOR | `options.py` | a config write that failed during serialization left its temp file behind | one `iptvclient.conf.*.tmp` per failed save |
| MINOR | `power.py` | the shutdown command was hard-coded to `C:\Windows\System32` | the machine did not power off when Windows was installed on another drive |
| MINOR | `internal_player.py` | the fullscreen button's label changed but its accessible name did not | NVDA announced "Toggle Full Screen" on a button that said "Exit Full Screen" |

### The two deadlocks

Both were the same mistake: a `threading.Lock` taken twice by the same thread.
`StreamProxy._cleanup_loop` holds the lock and calls `_expire_gateway_sessions`,
which takes it again; `StalkerPortalClient._ensure_token` holds the token lock
across `_portal_call`, which takes it again on a 401/403. In both cases the
second acquisition waits for a lock the same thread already holds, so the
thread waits for itself. The tests missed both because the inner method was
called directly in one case, and because no test drove a rejected portal token
in the other. Both locks are `RLock` now.

### The shutdown budget

The same file stopped the same way got two different budgets: the normal path
waited `finalize_timeout_seconds` (30 s plus the file's size at 8 MiB/s, so
more than ten minutes for a 5 GB MP4), and the shutdown path waited five
seconds. A faststart MP4 rewrites the whole file when it finalizes, so the
shutdown path killed ffmpeg mid-rewrite - exactly the failure the other path
was written to prevent. The shutdown budget is now
`max(DETACH_WAIT_SECONDS, finalize_timeout_seconds(...))`, and the
terminate/kill escalation still guarantees that no ffmpeg is left holding a
provider's one stream slot.

## Sixth pass: the updater, the dialogs and the schedule file

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `updater.py` | the `GITHUB_TOKEN` from the environment was attached to every request, including the download URL the release manifest names | the user's own GitHub credential was sent to whatever host an (unsigned) manifest pointed at |
| SEVERE | `main.py` | Enter on a programme in "What's on Now" was handled by the list's `EVT_KEY_DOWN`, which a dialog never delivers | pressing Enter on a programme did nothing at all: the dialog takes Enter first, and the Play button is not a native default button |
| SEVERE | `dvr.py` | a non-numeric timestamp in the schedule file was read outside any `try` | the value raised out of the scheduler's constructor, so the app did not start |
| SEVERE | `update_helper.ps1` | the helper killed whatever held the app's PID | the app exited and Windows handed that PID to another program, which was then killed with it |
| MINOR | `updater.py` | the PowerShell path fell back to the bare name `powershell.exe` | Windows resolves the current directory before System32, so a `powershell.exe` next to the app would run instead - with the user's privileges, during an update |
| MINOR | `catchup_direct.py` | the host comparison was case-sensitive | a provider whose name differed only in case lost the channel's cookie and answered 403 |
| MINOR | `options.py` | the write probe used one fixed file name | two writers probing the same folder collided, and the loser decided the folder was not writable - which sent the config somewhere else |
| MINOR | `stream_proxy.py` | issuing a gateway URL replaced the session's host set | a redirect the provider had taught the proxy about lost the channel's credentials |
| MINOR | `playlist.py` | the final `wal_checkpoint(TRUNCATE)` was not drained | the statement stayed in progress, so the WAL was not truncated |
| MINOR | `settings_backup.py` | a damaged backup raised the JSON parser's own error | the import box said "Expecting value: line 1 column 1 (char 0)" instead of what to do about it |

### Enter in a dialog

A `wx.Dialog` consumes Enter before the focused control sees an
`EVT_KEY_DOWN`, so a list inside one has to take Enter from the char hook -
the catch-up list and the scheduled-recordings list already do. The
"What's on Now" list was the last one still on the key-down, and its Play
button is not a native default button: its Win32 style carries no
`BS_DEFPUSHBUTTON`, so wx had nothing to press instead.

### The one parameter name

PowerShell 5.1 silently ignores a named argument that matches no
parameter: `Get-ParentAppProcess -Id $pid` bound nothing and left the
parameter at 0, so the helper read the *Idle* process (PID 0) instead of
the app. The parameter is named to match its call sites now, and the
reused-PID guard compares the process's start time with the helper's.

## Seventh pass: the scheduler and the caster

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `dvr.py`, `main.py` | starting a recording ran inside the scheduler tick | the tick could not run while it did: a recording that came due started late, and one whose window passed was marked missed and never recorded - the same class the fifth pass removed from the series scan |
| SEVERE | `casting.py` | the AirPlay runner reopened a live source without looking at ffmpeg's exit code | a cast to a source that failed (a 403 from the provider) reported success, and ffmpeg was respawned every second for good, holding the provider's stream slot |

The start now claims the job and hands the blocking work to a worker, so
the tick keeps running; the job is claimed before the worker starts, so a
second tick cannot start it twice, and a cancel during the start is still
caught by the check that stops the abandoned recording.

The AirPlay runner now reads ffmpeg's exit code before it reopens. A clean
end is a drop and is reopened at the live edge; an error exit is a source
that failed and ends the cast. A source that ends again straight away was
never working, so a few of those end it too.

## Eighth pass: the right-clicked row, and the values nobody checks

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `main.py` | the programme lists built their context menu from the selected row, and a right-click does not move the selection | the user pointed at one programme and the app played, recorded or deleted another |
| SEVERE | `main.py`, `catchup_direct.py` | the catch-up download handed ffmpeg the channel's cookie for the direct archive file, which can live on another host | the provider's credential went to whichever host the provider redirected to |
| SEVERE | `playlist.py` | a duration with a huge component was converted without a guard, and `int()` refuses one | the refusal escaped the per-programme loop: the whole guide was dropped over one programme |
| MINOR | `stream_proxy.py` | ffmpeg was taken from the current working directory | Windows resolves the current directory first, so an `ffmpeg.exe` that happened to sit there ran instead of the real one, with the user's privileges, on every transcode |
| MINOR | `vod.py` | an episode number, a season number and a category name were used as they came | one broken value from the provider took the whole episode list - or the whole catalogue - with it |

The channel list has always hit-tested the row the user pointed at; the
programme lists did not, and a right-click in a list control does not move
the selection. The three list controls now hit-test too, and a
multi-selection keeps its selection when the right-clicked row is part of
it.

The catch-up probe already knew that the credentials must not follow a
redirect, and it strips them for the probe - but the download that
followed was handed the original headers, which undid it. The headers are
now filtered for the host the file actually lives on.

## Ninth pass: the words that are not codes, and the headers that are not headers

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `channel_names.py` | the country-code variants were matched as free words, and a few of them are ordinary English | "Car SOS" and "You Can Do It" were tagged Canadian, and the channel then looked for a Canadian guide |
| SEVERE | `catchup_direct.py` | the channel's custom headers travel in `_extra`, and the catch-up probe sent that list as one header named `_extra` | the provider never saw the custom headers, so the probe was refused and the direct file was never found - and the list, which can carry a secret, went out under a name nobody asked for |
| MINOR | `stream_proxy.py` | a live upstream that answered with an HTTP error was reopened like a drop | a refused session was reopened for ever, holding ffmpeg and the provider's stream slot with nothing reported |

The codes still work where a code is meant: a leading or parenthesised
code in capitals ("CAN TV", "(CA) News") and the spelled-out names
("CANADA TV", "USA News"). "Fox USA" is still American.

## Tenth pass: the words, the lock and the MPV handshake

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `channel_names.py` | "car" was a strip tag, so "Car SOS" and "SOS" canonicalised to the same name | the guide of one and the playlist of the other matched to each other, and the wrong programme showed |
| SEVERE | `playlist.py` | the import lock was reclaimed after two hours whatever the owner was doing, and the release removed whichever lock was there | a long import and a second one ran at once, and the second one deleted the first one's lock |
| SEVERE | `mpv_subtitle_adapter.py` | the transport had no read lock, and the reader thread and a request's inline pump both read the pipe | two readers split a message between them, the JSON failed to parse and the message was lost |
| MINOR | `main.py` | Enter on a hierarchy-only category expanded it and then pulled the focus to the channel list | a screen-reader user browsing the categories lost their place |
| MINOR | `main.py` | the "What's on Now" dialog was not destroyed in a `try/finally` | a dialog that raised left itself allocated and parent-owned |
| MINOR | `mpv_subtitle_adapter.py` | the version check gated the whole session, and the launch budget was 1.5 s plus 1 s | a slow mpv cost the user their subtitles entirely - the session was dropped and the plain handoff used instead |

The adapter now observes before it asks anything, asks the version on a
worker and only logs it, and gives a cold mpv more time to answer. It also
stops forcing a window when the caller asked for no video: mpv stops
answering its own IPC while it tries to open a window it cannot.

## Eleventh pass: the credential that went stale

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| MINOR | `stream_proxy.py` | a re-issued URL with refreshed headers only touched the running converter, so the ffmpeg kept the credentials it started with | a provider that rotates its session cookie refused the old one, and the channel did not play until the converter was retired - up to a minute, for no visible reason |

The converter is replaced when the headers change and kept when they do
not, so re-issuing the same URL does not restart the transcode.

### Still open: the watchdog and a still video track

The A/V watchdog restarts the stream when **either** track stops
progressing. A radio source whose cover art decodes twice and then freezes
arms the video watchdog, and the player reconnects every ten seconds
while the audio plays perfectly well. The app knows the stream is
audio-only (the attached-picture rule in `media_type.py`), but the player
is not told: `main.py` passes `video_visible` and nothing else. The fix is
to hand the media hint to the player, so an audio-only source never arms
the video watchdog.

## Checked and not a defect

- The next daily or weekly DVR occurrence is advanced through naive local
  time, and the conversion back is symmetric, so a recording keeps its
  wall-clock time across a DST change. Only a recording scheduled inside the
  missing hour itself is off, and that is an edge case.

## Still open

- The MPV IPC endpoint used to reuse a running instance is a fixed, machine-wide
  named pipe, and the URL it carries the provider's user and password - in the
  process list and in the player's own media history. The adapter's own
  endpoint is per session; this one is not.
- `shutdown.exe` returning 0 only means the shutdown was scheduled: an
  application can still veto it afterwards, and the app has already closed by
  then.
- The spoken behaviour of the Cast error box (NVDA reading it, the focus
  returning to the Cast button) is covered by GUI tests only. It still needs
  a real screen reader.
- `updater.TRUSTED_SIGNING_THUMBPRINTS` is empty. A certificate rotation is
  delivered by an update signed with the old certificate that already carries
  the new pin, so there is nothing to fill in until the certificate rotates.
- The variant probe now waits 0.4 s for the manifest and falls back to the
  master playlist when the host is slow. The probe is off by default
  (`internal_player_variant_max_mbps` is 0), and the fallback costs the
  variant selection, not playback.
