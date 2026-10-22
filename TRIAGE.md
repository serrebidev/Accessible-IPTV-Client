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

## Twelfth pass: the watchdog and a still video track

The A/V watchdog restarts the stream when **either** track stops
progressing. A radio source whose cover art decodes twice and then freezes
armed the video watchdog, and the player reconnected every ten seconds
while the audio played perfectly well. The app already knows the stream is
audio-only (the attached-picture rule in `media_type.py`), but the player
was not told: `main.py` passed `video_visible` and nothing else. The media
hint now reaches the player, and an audio-only source never arms the video
watchdog.

## Thirteenth pass: the scheduler, the guide and the playlist

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `dvr.py` | the start-failure handler wrote "failed" over a job the user had canceled, and queued its next daily occurrence | a recording canceled while it was starting came back the next day, and the user was told it had failed |
| SEVERE | `dvr.py` | the schedule write shared the try block of the start, so a schedule that could not be written marked the running recording as failed | ffmpeg kept recording past the end of the window, and the provider's one stream slot stayed held for good |
| SEVERE | `main.py`, `playlist.py` | an import in which every source failed reported success | the box said the programme guide was up to date, and the run was recorded as fresh, so the automatic import skipped its next run |
| SEVERE | `main.py` | a playlist refresh that failed dropped the source's channels and announced "Playlist refreshed" | one provider that was briefly down took the user's playlist with it, with nothing said about it |
| MINOR | `shortcuts.py` | a shortcut read from the config was used without the check the app applies when it writes one | a hand-edited bare key in the config swallowed ordinary typing in the search box |

### A canceled recording that came back

Starting a recording resolves the stream URL and probes the channel, which
takes seconds. A cancel in that window found no recording to stop, so the job
stayed "recording" until the start itself failed - and the failure handler
wrote "failed" over the cancellation and queued the next daily occurrence.
The `mark_finished` path already kept a canceled job canceled; the start
path did not, and it does now.

### A schedule that cannot be written

The DVR schedule is a convenience: the jobs live in memory and the app keeps
working without the file. A write that fails (a full disk, a locked file)
must therefore never change a job's state. It did: the write that records
the running recording's id failed, the failure handler marked the job
"failed" and cleared the id, and the scheduler - which only stops jobs that
are "recording" - never stopped it. The schedule writes are now guarded, and
a write that fails is logged instead of changing anything.

### A guide that loaded nothing

Every EPG source fails on its own and the importer logs it and moves on, so
the import itself never fails. The run used to report success anyway: the
box said the guide was up to date and the run was recorded as a fresh
import, which is what suppresses the next automatic one. The importer now
returns how many guides came in, and a run that imported nothing is a
failure.

### A playlist that vanished

A source that could not be fetched contributed no channels, so its channels
were gone from the list - and the refresh still announced "Playlist
refreshed". A failed source now keeps the channels and the provider session
it had, and the failure is announced instead. A playlist that is one refresh
out of date is better than a playlist that is gone.

### Two guides, one channel id

Two guides that list the same channel id under different names overwrite
each other's schedule: the importer deletes a channel's programmes when the
stored name differs, which is how a renumbered channel loses the old
schedule. The last imported source wins, so that id's guide is always one
provider's. Telling the two apart needs the source recorded per programme,
which the database does not do.

## Fourteenth pass: the exit, the guide, the player and the portal

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `main.py` | the exit gate asked about a scheduled recording or about a running download, never both | a scheduled recording hid the download warning, so the download was truncated without the user ever being asked |
| SEVERE | `casting.py` | the Sonos and Kodi paths started the receiver without checking whether the cast had been stopped | a speaker played a channel the user had already stopped, and the audio proxy held the provider's one connection |
| SEVERE | `external_player.py` | launching another player left the application-owned MPV running | the old channel kept playing next to the new one |
| SEVERE | `external_player.py` | the MPV adapter worker had no launch generation | the adapter's handshake took seconds, and when it failed afterwards the plain handoff started the old channel over the new one |
| SEVERE | `vod.py` | a null entry in the provider's JSON was read as a dictionary | one bad row dropped every movie (or every series) in the catalogue |
| SEVERE | `main.py` | the programme-match index was built on the GUI thread when a programme was played or scheduled from "What's on Now" | the app froze for seconds, silent to the screen reader, on a full playlist |
| MINOR | `providers.py` | a portal reply with a null "js" was read as a dictionary | "'NoneType' object has no attribute 'get'" instead of a provider message |
| MINOR | `account_info.py` | the expiry line was printed even when the server had rejected the password | a dead account was reported as "Expires: Never" |
| MINOR | `recorder.py` | "stopped by the user" was set before the process was checked | a download that had already finished was deleted when the user pressed Cancel |
| MINOR | `main.py` | the EPG Manager dialog was destroyed only after the save | a save that raised left the dialog allocated and parent-owned |
| MINOR | `main.py` | an empty Video on Demand catalogue was only an unselected row | the view looked empty with nothing said about it |
| MINOR | `main.py` | a playlist reload accepted the Video on Demand catalogue that was being built | the old playlist's catalogue was shown, including a playlist that was gone |
| MINOR | `subtitle_speech.py` | the automatic speech was checked when the cue arrived, not when it was spoken | a cue queued before the speech was turned off was still spoken |
| MINOR | `main.py` | the application voice was never purged | a caption line kept talking after the user switched channel or stopped playback |

### Two warnings for two things

The exit gate asked about the scheduled recordings or about the running
download, never both: the download warning was in the branch that the
recording warning took. A scheduled recording therefore hid the download, and
the download was truncated without the user ever being asked. Each kind of
work now gets its own warning, and each can be refused on its own.

### A cast that started after the stop

The Sonos and Kodi paths probe the stream before they start the receiver,
and the probe takes as long as the provider answers. The other receivers
check whether the cast is still wanted after their probe; these two did not,
so a stop during the probe was accepted and the speaker started anyway. They
carry the launch generation now and refuse to start a cast that was stopped.

### Two players at once

The application-owned MPV - the one the subtitle adapter drives - was only
closed when another adapter launch replaced it. Launching VLC left it
playing the previous channel. Every launch that is not the adapter's own
closes it now.

The adapter's handshake takes as long as MPV answers, and the worker that
waits for it had no idea whether a newer launch had been asked for in the
meantime: when the handshake failed afterwards, the plain handoff started
the old channel over the new one. Every launch carries a generation now,
and a superseded launch neither installs its player nor hands off.

### One bad row, one whole catalogue

The provider's JSON is untrusted input. A null entry in the category list or
in the stream list was read as a dictionary, and the exception took the
whole section with it - the user saw "No Video on Demand content found".
A null row is skipped now, like the broken numbers the earlier passes
already handled.

### An index on the GUI thread

Playing or scheduling a programme from "What's on Now" resolves its channel
in the playlist. That lookup is an index over every channel, and building it
takes seconds on a full playlist - the app froze and the screen reader said
nothing. The index is built in the worker now, before the dialog appears,
like the EPG search already does.

## Fifteenth pass: the token, the signature, the guide and the proxy

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `updater.py` | the request that carries the GitHub token followed a redirect to any host | the user's own GitHub credential went to whatever host the (unsigned) manifest named |
| SEVERE | `tools/release.py` | the release published the assets before the signature was checked, and the installer's certificate was never compared with the pinned one | a wrongly signed release was public before the check failed, and an installer signed with another certificate would be refused by every installed client |
| SEVERE | `playlist.py` | the importer read the children of a namespaced feed without the namespace | every channel came in without a name and every programme without a title, and the next import overwrote the good ones with the blanks |
| SEVERE | `internal_player.py` | the cue timer was not stopped when the player was torn down | the timer asked a released libVLC for the subtitle position: a native crash, not an exception Python can catch |
| SEVERE | `internal_player.py` | the chosen audio track was re-applied by name only | a provider that renamed its tracks left the stream on its default track while the status line still claimed the chosen one |
| SEVERE | `internal_player.py` | the audio-track choice was disabled while it had the focus | the player was left with no focus at all, and the tracks came back a moment later |
| SEVERE | `stream_proxy.py` | the proxy's handler threads were ordinary threads | the app did not go away while a cast was playing: the interpreter joined the streaming handlers |
| MINOR | `stream_proxy.py` | a stalled upstream killed the gateway handler instead of answering | the receiver saw an empty reply instead of a 502 |
| MINOR | `stream_proxy.py` | a drive-relative segment name was accepted | a client with the cast token could name a file beside the application |
| MINOR | `playlist.py` | a programme that gave its length in hours was dropped | the end time could not be computed, so the programme never reached the database |
| MINOR | `main.py` | the scheduled-recordings dialog was re-centred after every context menu | the window moved under the user each time they opened the menu |

### The token and the redirect

The token in the environment is the user's own GitHub credential, and the
release manifest travels unsigned, so the token only went to a GitHub host.
urllib copies a request's headers into the redirected request, so a manifest
URL on GitHub that answered with a redirect took the credential with it. The
updater follows redirects through its own handler now, and the credential
stays behind when the redirect leaves GitHub.

### The signature, before the release

The cloud workflow published the release - and marked it the latest - and
only then checked the signature. A wrongly signed artifact was already
public when the check failed, and nothing took it back. The release driver
checks the signature itself now, before it commits, pushes or publishes, and
it checks the installer against the same certificate the updater pins: an
installer signed with another one is refused by every installed client.

### A guide in a namespace

Some feeds carry a default namespace. ElementTree keeps the namespace in the
tag, so the importer's plain lookups found nothing: every channel came in
without a name, every programme without a title, and the next import
overwrote the good names with the blanks. The lookups take any namespace now.
A programme that gives its length in hours - a unit XMLTV allows - was
dropped for the same kind of reason: the end time could not be computed, so
it never reached the database.

### The player, the tracks and the focus

The cue timer asks libVLC for the subtitle position. It was not stopped
when the player was torn down, so it could call a player that was being
released: a native crash, and not an exception Python can catch.

The chosen audio track was re-applied by name after a reconnect. The
provider's track names drift between connections - the slot usually does
not - so a rename left the stream on its default track while the status
line still claimed the one the user had chosen. The slot is used when the
name no longer matches, and the label follows the name the provider now
uses.

The audio-track choice is disabled while libVLC has not published the track
list yet. Disabling the focused control leaves the player with no focus at
all, and the screen reader says nothing until the user finds the window
again. The focus moves to the next control instead.

### The proxy that would not let the app go

The proxy's handler threads stream for as long as the receiver listens. As
ordinary threads they were joined when the server closed and when the
interpreter exited, so the app stayed alive - with its window gone - for as
long as a cast was playing. They are daemon threads now. A provider that
stalled while its playlist was being read also killed the handler with an
unhandled error, and the receiver saw an empty reply; it gets a 502 now.

## Sixteenth pass: the lookup that read the whole playlist

This pass started from evidence rather than from reading code: the
provider's own 66 MB playlist and the app's parsed copy of it on this
machine, 257,280 channels, and the timings the app's own code produces on
that data.

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `main.py` | resolving a programme to a playlist channel scanned every channel in the playlist | half a second of frozen window and silence for every row the user highlighted in the EPG search - 23 seconds for one page of results |
| SEVERE | `main.py` | the index those lookups need was built on the GUI thread | the first lookup after a playlist load froze the app for seconds |

### What the measurements said

On the playlist this machine has (257,280 channels):

| | before | after |
|---|---|---|
| one lookup of a programme that matches | 491 ms | 0.021 ms |
| one page of 50 EPG search results | 23 s | 0.03 s |
| the index build | 12.9 s | 12.9 s, off the GUI thread |

The answers did not change: 360 lookups - exact, fuzzy and guide-style -
returned the same channel as the scan they replaced, on all 257,280
channels.

### Why the scan was there

The match rules are a scoring list: an exact tvg-id (100), an exact name
(90), the same canonical name (70), the same name without its quality tag
(60), a substring (40) and a word in common (at most 30). The first four
are equality rules, and an equality rule is a dictionary lookup. Only the
last two need every channel, and they score so low that they cannot beat a
strong match.

So the index now carries a table per equality rule, and the scan runs only
when nothing matched strongly - the case where the answer is a guess anyway.
The tie-break is the same as the scan's: the first channel wins.

The index itself covers every channel in the playlist, and building it took
thelve seconds with a cold name cache, so it is built on a worker when the
playlist changes instead of on the GUI thread when the user highlights
something.

### What the data said that was right

The same pass checked the rest of the playlist against the app's own
output: all 257,280 channels keep their name, group, tvg-id, tvg-name,
logo and URL, and a channel whose display name contains a comma (the
provider ships "24/7: Trapper John, M.D.") is split at the right comma.
The 1,391 channel names that share a canonical name are mostly the same
channel in two spellings ("Sky Sports F1 HD" and "Sky Sports F1 4K"), and
the guide names the channel once, so the first match is the right answer.

## Seventeenth pass: what the app leaves behind

This pass started from the machine's own leftovers: the temp folders the app
and its test suite had accumulated, the crash dumps, the firewall rules, and
the app's own log - the only record of what the installed build actually
did.

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| SEVERE | `stream_proxy.py`, `main.py` | nothing stopped the cast proxy when the app quit | the FFmpeg that transcodes a cast outlived the app: it kept the provider's stream slot, kept writing segments into its temp folder, and the firewall rule it added stayed behind |
| SEVERE | `playlist.py` | a read-only open of the guide that does not exist yet failed | "Failed to fetch EPG data: unable to open database file" in "What's on Now", and a traceback in the log on every refresh until the first import |

### The proxy that was never stopped

The proxy is created on demand and lives for the life of the process. Its
converters are FFmpeg child processes, and the only thing that stopped them
was the proxy's own cleanup loop, which runs every ten seconds - so an app
that quit while a cast was running left the FFmpeg behind. Nothing called
`stop()`: not the exit path, not the caster, not the shutdown.

The proxy is stopped when the app quits now, which ends the FFmpeg
processes, removes their temp folders and takes the firewall rule with them.

### The guide that did not exist yet

The app's own log, from the first run of the installed build:

```
[DEBUG] EPG.ui: IPTVClient._refresh_now_playing_labels: ignored exception
  File "main.py", line 2201, in _refresh_now_playing_labels
  File "playlist.py", line 1364, in __init__
  File "playlist.py", line 1371, in _open
sqlite3.OperationalError: unable to open database file
```

Every view of the guide opens the database read-only, and SQLite refuses a
read-only open of a file that does not exist. Before the first import there
is no file, so "What's on Now" answered with that raw message and the
now-playing refresh logged the traceback on every tick.

There is no guide yet - that is not an error. A missing guide is now an
empty guide: the read-only open falls back to an empty database, so the views
say what they mean ("No programs are currently airing, or EPG data has not
been imported yet") and the log stays quiet.

### What the leftovers said that was right

The test suite had left 34 `iptv_remux_*` folders in the temp directory,
one per converter it started and never stopped. The two tests that started
a converter now stop it, and the folders go with them.

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
- Quitting while a recording is still finalizing waits for the container on
  the GUI thread, so the window is "Not Responding" for the length of that
  wait (minutes for a large faststart MP4). The wait has to stay there: the
  ffmpeg that is finalizing has to be gone before the app exits, or it
  outlives us and holds the provider's stream slot. The window has to stay
  alive while it waits.
- A portable update that installs but does not start leaves no rollback: the
  helper deletes the backup before it restarts the app, because the recursive
  delete competed with the freshly started app's own file loading. Putting
  the delete after the restart would keep the backup, but a rollback also
  needs a message of its own in every language, and the result file is
  written before the restart (the app reports the update within
  milliseconds of showing its window), so it would still say "completed".
- The Authenticode pin covers the executable and the installer, not the rest
  of the portable archive: the hash of the zip comes from the same unsigned
  manifest, so a tampered DLL beside the signed exe would install. The pin
  for the archive would have to come from outside the release, the way the
  certificate pin does.
