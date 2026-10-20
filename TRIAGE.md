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

Every fix has a regression test that fails without it.

## Checked and not a defect

- The next daily or weekly DVR occurrence is advanced through naive local
  time, and the conversion back is symmetric, so a recording keeps its
  wall-clock time across a DST change. Only a recording scheduled inside the
  missing hour itself is off, and that is an edge case.

## Still open

- The "is the EPG database usable" check runs on the GUI thread and its query
  cannot use an index on `end`: on a 2 million programme guide that is a
  multi-second freeze. The index is a schema change, so it wants its own
  migration and a schema version bump.
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
